"""The sector and the roles chosen at setup preselect patterns that the person confirms or declines."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import CatalogError, load_catalog, validate_entry
from openguildkit.cli import main
from openguildkit.init_cli import _interactive_init
from openguildkit.patterns import recommend_patterns
from openguildkit.project import profile_recommendations, validate_profile
from openguildkit.project_rules import resolved_profile, rule_plan
from openguildkit.project_setup import init_questions, setup_profile
from openguildkit.references import load_references
from openguildkit.storage import write_json

SECTOR_PACKS = {
    "healthcare": "health-data-protection",
    "public-sector": "public-sector-accessibility",
    "e-commerce": "online-consumer-sales",
    "education": "minors-data-protection",
    "insurance": "insurance-distribution",
    "critical-infrastructure": "nis2",
    "automotive": "unece-r155",
}
# The vehicle packs speak of a Certificate of Compliance, an object of the UN Regulations: AutomotiveSectorTests
# holds them to the same rules without the word filter that the other sectors' packs pass.
VEHICLE_PACKS = {"unece-r155": "unece-r155-vehicle-cybersecurity", "unece-r156": "unece-r156-software-updates"}
NEW_PACKS = [pack for pack in SECTOR_PACKS.values() if pack != "nis2" and pack not in VEHICLE_PACKS]
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
        # OGK-PROJECT-008, OGK-PROJECT-019
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


class AutomotiveSectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def norms(self):
        questions = {question["id"]: question for question in init_questions(self.catalog, "Ledger")}
        return {norm["id"]: norm for norm in questions["norms"]["norms"]}

    def test_the_sector_preselects_the_two_vehicle_regulations_and_neither_the_cra_nor_nis_2(self):
        plan = recommend_patterns(self.catalog, [], "automotive", [])
        self.assertEqual({entry["id"] for entry in plan["matched"]}, set(VEHICLE_PACKS.values()))
        packs = {pack for entry in plan["matched"] for pack in entry["packs"]}
        self.assertEqual(packs, set(VEHICLE_PACKS))
        for entry in plan["matched"]:
            self.assertEqual(entry["reasons"], ["sector automotive"])
        for pattern_id in VEHICLE_PACKS.values():
            pattern = self.catalog["patterns"][pattern_id]
            self.assertEqual(pattern["kind"], "regulation")
            self.assertEqual(pattern["match"], {"sectors": ["automotive"]})
        # A role suggests a regulation, never preselects it: a legal role in another sector sees them, unselected.
        legal = recommend_patterns(self.catalog, [], "general", ["legal", "engineering", "qa", "security"])
        self.assertFalse(set(VEHICLE_PACKS.values()) & {entry["id"] for entry in legal["matched"]})
        self.assertLessEqual(set(VEHICLE_PACKS.values()), {entry["id"] for entry in legal["suggested"]})

    def test_the_sector_asks_who_the_organization_is_and_what_decides_each_pattern(self):
        record = self.catalog["sectors"]["automotive"]
        context = " ".join(record["context"])
        for fact in ("tier 1", "tier 2", "vehicle manufacturer", "paragraphs 3.1", "fleet", "Annex I", "Annex II row D4",
                     "6 July 2022", "7 July 2024", "does not list UN Regulation No 156",
                     "decline the unece-r156-software-updates pattern when none does",
                     "Art. 2(2)(c)", "recital 27", "does not preselect cyber-resilience-act-product",
                     "2025/1455", "11 December 2027", "NIS 2 Annex II point 5(e)", "nis2-essential-entity",
                     "7.2.2.4(b)", "gdpr-personal-data", "ISO/SAE 21434", "ISO 24089", "ISO 26262", "paid standards"):
            self.assertIn(fact, context)
        self.assertNotRegex(context, r"(?i)\bcompliant\b|ensures? compliance")
        urls = {source["url"] for source in record["sources"]}
        self.assertLessEqual({
            "https://eur-lex.europa.eu/eli/reg/2019/2144/2026-08-02/eng",
            "https://eur-lex.europa.eu/eli/reg/2025/5/oj/eng",
            "https://eur-lex.europa.eu/eli/reg/2021/388/oj/eng",
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R2847",
            "https://eur-lex.europa.eu/eli/reg_del/2025/1455/oj/eng",
            "https://eur-lex.europa.eu/eli/dir/2022/2555/oj/eng",
        }, urls)

    def test_paid_standards_are_cited_by_the_publisher_page_and_never_quoted_by_a_rule(self):
        urls = {source["url"] for source in self.catalog["sectors"]["automotive"]["sources"]}
        self.assertLessEqual({"https://committee.iso.org/standard/70918.html", "https://committee.iso.org/standard/77796.html",
                              "https://committee.iso.org/standard/68383.html"}, urls)
        for pack_id in VEHICLE_PACKS:
            for rule in self.catalog["packs"][pack_id]["rules"]:
                with self.subTest(pack=pack_id, rule=rule["id"]):
                    self.assertNotRegex(f"{rule['instruction']} {rule['verification']}", r"\bISO\b|\bSAE\b|\bIEC\b")
        references = {reference["id"]: reference for family in load_references().values()
                      for reference in family["references"]}
        for reference_id, edition in (("iso-sae-21434", "2021"), ("iso-24089", "2023")):
            with self.subTest(reference=reference_id):
                self.assertEqual(references[reference_id]["kind"], "norme")
                self.assertEqual(references[reference_id]["edition"], edition)
                self.assertNotIn("packs", references[reference_id])
                self.assertTrue(all("iso.org" in source["url"] for source in references[reference_id]["sources"]))

    def test_vehicle_packs_say_who_a_rule_concerns_cite_the_text_and_claim_no_compliance(self):
        for pack_id in VEHICLE_PACKS:
            pack = self.catalog["packs"][pack_id]
            with self.subTest(pack=pack_id):
                self.assertRegex(pack["description"], r"\bEU\b")
                self.assertRegex(pack["description"], r"do not establish compliance")
                self.assertRegex(pack["description"], r"vehicle manufacturer")
                self.assertRegex(pack["description"], r"supplier")
                self.assertGreaterEqual(len(pack["sources"]), 3)
                self.assertGreaterEqual(len(pack["rules"]), 10)
                for rule in pack["rules"]:
                    text = f"{rule['instruction']} {rule['verification']}"
                    self.assertRegex(text, r"\b(Art\.|Annex|paragraphs?)\s", rule["id"])
                    self.assertNotRegex(text, r"(?i)\bcompliant\b|ensures? compliance|you are certified")
                    self.assertRegex(rule["instruction"], RULE_VERB, rule["id"])
                    self.assertRegex(rule["verification"], r"^(Link|Open|Run|Check|Find|Show|Test)\b", rule["id"])
                    self.assertTrue(rule.get("manual"), rule["id"])
                    self.assertNotIn("check", rule)
        # The roles in the approval are asked first, and a supplier has a rule of its own in each pack.
        for pack_id, role_rule, supplier_rule in (("unece-r155", "confirm-r155-role", "agree-supplier-obligations"),
                                                  ("unece-r156", "confirm-r156-role", "agree-update-information")):
            rules = self.catalog["packs"][pack_id]["rules"]
            self.assertEqual(rules[0]["id"], role_rule)
            supplier = next(rule for rule in rules if rule["id"] == supplier_rule)
            self.assertRegex(supplier["instruction"], r"^When the organization (is the supplier|supplies)")

    def test_r155_rules_name_the_paragraphs_that_say_what_they_ask(self):
        pack = self.catalog["packs"]["unece-r155"]
        text = " ".join(f"{rule['instruction']} {rule['verification']}" for rule in pack["rules"])
        for fact in ("paragraphs 3.1", "Annex 5 Part A", "Annex 5 Parts B and C", "7.3.3", "7.3.4", "7.3.5", "7.3.6", "7.3.7",
                     "7.3.8", "7.2.2.2", "7.2.2.4", "7.2.2.5", "7.3.2", "7.4.1", "8.1", "6.7", "6.11",
                     "first registration", "at least once a year"):
            self.assertIn(fact, text)
        for fact in ("Annex II row D4", "6 July 2022", "7 July 2024", "Art. 2(2)(c)", "Supplement 3", "Certificate of Compliance"):
            self.assertIn(fact, pack["description"])
        self.assertIn("https://eur-lex.europa.eu/eli/reg/2025/5/oj/eng", [source["url"] for source in pack["sources"]])

    def test_r156_rules_name_the_paragraphs_and_say_the_eu_act_does_not_list_it(self):
        pack = self.catalog["packs"]["unece-r156"]
        text = " ".join(f"{rule['instruction']} {rule['verification']}" for rule in pack["rules"])
        for fact in ("7.1.1.2", "7.1.1.7", "7.1.1.8", "7.1.2.3", "7.1.2.5", "7.1.3.1", "7.1.3.2", "7.2.1.1", "7.2.1.2",
                     "7.2.2.1", "7.2.2.2", "7.2.2.3", "6.6", "RXSWIN", "SUMS"):
            self.assertIn(fact, text)
        description = pack["description"]
        for fact in ("does not list it in Annex I or Annex II", "recital 27 of Regulation (EU) 2024/2847", "original text", "amendments"):
            self.assertIn(fact, description)
        self.assertIn("https://eur-lex.europa.eu/eli/reg/2021/388/oj/eng", [source["url"] for source in pack["sources"]])

    def test_the_patterns_say_when_they_do_not_apply_and_link_their_references(self):
        for pack_id, pattern_id in VEHICLE_PACKS.items():
            pattern = self.catalog["patterns"][pattern_id]
            with self.subTest(pattern=pattern_id):
                self.assertTrue(pattern["description"].startswith("Preselected for automotive: keep it when"))
                self.assertRegex(pattern["description"], r"Decline it|decline it")
                self.assertEqual(pattern["packs"], [pack_id])
                self.assertGreaterEqual(len(pattern["sources"]), 2)
                self.assertEqual(pattern["references"], [pack_id])
        r155 = self.catalog["patterns"]["unece-r155-vehicle-cybersecurity"]["description"]
        self.assertIn("Regulation (EU) 2019/2144", r155)
        r156 = self.catalog["patterns"]["unece-r156-software-updates"]["description"]
        self.assertIn("does not list UN Regulation No 156", r156)

    def test_init_proposes_both_vehicle_norms_for_automotive_with_their_condition(self):
        norms = self.norms()
        proposed = {norm_id for norm_id, norm in norms.items() if "automotive" in norm["when"].get("sectors", [])}
        self.assertEqual(proposed, set(VEHICLE_PACKS.values()))
        for norm_id in proposed:
            self.assertIn("the sector is automotive", norms[norm_id]["prompt"])
        self.assertIn("vehicle manufacturer", norms["unece-r155-vehicle-cybersecurity"]["help"])
        self.assertIn("https://eur-lex.europa.eu/eli/reg/2019/2144/2026-08-02/eng",
                      [source["url"] for source in norms["unece-r155-vehicle-cybersecurity"]["sources"]])
        resolved = resolved_profile(validate_profile(
            {"name": "Ledger", "sector": "automotive", "patterns": sorted(proposed)}, self.catalog), self.catalog)
        self.assertLessEqual(set(VEHICLE_PACKS), set(resolved["packs"]))
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory) / "answers.json", {"name": "Ledger", "sector": "automotive", "personal_data": "no"})
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertEqual(main(["--project", directory, "init", "--answers", f"{directory}/answers.json"]), 1)
            for norm_id in proposed:
                self.assertIn(norm_id, errors.getvalue())

    def test_a_declined_vehicle_norm_stays_declined_and_the_other_stays_proposed(self):
        answers = {"name": "Ledger", "sector": "automotive", "declined": ["unece-r156-software-updates"]}
        profile = validate_profile(answers, self.catalog)
        self.assertEqual(profile["declined"], ["unece-r156-software-updates"])
        plan = profile_recommendations(profile, self.catalog)
        self.assertNotIn("unece-r156-software-updates", ids(plan["matched"]) | ids(plan["suggested"]))
        self.assertIn("unece-r155-vehicle-cybersecurity", ids(plan["matched"]) | set(profile["patterns"]))


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


FRENCH_PACKS = {
    "france-health-data-hosting": "healthcare",
    "france-rgaa-accessibility": "public-sector",
    "france-public-sector-security": "public-sector",
    "france-cookies-and-trackers": None,
    "france-e-invoicing": None,
}
FRENCH_RULE_VERB = (r"^(Ask|When|For|Add|Make|Keep|Show|Provide|Write|Collect|Test|Record|Present|Do not|Configure|"
                    r"Build|Let|Send|Compute|Generate|Pin|Compare|Use|Host)\b")
FRENCH_HOSTS = ("legifrance.gouv.fr", "cnil.fr", "numerique.gouv.fr", "impots.gouv.fr", "esante.gouv.fr",
                "cyber.gouv.fr", "ssi.gouv.fr", "entreprises.gouv.fr")


class FrenchPackTests(unittest.TestCase):
    """The French packs sit on top of the EU ones: they say France, who they bind and when they do not apply."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def norms(self):
        questions = {question["id"]: question for question in init_questions(self.catalog, "Ledger")}
        return {norm["id"]: norm for norm in questions["norms"]["norms"]}

    def test_each_french_pack_names_france_its_limits_and_claims_no_compliance(self):
        for pack_id in FRENCH_PACKS:
            pack = self.catalog["packs"][pack_id]
            pattern = self.catalog["patterns"][pack_id]
            with self.subTest(pack=pack_id):
                self.assertRegex(pack["description"], r"^France only\.")
                self.assertRegex(pack["description"], r"do not establish compliance")
                self.assertRegex(pack["title"], r"France|French")
                self.assertRegex(pattern["title"] + pattern["description"], r"France|French")
                self.assertEqual(pattern["packs"], [pack_id])
                self.assertEqual(pattern["kind"], "regulation")
                self.assertLessEqual(len(pack["rules"]), 8)
                self.assertGreaterEqual(len(pack["sources"]), 2)
                for rule in pack["rules"]:
                    text = f"{rule['instruction']} {rule['verification']}"
                    self.assertNotRegex(text, r"(?i)\bcompliant\b|ensures? compliance")
                    self.assertRegex(rule["instruction"], FRENCH_RULE_VERB)
                    self.assertRegex(rule["verification"], r"^(Link|Open|Run|Check|Find|Show|Test|Compare|Send)\b")
                    self.assertIn("manual", rule, rule["id"])

    def test_the_sources_of_a_french_pack_are_official_french_pages_opened_on_the_day_of_the_lot(self):
        for pack_id in FRENCH_PACKS:
            for record in (self.catalog["packs"][pack_id], self.catalog["patterns"][pack_id]):
                for source in record["sources"]:
                    host = source["url"].split("/")[2]
                    with self.subTest(pack=pack_id, url=source["url"]):
                        self.assertTrue(any(host == name or host.endswith("." + name) for name in FRENCH_HOSTS), host)
                        self.assertEqual(source["checked"], "2026-11-25")

    def test_the_laws_the_french_rules_cite_are_named_in_the_rules_that_rely_on_them(self):
        text = {pack_id: " ".join(f"{rule['instruction']} {rule['verification']}"
                                  for rule in self.catalog["packs"][pack_id]["rules"]) for pack_id in FRENCH_PACKS}
        for fact in ("Art. L1111-8", "Art. R1111-8-8", "Art. R1111-9", "Art. R1111-11", "EU or EEA"):
            self.assertIn(fact, text["france-health-data-hosting"])
        for fact in ("Art. 47 of loi n° 2005-102", "10 %", "50 %", "Défenseur des droits"):
            self.assertIn(fact, text["france-rgaa-accessibility"])
        for fact in ("Art. 82", "guidelines point 27", "recommendation section 2.3", "6 months"):
            self.assertIn(fact, text["france-cookies-and-trackers"] + self.catalog["packs"]["france-cookies-and-trackers"]["description"])
        for fact in ("décret n° 2010-112", "décret n° 2022-513", "SecNumCloud"):
            self.assertIn(fact, text["france-public-sector-security"])
        for fact in ("plateforme agréée", "XP Z12-012", "SIREN", "Chorus Pro"):
            self.assertIn(fact, text["france-e-invoicing"])

    def test_the_cnil_pack_tells_a_legal_requirement_from_a_recommendation(self):
        for rule in self.catalog["packs"]["france-cookies-and-trackers"]["rules"]:
            with self.subTest(rule=rule["id"]):
                text = f"{rule['instruction']} {rule['verification']}"
                self.assertRegex(text, r"legal requirement|recommend|CNIL considers|guidelines point")

    def test_a_sector_preselects_its_french_patterns_and_the_others_are_only_suggested(self):
        for sector in ("healthcare", "public-sector"):
            plan = recommend_patterns(self.catalog, [], sector, [])
            expected = {pack_id for pack_id, home in FRENCH_PACKS.items() if home == sector}
            self.assertEqual({entry["id"] for entry in plan["matched"] if entry["id"].startswith("france-")}, expected)
            for entry in plan["matched"]:
                self.assertEqual(entry["reasons"], [f"sector {sector}"])
        for pack_id, home in FRENCH_PACKS.items():
            if home is None:
                self.assertNotIn("match", self.catalog["patterns"][pack_id])
                for sector in self.catalog["sectors"]:
                    plan = recommend_patterns(self.catalog, [], sector, [])
                    self.assertNotIn(pack_id, {entry["id"] for entry in plan["matched"]})
        legal = recommend_patterns(self.catalog, [], "general", ["legal"], personal_data=True)
        self.assertLessEqual(set(FRENCH_PACKS), {entry["id"] for entry in legal["suggested"]})
        self.assertFalse(set(FRENCH_PACKS) & {entry["id"] for entry in legal["matched"]})

    def test_the_norms_question_proposes_the_sector_ones_and_says_when_to_decline(self):
        norms = self.norms()
        self.assertEqual(norms["france-health-data-hosting"]["when"], {"sectors": ["healthcare"]})
        for pack_id in ("france-rgaa-accessibility", "france-public-sector-security"):
            self.assertEqual(norms[pack_id]["when"], {"sectors": ["public-sector"]})
        self.assertNotIn("france-cookies-and-trackers", norms)
        self.assertNotIn("france-e-invoicing", norms)
        for pack_id in ("france-health-data-hosting", "france-rgaa-accessibility", "france-public-sector-security"):
            self.assertRegex(norms[pack_id]["help"], r"decline it")

    def test_a_healthcare_project_outside_france_declines_the_hosting_norm_with_who_and_why(self):
        questions = init_questions(self.catalog, "Ledger")
        answers = {"name": "Ledger", "sector": "healthcare", "personal_data": "no",
                   "norms": {"health-data-protection": "yes"}}
        with self.assertRaisesRegex(ValueError, "france-health-data-hosting"):
            setup_profile(answers, self.catalog, questions)
        decline = {"answer": "no", "by": "Camille Martin", "reason": "Hosted in Germany only"}
        profile, _ = setup_profile({**answers, "norms": {**answers["norms"], "france-health-data-hosting": decline}},
                                   self.catalog, questions)
        self.assertEqual([entry["id"] for entry in profile["declined"]], ["france-health-data-hosting"])
        self.assertIn("health-data-protection", profile["patterns"])
        self.assertNotIn("france-health-data-hosting", profile["patterns"])
        kept, _ = setup_profile({**answers, "norms": {**answers["norms"], "france-health-data-hosting": "yes"}},
                                self.catalog, questions)
        self.assertIn("france-health-data-hosting", resolved_profile(kept, self.catalog)["packs"])

    def test_the_sector_contexts_name_the_french_patterns_and_when_to_decline_them(self):
        health = " ".join(self.catalog["sectors"]["healthcare"]["context"])
        self.assertIn("france-health-data-hosting", health)
        self.assertIn("decline it", health)
        public = " ".join(self.catalog["sectors"]["public-sector"]["context"])
        for pack_id in ("france-rgaa-accessibility", "france-public-sector-security"):
            self.assertIn(pack_id, public)
        self.assertIn("decline them", public)

    def test_each_reference_of_a_french_pack_names_it_back(self):
        from openguildkit.references import load_references

        references = {entry["id"]: entry for family in load_references().values() for entry in family["references"]}
        for reference_id, pack_id in (("hds", "france-health-data-hosting"), ("rgaa", "france-rgaa-accessibility"),
                                      ("cnil-cookies", "france-cookies-and-trackers"),
                                      ("facturation-electronique-france", "france-e-invoicing")):
            with self.subTest(reference=reference_id):
                self.assertIn(pack_id, references[reference_id]["packs"])
                self.assertIn(reference_id, self.catalog["patterns"][pack_id]["references"])

    def test_the_e_invoicing_pack_builds_on_the_vat_pack_and_does_not_repeat_its_dates(self):
        pack = self.catalog["packs"]["france-e-invoicing"]
        self.assertEqual(pack["depends_on"], ["vat-and-e-invoicing"])
        self.assertNotIn("meet-french-e-invoicing-dates", {rule["id"] for rule in pack["rules"]})
        resolved = resolved_profile(validate_profile(
            {"name": "Ledger", "patterns": ["france-e-invoicing"]}, self.catalog), self.catalog)
        self.assertLessEqual({"france-e-invoicing", "vat-and-e-invoicing"}, set(resolved["packs"]))


