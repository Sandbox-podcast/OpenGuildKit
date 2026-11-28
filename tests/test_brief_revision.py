"""A change request can lead to a revised brief, and the next round recalls the decision that sent it back."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.storage import write_json
from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "weekly-digest"
BRIEF = "Email parents a weekly summary with the grades in the email body"
REVISED = "Email parents a weekly link to the grades page, with no grade in the email"


class BriefRevisionTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "School portal", "stack": ["Python"], "packs": [], "checks": [command]})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", BRIEF, "--id", TASK)

    def consult_and_review(self, *extra):
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json", *extra)
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = json.loads((EXAMPLE / "review.json").read_text())
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"], **review})
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")

    def consult_and_review_again(self):
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = json.loads((EXAMPLE / "review.json").read_text())
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"], **review})
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")

    def test_the_brief_is_revised_at_the_new_consultation_and_the_earlier_one_kept(self):
        self.consult_and_review()
        self.run_cli("task", "decide", TASK, "--request-changes", "--by", "Dana Legal", "--reason", "No grade in an email")
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json", "--brief", "   ", code=1)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json", "--brief", REVISED)
        task = json.loads(self.run_cli("task", "show", TASK)[0])
        self.assertEqual(task["brief"], REVISED)
        self.assertEqual(task["consultation"]["scope"]["brief"], REVISED)
        self.assertEqual(task["rounds"][0]["brief"], BRIEF)
        self.assertIn(REVISED, self.run_cli("task", "list")[0])
        self.consult_and_review_again()
        self.run_cli("task", "decide", TASK, "--approve", "--by", "Sam Owner", "--reason", "Link only", typed=TASK)
        record = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertEqual((record["brief"], record["rounds"][0]["brief"]), (REVISED, BRIEF))

    def test_the_second_round_recalls_the_first_decision_and_its_reason(self):
        self.consult_and_review()
        self.assertNotIn("Round", self.run_cli("task", "challenge", TASK)[0].splitlines()[0])
        self.run_cli("task", "decide", TASK, "--request-changes", "--by", "Dana Legal", "--reason", "No grade in an email")
        self.consult_and_review("--brief", REVISED)
        first = self.run_cli("task", "challenge", TASK)[0].splitlines()[0]
        self.assertRegex(first, r"^Round 2\. Round 1: changes requested by Dana Legal on \d{4}-\d{2}-\d{2}: "
                                r"No grade in an email\. The brief was revised since\.$")
        prompt = self.run_cli("task", "decide", TASK, "--approve", "--by", "SO", "--reason", "Link only",
                              typed=TASK)[1]
        self.assertIn("Round 1: changes requested by Dana Legal", prompt.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
