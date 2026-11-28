import fnmatch
import json
import re
import shlex
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.hosts import CLAUDE_APPROVAL_RULES, CLAUDE_PROTECTED_RULES, _codex_rules, host_controls
from openguildkit.storage import write_json
from tests.support import CapturedCli

APPROVAL_FORMS = (
    "openguildkit --project . task decide t --approve --by A --reason B",
    "python3 -m openguildkit --project /work/app task decide t --approve --by A --reason B",
    ".venv/bin/openguildkit task decide t --approve --by A --reason B",
    "openguildkit task waive t security:1 --by A --reason B",
    "openguildkit task authorize t --action publish --target example.test --allow --by A --reason B",
    "python3 -c 'import pty; pty.spawn([\"openguildkit\"])'",
    "script -q /dev/null openguildkit task decide t --approve",
)
AGENT_FORMS = (
    "openguildkit task new brief",
    "openguildkit --project . task consult t --answers a.json",
    "openguildkit task decision-payload t --by A --reason B",
    "openguildkit task authorize t --action publish --target example.test --deny --by A --reason B",
)


def claude_denies(command: str, rules) -> bool:
    """Claude Code Bash rules: a trailing :* is a prefix match, * elsewhere matches anything."""
    for rule in rules:
        if not rule.startswith("Bash("):
            continue
        pattern = rule[5:-1]
        if pattern.endswith(":*"):
            pattern = pattern[:-2] + "*"
        if fnmatch.fnmatchcase(command, pattern):
            return True
    return False


def codex_forbids(command: str, rules_text: str) -> bool:
    """Codex prefix rules: each pattern token is a word or a list of alternatives."""
    words = shlex.split(command)
    for match in re.finditer(r"pattern = (\[.*?\]), decision", rules_text):
        pattern = json.loads(match.group(1))
        if len(words) >= len(pattern) and all(
            word in token if isinstance(token, list) else word == token for word, token in zip(words, pattern)
        ):
            return True
    return False


class HostControlTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # The hooks need openguildkit on the PATH, which a test run from a source checkout may not have: each test
        # that wants it missing says so.
        on_path = patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit")
        on_path.start()
        self.addCleanup(on_path.stop)

    def init(self, **extra):
        # These checks cover the research and approval controls; the guard has its own tests.
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], "guard": "off", **extra})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def test_claude_code_settings_enforce_research_and_approval(self):
        settings = self.root / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(npm test)"], "deny": ["Read(./.env)"]}}), encoding="utf-8")
        self.init(host="claude-code")
        report = {control["id"]: control["status"] for control in host_controls(self.root, {"host": "claude-code"})}
        self.assertEqual(report["research"], "missing")
        _, error = self.run_cli("check", code=1)
        self.assertIn("host apply", error)
        self.run_cli("host", "apply")
        written = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(written["permissions"]["allow"], ["Bash(npm test)"])
        self.assertIn("Read(./.env)", written["permissions"]["deny"])
        self.assertIn("WebSearch", written["permissions"]["deny"])
        for rule in CLAUDE_APPROVAL_RULES:
            self.assertIn(rule, written["permissions"]["deny"])
        self.run_cli("check")
        self.run_cli("host", "apply")
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), written)

    def test_codex_settings_are_written_where_codex_reads_them(self):
        config = self.root / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('model = "gpt-6.1-sol"\n\n[sandbox_workspace_write]\nwritable_roots = []\n', encoding="utf-8")
        self.init(host="codex")
        self.run_cli("host", "apply")
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(parsed["web_search"], "disabled")
        self.assertEqual(parsed["model"], "gpt-6.1-sol")
        rules = (self.root / ".codex" / "rules" / "openguildkit.rules").read_text(encoding="utf-8")
        self.assertIn('pattern = ["openguildkit", "task", ["decide", "waive", "authorize", "revoke"]], '
                      'decision = "forbidden"', rules)
        report, _ = self.run_cli("host", "check", "--json")
        self.assertTrue(all(item["status"] in ("enforced", "partial", "human") for item in json.loads(report)))

    def test_codex_settings_that_open_the_network_are_left_to_the_person(self):
        config = self.root / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('web_search = "live"\n', encoding="utf-8")
        self.init(host="codex")
        _, error = self.run_cli("host", "apply", code=1)
        self.assertIn('web_search = "live"', error)

    def test_an_unknown_host_is_told_which_rules_stay_instructions(self):
        self.init()
        report, _ = self.run_cli("host", "check")
        self.assertIn("[by instruction] Public research stays off", report)
        self.assertIn("[by a person] External actions", report)
        self.assertIn("Nothing missing.", report)
        self.assertNotIn("[missing]", report)
        self.run_cli("task", "new", "Show statuses.", "--id", "status")
        write_json(self.root / "a.json", {"kind": "bug", "surface": ["service"], "data": "none", "research": "local",
                                          "concerns": ["none"]})
        consultation, _ = self.run_cli("task", "consult", "status", "--answers", self.root / "a.json")
        self.assertIn("Public research is off for this project and this host agent has no setting that enforces it",
                      consultation)

    def test_external_actions_need_a_recorded_decision(self):
        self.init()
        self.run_cli("task", "new", "Show statuses.", "--id", "status")
        common = ["task", "authorize", "status", "--action", "external-api", "--by", "Camille", "--reason", "Status page"]
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli(*common, "--target", "api.example.com", "--allow", code=1)
        self.assertIn("interactive terminal", error)
        self.run_cli(*common, "--target", "https://api.example.com/v1?token=1", "--deny", code=1)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="status"):
            self.run_cli(*common, "--target", "api.example.com", "--allow")
        self.run_cli(*common, "--target", "tracker.example.com", "--deny")
        record = json.loads(self.run_cli("task", "show", "status")[0])
        self.assertEqual([item["decision"] for item in record["authorizations"]], ["allow", "deny"])
        self.assertEqual(record["authorizations"][0]["target"], "api.example.com")

    def test_deny_rules_cover_every_documented_approval_form(self):
        for command in APPROVAL_FORMS:
            self.assertTrue(claude_denies(command, CLAUDE_APPROVAL_RULES), command)
        for command in AGENT_FORMS:
            self.assertFalse(claude_denies(command, CLAUDE_APPROVAL_RULES), command)
        for command in (
            "openguildkit --project . task decide t --approve",
            "python3 -m openguildkit --project ./ task waive t security:1",
            "py -m openguildkit task authorize t --allow",
            "openguildkit task decide t --approve",
            "unbuffer openguildkit task decide t",
        ):
            self.assertTrue(codex_forbids(command, _codex_rules()), command)
        self.assertFalse(codex_forbids("openguildkit --project . task new brief", _codex_rules()))

    def test_with_the_guard_on_the_agent_cannot_edit_the_files_it_relies_on(self):
        self.init(host="claude-code", guard="enforce")
        self.run_cli("host", "apply")
        deny = json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
        for rule in CLAUDE_PROTECTED_RULES:
            self.assertIn(rule, deny)
        self.assertIn("Edit(/.openguildkit/tasks/**)", deny)
        self.assertIn("Edit(/.openguildkit/project.json)", deny)
        self.assertIn("Edit(/.openguildkit/alerts.json)", deny)
        self.assertIn("Edit(/.openguildkit/catalog/**)", deny)
        self.assertFalse([rule for rule in deny if rule.startswith("Edit(./")])

    def test_a_signed_project_keeps_the_file_tools_away_from_its_signers_file(self):
        (self.root / "keys").mkdir()
        (self.root / "keys" / "allowed_signers").write_text("camille@example.org ssh-ed25519 AAAA\n", encoding="utf-8")
        self.init(host="claude-code", approval={"mode": "signed", "allowed_signers": "keys/allowed_signers",
                                                "approvers": ["camille@example.org"]})
        report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json", code=1)[0])}
        self.assertEqual(report["approval"]["status"], "missing")
        self.run_cli("host", "apply")
        settings = self.root / ".claude" / "settings.json"
        written = json.loads(settings.read_text(encoding="utf-8"))
        self.assertIn("Edit(/keys/allowed_signers)", written["permissions"]["deny"])
        report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(report["approval"]["status"], "partial")
        self.assertIn("allowed signers file", report["approval"]["detail"])
        written["permissions"]["deny"].remove("Edit(/keys/allowed_signers)")
        settings.write_text(json.dumps(written), encoding="utf-8")
        report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json", code=1)[0])}
        self.assertIn("missing: Edit(/keys/allowed_signers)", report["approval"]["detail"])

    def test_host_apply_says_the_approval_rule_is_partial(self):
        for host in ("claude-code", "codex"):
            with self.subTest(host=host):
                (self.root / ".openguildkit" / "project.json").unlink(missing_ok=True)
                self.init(host=host)
                output, _ = self.run_cli("host", "apply")
                self.assertIn("[partial] The agent cannot run the approval command", output)
                self.assertNotIn("[enforced] The agent cannot run the approval command", output)
                self.assertIn("Partial: a script file", output)

    def test_in_enforce_a_user_setting_cannot_turn_the_hooks_off(self):
        self.init(host="claude-code", guard="enforce")
        self.run_cli("host", "apply")
        settings = self.root / ".claude" / "settings.json"
        written = json.loads(settings.read_text(encoding="utf-8"))
        self.assertIs(written["disableAllHooks"], False)
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            self.assertEqual({item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
                             ["board"]["status"], "enforced")
            for value in (None, True):
                if value is None:
                    written.pop("disableAllHooks")
                else:
                    written["disableAllHooks"] = value
                settings.write_text(json.dumps(written), encoding="utf-8")
                report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json", code=1)[0])}
                self.assertEqual(report["board"]["status"], "missing")
                self.assertIn('"disableAllHooks": false', report["board"]["detail"])
            self.run_cli("host", "apply")
        self.assertIs(json.loads(settings.read_text(encoding="utf-8"))["disableAllHooks"], False)

    def test_in_observe_the_hooks_switch_is_left_to_the_team(self):
        self.init(host="claude-code", guard="observe")
        self.run_cli("host", "apply")
        self.assertNotIn("disableAllHooks", json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8")))

    def test_edit_rules_relative_to_the_current_directory_are_replaced(self):
        settings = self.root / ".claude" / "settings.json"
        settings.parent.mkdir()
        old_rules = [f"Edit(./{rule[6:]}" for rule in CLAUDE_PROTECTED_RULES]
        settings.write_text(json.dumps({"permissions": {"deny": ["Read(./.env)", *old_rules]}}), encoding="utf-8")
        self.init(host="claude-code", guard="enforce")
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json", code=1)[0])}
            self.assertEqual(report["board"]["status"], "missing")
            self.run_cli("host", "apply")
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(report["board"]["status"], "enforced")
        deny = json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]
        self.assertEqual([rule for rule in deny if rule.startswith("Edit(")], list(CLAUDE_PROTECTED_RULES))
        self.assertIn("Read(./.env)", deny)

    def edit_hook(self):
        hooks = json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
        return hooks["PreToolUse"][0]["hooks"][0]

    def test_in_enforce_a_guard_hook_that_cannot_start_blocks_the_edit(self):
        self.init(host="claude-code", guard="enforce")
        self.run_cli("host", "apply")
        self.assertEqual(self.edit_hook()["onFailure"], "block")
        settings = self.root / ".claude" / "settings.json"
        written = json.loads(settings.read_text(encoding="utf-8"))
        del written["hooks"]["PreToolUse"][0]["hooks"][0]["onFailure"]
        settings.write_text(json.dumps(written), encoding="utf-8")
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json", code=1)[0])}
        self.assertEqual(report["board"]["status"], "missing")
        self.run_cli("host", "apply")
        self.assertEqual(self.edit_hook()["onFailure"], "block")
        self.assertEqual(len(json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]), 1)

    def test_in_observe_a_failing_guard_hook_does_not_block(self):
        self.init(host="claude-code", guard="observe")
        self.run_cli("host", "apply")
        self.assertNotIn("onFailure", self.edit_hook())
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(report["board"]["status"], "enforced")

    def test_the_guard_is_not_enforced_where_its_command_is_not_on_the_path(self):
        self.init(host="claude-code", guard="enforce")
        self.run_cli("host", "apply")
        with patch("openguildkit.hosts.shutil.which", return_value=None):
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json", code=1)[0])}
            checked, _ = self.run_cli("host", "check", code=1)
            # host apply writes what it can, then fails while the cause remains, and does not send back to itself.
            applied, _ = self.run_cli("host", "apply", code=1)
            _, error = self.run_cli("check", code=1)
        self.assertEqual((report["board"]["status"], report["board"]["cause"]), ("missing", "path"))
        self.assertIn("not on this workstation's PATH", report["board"]["detail"])
        for output in (checked, applied, error):
            with self.subTest(output=output[-120:]):
                self.assertIn("not on this workstation's PATH", output)
                self.assertIn("pipx install or uv tool install", output)
                self.assertNotIn("Run openguildkit host apply", output)
                self.assertNotIn("then openguildkit host apply", output)
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(report["board"]["status"], "enforced")
        self.assertIn("Shell commands", report["board"]["detail"])

    def test_host_apply_fails_while_a_setting_stays_missing(self):
        self.init(host="claude-code", guard="enforce")
        # A setting the write did not install, as when the settings file cannot be written.
        with patch("openguildkit.check_cli.apply_host_settings", return_value=[]):
            output, _ = self.run_cli("host", "apply", code=1)
        self.assertIn("settings missing. Run openguildkit host apply", output)
        self.run_cli("host", "apply")

    def test_enforce_without_signed_approvals_is_flagged(self):
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], "host": "claude-code", "guard": "enforce"})
        _, error = self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertIn("approvals are not signed", error)
        self.assertIn("signed", error)
        _, error = self.run_cli("host", "apply")
        self.assertNotIn("approvals are not signed", error)
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            _, check_error = self.run_cli("host", "check")
            _, error = self.run_cli("check")
        self.assertEqual(check_error.count("approvals are not signed"), 1)
        self.assertIn("approvals are not signed", error)

    def test_signed_approvals_raise_no_warning(self):
        (self.root / "allowed_signers").write_text("camille@example.org ssh-ed25519 AAAA\n", encoding="utf-8")
        self.init(guard="enforce", approval={"mode": "signed", "allowed_signers": "allowed_signers",
                                             "approvers": ["camille@example.org"]})
        self.assertNotIn("not signed", self.run_cli("host", "check")[1])


