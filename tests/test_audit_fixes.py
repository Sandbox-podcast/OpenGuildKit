"""Small fixes from the field audit: update shows what changes and who it touches, alerts and dossiers say what to do."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import _print_update, main
from openguildkit.storage import write_json
from openguildkit.project_checks import propose_checks

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "alerts"


class UpdatePreviewTests(unittest.TestCase):
    def test_a_preview_shows_the_old_and_the_new_rule_and_the_tasks_it_would_touch(self):
        result = {
            "changes": [{"collection": "packs", "id": "secure-sdlc", "status": "changed", "fields": ["rules"],
                         "version": ["1.0.0", "1.1.0"],
                         "rules": {"added": [], "removed": [], "changed": [
                             {"id": "protect-secrets", "before": "Keep secrets out of code.",
                              "after": "Keep secrets out of code and logs."}]},
                         "sources": {"added": [], "removed": [], "redated": []}}],
            "conflicts": [], "applied": False, "catalog_date": "2026-11-21",
            "stale_tasks": [{"id": "request-status", "status": "approved",
                             "step": "consult it again (openguildkit task consult request-status) or open a linked task"}],
        }
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _print_update(result, False)
        text = out.getvalue()
        self.assertIn("before: Keep secrets out of code.", text)
        self.assertIn("after:  Keep secrets out of code and logs.", text)
        self.assertIn("request-status (approved): consult it again", text)
        self.assertLess(text.index("request-status (approved)"), text.index("Nothing changed"))


class AlertAndDossierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")))
        self.cli("init", "--answers", self.root / "profile.json")
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "status")

    def cli(self, *args, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(["--project", str(self.root), *map(str, args)])
        self.assertEqual(result, code, err.getvalue())
        return out.getvalue(), err.getvalue()

    def test_an_import_for_a_task_that_was_consulted_says_to_consult_again(self):
        quiet, _ = self.cli("alerts", "import", FIXTURES / "npm-audit-critical.json", "--task", "status")
        self.assertNotIn("consult", quiet)
        self.cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json")
        note, _ = self.cli("alerts", "import", FIXTURES / "npm-audit-critical.json", "--task", "status")
        self.assertIn("openguildkit task consult status again", note)
        note, _ = self.cli("task", "alerts", "status", "--import", FIXTURES / "npm-audit-critical.json")
        self.assertIn("task consult status again", note)

    def test_a_dossier_about_another_subject_is_flagged_in_the_consultation(self):
        market = self.root / ".openguildkit" / "market"
        market.mkdir(parents=True, exist_ok=True)
        dossier = json.loads((EXAMPLE.parent / "market-dossier" / "support-portals.json").read_text(encoding="utf-8"))
        dossier.update(id="storage", title="Cold storage vendors", market="Object storage in Europe",
                       feature="Archive tiers for rarely read files")
        write_json(market / "storage.json", dossier)
        self.cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json", "--market", "storage")
        scope = json.loads(self.cli("task", "show", "status")[0])["consultation"]["scope"]
        self.assertIn("shares no word with the task brief", scope["market"]["relevance"])
        write_json(market / "support-portals.json", json.loads(
            (EXAMPLE.parent / "market-dossier" / "support-portals.json").read_text(encoding="utf-8")))
        self.cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json", "--market", "support-portals")
        scope = json.loads(self.cli("task", "show", "status")[0])["consultation"]["scope"]
        self.assertNotIn("relevance", scope["market"])


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
