"""Working assumptions at scoping (#436): the answers keep them apart from the confirmed facts, every board pass reads
them and can contest one, and the person reads them apart, contested first, before deciding."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.questionnaire import task_questions, validate_answers
from openguildkit.storage import write_json

from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
BASE = {"kind": "bug", "surface": ["service"], "data": "none", "research": "local", "concerns": ["none"]}
ASSUMED = ["Requests are linked to accounts by the customer ID.", "Support agents keep their current view."]


class AssumptionAnswerTests(unittest.TestCase):
    def test_assumptions_are_kept_as_a_list_of_sentences(self):
        validated = validate_answers({**BASE, "assumptions": ["  One link per account. ", "Labels stay in English."]})
        self.assertEqual(validated["assumptions"], ["One link per account.", "Labels stay in English."])

    def test_a_wrong_type_is_refused_with_what_to_write(self):
        for value in ("One link per account.", [1], ["ok", ""], {"a": "b"}, [["nested"]]):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                validate_answers({**BASE, "assumptions": value})
            self.assertIn("assumptions must be a list of sentences", str(error.exception))

    def test_answers_without_assumptions_read_as_before(self):
        self.assertEqual(validate_answers(BASE), validate_answers({**BASE, "assumptions": []}))
        self.assertNotIn("assumptions", validate_answers(BASE))

    def test_the_follow_ups_recall_assumptions_while_the_outcome_or_who_is_affected_is_empty(self):
        asked = [question["id"] for question in task_questions("Fix the export", BASE)]
        self.assertIn("assumptions", asked)
        answered = [question["id"] for question in task_questions("Fix the export", {**BASE, "outcome": "It works."})]
        self.assertNotIn("assumptions", answered)
        question = next(item for item in task_questions("Fix the export", BASE) if item["id"] == "assumptions")
        self.assertEqual(question["type"], "list")
        self.assertFalse(question["essential"])


class AssumptionFlowTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)

    def consult(self, assumptions=None):
        answers = json.loads((EXAMPLE / "answers.json").read_text())
        if assumptions is not None:
            answers["assumptions"] = assumptions
        write_json(self.root / "answers.json", answers)
        return self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")[0]

    def review(self, edit=None, code=0):
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        if edit:
            edit(review)
        write_json(self.root / "review.json", review)
        return self.run_cli("task", "review", TASK, "--file", self.root / "review.json", code=code)

    def test_questions_recall_assumptions_in_the_follow_ups(self):
        write_json(self.root / "first.json", BASE)
        listed = json.loads(self.run_cli("task", "questions", TASK, "--answers", self.root / "first.json",
                                         "--follow-ups")[0])
        self.assertIn("assumptions", [item["id"] for item in listed["follow_ups"]])

    def test_the_consultation_and_each_pass_show_the_assumptions_and_how_to_contest_one(self):
        consultation = self.consult(ASSUMED)
        self.assertIn("Assumptions not confirmed (2)", consultation)
        self.assertIn("1. Requests are linked to accounts by the customer ID.", consultation)
        board = json.loads(self.run_cli("task", "show", TASK)[0])["consultation"]["boards"][0]
        brief = self.run_cli("task", "pass", TASK, board)[0]
        self.assertIn("2. Support agents keep their current view.", brief)
        self.assertIn('"contested_assumptions"', brief)

    def test_a_contested_assumption_comes_first_in_the_decision_brief_and_the_approval_prompt(self):
        self.consult(ASSUMED)

        def contest(review):
            review["boards"][0]["contested_assumptions"] = [
                {"assumption": 2, "reason": "The support team asked for a new view in the brief."}]
        self.review(contest)
        contester = json.loads(self.run_cli("task", "show", TASK)[0])["review"]["boards"][0]["id"]
        brief = self.run_cli("task", "challenge", TASK)[0]
        self.assertIn("Assumptions not confirmed (2)", brief)
        contested = brief.index(f"Assumption 2, contested by {contester}: Support agents keep their current view.")
        self.assertLess(contested, brief.index("Assumption 1: Requests are linked"))
        report = json.loads(brief.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        self.assertEqual(report["assumptions"][0]["contested"][0]["board"], contester)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=[TASK]):
            _, prompt = self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        self.assertLess(prompt.index("Assumptions not confirmed (2)"), prompt.index(f"Type {TASK} to approve"))

    def test_a_board_entry_must_point_to_a_listed_assumption(self):
        self.consult(ASSUMED)

        def wrong(review):
            review["boards"][0]["contested_assumptions"] = [{"assumption": 3, "reason": "No."}]
        _, error = self.review(wrong, code=1)
        self.assertIn("contested_assumptions[1].assumption", error)
        self.assertIn("1 to 2", error)

    def test_a_task_without_assumptions_reads_as_before(self):
        consultation = self.consult()
        self.assertNotIn("Assumption", consultation)
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        self.assertTrue(all("contested_assumptions" not in entry for entry in template["boards"]))

        def contest(review):
            review["boards"][0]["contested_assumptions"] = [{"assumption": 1, "reason": "No."}]
        _, error = self.review(contest, code=1)
        self.assertIn("unknown contested_assumptions", error)
        self.review()
        brief = self.run_cli("task", "challenge", TASK)[0]
        self.assertNotIn("Assumption", brief)


if __name__ == "__main__":
    unittest.main()
