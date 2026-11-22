"""Briefs that must, or must not, reach each brain. CI runs them on every catalog change."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import main

from openguildkit.catalog import load_catalog
from openguildkit.storage import write_json
from openguildkit.workflow import (
    consult, normalize_text, normalize_with_offsets, require_concerns, select_boards, text_routes, trigger_matches,
    validate_answers,
)

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

    def test_concerns_are_checked_and_none_or_unsure_stand_alone(self):
        # A recorded answer file without concerns still reads; task consult and task route ask for it (require_concerns).
        self.assertNotIn("concerns", validate_answers(NEUTRAL))
        with self.assertRaisesRegex(ValueError, "Answer concerns.*none, unsure"):
            require_concerns(validate_answers(NEUTRAL))
        self.assertEqual(validate_answers({**NEUTRAL, "concerns": "money"})["concerns"], ["money"])
        with self.assertRaisesRegex(ValueError, "concerns"):
            validate_answers({**NEUTRAL, "concerns": ["money", "weather"]})
        for alone in ("none", "unsure"):
            with self.assertRaisesRegex(ValueError, alone):
                validate_answers({**NEUTRAL, "concerns": ["money", alone]})

    def test_unsure_concerns_route_the_boards_of_every_topic(self):
        routing = self.route("Change how the scheduler picks the next item", {**NEUTRAL, "concerns": ["unsure"]})["routing"]
        self.assertLessEqual({"legal", "data", "security", "finance", "devops"}, set(routing))
        self.assertIn("Concerns unsure, so this topic stays open: Money: prices, payments, invoices, payroll or spending",
                      routing["finance"])
        selected = self.route("Use AI to screen and rank job applicants", {**NEUTRAL, "concerns": ["unsure"]})
        self.assertEqual(selected["patterns"], self.route("Use AI to screen and rank job applicants")["patterns"])

    def test_an_unrecognised_brief_asks_the_requester_to_pick_boards(self):
        routing = self.route("Tidy things up")["routing"]
        self.assertEqual(list(routing), ["product"])
        self.assertIn("No discipline recognised", routing["product"][0])
        self.assertIn("--add", routing["product"][0])

    def test_a_negated_mention_selects_no_board_and_is_shown_as_excluded(self):
        brief = "Add a CSV export to the report page. No personal data, no payments, no AI, nothing customer-facing, " \
                "no budget impact."
        answers = {"kind": "bug", "surface": "service", "data": "none", "research": "local", "concerns": ["none"],
                   "context": "CSV export of the monthly report. No personal data, no payments, no AI model, "
                              "no customer screen."}
        selected = self.route(brief, answers)
        for board in ("data", "finance", "security"):
            self.assertNotIn(board, selected["routing"])
        self.assertIn("no payments", selected["excluded"]["finance"])
        self.assertIn("no budget", selected["excluded"]["finance"])
        self.assertIn("No personal data", selected["excluded"]["security"])
        self.assertIn("no AI model", selected["excluded"]["data"])
        self.assertNotIn("finance", selected["not_selected"])
        self.assertIn("legal", selected["not_selected"])
        self.assertNotIn("legal", selected["expected_not_selected"])

    def test_negations_in_english_and_french(self):
        negated = {
            "Export the report without personal data": "security",
            "Rename the export button; it does not touch the API": "engineering",
            "Réécrire l'export sans paiement": "finance",
            "Aucune donnée personnelle dans cet export": "security",
            "Pas de changement d'interface utilisateur": "design",
            "Neither invoices nor payments change": "finance",
            "Rename the job; no vendor, no contract": "procurement",
        }
        for brief, board in negated.items():
            with self.subTest(brief=brief):
                self.assertNotIn(board, text_routes(self.boards, brief))
        kept = {
            "Not only payments but also invoices": "finance",
            "The export is not without personal data": "security",
            "Ce n'est pas sans paiement": "finance",
            "No CSV export: payments go to the ledger": "finance",
            "Allow no more than 2 API calls": "engineering",
            "Sans doute du paiement": "finance",
            "No downtime\n- payment retries": "finance",
        }
        for brief, board in kept.items():
            with self.subTest(brief=brief):
                self.assertIn(board, text_routes(self.boards, brief))

    def test_a_negated_concept_term_does_not_route_the_concept(self):
        self.assertNotIn("legal", text_routes(self.boards, "Rank the applicants by date, no AI and no model"))
        self.assertIn("legal", text_routes(self.boards, "Rank the applicants with an AI model"))

    def test_a_reason_quotes_the_passage_that_triggered_it(self):
        routes = text_routes(self.boards, "Decide whether to adopt Stripe or Adyen for card payments")
        self.assertIn("Brief mentions 'payment': \"Adyen for card payments\"", routes["finance"])
        french =text_routes(self.boards, "Masquer les données personnelles des clients")
        self.assertIn("\"Masquer les données personnelles des clients\"", french["security"][0])

    def test_the_passage_offsets_follow_the_normalised_text(self):
        for sample in ("Sécurité  DES Données", "l’appel d’offres", "Straße/ÉTÉ_x", " a\n\tb ", "İstanbul ﬁle"):
            with self.subTest(sample=sample):
                normalized, offsets = normalize_with_offsets(sample)
                self.assertEqual(normalized, normalize_text(sample))
                self.assertEqual(len(offsets), len(normalized))

    def test_a_declared_role_that_the_task_serves_is_proposed(self):
        profile = {"name": "Support tools", "sector": "general", "packs": [], "boards": [],
                   "roles": ["support", "customer-success", "communication"]}
        answers = {**NEUTRAL, "kind": "feature", "surface": ["business", "service"], "data": "personal",
                   "affected": "Support managers who paste the weekly numbers into a spreadsheet."}
        routing = self.route("Let the weekly report be written as a CSV file with --csv", answers, profile)["routing"]
        self.assertIn("support", routing)
        self.assertIn("\"Support managers", routing["support"][0])
        self.assertNotIn("customer-success", routing)
        answers["affected"] = "The support team and customer-success managers"
        routing = self.route("Let the weekly report be written as a CSV file with --csv", answers, profile)["routing"]
        self.assertLessEqual({"support", "customer-success"}, set(routing))
        answers["affected"] = "Not the support team: finance analysts only"
        routing = self.route("Let the weekly report be written as a CSV file with --csv", answers, profile)["routing"]
        self.assertNotIn("support", routing)
        undeclared = {**profile, "roles": []}
        answers["affected"] = "Support managers"
        self.assertNotIn("support", self.route("Let the weekly report be written as a CSV file", answers,
                                               undeclared)["routing"])

    def test_the_route_lists_the_boards_left_out(self):
        profile = {"name": "Api", "sector": "general", "packs": [], "boards": ["backend", "devops", "qa", "security"]}
        answers = {**NEUTRAL, "kind": "bug", "surface": ["service"], "data": "internal"}
        selected = self.route("Neutralise formula characters in every CSV export", answers, profile)
        self.assertEqual(set(selected["routing"]), {"qa", "security"})
        self.assertEqual(selected["not_selected"], ["backend", "devops"])
        self.assertEqual(selected["excluded"], {})

    def test_a_negation_that_asks_for_the_subject_keeps_the_board_and_says_why(self):
        kept = text_routes(self.boards, "Sans paiement, la commande n'est pas validée : corriger ce cas")
        self.assertIn("may name what is needed", kept["finance"][0])
        self.assertNotIn("may name", text_routes(self.boards, "Do not forget payments in the checkout")["finance"][0])

    def test_the_items_of_a_negated_list_are_all_excluded(self):
        selected = self.route("Rename the job without touching personal data or secrets")
        self.assertEqual(selected["excluded"]["security"], ["without touching personal data or secrets"])

    def test_the_consultation_shows_what_the_brief_excludes(self):
        profile = {"name": "Portal", "sector": "general", "packs": [], "boards": []}
        answers = {**NEUTRAL, "kind": "feature", "surface": ["service"], "context": "No payments involved."}
        consultation = consult(profile, self.catalog, {"id": "t", "brief": "Add a CSV export", "answers": answers})
        self.assertIn("Mentioned as excluded, not consulted: finance (No payments)", consultation["markdown"])
        self.assertEqual(consultation["excluded"], {"finance": ["No payments"]})

    def test_a_quote_comes_from_one_text_and_ends_on_a_word(self):
        answers = {**NEUTRAL, "context": "Answer questions with an LLM", "affected": "x users"}
        routing = self.route("Add a help widget", answers)["routing"]
        self.assertIn('Brief mentions \'llm\': "questions with an LLM"', routing["data"])
        self.assertFalse(any("users" in reason for reason in routing["data"]), routing["data"])
        routes = text_routes(self.boards, "Move the payments to the ledger of the shop")
        self.assertIn('"Move the payments to the ledger"', routes["finance"][0])

    def test_the_audience_named_in_the_brief_or_context_selects_a_declared_role(self):
        profile = {"name": "Support tools", "sector": "general", "packs": [], "boards": [],
                   "roles": ["support", "customer-success"]}
        answers = {**NEUTRAL, "kind": "feature", "surface": ["business"], "affected": "users"}
        routing = self.route("Zendesk ticket report for our support agents", answers, profile)["routing"]
        self.assertIn('"report for our support agents"', routing["support"][-1])
        answers["context"] = "Audience: support team and customer-success managers"
        routing = self.route("Weekly ticket report", answers, profile)["routing"]
        self.assertLessEqual({"support", "customer-success"}, set(routing))
        answers["context"] = "Public : l'équipe support"
        self.assertIn("support", self.route("Rapport hebdomadaire des tickets", answers, profile)["routing"])
        answers["context"] = "Add support for Safari 16"
        self.assertNotIn("support", self.route("Fix the layout", answers, profile)["routing"])

    def test_a_hyphenated_role_further_in_an_audience_list_is_selected(self):
        profile = {"name": "Support tools", "sector": "general", "packs": [], "boards": [],
                   "roles": ["support", "customer-success"]}
        for field, text in (("context", "Read by the support team and customer-success managers"),
                            ("context", "Pour l'équipe support et les responsables customer-success"),
                            ("affected", "The support team and customer-success managers")):
            with self.subTest(text=text):
                answers = {**NEUTRAL, "kind": "feature", "surface": ["business"], field: text}
                selected = self.route("Weekly ticket report", answers, profile)
                self.assertLessEqual({"support", "customer-success"}, set(selected["routing"]))
                self.assertNotIn("customer-success", selected["expected_not_selected"])

    def test_the_boards_the_team_expects_get_a_reason_each(self):
        profile = {"name": "Shop", "sector": "general", "packs": [], "boards": [], "roles": ["backend", "finance"]}
        answers = {**NEUTRAL, "kind": "bug", "surface": ["customer"]}
        selected = self.route("Fix the colour of the header", answers, profile)
        self.assertEqual(set(selected["expected_not_selected"]), {"backend", "finance"})
        self.assertIn("declared role", selected["expected_not_selected"]["backend"])
        self.assertIn("backend, server-side", selected["expected_not_selected"]["backend"])
        self.assertIn("legal", selected["not_selected"])
        self.assertNotIn("legal", selected["expected_not_selected"])

    def test_dora_metrics_and_service_discovery_are_not_regulation_or_product(self):
        self.assertNotIn("legal", text_routes(self.boards, "Track DORA lead time for changes"))
        self.assertNotIn("security", text_routes(self.boards, "Report the DORA change failure rate"))
        self.assertNotIn("product", text_routes(self.boards, "Fix the service discovery timeout in Consul"))
        self.assertIn("product", text_routes(self.boards, "Plan the product discovery interviews"))
        self.assertNotIn("discovery", self.boards["product"]["triggers"])

    def test_a_negated_word_routes_no_brain(self):
        text = "No personal data, no payments, no AI model, no customer screen"
        self.assertEqual(text_routes(self.boards, text), {})
        for brief in ("Sans paiement ni budget", "Pas de paiement, aucun budget", "without any payment"):
            with self.subTest(brief=brief):
                self.assertNotIn("finance", text_routes(self.boards, brief))

    def test_a_comma_or_but_ends_the_negation(self):
        self.assertIn("finance", text_routes(self.boards, "No customer screen, but a payment retry"))
        self.assertIn("finance", text_routes(self.boards, "Users must not exceed the budget"))

    def test_the_reason_quotes_the_passage_that_routes_a_brain(self):
        reasons = text_routes(self.boards, "Add billing and payment retries")["finance"]
        self.assertTrue(all("add billing and payment retries" in reason.casefold() for reason in reasons), reasons)

    def test_the_route_lists_the_boards_it_leaves_out_and_how_to_change_them(self):
        profile = {"name": "Portal", "sector": "general", "packs": [], "boards": [], "roles": ["support"]}
        routed = self.route("A weekly report for the support team", profile=profile)
        self.assertIn("support", routed["routing"])
        self.assertTrue(any("Declared role" in reason for reason in routed["routing"]["support"]), routed["routing"])
        left_out = set(routed["not_selected"])
        self.assertNotIn("support", left_out)
        self.assertIn("finance", left_out)
        self.assertEqual(left_out | set(routed["routing"]) | set(routed["excluded"]), set(self.boards))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "p.json", profile)
            write_json(root / "a.json", {**NEUTRAL, "concerns": ["none"]})
            run = lambda *args: main(["--project", str(root), *map(str, args)])
            with contextlib.redirect_stdout(io.StringIO()):
                run("init", "--answers", root / "p.json")
                run("task", "new", "A weekly report for the support team", "--id", "report")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(run("task", "route", "report", "--answers", root / "a.json"), 0)
        self.assertIn("--add BOARD --remove BOARD --reason TEXT", out.getvalue())



class RouteOutputTests(unittest.TestCase):
    def cli(self, root: Path, *arguments) -> str:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--project", str(root), *map(str, arguments)])
        self.assertEqual(code, 0, err.getvalue())
        return out.getvalue()

    def test_route_explains_exclusions_left_out_boards_tools_and_how_to_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "setup.json").write_text(json.dumps({
                "name": "Support tools", "sector": "general", "stack": ["Python"], "personal_data": "no",
                "roles": ["support", "engineering"], "boards": ["engineering", "product", "qa", "finance", "support"],
                "host": "other", "guard": "off", "research": "local-only"}), encoding="utf-8")
            (root / "answers.json").write_text(json.dumps({
                "kind": "bug", "surface": "service", "data": "none", "research": "local", "concerns": ["none"],
                "context": "No payments involved.", "affected": "Support managers"}), encoding="utf-8")
            self.cli(root, "init", "--answers", root / "setup.json")
            self.cli(root, "tools", "apply", "zendesk", "--mock", "--host", "claude-code")
            self.cli(root, "task", "new", "Write the weekly report as a CSV file", "--id", "report-csv")
            route = self.cli(root, "task", "route", "report-csv", "--answers", root / "answers.json")
            self.assertIn('support: Declared role of the project, and the task is for "Support managers"', route)
            self.assertIn("  tools: Zendesk (connected)", route)
            self.assertIn("Mentioned as excluded: finance (No payments)", route)
            self.assertNotIn("finance:", route)
            self.assertIn("Not selected, although the project expects them:\n  product: enabled in the profile", route)
            self.assertNotIn("Other boards", route)
            self.assertIn("--add BOARD --remove BOARD --reason TEXT", route)
            answers = (root / "answers.json").as_posix()
            route = self.cli(root, "task", "route", "report-csv", "--answers", root / "answers.json",
                             "--add", "product", "--remove", "qa", "--reason", "Scope only, tests exist")
            self.assertIn(f'Apply: openguildkit task consult report-csv --answers {answers} --add product '
                          f'--remove qa --reason "Scope only, tests exist"', route)
            selected = json.loads(self.cli(root, "task", "route", "report-csv", "--answers", root / "answers.json",
                                           "--json"))
            self.assertEqual(selected["excluded"], {"finance": ["No payments"]})

    def test_route_shows_the_tools_of_the_project_and_who_can_query_a_named_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "setup.json").write_text(json.dumps({
                "name": "Support tools", "sector": "general", "stack": ["Python"], "personal_data": "no",
                "roles": ["support", "customer-success"], "tools": ["Zendesk", "Jira"],
                "host": "other", "guard": "off", "research": "local-only"}), encoding="utf-8")
            (root / "answers.json").write_text(json.dumps({
                "kind": "feature", "surface": "business", "data": "none", "research": "local", "concerns": ["none"],
                "context": "Audience: support agents", "affected": "users"}), encoding="utf-8")
            self.cli(root, "init", "--answers", root / "setup.json")
            self.cli(root, "task", "new", "Zendesk ticket report for our support agents", "--id", "report")
            route = self.cli(root, "task", "route", "report", "--answers", root / "answers.json")
            self.assertIn("  tools: Zendesk (listed, not connected)", route)
            self.assertIn("The brief names Zendesk: support (selected) can query it; customer-success, operations, "
                          "trust-and-safety could, with --add.", route)
            self.assertIn("Other boards you can add with --add:", route)


if __name__ == "__main__":
    unittest.main()
