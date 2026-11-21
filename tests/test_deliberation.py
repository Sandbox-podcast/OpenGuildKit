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
        self.draft = {"id": "request-status", "brief": (EXAMPLE / "brief.md").read_text(), "answers": answers,
                      "status": "consulting", "rounds": []}
        self.consultation = consult(profile, catalog, self.draft)
        self.task = self.reviewed()

    def reviewed(self, verdicts=None):
        """The example review, with some boards' verdicts changed; a block carries one blocker."""
        review = {"consultation_id": self.consultation["id"], **json.loads((EXAMPLE / "review.json").read_text())}
        for entry in review["boards"]:
            verdict = (verdicts or {}).get(entry["id"])
            if verdict:
                blockers = [{"finding": f"{entry['id']} finds no rate limit on exports.", "owner": "Security lead",
                             "clears_when": "A limit exists."}] if verdict == "block" else []
                entry["challenge"].update(verdict=verdict, blockers=blockers)
        return record_review({**self.draft, "consultation": self.consultation}, review)

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

    def test_a_board_that_blocks_confronts_a_board_that_asks_to_revise_on_its_blocker(self):
        """Issue 129: Product said revise and Security block, and their opinions never met."""
        task = self.reviewed({"product": "revise", "security": "block"})
        request = deliberation_request(task)
        item = next(item for item in request["objections"] if item["id"] == "security-to-product")
        self.assertEqual(item["point"], "security finds no rate limit on exports.")
        self.assertTrue(item["from_position"].startswith("block: "))
        self.assertTrue(item["to_position"].startswith("revise: "))
        self.assertNotIn("product-to-security", [entry["id"] for entry in request["objections"]])
        payload = copy.deepcopy(request["template"])
        boards = {r["board"] for r in payload["responses"] if r["objection"] == "security-to-product"}
        self.assertEqual(boards, {"security", "product"})
        for response in payload["responses"]:
            concede = response["objection"] == "security-to-product" and response["board"] == "product"
            response.update(position="concede" if concede else "maintain", response="On the rate limit: agreed.",
                            evidence_refs=[] if concede else [1])
        payload["decision_needed"] = "Decide on the remaining objections."
        self.assertIn("security-to-product", record_deliberation(task, payload)["deliberation"]["agreed"])

    def test_boards_that_all_give_the_same_verdict_have_no_objection(self):
        for verdict in ("revise", "block", "proceed"):
            with self.subTest(verdict=verdict):
                verdicts = {board: verdict for board in self.consultation["boards"]}
                if verdict == "proceed":
                    verdicts = {board: "proceed" for board in ("engineering", "design", "security")}
                    verdicts["marketing"] = None
                task = self.reviewed(verdicts)
                if verdict == "proceed":
                    task["review"]["boards"] = [e for e in task["review"]["boards"] if e["id"] != "marketing"]
                    task = {**task, "consultation": {**task["consultation"], "boards": [
                        b for b in task["consultation"]["boards"] if b != "marketing"]}}
                self.assertEqual(deliberation_request(task)["objections"], [])
                with self.assertRaisesRegex(ValueError, "nothing to deliberate"):
                    record_deliberation(task, deliberation_request(task)["template"])
                self.assertNotIn("Verdicts differ", challenge_report(task))

    def test_the_brief_says_when_verdicts_differ_without_a_confrontation_and_why(self):
        brief = challenge_report(self.task)
        self.assertIn("Verdicts differ without a confrontation: revise (engineering, design, security) and "
                      "insufficient-evidence (marketing). No objection asks them to answer each other, because both "
                      "hold the work back", brief)
        blocked = challenge_report(self.reviewed({"security": "block"}))
        self.assertIn("block (security) and insufficient-evidence (marketing)", blocked)
        self.assertNotIn("revise (engineering, design) and block", blocked)

    def test_without_deliberation_the_brief_lists_open_objections(self):
        self.assertIn("objections_not_deliberated", challenge_report(self.task))


if __name__ == "__main__":
    unittest.main()
