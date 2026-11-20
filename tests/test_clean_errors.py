import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import CatalogError, _validate_entry, load_catalog
from openguildkit.cli import _prompt_choices, main
from openguildkit.storage import write_json

REPO = Path(__file__).resolve().parents[1]


class CleanErrorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments, code=1):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stderr.getvalue()

    def init(self):
        write_json(self.root / "answers.json", {"name": "Portal", "stack": ["Python"]})
        self.run_cli("init", "--answers", self.root / "answers.json", code=0)

    def test_deeply_nested_json_is_an_input_error(self):
        nested = self.root / "nested.json"
        nested.write_text('{"a":' + "[" * 300000 + "]" * 300000 + "}", encoding="utf-8")
        error = self.run_cli("recommend", "--answers", nested)
        self.assertIn("nested too deeply", error)

    def test_end_of_input_has_a_message(self):
        self.init()
        self.run_cli("task", "new", "Show statuses.", "--id", "status", code=0)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=EOFError):
            error = self.run_cli("task", "consult", "status")
        self.assertIn("Input ended before completion.", error)

    def test_undecodable_arguments_are_reported_without_a_traceback(self):
        if os.name != "posix":
            self.skipTest("byte arguments are a POSIX case")
        result = subprocess.run(
            [sys.executable, "-m", "openguildkit", "--project", str(self.root), "brains", "--id", b"\xff"],
            capture_output=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"OpenGuildKit: Unknown brain", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_hand_edited_task_records_are_reported_as_inconsistent(self):
        self.init()
        self.run_cli("task", "new", "Show statuses.", "--id", "status", code=0)
        path = self.root / ".openguildkit" / "tasks" / "status.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for change in ({"brief": 5}, {"status": "approved"}, {"rounds": 5}, {"rounds": [1]}, {"status": "unknown"}):
            path.write_text(json.dumps({**original, **change}), encoding="utf-8")
            for command in (("task", "questions", "status"), ("task", "handoff", "status")):
                error = self.run_cli(*command)
                self.assertIn("is inconsistent", error)
        path.write_text(json.dumps({key: value for key, value in original.items() if key != "status"}), encoding="utf-8")
        self.assertIn("is inconsistent", self.run_cli("task", "show", "status"))

    @unittest.skipUnless(os.name == "posix", "file modes are POSIX")
    def test_new_files_follow_the_umask(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.init()
        for name in ("AGENTS.md", "CLAUDE.md", ".openguildkit/project.json"):
            self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o644, name)

    def test_a_failed_command_leaves_no_state_folder(self):
        self.assertIn("missing a profile", self.run_cli("sync"))
        self.assertFalse((self.root / ".openguildkit").exists())

    def test_prompt_and_identifier_messages_are_precise(self):
        question = {"type": "multi-select", "choices": [{"id": "a"}, {"id": "b"}]}
        self.assertEqual(_prompt_choices(question, "1,"), ["a"])
        self.init()
        self.assertIn("reserved file name", self.run_cli("task", "new", "x", "--id", "con"))
        self.assertIn("task ID is empty", self.run_cli("task", "new", "x", "--id", ""))
        write_json(self.root / "policy.json", {"name": "x", "packs": ["export-link-expiry"]})
        self.assertIn("--policy-repo", self.run_cli("preview", "--answers", self.root / "policy.json"))

    def test_catalog_text_refuses_control_characters_and_misnamed_files(self):
        pack = json.loads(json.dumps(load_catalog()["packs"]["python"]))
        for text in ("Bar\u0085", "x\u007fy", "a b"):
            with self.assertRaises(CatalogError):
                _validate_entry("packs", {**pack, "title": text})
        packs = self.root / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        write_json(packs / "foo.json", {**pack, "id": "team-python"})
        with self.assertRaisesRegex(CatalogError, "team-python.json"):
            load_catalog(self.root / ".openguildkit" / "catalog")

    def test_replay_refuses_a_file_as_project(self):
        target = self.root / "file.txt"
        target.write_text("x", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(REPO / "examples" / "request-status" / "replay.py"), "--project", str(target)],
            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is a file", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
