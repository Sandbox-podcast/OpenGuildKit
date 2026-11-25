"""The pages that describe the product follow the code: every module, every test file, no state of a past branch."""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "openguildkit"
TESTS = REPO / "tests"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def module_rows(page: str) -> set[str]:
    """The modules the table of docs/architecture.md describes, one per row."""
    return set(re.findall(r"^\| `([\w]+\.py)` \|", page, re.MULTILINE))


def test_kinds(page: str) -> list[str]:
    """The Where cell of each row of the kinds table of docs/testing.md."""
    table = page.split("## Kinds of tests", 1)[1].split("\n## ", 1)[0]
    return [row.split("|")[2] for row in table.splitlines() if row.startswith("| ") and "---" not in row][1:]


def placed(relative: str, cells: list[str]) -> bool:
    """Whether a row names a test file, by its path or by its file name (test file names are unique)."""
    name = relative.rsplit("/", 1)[-1]
    return any(f"`{relative}`" in cell or f"`{name}`" in cell for cell in cells)


class ArchitectureTests(unittest.TestCase):
    def test_the_module_table_names_every_module_of_the_package(self):
        modules = {path.name for path in PACKAGE.glob("*.py")}
        self.assertEqual(module_rows(_read(REPO / "docs" / "architecture.md")), modules)

    def test_the_diagram_shows_the_web_interface_over_the_cli(self):
        page = _read(REPO / "docs" / "architecture.md")
        diagram = page.split("```mermaid", 1)[1].split("```", 1)[0]
        self.assertRegex(diagram, r"webui\b[^\n]*-->[^\n]*\bcli\b")
        for words in ("X-OGK-Token", "project lock", "person at a terminal", "web/"):
            with self.subTest(words=words):
                self.assertIn(words, page)


class TestingPageTests(unittest.TestCase):
    def setUp(self):
        self.page = _read(REPO / "docs" / "testing.md")
        self.cells = test_kinds(self.page)

    def test_every_test_file_belongs_to_a_kind(self):
        files = sorted(path.relative_to(REPO).as_posix() for path in TESTS.rglob("test_*.py"))
        self.assertGreater(len(files), 100)
        self.assertEqual([relative for relative in files if not placed(relative, self.cells)], [])

    def test_the_web_interface_has_its_row(self):
        row = next(cell for cell in self.cells if "test_webui.py" in cell)
        for command in ("npm test", "npm run e2e", "npm run e2e:project"):
            with self.subTest(command=command):
                self.assertIn(f"`{command}`", row)

    def test_the_page_dates_the_count_and_the_duration_of_the_suite(self):
        self.assertRegex(self.page, r"\d{1,2} \w+ 20\d\d\b[^\n]*?: \d[\d ,]* tests in \d+ s")


class WebPagesTests(unittest.TestCase):
    def test_the_handover_note_is_gone_and_its_pitfalls_moved_to_the_readme(self):
        self.assertFalse((REPO / "web" / "REPRISE.md").exists())
        readme = _read(REPO / "web" / "README.md")
        self.assertIn("## Pièges connus", readme)
        self.assertNotIn("feat/guild-web-app", readme)

    def test_no_web_page_writes_a_test_count(self):
        pages = [REPO / "web" / "README.md", *sorted((REPO / "web" / "docs").glob("*.md"))]
        counted = re.compile(r"[0-9]+ tests? (Vitest|Python)|[0-9]+/[0-9]+")
        for path in pages:
            with self.subTest(page=path.relative_to(REPO).as_posix()):
                self.assertEqual(counted.findall(_read(path)), [])

    def test_no_page_gives_a_loopback_address_that_openguildkit_ui_refuses(self):
        # Since #281 the server answers only under the host name it printed (ogk-....localhost): on 127.0.0.1 the
        # page shows only the invitation to open the printed address, so OGK_API and measure:project need its origin.
        pages = [path for folder in ("web", "docs") for path in sorted((REPO / folder).rglob("*.md"))
                 if "node_modules" not in path.parts]
        refused = re.compile(r"OGK_API=http://127\.0\.0\.1|http://127\.0\.0\.1:[0-9]+/\?key=")
        for path in pages:
            with self.subTest(page=path.relative_to(REPO).as_posix()):
                self.assertEqual(refused.findall(_read(path)), [])


def places() -> dict[str, str]:
    """The places of web/src/shared/places.ts, each key with its RPG name."""
    source = _read(REPO / "web" / "src" / "shared" / "places.ts")
    return dict(re.findall(r"\{ key: '([a-z]+)', name: '([^']+)'", source))


def sweep_routes() -> list[str]:
    """The routes the sweep of web/tests/e2e/project-sweep.spec.ts opens."""
    source = _read(REPO / "web" / "tests" / "e2e" / "project-sweep.spec.ts")
    return re.findall(r"'(/[^']*)'", source.split("const ROUTES = [", 1)[1].split("];", 1)[0])


class WebPlacesTests(unittest.TestCase):
    def test_the_place_table_of_the_project_interface_has_a_row_for_each_place(self):
        page = _read(REPO / "web" / "docs" / "interface-projet.md")
        table = page.split("## Ce que fait chaque lieu", 1)[1].split("\n## ", 1)[0]
        rows = [line.split("|")[1].strip() for line in table.splitlines() if line.startswith("| ") and "---" not in line]
        self.assertEqual(len(places()), 13)
        self.assertEqual(sorted(rows[1:]), sorted(places().values()))
        arsenal = next(line for line in table.splitlines() if line.startswith("| Arsenal |"))
        for command in ("features list", "features enable", "features disable"):
            with self.subTest(command=command):
                self.assertIn(f"`{command}`", arsenal)

    def test_the_web_readme_counts_and_names_every_place(self):
        readme = _read(REPO / "web" / "README.md")
        self.assertEqual(set(re.findall(r"([0-9]+) lieux", readme)), {str(len(places()))})
        demo = readme.split("## Démonstration Atelier Nova", 1)[1].split("\n\n", 2)[1]
        for name in places().values():
            with self.subTest(place=name):
                self.assertIn(name, demo)

    def test_the_sweep_opens_every_place_and_the_pages_count_its_routes(self):
        routes = sweep_routes()
        self.assertEqual(sorted({route.split("/")[1] for route in routes}), sorted(places()))
        for name in ("accessibilite.md", "interface-projet.md"):
            with self.subTest(page=name):
                counts = set(re.findall(r"([0-9]+) routes", _read(REPO / "web" / "docs" / name)))
                self.assertEqual(counts, {str(len(routes))})


class RoadmapTests(unittest.TestCase):
    def test_available_names_what_shipped_and_the_three_systems(self):
        available = _read(REPO / "docs" / "roadmap.md").split("## Available", 1)[1].split("\n## ", 1)[0]
        for words in ("tool registry", "mock", "features", "Arsenal", "web interface", "field", "Linux, macOS and Windows"):
            with self.subTest(words=words):
                self.assertIn(words, available)

    def test_contributing_says_how_to_build_and_test_the_web_interface(self):
        setup = _read(REPO / "CONTRIBUTING.md").split("## Set up", 1)[1].split("\n## ", 1)[0]
        for command in ("npm ci", "npm run typecheck", "npm test", "npm run build"):
            with self.subTest(command=command):
                self.assertIn(command, setup)


if __name__ == "__main__":
    unittest.main()
