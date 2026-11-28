"""Managed settings of the hosts, the policy of the workstation and what host check reads of them (issue #453)."""

import json
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

    def test_the_command_needs_no_project_and_names_the_pages_it_rests_on(self):
        result = self.managed("--host", "claude-code", "--os", "linux", "--output", self.root / "out")
        self.assertIn("Read on 2026-11-28: https://code.claude.com/docs/en/settings-reference.md", result.stdout)

    def test_issue_453_the_claude_code_file_disables_bypass_mode(self):
        """Issue #453: the managed file left bypassPermissions mode open, which skips every permission rule."""
        settings = json.loads(self.managed("--host", "claude-code", "--os", "macos").stdout)
        self.assertEqual(settings["permissions"]["disableBypassPermissionsMode"], "disable")
        self.assertNotIn("availableModels", settings)
        self.assertNotIn("allowedMcpServers", settings)

    def test_issue_453_the_codex_file_holds_the_guard_hooks_as_managed_hooks(self):
        """Issue #453: the Codex file only pinned [features] hooks, so a workstation had no guard hook to keep on."""
        text = self.managed("--host", "codex", "--os", "linux", "--command", "/opt/ogk/bin/openguildkit").stdout
        requirements = tomllib.loads(text)
        self.assertIs(requirements["features"]["hooks"], True)
        self.assertNotIn("allow_managed_hooks_only", requirements)
        hooks = requirements["hooks"]
        self.assertEqual(hooks["UserPromptSubmit"][0]["hooks"][0],
                         {"type": "command", "command": "/opt/ogk/bin/openguildkit guard --hook prompt"})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "apply_patch|Edit|Write")
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"], "/opt/ogk/bin/openguildkit guard --hook pre-edit")

    def test_issue_480_the_allow_list_becomes_the_model_and_server_locks_of_claude_code_where_it_maps(self):
        """Issue #480: host managed did not write the allow list into the managed settings of the hosts."""
        addresses = self.root / "addresses.json"
        write_json(addresses, {"allow": {"mcp_servers": ["https://mcp.example.com/mcp"], "models": ["sonnet", "haiku"]}})
        result = self.managed("--host", "claude-code", "--os", "linux", "--allow", addresses)
        settings = json.loads(result.stdout)
        self.assertEqual(settings["availableModels"], ["sonnet", "haiku"])
        self.assertEqual(settings["allowedMcpServers"], [{"serverUrl": "https://mcp.example.com/mcp"}])
        packages = self.root / "packages.json"
        write_json(packages, {"mcp_servers": ["npm:@playwright/mcp", "https://mcp.example.com/mcp"], "models": [],
                              "endpoints": ["https://gateway.example"]})
        result = self.managed("--host", "claude-code", "--os", "linux", "--allow", packages)
        settings = json.loads(result.stdout)
        self.assertEqual(settings["availableModels"], [])
        self.assertNotIn("allowedMcpServers", settings)
        self.assertIn("allowedMcpServers is not written", result.stderr)
        self.assertIn("provider addresses of the list are not written", result.stderr)
        codex = self.managed("--host", "codex", "--os", "linux", "--allow", packages)
        self.assertNotIn("mcp_servers", tomllib.loads(codex.stdout))
        self.assertIn("The allow list is not written for codex", codex.stderr)
        self.assertIn("is an option of openguildkit host scan",
                      run_cli(self.root, "host", "check", "--allow", packages, expect=1).stderr)

    def test_issue_480_a_named_server_becomes_the_same_lock_in_codex_and_gemini_cli(self):
        """Issue #480: Codex and Gemini CLI name each allowed MCP server, and the allow list held no name."""
        named = self.root / "named.json"
        write_json(named, {"mcp_servers": [{"server": "https://mcp.example.com/mcp", "name": "docs"},
                                           {"server": "command:basecamp", "name": "basecamp"}]})
        codex = tomllib.loads(self.managed("--host", "codex", "--os", "linux", "--allow", named).stdout)
        self.assertEqual(codex["mcp_servers"], {"docs": {"identity": {"url": "https://mcp.example.com/mcp"}},
                                                "basecamp": {"identity": {"command": "basecamp"}}})
        gemini = self.managed("--host", "gemini-cli", "--os", "linux", "--allow", named)
        self.assertEqual(json.loads(gemini.stdout)["mcp"], {"allowed": ["docs", "basecamp"]})
        self.assertIn("mcp.allowed matches a server by its name only", gemini.stderr)
        addresses = self.root / "addresses.json"
        write_json(addresses, {"mcp_servers": [{"server": "https://mcp.example.com/mcp", "name": "docs"}]})
        claude = json.loads(self.managed("--host", "claude-code", "--os", "linux", "--allow", addresses).stdout)
        self.assertEqual(claude["allowedMcpServers"], [{"serverUrl": "https://mcp.example.com/mcp"}])
        package = self.root / "package.json"
        write_json(package, {"mcp_servers": [{"server": "npm:@playwright/mcp", "name": "playwright"}, "command:basecamp"]})
        codex = self.managed("--host", "codex", "--os", "linux", "--allow", package)
        self.assertNotIn("mcp_servers", tomllib.loads(codex.stdout))
        self.assertIn("The allow list is not written for codex", codex.stderr)
        gemini = self.managed("--host", "gemini-cli", "--os", "linux", "--allow", package)
        self.assertNotIn("mcp", json.loads(gemini.stdout))
        self.assertIn("The allow list is not written for gemini-cli", gemini.stderr)
        for entry in ({"server": "command:x", "name": "a b"}, {"server": "command:x"}, {"name": "x"}):
            write_json(package, {"mcp_servers": [entry]})
            self.assertIn("allow list", run_cli(self.root, "host", "managed", "--host", "codex", "--os", "linux",
                                                "--allow", package, expect=1).stderr)


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
