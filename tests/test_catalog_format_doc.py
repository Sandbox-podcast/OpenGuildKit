"""docs/catalog-format.md names every catalog folder and every tool category the code knows."""

import re
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

    def test_every_tool_category_is_listed(self):
        missing = [category for category in CATEGORIES if f"`{category}`" not in self.page]
        self.assertEqual(missing, [], "list these tool categories in docs/catalog-format.md")


if __name__ == "__main__":
    unittest.main()
