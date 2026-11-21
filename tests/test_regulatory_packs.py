"""Packs for GDPR, DORA, NIS 2, the AI Act and the Cyber Resilience Act."""

import re
import unittest

from openguildkit.catalog import load_catalog
from openguildkit.patterns import recommend_patterns
from openguildkit.project import render_instructions, resolved_profile, validate_profile
from openguildkit.references import find_references, load_references

REGULATIONS = {
    "gdpr": ("gdpr-personal-data", "rgpd"),
    "dora": ("dora-financial-entity", "dora"),
    "nis2": ("nis2-essential-entity", "nis-2"),
    "eu-ai-act": ("eu-ai-act-system", "eu-ai-act"),
    "cyber-resilience-act": ("cyber-resilience-act-product", "cyber-resilience-act"),
}


class RegulatoryPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.references = load_references()

    def test_each_rule_cites_the_text_and_claims_no_compliance(self):
        for pack_id in REGULATIONS:
            for rule in self.catalog["packs"][pack_id]["rules"]:
                text = f"{rule['instruction']} {rule['verification']}"
                with self.subTest(pack=pack_id, rule=rule["id"]):
                    self.assertRegex(text, r"\b(Art\.|Annex|Chapter)\s")
                    self.assertNotRegex(text, r"(?i)\bcompliant\b|ensures? compliance|certif")
                    self.assertRegex(rule["instruction"], r"^(Ask|When|For|Add|Make|Keep|Collect|Use|Include|Generate|Distribute)\b")

    def test_sources_are_the_official_texts(self):
        for pack_id, (pattern_id, reference_id) in REGULATIONS.items():
            reference = find_references(self.references, record_id=reference_id)[0]
            official = next(source["url"] for source in reference["sources"] if source["url"].startswith("https://eur-lex.europa.eu/"))
            with self.subTest(pack=pack_id):
                self.assertIn(official, [source["url"] for source in self.catalog["packs"][pack_id]["sources"]])
                self.assertIn(official, [source["url"] for source in self.catalog["patterns"][pattern_id]["sources"]])

    def test_legal_and_security_roles_reach_the_packs_and_references_link_them(self):
        for role in ("legal", "security"):
            suggested = {item["id"] for item in recommend_patterns(self.catalog, [], "general", [role])["suggested"]}
            self.assertLessEqual({pattern_id for pattern_id, _ in REGULATIONS.values()}, suggested)
        for pack_id, (pattern_id, reference_id) in REGULATIONS.items():
            with self.subTest(pack=pack_id):
                reference = find_references(self.references, record_id=reference_id)[0]
                self.assertEqual(reference["pattern"], pattern_id)
                self.assertIn(pack_id, reference["packs"])
                self.assertEqual(self.catalog["patterns"][pattern_id]["packs"], [pack_id])
                self.assertIn(reference_id, self.catalog["patterns"][pattern_id]["references"])

    def test_financial_services_sector_points_to_dora(self):
        sector = self.catalog["sectors"]["financial-services"]
        self.assertTrue(any("DORA" in item and "dora-financial-entity" in item for item in sector["context"]))
        profile = validate_profile(
            {"name": "Payments API", "sector": "financial-services", "patterns": ["dora-financial-entity"], "packs": []},
            self.catalog,
        )
        self.assertIn("dora", resolved_profile(profile, self.catalog)["packs"])
        instructions = render_instructions(profile, self.catalog)
        self.assertIn("`dora@1.0.0`", instructions)
        self.assertTrue(re.search(r"financial entity under DORA", instructions))


if __name__ == "__main__":
    unittest.main()
