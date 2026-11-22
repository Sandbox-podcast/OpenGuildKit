"""The first run of a newcomer: init in a terminal, init without one, and the README steps in the order that works.

A first `check` failed because the README put it before `host apply`, the README promised that Enter keeps a
default on every question, a copy of the README stopped at `init` without a terminal, and the interactive `init`
(its prompts, its confirmation, its "nothing was written") ran in no test.
"""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.workflow import validate_answers

REPO = Path(__file__).resolve().parents[1]
CONFIRMATION = "Write this profile and these rules? [Y/n]"


class InteractiveInitTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "portal"
        self.root.mkdir()

    def init(self, confirmation: str, terminal: bool = True) -> tuple[int, str]:
        """Run `openguildkit init` as typed in a terminal: Enter on every question, except the required one."""
        screen = io.StringIO()
        replies = []

        def answer(*_):
            shown = screen.getvalue()
            replies.append(shown)
            if len(replies) > 40:
                raise AssertionError(f"init kept asking: {shown[-300:]}")
            if CONFIRMATION in shown[-200:]:
                return confirmation
            question = shown[shown.rfind("> \n"):]  # the reply is not echoed: a new question follows "> "
            return "no" if "process personal data" in question else ""

        with patch("sys.stdin.isatty", return_value=terminal), patch("builtins.input", side_effect=answer), \
                contextlib.redirect_stderr(screen), contextlib.redirect_stdout(io.StringIO()):
            code = main(["--project", str(self.root), "init"])
        return code, screen.getvalue()

    def written(self) -> list[str]:
        return sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))

    def test_answering_no_to_the_confirmation_writes_nothing(self):
        code, screen = self.init("n")
        self.assertEqual(code, 1)
        self.assertIn(CONFIRMATION, screen)
        self.assertIn("Setup cancelled. Nothing was written.", screen)
        self.assertEqual(self.written(), [])

    def test_answering_yes_writes_the_profile_and_the_instructions(self):
        code, screen = self.init("o")
        self.assertEqual(code, 0, screen)
        self.assertTrue((self.root / "AGENTS.md").is_file())
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["name"], "portal")
        self.assertFalse(profile["personal_data"])

    def test_without_a_terminal_init_points_to_the_questions_and_answers_files(self):
        code, screen = self.init("o", terminal=False)
        self.assertEqual(code, 1)
        self.assertIn("openguildkit init --questions", screen)
        self.assertIn("openguildkit init --answers", screen)
        self.assertEqual(self.written(), [])


def _section(text: str, heading: str) -> str:
    start = text.index(f"## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


class ReadmeFirstRunTest(unittest.TestCase):
    PAGES = {
        "README.md": ("Set up your project", "A task from request to closing", "required"),
        "README.fr.md": ("Configurer ton projet", "Le parcours d'une tâche", "obligatoire"),
    }

    def test_host_apply_comes_before_the_first_check(self):
        for name, (setup, _, _) in self.PAGES.items():
            with self.subTest(page=name):
                block = re.search(r"```bash\n(.*?)```", _section((REPO / name).read_text(encoding="utf-8"), setup),
                                  re.DOTALL).group(1)
                commands = [line.split("#")[0].strip() for line in block.splitlines()]
                self.assertLess(commands.index("openguildkit host apply"), commands.index("openguildkit check"))

    def test_the_enter_key_sentence_names_the_required_question(self):
        for name, (setup, _, required) in self.PAGES.items():
            with self.subTest(page=name):
                section = _section((REPO / name).read_text(encoding="utf-8"), setup)
                sentence = next(part for part in re.split(r"(?<=\.) ", section) if re.search(r"\bEnt(er|rée)\b", part))
                self.assertIn(required, sentence)

    def test_the_readme_shows_task_answers_the_cli_accepts_and_the_init_files(self):
        for name, (setup, journey, _) in self.PAGES.items():
            with self.subTest(page=name):
                text = (REPO / name).read_text(encoding="utf-8")
                example = json.loads(re.search(r"```json\n(.*?)```", _section(text, journey), re.DOTALL).group(1))
                self.assertIn("concerns", example)
                validate_answers(example)
                setup_text = _section(text, setup)
                self.assertIn("init --questions", setup_text)
                self.assertIn("init --answers", setup_text)


if __name__ == "__main__":
    unittest.main()
