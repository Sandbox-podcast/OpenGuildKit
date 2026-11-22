"""The coverage page and the packs that fill the thinnest disciplines."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.patterns import recommend_patterns
from openguildkit.references import load_references

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coverage.py"
spec = importlib.util.spec_from_file_location("coverage_report", SCRIPT)
coverage_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage_report)

NEW_PACKS = {
    "support": "support-readiness",
    "communication": "release-communication",
    "hr": "employee-offboarding",
    "finance": "finops-cost-management",
    "performance": "web-performance",
    "security": "threat-modeling",
    "devops": "incident-response",
}


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.rows = {row["brain"]: row for row in coverage_report.brain_rows(cls.catalog, load_references())}

    def test_the_page_is_current(self):
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_page_says_why_there_is_no_soc_2_pack(self):
        text = (ROOT / "docs" / "coverage.md").read_text(encoding="utf-8")
        section = text.split("## Not turned into rules", 1)[1].split("## To cover", 1)[0]
        self.assertIn("SOC 2", section)
        self.assertIn("examination of controls", section)
        self.assertIn("iso-27001", section)
        self.assertNotIn("soc", {pack_id.split("-")[0] for pack_id in self.catalog["packs"]})

    def test_every_brain_reaches_packs_and_separates_documentary_references(self):
        self.assertEqual(set(self.rows), set(self.catalog["boards"]))
        for brain, row in self.rows.items():
            with self.subTest(brain=brain):
                self.assertGreater(row["packs"], 0)
                self.assertEqual(row["applied"] + len(row["documentary"]), row["references"])

    def test_thin_disciplines_get_their_new_pack_proposed_to_a_role(self):
        # Only a role's core methods are preselected (#152); the others are suggested with their reason.
        for role, pack_id in NEW_PACKS.items():
            with self.subTest(role=role):
                plan = recommend_patterns(self.catalog, [], "general", [role])
                proposed = plan["matched"] + plan["suggested"]
                self.assertIn(pack_id, {pack for pattern in proposed for pack in pattern["packs"]})
                pack = self.catalog["packs"][pack_id]
                self.assertTrue(pack["description"].startswith("For "))
                self.assertTrue(pack["sources"])


if __name__ == "__main__":
    unittest.main()
