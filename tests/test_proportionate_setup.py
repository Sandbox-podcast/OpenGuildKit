"""Setup preselects what the project needs: core role methods only, norms a person accepts, lenses that apply."""

import contextlib
import copy
import io
import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import CatalogError, load_catalog, validate_entry
from openguildkit.cli import main
from openguildkit.consultation import _board_template
from openguildkit.init_cli import _print_preselection
from openguildkit.project import profile_recommendations, validate_profile
from openguildkit.project_rules import RULE_WARNING, rule_plan
from openguildkit.project_setup import init_questions, setup_profile
from openguildkit.prompts import prompt_questions
from openguildkit.storage import write_json
from tests.support import run_cli

FINTECH = {"name": "payflow", "sector": "financial-services", "personal_data": "yes",
           "stack": ["Python", "FastAPI", "PostgreSQL", "Stripe"], "roles": ["engineering", "security", "finance", "legal"]}
SALES_HR_WEB = {"deal-desk", "meddpicc", "spin-selling", "sales-pipeline", "pay-transparency", "employee-offboarding",
                "employee-onboarding", "structured-interviews", "workforce-planning", "wcag-web-accessibility",
                "web-performance", "frontend-engineering", "search-engine-optimization", "react-web"}


def ids(entries):
    return {entry["id"] for entry in entries}


class CoreMethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_a_role_preselects_only_its_core_methods_and_suggests_the_others_with_a_reason(self):
        plan = profile_recommendations({"stack": [], "roles": ["sales", "hr", "backend"]}, self.catalog)
        self.assertEqual({entry["id"] for entry in plan["matched"]},
                         {"sales-pipeline", "structured-interviews", "backend-services"})
        suggested = {entry["id"]: entry for entry in plan["suggested"]}
        for pattern_id in ("deal-desk", "pay-transparency", "employee-offboarding", "public-api-docs"):
            reason = suggested[pattern_id]["reasons"][0]
            self.assertTrue(reason.startswith("role "), reason)
            self.assertIn(self.catalog["patterns"][pattern_id]["description"], reason)
            self.assertGreater(suggested[pattern_id]["rules"], 0)

    def test_the_fintech_answers_preselect_no_sales_hr_or_web_method(self):
        plan = profile_recommendations(FINTECH, self.catalog)
        self.assertFalse(SALES_HR_WEB & ids(plan["matched"]), ids(plan["matched"]))
        self.assertIn("python-fastapi-postgresql", ids(plan["matched"]))
        self.assertLess(plan["rule_count"], 100)

    def test_the_catalog_marks_one_or_two_core_methods_per_role_and_validates_the_field(self):
        counts = Counter(role for pattern in self.catalog["patterns"].values() for role in pattern.get("core_for", []))
        self.assertTrue(counts and max(counts.values()) <= 2, counts)
        for pattern in self.catalog["patterns"].values():
            if pattern.get("core_for"):
                self.assertEqual(pattern.get("kind", "method"), "method", pattern["id"])
                self.assertNotIn("match", pattern, pattern["id"])
        base = copy.deepcopy(self.catalog["patterns"]["threat-modeling"])
        for bad, message in (({"core_for": ["sales"]}, "roles of the pattern"),
                             ({"core_for": ["security"], "match": {"sectors": ["general"]}}, "without a match")):
            with self.subTest(bad=bad), self.assertRaisesRegex(CatalogError, message):
                validate_entry("patterns", {**base, **bad})

    def test_a_saved_profile_keeps_its_patterns(self):
        saved = {"schema_version": 1, "name": "Ledger", "sector": "general", "stack": ["Python"], "roles": ["sales"],
                 "patterns": ["deal-desk", "meddpicc"], "packs": ["agent-workflow"], "boards": [],
                 "research": "local-only", "conventions": [], "checks": []}
        self.assertEqual(validate_profile(saved, self.catalog), saved)


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def profile(self, **answers):
        base = {"name": "Ledger", "personal_data": "no", **answers}
        return setup_profile(base, self.catalog, init_questions(self.catalog, "Ledger"))[0]

    def test_the_preview_gives_each_pattern_its_reason_and_rules_and_each_regulation_what_it_asks(self):
        no_bank = {"answer": "no", "by": "Camille Martin", "reason": "No consumer banking service"}
        profile = self.profile(**{**FINTECH, "norms": {"dora-financial-entity": "yes", "gdpr-personal-data": "yes",
                                                       "pci-dss-cardholder-data": "yes",
                                                       "european-accessibility-act": no_bank}})
        plan = rule_plan(profile, self.catalog)
        patterns = {entry["id"]: entry for entry in plan["patterns"]}
        self.assertTrue(patterns["dora-financial-entity"]["reason"].startswith("sector financial-services"))
        self.assertTrue(patterns["python-fastapi-postgresql"]["reason"].startswith("stack "))
        regulations = {entry["id"]: entry["asks"] for entry in plan["regulations"]}
        self.assertEqual(set(regulations), {"dora-financial-entity", "gdpr-personal-data", "pci-dss-cardholder-data"})
        self.assertIn("record of processing activities", regulations["gdpr-personal-data"].lower())
        self.assertIn("rules, asked of a task whose data or concerns it touches", regulations["dora-financial-entity"])
        self.assertEqual(plan["rule_count"] > RULE_WARNING, plan["rule_warning"] is not None)

    def test_the_preview_warns_above_the_threshold(self):
        roles = ["sales", "hr", "finance", "marketing", "product", "design", "project-management", "frontend"]
        profile = self.profile(roles=roles, patterns=["deal-desk", "pay-transparency", "revenue-recognition",
                                                      "vat-and-e-invoicing", "frontend-engineering", "kanban",
                                                      "iso-27001-isms", "llm-evaluation", "threat-modeling",
                                                      "service-reliability-sre", "finops", "incident-response",
                                                      "vendor-due-diligence", "owasp-asvs-review"])
        plan = rule_plan(profile, self.catalog)
        self.assertGreater(plan["rule_count"], RULE_WARNING)
        self.assertIn("openguildkit profile decline", plan["rule_warning"])
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory) / "answers.json", {"name": "Ledger", "personal_data": "no", "roles": roles})
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                main(["--project", directory, "preview", "--answers", str(Path(directory) / "answers.json")])
        self.assertIn("rules in force; a task is asked only those that concern it.", output.getvalue())
        self.assertRegex(output.getvalue(), r"\(\d+ rules\)")


    def test_init_shows_each_pattern_with_its_reason_and_rules_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory) / "answers.json", {"name": "Ledger", "personal_data": "no", "roles": ["security"]})
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                main(["--project", directory, "init", "--answers", str(Path(directory) / "answers.json")])
        text = errors.getvalue()
        self.assertIn("Writing these patterns", text)
        self.assertIn("threat-modeling (3 rules): role security", text)
        self.assertIn("rules in force", text)


    def test_recommend_init_and_preview_give_each_pattern_the_same_rule_count(self):
        def counts(text):
            return dict(re.findall(r"^  ([a-z0-9-]+)\b[^\n]*?\((\d+) rules\)", text, re.MULTILINE))

        with tempfile.TemporaryDirectory() as directory:
            answers = Path(directory) / "answers.json"
            write_json(answers, {"name": "Ledger", "personal_data": "no", "stack": ["Python"],
                                 "roles": ["engineering", "security"]})

            def run(*arguments):
                result = run_cli(directory, *arguments)
                return result.stdout + result.stderr

            recommended = counts(run("recommend", "--answers", str(answers)))
            previewed = counts(run("preview", "--answers", str(answers)))
            written = counts(run("init", "--answers", str(answers)))
            saved = counts(run("preview"))
        self.assertTrue({"python-development", "secure-software-lifecycle", "threat-modeling"} <= set(saved), saved)
        for pattern_id, count in saved.items():
            with self.subTest(pattern=pattern_id):
                self.assertEqual({recommended[pattern_id], previewed[pattern_id], written[pattern_id]}, {count})
        self.assertEqual(saved["secure-software-lifecycle"], str(len(self.catalog["packs"]["secure-sdlc"]["rules"])))

    def test_the_interactive_preselection_shows_each_pattern_s_rules(self):
        plan = profile_recommendations({"stack": ["Python"], "roles": ["security"]}, self.catalog)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            _print_preselection(plan, self.catalog)
        self.assertIn("threat-modeling: role security (core method) (3 rules)", errors.getvalue())
        self.assertIn("Each pattern's count is the rules of its own packs", errors.getvalue())


class NormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def setup(self, answers):
        return setup_profile({"name": "Ledger", **answers}, self.catalog, init_questions(self.catalog, "Ledger"))[0]

    def test_a_card_provider_people_decisions_and_personal_data_propose_their_norms(self):
        for answers, norm in (({"stack": ["Python", "Stripe"], "personal_data": "no"}, "pci-dss-cardholder-data"),
                              ({"personal_data": "yes", "people_decisions": "yes"}, "eu-ai-act-system"),
                              ({"personal_data": "yes"}, "gdpr-personal-data")):
            with self.subTest(norm=norm):
                with self.assertRaisesRegex(ValueError, f"Ask the person about each norm.*{norm}"):
                    self.setup(answers)
                accepted = {item: "yes" for item in (norm, "gdpr-personal-data") if answers["personal_data"] == "yes"
                            or item == norm}
                self.assertIn(norm, self.setup({**answers, "norms": accepted})["patterns"])

    def test_a_norm_not_accepted_is_not_active(self):
        no = {"answer": "no", "by": "Camille Martin", "reason": "No card data: payments go through a hosted page"}
        profile = self.setup({"stack": ["Stripe"], "personal_data": "no", "norms": {"pci-dss-cardholder-data": no}})
        self.assertNotIn("pci-dss-cardholder-data", profile.get("patterns", []))
        self.assertEqual(profile["declined"][0]["by"], "Camille Martin")
        lines = rule_plan(profile, self.catalog)["declined"]
        self.assertEqual(lines[0]["reason"], no["reason"])


class QuestionnaireHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_every_question_has_a_one_line_help_and_says_what_unsure_applies(self):
        for question in init_questions(self.catalog, "Ledger"):
            with self.subTest(question=question["id"]):
                self.assertEqual(len(question["help"].splitlines()), 1)
                self.assertLessEqual(len(question["help"]), 120)
                self.assertTrue(question["unsure"])

    def test_an_unsure_answer_applies_the_announced_default_and_init_says_so(self):
        with tempfile.TemporaryDirectory() as directory:
            write_json(Path(directory) / "answers.json",
                       {"name": "Ledger", "personal_data": "unsure", "guard": "?", "norms": {"gdpr-personal-data": "unsure"}})
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertEqual(main(["--project", directory, "init", "--answers",
                                       str(Path(directory) / "answers.json")]), 0)
            profile = json.loads((Path(directory) / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertIs(profile["personal_data"], True)
        self.assertEqual(profile["guard"], "observe")
        self.assertIn("gdpr-personal-data", profile["patterns"])
        self.assertIn("personal_data: unsure, so yes: the protective answer", errors.getvalue())
        self.assertIn("guard: unsure, so the default: observe.", errors.getvalue())

    def test_the_prompt_shows_the_help_and_accepts_a_question_mark(self):
        question = next(item for item in init_questions(self.catalog, "Ledger") if item["id"] == "research")
        errors = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="?"), \
                contextlib.redirect_stderr(errors):
            self.assertEqual(prompt_questions([question], "init"), {"research": "local-only"})
        self.assertIn(question["help"], errors.getvalue())
        self.assertIn("research: unsure, so the default: local-only.", errors.getvalue())


class LensTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_a_service_task_is_not_asked_for_the_browser_lenses(self):
        board = self.catalog["boards"]["engineering"]
        service = [item["id"] for item in _board_template(board, surfaces=["service"])["challenge"]["specialists"]]
        self.assertNotIn("frontend-rendering", service)
        self.assertNotIn("browser-compatibility", service)
        self.assertIn("architecture", service)
        customer = [item["id"] for item in _board_template(board, surfaces=["customer"])["challenge"]["specialists"]]
        self.assertIn("frontend-rendering", customer)
        unsure = [item["id"] for item in _board_template(board, surfaces=["unsure"])["challenge"]["specialists"]]
        self.assertIn("browser-compatibility", unsure)
        finance = self.catalog["boards"]["finance"]
        infra = [item["id"] for item in _board_template(finance, surfaces=["infrastructure"])["challenge"]["specialists"]]
        self.assertFalse({"revenue-accountant", "pricing-and-margin-analyst", "tax-and-invoicing-specialist"} & set(infra))

    def test_the_catalog_validates_applies_to(self):
        board = copy.deepcopy(self.catalog["boards"]["engineering"])
        lens = board["review"]["specialists"][0]
        for value in (["browser"], ["customer", "customer"], ["unsure"]):
            lens["applies_to"] = value
            with self.subTest(value=value), self.assertRaisesRegex(CatalogError, "applies_to"):
                validate_entry("boards", board)
        lens["applies_to"] = ["service", "infrastructure"]
        validate_entry("boards", board)


if __name__ == "__main__":
    unittest.main()
