"""Briefs that must, or must not, reach each brain. CI runs them on every catalog change."""

import json
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.workflow import normalize_text, trigger_matches

CASES = json.loads((Path(__file__).with_name("routing_cases.json")).read_text(encoding="utf-8"))


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.boards = load_catalog()["boards"]

    def test_briefs_reach_the_right_brains(self):
        for case in CASES:
            with self.subTest(brief=case["brief"]):
                selected = trigger_matches(self.boards, case["brief"])
                for board in case.get("must", []):
                    self.assertIn(board, selected, f"{board} should review: {selected}")
                for board in case.get("must_not", []):
                    self.assertNotIn(board, selected, f"{board} should not review: {selected}")

    def test_every_brain_is_reachable_from_a_plain_brief(self):
        reached = {board for case in CASES for board in case.get("must", [])}
        self.assertEqual(set(self.boards) - reached, set())

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

    def test_hyphenated_words_do_not_match_inside(self):
        boards = {"sales": {"triggers": ["commerce"]}}
        self.assertEqual(trigger_matches(boards, "our e-commerce site"), {})
        self.assertEqual(trigger_matches(boards, "le commerce en ligne"), {"sales": ["commerce"]})


if __name__ == "__main__":
    unittest.main()
