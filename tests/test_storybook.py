import copy
import json
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from openguildkit.storage import write_json
from openguildkit.storybook import (
    MINIMAL_MAIN,
    REFS_FILE,
    compare,
    compose,
    dependency_conflicts,
    import_indexes,
    read_index,
    scope_entry,
    theme_sources,
)
from openguildkit.storybook_cli import _print_compose
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "storybook"
EXAMPLE = REPO / "examples" / "request-status"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StorybookIndexTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_import_warns_about_new_sources_until_the_project_index_is_rebuilt(self):
        index = self.root / "storybook-static" / "index.json"
        index.parent.mkdir()
        shutil.copyfile(FIXTURES / "project-index.json", index)
        source = self.root / "src" / "Loading.stories.tsx"
        source.parent.mkdir()
        source.write_text("export const Loading = {};", encoding="utf-8")
        old, new = 1_700_000_000, 1_700_000_010
        os.utime(index, (old, old))
        os.utime(source, (new, new))
        state = self.root / ".openguildkit"
        report = import_indexes(self.root, state)
        self.assertEqual(report["warnings"], [
            "src/Loading.stories.tsx is newer than storybook-static/index.json. "
            "Run npm run build-storybook, then import the project index again."])
        self.assertTrue((state / "storybook.json").is_file())
        os.utime(index, (new, new))
        self.assertNotIn("warnings", import_indexes(self.root, state))

    def test_storybook_10_and_7_indexes_are_read_and_older_formats_refused(self):
        # OGK-STORY-001, OGK-STORY-002
        project = read_index(FIXTURES / "project-index.json")
        self.assertIn({"id": "example-button--primary", "title": "Example/Button", "name": "Primary", "type": "story",
                       "tags": ["dev", "test", "manifest", "autodocs"], "importPath": "./src/stories/Button.stories.ts"},
                      project)
        self.assertEqual([item["type"] for item in read_index(FIXTURES / "storybook7-index.json")], ["docs", "story"])
        write_json(self.root / "stories.json", {"v": 3, "stories": {}})
        with self.assertRaisesRegex(ValueError, "Storybook 6"):
            read_index(self.root / "stories.json")
        broken = fixture("company-index.json")
        broken["entries"]["components-button--primary"]["id"] = "other"
        write_json(self.root / "index.json", broken)
        with self.assertRaisesRegex(ValueError, "unexpected Storybook entry"):
            read_index(self.root)

    def test_comparison_lists_matches_components_to_map_and_duplicates(self):
        project = read_index(FIXTURES / "project-index.json")
        company = read_index(FIXTURES / "company-index.json")
        report = compare(project, company)
        self.assertEqual(report["matched"], [{"project": "Example/Button", "company": "Components/Button"}])
        self.assertEqual([item["title"] for item in report["to_map"]], ["Example/Header", "Example/Page"])
        self.assertEqual(report["conflicts"], {"story_ids": [], "titles": []})
        copied = [dict(entry) for entry in company if entry["title"] == "Components/Button"]
        report = compare(project + copied, company)
        self.assertIn("components-button--disabled", report["conflicts"]["story_ids"])
        self.assertEqual(report["conflicts"]["titles"], ["Components/Button"])

    def test_dependency_report_uses_installed_versions_and_flags_styling_libraries(self):
        library, package = fixture("company-package.json"), fixture("project-package.json")
        rows = {row["name"]: row for row in dependency_conflicts(library, package, self.root)}
        self.assertEqual(rows["react"]["status"], "conflict")
        self.assertEqual(rows["react"]["checked"], ["19.3.1"])
        self.assertEqual(rows["react-dom"]["status"], "ok")
        self.assertEqual((rows["styled-components"]["status"], rows["styled-components"]["styling"]), ("missing", True))
        self.assertEqual(rows["@acme/icons"]["status"], "optional")
        self.assertEqual(rows["vite"]["status"], "duplicate")
        self.assertNotIn("clsx", rows)
        write_json(self.root / "node_modules" / "react" / "package.json", {"name": "react", "version": "18.3.1"})
        installed = {row["name"]: row for row in dependency_conflicts(library, package, self.root)}["react"]
        self.assertEqual((installed["status"], installed["installed"]), ("ok", "18.3.1"))
        themes = theme_sources(library, read_index(FIXTURES / "company-index.json"))
        self.assertEqual([item.get("export") or item.get("title") for item in themes], ["./theme.css", "./tokens", "Theme/Colors"])

    def test_compose_manages_its_own_refs_file_and_leaves_main_to_the_team(self):
        # OGK-STORY-004, OGK-STORY-005, OGK-STORY-007
        storybook = self.root / ".storybook"
        storybook.mkdir()
        main_file = storybook / "main.ts"
        main_file.write_text("const config = { framework: '@storybook/react-vite' };\nexport default config;\n")
        first = compose(self.root, "company", "https://design.example.com/", "Acme design system")
        self.assertFalse(first["imported"])
        self.assertIn("import refs from './openguildkit-refs.json' with { type: 'json' };", first["add_to_main"])
        compose(self.root, "brand", "https://brand.example.com")
        updated = compose(self.root, "company", "https://design.example.com/v5")
        self.assertEqual(updated["refs"]["company"], {"title": "Acme design system", "url": "https://design.example.com/v5"})
        self.assertEqual(list(json.loads((storybook / REFS_FILE).read_text())), ["brand", "company"])
        self.assertEqual(main_file.read_text(), "const config = { framework: '@storybook/react-vite' };\nexport default config;\n")
        main_file.write_text("import refs from './openguildkit-refs.json' with { type: 'json' };\n")
        self.assertTrue(compose(self.root, "brand", None, remove=True)["imported"])
        with self.assertRaisesRegex(ValueError, "https URL"):
            compose(self.root, "company", "ftp://design.example.com")
        with self.assertRaisesRegex(ValueError, "reserved"):
            compose(self.root, "project", "https://design.example.com")
        (storybook / REFS_FILE).write_text('{"stories": ["../src/**"]}')
        with self.assertRaisesRegex(ValueError, "managed by openguildkit"):
            compose(self.root, "company", "https://design.example.com")

    def test_compose_refuses_a_url_with_a_user_name_or_a_password(self):
        # OGK-STORY-003
        (self.root / ".storybook").mkdir()
        for url in ("https://user:secret@design.example.com", "https://user@design.example.com",
                    "https://:secret@design.example.com", "http://user:secret@localhost:6006"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "authentication"):
                compose(self.root, "company", url)
        self.assertFalse((self.root / ".storybook" / REFS_FILE).exists())

    def test_compose_prints_the_minimal_main_when_the_project_has_none(self):
        (self.root / ".storybook").mkdir()
        result = compose(self.root, "company", "https://design.example.com")
        self.assertIsNone(result["main"])
        self.assertIn("import refs from './openguildkit-refs.json' with { type: 'json' };", result["minimal_main"])
        self.assertIn("  refs,", result["minimal_main"])
        self.assertEqual(MINIMAL_MAIN, result["minimal_main"])
        text = "\n".join(_print_compose(result))
        self.assertIn(".storybook/main.ts", text)
        self.assertIn("framework: '@storybook/react-vite'", text)

    def test_an_index_outside_the_project_is_never_recorded_by_absolute_path(self):
        project = self.root / "project"
        project.mkdir()
        outside = self.root / "downloads" / "company-index.json"
        outside.parent.mkdir()
        shutil.copy(FIXTURES / "company-index.json", outside)
        report = import_indexes(project, project / ".openguildkit", None, outside, today=date(2026, 11, 20))
        record = (project / ".openguildkit" / "storybook.json").read_text()
        self.assertEqual(report["company"]["source"], "../downloads/company-index.json")
        self.assertNotIn(str(self.root.resolve()), record)
        self.assertNotIn(self.root.resolve().as_posix(), record)

    def test_import_records_both_indexes_without_touching_project_stories(self):
        state = self.root / ".openguildkit"
        story = self.root / "src" / "Button.stories.tsx"
        story.parent.mkdir()
        story.write_text("export default { title: 'Example/Button' };\n")
        shutil.copy(FIXTURES / "project-index.json", self.root / "project-index.json")
        for _ in range(2):
            report = import_indexes(self.root, state, self.root / "project-index.json", FIXTURES / "company-index.json",
                                    today=date(2026, 11, 20))
        self.assertEqual(story.read_text(), "export default { title: 'Example/Button' };\n")
        self.assertEqual(report["record"], ".openguildkit/storybook.json")
        entry = scope_entry(state, today=date(2026, 12, 1))
        self.assertEqual([item["ref"] for item in entry["indexes"]], ["project", "company"])
        self.assertEqual(entry["indexes"][0]["age_days"], 11)
        self.assertIn("components-button--disabled", entry["indexes"][1]["stories"])
        self.assertNotIn("theme-colors--docs", entry["indexes"][1]["stories"])
        import_indexes(self.root, state, None, FIXTURES / "storybook7-index.json", ref="forms", today=date(2026, 11, 21))
        self.assertEqual([item["ref"] for item in scope_entry(state)["indexes"]], ["project", "company", "forms"])
        self.assertIsNone(scope_entry(self.root / "elsewhere"))


