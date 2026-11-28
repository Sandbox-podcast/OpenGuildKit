"""init proposes the project's test commands, and a failed check says why and what to do next."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.detect import detect_stack
from openguildkit.init_cli import _prompt_checks
from openguildkit.project_checks import failure_message, propose_checks
from openguildkit.storage import write_json
from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


class ProjectTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, relative: str, text: str = "") -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def proposals(self) -> list[str]:
        return [item["command"] for item in propose_checks(self.root, detect_stack(self.root))]


class ProposalTests(ProjectTests):
    def test_each_test_runner_the_repository_shows_is_proposed(self):
        cases = {
            "npm": ({"package.json": '{"name": "web", "scripts": {"test": "jest"}}'}, ["npm test"]),
            "pytest": ({"pyproject.toml": '[project]\nname = "svc"\n[project.optional-dependencies]\ndev = ["pytest"]\n'},
                       ["python -m pytest"]),
            "unittest": ({"pyproject.toml": '[project]\nname = "svc"\n', "tests/test_app.py": ""},
                         ["python -m unittest discover -s tests"]),
            "go": ({"go.mod": "module example.test/svc\n\ngo 1.22\n"}, ["go test ./..."]),
            "maven": ({"pom.xml": "<project><artifactId>svc</artifactId></project>"}, ["mvn test"]),
            "gradle": ({"build.gradle": "plugins { id 'java' }\n", "gradlew": ""}, ["./gradlew test"]),
            "cargo": ({"Cargo.toml": '[package]\nname = "svc"\n'}, ["cargo test"]),
            "dotnet": ({"Api.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>'}, ["dotnet test"]),
        }
        for name, (files, expected) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                for relative, text in files.items():
                    self.write(relative, text)
                self.assertEqual(self.proposals(), expected)

    def test_a_sub_folder_with_only_a_test_script_gets_its_command(self):
        self.write("tools/linter/package.json", '{"name": "linter", "scripts": {"test": "node --test"}}')
        self.assertEqual(self.proposals(), ["cd tools/linter && npm test"])

    def test_a_dotnet_solution_covers_its_test_project(self):
        self.write("App.sln", "Microsoft Visual Studio Solution File, Format Version 12.00\n")
        self.write("App/App.csproj", '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>')
        self.write("App.Tests/App.Tests.csproj", '<Project Sdk="Microsoft.NET.Sdk"></Project>')
        self.assertEqual(self.proposals(), ["dotnet test"])

    def test_a_placeholder_script_or_a_bare_repository_proposes_nothing(self):
        self.write("package.json", '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}')
        self.assertEqual(self.proposals(), [])

    def test_a_component_s_command_runs_from_its_folder(self):
        self.write("apps/web/package.json", '{"scripts": {"test": "vitest run"}, "dependencies": {"react": "18.3.1"}}')
        self.write("services/api/go.mod", "module example.test/api\n\ngo 1.22\n")
        self.assertEqual(self.proposals(), ["cd apps/web && npm test", "cd services/api && go test ./..."])

    def test_setup_proposes_unittest_without_a_python_manifest(self):
        self.write("tests/test_smoke.py", "")
        questions = json.loads(self.run_cli("init", "--questions")[0])
        checks = next(question for question in questions if question["id"] == "checks")
        self.assertEqual([item["command"] for item in checks.get("proposed", [])], ["python -m unittest discover -s tests"])

    def test_a_component_path_with_spaces_works_in_the_check_shell(self):
        self.write("client app/pyproject.toml", '[project]\nname = "client"\n')
        self.write("client app/tests/test_smoke.py", """
import unittest

class SmokeTest(unittest.TestCase):
    def test_smoke(self):
        self.assertTrue(True)
