"""The profile changes after setup through openguildkit profile, with who, when and why, never by hand."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.storage import write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
DAY = {"SOURCE_DATE_EPOCH": "1795219200"}  # 2026-11-21


class ProfileCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"]})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch.dict("os.environ", DAY):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def agents(self) -> str:
        return (self.root / "AGENTS.md").read_text(encoding="utf-8")

    def test_a_second_init_fails_and_names_the_profile_command(self):
        _, error = self.run_cli("init", "--answers", self.root / "answers.json", code=1)
        self.assertIn("already initialized", error)
        self.assertIn("openguildkit profile", error)

    def test_adopt_records_who_when_and_why_and_rewrites_the_instructions(self):
        output, _ = self.run_cli("profile", "adopt", "gdpr-personal-data", "--by", "Camille Martin",
                                 "--reason", "The sign-up form stores emails")
        self.assertIn("Profile changed: adopt gdpr-personal-data, by Camille Martin on 2026-11-21", output)
        self.assertIn("gdpr-personal-data", self.profile()["patterns"])
        self.assertEqual(self.profile()["changes"][-1], {"change": "adopt gdpr-personal-data", "by": "Camille Martin",
                                                         "on": "2026-11-21", "reason": "The sign-up form stores emails"})
        self.assertIn("Adopted `gdpr-personal-data` by Camille Martin on 2026-11-21", self.agents())
        preview, _ = self.run_cli("preview")
        self.assertIn("gdpr-personal-data (+", preview)
        self.assertIn("adopted by Camille Martin on 2026-11-21: The sign-up form stores emails", preview)
        self.run_cli("check")

    def test_declining_a_regulation_is_typed_at_a_terminal_and_shows_everywhere(self):
        self.run_cli("profile", "adopt", "gdpr-personal-data", "--by", "Camille", "--reason", "Emails")
        arguments = ("profile", "decline", "gdpr-personal-data", "--by", "Camille Martin", "--reason", "No personal data")
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli(*arguments, code=1)
        self.assertIn("weakens a protection", error)
        self.assertIn("gdpr-personal-data", self.profile()["patterns"])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="gdpr-personal-data"):
            self.run_cli(*arguments)
        profile = self.profile()
        self.assertNotIn("gdpr-personal-data", profile.get("patterns", []))
        self.assertEqual(profile["declined"], [{"id": "gdpr-personal-data", "by": "Camille Martin", "on": "2026-11-21",
                                                "reason": "No personal data"}])
        self.assertIn("Declined `gdpr-personal-data` by Camille Martin on 2026-11-21: No personal data", self.agents())
        preview, _ = self.run_cli("preview")
        self.assertIn("Declined, not active: gdpr-personal-data by Camille Martin", preview)
        recommend, _ = self.run_cli("recommend")
        self.assertIn("gdpr-personal-data by Camille Martin on 2026-11-21: No personal data", recommend)
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        consultation, _ = self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        self.assertIn("- Declined, not active: gdpr-personal-data by Camille Martin on 2026-11-21: No personal data.",
                      consultation)
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        record = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertEqual(record["declined"], profile["declined"])
        self.run_cli("check")

    def test_lowering_the_guard_or_allowing_public_research_needs_a_terminal(self):
        for field, value in (("guard", "off"), ("research", "public-sources")):
            with self.subTest(field=field), patch("sys.stdin.isatty", return_value=False):
                _, error = self.run_cli("profile", "set", field, value, "--by", "Sam", "--reason", "Demo", code=1)
                self.assertIn("is the person's decision", error)
        output, _ = self.run_cli("profile", "set", "guard", "enforce", "--by", "Sam", "--reason", "Audit")
        self.assertIn("openguildkit host apply", output)
        self.assertEqual(self.profile()["guard"], "enforce")

    def test_lists_change_by_command_and_refuse_what_is_unknown_or_already_there(self):
        self.run_cli("profile", "add", "check", "python -m unittest", "--by", "Sam", "--reason", "Tests exist")
        self.run_cli("profile", "add", "tool", "Jira", "--by", "Sam", "--reason", "Tracker")
        self.run_cli("profile", "add", "role", "backend", "--by", "Sam", "--reason", "API team")
        self.run_cli("profile", "add", "pack", "api-design", "--by", "Sam", "--reason", "Public API")
        self.run_cli("profile", "add", "board", "security", "--by", "Sam", "--reason", "Always")
        self.run_cli("profile", "add", "convention", "Branches are named feature/X", "--by", "Sam", "--reason", "Team")
        profile = self.profile()
        self.assertEqual(profile["checks"], ["python -m unittest"])
        self.assertEqual((profile["tools"], profile["roles"], profile["boards"]), (["Jira"], ["backend"], ["security"]))
        self.assertIn("api-design", profile["packs"])
        self.run_cli("profile", "remove", "check", "python -m unittest", "--by", "Sam", "--reason", "Moved to CI")
        self.assertEqual(self.profile()["checks"], [])
        self.run_cli("profile", "set", "host", "codex", "--by", "Sam", "--reason", "Team moved")
        self.assertEqual(self.profile()["host"], "codex")
        for arguments, message in ((("add", "pack", "no-such-pack"), "Unknown pack"),
                                   (("add", "tool", "Jira"), "already in"),
                                   (("remove", "pack", "agent-workflow"), "required"),
                                   (("set", "guard", "strict"), "guard must be one of")):
            with self.subTest(arguments=arguments):
                _, error = self.run_cli("profile", *arguments, "--by", "Sam", "--reason", "x", code=1)
                self.assertIn(message, error)
        self.assertEqual(len(self.profile()["changes"]), 8)

    def test_a_change_names_the_tasks_it_touches_as_update_and_sync_do(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        output, _ = self.run_cli("profile", "add", "pack", "api-design", "--by", "Sam", "--reason", "Public API")
        self.assertIn("Tasks consulted under the previous rules:", output)
        self.assertIn(f"  {TASK} (consulting): ", output)

    def test_a_new_condition_names_the_norm_it_brings(self):
        output, _ = self.run_cli("profile", "set", "personal-data", "yes", "--by", "Sam", "--reason", "Accounts")
        self.assertIn("Norm gdpr-personal-data now concerns the project", output)
        self.assertNotIn("gdpr-personal-data", self.profile().get("patterns", []))
        self.assertIn("No open task was consulted under the previous profile.", output)


if __name__ == "__main__":
    unittest.main()