class StorybookConsultationTests(unittest.TestCase):
    def test_the_design_brain_cites_a_recorded_story_and_its_state(self):
        # OGK-BOARD-007
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            write_json(root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text()))
            run_cli(root, "init", "--answers", root / "profile.json")
            run_cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "before")
            consultation = run_cli(root, "task", "consult", "before", "--answers", EXAMPLE / "answers.json").stdout
            self.assertNotIn("storybook:STORY_ID", consultation)

            static = root / "storybook-static"
            static.mkdir()
            shutil.copy(FIXTURES / "project-index.json", static / "index.json")
            shutil.copy(FIXTURES / "project-package.json", root / "package.json")
            report = json.loads(run_cli(root, "storybook", "import", "--company-index", FIXTURES / "company-index.json",
                                    "--library", FIXTURES / "company-package.json", "--json").stdout)
            self.assertEqual(report["project"]["source"], "storybook-static/index.json")
            self.assertIn("Example/Page", [item["title"] for item in report["to_map"]])
            text = run_cli(root, "storybook", "import", "--company-index", FIXTURES / "company-index.json",
                          "--library", FIXTURES / "company-package.json").stdout
            self.assertIn("To map: Example/Header", text)
            self.assertIn("Dependency conflict: react ^18.2.0 in the library, ^19.3.1 in the project", text)

            run_cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "status")
            consultation = run_cli(root, "task", "consult", "status", "--answers", EXAMPLE / "answers.json").stdout
            self.assertIn("storybook:REF_STORY_ID", consultation)
            design_brief = run_cli(root, "task", "pass", "status", "design").stdout
            self.assertIn("storybook:button--disabled", design_brief)
            self.assertIn("storybook:company_components-button--disabled", design_brief)

            template = json.loads(run_cli(root, "task", "template", "status").stdout)
            review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
            design = next(entry for entry in review["boards"] if entry["id"] == "design")
            design["evidence"].append({"source": "project-file", "ref": "storybook:example-button--disabled",
                                       "supports": "A disabled button state."})
            write_json(root / "review.json", review)
            error = run_cli(root, "task", "review", "status", "--file", root / "review.json", expect=1).stderr
            self.assertIn("storybook:example-button--disabled is not a story", error)
            design["evidence"][-1] = {"source": "project-file", "ref": "storybook:company_components-button--disabled",
                                      "supports": "The company button has a disabled state to reuse."}
            design["evidence"].append({"source": "project-file", "ref": "storybook:example-button--primary",
                                       "supports": "The project's primary button."})
            write_json(root / "review.json", copy.deepcopy(review))
            run_cli(root, "task", "review", "status", "--file", root / "review.json")
            self.assertEqual(json.loads(run_cli(root, "task", "show", "status", "--json").stdout)["status"], "reviewed")


if __name__ == "__main__":
    unittest.main()
