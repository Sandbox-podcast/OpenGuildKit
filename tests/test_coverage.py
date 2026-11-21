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

    def test_every_brain_reaches_packs_and_separates_documentary_references(self):
        self.assertEqual(set(self.rows), set(self.catalog["boards"]))
        for brain, row in self.rows.items():
            with self.subTest(brain=brain):
                self.assertGreater(row["packs"], 0)
                self.assertEqual(row["applied"] + len(row["documentary"]), row["references"])

    def test_thin_disciplines_reach_their_new_pack_through_a_role(self):
        for role, pack_id in NEW_PACKS.items():
            with self.subTest(role=role):
                suggested = recommend_patterns(self.catalog, [], "general", [role])["suggested"]
                self.assertIn(pack_id, {pack for pattern in suggested for pack in pattern["packs"]})
                pack = self.catalog["packs"][pack_id]
                self.assertTrue(pack["description"].startswith("For "))
                self.assertTrue(pack["sources"])


if __name__ == "__main__":
    unittest.main()
