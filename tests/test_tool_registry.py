"""Check access metadata and environment forwarding in the bundled registry."""

import unittest

from openguildkit.tools import load_tools, plan_connections


class ToolRegistryTests(unittest.TestCase):
    def test_every_bundled_server_reports_access_and_consent(self):
        catalog = load_tools()
        for tool_id, tool in catalog.items():
            for server in tool["servers"]:
                key = f"{tool_id}/{server['id']}"
                with self.subTest(server=key):
                    host = "claude-code" if server["transport"] == "sse" else "codex"
                    plan = plan_connections(catalog, [key], host, community=True)[0]
                    self.assertIn(plan["access"]["mode"], ("read", "read-only", "read-write", "configurable"))
                    self.assertTrue(plan["access"]["consent"])
                    self.assertTrue(plan["access"]["scopes"])
                    for field in ("capabilities", "maintainer", "status", "source"):
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


if __name__ == "__main__":
    unittest.main()
