"""docs/catalog-format.md names every catalog folder and every tool category the code knows."""

import re
import unittest
from pathlib import Path

from openguildkit.brains import brain_skeleton
from openguildkit.catalog import COLLECTION_FIELDS
from openguildkit.rule_checks import CHECK_KINDS
from openguildkit.tool_registry import CATEGORIES

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "src" / "openguildkit"
PAGE = REPO / "docs" / "catalog-format.md"
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


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

    def test_the_counts_of_collections_and_folders_match_the_layout(self):
        announced = re.search(r"The catalog has (\w+) collections of records, one JSON file per record, and (\w+) "
                              r"folders of material", self.page)
        self.assertIsNotNone(announced, "the sentence before the layout counts the collections and the folders")
        bundled = self.page.split("```text", 1)[1].split(".openguildkit/catalog/", 1)[0]
        folders = set(re.findall(r"^  ([a-z-]+)/", bundled, re.MULTILINE))
        self.assertTrue(set(COLLECTION_FIELDS) <= folders)
        self.assertEqual(NUMBERS[announced[1]], len(COLLECTION_FIELDS))
        self.assertEqual(NUMBERS[announced[2]], len(folders - set(COLLECTION_FIELDS)),
                         sorted(folders - set(COLLECTION_FIELDS)))

    def test_every_tool_category_is_listed(self):
        missing = [category for category in CATEGORIES if f"`{category}`" not in self.page]
        self.assertEqual(missing, [], "list these tool categories in docs/catalog-format.md")

    def test_every_kind_of_machine_check_is_in_the_table(self):
        table = self.page.split("| `kind` | Fields | Passes when |", 1)[1].split("\n\n", 1)[0]
        missing = [kind for kind in CHECK_KINDS if f"| `{kind}` |" not in table]
        self.assertEqual(missing, [], "add these kinds to the table of machine checks in docs/catalog-format.md")


if __name__ == "__main__":
    unittest.main()