class RestrictedPathTests(CapturedCli, unittest.TestCase):
    """Issue #519: a team could not say that a folder is closed to the agent, and host apply wrote no Read rule."""

    RESTRICTED = [{"paths": ["data/customers/**", "secrets/**"], "class": "restricted", "boards": ["security", "legal"]}]
    RULES = ["Read(/data/customers/**)", "Edit(/data/customers/**)", "Read(/secrets/**)", "Edit(/secrets/**)"]

    def setUp(self):
        on_path = patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit")
        on_path.start()
        self.addCleanup(on_path.stop)
        self.fresh()

    def fresh(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / ".openguildkit" / "project.json"

    def init(self, host: str, restricted=RESTRICTED, **extra):
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], "guard": "off",
                                                "host": host, **extra})
        self.run_cli("init", "--answers", self.root / "answers.json")
        self.restrict(restricted)

    def restrict(self, restricted) -> None:
        """The person writes the setting by hand in project.json (profile set restricted-paths writes paths only)."""
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        if restricted is None:
            profile.pop("restricted_paths", None)
        else:
            profile["restricted_paths"] = restricted
        self.profile.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

    def control(self, code=None) -> dict | None:
        controls = json.loads(self.run_cli("host", "check", "--json", code=code)[0])
        return next((item for item in controls if item["id"] == "restricted-paths"), None)

    def test_host_apply_writes_the_read_and_edit_rules_of_each_path_and_keeps_the_rules_of_the_team(self):
        settings = self.root / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"permissions": {"deny": ["Read(./.env)", "Bash(rm:*)"]}}), encoding="utf-8")
        self.init("claude-code")
        self.assertEqual(self.control(code=1)["status"], "missing")
        self.run_cli("host", "apply")
        deny = json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]
        for rule in (*self.RULES, "Read(./.env)", "Bash(rm:*)"):
            self.assertIn(rule, deny)
        self.assertEqual(self.control(code=0)["status"], "enforced")
        self.run_cli("host", "apply")
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"], deny)

    def test_what_each_host_cannot_do_is_said_and_is_not_a_missing_setting(self):
        for host in ("codex", "gemini-cli", "other"):
            with self.subTest(host=host):
                self.fresh()
                self.init(host)
                control = self.control(code=0 if host == "other" else None)
                self.assertEqual(control["status"], "instruction")
                self.assertIn("no setting of this host that refuses a read was read", control["detail"])
                self.assertIn("à vérifier", control["detail"])
                self.assertIn("data/customers/**", control["detail"])

    def test_claude_code_says_that_its_rules_do_not_reach_a_shell_command(self):
        self.init("claude-code")
        self.assertIn("shell command", self.control(code=1)["detail"])

    def test_a_project_without_the_setting_has_the_controls_it_had(self):
        self.init("claude-code", restricted=None)
        self.assertIsNone(self.control(code=1))

    def test_a_setting_that_is_not_a_list_of_paths_is_refused_with_the_file_named(self):
        # OGK-PROJECT-016
        self.init("claude-code")
        for bad in ("secrets/**", [{"paths": "secrets/**"}], [{"paths": []}], [{"paths": ["/etc/passwd"]}],
                    [{"paths": ["../outside/**"]}], [{"paths": ["a/**"], "boards": "legal"}], [{"class": "restricted"}]):
            with self.subTest(bad=bad):
                self.restrict(bad)
                _, error = self.run_cli("host", "check", code=1)
                self.assertIn("restricted_paths", error)
                self.assertIn("project.json", error)
                self.assertEqual(len(error.strip().splitlines()), 1)

    def deny(self) -> list[str]:
        return json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]

    def test_issue_519_profile_set_restricted_paths_closes_them_and_host_apply_writes_then_removes_their_rules(self):
        """Issue #519: no profile command set the paths, and host apply never removed a Read rule it had written."""
        settings = self.root / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"permissions": {"deny": ["Read(./.env)"]}}), encoding="utf-8")
        self.init("claude-code", restricted=None)
        output, _ = self.run_cli("profile", "set", "restricted-paths", "data/customers/**", "secrets/**", "--by", "DP",
                                 "--reason", "Customer exports")
        self.assertIn("Run openguildkit host apply", output)
        profile = json.loads(self.profile.read_text(encoding="utf-8"))
        self.assertEqual(profile["restricted_paths"], [{"paths": ["data/customers/**", "secrets/**"]}])
        self.run_cli("host", "apply")
        self.assertEqual([rule for rule in self.deny() if rule in self.RULES or rule == "Read(./.env)"],
                         ["Read(./.env)", *self.RULES])
        self.run_cli("profile", "set", "restricted-paths", "data/customers/**", "--by", "DP", "--reason", "Secrets moved",
                     typed="data/customers/**")
        self.run_cli("host", "apply")
        self.assertIn("Read(/data/customers/**)", self.deny())
        self.assertNotIn("Read(/secrets/**)", self.deny())
        self.assertNotIn("Edit(/secrets/**)", self.deny())
        self.assertIn("Read(./.env)", self.deny())

    def test_issue_519_lifting_a_restricted_path_is_refused_without_a_terminal(self):
        """Issue #519: removing a restricted path is a lowered protection, the person's decision at a terminal."""
        self.init("claude-code", restricted=None)
        self.run_cli("profile", "set", "restricted-paths", "secrets/**", "--by", "DP", "--reason", "Secrets")
        _, error = self.run_cli("profile", "set", "restricted-paths", "none", "--by", "DP", "--reason", "x", code=1)
        self.assertIn("1 restricted path lifted (secrets/**)", error)
        self.assertIn("interactive terminal", error)
        self.assertIn("restricted_paths", self.profile.read_text(encoding="utf-8"))
        self.run_cli("profile", "set", "restricted-paths", "none", "--by", "DP", "--reason", "x", typed="none")
        self.assertNotIn("restricted_paths", self.profile.read_text(encoding="utf-8"))

    def test_issue_519_the_hook_refuses_an_edit_of_a_restricted_path_even_under_an_approved_task(self):
        """Issue #519: the hook knew approved tasks, not the sensitivity of a path."""
        from tests.test_guard import EXAMPLE, TASK

        self.init("claude-code", guard="enforce", restricted=None)
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", typed=TASK)
        self.run_cli("profile", "set", "restricted-paths", "data/customers/**", "--by", "DP", "--reason", "Exports")

        def edit(path):
            return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                               "tool_input": {"file_path": str(self.root / path), "new_string": "x"}})

        self.run_cli("guard", "--hook", "pre-edit", stdin=edit("app.py"))
        _, error = self.run_cli("guard", "--hook", "pre-edit", stdin=edit("Data/Customers/export.csv"), code=2)
        self.assertIn("Data/Customers/export.csv is a restricted path of the project", error)
        self.assertIn("even under an approved task", error)

    def test_the_setting_leaves_standing_approvals_standing(self):
        """The paths are read when the host acts, like the guard and the host: they are not rules of a task."""
        from tests.test_guard import EXAMPLE, TASK

        self.init("claude-code", guard="enforce", restricted=None)
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        self.assertEqual(len(json.loads(self.run_cli("guard", "--json")[0])["covered_by"]), 1)
        self.restrict(self.RESTRICTED)
        self.assertEqual(len(json.loads(self.run_cli("guard", "--json")[0])["covered_by"]), 1)


if __name__ == "__main__":
    unittest.main()
