"""Run the tests the module map attaches to files changed since a base revision, within a time budget.

    python scripts/check_fast.py [--base REF] [--budget SECONDS | --all] [--jobs N]
    python scripts/check_fast.py --plan [PATH | "COMMAND" ...]

REF defaults to origin/main. Changed files are the tracked diff against that revision, working tree included, plus
untracked files. Everything comes from docs/agents/map.json: a module of the package takes its tests; another file
or folder (scripts, documentation, workflows, fixtures, web/, integrations/ci/, the catalog under
src/openguildkit/registry/) takes the tests and commands of its `paths` entry, the longest folder first. A changed
test file runs itself. A changed file with no attached test is named, and the command exits 1.

Each test file runs in its own process, several at once (scripts/run_tests.py): the test named after a changed
module first, then the tests that name it, the shortest files first. The first failure stops the run and is printed
first. Past the budget (30 s), nothing more starts and the files left are named on standard error; --all runs them
all. Success is one line. --plan prints what would run, with the role and entry points of a module or the function of
a command, and runs nothing.
"""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - INTENTIONAL(#520): the one line an older Python gets
    raise SystemExit(f"OpenGuildKit needs Python 3.11 or later; this is Python {sys.version_info[0]}.{sys.version_info[1]}. "
                     "Run it with python3.11 or newer.")

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_tests  # The runner next to this script, once its folder is on the path (#456).

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs" / "agents" / "map.json"
BUDGET = 30.0
# The commands a paths entry may name, as (folder, command, what it checks).
COMMANDS = {
    "catalog": (".", None, "validate the catalog"),
    "web-typecheck": ("web", ["run", "typecheck"], "typecheck web/"),
    "web-test": ("web", ["test"], "test web/"),
    "node-tests": ("integrations/ci", ["test"], "test integrations/ci/"),
}


def plan(changed: list[str], module_map: dict) -> dict:
    """The tests and commands a set of changed paths needs, and the paths no test covers."""
    by_module = {item["module"]: item for item in module_map["modules"]}
    by_path = {item["path"]: item for item in module_map.get("paths", [])}
    folders = sorted((path for path in by_path if path.endswith("/")), key=len, reverse=True)
    tests, commands, unattached = [], [], []

    def add_tests(paths: list[str]) -> bool:
        available = [path for path in paths if (ROOT / path).is_file()]
        for path in available:
            if path not in tests:
                tests.append(path)
        return bool(available)

    for path in changed:
        name = path.rsplit("/", 1)[-1]
        if path.startswith("tests/") and path.endswith(".py") and name.startswith("test_"):
            if (ROOT / path).is_file():
                add_tests([path])
            continue
        item = by_module.get(path)
        if item:
            if not add_tests(item["tests"]):
                unattached.append(path)
            continue
        covered = False
        for entry in module_map["modules"]:
            if any(path.startswith(prefix) for prefix in entry.get("covers", [])):
                covered = add_tests(entry["tests"]) or covered
        if covered:
            continue
        entry = by_path.get(path) or next((by_path[folder] for folder in folders if path.startswith(folder)), None)
        found = add_tests(entry.get("tests", [])) if entry else False
        for command in entry.get("commands", []) if entry else []:
            if command not in commands:
                commands.append(command)
            found = True
        if not found:
            unattached.append(path)
    return {"tests": tests, "commands": commands, "unattached": unattached}


def ordered(tests: list[str], changed: list[str], root: Path = ROOT) -> list[str]:
    """The test named after a changed module first, then the tests that name a changed module, the shortest first."""
    stems = [Path(path).stem for path in changed if path.startswith("src/openguildkit/") and path.endswith(".py")]

    def rank(test: str) -> tuple[int, int]:
        if any(Path(test).name == f"test_{stem}.py" for stem in stems):
            return 0, 0
        text = (root / test).read_text(encoding="utf-8")
        named = any(f"openguildkit.{stem}" in text or f"import {stem}" in text for stem in stems)
        return (1 if named else 2), (root / test).stat().st_size

    return sorted(tests, key=rank)


def _git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "git failed")
    return [line for line in result.stdout.splitlines() if line]


def changed_files(root: Path, base: str) -> list[str]:
    """Tracked changes since base, including the working tree, and untracked files."""
    known = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"],
                           capture_output=True, text=True, check=False)
    if known.returncode:
        raise SystemExit(f"check_fast: unknown base revision {base}: run git fetch origin main, or pass --base HEAD.")
    tracked = _git_lines(root, "diff", "--name-only", "--no-renames", base)
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard")
    found = []
    for path in [*tracked, *untracked]:
        if path not in found:
            found.append(path)
    return found


