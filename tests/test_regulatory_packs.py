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
        self.assertIn("`dora@2.1.1`", instructions)
        self.assertTrue(re.search(r"financial entity under DORA", instructions))

    def test_gdpr_asks_for_the_notice_the_tracker_consent_and_the_art_22_safeguards(self):
        rules = {rule["id"]: rule for rule in self.catalog["packs"]["gdpr"]["rules"]}
        notice = rules["inform-data-subjects"]
        self.assertRegex(notice["instruction"], r"Art\. 13\b.*Art\. 14")
        trackers = rules["gate-trackers-on-consent"]
        self.assertIn("Directive 2002/58/EC Art. 5(3)", trackers["instruction"])
        self.assertIn("strictly necessary", trackers["instruction"])
        # Each one is verified on a test page of the changed flow.
        for rule in (notice, trackers):
            self.assertIn("test page", rule["verification"])
        automated = rules["review-automated-decisions"]
        self.assertRegex(automated["instruction"], r"Art\. 22\(2\).*Art\. 22\(3\)")
        self.assertIn("human intervention", automated["instruction"])
        # Art. 48 is about third-country judgments, not a transfer mechanism.
        transfer = rules["check-transfer-mechanism"]["instruction"]
        for article in ("Art. 45", "Art. 46", "Art. 47", "Art. 49"):
            self.assertIn(article, transfer)
        self.assertNotIn("Art. 48", transfer)
        self.assertNotIn("45 to 49", transfer)
        sources = {source["url"]: source["checked"] for source in self.catalog["packs"]["gdpr"]["sources"]}
        for url in ("https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra",
                    "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02002L0058-20091219",
                    "https://www.cnil.fr/fr/conformite-rgpd-information-des-personnes-et-transparence",
                    "https://www.cnil.fr/fr/cookies-et-autres-traceurs/regles/cookies"):
            self.assertEqual(sources.get(url), "2026-11-22", url)


if __name__ == "__main__":
    unittest.main()