AEROSPACE_PATTERNS = {
    "aviation-information-security": ["aviation-information-security"],
    "airborne-software-assurance": ["airborne-software-assurance", "airworthiness-security"],
}
AEROSPACE_PACKS = ("aviation-information-security", "airborne-software-assurance", "airworthiness-security")
AEROSPACE_RULE_VERB = r"^(Ask|When|For|Keep|Have|Identify|Make|Record|Reassess|Before|Verify)\b"
AEROSPACE_VERIFICATION = r"^(Link|Open|Run|Check|Find|Show|Test|List|Rebuild)\b"


class AerospaceSectorTests(unittest.TestCase):
    """The aerospace sector asks who is in scope, preselects Part-IS and the airborne software packs, and says what is out."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.sector = cls.catalog["sectors"]["aerospace"]

    def source_urls(self, record):
        return [source["url"] for source in record["sources"]]

    def test_the_sector_preselects_its_patterns_with_their_packs_and_general_does_not(self):
        plan = recommend_patterns(self.catalog, [], "aerospace", [])
        self.assertEqual({entry["id"] for entry in plan["matched"]}, set(AEROSPACE_PATTERNS))
        for entry in plan["matched"]:
            with self.subTest(pattern=entry["id"]):
                self.assertEqual(entry["reasons"], ["sector aerospace"])
                self.assertEqual(entry["packs"], AEROSPACE_PATTERNS[entry["id"]])
                pattern = self.catalog["patterns"][entry["id"]]
                self.assertEqual((pattern["kind"], pattern["match"]), ("regulation", {"sectors": ["aerospace"]}))
        general = recommend_patterns(self.catalog, [], "general", ["legal", "security", "qa"])
        self.assertFalse(set(AEROSPACE_PATTERNS) & {entry["id"] for entry in general["matched"]})
        self.assertLessEqual(set(AEROSPACE_PATTERNS), {entry["id"] for entry in general["suggested"]})
        profile = validate_profile({"name": "Avionics", "sector": "aerospace"}, self.catalog)
        self.assertLessEqual(set(AEROSPACE_PATTERNS), set(profile["patterns"]))
        self.assertLessEqual(set(AEROSPACE_PACKS), set(resolved_profile(profile, self.catalog)["packs"]))

    def test_the_sector_asks_who_is_in_scope_and_says_what_is_out_after_the_texts(self):
        context = self.sector["context"]
        self.assertTrue(all(re.match(r"^(Ask|Record|Name|Treat)\b", item) for item in context), context)
        text = " ".join(context)
        for fact in ("Art. 2 of Delegated Regulation (EU) 2022/1645", "Art. 2(1) of Implementing Regulation (EU) 2023/203",
                     "Part 21", "Part-145", "Part-CAMO", "Part-ORO", "Part-ATM/ANS.OR", "U-space",
                     "aviation-information-security", "airborne-software-assurance", "ground handling",
                     "27 March 2031", "Delegated Regulation (EU) 2025/22", "ED-12C / DO-178C",
                     "Regulation (EU) 2018/1139 (Art. 2(3))", "military", "state aircraft", "unmanned aircraft",
                     "NIS 2", "Annex I", "Art. 4", "nis2-essential-entity", "Cyber Resilience Act", "Art. 2(3)",
                     "ED-202B", "DO-326B", "never replace the authority's agreement"):
            self.assertIn(fact, text)
        self.assertRegex(text, r"decline it when no listed organisation is concerned")
        for url in ("https://eur-lex.europa.eu/eli/reg/2018/1139/oj/eng",
                    "https://eur-lex.europa.eu/eli/reg_del/2022/1645/oj/eng",
                    "https://eur-lex.europa.eu/eli/reg_impl/2023/203/oj/eng",
                    "https://eur-lex.europa.eu/eli/reg_del/2025/22/oj/eng",
                    "https://eur-lex.europa.eu/eli/dir/2022/2555/oj/eng"):
            self.assertIn(url, self.source_urls(self.sector))
        self.assertTrue(all(source["checked"] == "2026-11-25" for source in self.sector["sources"]))

    def test_part_is_states_who_it_reaches_its_dates_and_the_clocks_of_its_rules(self):
        pack = self.catalog["packs"]["aviation-information-security"]
        for fact in ("16 October 2025", "22 February 2026", "1 January 2026", "27 March 2031", "ELA2", "Part-ML",
                     "limited certificate", "IS.D.OR.200(e)", "IS.I.OR.200(e)", "Recital 7", "airworthiness-security",
                     "do not establish compliance"):
            self.assertIn(fact, pack["description"])
        rules = {rule["id"]: rule for rule in pack["rules"]}
        self.assertIn("72 hours", rules["file-the-72-hour-report"]["instruction"])
        self.assertIn("design approval holder", rules["file-the-72-hour-report"]["instruction"])
        records = rules["keep-records-five-years"]["instruction"]
        for fact in ("five years", "three years", "controlled access"):
            self.assertIn(fact, records)
        for url in ("https://eur-lex.europa.eu/eli/reg_del/2022/1645/oj/eng",
                    "https://eur-lex.europa.eu/eli/reg_impl/2023/203/oj/eng",
                    "https://eur-lex.europa.eu/eli/reg_del/2025/22/oj/eng",
                    "https://eur-lex.europa.eu/eli/reg_impl/2025/2293/oj/eng",
                    "https://www.easa.europa.eu/en/regulations/information-security",
                    "https://www.easa.europa.eu/en/faq/139292"):
            self.assertIn(url, self.source_urls(pack))
        mapping = rules["map-an-existing-iso-27001-system"]["instruction"]
        self.assertIn("ISO/IEC 27001", mapping)
        self.assertIn("recital 7", mapping)
        self.assertIn("does not apply", self.catalog["patterns"]["aviation-information-security"]["description"])

    def test_the_software_packs_name_the_public_pages_not_the_paid_text_and_never_replace_the_authority(self):
        for pack_id in ("airborne-software-assurance", "airworthiness-security"):
            pack = self.catalog["packs"][pack_id]
            with self.subTest(pack=pack_id):
                self.assertRegex(pack["description"], r"never replace the agreement of the")
                self.assertRegex(pack["description"], r"do not establish compliance")
                self.assertRegex(pack["description"], r"sold by")
                urls = " ".join(self.source_urls(pack))
                self.assertIn("rtca.org", urls)
                self.assertIn("eurocae.net", urls)
                self.assertIn("easa.europa.eu", urls)
                for rule in pack["rules"]:
                    text = f"{rule['instruction']} {rule['verification']}"
                    self.assertNotRegex(text, r"(ED-12C|DO-178C|ED-202[AB]|DO-326[AB])\W+\w*\W*(section|clause|objective|table)")
                    self.assertNotRegex(text, r"(?i)(DO-178C|ED-12C|DO-326A|ED-202A)\s+(requires|states|says|mandates)")
        software = self.catalog["packs"]["airborne-software-assurance"]
        self.assertIn("AMC 20-115D", software["description"])
        self.assertIn("Annex A tables", software["description"])
        security = self.catalog["packs"]["airworthiness-security"]
        for fact in ("AMC 20-42", "ED-202B", "October 2024", "DO-326B", "intentional unauthorised electronic interaction"):
            self.assertIn(fact, security["description"])
        text = " ".join(rule["instruction"] for rule in software["rules"])
        for fact in ("plan for the software aspects of certification", "in both directions", "other than its author",
                     "baseline", "change impact analysis", "qualification", "supplement", "life cycle data"):
            self.assertIn(fact, text)
        self.assertRegex(" ".join(rule["instruction"] for rule in security["rules"]), r"AMC 20-42 section 5\(a\)")

    def test_every_aerospace_rule_is_an_instruction_with_a_verification_and_the_reason_a_person_checks_it(self):
        for pack_id in AEROSPACE_PACKS:
            pack = self.catalog["packs"][pack_id]
            self.assertGreaterEqual(len(pack["rules"]), 7)
            for rule in pack["rules"]:
                with self.subTest(pack=pack_id, rule=rule["id"]):
                    self.assertRegex(rule["instruction"], AEROSPACE_RULE_VERB)
                    self.assertRegex(rule["verification"], AEROSPACE_VERIFICATION)
                    self.assertNotRegex(f"{rule['instruction']} {rule['verification']}",
                                        r"(?i)\bcompliant\b|ensures? compliance|certified by|will be approved")
                    self.assertNotEqual("check" in rule, "manual" in rule)
                    self.assertTrue(rule.get("manual") or rule.get("check"))

    def test_the_norms_question_proposes_both_patterns_for_the_sector_and_the_catalog_lists_its_packs(self):
        questions = {question["id"]: question for question in init_questions(self.catalog, "Avionics")}
        norms = {norm["id"]: norm for norm in questions["norms"]["norms"]}
        for pattern_id in AEROSPACE_PATTERNS:
            self.assertEqual(norms[pattern_id]["when"], {"sectors": ["aerospace"]})
            self.assertIn("the sector is aerospace", norms[pattern_id]["prompt"])
            self.assertIn("does not apply", norms[pattern_id]["help"])
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(output):
            main(["--project", root, "catalog"])
        line = next(line for line in output.getvalue().splitlines() if line.strip().startswith("aerospace "))
        for pack_id in AEROSPACE_PACKS:
            self.assertIn(pack_id, line)


if __name__ == "__main__":
    unittest.main()
