"""Managed settings of the hosts, the policy of the workstation and what host check reads of them (issue #453)."""

import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import managed, workstation
from openguildkit.storage import write_json

from tests.support import CapturedCli, openguildkit_on_path, run_cli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
EDIT = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app.py"}})
PROMPT = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "hello"})
DESTINATIONS = {
    ("claude-code", "macos"): "/Library/Application Support/ClaudeCode/managed-settings.d/50-openguildkit.json",
    ("claude-code", "linux"): "/etc/claude-code/managed-settings.d/50-openguildkit.json",
    ("claude-code", "windows"): "C:\\Program Files\\ClaudeCode\\managed-settings.d\\50-openguildkit.json",
    ("codex", "macos"): "/etc/codex/requirements.toml",
    ("codex", "linux"): "/etc/codex/requirements.toml",
    ("codex", "windows"): "%ProgramData%\\OpenAI\\Codex\\requirements.toml",
    ("gemini-cli", "macos"): "/Library/Application Support/GeminiCli/settings.json",
    ("gemini-cli", "linux"): "/etc/gemini-cli/settings.json",
    ("gemini-cli", "windows"): "C:\\ProgramData\\gemini-cli\\settings.json",
}


class Folder(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def policy(self, text: str | None) -> None:
        """The workstation policy file of this test, or none."""
        path = self.root / "etc" / "config.json"
        path.parent.mkdir(exist_ok=True)
        if text is not None:
            path.write_text(text, encoding="utf-8")
        patcher = patch.object(workstation, "LOCATIONS", (path,))
        patcher.start()
        self.addCleanup(patcher.stop)


class GeneratorTests(Folder):
    def managed(self, *arguments, code=0):
        return run_cli(self.root, "host", "managed", *arguments, expect=code)

    def test_claude_code_on_macos_prints_valid_json_and_the_folder_to_deploy_it_in(self):
        result = self.managed("--host", "claude-code", "--os", "macos")
        settings = json.loads(result.stdout)
        events = settings["hooks"]
        self.assertEqual(sorted(events), ["PreToolUse", "UserPromptSubmit"])
        commands = [handler["command"] for groups in events.values() for group in groups for handler in group["hooks"]]
        self.assertEqual(commands, ["openguildkit guard --hook prompt", "openguildkit guard --hook pre-edit"])
        deny = settings["permissions"]["deny"]
        self.assertIn("Bash(openguildkit task decide:*)", deny)
        self.assertIn("Bash(*openguildkit* task decide*)", deny)
        self.assertIn("/Library/Application Support/ClaudeCode/managed-settings.d/", result.stderr)
        self.assertIn("com.anthropic.claudecode", result.stderr)

    def test_each_host_and_system_names_its_destination_and_installs_nothing(self):
        output = self.root / "out"
        for (host, system), destination in DESTINATIONS.items():
            with self.subTest(host=host, system=system):
                result = self.managed("--host", host, "--os", system, "--output", output)
                self.assertIn(destination, result.stdout)
                self.assertIn("Nothing was installed", result.stdout)
        written = sorted(path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file())
        self.assertEqual(written, ["claude-code/50-openguildkit.json", "codex/requirements.toml",
                                   "gemini-cli/settings.json"])
        self.assertEqual([path.name for path in self.root.iterdir()], ["out"])

    def test_the_files_are_valid_for_their_format(self):
        output = self.root / "out"
        for host in ("claude-code", "codex", "gemini-cli"):
            self.managed("--host", host, "--os", "linux", "--output", output)
        claude = json.loads((output / "claude-code" / "50-openguildkit.json").read_text(encoding="utf-8"))
        self.assertIn("hooks", claude)
        requirements = tomllib.loads((output / "codex" / "requirements.toml").read_text(encoding="utf-8"))
        self.assertIs(requirements["features"]["hooks"], True)
        gemini = json.loads((output / "gemini-cli" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(gemini["hooks"]), ["BeforeAgent", "BeforeTool"])
        self.assertIs(gemini["hooksConfig"]["enabled"], True)
        self.assertEqual(gemini["hooks"]["BeforeTool"][0]["matcher"], "write_file|replace")

    def test_the_hooks_run_the_command_that_was_given_and_block_a_hook_that_cannot_start_only_on_request(self):
        plain = json.loads(self.managed("--host", "claude-code", "--os", "linux", "--command",
                                        "/opt/ogk/bin/openguildkit").stdout)
        handlers = [handler for groups in plain["hooks"].values() for group in groups for handler in group["hooks"]]
        self.assertEqual([handler["command"] for handler in handlers],
                         ["/opt/ogk/bin/openguildkit guard --hook prompt", "/opt/ogk/bin/openguildkit guard --hook pre-edit"])
        self.assertTrue(all("onFailure" not in handler for handler in handlers))
        spaced = json.loads(self.managed("--host", "claude-code", "--os", "windows", "--block-on-failure", "--command",
                                         "C:\\Program Files\\OGK\\openguildkit.exe").stdout)
        edit = spaced["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(edit["command"], '"C:\\Program Files\\OGK\\openguildkit.exe" guard --hook pre-edit')
        self.assertEqual(edit["onFailure"], "block")

    def test_a_host_or_a_system_that_is_not_listed_is_refused(self):
        self.managed("--host", "cursor", "--os", "linux", code=2)
        self.managed("--host", "codex", "--os", "plan9", code=2)
        self.assertIn("needs --host", self.managed("--os", "linux", code=1).stderr)

    def test_the_command_needs_no_project_and_says_what_it_did_not_write(self):
        result = self.managed("--host", "claude-code", "--os", "linux", "--output", self.root / "out")
        self.assertIn("à vérifier", result.stdout)
        self.assertIn("disableBypassPermissionsMode", result.stdout)


class NoProfileTests(Folder):
    def hook(self, stdin=EDIT, code=0):
        return run_cli(self.root, "guard", "--hook", "pre-edit", expect=code, stdin=stdin)

    def test_without_a_policy_a_folder_without_a_profile_is_silent_as_before(self):
        self.policy(None)
        result = self.hook()
        self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_refuse_refuses_the_documented_hook_input_in_a_folder_without_a_profile(self):
        """Issue #453: the hook run in a folder without a profile exited 0 without a word."""
        self.policy('{"no_profile": "refuse"}')
        result = self.hook(code=2)
        self.assertIn("Edit refused", result.stderr)
        self.assertIn("no OpenGuildKit profile", result.stderr)
        prompt = run_cli(self.root, "guard", "--hook", "prompt", stdin=PROMPT)
        self.assertIn("no OpenGuildKit profile", json.loads(prompt.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_observe_flags_and_allow_stays_silent(self):
        self.policy('{"no_profile": "observe"}')
        context = json.loads(self.hook().stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("flagged, not blocked", context)
        self.policy('{"no_profile": "allow"}')
        self.assertEqual(self.hook().stdout, "")

    def test_a_project_whose_profile_says_off_is_left_alone_whatever_the_policy_says(self):
        self.policy('{"no_profile": "refuse"}')
        answers = self.root / "answers.json"
        write_json(answers, {**json.loads((EXAMPLE / "profile.json").read_text()), "guard": "off"})
        run_cli(self.root, "init", "--answers", answers)
        self.assertEqual(self.hook().stdout, "")

    def test_a_policy_that_cannot_be_read_refuses_and_names_the_file(self):
        for text in ("{", '{"no_profile": "sometimes"}', '{"no_profil": "refuse"}', "[]"):
            with self.subTest(text=text):
                self.policy(text)
                result = self.hook(code=2)
                self.assertIn("config.json" if "sometimes" not in text else "no_profile is one of", result.stderr)


class CheckTests(Folder, CapturedCli):
    def setUp(self):
        super().setUp()
        openguildkit_on_path(self)
        answers = self.root / "answers.json"
        write_json(answers, {**json.loads((EXAMPLE / "profile.json").read_text()), "guard": "enforce", "host": "claude-code"})
        self.run_cli("init", "--answers", answers)
        self.run_cli("host", "apply")
        self.folder = self.root / "managed"
        self.folder.mkdir()
        patcher = patch.object(managed, "CLAUDE_FOLDER", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def board(self) -> dict:
        controls = json.loads(self.run_cli("host", "check", "--json", code=None)[0])
        return next(control for control in controls if control["id"] == "board")

    def run_cli(self, *arguments, code=0, stdin=None, typed=None):
        result = run_cli(self.root, *arguments, expect=code, stdin=stdin, typed=typed)
        return result.stdout, result.stderr

    def test_a_managed_file_that_lets_only_managed_hooks_run_makes_the_board_missing(self):
        """Issue #453: allowManagedHooksOnly stops the hooks of the project, and host check still said enforced."""
        self.assertEqual(self.board()["status"], "enforced")
        write_json(self.folder / "managed-settings.json", {"allowManagedHooksOnly": True})
        board = self.board()
        self.assertEqual(board["status"], "missing")
        self.assertIn("allowManagedHooksOnly", board["detail"])
        self.assertIn("host managed", board["detail"])

    def test_the_managed_hooks_of_openguildkit_restore_it_and_a_drop_in_file_counts(self):
        write_json(self.folder / "managed-settings.json", {"allowManagedHooksOnly": True})
        drop_in = self.folder / "managed-settings.d"
        drop_in.mkdir()
        hooks = json.loads(run_cli(self.root, "host", "managed", "--host", "claude-code", "--os", "linux").stdout)
        write_json(drop_in / "50-openguildkit.json", hooks)
        self.assertEqual(self.board()["status"], "enforced")

    def test_a_managed_file_without_the_key_changes_nothing(self):
        write_json(self.folder / "managed-settings.json", {"permissions": {"deny": ["WebFetch"]}})
        self.assertEqual(self.board()["status"], "enforced")

    def test_a_managed_file_that_is_not_json_is_ignored(self):
        (self.folder / "managed-settings.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.board()["status"], "enforced")


if __name__ == "__main__":
    unittest.main()