""")
        command, = self.proposals()
        self.assertEqual(command, 'cd "client app" && python -m unittest discover -s tests')
        executable_command = command.replace(" && python ", f' && "{sys.executable}" ', 1)
        result = subprocess.run(executable_command, cwd=self.root, shell=True, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ran 1 test", result.stderr)

    def test_the_questionnaire_proposes_them_and_keeps_none_without_a_confirmation(self):
        self.write("package.json", '{"name": "web", "scripts": {"test": "jest"}}')
        questions = {question["id"]: question for question in json.loads(self.run_cli("init", "--questions")[0])}
        checks = questions["checks"]
        self.assertEqual(checks["default"], [])
        self.assertEqual(checks["proposed"], [{"command": "npm test", "evidence": ".: a test script in package.json"}])
        self.assertIn("confirm or remove", checks["prompt"])
        write_json(self.root / "answers.json", {"name": "Web", "personal_data": "no"})
        output, _ = self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertIn("Test commands found but not kept as project checks: npm test.", output)
        self.assertEqual(json.loads((self.root / ".openguildkit" / "project.json").read_text())["checks"], [])

    def test_init_says_which_checks_task_verify_runs(self):
        write_json(self.root / "answers.json", {"name": "Web", "personal_data": "no", "checks": ["npm test"]})
        output, _ = self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertIn("Project checks run by task verify: npm test.", output)
        bare = tempfile.TemporaryDirectory()
        self.addCleanup(bare.cleanup)
        self.root = Path(bare.name)
        write_json(self.root / "answers.json", {"name": "Web", "personal_data": "no"})
        output, _ = self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertIn("No project check: task verify runs no test command", output)

    def test_the_person_keeps_each_proposed_command_with_a_yes(self):
        question = {"id": "checks", "type": "list", "prompt": "Checks?", "default": [],
                    "proposed": [{"command": "npm test", "evidence": "."}, {"command": "go test ./...", "evidence": "."}]}
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["y", "", "make lint"]), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(_prompt_checks(question), ["npm test", "make lint"])


class FailureTests(ProjectTests):
    def test_the_message_names_the_cause_the_last_lines_the_next_step_and_the_log(self):
        log = ".openguildkit/tasks/t-checks/command-1.log"
        cases = [
            (127, "> jest\nsh: jest: command not found\n", "command not found", "install the project's dependencies"),
            (1, "'jest' is not recognized as an internal or external command,\n", "command not found", "install"),
            (1, "Error: Cannot find module 'express'\n", "a dependency or the network is missing", "network"),
            (2, "ModuleNotFoundError: No module named 'fastapi'\n", "a dependency or the network is missing", "network"),
            (None, "Timed out after 5 seconds.\n", "timed out", "by hand"),
            (1, "FAILED tests/test_app.py::test_total\n1 failed\n", "exit code 1", "fix the code or the test"),
        ]
        for code, output, cause, step in cases:
            with self.subTest(output=output):
                message = failure_message(code, output, log)
                self.assertIn(cause, message)
                self.assertIn(step, message)
                self.assertIn(output.strip().splitlines()[-1].strip(), message)
                self.assertTrue(message.endswith(f"Log: {log}"))
                self.assertEqual(len(message.splitlines()), 1)
        self.assertIn("no output", failure_message(1, "", log))
        many = "\n".join(f"line {index}" for index in range(10))
        self.assertIn("line 7 | line 8 | line 9", failure_message(1, many, log))
        self.assertNotIn("line 6", failure_message(1, many, log))
        # The line that names the error comes first, even when a stack trace ends the output.
        node = ("node:internal/modules/cjs/loader:1228\n  throw err;\n  ^\n\nError: Cannot find module 'express'\n"
                "Require stack:\n- /app/[eval]\n    at Module._resolveFilename (node:internal)\n{\n"
                "  code: 'MODULE_NOT_FOUND',\n  requireStack: [ '/app/[eval]' ]\n}\n\nNode.js v26.13.0\n")
        message = failure_message(1, node, log)
        self.assertIn("Error: Cannot find module 'express' | } | Node.js v26.13.0", message)
        self.assertIn("a dependency or the network is missing", message)

    def approved(self, script: str) -> None:
        command = f'"{sys.executable}" -c "{script}"'
        profile = {"personal_data": "no", "name": "Portal", "stack": ["Python"], "packs": ["python"], "checks": [command]}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

    def test_verify_and_complete_show_why_a_mandatory_check_failed_and_where_its_log_is(self):
        self.approved("import sys; print('sh: jest: command not found'); sys.exit(127)")
        # A failed mandatory command makes task verify exit with 1, so a script or a CI job can tell.
        output, _ = self.run_cli("task", "verify", TASK, code=1)
        log = f".openguildkit/tasks/{TASK}-checks/command-1.log"
        self.assertIn("command:1: failed", output)
        self.assertIn(f"exit code 127, command not found: sh: jest: command not found. Next: install", output)
        self.assertIn(f"Log: {log}", output)
        self.assertTrue((self.root / log).is_file())
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("command:1 is mandatory and failed: exit code 127, command not found", error)
        self.assertIn(f"Log: {log}", error)

    def test_a_passing_check_carries_no_failure_message(self):
        self.approved("print('ok')")
        self.run_cli("task", "verify", TASK)
        record = json.loads(self.run_cli("task", "show", TASK, "--json")[0])
        self.assertNotIn("message", record["result"]["checks"][0])


class SuggestedChecksTests(unittest.TestCase):
    def folder(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def commands(self, root, *components):
        detected = {"components": [{"path": path} for path in components]}
        return [item["command"] for item in propose_checks(root, detected)]

    def test_the_commands_a_repository_points_to_are_proposed_and_nothing_is_run(self):
        root = self.folder()
        self.assertEqual(self.commands(root), [])
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}}), encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text("", encoding="utf-8")
        (root / "pom.xml").write_text("<project/>", encoding="utf-8")
        (root / "api").mkdir()
        (root / "api" / "Api.csproj").write_text("<Project/>", encoding="utf-8")
        before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
        self.assertEqual(self.commands(root, ".", "api"), ["npm test", "npm run lint", "cd api && dotnet test"])
        self.assertEqual(sorted(path.relative_to(root).as_posix() for path in root.rglob("*")), before)

    def test_the_placeholder_npm_test_script_and_pytest_configuration(self):
        root = self.folder()
        (root / "package.json").write_text(
            json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}), encoding="utf-8")
        (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
        self.assertEqual(self.commands(root), ["python -m pytest"])

    def test_the_suggested_unittest_command_runs_tests_at_the_project_root(self):
        root = self.folder()
        (root / "test_root.py").write_text(
            "import unittest\n"
            "class RootTest(unittest.TestCase):\n"
            "    def test_root(self): pass\n",
            encoding="utf-8",
        )
        (command,) = self.commands(root)
        result = subprocess.run([sys.executable, *command.split()[1:]], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ran 1 test", result.stderr)

    def test_init_proposes_them_in_the_checks_question_for_the_person_to_confirm(self):
        root = self.folder()
        (root / "go.mod").write_text("module example.org/app\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", str(root), "init", "--questions"]), 0)
        question = next(item for item in json.loads(out.getvalue()) if item["id"] == "checks")
        self.assertEqual([item["command"] for item in question["proposed"]], ["go test ./..."])
        self.assertEqual(question["default"], [])
        self.assertIn("confirm or remove each one", question["prompt"])


if __name__ == "__main__":
    unittest.main()
