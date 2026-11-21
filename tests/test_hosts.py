import contextlib
import fnmatch
import io
import json
import re
import shlex
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.hosts import CLAUDE_APPROVAL_RULES, CLAUDE_PROTECTED_RULES, _codex_rules, host_controls
from openguildkit.storage import write_json


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


class HostControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def init(self, **extra):
        # These checks cover the research and approval controls; the guard has its own tests.
        write_json(self.root / "answers.json", {"name": "Portal", "stack": ["Python"], "guard": "off", **extra})
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
        self.assertIn('pattern = ["openguildkit", "task", ["decide", "waive", "authorize"]], decision = "forbidden"', rules)
        report, _ = self.run_cli("host", "check", "--json")
        self.assertTrue(all(item["status"] in ("enforced", "human") for item in json.loads(report)))

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
        self.assertIn("[instruction] Public research stays off", report)
        self.run_cli("task", "new", "Show statuses.", "--id", "status")
        write_json(self.root / "a.json", {"kind": "bug", "surface": ["service"], "data": "none", "research": "local"})
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
        self.assertFalse([rule for rule in deny if rule.startswith("Edit(./")])

    def test_edit_rules_relative_to_the_current_directory_are_replaced(self):
        settings = self.root / ".claude" / "settings.json"
        settings.parent.mkdir()
        old_rules = [f"Edit(./{rule[6:]}" for rule in CLAUDE_PROTECTED_RULES]
        settings.write_text(json.dumps({"permissions": {"deny": ["Read(./.env)", *old_rules]}}), encoding="utf-8")
        self.init(host="claude-code", guard="enforce")
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
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
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
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
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
            _, error = self.run_cli("check", code=1)
        self.assertEqual(report["board"]["status"], "missing")
        self.assertIn("not on this workstation's PATH", report["board"]["detail"])
        self.assertIn("host check", error)
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            report = {item["id"]: item for item in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(report["board"]["status"], "enforced")
        self.assertIn("Shell commands", report["board"]["detail"])

    def test_enforce_without_signed_approvals_is_flagged(self):
        write_json(self.root / "answers.json", {"name": "Portal", "stack": ["Python"], "host": "claude-code", "guard": "enforce"})
        _, error = self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertIn("approvals are not signed", error)
        self.assertIn("signed", error)
        _, error = self.run_cli("host", "apply")
        self.assertEqual(error.count("approvals are not signed"), 1)
        with patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit"):
            _, error = self.run_cli("check")
        self.assertIn("approvals are not signed", error)

    def test_signed_approvals_raise_no_warning(self):
        (self.root / "allowed_signers").write_text("camille@example.org ssh-ed25519 AAAA\n", encoding="utf-8")
        self.init(guard="enforce", approval={"mode": "signed", "allowed_signers": "allowed_signers",
                                             "approvers": ["camille@example.org"]})
        self.assertNotIn("not signed", self.run_cli("host", "check")[1])


if __name__ == "__main__":
    unittest.main()
