"""Packs for GDPR, DORA, NIS 2, the AI Act and the Cyber Resilience Act."""

import re
import unittest
from datetime import datetime

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

    def test_incident_notification_uses_the_same_ai_act_consolidation(self):
        ai_act = self.catalog["packs"]["eu-ai-act"]
        consolidated_url = next(
            source["url"] for source in ai_act["sources"] if source["url"].startswith("https://eur-lex.europa.eu/")
        )
        incident_sources = self.catalog["packs"]["incident-notification"]["sources"]
        self.assertIn(consolidated_url, [source["url"] for source in incident_sources])

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
        automated = rules["automated-decision"]
        self.assertRegex(automated["instruction"], r"Art\. 22\(2\).*Art\. 22\(3\)")
        self.assertIn("human intervention", automated["instruction"])
        # Art. 22(3) opens with "In the cases referred to in points (a) and (c) of paragraph 2": for (b), the law
        # that authorises the decision lays down the safeguards (#301).
        self.assertIn("Art. 22(3) safeguards for exception (a) or (c)", automated["instruction"])
        self.assertIn("for (b), the safeguards the authorising law lays down", automated["instruction"])
        self.assertNotRegex(automated["instruction"], r"applies and add the Art\. 22\(3\)")
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

    def test_pay_transparency_states_the_thresholds_and_the_right_to_information(self):
        pack = self.catalog["packs"]["pay-transparency"]
        rules = {rule["id"]: rule for rule in pack["rules"]}
        report = rules["report-and-assess-pay-gaps"]["instruction"]
        for fact in ("100 workers or more", "250 workers or more", "150 to 249", "100 to 149", "7 June 2027",
                     "7 June 2031", "Art. 9(2)", "Art. 9(3)", "Art. 9(4)", "within six months", "Art. 10(1)"):
            self.assertIn(fact, report)
        information = rules["answer-pay-information-requests"]["instruction"]
        for fact in ("Art. 7(1)", "Art. 7(4)", "two months", "Art. 7(5)"):
            self.assertIn(fact, information)
        self.assertNotIn("to transpose by", pack["description"])

    def test_rules_not_yet_applicable_carry_their_date(self):
        dated = {
            "eu-ai-act": {"classify-employment-use": "2 December 2027", "keep-high-risk-logs": "2 December 2027",
                          "enable-human-oversight": "2 December 2027",
                          "maintain-technical-documentation": "2 December 2027",
                          "mark-generated-content": "2 December 2026"},
            "cyber-resilience-act": {rule_id: "11 December 2027" for rule_id in (
                "generate-release-sbom", "publish-disclosure-policy", "ship-secure-defaults",
                "distribute-updates-securely", "record-support-period")},
        }
        for pack_id, rules in dated.items():
            pack = {rule["id"]: rule for rule in self.catalog["packs"][pack_id]["rules"]}
            for rule_id, day in rules.items():
                with self.subTest(pack=pack_id, rule=rule_id):
                    self.assertIn(day, pack[rule_id]["instruction"])
        sources = {source["url"]: source["checked"] for source in self.catalog["packs"]["eu-ai-act"]["sources"]}
        self.assertEqual(sources["https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act"],
                         "2026-11-22")
        self.assertIn("11 September 2026", self.catalog["packs"]["cyber-resilience-act"]["description"])

    def test_no_pack_description_presents_a_past_date_as_future(self):
        months = "January|February|March|April|May|June|July|August|September|October|November|December"
        future = re.compile(rf"\b(?:to transpose by|transpose by|will apply (?:from|on)|applies from|apply from|"
                            rf"applicable from|due by|enters into force on)\s+(\d{{1,2}} (?:{months}) \d{{4}})")
        stale = []
        for pack_id, pack in self.catalog["packs"].items():
            checked = max((source.get("checked", "") for source in pack["sources"]), default="")
            for day in future.findall(pack["description"]):
                if datetime.strptime(day, "%d %B %Y").date().isoformat() <= checked:
                    stale.append(f"{pack_id}: {day} (checked {checked})")
        self.assertEqual(stale, [])
        self.assertTrue(future.search("Member States are to transpose by 7 June 2026"))

    def test_nis2_names_the_implementing_regulation_for_digital_providers(self):
        pack = self.catalog["packs"]["nis2"]
        self.assertIn("Implementing Regulation (EU) 2024/2690", pack["description"])
        sources = {source["url"]: source["checked"] for source in pack["sources"]}
        self.assertEqual(sources["https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R2690"], "2026-11-22")
        rule = next(rule for rule in pack["rules"] if "2024/2690" in rule["instruction"])
        self.assertIn("Art. 7", rule["instruction"])


if __name__ == "__main__":
    unittest.main()
