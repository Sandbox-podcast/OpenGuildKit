import copy
import json
import unittest
import unittest.mock
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.tasks import record_deliberation, record_review
from openguildkit.workflow import challenge_report, consult, decision_summary, deliberation_request

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
        item = next(item for item in request["objections"] if item["from"] == "security")
        self.assertTrue(item["point"])
        self.assertTrue(item["from_position"].startswith("revise"))
        boards = {r["board"] for r in payload["responses"] if r["objection"] == item["id"]}
        self.assertEqual(boards, {"security", item["to"]})
        with self.assertRaisesRegex(ValueError, "decision the responsible person"):
            record_deliberation(self.task, payload)
        payload["decision_needed"] = "Choose between shipping read-only now or after the access tests."
        result = record_deliberation(self.task, payload)
        self.assertEqual(result["review"], self.task["review"])
        self.assertEqual(sorted(result["deliberation"]["open"]), sorted(ids))

    def test_a_concession_resolves_the_objection_and_the_brief_separates_agreement(self):
        _, payload = self.responses()
        conceded = next(item for item in deliberation_request(self.task)["objections"] if item["from"] == "security")
        for response in payload["responses"]:
            if response["objection"] == conceded["id"] and response["board"] == conceded["to"]:
                response.update(position="concede", evidence_refs=[])
        payload["decision_needed"] = "Decide on the remaining objections."
        task = record_deliberation(self.task, payload)
        self.assertIn(conceded["id"], task["deliberation"]["agreed"])
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


    def test_an_objection_reaches_only_the_boards_it_touches_and_the_rules_are_listed(self):
        request = deliberation_request(self.task)
        verdicts = {entry["id"]: entry["challenge"]["verdict"] for entry in self.task["review"]["boards"]}
        proceeding = [board for board, verdict in verdicts.items() if verdict == "proceed"]
        raising = {item["from"] for item in request["objections"]}
        per_board = {board: sum(item["from"] == board for item in request["objections"]) for board in raising}
        self.assertTrue(all(count <= 2 for count in per_board.values()), per_board)
        self.assertLess(len(request["objections"]), len(raising) * len(proceeding))
        self.assertEqual(len(request["objections"]), len({item["id"] for item in request["objections"]}))
        text = " ".join(request["rules"])
        for word in ("maintain", "concede", "amend", "evidence_refs", "decision_needed", "list of IDs"):
            self.assertIn(word, text)

    def test_one_response_can_answer_several_objections_and_two_amendments_settle_a_point(self):
        task = self.reviewed({"product": "revise", "engineering": "revise", "security": "revise"})
        request = deliberation_request(task)
        by_target = {}
        for item in request["objections"]:
            by_target.setdefault(item["to"], []).append(item["id"])
        target, ids = max(by_target.items(), key=lambda pair: len(pair[1]))
        self.assertGreater(len(ids), 1, request["objections"])
        responses = [
            {"objection": ids, "board": target, "position": "amend", "response": "Agreed on a shared wording.", "evidence_refs": [1]},
        ]
        for item in request["objections"]:
            if item["id"] in ids:
                responses.append({"objection": item["id"], "board": item["from"], "position": "amend",
                                  "response": "Agreed on a shared wording.", "evidence_refs": [1]})
            else:
                for board in (item["from"], item["to"]):
                    responses.append({"objection": item["id"], "board": board, "position": "maintain",
                                      "response": "Our evidence still holds.", "evidence_refs": [1]})
        payload = {"consultation_id": request["template"]["consultation_id"], "responses": responses, "decision_needed": "Decide the rest."}
        result = record_deliberation(task, payload)
        self.assertTrue(set(ids) <= set(result["deliberation"]["agreed"]))
        self.assertEqual(len([r for r in result["deliberation"]["responses"] if r["board"] == target and r["objection"] in ids]), len(ids))

    def test_a_board_that_conceded_everything_no_longer_counts_against_approval_and_each_objection_shows_once(self):
        task = self.task
        request = deliberation_request(task)
        payload = copy.deepcopy(request["template"])
        for response in payload["responses"]:
            concede = response["board"] == "security"
            response.update(position="concede" if concede else "maintain", response="Agreed.", evidence_refs=[] if concede else [1])
        payload["decision_needed"] = "Nothing left."
        deliberated = record_deliberation(task, payload)
        before = decision_summary(task)
        after = decision_summary(deliberated)
        warning = lambda lines: next(line for line in lines if "Approving goes against their advice" in line)
        self.assertIn("security", warning(before))
        self.assertNotIn("security", warning(after))
        self.assertTrue(any("no longer objecting: security" in line for line in after))
        for item in request["objections"]:
            mentions = [line for line in after if item["id"] in line]
            self.assertLessEqual(len(mentions), 1, mentions)


if __name__ == "__main__":
    unittest.main()
