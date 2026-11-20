import copy
import json
import unittest
import unittest.mock
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.tasks import record_deliberation, record_review
from openguildkit.workflow import challenge_report, consult, deliberation_request

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"


class DeliberationTests(unittest.TestCase):
    def setUp(self):
        catalog = load_catalog()
        profile = resolved_profile(validate_profile(json.loads((EXAMPLE / "profile.json").read_text()), catalog), catalog)
        answers = json.loads((EXAMPLE / "answers.json").read_text())
        task = {"id": "request-status", "brief": (EXAMPLE / "brief.md").read_text(), "answers": answers,
                "status": "consulting", "rounds": []}
        consultation = consult(profile, catalog, task)
        review = {"consultation_id": consultation["id"], **json.loads((EXAMPLE / "review.json").read_text())}
        self.task = record_review({**task, "consultation": consultation}, review)

    def responses(self):
        request = deliberation_request(self.task)
        payload = copy.deepcopy(request["template"])
        for response in payload["responses"]:
            response.update(position="maintain", response="Our evidence still holds.", evidence_refs=[1])
        return request, payload

    def test_first_opinions_stay_and_both_boards_answer_the_same_point(self):
        request, payload = self.responses()
        ids = [item["id"] for item in request["objections"]]
        self.assertIn("security-to-product", ids)
        item = next(item for item in request["objections"] if item["id"] == "security-to-product")
        self.assertTrue(item["point"])
        self.assertTrue(item["from_position"].startswith("revise"))
        boards = {r["board"] for r in payload["responses"] if r["objection"] == "security-to-product"}
        self.assertEqual(boards, {"security", "product"})
        with self.assertRaisesRegex(ValueError, "decision the responsible person"):
            record_deliberation(self.task, payload)
        payload["decision_needed"] = "Choose between shipping read-only now or after the access tests."
        result = record_deliberation(self.task, payload)
        self.assertEqual(result["review"], self.task["review"])
        self.assertEqual(sorted(result["deliberation"]["open"]), sorted(ids))

    def test_a_concession_resolves_the_objection_and_the_brief_separates_agreement(self):
        _, payload = self.responses()
        for response in payload["responses"]:
            if response["objection"] == "security-to-product" and response["board"] == "product":
                response.update(position="concede", evidence_refs=[])
        payload["decision_needed"] = "Decide on the remaining objections."
        task = record_deliberation(self.task, payload)
        self.assertIn("security-to-product", task["deliberation"]["agreed"])
        brief = challenge_report(task)
        self.assertIn('"agreed"', brief)
        self.assertIn('"disagreements"', brief)
        self.assertIn("Decide on the remaining objections.", brief)

    def test_positions_need_evidence_and_every_answer(self):
        _, payload = self.responses()
        payload["decision_needed"] = "x"
        payload["responses"][0]["evidence_refs"] = []
        with self.assertRaisesRegex(ValueError, "cite its evidence"):
            record_deliberation(self.task, payload)
        _, payload = self.responses()
        payload["responses"].pop()
        with self.assertRaisesRegex(ValueError, "Responses are missing"):
            record_deliberation(self.task, payload)

    def test_structured_blockers_become_the_point_of_the_objection(self):
        review = copy.deepcopy(self.task["review"])
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"]["blockers"] = [{"finding": "No rate limit on exports.", "owner": "Security lead", "clears_when": "A limit exists."}]
        task = {**self.task, "review": review}
        with unittest.mock.patch("openguildkit.workflow.validate_review", return_value=review):
            items = deliberation_request(task)["objections"]
        self.assertEqual(next(item for item in items if item["from"] == "security")["point"], "No rate limit on exports.")

    def test_without_deliberation_the_brief_lists_open_objections(self):
        self.assertIn("objections_not_deliberated", challenge_report(self.task))


if __name__ == "__main__":
    unittest.main()
