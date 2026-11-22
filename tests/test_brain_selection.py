import unittest

from openguildkit.catalog import load_catalog
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.consultation import consult
from openguildkit.questionnaire import validate_answers
from openguildkit.routing import select_boards
from openguildkit.workflow import validate_review


class BrainSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def setUp(self):
        self.answers = validate_answers({"kind": "feature", "surface": ["customer"], "data": "none", "research": "local"})
        self.task = {"id": "t", "brief": "Show the status of each export to its owner.", "answers": self.answers}

    def profile(self, **extra):
        return resolved_profile(validate_profile({"name": "Portal", **extra}, self.catalog), self.catalog)

    def test_preview_lists_proposed_boards_with_their_reasons(self):
        selected = select_boards(self.profile(), self.catalog, self.task, self.answers)
        self.assertIn("Customer experience", selected["routing"]["design"])
        self.assertEqual(selected["adjustments"], [])

    def test_the_requester_adds_or_removes_a_board_with_a_reason(self):
        selection = {"add": ["finance"], "remove": ["marketing"], "reason": "Exports are billed per page."}
        consultation = consult(self.profile(), self.catalog, self.task, selection)
        self.assertIn("finance", consultation["boards"])
        self.assertNotIn("marketing", consultation["boards"])
        self.assertEqual(
            consultation["adjustments"],
            [{"action": "add", "board": "finance", "reason": "Exports are billed per page."},
             {"action": "remove", "board": "marketing", "reason": "Exports are billed per page."}],
        )
        with self.assertRaisesRegex(ValueError, "--reason"):
            select_boards(self.profile(), self.catalog, self.task, self.answers, {"remove": ["marketing"]})

    def test_required_boards_are_added_and_cannot_be_removed(self):
        profile = self.profile(required_boards=["security"])
        selected = select_boards(profile, self.catalog, self.task, self.answers)
        self.assertEqual(selected["routing"]["security"], ["Required by the project"])
        with self.assertRaisesRegex(ValueError, "cannot be removed"):
            select_boards(profile, self.catalog, self.task, self.answers, {"remove": ["security"], "reason": "x"})

    def test_an_unavailable_required_board_needs_a_named_reviewer(self):
        profile = self.profile(boards=["product", "design"], required_boards=["security"])
        with self.assertRaisesRegex(ValueError, "Required reviews are unavailable: security"):
            consult(profile, self.catalog, self.task)
        consultation = consult(profile, self.catalog, self.task, {"delegate": {"security": "Alex Moreau"}})
        self.assertEqual(consultation["delegations"], {"security": "Alex Moreau"})
        self.assertIn("Alex Moreau reviews for this board", consultation["markdown"])
        template = consultation["review_template"]
        entry = next(item for item in template["boards"] if item["id"] == "security")
        self.assertEqual(entry["reviewer"], "Alex Moreau")
        template["summary"] = "Agreed."
        for item in template["boards"]:
            item.update(recommendation="Proceed with a read-only scope.", evidence=[{"source": "project-file", "ref": "docs/scope.md", "supports": "Read-only scope."}])
            for lens in item["challenge"]["specialists"]:
                lens.update(finding="The scope is read-only.", basis="observed", evidence_refs=[1])
            item["challenge"].update(verdict="revise", confidence="medium", alternative="Wait.",
                                     failure_mode="A leak.", verification="Test it.")
        self.assertEqual(validate_review(consultation, template)["boards"][-1]["reviewer"], "Alex Moreau")
        entry["reviewer"] = " "
        with self.assertRaisesRegex(ValueError, "reviewer"):
            validate_review(consultation, template)

    def test_unknown_or_disabled_boards_are_refused(self):
        profile = self.profile(boards=["product", "design"])
        with self.assertRaisesRegex(ValueError, "not enabled"):
            select_boards(profile, self.catalog, self.task, self.answers, {"add": ["finance"], "reason": "x"})
        with self.assertRaisesRegex(ValueError, "Only a required board"):
            select_boards(profile, self.catalog, self.task, self.answers, {"delegate": {"finance": "Sam"}})


if __name__ == "__main__":
    unittest.main()
