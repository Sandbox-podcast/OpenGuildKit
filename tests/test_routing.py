"""Briefs that must, or must not, reach each brain. CI runs them on every catalog change."""

import json
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.workflow import normalize_text, select_boards, text_routes, trigger_matches, validate_answers

# routing_cases_new_brains.json holds the cases of the brains added after the first eighteen.
CASES = [
    case
    for name in ("routing_cases.json", "routing_cases_new_brains.json")
    for case in json.loads(Path(__file__).with_name(name).read_text(encoding="utf-8"))
]
NEUTRAL = {"kind": "other", "surface": ["other"], "data": "none", "research": "local", "context": "see brief"}


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.boards = cls.catalog["boards"]

    def route(self, brief: str, answers: dict | None = None, profile: dict | None = None) -> dict:
        answers = validate_answers(answers or NEUTRAL)
        profile = profile or {"name": "Portal", "sector": "general", "packs": [], "boards": []}
        return select_boards(profile, self.catalog, {"id": "t", "brief": brief}, answers)

    def test_briefs_reach_the_right_brains(self):
        for case in CASES:
            with self.subTest(brief=case["brief"]):
                selected = text_routes(self.boards, case["brief"])
                for board in case.get("must", []):
                    self.assertIn(board, selected, f"{board} should review: {selected}")
                for board in case.get("must_not", []):
                    self.assertNotIn(board, selected, f"{board} should not review: {selected}")

    def test_every_brain_is_reachable_from_a_plain_brief(self):
        reached = {board for case in CASES for board in case.get("must", [])}
        self.assertEqual(set(self.boards) - reached, set())

    def test_the_audit_table_covers_every_brain_in_both_languages(self):
        audit = CASES[50:]
        self.assertGreaterEqual(len(audit), 60)
        self.assertEqual(set(self.boards) - {board for case in audit for board in case.get("must", [])}, set())
        self.assertTrue(any("must_not" in case for case in audit))
        self.assertTrue(any("é" in case["brief"] or "TVA" in case["brief"] for case in audit))

    def test_case_accents_apostrophes_and_plurals_are_folded(self):
        self.assertEqual(normalize_text("Sécurité  DES Données"), "securite des donnees")
        self.assertEqual(normalize_text("l’appel d’offres"), "l'appel d'offres")
        boards = {"x": {"triggers": ["partie prenante"]}}
        self.assertEqual(trigger_matches(boards, "Les parties prenantes"), {"x": ["partie prenante"]})

    def test_a_longer_phrase_wins_and_an_identical_phrase_is_shared(self):
        boards = {
            "finance": {"triggers": ["budget"]},
            "performance": {"triggers": ["performance budget"]},
            "operations": {"triggers": ["support ticket"]},
            "support": {"triggers": ["support ticket"]},
        }
        self.assertEqual(trigger_matches(boards, "Set a performance budget"), {"performance": ["performance budget"]})
        self.assertEqual(set(trigger_matches(boards, "Close the support ticket")), {"operations", "support"})

    def test_a_boards_own_phrases_do_not_cancel_each_other(self):
        boards = {
            "devops": {"triggers": ["dora lead time", "lead time for changes"]},
            "legal": {"triggers": ["dora"]},
        }
        self.assertEqual(trigger_matches(boards, "Track DORA lead time for changes"),
                         {"devops": ["lead time for changes"]})

    def test_a_neutral_phrase_claims_a_job_title(self):
        boards = {"engineering": {"triggers": ["backend"]}, "hr": {"triggers": ["hire"]}}
        self.assertEqual(trigger_matches(boards, "Hire two backend engineers"), {"hr": ["hire"]})
        self.assertEqual(trigger_matches(boards, "Split the backend"), {"engineering": ["backend"]})

    def test_hyphenated_words_do_not_match_inside(self):
        boards = {"sales": {"triggers": ["commerce"]}}
        self.assertEqual(trigger_matches(boards, "our e-commerce site"), {})
        self.assertEqual(trigger_matches(boards, "le commerce en ligne"), {"sales": ["commerce"]})

    def test_ai_screening_of_applicants_reaches_hr_legal_and_data(self):
        answers = {"kind": "feature", "surface": ["business", "service"], "data": "personal", "research": "local",
                   "context": "Candidates upload a CV, the model scores them"}
        selected = self.route("Use AI to screen and rank job applicants", answers)
        self.assertLessEqual({"hr", "legal", "data"}, set(selected["routing"]))
        self.assertIn("eu-ai-act-system", [pattern["id"] for pattern in selected["patterns"]])
        rules = {rule["id"]: rule for rule in self.catalog["packs"]["eu-ai-act"]["rules"]}
        self.assertIn("Annex III, point 4", rules["classify-employment-use"]["instruction"])

    def test_an_active_pattern_is_not_suggested_again(self):
        profile = {"name": "Portal", "sector": "general", "packs": [], "boards": [], "patterns": ["eu-ai-act-system"]}
        selected = self.route("Use AI to screen and rank job applicants", profile=profile)
        self.assertEqual(selected["patterns"], [])

    def test_answers_route_without_any_keyword(self):
        plain = "Change how the scheduler picks the next item"
        cases = {
            "people-decisions": {"legal", "data", "security"},
            "money": {"finance"},
            "ai": {"data", "security", "legal"},
            "credentials": {"security", "devops"},
        }
        for concern, boards in cases.items():
            with self.subTest(concern=concern):
                routing = self.route(plain, {**NEUTRAL, "concerns": [concern]})["routing"]
                self.assertLessEqual(boards, set(routing))
        self.assertNotIn("legal", self.route(plain, {**NEUTRAL, "concerns": ["none"]})["routing"])

    def test_personal_data_reaches_legal_as_well_as_security(self):
        routing = self.route("Change how the scheduler picks the next item", {**NEUTRAL, "data": "personal"})["routing"]
        self.assertLessEqual({"legal", "security"}, set(routing))

    def test_a_credential_leak_reaches_security_and_devops_whatever_the_data_answer(self):
        for data in ("none", "internal", "personal", "regulated", "unsure"):
            with self.subTest(data=data):
                routing = self.route("Rotate the leaked AWS access key", {**NEUTRAL, "data": data})["routing"]
                self.assertLessEqual({"security", "devops"}, set(routing))

    def test_concerns_are_optional_and_checked(self):
        self.assertNotIn("concerns", validate_answers(NEUTRAL))
        self.assertEqual(validate_answers({**NEUTRAL, "concerns": "money"})["concerns"], ["money"])
        with self.assertRaisesRegex(ValueError, "concerns"):
            validate_answers({**NEUTRAL, "concerns": ["money", "weather"]})
        with self.assertRaisesRegex(ValueError, "none"):
            validate_answers({**NEUTRAL, "concerns": ["money", "none"]})

    def test_an_unrecognised_brief_asks_the_requester_to_pick_boards(self):
        routing = self.route("Tidy things up")["routing"]
        self.assertEqual(list(routing), ["product"])
        self.assertIn("No discipline recognised", routing["product"][0])
        self.assertIn("--add", routing["product"][0])

    def test_dora_metrics_and_service_discovery_are_not_regulation_or_product(self):
        self.assertNotIn("legal", text_routes(self.boards, "Track DORA lead time for changes"))
        self.assertNotIn("security", text_routes(self.boards, "Report the DORA change failure rate"))
        self.assertNotIn("product", text_routes(self.boards, "Fix the service discovery timeout in Consul"))
        self.assertIn("product", text_routes(self.boards, "Plan the product discovery interviews"))
        self.assertNotIn("discovery", self.boards["product"]["triggers"])


if __name__ == "__main__":
    unittest.main()
