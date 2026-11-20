import unittest

from openguildkit.catalog import load_catalog
from openguildkit.workflow import consult, open_points, task_questions, validate_answers


class AdaptiveQuestionTests(unittest.TestCase):
    def test_follow_ups_depend_on_the_kind_and_impact(self):
        feature = {"kind": "feature", "surface": ["customer", "service"], "data": "personal", "research": "local"}
        ids = [question["id"] for question in task_questions("Export request history.", feature)]
        self.assertIn("outcome", ids)
        self.assertIn("affected", ids)
        decision = {"kind": "decision", "surface": ["business"], "data": "none", "research": "local"}
        ids = [question["id"] for question in task_questions("Choose a billing model.", decision)]
        self.assertIn("options", ids)

    def test_a_well_described_local_bug_gets_no_unrelated_questions(self):
        bug = {
            "kind": "bug", "surface": ["service"], "data": "none", "research": "local",
            "outcome": "The export returns every page; reproduce with 101 rows.",
        }
        brief = "The CSV export of the order service stops after the first 100 rows."
        ids = [question["id"] for question in task_questions(brief, bug)]
        self.assertNotIn("affected", ids)
        self.assertNotIn("options", ids)
        self.assertEqual(open_points(brief, validate_answers(bug)), [])

    def test_a_vague_request_shows_its_open_points(self):
        answers = validate_answers({"kind": "unsure", "surface": "unsure", "data": "unsure", "research": "local"})
        points = open_points("Improve exports", answers)
        self.assertTrue(any("brief is short" in point for point in points))
        self.assertTrue(any("kind of work" in point for point in points))
        self.assertTrue(any("Who is affected" in point for point in points))
        self.assertTrue(any("different once this task is done" in point for point in points))

    def test_a_task_can_declare_several_impacts(self):
        answers = validate_answers({"kind": "feature", "surface": ["customer", "service"], "data": "none", "research": "local"})
        self.assertEqual(answers["surface"], ["customer", "service"])
        self.assertEqual(validate_answers({**answers, "surface": "customer"})["surface"], ["customer"])
        with self.assertRaisesRegex(ValueError, "or unsure"):
            validate_answers({**answers, "surface": ["customer", "unsure"]})
        profile = {"name": "Portal", "sector": "general", "packs": [], "boards": []}
        task = {"id": "t", "brief": "Show the status of each export to its owner.", "answers": answers}
        routing = consult(profile, load_catalog(), task)["routing"]
        self.assertIn("design", routing)
        self.assertIn("performance", routing)

    def test_open_points_reach_the_consultation(self):
        profile = {"name": "Portal", "sector": "general", "packs": [], "boards": []}
        answers = {"kind": "feature", "surface": ["customer"], "data": "none", "research": "local"}
        consultation = consult(profile, load_catalog(), {"id": "t", "brief": "Improve exports", "answers": answers})
        self.assertIn("## Open points", consultation["markdown"])
        self.assertTrue(consultation["scope"]["open_points"])


if __name__ == "__main__":
    unittest.main()
