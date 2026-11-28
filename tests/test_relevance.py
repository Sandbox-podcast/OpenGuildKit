"""Only the rules that concern a task are asked when it closes; the others are listed with the reason."""

import unittest

from openguildkit.catalog import load_catalog
from openguildkit.patterns import recommend_patterns
from openguildkit.project import validate_profile
from openguildkit.project_rules import resolved_profile
from openguildkit.relevance import judge_rules, pack_relevance
from openguildkit.result_form import result_template
from openguildkit.results import asked_checks, expected_checks, not_concerned

# The project of the field check that counted 116 answers for a 20-line bug fix.
FINTECH = {"name": "Ledger", "sector": "financial-services", "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16", "React 18"],
           "roles": ["backend", "design", "devops", "data"]}
BUG = {"kind": "bug", "surface": ["service"], "data": "internal", "research": "local", "concerns": ["none"],
       "outcome": "A cell that starts with = is exported as text."}


def field_profile(catalog: dict) -> dict:
    """The large profile of the field check: every method of its roles, as setup preselected them before #152."""
    plan = recommend_patterns(catalog, FINTECH["stack"], FINTECH["sector"], FINTECH["roles"])
    methods = [entry["id"] for entry in plan["suggested"]
               if entry.get("kind") != "regulation" and not entry.get("choice_required")]
    return validate_profile({**FINTECH, "patterns": [entry["id"] for entry in plan["matched"]] + methods}, catalog)


class RelevanceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def task(self, answers, boards=("engineering", "qa", "performance", "security"), profile=None, **extra):
        profile = profile or field_profile(self.catalog)
        packs = resolved_profile(profile, self.catalog)["packs"]
        task = {"id": "csv-injection", "brief": extra.get("brief", "Fix the export."), "answers": answers,
                "decision": {"base_revision": None},
                "consultation": {"boards": list(boards), "scope": {"answers": answers, "checks": [],
                                                                    "packs": [self.catalog["packs"][p] for p in packs]}}}
        return task, profile

    def relevance(self, task, profile, changed=None, every=False):
        return {"packs": pack_relevance(task, profile, self.catalog, changed, every), "changed": changed, "every": every}


