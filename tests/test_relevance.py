"""Only the rules that concern a task are asked when it closes; the others are listed with the reason."""

import unittest

from openguildkit.catalog import load_catalog
from openguildkit.patterns import recommend_patterns
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.relevance import pack_relevance
from openguildkit.results import asked_checks, expected_checks, not_concerned, result_template

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


class RelevanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def task(self, answers, boards=("engineering", "qa", "performance", "security"), profile=None, **extra):
        profile = profile or field_profile(self.catalog)
        packs = resolved_profile(profile, self.catalog)["packs"]
        task = {"id": "csv-injection", "answers": answers, "decision": {"base_revision": None},
                "consultation": {"boards": list(boards), "scope": {"answers": answers, "checks": [],
                                                                    "packs": [self.catalog["packs"][p] for p in packs]}}}
        return task, profile

    def relevance(self, task, profile, changed=None, every=False):
        return {"packs": pack_relevance(task, profile, self.catalog, changed, every), "changed": changed, "every": every}

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
        self.assertEqual(len(template["checks"]) + in_packs + listed,
                         len([c for c in every if c["kind"] in ("rule", "evidence")]))

    def test_personal_data_selects_the_gdpr_rules_and_their_evidence(self):
        task, profile = self.task({**BUG, "kind": "feature", "data": "personal"},
                                  boards=("engineering", "qa", "security", "legal"))
        relevance = self.relevance(task, profile)
        self.assertTrue(relevance["packs"]["gdpr"]["concerned"])
        self.assertTrue(relevance["packs"]["gdpr"]["selected"])
        # Personal data selects the data protection rules, not every regulation of the profile.
        self.assertFalse(relevance["packs"]["incident-notification"]["concerned"])
        self.assertFalse(relevance["packs"]["iso-27001"]["concerned"])
        evidence = [c for c in asked_checks(task, profile, relevance) if c["kind"] == "evidence"]
        self.assertEqual({c["id"] for c in evidence}, {"evidence:gdpr/update-processing-record/processing-record",
                                                       "evidence:gdpr/assess-dpia-need/dpia-decision"})
        self.assertTrue(all(c["must_supply"] for c in evidence))
        self.assertFalse(relevance["packs"]["dora"]["concerned"])

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
                             "assess-dpia-need", "review-processor-terms", "check-transfer-mechanism",
                             "keep-data-subject-rights-working"):
                    self.assertNotIn(f"rule:gdpr/{rule}", asked)
                    self.assertIn(f"kind {kind}", checks[f"rule:gdpr/{rule}"]["reason"])
                    self.assertIn("creates or changes a processing", checks[f"rule:gdpr/{rule}"]["reason"])
                self.assertNotIn("evidence:gdpr/update-processing-record/processing-record", asked)
                template = result_template(task, profile, relevance)
                answers = (len(template["checks"]) + len(template["criteria"])
                           + sum(len(pack["rules"]) for pack in template["packs"]))
                self.assertLess(answers, 25)
        # A feature keeps every GDPR rule, and required_rules keeps a rule whatever the kind.
        task, profile = self.task({**BUG, "kind": "feature", "data": "personal"}, boards=boards)
        asked = {c["id"] for c in asked_checks(task, profile, self.relevance(task, profile))}
        self.assertEqual(len([name for name in asked if name.startswith("rule:gdpr/")]), 8)
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


if __name__ == "__main__":
    unittest.main()
