"""A message that sends the reader to a documentation page gives its https address, and the page has the heading."""

import ast
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import doc_links
from openguildkit.doc_links import doc_link
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "src" / "openguildkit"
# A page of this repository, not the docs/ folder of another site (https://code.claude.com/docs/en/settings.md).
PAGE = re.compile(r"(?<![/\w.])(?:docs|integrations)/[\w/.-]+\.md\b")
# A path a message gives as an example of a file of the person's project, not a page of this repository.
EXAMPLE_PATHS = {"docs/privacy/record.md"}


def anchors(page: Path) -> set[str]:
    """The anchors GitHub gives to the headings of a Markdown page, outside its code blocks."""
    found = set()
    for block in re.split(r"^```.*?^```", page.read_text(encoding="utf-8"), flags=re.MULTILINE | re.DOTALL):
        for heading in re.findall(r"^#{1,6} +(.+?) *#*$", block, re.MULTILINE):
            found.add(re.sub(r"[^\w\- ]", "", heading.lower().replace("`", "")).replace(" ", "-"))
    return found


def printed_strings() -> list[tuple[str, int, str]]:
    """Every string of src/openguildkit that is neither a docstring nor an argument of doc_link, with its place."""
    found = []
    for path in sorted(SOURCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)}
        linked = {id(argument) for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and getattr(node.func, "id", None) == "doc_link" for argument in node.args}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings | linked:
                found.append((path.name, node.lineno, node.value))
    return found


def cited() -> list[tuple[str, int, str, str]]:
    """Each doc_link call of src/openguildkit whose page and anchor are written in the call."""
    found = []
    for path in sorted(SOURCE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "doc_link":
                arguments = [argument.value for argument in node.args if isinstance(argument, ast.Constant)]
                found.append((path.name, node.lineno, *(arguments + [""])[:2]))
    return found


class DocLinkTests(unittest.TestCase):
    def setUp(self):
        doc_links._revision.cache_clear()
        self.addCleanup(doc_links._revision.cache_clear)

    def test_an_installed_release_links_the_page_at_its_tag(self):
        with patch("openguildkit.lock.package_version", return_value="0.17.0"):
            self.assertEqual(doc_link("docs/workflow.md", "project-checks"),
                             "https://github.com/Sandbox-podcast/OpenGuildKit/blob/v0.17.0/docs/workflow.md#project-checks")
            self.assertEqual(doc_link("docs/catalog-format.md"),
                             "https://github.com/Sandbox-podcast/OpenGuildKit/blob/v0.17.0/docs/catalog-format.md")

    def test_a_checkout_or_a_development_version_links_the_main_branch(self):
        for version in ("0.17.1.dev0+source", "0.17.1.dev0", "unknown"):
            doc_links._revision.cache_clear()
            with self.subTest(version=version), patch("openguildkit.lock.package_version", return_value=version):
                self.assertTrue(doc_link("docs/workflow.md").startswith(
                    "https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/workflow.md"))

    def test_no_message_names_a_page_of_the_repository_without_doc_link(self):
        """Issue #494: 15 messages cited docs/workflow.md, a path a wheel installation does not have."""
        bare = [f"{module}:{line}: {text[:60]!r}" for module, line, text in printed_strings()
                if any(name not in EXAMPLE_PATHS for name in PAGE.findall(text))]
        self.assertEqual(bare, [])

    def test_every_page_and_heading_a_message_cites_exists(self):
        calls = cited()
        self.assertGreaterEqual(len(calls), 15)
        for module, line, page, anchor in calls:
            with self.subTest(call=f"{module}:{line}"):
                self.assertTrue((REPO / page).is_file(), page)
                if anchor:
                    self.assertIn(anchor, anchors(REPO / page))

    def test_the_anchor_check_catches_a_heading_that_is_gone(self):
        self.assertIn("signed-approvals", anchors(REPO / "docs" / "workflow.md"))
        self.assertNotIn("signed-approval", anchors(REPO / "docs" / "workflow.md"))

    def test_init_prints_the_address_of_the_page_it_cites(self):
        with tempfile.TemporaryDirectory() as directory:
            answers = Path(directory) / "answers.json"
            answers.write_text('{"personal_data": "no", "checks": []}', encoding="utf-8")
            output = run_cli(Path(directory), "init", "--answers", answers).stdout
        self.assertIn("https://github.com/Sandbox-podcast/OpenGuildKit/blob/", output)
        self.assertIn("/docs/workflow.md#project-checks", output)
        self.assertNotIn("(docs/workflow.md", output)


if __name__ == "__main__":
    unittest.main()
