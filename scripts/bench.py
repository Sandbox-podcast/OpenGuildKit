"""Time the CLI commands that run most often, and print the times as a table and as JSON.

    python scripts/bench.py [--repeat N] [--dependencies FILES] [--json]

Each command runs as a real process, as an agent or a hook runs it, in projects
built in a temporary folder: the request status example (guard off), the same
project with 500 tasks of which 5 are approved (guard enforce), that project
again inside a Git repository whose commit the approvals record, a web project
whose node_modules holds FILES files (50 000 by default), and a monorepo of 200
packages. Python caches the bytecode in that folder, as an installed package
does, even when PYTHONDONTWRITEBYTECODE is set. The time of each command is the
median of N runs; "x start" divides it by the time of openguildkit --version,
so the figure stays comparable between a fast laptop and a slow CI runner.
tests/test_performance.py runs the same measures with budgets, with a smaller
node_modules: the walk never enters it, which a test checks on its own.
"""

import argparse
import contextlib
import io
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))

from openguildkit.cli import main as openguildkit_main  # noqa: E402 - INTENTIONAL(#522): after sys.path is set above
from openguildkit.storage import write_json  # noqa: E402 - INTENTIONAL(#522): after sys.path is set above

EXAMPLE = ROOT / "examples" / "request-status"
TASK = "request-status"
TASKS = 500
APPROVED = 5
PACKAGES = 200
DEPENDENCY_FILES = 50_000
BUG_BRIEF = ("The status page crashes: `renderStatus()` returns the wrong label in src/app.ts and `missingHelper()` "
             "is never called.")
