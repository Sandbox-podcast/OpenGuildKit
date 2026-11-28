import json
import unittest

from openguildkit.catalog import CatalogError, load_catalog, validate_entry
from openguildkit.consultation import consult
from openguildkit.project import validate_profile
from openguildkit.project_instructions import render_instructions
from openguildkit.project_rules import resolved_profile, rule_plan


class RulePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        # No bundled packs conflict today: declare one so the resolution flow stays covered.
        cls.conflicting = json.loads(json.dumps(cls.catalog))
        cls.conflicting["packs"]["scrum-delivery"]["conflicts_with"] = ["kanban-delivery"]

    def test_plan_shows_version_origin_and_scope_of_every_pack(self):
        answers = {
            "name": "Portal",
            "components": [{"id": "api", "path": "services/api", "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16"]}],
            "conventions": ["Use Conventional Commits."],
            "checks": ["python -m pytest"],
        }
        plan = rule_plan(validate_profile(answers, self.catalog), self.catalog)
        packs = {pack["id"]: pack for pack in plan["packs"]}
        self.assertEqual(packs["agent-workflow"]["provenance"], ["required by OpenGuildKit"])
        self.assertIn("pattern python-fastapi-postgresql", packs["fastapi"]["provenance"])
        self.assertIn("dependency of fastapi", packs["api-design"]["provenance"])
        self.assertEqual(packs["fastapi"]["scope"], ["api"])
        self.assertIsNone(packs["agent-workflow"]["scope"])
        self.assertTrue(packs["fastapi"]["version"])
        self.assertEqual(plan["conventions"], ["Use Conventional Commits."])
        self.assertEqual(plan["checks"], ["python -m pytest"])
        ids = [pack["id"] for pack in plan["packs"]]
        self.assertLess(ids.index("api-design"), ids.index("fastapi"))

    def test_conflict_is_reported_whether_it_comes_from_a_pattern_or_a_pack(self):
        from_pattern = {"name": "Team", "patterns": ["scrum"], "packs": ["kanban-delivery"]}
        profile = validate_profile(from_pattern, self.conflicting)
        conflicts = rule_plan(profile, self.conflicting)["conflicts"]
        self.assertEqual(conflicts[0]["packs"], ["kanban-delivery", "scrum-delivery"])
        self.assertIsNone(conflicts[0]["resolution"])
        # OGK-RULE-001
        with self.assertRaisesRegex(ValueError, "Conflicting rule packs: kanban-delivery and scrum-delivery"):
            render_instructions(profile, self.conflicting)

        direct = validate_profile({"name": "Team", "packs": ["kanban-delivery", "scrum-delivery"]}, self.conflicting)
        self.assertEqual(len(rule_plan(direct, self.conflicting)["conflicts"]), 1)

    def test_conflicts_in_separate_components_do_not_collide(self):
        catalog = json.loads(json.dumps(self.conflicting))
        catalog["patterns"]["scrum"]["match"] = {"stack": [["react"]]}
        catalog["patterns"]["kanban"]["match"] = {"stack": [["fastapi"]]}
        answers = {
            "name": "Two teams",
            "components": [{"id": "web", "stack": ["React"]}, {"id": "api", "stack": ["FastAPI"]}],
            "patterns": [{"id": "scrum", "components": ["web"]}, {"id": "kanban", "components": ["api"]}],
        }
        profile = validate_profile(answers, catalog)
        self.assertEqual(rule_plan(profile, catalog)["conflicts"], [])

    def test_the_team_choice_and_its_reason_reach_the_instructions_and_the_brief(self):
        answers = {
            "name": "Team",
            "packs": ["kanban-delivery", "scrum-delivery"],
            "resolutions": [{
                "packs": ["scrum-delivery", "kanban-delivery"], "keep": ["kanban-delivery"],
                "reason": "Support work arrives continuously.",
            }],
        }
        profile = validate_profile(answers, self.conflicting)
        self.assertNotIn("scrum-delivery", resolved_profile(profile, self.conflicting)["packs"])
        plan = rule_plan(profile, self.conflicting)
        self.assertEqual(plan["excluded"], ["scrum-delivery"])
        instructions = render_instructions(profile, self.conflicting)
        self.assertIn("- `kanban-delivery` applies instead of `scrum-delivery`. Reason: Support work arrives continuously.", instructions)
        self.assertNotIn("scrum-delivery@", instructions)

        task = {"id": "t", "brief": "Plan the next release.", "answers": {"kind": "decision", "surface": "business", "data": "none", "research": "local"}}
        scope = consult(resolved_profile(profile, self.conflicting), self.conflicting, task)["scope"]
        self.assertEqual(scope["resolutions"][0]["keep"], ["kanban-delivery"])
        self.assertNotIn("scrum-delivery", [pack["id"] for pack in scope["packs"]])

    def test_keeping_both_packs_is_a_recorded_choice(self):
        answers = {
            "name": "Team", "packs": ["kanban-delivery", "scrum-delivery"],
            "resolutions": [{"packs": ["kanban-delivery", "scrum-delivery"], "keep": ["kanban-delivery", "scrum-delivery"],
                             "reason": "Scrum with a Kanban board."}],
        }
        instructions = render_instructions(validate_profile(answers, self.conflicting), self.conflicting)
        self.assertIn("both apply. Reason: Scrum with a Kanban board.", instructions)

    def test_invalid_resolutions_and_conflict_declarations_are_rejected(self):
        # OGK-CATALOG-022, OGK-PROJECT-015
        with self.assertRaisesRegex(ValueError, "keep must list"):
            validate_profile({"name": "x", "resolutions": [{"packs": ["kanban-delivery", "scrum-delivery"],
                                                            "keep": ["python"], "reason": "x"}]}, self.catalog)
        pack = json.loads(json.dumps(self.catalog["packs"]["python"]))
        pack["conflicts_with"] = ["python"]
        with self.assertRaisesRegex(CatalogError, "the pack itself"):
            validate_entry("packs", pack)


if __name__ == "__main__":
    unittest.main()
