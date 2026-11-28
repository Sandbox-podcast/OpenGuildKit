"""Check access metadata, environment forwarding and the facts of the bundled registry."""

import contextlib
import copy
import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from openguildkit.catalog import CatalogError
from openguildkit.cli import main
from openguildkit.tools import NOT_RECORDED, _validate_tool, check_settings, load_tools, plan_connections
from tests.support import run_cli

# A local server as a publisher documents it, before the checks below change one field.
LOCAL = {
    "id": "acme-local", "name": "Acme MCP", "publisher": "vendor", "maintainer": "Acme", "transport": "stdio",
    "command": "node", "args": ["dist/index.js", "--transport=stdio"],
    "package": {"registry": "other", "name": "github.com/acme/acme-mcp (clone and build)"}, "auth": "none", "env": [],
    "status": "unknown", "capabilities": "Read tickets.", "source": "https://docs.acme.example/mcp", "verified": "2026-11-21",
}


def local_tool(**server) -> dict:
    return {"id": "acme", "title": "Acme", "vendor": "Acme", "summary": "A tracker.", "homepage": "https://acme.example",
            "brains": ["qa"], "servers": [{**copy.deepcopy(LOCAL), **server}]}


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


class StandInCommandTests(unittest.TestCase):
    """A command copied with the publisher's stand-in for a path starts nothing: the registry asks for the value."""

    def test_a_stand_in_path_or_angle_brackets_in_a_command_or_an_argument_is_refused(self):
        for change in ({"command": "path/to/bundled-lens-cli"}, {"args": ["path/to/mcp-quickbooks-online/dist/index.js"]},
                       {"args": ["/FULL/PATH/TO/YOUR/docker-hub-mcp-server/dist/index.js", "--transport=stdio"]},
                       {"command": "<lens-cli>"}, {"args": ["--site=<your-site>"]}):
            with self.subTest(change=change), self.assertRaisesRegex(CatalogError, "placeholders as {name}"):
                _validate_tool(local_tool(**change), "testing")

    def test_a_command_takes_a_declared_placeholder_like_its_arguments(self):
        setting = [{"name": "cli_path", "description": "Acme: the path of the Acme CLI"}]
        self.assertIsNone(_validate_tool(local_tool(command="{cli_path}", settings=setting), "testing"))
        with self.assertRaisesRegex(CatalogError, "declare exactly the placeholders used: cli_path"):
            _validate_tool(local_tool(command="{cli_path}"), "testing")

    def test_plan_asks_for_the_real_path_and_says_where_to_find_it(self):
        catalog = load_tools()
        for tool_id, setting, where in (("lens", "cli_path", "snippet Lens shows"),
                                        ("quickbooks", "clone_path", "github.com/intuit/quickbooks-online-mcp-server"),
                                        ("docker-hub", "clone_path", "github.com/docker/hub-mcp")):
            with self.subTest(tool=tool_id):
                plan = plan_connections(catalog, [tool_id], "claude-code")[0]
                self.assertIn(setting, plan["needs"]["settings"])
                step = next(step for step in plan["steps"] if step.startswith("Still to provide"))
                self.assertRegex(step, rf"--set {tool_id}\.{setting}=VALUE \([^)]*{re.escape(where)}")
                with self.assertRaisesRegex(ValueError, f"{tool_id}: provide .*{setting}"):
                    check_settings([plan])
                self.assertNotRegex(json.dumps(catalog[tool_id]), r"(?i)path/to|[<>]")
        lens = plan_connections(catalog, ["lens"], "claude-code", settings={"lens": {"cli_path": "/opt/example/lens-cli"}})[0]
        self.assertEqual((lens["entry"]["command"], lens["entry"]["args"]), ("/opt/example/lens-cli", ["mcp-server"]))
        self.assertIn("`/opt/example/lens-cli` runs on each workstation", " ".join(lens["steps"]))
        quickbooks = plan_connections(catalog, ["quickbooks"], "codex",
                                      settings={"quickbooks": {"clone_path": "C:/work/quickbooks-online-mcp-server"}})[0]
        self.assertEqual(quickbooks["entry"]["args"], ["C:/work/quickbooks-online-mcp-server/dist/index.js"])

    def test_apply_writes_nothing_until_the_path_is_given(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"name": "x", "host": "claude-code", "personal_data": "no"}),
                                         encoding="utf-8")
            run_cli(root, "init", "--answers", root / "a.json")
            plan = run_cli(root, "tools", "plan", "lens").stdout
            self.assertIn("Still to provide: --set lens.cli_path=VALUE (Lens: ", plan)
            refused = run_cli(root, "tools", "apply", "lens", "--yes", expect=1)
            self.assertIn("lens: provide cli_path", refused.stderr)
            self.assertFalse((root / ".mcp.json").exists())
            run_cli(root, "tools", "apply", "lens", "--yes", "--set", "lens.cli_path=/opt/example/lens-cli")
            entry = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["lens-mcp-server"]
            self.assertEqual(entry["command"], "/opt/example/lens-cli")

    def test_docker_hub_runs_the_command_its_page_publishes(self):
        tool = load_tools()["docker-hub"]
        server = tool["servers"][0]
        self.assertEqual(server["source"], "https://docs.docker.com/docker-hub/mcp-server/")
        self.assertNotIn("dockerhub-mcp", json.dumps(tool))
        settings = {"docker-hub": {"hub_username": "demo-user", "clone_path": "/srv/example/hub-mcp"}}
        plan = plan_connections(load_tools(), ["docker-hub"], "claude-code", settings=settings)[0]
        self.assertEqual(plan["entry"], {
            "command": "node", "args": ["/srv/example/hub-mcp/dist/index.js", "--transport=stdio", "--username=demo-user"],
            "env": {"HUB_PAT_TOKEN": "${HUB_PAT_TOKEN}"}})


