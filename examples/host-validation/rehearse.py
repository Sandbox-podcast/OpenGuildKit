"""Rehearse the host validation scenario with the CLI alone, as a host without subagents would.

    python examples/host-validation/rehearse.py [--project DIR] [--report FILE]

It copies the fictional project, runs both tasks through every step with prepared board
answers (one pass at a time), and writes a report of what it observed. The approval step
uses a pseudo-terminal on Linux and macOS, as a person would; elsewhere the script stops
before the decision. No network, no real customer data, no keys.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
# Bytecode goes to a folder of its own, not next to the sources, and is reused from one command to the next.
ENV = {**{key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"},
       "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
       "PYTHONPYCACHEPREFIX": os.environ.get("PYTHONPYCACHEPREFIX") or str(Path(tempfile.gettempdir()) / "openguildkit-pycache"),
       "PYTHONIOENCODING": "utf-8"}


def run(project: Path, *args: str) -> subprocess.CompletedProcess:
    """openguildkit on the project, its output captured. The tests run it in their own process."""
    return subprocess.run([sys.executable, "-m", "openguildkit", "--project", str(project), *args],
                          env=ENV, text=True, encoding="utf-8", capture_output=True)


def cli(project: Path, *args, check: bool = True) -> subprocess.CompletedProcess:
    result = run(project, *map(str, args))
    if check and result.returncode:
        raise SystemExit(f"openguildkit {' '.join(map(str, args))} failed:\n{result.stderr}")
    return result


def approve(project: Path, task_id: str, *, by: str = "Validation owner",
            reason: str = "Scenario decision", signature: Path | None = None, signer: str | None = None) -> bool:
    """Forward a person's signature, or replay the local approval in the validation scenario."""
    args = ("task", "decide", task_id, "--approve", "--by", by, "--reason", reason)
    if (signature is None) != (signer is None):
        raise ValueError("Pass both the approval signature and its signer.")
    if signature is not None:
        return cli(project, *args, "--signature", signature, "--signer", signer, check=False).returncode == 0
    return in_terminal(project, args, task_id)


def in_terminal(project: Path, args: tuple, typed: str) -> bool:
    """Replay a person's command at a terminal, typing the confirmation; a person's act needs a terminal."""
    if os.name != "posix":
        return False
    import pty

    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "openguildkit", "--project", str(project), *map(str, args)],
        stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV)
    os.close(slave)
    os.write(master, f"{typed}\n".encode())
    process.communicate(timeout=60)
    os.close(master)
    return process.returncode == 0


def evidence(ref: str, supports: str, source: str = "project-file") -> dict:
    return {"source": source, "ref": ref, "supports": supports}


def entry(template: dict, verdict: str, recommendation: str, items: list[dict], basis: str = "observed",
          blockers: list[dict] | None = None) -> dict:
    confidence = "low" if verdict == "insufficient-evidence" else "medium"
    challenge = template["challenge"]
    for lens in challenge["specialists"]:
        observed = basis == "observed" and items
        lens.update(finding=f"{lens['id']}: {recommendation}", basis="observed" if observed else "missing",
                    evidence_refs=[1] if observed else [])
    challenge.update(verdict=verdict, confidence=confidence, alternative="Keep the current behaviour for one more release.",
                     failure_mode="A customer sees a request that belongs to someone else.",
                     verification="Run the ownership test with two synthetic accounts.", blockers=blockers or [])
    return {**template, "recommendation": recommendation, "evidence": items, "open_questions": []}


