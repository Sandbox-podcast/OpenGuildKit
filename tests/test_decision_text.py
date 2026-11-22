"""What the person reads before deciding: one text for the prompt, task challenge and task decision-payload
(issue #206): the check commands and their changes, the signed payload in clear, advice copied across boards."""

import json
import shutil
import subprocess
import unittest

from openguildkit.decisions import decision_payload, payload_text, seal
from openguildkit.storage import read_json, write_json
from tests.test_approval_lifecycle import EXAMPLE, ApprovalCase

PRINCIPAL = "camille@example.test"


def copied_review(template: dict, ref: str) -> dict:
    """One paragraph written once and pasted into every board with its name swapped, each finding citing one file."""
    boards = []
    for board in template["boards"]:
        name = board["id"]
        entry = {"id": name, "recommendation": f"{name}: proceed with a CSV export of the timesheets.",
                 "evidence": [{"source": "project-file", "ref": ref, "supports": f"{name}: the view returns the export."}],
                 "open_questions": []}
        if "challenge" in board:
            entry["challenge"] = {
                "specialists": [{"id": lens["id"], "finding": f"{name}: the export view returns the requested rows.",
                                 "basis": "observed", "evidence_refs": [1]} for lens in board["challenge"]["specialists"]],
                "verdict": "proceed", "confidence": "medium", "alternative": f"{name}: none needed.",
                "failure_mode": f"{name}: none seen.", "verification": f"{name}: run the export once.", "blockers": []}
        if "reviewer" in board:
            entry["reviewer"] = "Alex Moreau"
        boards.append(entry)
    return {"consultation_id": template["consultation_id"], "summary": "Every board agrees: proceed.", "boards": boards}


class CheckCommandTests(ApprovalCase):
    def test_the_prompt_and_challenge_list_the_commands_and_those_changed_since_the_last_approval(self):
        self.init()
        first = read_json(self.state / "project.json")["checks"][0]
        self.approve("t1")
        added = f"{first} > ran-after-approval.txt"
        self.run_cli("profile", "add", "check", added, "--by", "Someone", "--reason", "one more check")
        self.run_cli("profile", "remove", "check", first, "--by", "Sam", "--reason", "too slow", typed=first)
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "t2")
        self.run_cli("task", "consult", "t2", "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", "t2")[0])
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", "t2", "--file", self.root / "review.json")
        day = self.task("t1")["decision"]["at"][:10]
        expected = [
            f"Check command command:1, which task verify runs as a shell command in the project root: `{added}`",
            f"Check command added since the last approval of the project (t1 on {day}): `{added}` (add check by "
            f"Someone on {day}: one more check).",
            f"Check command removed since the last approval of the project (t1 on {day}): `{first}` (remove check by "
            f"Sam on {day}: too slow).",
        ]
        challenge = self.run_cli("task", "challenge", "t2")[0]
        _, prompt = self.run_cli("task", "decide", "t2", "--approve", "--by", "Camille", "--reason", "Agreed", typed="t2")
        for line in expected:
            self.assertIn(f"- {line}\n", challenge)
            self.assertIn(f"{line}\n", prompt)


