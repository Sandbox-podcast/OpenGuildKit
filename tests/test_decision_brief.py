"""What the person approving sees: board changes, open points, objections, blockers, verdicts and review warnings."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.storage import write_json
from openguildkit.routing import select_boards
from openguildkit.workflow import validate_review

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


class DecisionBriefTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_access.py").write_text("def test_access(): pass\n", encoding="utf-8")

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def record(self):
        return json.loads(self.run_cli("task", "show", TASK)[0])

    def reviewed(self, *consult_options, answers=None, edit=None):
        """Consult the example task, record the example review for the selected boards, edited by `edit`."""
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        write_json(self.root / "answers.json", {**json.loads((EXAMPLE / "answers.json").read_text()), **(answers or {})})
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json", *consult_options)
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        if edit:
            edit(review)
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")

    def decide(self, *typed, code=0):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=list(typed)):
            return self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", code=code)

    def test_a_removed_board_is_shown_with_its_reason_and_who_asked(self):
        self.reviewed("--remove", "marketing", "--reason", "No launch planned")
        brief, _ = self.run_cli("task", "challenge", TASK)
        self.assertIn("Board removed: marketing", brief)
        self.assertIn("No launch planned", brief)
        self.assertIn("requested by the agent", brief)
        _, prompt = self.decide(TASK)
        self.assertIn("Board removed: marketing", prompt)
        self.assertEqual(self.record()["status"], "approved")

    def test_removing_a_board_routed_for_personal_data_needs_the_person_to_confirm(self):
        self.reviewed("--remove", "security", "--reason", "not needed")
        consultation = self.record()["consultation"]
        self.assertEqual(consultation["adjustments"][0]["confirmation"], "pending")
        brief, _ = self.run_cli("task", "challenge", TASK)
        self.assertIn("Board removed: security", brief)
        self.assertIn("Personal data access", brief)
        self.assertIn("confirm", brief)

        _, error = self.decide(TASK, "yes", code=1)
        self.assertIn("removal of the security board was not confirmed", error)
        self.assertEqual(self.record()["status"], "reviewed")

        _, prompt = self.decide(TASK, "security")
        self.assertIn("Type security to confirm", prompt)
        decision = self.record()["decision"]
        self.assertEqual(decision["confirmed_removals"], ["security"])
        brief, _ = self.run_cli("task", "challenge", TASK)
        self.assertIn("confirmed by Camille", brief)

    def test_the_approval_covers_the_boards_removed_at_consultation(self):
        self.reviewed("--remove", "security", "--reason", "not needed")
        self.decide(TASK, "security")
        self.run_cli("task", "handoff", TASK)
        path = self.root / ".openguildkit" / "tasks" / f"{TASK}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["consultation"]["adjustments"][0]["reason"] = "The requester asked for it"
        path.write_text(json.dumps(record), encoding="utf-8")
        _, error = self.run_cli("task", "handoff", TASK, code=1)
        self.assertIn("no longer matches what was approved", error)
        record["consultation"]["adjustments"] = []
        path.write_text(json.dumps(record), encoding="utf-8")
        _, error = self.run_cli("task", "handoff", TASK, code=1)
        self.assertIn("no longer matches what was approved", error)

    def test_only_a_board_routed_by_sensitive_data_is_protected(self):
        catalog = load_catalog()
        profile = resolved_profile(validate_profile(json.loads((EXAMPLE / "profile.json").read_text()), catalog), catalog)
        task = {"id": "t", "brief": "Export the support requests.", "rounds": []}
        for data, board, pending in (("regulated", "legal", True), ("unsure", "security", True), ("internal", "security", False)):
            answers = {"kind": "feature", "surface": ["customer"], "data": data, "research": "local"}
            selected = select_boards(profile, catalog, task, answers, {"remove": [board], "reason": "Not needed"})
            with self.subTest(data=data):
                self.assertEqual(selected["adjustments"][0].get("confirmation") == "pending", pending)

    def test_the_prompt_starts_with_the_verdicts_and_warns_against_objections(self):
        self.reviewed()
        _, prompt = self.decide(TASK)
        self.assertTrue(prompt.startswith("Verdicts: "), prompt[:200])
        self.assertIn("3 proceed", prompt.splitlines()[0])
        self.assertIn("3 revise", prompt.splitlines()[0])
        self.assertIn("Warning: 4 of 7 boards say revise, block or insufficient-evidence", prompt)
        self.assertIn("Objection not deliberated: security-to-legal", prompt)
        self.assertIn("one of the two boards concedes, or when both amend", prompt)
        self.assertIn("objections not deliberated yet: approving is still possible", prompt)
        self.assertIn("Brief: ", prompt)
        self.assertIn(f"Full decision brief, with each board's evidence: openguildkit task challenge {TASK}", prompt)
        self.assertNotIn('"specialists"', prompt)
        brief, _ = self.run_cli("task", "challenge", TASK)
        self.assertIn("Warning: 4 of 7 boards", brief)
        self.assertIn("Objection not deliberated", brief)

    def test_open_points_are_shown_before_approval(self):
        self.reviewed(answers={"data": "unsure"})
        brief, _ = self.run_cli("task", "challenge", TASK)
        self.assertIn("Open point: The requester is unsure about the most sensitive data.", brief)
        _, prompt = self.decide(TASK)
        self.assertIn("Open point: The requester is unsure about the most sensitive data.", prompt)

    def test_a_cleared_blocker_shows_its_evidence(self):
        def block(review):
            security = next(entry for entry in review["boards"] if entry["id"] == "security")
            security["challenge"].update(verdict="block", blockers=[{
                "finding": "SQL injection risk", "owner": "Security lead", "clears_when": "A test proves inputs are bound."}])
        self.reviewed(edit=block)
        _, error = self.run_cli("task", "clear", TASK, "security:1", "--by", "Alex", "--evidence", "x",
                                "--supports", "y", code=1)
        self.assertIn("https link", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=[TASK]):
            self.run_cli("task", "clear", TASK, "security:1", "--by", "Alex", "--evidence", "tests/test_access.py",
                         "--supports", "Inputs are bound parameters.")
        listing, _ = self.run_cli("task", "blockers", TASK)
        self.assertIn("tests/test_access.py", listing)
        self.assertIn("Inputs are bound parameters.", listing)
        self.assertNotIn("without a terminal", listing)
        _, prompt = self.decide(TASK)
        self.assertIn("Blocker security:1 cleared by Alex", prompt)
        self.assertIn("Evidence: tests/test_access.py", prompt)
        self.assertIn("Supports: Inputs are bound parameters.", prompt)

    def test_a_blocker_cleared_by_the_finished_work_is_a_condition_of_the_approval(self):
        """Issue 159: a blocker that waits for code deadlocked the approval."""
        def block(review):
            security = next(entry for entry in review["boards"] if entry["id"] == "security")
            security["challenge"].update(verdict="block", blockers=[{
                "finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
                "clears_when": "The cross-account test passes.", "phase": "verification"}])
        self.reviewed(edit=block)
        condition = ("Condition of approval security:1, cleared after implementation and before the task completes: "
                     "No test proves a user cannot read another user's request. Clears when: The cross-account test "
                     "passes.")
        brief, _ = self.run_cli("task", "challenge", TASK)
        self.assertIn(condition, brief)
        _, prompt = self.decide(TASK)
        self.assertIn(condition, prompt)
        self.assertEqual(self.record()["status"], "approved")
        handoff, _ = self.run_cli("task", "handoff", TASK)
        self.assertLess(handoff.index("## Conditions of the approval"), handoff.index("## Human approval"))
        self.assertIn("let them clear it in their terminal", handoff)
        _, error = self.run_cli("task", "clear", TASK, "security:1", "--by", "Alex", "--evidence", "tests/test_access.py",
                                "--supports", "The test passes.", code=1)
        self.assertIn("Clearing a blocker is the person's act", error)

    def test_a_copied_review_is_recorded_with_warnings(self):
        (self.root / "api").mkdir()
        (self.root / "api" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

        def copy_everything(review):
            for entry in review["boards"]:
                entry["recommendation"] = "Ship it."
                entry["evidence"] = [{"source": "project-file", "ref": "api/pyproject.toml", "supports": "The stack."}]
                challenge = entry["challenge"]
                challenge.update(verdict="revise", confidence="low", blockers=[])
                for lens in challenge["specialists"]:
                    lens.update(finding="Looks fine.", basis="assumption", evidence_refs=[])
        self.reviewed(edit=copy_everything)
        self.assertEqual(self.record()["status"], "reviewed")
        warnings = self.record()["review"]["warnings"]
        self.assertTrue(any("same recommendation" in warning for warning in warnings), warnings)
        self.assertTrue(any("same finding" in warning for warning in warnings), warnings)
        self.assertTrue(any(warning.startswith("No observed finding from product, engineering") for warning in warnings), warnings)
        brief, _ = self.run_cli("task", "challenge", TASK)
        self.assertIn("Review warning: ", brief)
        _, prompt = self.decide(TASK)
        self.assertIn("Review warning: ", prompt)

    def test_an_independent_review_has_no_warning(self):
        self.reviewed()
        self.assertNotIn("warnings", self.record()["review"])

    def test_warnings_in_a_submitted_review_are_recomputed(self):
        self.reviewed()
        task = self.record()
        review = copy.deepcopy(task["review"])
        review["warnings"] = ["Nothing to see."]
        self.assertNotIn("warnings", validate_review(task["consultation"], review))

    def test_proceed_on_the_requester_word_alone_is_still_refused(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        product = next(entry for entry in review["boards"] if entry["id"] == "product")
        product["evidence"] = [{"source": "requester", "ref": "brief", "supports": "The requester wants it."}]
        for lens in product["challenge"]["specialists"]:
            lens.update(basis="observed", evidence_refs=[1])
        write_json(self.root / "review.json", review)
        _, error = self.run_cli("task", "review", TASK, "--file", self.root / "review.json", code=1)
        self.assertIn("requester's own words", error)


if __name__ == "__main__":
    unittest.main()