def describe(arguments: list[str], module_map: dict, selected: dict) -> str:
    """What --plan prints: each named module or command, then the tests and commands that would run."""
    lines = []
    modules = {item["module"]: item for item in module_map["modules"]}
    commands = {item["command"]: item for item in module_map.get("commands", [])}
    for argument in arguments:
        if argument in modules:
            item = modules[argument]
            lines += [f"{argument}: {item['role']}", f"  entry: {', '.join(item['entry'])}", f"  doc: {item['doc']}"]
        elif argument in commands:
            item = commands[argument]
            lines.append(f"{argument}: {item['module']}:{item['line']} {item['function']}")
    short = [Path(test).stem for test in selected["tests"]]
    lines.append(f"tests ({len(short)}): {' '.join(short) or 'none'}")
    if selected["commands"]:
        lines.append(f"commands: {' '.join(selected['commands'])}")
    if selected["unattached"]:
        lines.append(f"no test attached: {' '.join(selected['unattached'])}")
    return "\n".join(lines)


def _command(name: str) -> tuple[bool, str]:
    """Run one command of COMMANDS; (passed, output to show when it failed)."""
    folder, npm_arguments, what = COMMANDS[name]
    if npm_arguments is None:
        command = [sys.executable, "-m", "openguildkit", "catalog", "--json"]
    else:
        npm = shutil.which("npm")
        if npm is None:
            return False, f"npm is not on PATH, so check_fast cannot {what}."
        command = [npm, *npm_arguments]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    result = subprocess.run(command, cwd=ROOT / folder, env=env, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return True, ""
    output = (result.stderr or result.stdout[-4000:]) if npm_arguments is None else result.stdout + result.stderr
    shown = f"npm {' '.join(npm_arguments)}" if npm_arguments else "openguildkit catalog"
    return False, f"===== {shown} failed ({what})\n{output.rstrip()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the tests attached to files changed since a base revision.")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--plan", nargs="*", metavar="PATH", help="print what would run, for these paths or commands "
                                                                   "(default: the changed files), and run nothing")
    parser.add_argument("--budget", type=float, default=BUDGET, help="start nothing after so many seconds (default 30)")
    parser.add_argument("--all", action="store_true", help="run every selected test, whatever the budget")
    parser.add_argument("--jobs", type=int, default=run_tests.default_jobs(), help="test files at once")
    args = parser.parse_args(argv)
    module_map = json.loads(MAP.read_text(encoding="utf-8"))
    if args.plan:
        commands = {item["command"] for item in module_map.get("commands", [])}
        named = [item["module"] for item in module_map.get("commands", []) if item["command"] in args.plan]
        paths = [argument for argument in args.plan if argument not in commands] + named
        print(describe(args.plan, module_map, plan(paths, module_map)))
        return 0
    changed = changed_files(ROOT, args.base)
    if args.plan is not None:
        print(describe([], module_map, plan(changed, module_map)))
        return 0
    if not changed:
        print(f"check_fast: no changes since {args.base}.")
        return 0
    selected = plan(changed, module_map)
    tests = ordered(selected["tests"], changed)
    started = time.monotonic()
    print(f"check_fast: {len(tests)} test file(s) and {len(selected['commands'])} command(s), "
          f"{args.jobs} at once: ", end="", flush=True)
    failures = []
    for name in selected["commands"]:
        passed, output = _command(name)
        if not passed:
            failures.append(output)
    result = run_tests.run(tests, args.jobs, stop_on_failure=True,
                           deadline=None if args.all else started + args.budget) if tests else None
    if result:
        failures = [f"===== {path} failed\n{output.rstrip()}" for path, output in result["failed"]] + failures
    seconds = time.monotonic() - started
    if failures or selected["unattached"]:
        print(f"failed in {seconds:.1f} s.")
        for output in failures:
            print(output + "\n")
        if selected["unattached"]:
            print("check_fast: no test is attached to:\n" + "\n".join(f"- {path}" for path in selected["unattached"]))
        return 1
    left = (result["stopped"] + result["not_run"]) if result else []
    print(f"{result['tests'] if result else 0} tests passed in {seconds:.1f} s.", flush=True)
    if left:
        print(f"Warning: check_fast: {len(left)} test file(s) not run within the {args.budget:g} s budget "
              f"(--all runs them): {' '.join(Path(path).stem for path in left)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