class RelevanceTests(RelevanceCase):
    def test_a_small_bug_fix_in_a_large_profile_asks_fewer_than_25_answers(self):
        task, profile = self.task(BUG)
        every = asked_checks(task, profile, self.relevance(task, profile, every=True))
        self.assertGreater(len(every), 100)
        template = result_template(task, profile, self.relevance(task, profile))
        answers = len(template["checks"]) + len(template["criteria"]) + sum(len(p["rules"]) for p in template["packs"])
        self.assertLess(answers, 25)
        skipped = {entry.get("pack"): entry["reason"] for entry in template["not_concerned"]}
        self.assertIn("its subject is the user interface", skipped["react"])
        self.assertIn("surface includes customer", skipped["react"])
        self.assertIn("security-sensitive changes", skipped["iso-27001"])
        self.assertIn("surface service", skipped["iso-27001"])
        self.assertIn("ai/people-decisions", skipped["llm-evaluations"] + skipped.get("eu-ai-act", "ai/people-decisions"))
        listed = sum(entry["checks"] for entry in template["not_concerned"])
        in_packs = sum(len(pack["rules"]) for pack in template["packs"])
        # A rule with a machine check is recorded by task verify, listed apart from the answers.
        verified = len([item for item in template["recorded_by_verify"] if item["check"].startswith("rule:")])
        self.assertEqual(len(template["checks"]) + in_packs + listed + verified,
                         len([c for c in every if c["kind"] in ("rule", "evidence", "machine")]))

    def test_personal_data_selects_the_gdpr_rules_and_their_evidence(self):
        task, profile = self.task({**BUG, "kind": "feature", "data": "personal"},
                                  boards=("engineering", "qa", "security", "legal"))
        relevance = self.relevance(task, profile)
        self.assertTrue(relevance["packs"]["gdpr"]["concerned"])
        self.assertTrue(relevance["packs"]["gdpr"]["selected"])
        # Personal data selects the data protection rules and the regulations of the entity's ICT systems, and
        # the incident matrix follows them row by row. iso-27001 came for the devops role, which is not consulted.
        self.assertTrue(relevance["packs"]["dora"]["concerned"])
        self.assertTrue(relevance["packs"]["incident-notification"]["concerned"])
        self.assertFalse(relevance["packs"]["iso-27001"]["concerned"])
        evidence = [c for c in asked_checks(task, profile, relevance) if c["kind"] == "evidence"]
        self.assertEqual({c["id"] for c in evidence}, {"evidence:gdpr/update-processing-record/processing-record",
                                                       "evidence:gdpr/assess-dpia-need/dpia-decision",
                                                       "evidence:dora/update-ict-asset-inventory/ict-asset-inventory",
                                                       "evidence:dora/register-ict-third-party/register-of-information"})
        self.assertTrue(all(c["must_supply"] for c in evidence if c["pack"] == "gdpr"))

    def test_a_fix_on_existing_personal_data_is_asked_only_the_gdpr_rules_that_concern_it(self):
        boards = ("engineering", "qa", "security", "legal")
        for kind in ("bug", "maintenance"):
            with self.subTest(kind=kind):
                task, profile = self.task({**BUG, "kind": kind, "data": "personal"}, boards=boards)
                relevance = self.relevance(task, profile)
                checks = {c["id"]: c for c in expected_checks(task, profile, relevance)}
                asked = {name for name, c in checks.items() if c["concerned"]}
                self.assertIn("rule:gdpr/minimise-collected-fields", asked)
                for rule in ("update-processing-record", "confirm-lawful-basis", "apply-retention-period",
                             "assess-dpia-need", "keep-data-subject-rights-working"):
                    self.assertNotIn(f"rule:gdpr/{rule}", asked)
                    self.assertIn(f"kind {kind}", checks[f"rule:gdpr/{rule}"]["reason"])
                    self.assertIn("creates or changes a processing", checks[f"rule:gdpr/{rule}"]["reason"])
                self.assertNotIn("evidence:gdpr/update-processing-record/processing-record", asked)
                # A migration often adds a processor or a transfer; a bug fix almost never.
                for rule in ("review-processor-terms", "check-transfer-mechanism"):
                    if kind == "bug":
                        self.assertNotIn(f"rule:gdpr/{rule}", asked)
                        self.assertIn("a new service provider", checks[f"rule:gdpr/{rule}"]["reason"])
                    else:
                        self.assertIn(f"rule:gdpr/{rule}", asked)
                if kind == "bug":
                    template = result_template(task, profile, relevance)
                    answers = (len(template["checks"]) + len(template["criteria"])
                               + sum(len(pack["rules"]) for pack in template["packs"]))
                    self.assertLess(answers, 25)
        # A feature keeps every GDPR rule but those with a subject of their own (Art. 22 needs decisions about
        # people), and required_rules keeps a rule whatever the kind.
        task, profile = self.task({**BUG, "kind": "feature", "data": "personal"}, boards=boards)
        asked = {c["id"] for c in asked_checks(task, profile, self.relevance(task, profile))}
        self.assertEqual({name for name in asked if name.startswith("rule:gdpr/")},
                         {f"rule:gdpr/{rule['id']}" for rule in self.catalog["packs"]["gdpr"]["rules"]}
                         - {"rule:gdpr/automated-decision"})
        task, profile = self.task({**BUG, "kind": "feature", "data": "personal", "concerns": ["people-decisions"]},
                                  boards=boards)
        self.assertIn("rule:gdpr/automated-decision",
                      {c["id"] for c in asked_checks(task, profile, self.relevance(task, profile))})
        required = validate_profile({**dict(field_profile(self.catalog)), "required_rules": ["gdpr/assess-dpia-need"]},
                                    self.catalog)
        task, profile = self.task({**BUG, "data": "personal"}, boards=boards, profile=required)
        asked = {c["id"] for c in asked_checks(task, profile, self.relevance(task, profile))}
        self.assertIn("rule:gdpr/assess-dpia-need", asked)
        self.assertIn("evidence:gdpr/assess-dpia-need/dpia-decision", asked)
        # Every rule stays available on request.
        task, profile = self.task({**BUG, "data": "personal"}, boards=boards)
        asked = {c["id"] for c in asked_checks(task, profile, self.relevance(task, profile, every=True))}
        self.assertIn("rule:gdpr/confirm-lawful-basis", asked)

    def test_a_method_pack_needs_its_subject_and_a_board_of_its_role(self):
        credentials = {**BUG, "concerns": ["credentials"]}
        task, profile = self.task(credentials, boards=("engineering", "devops"))
        self.assertTrue(self.relevance(task, profile)["packs"]["iso-27001"]["concerned"])
        # A board of its role alone does not bring it: the task must touch its subject.
        task, profile = self.task(BUG, boards=("engineering", "devops"))
        self.assertFalse(self.relevance(task, profile)["packs"]["iso-27001"]["concerned"])
        task, profile = self.task(credentials)
        reason = self.relevance(task, profile)["packs"]["iso-27001"]["reason"]
        self.assertIn("no board of those roles reviewed the task", reason)

    def test_a_named_evidence_with_a_data_condition_is_not_asked_for_other_data(self):
        profile = validate_profile({**FINTECH, "roles": ["security"], "patterns": ["iso-27001-isms"]}, self.catalog)
        task, profile = self.task({**BUG, "concerns": ["credentials"]}, boards=("engineering", "security"),
                                  profile=profile)
        relevance = self.relevance(task, profile)
        self.assertTrue(relevance["packs"]["iso-27001"]["concerned"])
        ids = {c["id"] for c in asked_checks(task, profile, relevance)}
        self.assertIn("evidence:iso-27001/map-applicable-controls/statement-of-applicability", ids)

    def test_a_pack_scoped_to_components_follows_the_changed_files(self):
        profile = validate_profile({
            "name": "Shop", "stack": ["Python"], "packs": ["python"],
            "components": [{"id": "web", "path": "apps/web", "stack": ["React 18"]},
                           {"id": "api", "path": "apps/api", "stack": ["Python"]}],
            "patterns": [{"id": "react-web", "components": ["web"]}],
        }, self.catalog)
        answers = {**BUG, "surface": ["service"]}
        task, profile = self.task(answers, profile=profile)
        self.assertFalse(self.relevance(task, profile, ["apps/api/export.py"])["packs"]["react"]["concerned"])
        self.assertTrue(self.relevance(task, profile, ["apps/web/Table.tsx"])["packs"]["react"]["concerned"])
        # Nothing to compare: the task's surface decides.
        self.assertFalse(self.relevance(task, profile, None)["packs"]["react"]["concerned"])
        task, profile = self.task({**answers, "surface": ["customer"]}, profile=profile)
        self.assertTrue(self.relevance(task, profile, None)["packs"]["react"]["concerned"])

    def test_a_component_at_the_root_or_with_a_trailing_slash_holds_its_files(self):
        for path, inside, outside in ((".", "service/export.py", None), ("apps/api/", "apps/api/export.py", "apps/web/x.ts"),
                                      ("./apps/api", "apps/api/export.py", "apps/apiary/x.py")):
            with self.subTest(path=path):
                profile = validate_profile({
                    "name": "Shop", "stack": ["Python"], "packs": [],
                    "components": [{"id": "api", "path": path, "stack": ["Python", "FastAPI", "PostgreSQL"]}],
                    "patterns": [{"id": "python-fastapi-postgresql", "components": ["api"]}],
                }, self.catalog)
                task, profile = self.task(BUG, profile=profile)
                self.assertTrue(self.relevance(task, profile, [inside])["packs"]["fastapi"]["concerned"])
                if outside:
                    packs = self.relevance(task, profile, [outside])["packs"]
                    self.assertFalse(packs["fastapi"]["concerned"])
                    self.assertIn("no file changed", packs["fastapi"]["reason"])

    def test_every_bundled_pack_has_a_subject(self):
        from openguildkit.relevance import SUBJECTS
        self.assertEqual(set(self.catalog["packs"]) - set(SUBJECTS), set())

    def test_the_profile_can_keep_every_rule_asked(self):
        # OGK-PROJECT-025
        profile = validate_profile({**FINTECH, "ask_every_rule": True}, self.catalog)
        task, profile = self.task(BUG, profile=profile)
        relevance = self.relevance(task, profile)
        self.assertTrue(all(item["concerned"] for item in relevance["packs"].values()))
        self.assertEqual(not_concerned(task, profile, relevance), [])
        with self.assertRaisesRegex(ValueError, "ask_every_rule"):
            validate_profile({**FINTECH, "ask_every_rule": "yes"}, self.catalog)

    def test_an_open_answer_keeps_the_rules_of_that_area(self):
        task, profile = self.task({**BUG, "surface": ["unsure"], "concerns": []})
        packs = self.relevance(task, profile)["packs"]
        self.assertTrue(packs["react"]["concerned"])
        self.assertFalse(packs["react"]["selected"])


