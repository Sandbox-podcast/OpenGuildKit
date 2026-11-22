"""Small fixes from the field audit: update shows what changes and who it touches, alerts and dossiers say what to do."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import _print_update, main
from openguildkit.storage import write_json
from openguildkit.test_commands import suggest_checks

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
            "stale_tasks": [{"id": "request-status", "status": "done"}],
        }
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            _print_update(result, False)
        text = out.getvalue()
        self.assertIn("was: Keep secrets out of code.", text)
        self.assertIn("now: Keep secrets out of code and logs.", text)
        self.assertIn("Task request-status (done)", text)
        self.assertLess(text.index("Task request-status"), text.index("Nothing changed"))


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
        _, quiet = self.cli("alerts", "import", FIXTURES / "npm-audit-critical.json", "--task", "status")
        self.assertNotIn("consult", quiet)
        self.cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json")
        _, note = self.cli("alerts", "import", FIXTURES / "npm-audit-critical.json", "--task", "status")
        self.assertIn("openguildkit task consult status again", note)
        _, note = self.cli("task", "alerts", "status", "--import", FIXTURES / "npm-audit-critical.json")
        self.assertIn("task consult status again", note)

    def test_a_dossier_about_another_subject_is_flagged_in_the_consultation(self):
        market = self.root / ".openguildkit" / "market"
        market.mkdir(parents=True, exist_ok=True)
        dossier = json.loads((EXAMPLE.parent / "market-dossier" / "support-portals.json").read_text(encoding="utf-8"))
        dossier.update(id="storage", title="Cold storage vendors", market="Object storage in Europe",
                       feature="Archive tiers for rarely read files")
        write_json(market / "storage.json", dossier)
        output, _ = self.cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json", "--market", "storage")
        self.assertEqual(sum("the task does not mention it" in line for line in output.splitlines()), 1)
        scope = json.loads(self.cli("task", "show", "status")[0])["consultation"]["scope"]
        self.assertIn("does not mention it", scope["market"]["relevance"])
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

    def test_the_commands_a_repository_points_to_are_proposed_and_nothing_is_run(self):
        root = self.folder()
        self.assertEqual(suggest_checks(root), [])
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}}), encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text("", encoding="utf-8")
        (root / "pom.xml").write_text("<project/>", encoding="utf-8")
        (root / "api").mkdir()
        (root / "api" / "Api.csproj").write_text("<Project/>", encoding="utf-8")
        self.assertEqual(suggest_checks(root), ["npm test", "npm run lint", "python -m unittest discover -s tests", "dotnet test"])

    def test_the_placeholder_npm_test_script_and_pytest_configuration(self):
        root = self.folder()
        (root / "package.json").write_text(
            json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}), encoding="utf-8")
        (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
        self.assertEqual(suggest_checks(root), ["python -m pytest"])

    def test_init_offers_them_as_the_default_of_the_checks_question(self):
        root = self.folder()
        (root / "go.mod").write_text("module example.org/app\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--project", str(root), "init", "--questions"]), 0)
        question = next(item for item in json.loads(out.getvalue()) if item["id"] == "checks")
        self.assertEqual(question["default"], ["go test ./..."])
        self.assertIn("keep or remove each", question["prompt"])


if __name__ == "__main__":
    unittest.main()
