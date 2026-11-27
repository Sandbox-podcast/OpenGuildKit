"""Response to an incident (#481): a freeze and a longest age of an approval, both off by default.

`profile set freeze on` stops the edit hook and `guard --ci`; `profile set max-approval-age N` ends the cover of an
approval after N days. A project that sets neither reads its earlier records and answers as before; setting one
restricts, so an agent without a terminal may, and lifting or loosening one is a person's act at a terminal.
"""

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json

from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
BEFORE = json.loads((REPO / "tests" / "fixtures" / "upgrade" / "before-light-lane.json").read_text(encoding="utf-8"))
NOW = datetime.fromisoformat(BEFORE["now"])
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"


def edit_input(path: Path) -> str:
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(path)}})


class EarlierProject(unittest.TestCase):
    """A project written by an earlier release (tests/fixtures/upgrade/before-light-lane.json), guard on enforce, with an
    approved task, at the day of the fixture."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, content in BEFORE["files"].items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        self.days(0)

    def days(self, count: int):
        """The real clock `count` days after the day of the fixture."""
        patcher = patch("openguildkit.clock.real_now", return_value=NOW + timedelta(days=count))
        patcher.start()
        self.addCleanup(patcher.stop)

    def cli(self, *arguments, code=0, typed=None):
        # Without a typed line, no terminal: the suite may itself run at one.
        return run_cli(self.root, *arguments, expect=code, typed=typed, stdin="" if typed is None else None)

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def hook(self, path: Path, code: int):
        return run_cli(self.root, "guard", "--hook", "pre-edit", expect=code, stdin=edit_input(path))

    def covered(self) -> list[str]:
        return json.loads(self.cli("guard", "--json").stdout)["covered_by"]

    def row(self, task_id: str = "approved-task") -> dict:
        return next(item for item in json.loads(self.cli("task", "list", "--json").stdout) if item["id"] == task_id)


class OffByDefaultTests(EarlierProject):
    def test_issue_481_records_written_before_it_behave_as_before_when_neither_option_is_set(self):
        """Issue #481: a project that sets neither option reads its earlier records and answers as it did."""
        for name, content in BEFORE["files"].items():
            if name.startswith(".openguildkit/"):
                self.assertNotIn("frozen", content, name)
                self.assertNotIn("max_age_days", content, name)
        self.assertEqual(self.covered(), ["approved-task"])
        self.assertNotIn("approval_problem", self.row())
        context = json.loads(self.hook(self.root / "app.py", 0).stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("approved task(s) in progress: approved-task", context)
        self.days(400)
        self.assertEqual(self.covered(), ["approved-task"])
        target = self.root / "again.json"
        self.cli("task", "export", "done-task", "--output", target)
        self.assertEqual(target.read_text(encoding="utf-8"), BEFORE["files"][".openguildkit/decisions/done-task.json"])
        self.assertNotIn("approval", self.profile())


class FreezeTests(EarlierProject):
    def freeze(self, by="CM", reason="Model compromised"):
        return self.cli("profile", "set", "freeze", "on", "--by", by, "--reason", reason)

    def test_issue_481_a_frozen_project_refuses_an_edit_an_approved_task_covers_and_says_who_and_why(self):
        """Issue #481: no command or setting stopped the edits of agents in a project."""
        self.assertEqual(self.hook(self.root / "app.py", 0).returncode, 0)
        self.freeze()
        frozen = self.profile()["frozen"]
        self.assertEqual((frozen["by"], frozen["reason"]), ("CM", "Model compromised"))
        self.assertEqual(frozen["on"], self.profile()["changes"][-1]["on"])
        refused = self.hook(self.root / "app.py", 2).stderr
        self.assertIn(f"Edit refused: the project is frozen by CM since {frozen['on']}: Model compromised", refused)
        self.assertEqual(self.covered(), ["approved-task"])
        self.assertEqual(self.hook(Path(tempfile.gettempdir()) / "elsewhere.txt", 0).stderr, "")
        prompt = run_cli(self.root, "guard", "--hook", "prompt", stdin="").stdout
        self.assertIn("frozen by CM", json.loads(prompt)["hookSpecificOutput"]["additionalContext"])

    def test_issue_481_a_freeze_refuses_in_observe_mode_too_and_leaves_approvals_standing(self):
        """Issue #481: a freeze stops edits whatever the mode of the guard."""
        self.cli("profile", "set", "guard", "observe", "--by", "CM", "--reason", "x", typed="observe")
        self.hook(self.root / "app.py", 0)
        self.freeze()
        self.assertIn("frozen by CM", self.hook(self.root / "app.py", 2).stderr)
        self.assertNotIn("approval_problem", self.row())
        self.cli("task", "handoff", "approved-task")

    def test_issue_481_freezing_needs_no_terminal_and_lifting_it_needs_a_person(self):
        """Issue #481: a freeze only restricts; lifting it weakens a protection."""
        self.freeze()
        again = self.cli("profile", "set", "freeze", "on", "--by", "AB", "--reason", "x", code=1)
        self.assertIn(f"already frozen by CM since {self.profile()['frozen']['on']}", again.stderr)
        refused = self.cli("profile", "set", "freeze", "off", "--by", "CM", "--reason", "All clear", code=1)
        self.assertIn("weakens a protection", refused.stderr)
        self.assertIn("freeze lifted", refused.stderr)
        self.assertIn("frozen", self.profile())
        self.cli("profile", "set", "freeze", "off", "--by", "AB", "--reason", "All clear", typed="off")
        self.assertNotIn("frozen", self.profile())
        self.assertEqual(self.hook(self.root / "app.py", 0).returncode, 0)
        self.assertEqual([entry["change"] for entry in self.profile()["changes"]][-2:],
                         ["set freeze on", "set freeze off"])

    def test_issue_481_the_command_says_when_the_guard_is_off_and_the_freeze_stops_nothing(self):
        """Issue #481: a freeze is read by the guard; with the guard off it would silently do nothing."""
        self.cli("profile", "set", "guard", "off", "--by", "CM", "--reason", "x", typed="off")
        said = self.freeze().stdout
        self.assertIn("the guard is off", said)
        self.assertIn("profile set guard enforce", said)

    def test_issue_481_who_and_why_are_one_line_each(self):
        """Issue #481: the freeze is shown in a line of the hook: its fields hold one line."""
        refused = self.cli("profile", "set", "freeze", "on", "--by", "CM", "--reason", "two\nlines", code=1)
        self.assertIn("single line", refused.stderr)
        self.assertNotIn("frozen", self.profile())


class MaxAgeTests(EarlierProject):
    def limit(self, days: str, *, code=0, typed=None):
        return self.cli("profile", "set", "max-approval-age", days, "--by", "CM", "--reason", "Reconsult monthly",
                        code=code, typed=typed)

    def test_issue_481_an_approval_older_than_the_limit_no_longer_covers_and_task_list_says_to_consult_again(self):
        """Issue #481: an approval covered edits without a time limit; the stale flag after 14 days was a message."""
        self.limit("30")
        self.assertEqual(self.profile()["approval"], {"mode": "local", "max_age_days": 30})
        self.days(30)
        self.assertEqual(self.covered(), ["approved-task"])
        self.days(31)
        self.assertEqual(self.covered(), [])
        row = self.row()
        self.assertIn("31 days old", row["next"])
        self.assertIn("30 days", row["next"])
        self.assertIn("task consult approved-task --reuse-answers", row["next"])
        self.assertEqual((row["approval_problem"], row["severity"]), ("approval-expired", "error"))
        self.assertIn("31 days old", self.cli("task", "handoff", "approved-task", code=1).stderr)
        self.assertIn("31 days old", self.cli("check", code=1).stderr)
        sarif = json.loads(self.cli("check", "--format", "sarif", code=1).stdout)
        self.assertIn("decision-expired", {item["ruleId"] for item in sarif["runs"][0]["results"]})
        self.assertIn("Edit refused", self.hook(self.root / "app.py", 2).stderr)

    def test_issue_481_profile_export_names_the_command_for_the_limit(self):
        """Issue #481: another repository does not inherit a limit without a person typing it."""
        self.limit("30")
        exported = self.cli("profile", "export")
        self.assertNotIn("approval", json.loads(exported.stdout))
        self.assertIn("profile set max-approval-age DAYS", exported.stderr)

    def test_issue_481_a_completed_task_is_history_and_the_limit_does_not_reach_it(self):
        """Issue #481: only an approval that still covers work expires."""
        self.limit("1")
        self.days(100)
        self.assertNotIn("approval_problem", self.row("done-task"))

    def test_issue_481_the_limit_is_tightened_by_anyone_and_loosened_by_a_person(self):
        """Issue #481: a shorter limit restricts; a longer one, or none, weakens a protection."""
        self.limit("30")
        self.limit("20")
        refused = self.limit("60", code=1)
        self.assertIn("weakens a protection", refused.stderr)
        self.assertIn("approval age limit", refused.stderr)
        self.assertEqual(self.profile()["approval"]["max_age_days"], 20)
        self.limit("60", typed="60")
        self.assertEqual(self.profile()["approval"]["max_age_days"], 60)
        self.limit("none", code=1)
        self.limit("none", typed="none")
        self.assertNotIn("approval", self.profile())
        self.limit("none", code=1)

    def test_issue_481_the_limit_is_a_whole_number_of_days_and_signing_keeps_it(self):
        """Issue #481: 1 to 366 days, like a waiver; turning signed approvals off leaves the limit in place."""
        for bad in ("0", "400", "soon"):
            self.assertIn("1 to 366", self.limit(bad, code=1).stderr)
        self.limit("30")
        self.cli("profile", "set", "approval", "local", "--by", "CM", "--reason", "x", code=1)
        self.assertEqual(self.profile()["approval"], {"mode": "local", "max_age_days": 30})

    def test_issue_481_an_approval_with_a_time_that_cannot_be_read_does_not_cover(self):
        """Issue #481: with a limit, an approval whose date is unreadable cannot be shown to be recent."""
        self.limit("30")
        path = self.root / ".openguildkit" / "tasks" / "approved-task.json"
        task = json.loads(path.read_text(encoding="utf-8"))
        task["decision"]["at"] = "sometime"
        write_json(path, task)
        self.assertEqual(self.covered(), [])


class CiTests(unittest.TestCase):
    """guard --ci on a base revision that is frozen: every change fails but the one that lifts the freeze."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "project"
        self.root.mkdir()
        self.answers = Path(temporary.name).resolve()  # Outside the project: no file of the test is a change.
        write_json(self.answers / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()),
                                                   "guard": "enforce"})
        self.git("init", "-q", "-b", "main")
        self.cli("init", "--answers", self.answers / "profile.json")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"})

    def cli(self, *arguments, code=0, typed=None):
        return run_cli(self.root, *arguments, expect=code, typed=typed, stdin="" if typed is None else None)

    def approve(self):
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.cli("task", "template", TASK).stdout)
        write_json(self.answers / "review.json", {"consultation_id": template["consultation_id"],
                                                  **json.loads((EXAMPLE / "review.json").read_text())})
        self.cli("task", "review", TASK, "--file", self.answers / "review.json")
        self.cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", typed=TASK)

    def deliver(self):
        """Commit the work, then export the decision of the approved task and commit it."""
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "work")
        self.cli("task", "export", TASK)
        self.git("add", "-f", f".openguildkit/decisions/{TASK}.json")
        self.git("commit", "-q", "-m", "decision")

    def ci(self, code: int) -> dict:
        return json.loads(self.cli("guard", "--ci", "--base", "main", "--json", code=code).stdout)

    def freeze_main(self):
        self.cli("profile", "set", "freeze", "on", "--by", "CM", "--reason", "Server compromised")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "freeze")

    def test_issue_481_a_change_fails_on_a_frozen_base_whatever_its_decision(self):
        """Issue #481: the CI check is the barrier for pull requests: it fails for every change of a frozen base."""
        self.freeze_main()
        self.git("checkout", "-q", "-b", "change")
        self.approve()
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.deliver()
        result = self.ci(1)
        self.assertEqual((result["mode"], result["ok"]), ("enforce", False))
        self.assertTrue(any("frozen by CM since" in problem and "Server compromised" in problem
                            for problem in result["problems"]), result["problems"])
        sarif = json.loads(self.cli("guard", "--ci", "--base", "main", "--format", "sarif", code=1).stdout)
        self.assertIn("guard-frozen", {item["ruleId"] for item in sarif["runs"][0]["results"]})

    def test_issue_481_the_change_that_only_lifts_the_freeze_with_its_decision_passes(self):
        """Issue #481: the pull request that lifts the freeze is judged as any change, and no longer refused for it."""
        self.freeze_main()
        self.git("checkout", "-q", "-b", "lift")
        self.approve()
        self.cli("profile", "set", "freeze", "off", "--by", "AB", "--reason", "All clear", typed="off")
        self.deliver()
        result = self.ci(0)
        self.assertEqual((result["ok"], result["decisions"]), (True, [TASK]))
        # The same change with more in it is not the lifting alone.
        self.git("checkout", "-q", "-b", "lift-and-more")
        (self.root / "app.py").write_text("print('more')\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "more")
        self.assertTrue(any("frozen by CM" in problem for problem in self.ci(1)["problems"]))

    def test_issue_481_a_profile_edited_by_hand_is_not_a_lifting(self):
        """Issue #481: only the profile with `frozen` removed and the freeze's own history entry lifts it."""
        self.freeze_main()
        self.git("checkout", "-q", "-b", "edit")
        path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        del profile["frozen"]
        write_json(path, profile)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "drop the freeze by hand")
        self.assertTrue(any("frozen by CM" in problem for problem in self.ci(1)["problems"]))

    def test_issue_481_an_unfrozen_base_is_judged_as_before(self):
        """Issue #481: with no freeze on the base revision the check is the one it was."""
        self.git("checkout", "-q", "-b", "change")
        self.approve()
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.deliver()
        result = self.ci(0)
        self.assertEqual((result["ok"], result["decisions"]), (True, [TASK]))
        self.assertFalse(any("frozen" in problem for problem in result["problems"]))
