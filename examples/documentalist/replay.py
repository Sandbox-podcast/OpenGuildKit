"""Replay the documentation export example, from init to docs export.

    python examples/documentalist/replay.py --project DIR

The first run sets up the request status task, records the boards' review and stops at
the decision, which needs a person: in a terminal it asks your name and lets you approve,
otherwise it prints the command to run yourself. Run the script again with the same
--project once the task is approved: it runs the checks, records the result, completes
the task, exports DIR/docs-site and compares it with this folder's docs-site.

The script sets SOURCE_DATE_EPOCH to the example's completion day, so the dated blog page
is the same on any day. The project page is left out: it quotes the catalog's pack rules,
which change between versions, while the task pages depend only on this folder's inputs.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
REQUEST_STATUS = REPO / "examples" / "request-status"
TASK_ID = "request-status"
VERSION = "1.4.0"
SECTIONS = "reference,learn,blog"
COMPLETED = "1795176000"  # 2026-11-20T12:00:00Z, the day docs-site was exported
ENV = {
    **os.environ,
    "SOURCE_DATE_EPOCH": COMPLETED,
    "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
    "PYTHONIOENCODING": "utf-8",
}


def cli(project: Path, *args, capture: bool = False) -> str:
    command = [sys.executable, "-m", "openguildkit", "--project", str(project), *map(str, args)]
    print("$ openguildkit " + " ".join(map(str, args)), flush=True)
    result = subprocess.run(command, env=ENV, text=True, encoding="utf-8", capture_output=capture)
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    return result.stdout if capture else ""


def write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def review(project: Path) -> None:
    """Open the task with this folder's answers and record the request status review."""
    cli(project, "init", "--answers", HERE / "profile.json")
    cli(project, "task", "new", "--file", REQUEST_STATUS / "brief.md", "--id", TASK_ID)
    cli(project, "task", "consult", TASK_ID, "--answers", HERE / "answers.json", capture=True)
    template = json.loads(cli(project, "task", "template", TASK_ID, capture=True))
    recorded = json.loads((REQUEST_STATUS / "review.json").read_text(encoding="utf-8"))
    path = write(project / "review.json", {"consultation_id": template["consultation_id"], **recorded})
    cli(project, "task", "review", TASK_ID, "--file", path)


def decide(project: Path) -> bool:
    """Let a person at a terminal approve; return False when nobody can."""
    command = f'openguildkit --project "{project}" task decide {TASK_ID} --approve --by INITIALS --reason "Scope agreed"'
    if sys.stdin.isatty():
        try:
            name = input("Your initials or team handle for the approval record: ").strip() or "example-reviewer"
        except EOFError:
            name = ""
        if name:
            cli(project, "task", "decide", TASK_ID, "--approve", "--by", name, "--reason", "Read-only scope agreed in the example")
            return True
    print("Approval needs a person. Run, in your own terminal:")
    print(f"  {command}")
    print(f'Then run this script again with --project "{project}".')
    return False


def deliver(project: Path, approver: str) -> None:
    """Run the project check, record this folder's result and complete the task."""
    cli(project, "task", "verify", TASK_ID)
    checks = json.loads(cli(project, "task", "checks", TASK_ID, "--json", capture=True))
    # The example changes no code, so the owner marks each pack rule as not applicable.
    rules = [{"check": item["id"], "status": "not-applicable", "reason": "The example project has no code to check.",
              "owner": approver} for item in checks if item["kind"] == "rule"]
    result = json.loads((HERE / "result.json").read_text(encoding="utf-8"))
    path = write(project / "result.json", {**result, "checks": [*result["checks"], *rules]})
    cli(project, "task", "result", TASK_ID, "--file", path)
    cli(project, "task", "complete", TASK_ID)


def _files(folder: Path) -> dict[str, bytes]:
    """Each file of a folder with Windows line endings folded: a checkout may have converted them."""
    return {path.relative_to(folder).as_posix(): path.read_bytes().replace(b"\r\n", b"\n")
            for path in folder.rglob("*") if path.is_file()}


def compare(left: Path, right: Path) -> list[str]:
    """Paths that differ between two folders, or exist in only one of them."""
    ours, theirs = _files(left), _files(right)
    return sorted(name for name in ours.keys() | theirs.keys() if ours.get(name) != theirs.get(name))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, required=True, help="Empty folder for the first run, the same folder after.")
    project = parser.parse_args().project
    project.mkdir(parents=True, exist_ok=True)
    project = project.resolve()
    if not (project / ".openguildkit").is_dir():
        if any(project.iterdir()):
            sys.exit(f"{project} is not empty. Pick an empty folder.")
        review(project)
    task = json.loads(cli(project, "task", "show", TASK_ID, capture=True))
    if task["status"] not in ("approved", "done") and not decide(project):
        return
    task = json.loads(cli(project, "task", "show", TASK_ID, capture=True))
    if task["status"] == "approved":
        deliver(project, task["decision"]["by"])
    cli(project, "docs", "export", "--tasks", TASK_ID, "--output", "docs-site", "--version", VERSION, "--sections", SECTIONS)
    differences = compare(project / "docs-site", HERE / "docs-site")
    if not differences:
        print(f"{project / 'docs-site'} is identical to examples/documentalist/docs-site.")
        return
    print("Differences with examples/documentalist/docs-site:")
    for path in differences:
        print(f"  {path}")


if __name__ == "__main__":
    main()