NETWORK = os.environ.get("OPENGUILDKIT_NETWORK_TESTS") == "1"


def _read(url: str, headers: dict | None = None) -> tuple[int, bytes, object]:
    """GET a public registry page: its status, body and headers (any case); 404 and 401 are answers, not errors."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(), error.headers


def image_exists(reference: str) -> bool:
    """An image as a docker command spells it, on Docker Hub or another registry: its manifest answers."""
    name, _, digest = reference.partition("@")
    tag = "latest"
    if not digest and ":" in name.rsplit("/", 1)[-1]:
        name, tag = name.rsplit(":", 1)
    first = name.split("/", 1)[0]
    host, repository = (first, name.split("/", 1)[1]) if "." in first or ":" in first else ("registry-1.docker.io", name)
    if host == "registry-1.docker.io" and "/" not in repository:
        repository = f"library/{repository}"
    url = f"https://{host}/v2/{repository}/manifests/{digest or tag}"
    accept = {"Accept": ", ".join((
        "application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json"))}
    status, _, headers = _read(url, accept)
    challenge = headers.get("WWW-Authenticate", "")
    if status == 401 and challenge.startswith("Bearer "):
        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        query = urllib.parse.urlencode({key: fields[key] for key in ("service", "scope") if key in fields})
        _, body, _ = _read(f"{fields['realm']}?{query}")
        answer = json.loads(body)
        status, _, _ = _read(url, {**accept, "Authorization": f"Bearer {answer.get('token') or answer.get('access_token')}"})
    return status == 200


def package_exists(registry: str, name: str, version: str | None) -> bool:
    """An npm or PyPI package, and the exact version a command pins when it pins one."""
    if registry == "npm":
        status, body, _ = _read(f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@')}")
        return status == 200 and (version is None or version in json.loads(body).get("versions", {}))
    path = f"{name}/{version}" if version else name
    return _read(f"https://pypi.org/pypi/{path}/json")[0] == 200


def registry_packages() -> list[tuple[str, str, str, str | None]]:
    """Each docker image, npm or PyPI package of the bundled registry, as its command spells it."""
    found = []
    for tool in load_tools().values():
        for server in tool["servers"]:
            package = server.get("package", {})
            name, registry = package.get("name"), package.get("registry")
            if registry not in ("docker", "npm", "pypi"):
                continue
            label = f"{tool['id']}/{server['id']}"
            spelled = next((arg for arg in server["args"] if arg == name or arg.startswith((name + ":", name + "@",
                                                                                            name + "=="))), name)
            if registry == "docker":
                found.append((label, registry, spelled, None))
                continue
            pinned = re.split(r"@|==", spelled[len(name):], maxsplit=1)[-1] if spelled != name else None
            found.append((label, registry, name, None if pinned in (None, "", "latest") else pinned))
    return found


@unittest.skipUnless(NETWORK, "Reads Docker Hub, ghcr.io, npm and PyPI: set OPENGUILDKIT_NETWORK_TESTS=1 to run it.")
class RegistryPackagesExistTests(unittest.TestCase):
    """Optional, on the network: every image and package a registered command runs exists where it says."""

    def test_every_docker_image_and_npm_or_pypi_package_of_the_registry_exists(self):
        missing = []
        for label, registry, name, version in registry_packages():
            exists = image_exists(name) if registry == "docker" else package_exists(registry, name, version)
            if not exists:
                missing.append(f"{label}: {registry} {name}" + (f" {version}" if version else ""))
        self.assertEqual(missing, [], "fix these commands from the publisher's page")


class RegistryPackageListTests(unittest.TestCase):
    def test_the_network_check_reads_every_package_as_its_command_spells_it(self):
        packages = {(registry, name, version) for _, registry, name, version in registry_packages()}
        self.assertIn(("docker", "hashicorp/terraform-mcp-server:1.4.1", None), packages)
        self.assertIn(("pypi", "mailchimp-mcp", "1.3.0"), packages)
        self.assertIn(("npm", "@playwright/mcp", "0.0.86"), packages)
        self.assertGreaterEqual(len(packages), 30)


if __name__ == "__main__":
    unittest.main()
