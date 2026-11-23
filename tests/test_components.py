import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import CatalogError, validate_entry, load_catalog
from openguildkit.detect import components_for_profile, detect_stack
from openguildkit.patterns import patterns_to_review, recommend_patterns, technology_version
from openguildkit.project import pack_scopes, render_instructions, resolved_profile, validate_profile
from tests.support import run_cli


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class DetectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_monorepo_manifests_become_components_with_versions_and_evidence(self):
        write(self.root, "apps/web/package.json", {"dependencies": {"next": "^14.2.3", "react": "18.3.1"},
                                                   "devDependencies": {"typescript": "~5.4.0"}})
        write(self.root, "services/api/pyproject.toml",
              '[project]\nname = "api"\nrequires-python = ">=3.12"\ndependencies = ["fastapi>=0.115", "psycopg[binary]==3.2.1"]\n')
        write(self.root, "services/api/node_modules/next/package.json", {"dependencies": {"next": "1.0.0"}})
        write(self.root, "docker-compose.yml", "services:\n  db:\n    image: postgres:16-alpine\n")
        write(self.root, ".github/workflows/ci.yml", "on: push\n")

        detected = detect_stack(self.root)
        components = {component["path"]: component for component in detected["components"]}
        self.assertEqual(set(components), {".", "apps/web", "services/api"})
        self.assertEqual(components["apps/web"]["id"], "apps-web")
        self.assertIn("Next.js ^14.2.3", components["apps/web"]["stack"])
        self.assertIn("TypeScript ~5.4.0", components["apps/web"]["stack"])
        self.assertIn("Python >=3.12", components["services/api"]["stack"])
        self.assertIn("FastAPI >=0.115", components["services/api"]["stack"])
        postgres = next(item for item in components["services/api"]["evidence"] if item["name"] == "PostgreSQL")
        self.assertTrue(postgres["inferred"])
        self.assertEqual(postgres["evidence"], "services/api/pyproject.toml")
        self.assertIn("PostgreSQL 16", components["."]["stack"])
        self.assertIn("GitHub Actions", components["."]["stack"])
        self.assertNotIn("evidence", components_for_profile(detected)[0])

    def test_unreadable_or_unknown_files_are_ignored(self):
        write(self.root, "package.json", "{not json")
        write(self.root, "README.md", "# Nothing to detect")
        self.assertEqual(detect_stack(self.root), {"components": []})


class ComponentPatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_versions_are_read_from_the_declared_stack(self):
        self.assertEqual(technology_version("Next.js 14.2"), "14.2")
        self.assertEqual(technology_version("Postgres@16"), "16")
        self.assertEqual(technology_version("next@v13.4.1"), "13.4.1")
        self.assertEqual(technology_version("Next.js >= 14.2.3 < 16 || ^16.1"), "14.2.3")
        self.assertEqual(technology_version("Next.js >=14, >=14.3"), "14.3")
        self.assertIsNone(technology_version("Next.js < 16"))
        self.assertIsNone(technology_version("Next.js"))

    def test_app_router_rules_skip_next_10_and_flag_an_unknown_version(self):
        old = recommend_patterns(self.catalog, ["Next.js 10", "React 17"], "general", [])
        self.assertNotIn("nextjs-react", [pattern["id"] for pattern in old["matched"]])
        self.assertIn("react-web", [pattern["id"] for pattern in old["matched"]])
        self.assertEqual(old["excluded"][0]["id"], "nextjs-react")
        self.assertIn("13.4", old["excluded"][0]["reasons"][0])

        recent = recommend_patterns(self.catalog, ["Next.js 14.2", "React"], "general", [])
        self.assertIn("nextjs-react", [pattern["id"] for pattern in recent["matched"]])
        ranged = recommend_patterns(self.catalog, ["Next.js >=14.2.3 <16", "React"], "general", [])
        self.assertIn("nextjs-react", [pattern["id"] for pattern in ranged["matched"]])

        unknown = recommend_patterns(self.catalog, ["Next.js", "React"], "general", [])
        pattern = next(pattern for pattern in unknown["matched"] if pattern["id"] == "nextjs-react")
        self.assertEqual(pattern["version_unknown"], ["next.js >= 13.4"])

    def test_a_compound_pattern_needs_its_technologies_in_one_component(self):
        components = [
            {"id": "api", "path": "services/api", "stack": ["Python 3.12", "FastAPI"]},
            {"id": "jobs", "path": "services/jobs", "stack": ["Python 3.12", "PostgreSQL 16"]},
        ]
        split = recommend_patterns(self.catalog, [], "general", [], components)
        self.assertNotIn("python-fastapi-postgresql", [pattern["id"] for pattern in split["matched"]])
        python = next(pattern for pattern in split["matched"] if pattern["id"] == "python-development")
        self.assertEqual(python["components"], ["api", "jobs"])

        components[0]["stack"].append("Postgres")
        joined = recommend_patterns(self.catalog, [], "general", [], components)
        compound = next(pattern for pattern in joined["matched"] if pattern["id"] == "python-fastapi-postgresql")
        self.assertEqual(compound["components"], ["api"])

    def test_scoped_patterns_reach_the_instructions_and_their_packs(self):
        answers = {"personal_data": "no", 
            "name": "Portal",
            "components": [
                {"id": "web", "path": "apps/web", "stack": ["Next.js 14.2", "React 18"]},
                {"id": "api", "path": "services/api", "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16"]},
            ],
        }
        profile = validate_profile(answers, self.catalog)
        self.assertIn({"id": "nextjs-react", "components": ["web"]}, profile["patterns"])
        self.assertIn("Next.js 14.2", profile["stack"])
        scopes = pack_scopes(profile, self.catalog)
        self.assertEqual(scopes["nextjs"], ["web"])
        self.assertEqual(scopes["fastapi"], ["api"])
        self.assertIsNone(scopes["agent-workflow"])
        instructions = render_instructions(profile, self.catalog)
        self.assertIn("- `web` in `apps/web`: Next.js 14.2, React 18", instructions)
        self.assertIn("Applies to `web` (apps/web).", instructions)
        self.assertIn("nextjs", resolved_profile(profile, self.catalog)["packs"])

    def test_a_context_change_lists_the_patterns_to_review(self):
        profile = validate_profile({"personal_data": "no", "name": "Portal", "stack": ["Next.js 14", "React"]}, self.catalog)
        self.assertEqual(patterns_to_review(profile, self.catalog), [])
        profile["stack"] = ["Next.js 12", "React"]
        review = patterns_to_review(profile, self.catalog)
        self.assertEqual([item["id"] for item in review], ["nextjs-react"])
        self.assertIn("below", review[0]["reasons"][0])

    def test_previous_profiles_keep_their_instructions(self):
        answers = {"personal_data": "no", "name": "Backend", "stack": ["Python", "FastAPI", "PostgreSQL"], "patterns": ["python-fastapi-postgresql"]}
        profile = validate_profile(answers, self.catalog)
        self.assertEqual(profile["patterns"], ["python-fastapi-postgresql"])
        self.assertNotIn("components", profile)
        instructions = render_instructions(profile, self.catalog)
        self.assertNotIn("### Components", instructions)
        self.assertNotIn("Applies to", instructions)

    def test_profile_rejects_unknown_component_scopes_and_unsafe_paths(self):
        components = [{"id": "web", "path": "apps/web", "stack": ["React"]}]
        with self.assertRaisesRegex(ValueError, "unknown components"):
            validate_profile({"personal_data": "no", "name": "x", "components": components,
                              "patterns": [{"id": "react-web", "components": ["api"]}]}, self.catalog)
        with self.assertRaisesRegex(ValueError, "relative"):
            validate_profile({"personal_data": "no", "name": "x", "components": [{"id": "web", "path": "../web", "stack": ["React"]}]}, self.catalog)

    def test_catalog_checks_minimum_versions(self):
        pattern = json.loads(json.dumps(self.catalog["patterns"]["nextjs-react"]))
        pattern["match"]["min_versions"] = {"vue": "3"}
        with self.assertRaisesRegex(CatalogError, "not a stack alias"):
            validate_entry("patterns", pattern)
        pattern["match"]["min_versions"] = {"next.js": "13.x"}
        with self.assertRaisesRegex(CatalogError, "version such as"):
            validate_entry("patterns", pattern)


if __name__ == "__main__":
    unittest.main()


class ComponentTaskTests(unittest.TestCase):
    """A project with components scopes its patterns: every task command must read them."""

    def test_a_task_is_routed_and_consulted_in_a_project_with_scoped_patterns(self):
        import contextlib
        import io

        from openguildkit.cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, "profile.json", {"personal_data": "no", 
                "name": "Shop", "components": [
                    {"id": "web", "path": "web", "stack": ["React", "TypeScript"]},
                    {"id": "api", "path": "api", "stack": ["Python", "FastAPI", "PostgreSQL"]},
                ],
            })
            write(root, "answers.json", {
                "kind": "feature", "surface": ["customer", "service"], "data": "personal", "research": "local", "concerns": ["none"],
                "outcome": "A customer is told when a product is back in stock.", "affected": "Customers",
            })

            def run(*arguments):
                return run_cli(root, *arguments).stdout

            run("init", "--answers", root / "profile.json")
            profile = json.loads((root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
            self.assertTrue(any(isinstance(entry, dict) for entry in profile["patterns"]), profile["patterns"])
            run("task", "new", "Tell customers by email when a product is back in stock, with an AI model that ranks who to notify first.",
                "--id", "back-in-stock")
            route = run("task", "route", "back-in-stock", "--answers", root / "answers.json")
            self.assertIn("security", route)
            consultation = run("task", "consult", "back-in-stock", "--answers", root / "answers.json")
            self.assertIn("# Board consultation request", consultation)
            self.assertIn("Board pass", run("task", "pass", "back-in-stock", "security", "--mode", "sequential"))
