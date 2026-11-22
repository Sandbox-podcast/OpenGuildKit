"""Check access metadata, environment forwarding and the facts of the bundled registry."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import main
from openguildkit.tools import NOT_RECORDED, load_tools, plan_connections


class ToolRegistryTests(unittest.TestCase):
    def test_every_bundled_server_reports_access_and_consent(self):
        catalog = load_tools()
        for tool_id, tool in catalog.items():
            for server in tool["servers"]:
                key = f"{tool_id}/{server['id']}"
                with self.subTest(server=key):
                    self.assertIn("access", server, "record whether the server reads, writes or both")
                    host = "claude-code" if server["transport"] == "sse" else "codex"
                    plan = plan_connections(catalog, [key], host, community=True)[0]
                    review = plan["review"]
                    self.assertFalse(review["access"].startswith(NOT_RECORDED), review["access"])
                    for field in ("scopes", "read_only", "credentials", "covers", "publisher", "version"):
                        self.assertTrue(review[field], field)
                    for field in ("status", "source"):
                        self.assertTrue(plan[field], field)

    def test_every_variable_a_docker_server_declares_is_passed_to_its_container(self):
        missing = []
        for tool in load_tools().values():
            for server in tool.get("servers", []):
                if server.get("command") != "docker":
                    continue
                args = server.get("args", [])
                passed = {args[index + 1].split("=", 1)[0] for index, arg in enumerate(args[:-1]) if arg in ("-e", "--env")}
                for name in server.get("env", []):
                    if name not in passed:
                        missing.append(f"{tool['id']}/{server['id']}: {name}")
        self.assertEqual(missing, [], "Pass each declared variable with -e NAME so the container receives it.")

    def test_toggl_track_gets_no_toggl_focus_server(self):
        catalog = load_tools()
        track, focus = catalog["toggl-track"], catalog["toggl-focus"]
        self.assertEqual(track["servers"], [])
        self.assertEqual(track["api"]["docs"], "https://engineering.toggl.com/docs/track/")
        self.assertIn("API v9", track["notes"])
        self.assertEqual({server["url"] for server in focus["servers"] if "url" in server}, {"https://focus.toggl.com/mcp"})
        self.assertIn("Toggl Focus", focus.get("aliases", []))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.json").write_text(json.dumps({"name": "x", "host": "claude-code"}), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                main(["--project", directory, "init", "--answers", str(Path(directory) / "a.json")])
                main(["--project", directory, "tools", "plan", "toggl-track", "--host", "claude-code"])
            self.assertNotIn("focus.toggl.com", output.getvalue())
            self.assertNotIn("tools apply toggl-track", output.getvalue())

    def test_a_known_status_cites_the_page_that_states_it(self):
        for tool_id, tool in load_tools().items():
            for server in tool["servers"]:
                with self.subTest(server=f"{tool_id}/{server['id']}"):
                    if server["status"] == "unknown":
                        self.assertNotIn("status_source", server)
                    else:
                        self.assertTrue(server["status_source"].startswith("https://"))
        catalog = load_tools()
        self.assertEqual(catalog["hubspot"]["servers"][0]["status"], "unknown")
        self.assertNotIn("changelog", catalog["hubspot"]["notes"])
        self.assertIn("repository", catalog["jira"]["notes"])
        self.assertIn("30 June 2026", catalog["jira"]["notes"])
        self.assertIn("Free, Starter and Basic", catalog["pennylane"]["notes"])
        rovo = {catalog[tool]["servers"][0]["status_source"] for tool in ("jira", "confluence", "bitbucket")}
        self.assertEqual(rovo, {"https://github.com/atlassian/atlassian-mcp-server"})


if __name__ == "__main__":
    unittest.main()
