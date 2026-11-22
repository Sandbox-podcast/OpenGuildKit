"""The sector and the roles chosen at setup preselect patterns that the person confirms or declines."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import CatalogError, validate_entry, load_catalog
from openguildkit.cli import _interactive_init, main
from openguildkit.patterns import recommend_patterns
from openguildkit.project import (
    init_questions,
    profile_recommendations,
    resolved_profile,
    rule_plan,
    setup_profile,
    validate_profile,
)
from openguildkit.storage import write_json

SECTOR_PACKS = {
    "healthcare": "health-data-protection",
    "public-sector": "public-sector-accessibility",
    "e-commerce": "online-consumer-sales",
    "education": "minors-data-protection",
    "insurance": "insurance-distribution",
    "critical-infrastructure": "nis2",
}
NEW_PACKS = [pack for pack in SECTOR_PACKS.values() if pack != "nis2"]
RULE_VERB = r"^(Ask|When|For|Add|Make|Keep|Show|Label|Provide|Write|Collect|Test|Record|Present|Do not)\b"


def ids(entries):
    return {entry["id"] for entry in entries}


class SectorPreselectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def recommend(self, **answers):
        return profile_recommendations({"stack": ["Python"], **answers}, self.catalog)

    def test_financial_services_preselects_dora_without_a_legal_or_security_role(self):
        for roles in ([], ["qa"], ["legal", "security"]):
            with self.subTest(roles=roles):
                plan = self.recommend(sector="financial-services", roles=roles)
                dora = next(entry for entry in plan["matched"] if entry["id"] == "dora-financial-entity")
                self.assertIn("sector financial-services", dora["reasons"])
                self.assertIn("dora", plan["recommended_packs"])
                self.assertNotIn("dora-financial-entity", ids(plan["suggested"]))

    def test_dora_declares_its_sectors_and_general_does_not_propose_it_for_the_sector(self):
        pattern = self.catalog["patterns"]["dora-financial-entity"]
        self.assertIn("financial-services", pattern["match"]["sectors"])
        for roles in ([], ["hr", "qa"]):
            plan = self.recommend(sector="general", roles=roles)
            self.assertNotIn("dora-financial-entity", ids(plan["matched"]) | ids(plan["suggested"]))
        legal = self.recommend(sector="general", roles=["legal"])
        self.assertNotIn("dora-financial-entity", ids(legal["matched"]))
        self.assertIn("dora-financial-entity", ids(legal["suggested"]))

    def test_gdpr_is_proposed_for_personal_data_or_the_legal_role_only(self):
        with_data = self.recommend(sector="financial-services", personal_data=True)
        gdpr = next(entry for entry in with_data["matched"] if entry["id"] == "gdpr-personal-data")
        self.assertEqual(gdpr["reasons"], ["sector financial-services", "personal data"])
        without = self.recommend(sector="financial-services", personal_data=False)
        self.assertNotIn("gdpr-personal-data", ids(without["matched"]) | ids(without["suggested"]))
        legal = self.recommend(sector="general", roles=["legal"])
        self.assertIn("gdpr-personal-data", ids(legal["suggested"]))
        self.assertIn("gdpr-personal-data", ids(self.recommend(personal_data="yes")["matched"]))

    def test_init_selects_the_sector_pattern_unless_the_answers_choose_patterns(self):
        profile = validate_profile({"name": "Ledger", "sector": "financial-services"}, self.catalog)
        self.assertIn("dora-financial-entity", profile["patterns"])
        self.assertIn("dora", resolved_profile(profile, self.catalog)["packs"])
        chosen = validate_profile({"name": "Ledger", "sector": "financial-services", "patterns": []}, self.catalog)
        self.assertNotIn("patterns", chosen)

    def test_a_declined_pattern_is_recorded_and_not_proposed_again(self):
        answers = {"name": "Ledger", "sector": "financial-services", "declined": ["dora-financial-entity"]}
        profile = validate_profile(answers, self.catalog)
        self.assertEqual(profile["declined"], ["dora-financial-entity"])
        self.assertNotIn("dora-financial-entity", profile.get("patterns", []))
        plan = profile_recommendations(profile, self.catalog)
        self.assertNotIn("dora-financial-entity", ids(plan["matched"]) | ids(plan["suggested"]))
        self.assertEqual(plan["declined"], ["dora-financial-entity"])
        with self.assertRaisesRegex(ValueError, "both selected and declined"):
            validate_profile({**answers, "patterns": ["dora-financial-entity"]}, self.catalog)
        with self.assertRaisesRegex(ValueError, "Unknown declined"):
            validate_profile({**answers, "declined": ["no-such-pattern"]}, self.catalog)

    def test_a_saved_profile_keeps_its_packs_and_patterns(self):
        saved = {
            "schema_version": 1, "name": "Ledger", "sector": "financial-services", "stack": ["Python"],
            "roles": ["security"], "packs": ["agent-workflow", "python"], "boards": [], "research": "local-only",
            "conventions": [], "checks": [],
        }
        profile = validate_profile(saved, self.catalog)
        self.assertEqual(profile, saved)
        self.assertNotIn("dora", resolved_profile(profile, self.catalog)["packs"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".openguildkit" / "project.json"
            write_json(path, saved)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--project", directory, "sync"]), 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), saved)
            self.assertNotIn("`dora@", (Path(directory) / "AGENTS.md").read_text(encoding="utf-8"))


class RolePreselectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_roles_change_the_preview_and_name_the_role_behind_each_method(self):
        base = {"name": "Portal", "stack": ["Python"]}
        roles = ["security", "legal", "hr", "finance", "qa"]
        without = rule_plan(validate_profile(base, self.catalog), self.catalog)
        with_roles = rule_plan(validate_profile({**base, "roles": roles}, self.catalog), self.catalog)
        self.assertNotEqual(without, with_roles)
        packs = {pack["id"]: pack for pack in with_roles["packs"]}
        self.assertIn("pattern threat-modeling (role security)", packs["threat-modeling"]["provenance"])
        self.assertIn("pattern structured-interviews (role hr)", packs["structured-hiring"]["provenance"])

    def test_a_role_suggests_regulations_without_preselecting_them(self):
        plan = recommend_patterns(self.catalog, [], "general", ["legal", "security"])
        regulations = {pattern_id for pattern_id, pattern in self.catalog["patterns"].items()
                       if pattern.get("kind") == "regulation" and "legal" in pattern["roles"]}
        self.assertTrue({"eu-ai-act-system", "gdpr-personal-data", "nis2-essential-entity"} <= regulations)
        self.assertFalse(regulations & ids(plan["matched"]))
        self.assertLessEqual(regulations, ids(plan["suggested"]))
        self.assertIn("threat-modeling", ids(plan["matched"]))
        for entry in plan["matched"]:
            self.assertTrue(entry["reasons"] and all(reason.startswith("role ") for reason in entry["reasons"]), entry["id"])


class SectorCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_each_new_sector_preselects_a_pattern_with_a_pack(self):
        for sector, pack_id in SECTOR_PACKS.items():
            with self.subTest(sector=sector):
                self.assertIn(sector, self.catalog["sectors"])
                record = self.catalog["sectors"][sector]
                self.assertTrue(record["context"] and record["sources"])
                plan = recommend_patterns(self.catalog, [], sector, [])
                packs = {pack for entry in plan["matched"] for pack in entry["packs"]}
                self.assertIn(pack_id, packs)
                self.assertTrue(all(f"sector {sector}" in entry["reasons"] for entry in plan["matched"]))

    def test_sector_packs_cite_their_text_ask_an_owner_and_claim_no_compliance(self):
        for pack_id in NEW_PACKS:
            pack = self.catalog["packs"][pack_id]
            with self.subTest(pack=pack_id):
                self.assertRegex(pack["description"], r"\bEU\b")
                self.assertRegex(pack["description"], r"do not establish compliance")
                self.assertGreaterEqual(len(pack["sources"]), 2)
                for rule in pack["rules"]:
                    text = f"{rule['instruction']} {rule['verification']}"
                    self.assertRegex(text, r"\b(Art\.|Annex|clause|point)\s")
                    self.assertNotRegex(text, r"(?i)\bcompliant\b|ensures? compliance|certif")
                    self.assertRegex(rule["instruction"], RULE_VERB)
                    self.assertRegex(rule["verification"], r"^(Link|Open|Run|Check|Find|Show|Test)\b")

    def test_catalog_lists_the_sectors_with_the_packs_they_preselect(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(output):
            main(["--project", root, "catalog"])
        text = output.getvalue()
        for sector, pack_id in SECTOR_PACKS.items():
            line = next(line for line in text.splitlines() if line.strip().startswith(sector + " "))
            self.assertIn(pack_id, line)

    def test_a_pattern_can_match_on_its_sector_alone_but_not_on_nothing(self):
        record = {
            "id": "retail-banking-rules", "title": "Retail banking", "description": "Sector rules.", "sources": [],
            "roles": ["legal"], "packs": ["dora"], "kind": "regulation", "match": {"sectors": ["general"]},
        }
        validate_entry("patterns", record)
        for match in ({}, {"min_versions": {"python": "3"}, "sectors": ["general"]}, {"personal_data": False}):
            with self.subTest(match=match), self.assertRaises(CatalogError):
                validate_entry("patterns", {**record, "match": match})
        with self.assertRaises(CatalogError):
            validate_entry("patterns", {**record, "kind": "law"})


class SectorQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_the_sector_question_says_a_project_catalog_can_add_one(self):
        questions = {question["id"]: question for question in init_questions(self.catalog, "Ledger")}
        self.assertIn(".openguildkit/catalog/sectors/", questions["sector"]["prompt"])
        self.assertEqual([choice["id"] for choice in questions["personal_data"]["choices"]], ["yes", "no"])

    def test_a_project_catalog_adds_a_sector_and_its_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            extra = Path(directory)
            write_json(extra / "sectors" / "retail-banking.json", {
                "id": "retail-banking", "title": "Retail banking", "description": "Branch and online banking.",
                "context": ["Ask the compliance owner which supervisor applies."], "sources": [],
            })
            write_json(extra / "patterns" / "retail-banking-dora.json", {
                "id": "retail-banking-dora", "title": "DORA for the bank", "description": "Bank rules.",
                "sources": [], "roles": ["legal"], "packs": ["dora"], "kind": "regulation",
                "match": {"sectors": ["retail-banking"]},
            })
            catalog = load_catalog(extra)
        plan = profile_recommendations({"sector": "retail-banking"}, catalog)
        self.assertIn("retail-banking-dora", ids(plan["matched"]))

    def test_interactive_init_shows_the_preselection_and_records_the_decline(self):
        questions = init_questions(self.catalog, "Ledger")
        # name, sector, stack, roles, personal data, DORA with who and why, the European Accessibility Act kept,
        # patterns, packs, boards, tools, host, guard, research, conventions, checks.
        replies = ["Ledger", "financial-services", "Python", "", "no", "n", "Camille Martin", "Not under DORA Art. 2",
                   "", "python-development", "", "", "", "", "", "", "", ""]
        errors = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=replies), \
                contextlib.redirect_stderr(errors):
            answers = _interactive_init(questions, self.catalog)
        self.assertIn("dora-financial-entity: sector financial-services", errors.getvalue())
        self.assertEqual(answers["patterns"], ["european-accessibility-act", "python-development"])
        decline = {"answer": "no", "by": "Camille Martin", "reason": "Not under DORA Art. 2"}
        self.assertEqual(answers["norms"], {"dora-financial-entity": decline, "european-accessibility-act": "yes"})
        # Each norm shows the description that says when it does not apply.
        self.assertIn("Select when the organization is a financial entity", errors.getvalue())
        self.assertIs(answers["personal_data"], False)
        profile, _ = setup_profile(answers, self.catalog, questions)
        self.assertEqual([entry["id"] for entry in profile["declined"]], ["dora-financial-entity"])
        self.assertEqual(profile["declined"][0]["by"], "Camille Martin")

    def test_recommend_prints_the_reason_and_the_declined_patterns(self):
        with tempfile.TemporaryDirectory() as directory:
            answers = Path(directory) / "answers.json"
            answers.write_text(json.dumps({
                "sector": "insurance", "stack": ["Python"], "declined": ["dora-financial-entity"],
            }), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["--project", directory, "recommend", "--answers", str(answers)])
        text = output.getvalue()
        self.assertIn("insurance-distribution: sector insurance", text)
        self.assertIn("Declined", text)
        self.assertIn("dora-financial-entity", text.split("Declined", 1)[1])


class SoftwarePublisherAndAccessibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def norms(self):
        questions = {question["id"]: question for question in init_questions(self.catalog, "Ledger")}
        return {norm["id"]: norm for norm in questions["norms"]["norms"]}

    def test_the_european_accessibility_act_is_proposed_for_shops_and_banks(self):
        pattern = self.catalog["patterns"]["european-accessibility-act"]
        self.assertEqual(pattern["kind"], "regulation")
        self.assertEqual(set(pattern["match"]["sectors"]), {"e-commerce", "financial-services"})
        self.assertEqual(self.norms()["european-accessibility-act"]["when"],
                         {"sectors": ["e-commerce", "financial-services"]})
        pack = self.catalog["packs"]["european-accessibility-act"]
        self.assertIn("web-accessibility", pack["depends_on"])
        text = " ".join(f"{rule['instruction']} {rule['verification']}" for rule in pack["rules"])
        for fact in ("Art. 2(2)", "Art. 4(5)", "micro-enterprise", "WCAG 2.2 Level AA", "EN 301 549", "Annex V",
                     "Art. 13(2)"):
            self.assertIn(fact, text)
        self.assertIn("https://eur-lex.europa.eu/eli/dir/2019/882/oj/eng", [s["url"] for s in pack["sources"]])
        for sector in ("e-commerce", "financial-services"):
            with self.subTest(sector=sector):
                context = " ".join(self.catalog["sectors"][sector]["context"])
                self.assertIn("Directive (EU) 2019/882", context)
                self.assertIn("28 June 2025", context)
                plan = recommend_patterns(self.catalog, [], sector, [])
                self.assertIn("european-accessibility-act", {entry["id"] for entry in plan["matched"]})

    def test_financial_services_says_to_decline_dora_out_of_scope(self):
        context = self.catalog["sectors"]["financial-services"]["context"][0]
        self.assertIn("preselects the dora-financial-entity", context)
        self.assertIn("decline DORA when it is out of scope", context)
        self.assertNotIn("select the dora-financial-entity pattern", context)

    def test_web_accessibility_targets_wcag_2_2_level_aa(self):
        pack = self.catalog["packs"]["web-accessibility"]
        self.assertIn("WCAG 2.2 Level AA", pack["description"])
        text = " ".join(rule["instruction"] for rule in pack["rules"])
        for criterion in ("1.1.1", "2.4.11", "2.5.8", "3.3.8"):
            self.assertRegex(text, rf"\b{criterion.replace('.', '[.]')}\b")
        self.assertIn("24 by 24 CSS pixels", text)

    def test_a_software_publisher_is_asked_iso_27001_and_the_cra_with_their_condition(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(output):
            main(["--project", root, "catalog"])
        self.assertTrue(any(line.strip().startswith("software-publisher ") for line in output.getvalue().splitlines()))
        norms = self.norms()
        proposed = {norm_id for norm_id, norm in norms.items()
                    if "software-publisher" in norm["when"].get("sectors", [])}
        self.assertEqual(proposed, {"iso-27001-certification", "cyber-resilience-act-product"})
        for norm_id in proposed:
            self.assertIn("the sector is software-publisher", norms[norm_id]["prompt"])
        cra = norms["cyber-resilience-act-product"]
        self.assertIn("SaaS", cra["help"])
        self.assertIn("recital 12", cra["help"])
        self.assertIn("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R2847",
                      [source["url"] for source in cra["sources"]])
        plan = recommend_patterns(self.catalog, [], "software-publisher", [])
        self.assertLessEqual(proposed, {entry["id"] for entry in plan["matched"]})
        resolved = resolved_profile(validate_profile(
            {"name": "Ledger", "sector": "software-publisher", "patterns": sorted(proposed)}, self.catalog),
            self.catalog)
        self.assertLessEqual({"iso-27001", "cyber-resilience-act"}, set(resolved["packs"]))
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory) / "answers.json", {"name": "Ledger", "sector": "software-publisher",
                                                          "personal_data": "no"})
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertEqual(main(["--project", directory, "init", "--answers", f"{directory}/answers.json"]), 1)
            for norm_id in proposed:
                self.assertIn(norm_id, errors.getvalue())


if __name__ == "__main__":
    unittest.main()
