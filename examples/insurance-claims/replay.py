"""Replay the insurance example from init to handoff.

    python examples/insurance-claims/replay.py [--project DIR]

Without --project, the run uses a new temporary folder. When stdin is a
terminal, the script lets you record the approval yourself and prints the
handoff. Otherwise it stops before the decision, which needs a person.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TASK_ID = "claim-status"
ENV = {
    **os.environ,
    "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
    "PYTHONIOENCODING": "utf-8",
}


def step(title: str) -> None:
    print(f"\n== {title}", flush=True)


def cli(project: Path, *args, capture: bool = False) -> str:
    command = [sys.executable, "-m", "openguildkit", "--project", str(project), *map(str, args)]
    print("$ openguildkit " + " ".join(map(str, args)), flush=True)
    result = subprocess.run(command, env=ENV, text=True, encoding="utf-8", capture_output=capture)
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    return result.stdout if capture else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, help="Empty folder to use as the example project.")
    args = parser.parse_args()

    project = args.project or Path(tempfile.mkdtemp(prefix="openguildkit-claims-"))
    project.mkdir(parents=True, exist_ok=True)
    if any(project.iterdir()):
        sys.exit(f"{project} is not empty. Pick an empty folder.")
    project = project.resolve()
    print(f"Example project: {project}")

    step("1. Set up the project")
    cli(project, "init", "--answers", HERE / "profile.json")

    step("2. Open the task")
    cli(project, "task", "new", "--file", HERE / "brief.md", "--id", TASK_ID)

    step("3. Scope it and consult the boards")
    cli(project, "task", "consult", TASK_ID, "--answers", HERE / "answers.json", capture=True)
    task = json.loads(cli(project, "task", "show", TASK_ID, capture=True))
    for board, reasons in task["consultation"]["routing"].items():
        print(f"  {board:<20} {'; '.join(reasons)}")

    step("4. Record the boards' review")
    template = json.loads(cli(project, "task", "template", TASK_ID, capture=True))
    review = json.loads((HERE / "review.json").read_text(encoding="utf-8"))
    review_path = project / "review.json"
    review_path.write_text(
        json.dumps({"consultation_id": template["consultation_id"], **review}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cli(project, "task", "review", TASK_ID, "--file", review_path)

    step("5. Human decision")
    decide = ["task", "decide", TASK_ID, "--approve", "--by", "NAME", "--reason", "REASON"]

    def manual_steps() -> None:
        print("Approval needs a person at a terminal. Run, in your own terminal:")
        print(f'  openguildkit --project "{project}" task decide {TASK_ID} --approve --by "Your Name" --reason "Scope agreed"')
        print(f'  openguildkit --project "{project}" task handoff {TASK_ID}')

    if not sys.stdin.isatty():
        manual_steps()
        return
    try:
        name = input("Your name for the approval record: ").strip() or "Example reviewer"
    except EOFError:
        # On Windows, a redirect from NUL looks like a terminal but has no input.
        print()
        manual_steps()
        return
    decide[decide.index("NAME")] = name
    decide[decide.index("REASON")] = "Read-only scope agreed in the example"
    cli(project, *decide)

    step("6. Handoff")
    cli(project, "task", "handoff", TASK_ID)


if __name__ == "__main__":
    main()