GIT_IDENTITY = ("-c", "user.name=Bench", "-c", "user.email=bench@example.test", "-c", "commit.gpgsign=false")
ENV = {
    **{key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"},
    "PYTHONPATH": os.pathsep.join(filter(None, [str(SOURCE), os.environ.get("PYTHONPATH")])),
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


def cli(project: Path, *args, stdin: str = "") -> float:
    """Run one command and return its wall time in seconds; a failure stops the benchmark."""
    command = [sys.executable, "-m", "openguildkit", "--project", str(project), *map(str, args)]
    started = time.perf_counter()
    result = subprocess.run(command, input=stdin, capture_output=True, text=True, encoding="utf-8", env=ENV,
                            timeout=600)
    elapsed = time.perf_counter() - started
    if result.returncode not in (0, 2) or (result.returncode == 2 and args[:1] != ("guard",)):
        raise RuntimeError(f"openguildkit {' '.join(map(str, args))} failed: {result.stderr}")
    return elapsed


def interpreter() -> float:
    """Wall time of a bare interpreter start, the floor under every command."""
    started = time.perf_counter()
    subprocess.run([sys.executable, "-c", "pass"], check=True, env=ENV, timeout=600)
    return time.perf_counter() - started


def example_project(folder: Path, guard: str = "off") -> Path:
    folder.mkdir(parents=True)
    profile = {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": guard}
    write_json(folder / "profile.json", profile)
    cli(folder, "init", "--answers", folder / "profile.json")
    return folder


def in_process(project: Path, *args, typed: str | None = None) -> str:
    """Run one command in this process, typing at a terminal when typed is given; return its output."""
    stdout = io.StringIO()
    terminal = patch("sys.stdin.isatty", return_value=True) if typed else contextlib.nullcontext()
    answer = patch("builtins.input", return_value=typed) if typed else contextlib.nullcontext()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()), terminal, answer:
        code = openguildkit_main(["--project", str(project), *map(str, args)])
    if code:
        raise RuntimeError(f"openguildkit {' '.join(map(str, args))} failed")
    return stdout.getvalue()


def approve(project: Path, task_id: str) -> None:
    """Consult the example task, record the example review and approve it, as a person at a terminal does."""
    in_process(project, "task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
    in_process(project, "task", "consult", task_id, "--answers", EXAMPLE / "answers.json")
    template = json.loads(in_process(project, "task", "template", task_id))
    review = {"consultation_id": template["consultation_id"],
              **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
    write_json(project / "review.json", review)
    in_process(project, "task", "review", task_id, "--file", project / "review.json")
    in_process(project, "task", "decide", task_id, "--approve", "--by", "Camille Example", "--reason", "Agreed",
               typed=task_id)


def git(project: Path, *args) -> None:
    subprocess.run(["git", "-C", str(project), *GIT_IDENTITY, *args], check=True, capture_output=True, timeout=600)


def many_tasks(folder: Path, in_git: bool = False) -> Path:
    """The example project with TASKS records: APPROVED approved, then drafts and consulted copies by halves.

    In a Git repository, each approval records the commit, and every edit hook checks that it is still in the history.
    """
    project = example_project(folder, guard="enforce")
    if in_git:
        git(project, "init", "-q")
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("print('app')\n", encoding="utf-8")
        git(project, "add", "-A")
        git(project, "commit", "-qm", "Start")
    for index in range(APPROVED):
        approve(project, f"approved-{index}")
    cli(project, "task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
    cli(project, "task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
    tasks = project / ".openguildkit" / "tasks"
    consulted = json.loads((tasks / f"{TASK}.json").read_text(encoding="utf-8"))
    draft = {key: consulted[key] for key in ("schema_version", "brief", "created_at")}
    for index in range(TASKS - APPROVED - 1):
        task_id = f"task-{index:04d}"
        record = {**consulted, "id": task_id} if index % 2 else {**draft, "id": task_id, "status": "draft", "rounds": []}
        write_json(tasks / f"{task_id}.json", record)
    return project


def web_project(folder: Path, dependencies: int) -> Path:
    """The example project with a front end and a node_modules of that many files, as npm install leaves it."""
    project = example_project(folder)
    (project / "src").mkdir()
    (project / "src" / "app.ts").write_text("export function renderStatus() { return 'open'; }\n", encoding="utf-8")
    for index in range(dependencies):
        package = project / "node_modules" / f"pkg-{index // 50:04d}" / "lib"
        package.mkdir(parents=True, exist_ok=True)
        (package / f"file-{index % 50}.js").write_text("module.exports = {};\n", encoding="utf-8")
    answers = json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8"))
    write_json(project / "bug-answers.json", {**answers, "kind": "bug"})
    return project


def monorepo(folder: Path) -> Path:
    """PACKAGES packages over three levels, each with a manifest and a few source files."""
    folder.mkdir(parents=True)
    for index in range(PACKAGES):
        package = folder / ("apps" if index % 2 else "packages") / f"group-{index % 10}" / f"pkg-{index:03d}"
        (package / "src").mkdir(parents=True)
        if index % 3:
            (package / "package.json").write_text(json.dumps({
                "name": f"pkg-{index}", "dependencies": {"react": "^18.3.1", "next": "14.2.0"},
                "devDependencies": {"typescript": "5.6.3", "vitest": "2.1.0"}}), encoding="utf-8")
        else:
            (package / "pyproject.toml").write_text(
                f'[project]\nname = "pkg-{index}"\ndependencies = ["fastapi>=0.110", "psycopg>=3.1"]\n', encoding="utf-8")
        for name in ("index.ts", "util.ts", "README.md"):
            (package / "src" / name).write_text("export {};\n", encoding="utf-8")
        (package / "node_modules" / "ignored").mkdir(parents=True)
    return folder


def edit_hook(project: Path) -> str:
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(project),
                       "tool_input": {"file_path": str(project / "src" / "app.py")}})


def scenarios(base: Path, dependencies: int = DEPENDENCY_FILES) -> list[tuple[str, callable]]:
    """(name, run) pairs; each run returns the wall time of one command."""
    plain = example_project(base / "plain")
    big = many_tasks(base / "many-tasks")
    in_git = many_tasks(base / "many-tasks-git", in_git=True)
    web = web_project(base / "web", dependencies)
    repo = monorepo(base / "monorepo")
    counter = iter(range(10 ** 6))

    def fresh_init():
        folder = base / "init" / str(next(counter))
        folder.mkdir(parents=True)
        return cli(folder, "init", "--answers", EXAMPLE / "profile.json")

    def consult():
        task_id = f"consult-{next(counter)}"
        cli(plain, "task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
        return cli(plain, "task", "consult", task_id, "--answers", EXAMPLE / "answers.json")

    def consult_bug():
        task_id = f"bug-{next(counter)}"
        cli(web, "task", "new", BUG_BRIEF, "--id", task_id)
        return cli(web, "task", "consult", task_id, "--answers", web / "bug-answers.json")

    def init_monorepo():
        shutil.rmtree(repo / ".openguildkit", ignore_errors=True)
        for name in ("AGENTS.md", "CLAUDE.md"):
            (repo / name).unlink(missing_ok=True)
        return cli(repo, "init", "--answers", EXAMPLE / "profile.json")

    return [
        ("python -c pass", interpreter),
        ("start (--version)", lambda: cli(plain, "--version")),
        ("catalog --json", lambda: cli(plain, "catalog", "--json")),
        ("init", fresh_init),
        ("task consult", consult),
        ("task consult, bug, with node_modules", consult_bug),
        (f"task list ({TASKS} tasks)", lambda: cli(big, "task", "list")),
        (f"check ({TASKS} tasks)", lambda: cli(big, "check")),
        ("references search", lambda: cli(plain, "references", "security")),
        (f"guard --hook pre-edit ({TASKS} tasks)", lambda: cli(big, "guard", "--hook", "pre-edit", stdin=edit_hook(big))),
        (f"guard --hook pre-edit (Git, {APPROVED} approvals)",
         lambda: cli(in_git, "guard", "--hook", "pre-edit", stdin=edit_hook(in_git))),
        ("guard --hook pre-edit, guard off", lambda: cli(plain, "guard", "--hook", "pre-edit", stdin=edit_hook(plain))),
        (f"guard --hook prompt ({TASKS} tasks)", lambda: cli(big, "guard", "--hook", "prompt", stdin="{}")),
        (f"detect (monorepo, {PACKAGES} packages)", lambda: cli(repo, "detect", "--json")),
        (f"init (monorepo, {PACKAGES} packages)", init_monorepo),
    ]


def measure(repeat: int = 3, dependencies: int = DEPENDENCY_FILES) -> dict:
    """Median seconds per scenario, the runs, and the ratio to the start time."""
    base = Path(tempfile.mkdtemp(prefix="ogk-bench-")).resolve()
    ENV["PYTHONPYCACHEPREFIX"] = str(base / "bytecode")
    try:
        results = {}
        for name, run in scenarios(base, dependencies):
            run()  # warm the file cache and the bytecode
            runs = [run() for _ in range(repeat)]
            results[name] = {"median": statistics.median(runs), "runs": runs}
        start = results["start (--version)"]["median"]
        for item in results.values():
            item["x_start"] = item["median"] / start
        return results
    finally:
        shutil.rmtree(base, ignore_errors=True)


def report(results: dict) -> dict:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(terse=True),
        "results": {name: {"median_s": round(item["median"], 3), "x_start": round(item["x_start"], 1)}
                    for name, item in results.items()},
    }


def table(results: dict) -> str:
    width = max(map(len, results))
    lines = [f"{'command':<{width}}  median s  x start", f"{'-' * width}  --------  -------"]
    lines += [f"{name:<{width}}  {item['median']:8.3f}  {item['x_start']:7.1f}" for name, item in results.items()]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=5, help="Runs per command (default 5).")
    parser.add_argument("--dependencies", type=int, default=DEPENDENCY_FILES,
                        help=f"Files in the web project's node_modules (default {DEPENDENCY_FILES}).")
    parser.add_argument("--json", action="store_true", help="Print only the JSON report.")
    args = parser.parse_args()
    results = measure(args.repeat, args.dependencies)
    if not args.json:
        print(table(results))
        print()
    print(json.dumps(report(results), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
