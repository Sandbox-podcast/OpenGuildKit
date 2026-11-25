"""Build a sample OpenGuildKit project whose tasks cover every state, to try or test the web interface.

    python web/scripts/sample-project.py DIR
    python web/scripts/sample-project.py DIR --gdpr

DIR must be empty or missing. The project reuses the fictional support portal of examples/request-status.
With --gdpr, the project has the GDPR pattern and one approved task on personal data, whose named evidence
(record of processing activities, DPIA decision) a person provides from the page.
Approvals need a person at a terminal: this script simulates that person for its own fixture tasks only,
the way the CLI's own tests do. Never use it on a real project.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from openguildkit.cli import main  # noqa: E402

EXAMPLE = REPO / "examples" / "request-status"
REVIEW = json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))
# A consultation needs the concerns answer; the example's own answer, when it has one, wins.
ANSWERS = {"concerns": ["none"], **json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8"))}
PASS = f'"{sys.executable}" -c "print(\'ok\')"'


def run(root: Path, *args, code: int = 0, tty_input: str | None = None) -> str:
    out, err = io.StringIO(), io.StringIO()
    argv = ["--project", str(root), *map(str, args)]
    with contextlib.ExitStack() as stack:
        if tty_input is not None:
            stack.enter_context(patch("sys.stdin.isatty", return_value=True))
            stack.enter_context(patch("builtins.input", return_value=tty_input))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        result = main(argv)
    if result != code:
        raise SystemExit(f"openguildkit {' '.join(map(str, args))} -> {result}\n{err.getvalue()}")
    return out.getvalue()


def write(root: Path, name: str, data) -> Path:
    path = root / ".sample" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def review_for(root: Path, task: str, summary: str, blockers: dict | None = None) -> Path:
    template = json.loads(run(root, "task", "template", task))
    wanted = [board["id"] for board in template["boards"]]
    entries = {entry["id"]: json.loads(json.dumps(entry)) for entry in REVIEW["boards"]}
    boards = []
    for board_id in wanted:
        entry = entries[board_id]
        entry["challenge"]["blockers"] = (blockers or {}).get(board_id, [])
        if entry["challenge"]["blockers"]:
            entry["challenge"]["verdict"] = "block"
        boards.append(entry)
    return write(root, f"{task}-review.json", {"consultation_id": template["consultation_id"], "summary": summary, "boards": boards})


def consult(root: Path, task: str, answers: dict) -> None:
    route = json.loads(run(root, "task", "route", task, "--answers", write(root, f"{task}-answers.json", answers), "--json"))
    known = {entry["id"] for entry in REVIEW["boards"]}
    extra = [board for board in route["routing"] if board not in known]
    removes = [item for board in extra for item in ("--remove", board)]
    reason = ["--reason", "The sample review covers six boards."] if removes else []
    run(root, "task", "consult", task, "--answers", root / ".sample" / f"{task}-answers.json", *removes, *reason)


def approve(root: Path, task: str, by: str, reason: str) -> None:
    run(root, "task", "decide", task, "--approve", "--by", by, "--reason", reason, tty_input=task)


def outcomes(root: Path, task: str) -> list[dict]:
    checks = json.loads(run(root, "task", "checks", task, "--json"))
    return [{"check": check["id"], "status": "not-applicable", "reason": "No change in this area.", "owner": "Camille Martin"}
            for check in checks if check["kind"] == "rule"]


def build(root: Path) -> None:
    profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
    profile.update({
        "name": "Portail support",
        "checks": [PASS],
        "tools": ["Brevo", "Notion"],
        "waivers": {"allowed_by": ["Camille Martin"], "max_days": 30},
    })
    run(root, "init", "--answers", write(root, "profile.json", profile))
    (root / ".gitignore").write_text(".sample/\n", encoding="utf-8")

    # 1. Done: approved, verified, reported, completed, documented and shared.
    run(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")
    consult(root, "request-status", ANSWERS)
    run(root, "task", "review", "request-status", "--file", review_for(root, "request-status", REVIEW["summary"]))
    approve(root, "request-status", "Camille Martin", "Read-only scope agreed with support")
    run(root, "task", "verify", "request-status")
    result = {"pull_request": "https://github.com/example/portal/pull/7",
              "criteria": [{"criterion": "Signed-in users only see the requests they opened.", "status": "met",
                            "evidence": "tests/test_access.py"}],
              "checks": outcomes(root, "request-status")}
    run(root, "task", "result", "request-status", "--file", write(root, "request-status-result.json", result))
    run(root, "task", "complete", "request-status")
    run(root, "task", "export", "request-status")
    run(root, "docs", "export", "--tasks", "request-status", "--output", "docs-site", "--version", "1.4.0")
    run(root, "docs", "share", "add", "--deliverable", "docs-site/reference/request-status.md",
        "--recipient", "client@example.org", "--until", "2026-12-31",
        "--portal", "https://docs.example.org/p/support-portal", "--by", "Camille Martin")

    # 2. Approved and handed off: the forge implements it.
    run(root, "task", "new", "Show customers the history of each support request.", "--id", "request-history",
        "--follows", "request-status")
    consult(root, "request-history", {**ANSWERS, "context": "Customers see past status changes of their own requests."})
    run(root, "task", "review", "request-history", "--file", review_for(root, "request-history", REVIEW["summary"]))
    approve(root, "request-history", "Camille Martin", "History follows the agreed read-only scope")
    run(root, "deliverable", "new", "release-announcement", "--task", "request-history", "--tool", "Notion",
        "--output", "marketing/request-history-announcement.md")

    # 3. Reviewed with a blocker: the council has to clear it before a person decides.
    run(root, "task", "new", "Let customers export their requests as a CSV file.", "--id", "request-export")
    consult(root, "request-export", {**ANSWERS, "context": "Customers download their own requests as CSV."})
    blocker = {"security": [{"finding": "The export could include requests of other accounts in the same company.",
                             "owner": "Alex Moreau", "clears_when": "A test proves the export only holds the requester's own requests."}]}
    run(root, "task", "review", "request-export", "--file",
        review_for(root, "request-export", "Proceed once cross-account access is proven impossible.", blocker))

    # Local evidence for the blocker-clearing journey in this fictional project.
    write(root, "request-export-evidence.md", "# Sample export access check\n\n"
          "In the fixture, each of two accounts exported only its own requests.\n")

    # 4. Consulting: two boards have passed, the others are still missing.
    run(root, "task", "new", "Agree on the customer-facing status labels.", "--id", "status-labels")
    consult(root, "status-labels", {**ANSWERS, "kind": "decision", "options": "Keep internal labels, or map them to four customer labels."})
    template = json.loads(run(root, "task", "template", "status-labels"))
    for index, board in enumerate(template["boards"]):
        # Every board's entry is ready in .sample/ for the person or the tests; two are already submitted.
        entry = next(item for item in REVIEW["boards"] if item["id"] == board["id"])
        path = write(root, f"status-labels-{board['id']}.json", entry)
        if index < 2:
            run(root, "task", "pass", "status-labels", board["id"], "--mode", "sequential")
            run(root, "task", "submit", "status-labels", "--file", path)

    # 5. Sent back with changes requested.
    run(root, "task", "new", "Send a satisfaction survey when a request closes.", "--id", "closing-survey")
    consult(root, "closing-survey", {**ANSWERS, "context": "An email survey after each closed request."})
    run(root, "task", "review", "closing-survey", "--file", review_for(root, "closing-survey", REVIEW["summary"]))
    run(root, "task", "decide", "closing-survey", "--request-changes", "--by", "Camille Martin",
        "--reason", "Check consent for survey emails first")

    # 6. Draft: the brief is written, the questions are not answered yet.
    run(root, "task", "new", "Add a dark theme to the customer portal.", "--id", "dark-theme")

    # Dependency alerts, a market dossier, an extracted design system.
    run(root, "alerts", "import", REPO / "tests" / "fixtures" / "alerts" / "npm-audit-critical.json", "--task", "request-history")
    market = root / ".openguildkit" / "market"
    market.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", market / "support-portals.json")
    shutil.copytree(REPO / "examples" / "storybook-extract" / "src", root / "src")
    run(root, "storybook", "extract", "--src", root / "src")
    run(root, "storybook", "propose")


def build_gdpr(root: Path) -> None:
    """A project on personal data with the GDPR pattern, and one approved task on personal data."""
    profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
    profile.update({"name": "Portail RGPD", "checks": [PASS], "patterns": ["gdpr-personal-data"]})
    run(root, "init", "--answers", write(root, "profile.json", profile))
    (root / ".gitignore").write_text(".sample/\n", encoding="utf-8")
    run(root, "task", "new", "Let customers download the data held about them.", "--id", "data-export")
    consult(root, "data-export", {**ANSWERS, "context": "Customers download their own data as a JSON file."})
    run(root, "task", "review", "data-export", "--file", review_for(root, "data-export", REVIEW["summary"]))
    approve(root, "data-export", "Camille Martin", "Export limited to the requester's own data")
    run(root, "task", "verify", "data-export")
    # The documents the evidence owners provide, ready for the page to cite.
    for name in ("records/processing-record.md", "records/dpia-decision.md"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n\nFictional document of the sample project.\n", encoding="utf-8")


def main_() -> None:
    # argparse prints the usage for --help and refuses any other argument that starts with a dash, so that no
    # project is built in a folder named after an option.
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir", metavar="DIR", help="an empty or missing folder")
    parser.add_argument("--gdpr", action="store_true", help="add the GDPR pattern and a task on personal data")
    args = parser.parse_args()
    root = Path(args.dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} is not empty. Pick an empty folder.")
    root.mkdir(parents=True, exist_ok=True)
    (build_gdpr if args.gdpr else build)(root)
    print(f"Sample project ready: {root}\nRun: openguildkit --project \"{root}\" ui")


if __name__ == "__main__":
    main_()
