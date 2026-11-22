"""The documented contribution is accepted by the same CLI as a real board."""

import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import catalog
from openguildkit.cli import main

ROOT = Path(__file__).resolve().parents[1]


class FirstContributionTests(unittest.TestCase):
    def test_tutorial_specialist_passes_brains_check(self):
        tutorial = (ROOT / "docs" / "first-contribution.md").read_text(encoding="utf-8")
        example = json.loads(re.search(r"```json\s+(.*?)\s+```", tutorial, re.DOTALL).group(1))
        self.assertTrue(example["checks"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = root / "registry"
            shutil.copytree(ROOT / "src" / "openguildkit" / "registry", registry)
            board_file = registry / "boards" / "hr.json"
            board = json.loads(board_file.read_text(encoding="utf-8"))
            self.assertNotIn(example["id"], [s["id"] for s in board["review"]["specialists"]])
            self.assertNotIn(example["title"], [s["title"] for s in board["review"]["specialists"]])
            board["review"]["specialists"].append(example)
            board_file.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
            with patch.object(catalog, "_registry", return_value=registry), \
                    contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(["--project", str(root), "brains", "--check"]), 0, error.getvalue())
                self.assertIn("0 gap(s)", output.getvalue())