def run_feature(project: Path, observed: dict) -> None:
    task = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))[0]
    cli(project, "task", "new", task["brief"], "--id", task["id"])
    (project / "answers.json").write_text(json.dumps(task["answers"]), encoding="utf-8")
    cli(project, "task", "consult", task["id"], "--answers", project / "answers.json")
    record = json.loads(cli(project, "task", "show", task["id"]).stdout)
    boards = record["consultation"]["boards"]
    observed["feature_boards"] = boards
    templates = {item["id"]: item for item in record["consultation"]["review_template"]["boards"]}
    code = evidence("project/app.py", "requests_for filters requests by owner.")
    test = evidence("project/test_app.py", "A test checks that a user only sees their own requests.", "test")
    for board in boards:
        brief = cli(project, "task", "pass", task["id"], board, "--mode", "sequential").stdout
        observed.setdefault("briefs_scoped", []).append(f"# Board pass: {board}" in brief and "## Board brief" in brief
                                                        and '"packs"' not in brief)
        if board == "security":
            blocker = {"finding": "The export has no rate limit, and the acceptance criteria set no cap per account.", "owner": "Security lead",
                       "clears_when": "The export endpoint is limited per account."}
            item = entry(templates[board], "revise", "Add a per-account limit before exporting.", [code, test], blockers=[blocker])
        else:
            item = entry(templates[board], "proceed", "Ship the export for the requests a user owns.", [code, test])
        (project / f"{board}.json").write_text(json.dumps(item), encoding="utf-8")
        cli(project, "task", "submit", task["id"], "--file", project / f"{board}.json")
    progress = json.loads(cli(project, "task", "progress", task["id"], "--json").stdout)
    observed["passes_done"] = all(item["status"] == "done" and item["mode"] == "sequential" for item in progress)
    cli(project, "task", "review", task["id"], "--summary", "Product would ship; Security asks for a rate limit first.")
    request = json.loads(cli(project, "task", "deliberate", task["id"]).stdout)
    observed["objections"] = [item["id"] for item in request["objections"]]
    payload = request["template"]
    for response in payload["responses"]:
        response.update(position="maintain", response="Our first review still holds.", evidence_refs=[1])
    payload["decision_needed"] = "Ship now with monitoring, or wait for the rate limit."
    (project / "deliberation.json").write_text(json.dumps(payload), encoding="utf-8")
    observed["deliberation"] = cli(project, "task", "respond", task["id"], "--file", project / "deliberation.json").stdout.strip()
    observed["agent_cannot_clear"] = cli(
        project, "task", "clear", task["id"], "security:1", "--evidence", "project/app.py",
        "--supports", "Limit added in the rehearsal", "--by", "Validation owner", check=False).returncode == 1
    observed["cleared"] = in_terminal(project, ("task", "clear", task["id"], "security:1", "--evidence", "project/app.py",
                                                "--supports", "Limit added in the rehearsal", "--by",
                                                "Validation owner"), task["id"])
    observed["approved"] = approve(project, task["id"])
    if not observed["approved"]:
        return
    cli(project, "task", "handoff", task["id"])
    cli(project, "task", "verify", task["id"])
    checks = json.loads(cli(project, "task", "checks", task["id"], "--json").stdout)
    result = {"revision": "rehearsal", "criteria": [{"criterion": task["answers"]["outcome"], "status": "met",
                                                       "evidence": "project/test_app.py"}],
              "checks": [{"check": item["id"], "status": "not-applicable", "reason": "No rule pack in the scenario.",
                          "owner": "Validation owner"} for item in checks if item["kind"] == "rule"]}
    (project / "result.json").write_text(json.dumps(result), encoding="utf-8")
    cli(project, "task", "result", task["id"], "--file", project / "result.json")
    done = cli(project, "task", "complete", task["id"], check=False)
    observed["completed"] = done.returncode == 0
    observed["completion_message"] = (done.stdout or done.stderr).strip()


def run_decision(project: Path, observed: dict) -> None:
    task = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))[1]
    cli(project, "task", "new", task["brief"], "--id", task["id"])
    (project / "answers2.json").write_text(json.dumps(task["answers"]), encoding="utf-8")
    cli(project, "task", "consult", task["id"], "--answers", project / "answers2.json", "--add", "marketing",
        "--reason", "A pricing comparison is a market question")
    record = json.loads(cli(project, "task", "show", task["id"]).stdout)
    templates = {item["id"]: item for item in record["consultation"]["review_template"]["boards"]}
    for board in record["consultation"]["boards"]:
        cli(project, "task", "pass", task["id"], board, "--mode", "sequential")
        item = entry(templates[board], "insufficient-evidence", "Collect competitor pricing before deciding.", [], basis="missing")
        (project / f"d-{board}.json").write_text(json.dumps(item), encoding="utf-8")
        cli(project, "task", "submit", task["id"], "--file", project / f"d-{board}.json")
    cli(project, "task", "review", task["id"], "--summary", "No market evidence was provided.")
    brief = cli(project, "task", "challenge", task["id"]).stdout
    observed["insufficient_evidence"] = '"insufficient-evidence"' in brief


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, help="Empty folder for the rehearsal.")
    parser.add_argument("--report", type=Path, help="Write the observations as JSON.")
    args = parser.parse_args()
    project = (args.project or Path(tempfile.mkdtemp(prefix="ogk-host-validation-"))).resolve()
    project.mkdir(parents=True, exist_ok=True)
    shutil.copytree(HERE / "project", project / "project", dirs_exist_ok=True)
    profile = json.loads((HERE / "profile.json").read_text(encoding="utf-8"))
    # Run the project's check with this interpreter: "python" may not be on the PATH.
    profile["checks"] = [check.replace("python ", f'"{sys.executable}" ', 1) for check in profile["checks"]]
    (project / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    cli(project, "init", "--answers", project / "profile.json")
    observed = {"host": "CLI rehearsal without subagents", "project": str(project)}
    run_feature(project, observed)
    run_decision(project, observed)
    text = json.dumps(observed, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
