"""Stable error codes of the tool connections and the host settings (#487): the refusals no other test meets, each
provoked by calling the function that builds it with a file or an option a person could write, or by the command."""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit import hosts, tool_connections, tools, tools_cli
from openguildkit.errors import OgkError
from tests.support import run_cli


class CodedCase(unittest.TestCase):
    def assertCodes(self, cases):
        for code, call in cases:
            with self.subTest(code=code), self.assertRaises(OgkError) as raised:
                call()
            self.assertEqual(raised.exception.code, code, raised.exception)

    def folder(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class ToolsCodeTests(CodedCase):
    """Issue #487: a mock, a scenario, a server, a host or a connection file refused without a code."""

    def test_issue_487_a_refused_mock_scenario_or_server_has_its_code(self):
        """Issue #487: read_scenario, load_mock, choose_server, _plan_options, _live_connection and _pairs."""
        broken, wrong = self.folder(), self.folder()
        self.write(broken / tools.SCENARIO, "{not json")
        self.write(wrong / tools.SCENARIO, "[]")
        stdio = {"id": "local", "transport": "stdio", "settings": []}
        self.assertCodes([
            ("OGK-TOOLS-021", lambda: tools.read_scenario(broken)),
            ("OGK-TOOLS-022", lambda: tools.read_scenario(wrong)),
            ("OGK-TOOLS-023", lambda: tools.load_mock("Not An ID")),
            ("OGK-TOOLS-024", lambda: tools.load_mock("no-such-tool")),
            ("OGK-TOOLS-025", lambda: tools.choose_server({"id": "jira", "servers": []}, "nope")),
            ("OGK-TOOLS-026", lambda: tools._plan_options("no-host", False, None, None, False)),
            ("OGK-TOOLS-027", lambda: tools._live_connection("jira", {}, stdio, "codex", {}, "JIRA_TOKEN", False, {})),
            ("OGK-TOOLS-028", lambda: tools_cli._pairs(["no-equals"], ".", "TOOL.NAME=VALUE")),
            ("OGK-TOOLS-029", lambda: tools_cli._pairs(["jira=value"], ".", "TOOL.NAME=VALUE")),
        ])

    def test_issue_487_a_damaged_connection_file_has_its_code(self):
        """Issue #487: read_manifest, _split_codex, _mcp_file, _write_host and remove_connections."""
        root = self.folder()
        state = root / ".openguildkit"
        listed, unconnected, empty = self.folder(), self.folder(), self.folder()
        self.write(listed / tool_connections.MANIFEST, json.dumps({"connections": {}}))
        self.write(unconnected / tool_connections.MANIFEST,
                   json.dumps({"connections": [], tool_connections.UNCONNECTED: [1]}))
        mcp = self.write(root / ".mcp.json", "[]")
        self.write(root / tool_connections.CODEX_CONFIG_FILE, "not = [toml\n")
        self.assertCodes([
            ("OGK-TOOLS-032", lambda: tool_connections.read_manifest(listed)),
            ("OGK-TOOLS-033", lambda: tool_connections.read_manifest(unconnected)),
            ("OGK-TOOLS-034", lambda: tool_connections._split_codex(tool_connections.CODEX_BLOCK_START, mcp)),
            ("OGK-TOOLS-035", lambda: tool_connections._mcp_file(mcp)),
            ("OGK-TOOLS-036", lambda: tool_connections._write_host(root, "codex", [], set())),
            ("OGK-TOOLS-037", lambda: tool_connections.remove_connections(root, empty, "claude-code", ["jira"])),
        ])
        self.assertFalse(state.exists())

    def test_issue_487_tools_call_and_tools_list_print_their_codes(self):
        """Issue #487: an unknown tool of a mock and an unknown brain, through the command."""
        root = self.folder()
        self.write(root / "profile.json", json.dumps({"personal_data": "no", "name": "Portal", "stack": ["Python"],
                                                      "packs": [], "checks": []}))
        run_cli(root, "init", "--answers", root / "profile.json")
        for code, arguments in (("OGK-TOOLS-030", ("tools", "call", "datadog", "no-such-tool")),
                                ("OGK-TOOLS-031", ("tools", "list", "--brain", "no-such-brain"))):
            with self.subTest(code=code):
                error = run_cli(root, *arguments, expect=1).stderr
                self.assertTrue(error.splitlines()[-1].startswith(f"OpenGuildKit [{code}]: "), error)


class HostCodeTests(CodedCase):
    """Issue #487: a host settings file OpenGuildKit cannot read or change safely, refused without a code."""

    def test_issue_487_a_host_file_refused_has_its_code(self):
        """Issue #487: _codex_config, _codex_lift_web_search, _apply_claude and _apply_codex."""
        broken, codex = self.folder(), self.folder()
        self.write(broken / hosts.CODEX_CONFIG_FILE, "not = [toml\n")
        self.write(codex / hosts.CODEX_CONFIG_FILE, "[sandbox_workspace_write]\nnetwork_access = true\n")
        permissions, deny = self.folder(), self.folder()
        self.write(permissions / hosts.CLAUDE_SETTINGS_FILE, json.dumps({"permissions": []}))
        self.write(deny / hosts.CLAUDE_SETTINGS_FILE, json.dumps({"permissions": {"deny": "Bash"}}))
        line = hosts.CODEX_WEB_SEARCH_LINE + "\n"
        self.assertCodes([
            ("OGK-HOST-011", lambda: hosts._codex_config(broken)),
            ("OGK-HOST-012", lambda: hosts._codex_lift_web_search(broken, line, {"model": "kept"})),
            ("OGK-HOST-013", lambda: hosts._apply_claude(permissions, {}, False, "claude-code")),
            ("OGK-HOST-014", lambda: hosts._apply_claude(deny, {}, False, "claude-code")),
            ("OGK-HOST-015", lambda: hosts._apply_codex(codex, {}, True, "codex")),
        ])


if __name__ == "__main__":
    unittest.main()
