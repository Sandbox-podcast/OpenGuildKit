import contextlib
import io
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.hosts import CLAUDE_APPROVAL_RULES, host_controls
from openguildkit.storage import write_json


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
        write_json(self.root / "answers.json", {"name": "Portal", "stack": ["Python"], **extra})
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
        self.assertIn('pattern = ["openguildkit", "task", "decide"], decision = "forbidden"', rules)
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
        self.assertIn("does not block public research", consultation)

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


if __name__ == "__main__":
    unittest.main()
