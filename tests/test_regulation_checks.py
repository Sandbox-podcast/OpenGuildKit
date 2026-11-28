"""The regulation packs that use machine checks: PCI DSS, ISO 27001 and DORA rules, their sources, evidence and
defaults."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.project import profile_recommendations, validate_profile
from openguildkit.project_rules import resolved_profile
from openguildkit.project_setup import init_questions
from openguildkit.storage import write_json


class RegulationPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_pci_dss_rules_cite_a_requirement_of_the_edition_read(self):
        pci = self.catalog["packs"]["pci-dss"]
        self.assertIn("PCI DSS v4.0.1", pci["description"])
        for rule in pci["rules"]:
            with self.subTest(rule=rule["id"]):
                self.assertRegex(rule["instruction"], r"Requirements? \d+(\.\d+)*")
        urls = [source["url"] for source in pci["sources"]]
        # The requirements come from the PCI SSC; the secret scanners that the 8.6.2 check looks for, from their projects.
        scanners = {"https://github.com/gitleaks/gitleaks", "https://github.com/trufflesecurity/trufflehog",
                    "https://github.com/Yelp/detect-secrets"}
        self.assertTrue(all(re.match(r"https://(www|blog|listings)\.pcisecuritystandards\.org/", url) or url in scanners
                            for url in urls))

    def test_pci_dss_covers_what_a_development_team_meets_first(self):
        pci = self.catalog["packs"]["pci-dss"]
        rules = {rule["id"]: rule for rule in pci["rules"]}
        for rule_id, requirement in (("mask-displayed-pan", "3.4.1"), ("no-live-pans-before-production", "6.5.5"),
                                     ("remove-test-data-before-production", "6.5.6"),
                                     ("no-hard-coded-passwords", "8.6.2")):
            with self.subTest(rule=rule_id):
                self.assertIn(f"Requirement {requirement}", rules[rule_id]["instruction"])
                self.assertTrue(rules[rule_id]["verification"])
        scanner = rules["no-hard-coded-passwords"]["check"]
        self.assertEqual((scanner["kind"], scanner["expect"]), ("text", "present"))
        self.assertIn("gitleaks", scanner["contains"])
        self.assertIn(".pre-commit-config.yaml", scanner["paths"])
        self.assertIn("PCI SSC Document Library", pci["description"])
        dated = {source["url"]: source["checked"] for source in pci["sources"]}
        self.assertEqual(dated["https://www.pcisecuritystandards.org/document_library/?class=pcidss&doc=pci_dss"],
                         "2026-11-22")
        self.assertEqual(dated["https://listings.pcisecuritystandards.org/documents/PCI-DSS-v4-0-SAQ-D-Merchant.pdf"],
                         "2026-11-22")

    def test_the_pci_dss_proposal_says_the_questionnaire_depends_on_the_integration(self):
        questions = {question["id"]: question for question in init_questions(self.catalog, "Shop")}
        norm = next(norm for norm in questions["norms"]["norms"] if norm["id"] == "pci-dss-cardholder-data")
        self.assertIn("self-assessment questionnaire", norm["help"])
        self.assertIn("depends on the payment integration", norm["help"])
        self.assertIn("https://listings.pcisecuritystandards.org/documents/PCI-DSS-v4-0-SAQ-A.pdf",
                      [source["url"] for source in norm["sources"]])

    def test_iso_27001_names_the_development_controls_and_only_controls_of_annex_a(self):
        rules = self.catalog["packs"]["iso-27001"]["rules"]
        text = " ".join(rule["instruction"] for rule in rules)
        for control in ("8.25", "8.28", "8.29", "8.31", "8.32", "8.33"):
            self.assertRegex(text, rf"\b{re.escape(control)}\b")
        # ISO/IEC 27001:2022 Annex A takes the 93 controls of ISO/IEC 27002:2022: 37 organizational (5.x), 8 people
        # (6.x), 14 physical (7.x) and 34 technological (8.x), as the ISO/IEC JTC 1/SC 27 Journal of July 2022 says.
        annex_a = {f"{clause}.{number}" for clause, count in ((5, 37), (6, 8), (7, 14), (8, 34))
                   for number in range(1, count + 1)}
        self.assertEqual(len(annex_a), 93)
        cited = {(rule["id"], control) for rule in rules if "Annex A" in rule["instruction"]
                 for control in re.findall(r"(?<![\d.])(\d+\.\d+)(?![\d])", rule["instruction"])}
        self.assertGreater(len(cited), 20)
        for rule_id, control in sorted(cited):
            with self.subTest(rule=rule_id, control=control):
                self.assertIn(control, annex_a)

    def test_pci_dss_is_proposed_for_a_payment_stack_and_never_imposed(self):
        with_cards = profile_recommendations({"stack": ["Python", "Stripe"]}, self.catalog)
        self.assertIn("pci-dss-cardholder-data", {entry["id"] for entry in with_cards["matched"]})
        without = profile_recommendations({"stack": ["Python"], "sector": "financial-services"}, self.catalog)
        self.assertNotIn("pci-dss-cardholder-data", {entry["id"] for entry in without["matched"]})
        security = profile_recommendations({"stack": ["Python"], "roles": ["security"]}, self.catalog)
        self.assertIn("pci-dss-cardholder-data", {entry["id"] for entry in security["suggested"]})
        chosen = validate_profile({"personal_data": "no", "name": "Shop", "stack": ["Python"], "patterns": ["pci-dss-cardholder-data"]},
                                  self.catalog)
        self.assertIn("pci-dss", resolved_profile(chosen, self.catalog)["packs"])
        declined = validate_profile({"personal_data": "no", "name": "Shop", "stack": ["Stripe"], "declined": ["pci-dss-cardholder-data"]},
                                    self.catalog)
        self.assertNotIn("pci-dss", resolved_profile(declined, self.catalog)["packs"])

    def test_iso_27001_maps_each_kind_of_change_to_annex_a_controls(self):
        rules = {rule["id"]: rule for rule in self.catalog["packs"]["iso-27001"]["rules"]}
        expected = {
            "annex-a-access-control": "8.5", "annex-a-cryptography": "8.24", "annex-a-logging-monitoring": "8.15",
            "annex-a-suppliers": "5.19", "annex-a-secure-development": "8.4", "annex-a-networks": "8.20",
            "annex-a-incident-handling": "5.26", "annex-a-assets": "5.9",
        }
        for rule_id, control in expected.items():
            with self.subTest(rule=rule_id):
                self.assertIn("ISO/IEC 27001:2022 Annex A", rules[rule_id]["instruction"])
                self.assertRegex(rules[rule_id]["instruction"], rf"\b{re.escape(control)}\b")
        self.assertEqual(rules["map-applicable-controls"]["evidence"][0]["id"], "statement-of-applicability")

    def test_regulation_packs_name_their_evidence_and_checks(self):
        packs = self.catalog["packs"]
        evidence = {pack_id: {item["id"] for rule in packs[pack_id]["rules"] for item in rule.get("evidence", [])}
                    for pack_id in ("gdpr", "dora")}
        self.assertEqual(evidence["gdpr"], {"processing-record", "dpia-decision"})
        for rule in packs["gdpr"]["rules"]:
            for item in rule.get("evidence", []):
                self.assertEqual(item["when"], {"data": ["personal", "regulated", "unsure"]}, item["id"])
        self.assertIn("register-of-information", evidence["dora"])
        for pack_id in ("nis2", "cyber-resilience-act"):
            checks = [rule["check"] for rule in packs[pack_id]["rules"] if "check" in rule]
            self.assertIn({"kind": "file-exists", "paths": ["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"]},
                          checks, pack_id)

    def test_financial_services_has_dora_and_gdpr_by_default_unless_declined(self):
        default = validate_profile({"name": "Ledger", "sector": "financial-services"}, self.catalog)
        self.assertLessEqual({"dora", "gdpr"}, set(resolved_profile(default, self.catalog)["packs"]))
        no_data = validate_profile({"name": "Ledger", "sector": "financial-services", "personal_data": "no"},
                                   self.catalog)
        self.assertNotIn("gdpr", resolved_profile(no_data, self.catalog)["packs"])
        with tempfile.TemporaryDirectory() as directory:
            # A norm is active only once a person accepts it (#153): init stops until each one is answered.
            write_json(Path(directory) / "answers.json", {"personal_data": "no", "name": "Ledger", "sector": "financial-services"})
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertEqual(main(["--project", directory, "init", "--answers", f"{directory}/answers.json"]), 1)
            self.assertIn("dora-financial-entity", errors.getvalue())
            write_json(Path(directory) / "answers.json", {"personal_data": "no", "name": "Ledger", "sector": "financial-services", "norms": {
                "dora-financial-entity": "yes", "gdpr-personal-data": "yes", "european-accessibility-act": "yes"}})
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--project", directory, "init", "--answers", f"{directory}/answers.json"]), 0)
            created = json.loads((Path(directory) / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
            self.assertLessEqual({"dora", "gdpr"}, set(resolved_profile(created, self.catalog)["packs"]))
        declined = validate_profile({"personal_data": "no", "name": "Ledger", "sector": "financial-services",
                                     "declined": ["gdpr-personal-data", "dora-financial-entity"]}, self.catalog)
        self.assertFalse({"dora", "gdpr"} & set(resolved_profile(declined, self.catalog)["packs"]))


if __name__ == "__main__":
    unittest.main()
