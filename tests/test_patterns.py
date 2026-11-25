import unittest

from openguildkit.catalog import load_catalog
from openguildkit.patterns import check_pattern_choices, recommend_patterns
from openguildkit.project import resolved_profile, validate_profile


class PatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_partial_stack_does_not_pull_in_the_compound_pack(self):
        answers = {"name": "Backend", "stack": ["Python 3.12", "FastAPI 0.115"]}
        profile = validate_profile(answers, self.catalog)
        self.assertNotIn("python-fastapi-postgresql", profile["patterns"])
        self.assertNotIn("fastapi", resolved_profile(profile, self.catalog)["packs"])
        self.assertNotIn("postgresql", resolved_profile(profile, self.catalog)["packs"])

    def test_explicit_pack_profile_keeps_the_previous_selection(self):
        answers = {
            "name": "Existing service",
            "stack": ["Python", "FastAPI", "PostgreSQL"],
            "packs": ["agent-workflow", "python"],
        }
        profile = validate_profile(answers, self.catalog)
        self.assertNotIn("patterns", profile)
        self.assertEqual(resolved_profile(profile, self.catalog)["packs"], answers["packs"])

    def test_each_pattern_activates_its_own_method(self):
        # A norm a sector proposes may activate the pack of a method (iso-27001-certification and iso-27001-isms):
        # it is the same rules, proposed to the person for the sector. Two methods, or two norms, never share one.
        for kind in ("method", "regulation"):
            packs = {pattern_id: frozenset(pattern["packs"]) for pattern_id, pattern in self.catalog["patterns"].items()
                     if pattern.get("kind", "method") == kind}
            shared = [ids for ids in packs.values() if list(packs.values()).count(ids) > 1]
            self.assertEqual(shared, [], kind)
        separated = {
            "a-b-testing": "campaign-measurement", "utm-campaign-measurement": "controlled-experiments",
            "okr": "strategy-map", "strategy-mapping": "leadership-planning",
            "raci": "project-planning", "critical-path": "responsibility-matrix",
            "jobs-to-be-done": "product-discovery", "opportunity-solution-tree": "product-discovery",
            "continuous-discovery": "jobs-to-be-done", "marketing-channel-planning": "campaign-planning",
        }
        for pattern_id, other_method in separated.items():
            with self.subTest(pattern=pattern_id):
                profile = validate_profile({"name": "Team", "patterns": [pattern_id], "packs": []}, self.catalog)
                self.assertNotIn(other_method, resolved_profile(profile, self.catalog)["packs"])

    def test_frameworks_match_without_their_platform(self):
        def matched(stack):
            return {pattern["id"] for pattern in recommend_patterns(self.catalog, stack, "general", [])["matched"]}

        self.assertIn("java-spring-boot", matched(["Kotlin 2.1", "Spring Boot 3.5"]))
        self.assertIn("dotnet-aspnet-core", matched(["ASP.NET Core 9"]))
        self.assertTrue({"nextjs-react", "react-web"} <= matched(["Next.js 15"]))
        profile = validate_profile({"name": "Web", "stack": ["Next.js 15"]}, self.catalog)
        self.assertIn("react", resolved_profile(profile, self.catalog)["packs"])

    def test_http_contract_rules_reach_every_service_stack(self):
        for stack in (["Java", "Spring Boot"], ["ASP.NET Core"], ["Go", "PostgreSQL"], ["Python", "FastAPI", "PostgreSQL"],
                      ["Kotlin", "Ktor"]):
            with self.subTest(stack=stack):
                profile = validate_profile({"name": "Service", "stack": stack}, self.catalog)
                self.assertIn("api-design", resolved_profile(profile, self.catalog)["packs"])

    def test_sector_and_exclusive_groups_control_the_recommendation(self):
        catalog = {"patterns": {
            "alternative-one": {
                "id": "alternative-one", "roles": ["engineering"],
                "match": {"stack": [["postgresql", "postgres"]], "sectors": ["internal-tools"]},
                "exclusive_group": "database-layout",
            },
            "alternative-two": {
                "id": "alternative-two", "roles": ["engineering"],
                "match": {"stack": [["postgresql", "postgres"]], "sectors": ["internal-tools"]},
                "exclusive_group": "database-layout",
            },
        }}
        general = recommend_patterns(catalog, ["Postgres@16"], "general", [])
        self.assertEqual(general, {"matched": [], "suggested": [], "excluded": []})
        scoped = recommend_patterns(catalog, ["Postgres@16"], "internal-tools", [])
        self.assertEqual(scoped["matched"], [])
        self.assertTrue(all(item["choice_required"] for item in scoped["suggested"]))
        self.assertEqual(len(scoped["suggested"]), 2)
        with self.assertRaisesRegex(ValueError, "Choose one pattern"):
            check_pattern_choices(["alternative-one", "alternative-two"], catalog["patterns"])
