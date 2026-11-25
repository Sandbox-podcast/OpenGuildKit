"""The search examples of the documentation, run as a reader would type them: each one finds something."""

import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path

from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)


def reference_examples() -> list[tuple[str, int, str]]:
    """Each `openguildkit references` line of a code block of docs/*.md, with its page and line number."""
    found = []
    for page in sorted((REPO / "docs").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        for block in FENCE.finditer(text):
            first_line = text.count("\n", 0, block.start(1)) + 1
            for offset, line in enumerate(block.group(1).splitlines()):
                if line.strip().startswith("openguildkit references"):
                    found.append((page.relative_to(REPO).as_posix(), first_line + offset, line.strip()))
    return found


def arguments(line: str) -> list[str]:
    """The command's arguments after `openguildkit`, without its comment and its output redirection."""
    words = shlex.split(line, comments=True)[1:]
    if ">" in words:
        words = words[:words.index(">")]
    return words


class ReferenceExampleTests(unittest.TestCase):
    def test_the_pages_hold_search_examples(self):
        examples = reference_examples()
        self.assertGreaterEqual(len(examples), 6)
        self.assertIn("docs/patterns.md", {page for page, _, _ in examples})
        self.assertEqual(arguments('openguildkit references --family cloud "observabilite" --json  # a note'),
                         ["references", "--family", "cloud", "observabilite", "--json"])
        self.assertEqual(arguments("openguildkit references > /dev/null"), ["references"])

    def test_each_example_finds_at_least_one_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            for page, number, line in reference_examples():
                with self.subTest(example=f"{page}:{number}: {line}"):
                    words = arguments(line)
                    result = run_cli(Path(directory), *words)
                    self.assertNotIn("No references matched", result.stdout)
                    if "--json" in words:
                        self.assertTrue(json.loads(result.stdout))
                    else:
                        self.assertTrue(result.stdout.strip())


class ToolsScenarioTests(unittest.TestCase):
    """docs/tools.md connects jira, tempo and snyk as mocks, then writes a scenario for a task."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # The example profile names no tool: the scenario can only come from the connected mocks.
        run_cli(self.root, "init", "--answers", EXAMPLE / "profile.json")
        run_cli(self.root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")

    def test_the_scenario_covers_the_tools_connected_as_mocks(self):
        run_cli(self.root, "tools", "apply", "jira", "tempo", "snyk", "--mock", "--host", "claude-code")
        output = run_cli(self.root, "tools", "scenario", "--task", "request-status").stdout
        self.assertIn("Wrote .openguildkit/catalog/tool-mocks/scenario.json for jira, snyk, tempo.", output)
        self.assertIn("one jira record for the task", output)
        written = json.loads((self.root / ".openguildkit" / "catalog" / "tool-mocks" / "scenario.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(set(written["records"]), {"jira", "tempo", "snyk"})

    def test_without_a_tool_the_message_says_what_was_examined_and_what_to_type(self):
        error = run_cli(self.root, "tools", "scenario", "--task", "request-status", expect=1).stderr
        self.assertIn("The profile names no tool and no tool is connected as a mock", error)
        self.assertIn("openguildkit tools scenario TOOL", error)
        self.assertIn("openguildkit tools list --mocks", error)
        run_cli(self.root, "tools", "apply", "gryzzly", "--mock", "--host", "claude-code", expect=1)
        error = run_cli(self.root, "tools", "scenario", "gryzzly", expect=1).stderr
        self.assertIn("None of these tools has a mock with records: gryzzly.", error)

    def test_no_page_points_the_real_interface_at_a_numeric_loopback(self):
        """Issue #330: openguildkit ui answers only the printed ogk-….localhost origin."""
        repo = Path(__file__).resolve().parents[1]
        forbidden = ("OGK_API=http://127.0.0.1", "http://127.0.0.1:7311/?key=")
        found = []
        for folder in (repo / "docs", repo / "web"):
            for page in folder.rglob("*.md"):
                text = page.read_text(encoding="utf-8")
                for needle in forbidden:
                    if needle in text:
                        found.append(f"{page.relative_to(repo).as_posix()}: {needle}")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
