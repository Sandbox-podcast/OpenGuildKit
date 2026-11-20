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
