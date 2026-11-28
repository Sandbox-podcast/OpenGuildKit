import copy
import json
import unittest
import unittest.mock
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.consultation import consult
from openguildkit.project import validate_profile
from openguildkit.project_rules import resolved_profile
from openguildkit.tasks_closing import record_deliberation
from openguildkit.tasks_review import record_review
from openguildkit.workflow import challenge_report, decision_summary, deliberation_request, verdict_lines

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

    def reviewed(self, verdicts=None, failure_modes=None):
        """The example review, with some boards' verdicts changed; a block carries one blocker that meets the
        domains of Product (acceptance criteria) and Legal (compliance)."""
        review = {"consultation_id": self.consultation["id"], **json.loads((EXAMPLE / "review.json").read_text())}
        for entry in review["boards"]:
            verdict = (verdicts or {}).get(entry["id"])
            if verdict:
                blockers = [{"finding": f"{entry['id']} finds the acceptance criteria have no compliance check "
                                        "for exports.", "owner": "Security lead",
                             "clears_when": "A limit exists."}] if verdict == "block" else []
                entry["challenge"].update(verdict=verdict, blockers=blockers)
            if (failure_modes or {}).get(entry["id"]):
                entry["challenge"]["failure_mode"] = failure_modes[entry["id"]]
        return record_review({**self.draft, "consultation": self.consultation}, review)

    def responses(self, task=None, position="maintain"):
        request = deliberation_request(task or self.task)
        payload = copy.deepcopy(request["template"])
        for response in payload["responses"]:
            response.update(position=position, response="Our evidence still holds.", evidence_refs=[1])
        return request, payload

    def test_first_opinions_stay_and_both_boards_answer_the_same_point(self):
        request, payload = self.responses()
        ids = [item["id"] for item in request["objections"]]
        self.assertIn("security-to-legal", ids)
        item = next(item for item in request["objections"] if item["id"] == "security-to-legal")
        self.assertTrue(item["point"])
        self.assertTrue(item["meets"])
        self.assertTrue(item["from_position"].startswith("revise"))
        boards = {r["board"] for r in payload["responses"] if "security-to-legal" in r["objections"]}
        self.assertEqual(boards, {"security", "legal"})
        with self.assertRaisesRegex(ValueError, "decision the responsible person"):
            record_deliberation(self.task, payload)
        payload["decision_needed"] = "Choose between shipping read-only now or after the access tests."
        result = record_deliberation(self.task, payload)
        self.assertEqual(result["review"], self.task["review"])
        self.assertEqual(sorted(result["deliberation"]["open"]), sorted(ids))

    def test_an_objection_reaches_only_the_boards_whose_domain_it_meets(self):
        """Issue 158: a generic failure mode was sent to every board that proceeds."""
        generic = {board: f"Concern of {board}: failure mode specific to {board} board."
                   for board in ("engineering", "design", "marketing", "security")}
        task = self.reviewed({"engineering": "revise", "design": "revise", "security": "block"}, generic)
        items = deliberation_request(task)["objections"]
        self.assertEqual(sorted(item["id"] for item in items), ["security-to-legal", "security-to-product"])
        self.assertLess(len(items), 8)
        self.assertIn("Advice addressed to no other board", challenge_report(task))

    def test_a_word_with_two_meanings_is_not_a_meeting_of_domains(self):
        """Issue 158: legal's contracts met engineering's contract test."""
        review = {"consultation_id": self.consultation["id"], **json.loads((EXAMPLE / "review.json").read_text())}
        for entry in review["boards"]:
            if entry["id"] == "legal":
                entry["challenge"].update(verdict="revise", failure_mode="The retention period of the requests is "
                                          "not decided and could break the customer contract.")
            if entry["id"] == "engineering":
                entry["challenge"].update(verdict="proceed", verification="Contract test of the endpoint.")
                entry["recommendation"] = "Ship the read-only endpoint."
        task = record_review({**self.draft, "consultation": self.consultation}, review)
        ids = [item["id"] for item in deliberation_request(task)["objections"]]
        self.assertNotIn("legal-to-engineering", ids)

    def test_a_concession_closes_the_objection_without_the_other_answer(self):
        """Issue 158: the other board still had to answer a point the objector had conceded."""
        _, payload = self.responses()
        payload["responses"] = [dict(r, position="concede", evidence_refs=[]) for r in payload["responses"]
                                if r["board"] == "security" and r["objections"] == ["security-to-legal"]]
        payload["responses"] += [r for r in self.responses()[1]["responses"] if "security-to-legal" not in r["objections"]]
        payload["decision_needed"] = "Decide on the remaining objections."
        task = record_deliberation(self.task, payload)
        self.assertIn("security-to-legal", task["deliberation"]["agreed"])
        self.assertEqual([r["board"] for r in task["deliberation"]["responses"] if r["objection"] == "security-to-legal"],
                         ["security"])

    def test_one_response_answers_several_objections(self):
        task = self.reviewed({"security": "block"})
        request, payload = self.responses(task)
        security = [r for r in payload["responses"] if r["board"] == "security"]
        self.assertEqual(len(security), 1)
        self.assertEqual(sorted(security[0]["objections"]), ["security-to-legal", "security-to-product"])
        self.assertEqual(set(request["rules"]["positions"]), {"maintain", "amend", "concede"})
        self.assertIn("decision_needed", request["rules"])
        self.assertEqual(request["example"]["position"], "amend")
        self.assertIn("raised and received", request["rules"]["one_response"])
        payload["decision_needed"] = "Decide."
        recorded = record_deliberation(task, payload)["deliberation"]
        self.assertEqual(len([r for r in recorded["responses"] if r["board"] == "security"]), 2)

    def test_a_concession_resolves_the_objection_and_the_brief_separates_agreement(self):
        _, payload = self.responses()
        conceded = next(item for item in deliberation_request(self.task)["objections"] if item["from"] == "security")
        for response in payload["responses"]:
            if response["board"] == "legal":
                response.update(position="concede", evidence_refs=[])
        payload["decision_needed"] = "Decide on the remaining objections."
        task = record_deliberation(self.task, payload)
        self.assertIn("security-to-legal", task["deliberation"]["agreed"])
        brief = challenge_report(task)
        self.assertIn('"status": "resolved"', brief)
        self.assertIn('"status": "open"', brief)
        self.assertIn("Decide on the remaining objections.", brief)
        self.assertIn("one of the two boards concedes, or when both amend", brief)

    def test_an_amendment_accepted_on_both_sides_resolves_the_objection(self):
        """Issue 158: two amends were still counted as an open disagreement."""
        _, payload = self.responses(position="amend")
        task = record_deliberation(self.task, payload)
        self.assertEqual(task["deliberation"]["open"], [])
        brief = challenge_report(task)
        self.assertNotIn("Disagreement left open", brief)
        self.assertNotIn("Objection not deliberated", brief)
        _, payload = self.responses()
        for response in payload["responses"]:
            if response["board"] == "security":
                response["position"] = "amend"
        payload["decision_needed"] = "Decide."
        task = record_deliberation(self.task, payload)
        self.assertIn("security-to-legal", task["deliberation"]["open"])
        brief = challenge_report(task)
        self.assertEqual(brief.count("Disagreement left open: security-to-legal"), 1)
        self.assertNotIn("Objection not deliberated", brief)

    def test_the_warning_follows_the_advice_after_deliberation(self):
        """Issue 158: the brief warned against advice that a concession had already resolved."""
        before = challenge_report(self.task)
        self.assertIn("(engineering, design, security, marketing). Approving goes against their advice.", before)
        _, payload = self.responses()
        for response in payload["responses"]:
            if response["board"] in ("legal", "product"):
                response.update(position="concede", evidence_refs=[])
        task = record_deliberation(self.task, payload)
        after = challenge_report(task)
        self.assertIn("Objections of marketing, security were all resolved in deliberation.", after)
        self.assertIn("Warning: 2 of 7 boards say revise, block or insufficient-evidence (engineering, design).", after)

    def test_counts_agree_with_their_noun(self):
        """"1 objections not deliberated yet" and "1 of 6 boards say revise" were printed."""
        review = {"boards": [{"id": board, "recommendation": "x", "challenge": {"verdict": verdict}}
                             for board, verdict in (("security", "revise"), ("product", "proceed"))]}
        self.assertIn("Warning: 1 of 2 boards says revise, block or insufficient-evidence (security).",
                      verdict_lines(review)[1])
        review["boards"][1]["challenge"]["verdict"] = "block"
        self.assertIn("Warning: 2 of 2 boards say revise", verdict_lines(review)[1])
        with unittest.mock.patch("openguildkit.workflow.objections", return_value=[{"id": "security-to-legal", "from": "security", "to": "legal", "point": "p"}]):
            self.assertIn("1 objection not deliberated yet:", challenge_report(self.task))
        self.assertIn("2 objections not deliberated yet:", challenge_report(self.task))

    def test_positions_need_evidence_and_every_answer(self):
        _, payload = self.responses()
        payload["decision_needed"] = "x"
        payload["responses"][0]["evidence_refs"] = []
        payload["responses"][1]["position"] = "agree"
        with self.assertRaisesRegex(ValueError, "2 problems") as raised:
            record_deliberation(self.task, payload)
        self.assertIn("cite its evidence", str(raised.exception))
        self.assertIn("accepted: maintain, concede, amend", str(raised.exception))
        _, payload = self.responses()
        payload["responses"].pop()
        with self.assertRaisesRegex(ValueError, "Responses are missing"):
            record_deliberation(self.task, payload)

    def test_structured_blockers_become_the_point_of_the_objection(self):
        review = copy.deepcopy(self.task["review"])
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"]["blockers"] = [{"finding": "No privacy review of exports.", "owner": "Security lead",
                                              "clears_when": "A limit exists."}]
        task = {**self.task, "review": review}
        with unittest.mock.patch("openguildkit.workflow.validate_review", return_value=review):
            items = deliberation_request(task)["objections"]
        self.assertEqual(next(item for item in items if item["from"] == "security")["point"], "No privacy review of exports.")

    def test_a_board_that_blocks_confronts_a_board_that_asks_to_revise_on_its_blocker(self):
        """Issue 129: Product said revise and Security block, and their opinions never met."""
        task = self.reviewed({"product": "revise", "security": "block"})
        request = deliberation_request(task)
        item = next(item for item in request["objections"] if item["id"] == "security-to-product")
        self.assertEqual(item["point"], "security finds the acceptance criteria have no compliance check for exports.")
        self.assertTrue(item["from_position"].startswith("block: "))
        self.assertTrue(item["to_position"].startswith("revise: "))
        self.assertNotIn("product-to-security", [entry["id"] for entry in request["objections"]])
        payload = copy.deepcopy(request["template"])
        boards = {r["board"] for r in payload["responses"] if "security-to-product" in r["objections"]}
        self.assertEqual(boards, {"security", "product"})
        for response in payload["responses"]:
            concede = response["board"] == "product"
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
        text = json.dumps(request["rules"])
        for word in ("maintain", "concede", "amend", "evidence_refs", "decision_needed", "several objections"):
            self.assertIn(word, text)

    def test_one_response_can_answer_several_objections_and_two_amendments_settle_a_point(self):
        task = self.reviewed({"engineering": "block", "security": "block"})
        request = deliberation_request(task)
        by_target = {}
        for item in request["objections"]:
            by_target.setdefault(item["to"], []).append(item["id"])
        target, ids = max(by_target.items(), key=lambda pair: len(pair[1]))
        self.assertGreater(len(ids), 1, request["objections"])
        responses = [
            {"objections": ids, "board": target, "position": "amend", "response": "Agreed on a shared wording.", "evidence_refs": [1]},
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
        self.assertTrue(any("Objections of security were all resolved in deliberation" in line for line in after), after)
        for item in request["objections"]:
            mentions = [line for line in after if item["id"] in line]
            self.assertLessEqual(len(mentions), 1, mentions)


if __name__ == "__main__":
    unittest.main()


class ObjectionScanTests(unittest.TestCase):
    """objections scans each text once for every board's domain, not once per pair of boards."""

    setUp = DeliberationTests.setUp
    reviewed = DeliberationTests.reviewed

    def test_objections_scan_each_distinct_text_once(self):
        """Issue #540: objections ran 24 trigger scans for 7 distinct texts, 12.3 s for task retro --all at 1,000."""
        from openguildkit import routing, workflow

        task = self.reviewed({"security": "block", "qa": "block"})
        with unittest.mock.patch("openguildkit.routing.scan_triggers", wraps=routing.scan_triggers) as scan:
            found = workflow.objections(task["review"], task["consultation"]["domains"])
        texts = [call.args[1] for call in scan.call_args_list]
        self.assertTrue(found)
        self.assertGreater(len(texts), 1)
        self.assertEqual(len(texts), len(set(texts)))
