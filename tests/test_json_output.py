"""The shape of the --json outputs (#484): with OPENGUILDKIT_JSON_ENVELOPE=1 every answer comes in one envelope that
carries schema_version, and an error under --json is JSON on standard output, with its code (#487)."""

import ast
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import ENVELOPE_VARIABLE
from tests.support import run_cli
from tests.test_approval_lifecycle import ApprovalCase
from tests.test_command_output_budget import EXAMPLES, Projects, command_of

REPO = Path(__file__).resolve().parents[1]
JSON_EXAMPLES = [example for example in EXAMPLES if "--json" in shlex.split(example.command)]


def command_words(example) -> str:
    """The words of the command of an example, up to its first argument that is not a subcommand."""
    return " ".join(command_of(example))


class EnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory(prefix="ogk-test-json-")
        cls.addClassCleanup(folder.cleanup)
        cls.projects = Projects(Path(folder.name))

    def test_issue_484_every_json_example_answers_in_the_envelope(self):
        """Issue #484: of 26 --json outputs, none carried schema_version and 11 were bare lists."""
        self.assertGreaterEqual(len(JSON_EXAMPLES), 40)
        for example in JSON_EXAMPLES:
            with self.subTest(command=example.command):
                if example.stage in Projects.NEEDS_GIT and shutil.which("git") is None:
                    self.skipTest("needs git")
                self.projects.stage(example.stage)  # Built without the envelope, which the stages read.
                with patch.dict(os.environ, {ENVELOPE_VARIABLE: "1"}):
                    result = self.projects.run(example)
                self.assertEqual(result.returncode, example.code, result.stderr[-500:])
                answer = json.loads(result.stdout)
                self.assertEqual(answer["schema_version"], 1)
                if "error" not in answer or example.code == 0:
                    self.assertEqual((answer["command"], set(answer)), (command_words(example),
                                                                        {"schema_version", "command", "data"}))

    def test_issue_484_without_the_variable_an_answer_keeps_its_shape(self):
        """Issue #484: the envelope changes the shape the web page and scripts read; it is asked for, not imposed."""
        example = next(example for example in JSON_EXAMPLES if example.command == "task list --json")
        with patch.dict(os.environ, {ENVELOPE_VARIABLE: ""}):
            self.assertIsInstance(json.loads(self.projects.run(example).stdout), list)

    def test_issue_484_no_module_prints_json_around_print_json(self):
        """Issue #484: alerts, market, tools and features printed their JSON themselves, out of any common shape."""
        found = []
        for path in sorted((REPO / "src" / "openguildkit").glob("*.py")):
            if path.name in ("storage.py", "cli.py"):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print" \
                        and node.args and isinstance(node.args[0], ast.Call) \
                        and ast.unparse(node.args[0].func) in ("json_text", "json.dumps"):
                    found.append(f"{path.name}:{node.lineno}")
        self.assertEqual(found, [], "print a --json answer with storage.print_json")


class JsonErrorTests(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_issue_484_an_error_under_json_is_json_with_the_usual_exit_code(self):
        """Issue #484: under --json, an error left standard output empty and was a sentence on standard error."""
        result = run_cli(self.root, "task", "checks", "nope", "--json", expect=1)
        error = json.loads(result.stdout)
        self.assertEqual(error["schema_version"], 1)
        self.assertEqual(error["error"]["code"], "OGK-TASK-021")
        self.assertTrue(error["error"]["message"].startswith("Unknown task: nope."), error)
        self.assertEqual(result.stderr, f"OpenGuildKit [OGK-TASK-021]: {error['error']['message']}\n")
        uncoded = run_cli(self.root, "recommend", "--answers", self.root / "missing.json", "--json", expect=1)
        self.assertEqual(json.loads(uncoded.stdout)["error"]["code"], None)
        self.assertEqual(uncoded.stderr, f"OpenGuildKit: {json.loads(uncoded.stdout)['error']['message']}\n")
        coded = json.loads(run_cli(self.root, "task", "list", "--since", "2026-02-30", "--json", expect=1).stdout)
        self.assertEqual(coded["error"]["code"], "OGK-TASK-006")
        self.assertEqual(run_cli(self.root, "task", "list", "--since", "2026-02-30", expect=1).stdout, "")

    def test_issue_484_the_error_names_the_command_to_run_next(self):
        """Issue #484: the error object gives the command a message names in error.next."""
        result = run_cli(self.root.parent, "task", "list", "--json", expect=1)
        self.assertEqual(json.loads(result.stdout)["error"]["next"], "openguildkit init")

    def test_issue_484_check_answers_in_json(self):
        """Issue #484: check, the first command an agent runs, had no structured output."""
        answer = json.loads(self.run_cli("check", "--json")[0])
        self.assertEqual(answer, {"passes": True, "findings": []})
        _, error = self.run_cli("check", "--json", "--format", "sarif", code=1)
        self.assertTrue(error.startswith("OpenGuildKit [OGK-CHECK-001]: --format sarif and --json both print"), error)


if __name__ == "__main__":
    unittest.main()
