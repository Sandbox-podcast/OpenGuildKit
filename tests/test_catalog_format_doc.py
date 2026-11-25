"""docs/catalog-format.md names every catalog folder and every tool category the code knows."""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.brains import brain_skeleton
from openguildkit.catalog import COLLECTION_FIELDS
from openguildkit.tools import CATEGORIES

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "src" / "openguildkit"
PAGE = REPO / "docs" / "catalog-format.md"


def folders_in_code() -> set[str]:
    """The catalog folders the loaders read: record collections, registry folders, project paths in the code."""
    folders = set(COLLECTION_FIELDS)
    folders |= {path.name for path in (SOURCE / "registry").iterdir() if path.is_dir()}
    folders |= {relative.split("/")[0] for relative in brain_skeleton("sample-brain")}
    for path in SOURCE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        folders |= set(re.findall(r'"catalog" / "([a-z-]+)"', text))
        folders |= set(re.findall(r"\.openguildkit/catalog/([a-z-]+)/", text))
    return folders


class CatalogFormatPageTests(unittest.TestCase):
    def setUp(self):
        self.page = PAGE.read_text(encoding="utf-8")

    def test_every_catalog_folder_is_described(self):
        layout = self.page.split("```text", 1)[1].split("```", 1)[0]
        missing = sorted(folder for folder in folders_in_code() if f"{folder}/" not in layout)
        self.assertEqual(missing, [], "add these folders to the layout at the top of docs/catalog-format.md")
        for heading in ("## References", "## Deliverables", "## Tools"):
            self.assertIn(f"\n{heading}\n", self.page)

    def test_the_announced_material_folder_count_matches_the_layout(self):
        words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
        announced = words[re.search(r"(\w+) folders of material", self.page).group(1)]
        layout = self.page.split("```text", 1)[1].split("```", 1)[0]
        material = [name for name in re.findall(r"^  ([a-z-]+)/", layout, re.M) if name not in COLLECTION_FIELDS]
        self.assertEqual(announced, len(material), material)

    def test_sample_project_explains_itself_and_refuses_an_option_it_does_not_know(self):
        script = REPO / "web" / "scripts" / "sample-project.py"
        with tempfile.TemporaryDirectory() as folder:
            shown = subprocess.run([sys.executable, str(script), "--help"], cwd=folder, capture_output=True,
                                   text=True, encoding="utf-8")
            refused = subprocess.run([sys.executable, str(script), "--nope"], cwd=folder, capture_output=True,
                                     text=True, encoding="utf-8")
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("sample-project.py DIR", shown.stdout)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("sample-project.py DIR", refused.stderr)

    def test_every_tool_category_is_listed(self):
        missing = [category for category in CATEGORIES if f"`{category}`" not in self.page]
        self.assertEqual(missing, [], "list these tool categories in docs/catalog-format.md")


if __name__ == "__main__":
    unittest.main()
