"""The tool registry describes servers that really start: what a docker server declares reaches the container."""

import unittest

from openguildkit.tools import load_tools


class DockerServerTests(unittest.TestCase):
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