class SubjectTests(RelevanceCase):
    """The subjects of the packs reach the tasks a practitioner would hold them to (issue 10 of the second audit)."""

    FEATURE = {**BUG, "kind": "feature", "data": "personal", "outcome": "The onboarding checks the customer's identity."}

    def profile(self, **fields) -> dict:
        return validate_profile({"name": "Bank", "sector": "financial-services", "stack": ["Python 3.12", "FastAPI"],
                                 "roles": ["engineering", "security", "legal"], **fields}, self.catalog)

    def asked(self, task, profile) -> set[str]:
        return {check["id"] for check in asked_checks(task, profile, self.relevance(task, profile))}

    def test_dora_concerns_a_feature_on_personal_data_of_a_financial_entity(self):
        profile = self.profile(patterns=["dora-financial-entity"])
        task, profile = self.task(self.FEATURE, boards=("engineering", "security", "legal"), profile=profile)
        self.assertTrue(self.relevance(task, profile)["packs"]["dora"]["concerned"])
        # A bug fix restores a system as it was: it adds no ICT asset or provider.
        task, profile = self.task({**self.FEATURE, "kind": "bug"}, boards=("engineering", "security", "legal"),
                                  profile=profile)
        self.assertFalse(self.relevance(task, profile)["packs"]["dora"]["concerned"])

    def test_a_new_external_provider_is_asked_the_third_party_rules(self):
        profile = self.profile(patterns=["dora-financial-entity", "iso-27001-isms"])
        task, profile = self.task(self.FEATURE, boards=("engineering", "security", "legal"), profile=profile,
                                  brief="Call an external identity verification API from the onboarding service.")
        asked = self.asked(task, profile)
        self.assertIn("rule:dora/register-ict-third-party", asked)
        self.assertIn("rule:iso-27001/annex-a-suppliers", asked)

    def test_the_security_packs_concern_personal_data_on_a_customer_or_service_surface(self):
        profile = self.profile(patterns=["threat-modeling", "owasp-asvs-review", "iso-27001-isms"])
        for surface in ("customer", "service"):
            with self.subTest(surface=surface):
                task, profile = self.task({**self.FEATURE, "surface": [surface]}, boards=("engineering", "security"),
                                          profile=profile)
                packs = self.relevance(task, profile)["packs"]
                for pack in ("owasp-asvs", "threat-modeling", "iso-27001"):
                    self.assertTrue(packs[pack]["concerned"], pack)
        task, profile = self.task({**self.FEATURE, "data": "internal"}, boards=("engineering", "security"),
                                  profile=profile)
        self.assertFalse(self.relevance(task, profile)["packs"]["threat-modeling"]["concerned"])

    def test_no_bundled_pack_has_an_empty_subject(self):
        from openguildkit.relevance import SUBJECTS
        self.assertEqual([pack for pack, (_, alternatives) in SUBJECTS.items() if alternatives == []], [])

    def test_pay_and_hiring_packs_follow_the_hr_board(self):
        profile = validate_profile({"name": "People", "stack": ["Python"], "roles": ["hr", "finance", "legal"],
                                    "patterns": ["pay-transparency", "structured-interviews"]}, self.catalog)
        salary = {**BUG, "kind": "decision", "surface": ["business"], "data": "internal", "concerns": ["money"]}
        task, profile = self.task(salary, boards=("product", "hr", "finance"), profile=profile,
                                  brief="Set the salary bands of the engineering ladder.")
        self.assertTrue(self.relevance(task, profile)["packs"]["pay-transparency"]["concerned"])
        hiring = {**BUG, "kind": "feature", "surface": ["business"], "data": "personal"}
        task, profile = self.task(hiring, boards=("hr", "legal"), profile=profile,
                                  brief="Prepare the interview loop for the senior engineer hiring.")
        packs = self.relevance(task, profile)["packs"]
        self.assertTrue(packs["structured-hiring"]["concerned"])
        self.assertTrue(packs["pay-transparency"]["concerned"])
        task, profile = self.task(hiring, boards=("hr", "legal"), profile=profile,
                                  brief="Write the onboarding checklist for new employees.")
        packs = self.relevance(task, profile)["packs"]
        self.assertFalse(packs["structured-hiring"]["concerned"])
        self.assertIn("consultation includes the hr board and text names hiring", packs["structured-hiring"]["reason"])

    def test_finops_concerns_a_spending_task_reviewed_by_finance_or_devops(self):
        profile = validate_profile({"name": "Ops", "stack": ["Python"], "roles": ["finance", "devops"],
                                    "patterns": ["finops"]}, self.catalog)
        budget = {**BUG, "kind": "feature", "surface": ["business"], "concerns": ["money"]}
        for boards in (("finance",), ("devops",)):
            with self.subTest(boards=boards):
                task, profile = self.task(budget, boards=boards, profile=profile, brief="Plan next year's cloud budget.")
                self.assertTrue(self.relevance(task, profile)["packs"]["finops-cost-management"]["concerned"])

    def test_the_agent_native_pack_concerns_infrastructure_and_delivery_only(self):
        profile = validate_profile({"name": "Agents", "stack": ["Python"], "roles": ["engineering", "devops"],
                                    "patterns": ["agent-native-repository"]}, self.catalog)
        tooling = {**BUG, "kind": "maintenance", "surface": ["infrastructure"]}
        task, profile = self.task(tooling, boards=("engineering", "devops"), profile=profile,
                                  brief="Bound the output of the test runner.")
        self.assertTrue(self.relevance(task, profile)["packs"]["agent-native-engineering"]["concerned"])
        task, profile = self.task(BUG, boards=("engineering", "devops"), profile=profile)
        self.assertFalse(self.relevance(task, profile)["packs"]["agent-native-engineering"]["concerned"])

    def test_the_agentic_security_pack_concerns_tasks_about_agents_and_mcp_only(self):
        profile = validate_profile({"name": "Agents", "stack": ["Python", "MCP"], "roles": ["engineering", "security"]},
                                   self.catalog)
        self.assertIn("agentic-application-security", resolved_profile(profile, self.catalog)["packs"])
        boards = ("engineering", "security")
        task, profile = self.task(BUG, boards=boards, profile=profile, brief="Fix the CSV export of invoices.")
        packs = self.relevance(task, profile)["packs"]
        self.assertFalse(packs["agentic-application-security"]["concerned"])
        self.assertIn("text names agents and MCP", packs["agentic-application-security"]["reason"])
        # A support agent or a sales agent is a person, not an AI agent.
        task, profile = self.task({**BUG, "kind": "feature"}, boards=boards, profile=profile,
                                  brief="Let the support agent reassign a ticket to another team.")
        self.assertFalse(self.relevance(task, profile)["packs"]["agentic-application-security"]["concerned"])
        for answers, brief in (({**BUG, "concerns": ["ai"]}, "Fix the export."),
                               ({**BUG, "kind": "feature"}, "Add an MCP server to our product."),
                               ({**BUG, "kind": "feature"}, "Ajouter un serveur MCP à notre produit."),
                               ({**BUG, "kind": "feature"}, "Expose the ticket search as a tool for AI agents.")):
            with self.subTest(brief=brief, concerns=answers["concerns"]):
                task, profile = self.task(answers, boards=boards, profile=profile, brief=brief)
                self.assertTrue(self.relevance(task, profile)["packs"]["agentic-application-security"]["concerned"])

    def test_pci_dss_needs_regulated_data_or_cards_and_payments_named(self):
        profile = self.profile(patterns=["pci-dss-cardholder-data"])
        proration = {**BUG, "kind": "feature", "data": "internal", "concerns": ["money"]}
        task, profile = self.task(proration, boards=("engineering", "finance"), profile=profile,
                                  brief="Prorate the monthly plan when a customer upgrades mid-cycle.")
        packs = self.relevance(task, profile)["packs"]
        self.assertFalse(packs["pci-dss"]["concerned"])
        self.assertIn("text names card payments", packs["pci-dss"]["reason"])
        for brief in ("Retry a declined card payment once at checkout.", "Ajouter le paiement par carte bancaire."):
            with self.subTest(brief=brief):
                task, profile = self.task(proration, boards=("engineering", "finance"), profile=profile, brief=brief)
                self.assertTrue(self.relevance(task, profile)["packs"]["pci-dss"]["concerned"])
        task, profile = self.task(proration, boards=("engineering", "finance"), profile=profile,
                                  brief="Prorate the plan; no card payment changes.")
        self.assertFalse(self.relevance(task, profile)["packs"]["pci-dss"]["concerned"])

    def test_a_migration_keeps_the_processor_and_transfer_rules_and_a_bug_does_not(self):
        from openguildkit.relevance import rule_not_concerned
        for rule in ("review-processor-terms", "check-transfer-mechanism"):
            with self.subTest(rule=rule):
                self.assertEqual(rule_not_concerned({"answers": {"kind": "maintenance"}}, "gdpr", rule), "")
                self.assertIn("kind bug", rule_not_concerned({"answers": {"kind": "bug"}}, "gdpr", rule))
        self.assertIn("kind maintenance",
                      rule_not_concerned({"answers": {"kind": "maintenance"}}, "gdpr", "update-processing-record"))

    def test_each_incident_row_follows_the_pack_of_its_regulation(self):
        profile = self.profile(patterns=["gdpr-personal-data", "dora-financial-entity"])
        task, profile = self.task(self.FEATURE, boards=("engineering", "security", "legal"), profile=profile)
        asked = self.asked(task, profile)
        for row in ("keep-notification-matrix", "gdpr-personal-data-breach", "dora-major-ict-incident"):
            self.assertIn(f"rule:incident-notification/{row}", asked)
        for row in ("nis2-significant-incident", "cra-actively-exploited-vulnerability", "ai-act-serious-incident"):
            self.assertNotIn(f"rule:incident-notification/{row}", asked)
        checks = {check["id"]: check for check in expected_checks(task, profile, self.relevance(task, profile))}
        self.assertIn("the pack of the row's regulation is not in force",
                      checks["rule:incident-notification/nis2-significant-incident"]["reason"])
        # Without personal data and without its own subject, no row and no matrix are asked.
        task, profile = self.task({**self.FEATURE, "data": "internal"}, boards=("engineering", "security"),
                                  profile=profile)
        packs = self.relevance(task, profile)["packs"]
        self.assertFalse(packs["incident-notification"]["concerned"])
        self.assertIn("its rows follow gdpr, dora", packs["incident-notification"]["reason"])

    def test_a_rule_with_a_subject_of_its_own_follows_it(self):
        """The hook of a GDPR Art. 22 rule: gdpr/automated-decision is asked when software decides about people."""
        profile = self.profile(patterns=["gdpr-personal-data"])
        rule = {"id": "automated-decision", "instruction": "Check Art. 22.", "verification": "Recorded."}
        for concerns, asked in ((["none"], False), (["people-decisions"], True), (["unsure"], True)):
            with self.subTest(concerns=concerns):
                task, profile = self.task({**self.FEATURE, "concerns": concerns}, boards=("legal",), profile=profile)
                packs = task["consultation"]["scope"]["packs"]
                index = next(index for index, pack in enumerate(packs) if pack["id"] == "gdpr")
                packs[index] = {**packs[index], "rules": [*packs[index]["rules"], rule]}
                judged = judge_rules(task, profile, self.relevance(task, profile))
                self.assertEqual(judged["gdpr/automated-decision"]["concerned"], asked)
                if not asked:
                    self.assertIn("automated decisions about people", judged["gdpr/automated-decision"]["reason"])

    def test_every_regulatory_pack_states_its_subject_and_legal_reason(self):
        from openguildkit.legal_basis import LEGAL_BASIS
        regulatory = {pack for pattern in self.catalog["patterns"].values() if pattern.get("kind") == "regulation"
                      for pack in pattern["packs"]}
        regulatory |= {"incident-notification", "notice-and-action", "pay-transparency", "iso-27001"}
        self.assertEqual(regulatory - set(LEGAL_BASIS), set())
        for pack, reason in LEGAL_BASIS.items():
            self.assertRegex(reason, r"Art\. |Annex|PCI DSS|WCAG|impots\.gouv\.fr", pack)


if __name__ == "__main__":
    unittest.main()
