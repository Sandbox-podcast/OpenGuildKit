import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.storage import write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}


class GuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments, code=0, stdin=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        replaced = patch("sys.stdin", io.StringIO(stdin)) if stdin is not None else contextlib.nullcontext()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), replaced:
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def init(self, **extra):
        profile = {**json.loads((EXAMPLE / "profile.json").read_text()), **extra}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")

    def approve_example(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

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
        self.assertIn("Edit refused for", json.loads(output)["hookSpecificOutput"]["additionalContext"])

    def test_host_apply_installs_the_hooks(self):
        self.init(guard="enforce", host="claude-code")
        self.run_cli("host", "apply")
        hooks = json.loads((self.root / ".claude" / "settings.json").read_text())["hooks"]
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"], "openguildkit guard --hook pre-edit")
        self.assertEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["command"], "openguildkit guard --hook prompt")
        self.run_cli("host", "apply")
        self.assertEqual(len(json.loads((self.root / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]), 1)
        report = {item["id"]: item["status"] for item in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(report["board"], "enforced")

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_ci_requires_an_exported_decision_for_changes(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, env=GIT_ENV)
        git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "feature")
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        git("add", "app.py")
        git("commit", "-q", "-m", "change")
        result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json", code=1)[0])
        self.assertIn("no exported decision", result["problems"][0])

        self.approve_example()
        exported = self.run_cli("task", "export", TASK)[0].strip()
        record = json.loads((self.root / exported).read_text())
        self.assertNotIn("\"evidence\":", json.dumps(record))
        git("add", exported)
        git("commit", "-q", "-m", "decision")
        result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json")[0])
        self.assertEqual(result["decisions"], [TASK])


if __name__ == "__main__":
    unittest.main()
