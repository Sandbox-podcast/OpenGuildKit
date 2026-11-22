"""The READMEs and the glossary stay true: the task journey uses real commands and the product's words are defined.

Field testers reading the French page could not find how a task goes from request to closing, and had to look up
the product's own words. These tests keep the journey runnable and the glossary complete in both languages.
"""

import contextlib
import io
import re
import shlex
import unittest
from pathlib import Path

from openguildkit.cli import _parser

REPO = Path(__file__).resolve().parents[1]
README_EN = REPO / "README.md"
README_FR = REPO / "README.fr.md"
GLOSSARY = REPO / "docs" / "glossary.md"

TERMS = (
    "pack", "pattern", "board", "brain", "lens", "guard", "host", "hook", "MCP", "mock", "handoff", "deliberate",
    "challenge", "maintain", "concede", "amend", "evidence_refs", "blocker", "waive", "seal", "surface", "DPIA", "UTM",
    "norm", "named evidence", "not concerned", "done-with-reservations", "condition of approval", "scenario",
    "component",
)
ENTRY = re.compile(r"^### `([^`]+)` · (.+)$\n\n\*\*EN\*\* (.+)$\n\n\*\*FR\*\* (.+)$", re.MULTILINE)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body of a level-two section, up to the next one."""
    start = text.index(f"## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _commands(text: str) -> list[str]:
    """Each openguildkit command line of the bash blocks, without the program name, comments or redirections."""
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        for line in block.splitlines():
            if line.startswith("openguildkit "):
                words = shlex.split(line, comments=True)[1:]
                cut = next((i for i, word in enumerate(words) if word in (">", "|", "&&")), len(words))
                commands.append(words[:cut])
    return commands


def _parse_error(words: list[str]) -> str | None:
    """The parser's complaint about a command, or None when the CLI accepts it."""
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            _parser().parse_args(words)
    except SystemExit:
        return (stderr.getvalue().strip().splitlines() or ["refused"])[-1]
    return None


class JourneyTests(unittest.TestCase):
    def test_every_command_the_readmes_show_is_accepted_by_the_cli(self):
        for page in (README_FR, README_EN):
            commands = _commands(_text(page))
            self.assertGreater(len(commands), 20, page.name)
            for words in commands:
                with self.subTest(page=page.name, command=" ".join(words)):
                    self.assertIsNone(_parse_error(words))

    def test_the_check_rejects_a_command_the_cli_does_not_have(self):
        self.assertIsNotNone(_parse_error(["task", "close", "statut-demandes"]))
        self.assertIsNotNone(_parse_error(["task", "decide", "statut-demandes", "--approuver"]))
        self.assertIsNone(_parse_error(["task", "complete", "statut-demandes"]))

    def test_the_french_journey_runs_from_task_new_to_task_export_in_order(self):
        actions = self._journey_actions(README_FR, "Le parcours d'une tâche")
        self.assertEqual(actions[0], "new")
        self.assertEqual(actions[-1], "export")
        for earlier, later in (("questions", "consult"), ("consult", "pass"), ("submit", "review"),
                               ("review", "challenge"), ("challenge", "decide"), ("decide", "handoff"),
                               ("handoff", "verify"), ("verify", "result"), ("result", "complete"),
                               ("complete", "export")):
            self.assertLess(actions.index(earlier), actions.index(later), (earlier, later))

    def test_both_readmes_tell_the_same_journey(self):
        french = self._journey_actions(README_FR, "Le parcours d'une tâche")
        english = self._journey_actions(README_EN, "A task from request to closing")
        self.assertEqual(french, english)

    def test_the_french_page_says_what_is_in_english_and_that_briefs_can_be_french(self):
        text = _text(README_FR)
        top = text[:text.index("\n## ")]
        self.assertIn("en anglais", top)
        self.assertIn("questionnaire", top)
        self.assertIn("en français", top)

    def _journey_actions(self, page: Path, heading: str) -> list[str]:
        commands = _commands(_section(_text(page), heading))
        self.assertTrue(commands, page.name)
        self.assertTrue(all(words[0] == "task" for words in commands), page.name)
        return [words[1] for words in commands]


class GlossaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = {term: (gloss, en, fr) for term, gloss, en, fr in ENTRY.findall(_text(GLOSSARY))}

    def test_every_listed_term_is_defined_in_english_and_in_french(self):
        missing = [term for term in TERMS if term not in self.entries]
        self.assertEqual(missing, [], "Add an entry for each of these terms to docs/glossary.md.")
        for term in TERMS:
            gloss, english, french = self.entries[term]
            with self.subTest(term=term):
                self.assertTrue(gloss.strip() and english.strip() and french.strip())
                self.assertNotEqual(english, french)

    def test_every_heading_is_a_complete_entry(self):
        headings = re.findall(r"^### (.+)$", _text(GLOSSARY), re.MULTILINE)
        self.assertEqual(len(headings), len(self.entries), "Each term needs its gloss, an EN and an FR sentence.")

    def test_both_readmes_link_to_the_glossary(self):
        for page in (README_EN, README_FR):
            with self.subTest(page=page.name):
                self.assertIn("docs/glossary.md", LINK.findall(_text(page)))

    def test_relative_links_of_the_entry_pages_resolve(self):
        for page in (README_EN, README_FR, GLOSSARY):
            for target in LINK.findall(_text(page)):
                if re.match(r"[a-z]+:", target) or target.startswith("#"):
                    continue
                with self.subTest(page=page.name, link=target):
                    self.assertTrue((page.parent / target.split("#")[0]).exists())


if __name__ == "__main__":
    unittest.main()
