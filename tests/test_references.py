import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import CatalogError
from openguildkit.references import find_references, load_references


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.families = load_references()

    def test_title_matches_rank_above_mentions(self):
        matches = find_references(self.families, query="ISO 27001")
        self.assertEqual(matches[0]["id"], "iso-iec-27001")
        self.assertEqual(matches[0]["family"], "governance")

    def test_search_ignores_accents_and_can_filter_by_family(self):
        query = "observabilite"
        matches = find_references(self.families, family_id="cloud", query=query)
        self.assertTrue(matches)
        self.assertTrue(all(record["family"] == "cloud" for record in matches))
        self.assertEqual(matches, find_references(self.families, family_id="cloud", query="OBSERVABILITÉ"))

    def test_local_entries_extend_families_without_shadowing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.json"
            family = self.families["code"]
            example = family["references"][0]
            data = {
                "id": "code",
                "title": family["title"],
                "references": [{**example, "id": "team-code-style", "title": "Team code style"}],
            }
            path.write_text(json.dumps(data), encoding="utf-8")
            merged = load_references(path.parent)
            self.assertEqual(len(merged["code"]["references"]), len(family["references"]) + 1)
            self.assertEqual(find_references(merged, record_id="team-code-style")[0]["family"], "code")
            data["references"] = [example]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "Duplicate reference ID"):
                load_references(path.parent)