@unittest.skipIf(shutil.which("ssh-keygen") is None, "needs ssh-keygen")
class SignedDecisionTests(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.key = self.copies / "synthetic-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key)], check=True)
        self.init(approval={"mode": "signed", "allowed_signers": "allowed_signers", "approvers": [PRINCIPAL]})
        (self.root / "allowed_signers").write_text(
            f"{PRINCIPAL} {self.key.with_suffix('.pub').read_text(encoding='utf-8')}", encoding="utf-8")
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "sx")
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", "sx", "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", "sx")[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"].update(verdict="block", blockers=[{
            "finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
            "clears_when": "An automated test with two synthetic accounts passes.", "phase": "verification"}])
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", "sx", "--file", self.root / "review.json")

    def sign(self, path):
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(self.key), "-n", "openguildkit-decision", str(path)],
                       check=True)
        return path.with_suffix(".json.sig")

    def test_the_payload_shows_the_prompt_and_carries_the_brief_and_summary_in_clear(self):
        payload = self.root / "decision.json"
        _, shown = self.run_cli("task", "decision-payload", "sx", "--by", "Camille Martin", "--reason", "Agreed",
                                "--output", payload)
        data = json.loads(payload.read_text(encoding="utf-8"))
        task = self.task("sx")
        self.assertEqual((data["brief"], data["summary"]), (task["brief"], task["review"]["summary"]))
        self.assertIn("Verdicts:", shown)
        self.assertIn("Condition of approval security:1", shown)
        self.assertIn("Check command command:1, which task verify runs", shown)
        signature = self.sign(payload)
        output, prompt = self.run_cli("task", "decide", "sx", "--approve", "--by", "Camille Martin", "--reason",
                                      "Agreed", "--signature", signature, "--signer", PRINCIPAL)
        self.assertEqual(output, "approved\n")
        self.assertEqual(prompt, shown)

    def test_an_approval_signed_over_the_earlier_payload_still_verifies(self):
        task = self.task("sx")
        payload = decision_payload(task, "Camille Martin", "Agreed", None, version=2)
        self.assertNotIn("brief", payload)
        earlier = self.root / "earlier.json"
        earlier.write_bytes(payload_text(payload).encode("utf-8"))
        task.update(status="approved", decision={
            "outcome": "approved", "by": "Camille Martin", "reason": "Agreed", "at": "2026-11-22T10:00:00+00:00",
            "base_revision": None, "seal": seal(payload), "signer": PRINCIPAL,
            "signature": self.sign(earlier).read_text(encoding="utf-8")})
        write_json(self.state / "tasks" / "sx.json", task)
        self.assertIn("Approved task handoff", self.run_cli("task", "handoff", "sx")[0])

    def test_decide_and_clear_record_the_person_named_by_by_and_the_verified_signer(self):
        payload = self.root / "decision.json"
        self.run_cli("task", "decision-payload", "sx", "--by", "Camille Martin", "--reason", "Agreed", "--output", payload)
        self.run_cli("task", "decide", "sx", "--approve", "--by", "Camille Martin", "--reason", "Agreed",
                     "--signature", self.sign(payload), "--signer", PRINCIPAL)
        clear = ["task", "clear", "sx", "security:1", "--by", "Camille Martin", "--evidence", "README.md",
                 "--supports", "Two synthetic accounts are tested."]
        clearance = self.root / "clearance.json"
        self.run_cli(*clear, "--payload", clearance)
        self.run_cli(*clear, "--signature", self.sign(clearance), "--signer", PRINCIPAL)
        task = self.task("sx")
        cleared = task["verification_blocker_resolutions"]["security:1"]
        self.assertEqual((task["decision"]["by"], task["decision"]["signer"]), ("Camille Martin", PRINCIPAL))
        self.assertEqual((cleared["by"], cleared["signer"]), ("Camille Martin", PRINCIPAL))


class CopiedAdviceTests(ApprovalCase):
    """Eight boards filled with one paragraph whose board name is swapped, each finding citing one two-line file."""

    def setUp(self):
        super().setUp()
        self.init()
        (self.root / "api" / "app").mkdir(parents=True)
        (self.root / "api" / "app" / "views.py").write_text("def timesheet_export(request):\n    return []\n",
                                                            encoding="utf-8")
        self.run_cli("task", "new", "Export each employee's timesheets as a CSV file.", "--id", "timesheet-export")
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", "timesheet-export", "--answers", self.root / "answers.json",
                     "--add", "data", "--reason", "Timesheets are personal data")
        self.template = json.loads(self.run_cli("task", "template", "timesheet-export")[0])
        self.assertEqual(len(self.template["boards"]), 8)
        self.review = copied_review(self.template, "api/app/views.py")

    def test_the_eight_copied_reviews_are_flagged_at_review_in_challenge_and_at_the_prompt(self):
        write_json(self.root / "review.json", self.review)
        _, warned = self.run_cli("task", "review", "timesheet-export", "--file", self.root / "review.json")
        challenge = self.run_cli("task", "challenge", "timesheet-export")[0]
        _, prompt = self.run_cli("task", "decide", "timesheet-export", "--approve", "--by", "Camille", "--reason",
                                 "Agreed", code=1, typed="no")
        boards = ", ".join(board["id"] for board in self.template["boards"][:6]) + " and 2 more"
        for text in (f"Boards {boards} give the same recommendation word for word, once each board's name is taken out.",
                     "once each board's name is taken out: product: the export view returns the requested rows.",
                     "Every finding of a board cites one and the same evidence item: product (its evidence #1), "):
            self.assertIn(text, warned)
            self.assertIn(text, challenge)
            self.assertIn(text, prompt)
        self.assertIn("Verdicts: 8 proceed.", challenge)

    def test_a_submitted_pass_that_copies_an_earlier_one_is_flagged(self):
        entries = {entry["id"]: entry for entry in self.review["boards"]}
        for board in ("product", "engineering"):
            self.run_cli("task", "pass", "timesheet-export", board)
            write_json(self.root / f"{board}.json", entries[board])
            _, warned = self.run_cli("task", "submit", "timesheet-export", "--file", self.root / f"{board}.json")
        self.assertIn("Warning: Boards product, engineering give the same recommendation word for word", warned)
        self.assertIn("Warning: The same finding appears in", warned)


if __name__ == "__main__":
    unittest.main()
