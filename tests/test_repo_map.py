"""The repository map that scripts/build_map.py writes: the role of each module, taken from its docstring (#502)."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_map", REPO / "scripts" / "build_map.py")
build_map = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_map)


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.map = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))

    def test_issue_502_the_role_of_a_module_comes_from_its_docstring(self):
        """Issue #502: the role of a module was written in the map and in docs/architecture.md, apart from its
        docstring, and none of the three agreed."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "src" / "openguildkit").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "src" / "openguildkit" / "a.py").write_text('"""Reads the a\nrecords.\n\nEntry: x\n"""\n', "utf-8")
        current = {"modules": [{"module": "src/openguildkit/a.py", "role": "Old role.", "entry": [], "tests": [],
                                "doc": "docs/architecture.md"}]}
        built = build_map.build(current, root)
        self.assertEqual(built["modules"][0]["role"], "Reads the a records.")
        self.assertIn("modules: src/openguildkit/a.py differs in entry, role", build_map.differences(current, built))
        page = "# A\n\n| Module | Responsibility |\n|---|---|\n| `a.py` | Old role. |\n\nAfter.\n"
        self.assertEqual(build_map.with_table(page, built),
                         "# A\n\n| Module | Responsibility |\n|---|---|\n| `a.py` | Reads the a records. |\n\nAfter.\n")
        architecture = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        self.assertEqual(build_map.with_table(architecture, self.map), architecture, "run python scripts/build_map.py")

if __name__ == "__main__":
    unittest.main()
