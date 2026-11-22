"""The first-contribution tutorial and the board guide of CONTRIBUTING.md lead to a brain that passes brains --check."""

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
TUTORIAL = ROOT / "docs" / "first-contribution.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"


def section(text: str, heading: str) -> str:
    """The text under a Markdown heading, up to the next heading of the same level or above."""
    level = heading.split(" ", 1)[0]
    start = text.index(f"\n{heading}\n")
    following = re.search(rf"\n#{{1,{len(level)}}} ", text[start + 1:])
    return text[start:start + 1 + following.start()] if following else text[start:]


def tutorial_lens() -> dict:
    step = section(TUTORIAL.read_text(encoding="utf-8"), "## 3. Make the change")
    return json.loads(re.search(r"```json\n(.*?)\n```", step, re.DOTALL).group(1))


class FirstContributionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        (self.folder / "project").mkdir()

    def brains(self, *arguments, registry=None):
        """Run openguildkit brains on an empty project, with the bundled catalog read from registry if given."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            if registry is not None:
                stack.enter_context(patch("openguildkit.catalog._registry", return_value=registry))
                stack.enter_context(patch.dict(catalog._BUNDLED, clear=True))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = main(["--project", str(self.folder / "project"), "brains", *arguments])
        return code, out.getvalue(), err.getvalue()

    def test_the_tutorial_lens_is_new_to_the_hr_brain_and_passes_brains_check(self):
        lens = tutorial_lens()
        self.assertTrue(lens["checks"] and all(isinstance(check, str) and check for check in lens["checks"]))
        bundled = catalog.load_catalog()["boards"]["hr"]["review"]["specialists"]
        self.assertNotIn(lens["id"], [specialist["id"] for specialist in bundled])
        self.assertNotIn(lens["title"].casefold(), [specialist["title"].casefold() for specialist in bundled])
        code, before, _ = self.brains("--id", "hr")
        self.assertEqual(code, 0)
        self.assertNotIn(lens["title"], before)

        registry = self.folder / "registry"
        shutil.copytree(catalog._registry(), registry)
        path = registry / "boards" / "hr.json"
        board = json.loads(path.read_text(encoding="utf-8"))
        board["review"]["specialists"].append(lens)
        path.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        code, output, error = self.brains("--check", registry=registry)
        self.assertEqual(code, 0, output + error)
        self.assertRegex(output, r"\d+ brains, 0 gap\(s\)\.")
        code, output, _ = self.brains("--id", "hr", registry=registry)
        self.assertEqual(code, 0)
        self.assertIn(f"{lens['title']}: {lens['focus']}", output)
        for check in lens["checks"]:
            self.assertIn(f"    - {check}", output)

    def test_the_tutorial_names_the_review_lists_to_keep_in_step(self):
        step = section(TUTORIAL.read_text(encoding="utf-8"), "## 3. Make the change")
        for field in ("review.specialists", "checks", "review.evidence", "review.challenge", "decision criterion"):
            self.assertIn(field, step)

    def test_adding_a_board_names_the_review_block_and_the_commands_that_check_it(self):
        guide = section(CONTRIBUTING.read_text(encoding="utf-8"), "## Adding a board")
        for text in ("`review`", "`specialists`", "`checks`", "`evidence`", "`challenge`", "`decision_criteria`",
                     "openguildkit brains --new", "openguildkit brains --check", "openguildkit brains --id"):
            with self.subTest(text=text):
                self.assertIn(text, guide)


if __name__ == "__main__":
    unittest.main()
