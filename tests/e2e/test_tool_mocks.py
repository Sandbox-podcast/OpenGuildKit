"""A project connects its tools to mocks, an MCP client talks to them, and a board cites what it read."""

import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from openguildkit.mcp_mock import serve
from openguildkit.tools import load_mock
from tests.support import run_cli, subprocess_environment

REPO = Path(__file__).resolve().parents[2]
ENV = subprocess_environment({"PYTHONPATH": str(REPO / "src"), "PYTHONIOENCODING": "utf-8"})
META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
PROFILE = {"personal_data": "no", 
    "name": "Support portal", "sector": "general", "stack": ["Python"], "packs": [], "boards": ["product", "qa", "security"],
    "research": "local-only", "host": "codex", "tools": ["Jira Cloud", "Snyk", "Gryzzly", "Our intranet"],
}


def cli(project: Path, *args, check: bool = True, stdin: str | None = None) -> subprocess.CompletedProcess:
    """The CLI in this process; check=False returns a failed command instead of raising."""
    return run_cli(project, *args, stdin=stdin, expect=0 if check else None)


def exchange_in_process(tool_id: str, messages: list) -> list[dict]:
    """The same exchange with a bundled mock served in this process, for many calls without a process each."""
    payload = "".join(json.dumps(item) + "\n" for item in messages).encode("utf-8")
    answers = io.BytesIO()
    serve(load_mock(tool_id), stdin=io.BytesIO(payload), stdout=answers)
    return [json.loads(line) for line in answers.getvalue().decode("utf-8").splitlines()]


def exchange(command: list[str], messages: list) -> list[dict]:
    """Send JSON-RPC messages to an MCP server on stdio and return its answers, in order."""
    payload = "".join((item if isinstance(item, str) else json.dumps(item)) + "\n" for item in messages)
    result = subprocess.run(command, env=ENV, input=payload.encode("utf-8"), capture_output=True, timeout=60)
    if result.returncode:
        raise AssertionError(result.stderr.decode("utf-8", "replace"))
    lines = result.stdout.decode("utf-8").splitlines()
    return [json.loads(line) for line in lines]


class MockServerTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.project = Path(self._directory.name)
        self.mock = [sys.executable, "-m", "openguildkit", "--project", str(self.project), "tools", "mock"]

    def test_a_client_of_the_handshake_revisions_lists_and_calls_tools(self):
        log = self.project / "calls.jsonl"
        answers = exchange(self.mock + ["jira", "--log", str(log)], [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_issues", "arguments": {"query": "CSV export"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_issue", "arguments": {"key": "NOPE-1"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "search_issues", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "drop_database", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 8, "method": "ping"},
            "this is not JSON",
            {"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
        ])
        self.assertEqual([item.get("id") for item in answers], [1, 2, 3, 4, 5, 6, 7, 8, None, 9])
        self.assertEqual(answers[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(answers[0]["result"]["serverInfo"]["name"], "openguildkit-mock-jira")
        names = [tool["name"] for tool in answers[1]["result"]["tools"]]
        self.assertIn("search_issues", names)
        self.assertNotIn("resultType", answers[1]["result"])
        found = answers[2]["result"]
        self.assertFalse(found["isError"])
        self.assertEqual(found["structuredContent"]["issues"][0]["key"], "SUP-142")
        self.assertEqual(json.loads(found["content"][0]["text"]), found["structuredContent"])
        self.assertTrue(answers[3]["result"]["isError"])
        self.assertTrue(answers[4]["result"]["isError"])
        self.assertIn("Missing argument", answers[4]["result"]["content"][0]["text"])
        self.assertEqual(answers[5]["error"]["code"], -32602)
        self.assertEqual(answers[6]["error"]["code"], -32601)
        self.assertEqual(answers[7]["result"], {})
        self.assertEqual(answers[8]["error"]["code"], -32700)
        self.assertEqual(answers[9]["result"]["protocolVersion"], "2025-11-25")
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([item["call"] for item in calls], ["search_issues", "get_issue", "search_issues", "drop_database"])
        self.assertEqual(calls[0]["arguments"], {"query": "CSV export"})

    def test_a_client_of_the_stateless_revision_needs_no_handshake(self):
        answers = exchange(self.mock + ["tempo"], [
            {"jsonrpc": "2.0", "id": "discover-1", "method": "server/discover", "params": {"_meta": META}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": META}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "log_work", "_meta": META,
                "arguments": {"issue_key": "SUP-142", "hours": 1.5, "date": "2026-11-21", "description": "Review"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list",
             "params": {"_meta": {**META, "io.modelcontextprotocol/protocolVersion": "1900-01-01"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list",
             "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "ping", "params": {"_meta": META}},
        ])
        discover = answers[0]["result"]
        self.assertEqual(discover["resultType"], "complete")
        self.assertEqual(discover["supportedVersions"], ["2026-07-28"])
        self.assertEqual(discover["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "openguildkit-mock-tempo")
        listing = answers[1]["result"]
        self.assertEqual((listing["resultType"], listing["cacheScope"]), ("complete", "public"))
        self.assertGreater(listing["ttlMs"], 0)
        logged = answers[2]["result"]
        self.assertEqual((logged["resultType"], logged["isError"]), ("complete", False))
        self.assertEqual(logged["structuredContent"]["hours"], 1.5)
        self.assertEqual(logged["structuredContent"]["issue_key"], "SUP-142")
        self.assertEqual(answers[3]["error"]["code"], -32022)
        self.assertEqual(answers[3]["error"]["data"]["requested"], "1900-01-01")
        self.assertIn("2026-07-28", answers[3]["error"]["data"]["supported"])
        self.assertEqual(answers[4]["error"]["code"], -32602)
        self.assertEqual(answers[5]["error"]["code"], -32601)

    def test_every_bundled_mock_answers_each_of_its_tools(self):
        listed = cli(self.project, "tools", "list", "--mocks", "--json").stdout
        for tool in json.loads(listed):
            answers = exchange_in_process(tool["id"], [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
            tools = answers[0]["result"]["tools"]
            self.assertGreaterEqual(len(tools), 3, tool["id"])
            calls = []
            for index, item in enumerate(tools, start=2):
                schema = item["inputSchema"]
                arguments = {
                    name: {"string": "export", "integer": 1, "number": 1.5, "boolean": True, "array": [], "object": {}}[
                        schema["properties"][name].get("type", "string")]
                    if "enum" not in schema["properties"][name] else schema["properties"][name]["enum"][0]
                    for name in schema.get("required", [])
                }
                calls.append({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                              "params": {"name": item["name"], "arguments": arguments}})
            for answer in exchange_in_process(tool["id"], calls):
                self.assertIn("result", answer, tool["id"])
                self.assertEqual(answer["result"]["content"][0]["type"], "text")


class DemoTests(unittest.TestCase):
    def test_the_bundled_demo_plays_an_agent_against_the_mocks(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(REPO / "examples" / "tool-mocks" / "demo.py"), "--project", str(Path(directory) / "demo")],
                env=ENV, capture_output=True, text=True, encoding="utf-8", timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = (Path(directory) / "demo" / "mock-calls.jsonl").read_text(encoding="utf-8").splitlines()
            servers = json.loads((Path(directory) / "demo" / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertIn('"key": "SUP-142"', result.stdout)
        self.assertIn("gryzzly              named in the profile. Servers: no MCP server on record", result.stdout)
        self.assertEqual([json.loads(line)["call"] for line in calls][-1], "log_work")
        self.assertEqual(set(servers), {"jira", "github", "snyk", "factorial", "tempo"})


class ProjectConnectionTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.project = Path(self._directory.name)
        (self.project / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
        (self.project / ".github" / "workflows").mkdir(parents=True)
        (self.project / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
        cli(self.project, "init", "--answers", self.project / "profile.json")

    def test_from_the_profile_to_a_working_mock_and_an_evidence_item(self):
        recommended = json.loads(cli(self.project, "tools", "recommend", "--json").stdout)
        by_id = {item["id"]: item for item in recommended["tools"]}
        self.assertEqual(set(by_id), {"jira", "snyk", "gryzzly", "github"})
        self.assertTrue(by_id["jira"]["named"] and by_id["jira"]["mock"])
        self.assertEqual(by_id["github"]["signals"], [".github/workflows/*.yml"])
        self.assertEqual(by_id["gryzzly"]["servers"], [])
        self.assertEqual(recommended["unknown"], ["Our intranet"])

        plan = cli(self.project, "tools", "plan", "jira", "snyk", "gryzzly")
        self.assertIn("atlassian-rovo", plan.stdout)
        self.assertIn("codex mcp login atlassian-rovo", plan.stdout)
        self.assertIn("Gryzzly: skipped. It has no MCP server on record.", plan.stdout)
        self.assertFalse((self.project / ".codex" / "config.toml").exists())
        self.assertFalse((self.project / ".openguildkit" / "tools.json").exists())

        journal = self.project / "mock-calls.jsonl"
        applied = cli(self.project, "tools", "apply", "jira", "snyk", "gryzzly", "--mock", "--log", journal,
                      check=False)
        self.assertEqual(applied.returncode, 2)
        self.assertIn("Wrote jira, snyk", applied.stdout)
        self.assertIn("Connected mocks: jira, snyk. Tools without a mock: gryzzly.", applied.stdout)
        config = tomllib.loads((self.project / ".codex" / "config.toml").read_text(encoding="utf-8"))
        entry = config["mcp_servers"]["jira"]
        self.assertEqual((entry["command"], entry["args"][:3]), ("openguildkit", ["tools", "mock", "jira"]))
        self.assertEqual(cli(self.project, "tools", "status").returncode, 0)
        statuses = json.loads(cli(self.project, "tools", "status", "--json").stdout)
        skipped = next(item for item in statuses if item["key"] == "gryzzly")
        self.assertFalse(skipped["configured"])
        self.assertIn("No mock", skipped["reason"])
        recommended = json.loads(cli(self.project, "tools", "recommend", "--json").stdout)
        jira = next(item for item in recommended["tools"] if item["id"] == "jira")
        self.assertEqual(jira["connections"], [{"host": "codex", "mode": "mock"}])
        suggestion = next(line for line in cli(self.project, "tools", "recommend").stdout.splitlines()
                          if line.startswith("Next:"))
        self.assertNotIn("jira", suggestion)
        self.assertNotIn("snyk", suggestion)

        command = [sys.executable, "-m", "openguildkit", "--project", str(self.project), *entry["args"]]
        answer = exchange(command, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "get_issue", "arguments": {"key": "SUP-142"}}}])[0]
        self.assertFalse(answer["result"]["isError"])

        cli(self.project, "task", "new", "Let customers export their own support requests as CSV.", "--id", "export")
        answers = {"kind": "feature", "surface": ["customer"], "data": "personal", "research": "local", "concerns": ["none"],
                   "outcome": "A customer downloads their requests.", "affected": "Customers"}
        (self.project / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
        brief = cli(self.project, "task", "consult", "export", "--answers", self.project / "answers.json").stdout
        self.assertIn("Jira (server jira, mock data)", brief)
        record = json.loads(cli(self.project, "task", "show", "export").stdout)
        self.assertEqual([item["id"] for item in record["consultation"]["scope"]["tools"]], ["jira", "snyk"])
        board = record["consultation"]["boards"][0]
        entry = next(item for item in record["consultation"]["review_template"]["boards"] if item["id"] == board)
        entry["recommendation"] = "Ship the export."
        entry["evidence"] = [{"source": "tool", "ref": "jira:SUP-142", "supports": "The request is tracked and in progress."}]
        for lens in entry["challenge"]["specialists"]:
            lens.update(finding="Checked in the tracker.", basis="observed", evidence_refs=[1])
        entry["challenge"].update(verdict="revise", confidence="medium", alternative="Keep the current screen.",
                                  failure_mode="A customer sees another customer's request.", verification="Run the ownership test.")
        cli(self.project, "task", "pass", "export", board, "--mode", "sequential")
        (self.project / "entry.json").write_text(json.dumps(entry), encoding="utf-8")
        submitted = cli(self.project, "task", "submit", "export", "--file", self.project / "entry.json")
        self.assertEqual(submitted.stdout.strip(), "done")
        self.assertNotIn("no recorded jira call", submitted.stderr)
        self.assertIn("the cited record comes from the jira mock, synthetic sample data", submitted.stderr)
        entry["evidence"][0]["ref"] = "jira:SUP-99999"
        (self.project / "entry.json").write_text(json.dumps(entry), encoding="utf-8")
        unverified = cli(self.project, "task", "submit", "export", "--file", self.project / "entry.json")
        self.assertIn("the jira mock holds no record with the cited id", unverified.stderr)
        self.assertNotIn("SUP-99999", unverified.stderr)
        entry["evidence"][0]["ref"] = "gryzzly:timesheet-4"
        (self.project / "entry.json").write_text(json.dumps(entry), encoding="utf-8")
        refused = cli(self.project, "task", "submit", "export", "--file", self.project / "entry.json", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("Connected: jira, snyk", refused.stderr)
        for other in record["consultation"]["boards"]:
            entry = next(item for item in record["consultation"]["review_template"]["boards"] if item["id"] == other)
            entry["recommendation"] = "Ship the export."
            entry["evidence"] = [{"source": "tool", "ref": "jira:SUP-142", "supports": "The request is tracked."}]
            for lens in entry["challenge"]["specialists"]:
                lens.update(finding="Checked in the tracker.", basis="observed", evidence_refs=[1])
            entry["challenge"].update(verdict="proceed", confidence="high", alternative="Keep the current screen.",
                                      failure_mode="A customer sees another customer's request.",
                                      verification="Run the ownership test.")
            if other != board:
                cli(self.project, "task", "pass", "export", other, "--mode", "sequential")
            (self.project / "entry.json").write_text(json.dumps(entry), encoding="utf-8")
            cli(self.project, "task", "submit", "export", "--file", self.project / "entry.json")
        cli(self.project, "task", "review", "export", "--summary", "Ship the export, ownership tested.")
        count = len(record["consultation"]["boards"])
        decision_brief = cli(self.project, "task", "challenge", "export").stdout
        self.assertIn(f"Mock data: {count} evidence item(s) come from mock tools, synthetic sample data and not the "
                      f"real systems: {board} #1 jira:SUP-142", decision_brief)

        removed = cli(self.project, "tools", "remove", "jira", "snyk")
        self.assertIn("Removed jira, snyk", removed.stdout)
        self.assertNotIn("mcp_servers", tomllib.loads((self.project / ".codex" / "config.toml").read_text(encoding="utf-8")))

    def test_a_completely_unavailable_mock_request_only_writes_its_status(self):
        result = cli(self.project, "tools", "apply", "gryzzly", "--mock", "--host", "claude-code", "--json", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["applied"], [])
        config = self.project / ".mcp.json"
        self.assertFalse(config.exists())
        self.assertIn("gryzzly", cli(self.project, "tools", "status").stdout)
        self.assertIn("No mock", cli(self.project, "tools", "status").stdout)
        cli(self.project, "tools", "remove", "gryzzly", "--host", "claude-code")
        self.assertEqual(json.loads(cli(self.project, "tools", "status", "--json").stdout), [])
        self.assertFalse(config.exists())

    def test_live_connections_for_claude_code_name_variables_only(self):
        unconfirmed = cli(self.project, "tools", "apply", "jira", "--host", "claude-code", check=False, stdin="")
        self.assertEqual(unconfirmed.returncode, 1)
        self.assertIn("--yes", unconfirmed.stderr)
        self.assertFalse((self.project / ".mcp.json").exists())
        cli(self.project, "tools", "apply", "jira", "github/github-local", "linear", "--host", "claude-code",
            "--token-env", "linear=LINEAR_API_KEY", "--yes")
        servers = json.loads((self.project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(servers["atlassian-rovo"]["type"], "http")
        self.assertEqual(servers["github-local"]["env"], {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"})
        self.assertEqual(servers["linear-remote"]["headers"], {"Authorization": "Bearer ${LINEAR_API_KEY}"})
        status = cli(self.project, "tools", "status", "--json").stdout
        missing = {item["key"]: item["missing_env"] for item in json.loads(status)}
        if not os.environ.get("LINEAR_API_KEY"):
            self.assertEqual(missing["linear-remote"], ["LINEAR_API_KEY"])
        refused = cli(self.project, "tools", "apply", "zendesk", "--host", "claude-code", "--yes", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("Settings are missing", refused.stderr)
        self.assertNotIn("Traceback", refused.stderr)


if __name__ == "__main__":
    unittest.main()
