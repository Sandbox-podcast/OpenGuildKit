"""The tool registry: what it accepts, how it matches a project and what it writes for each host."""

import contextlib
import copy
import io
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock as patching

from openguildkit.catalog import CatalogError, load_catalog
from openguildkit.cli import main
from openguildkit.mcp_mock import call_tool, describe, example_arguments, list_all_arguments, reference_problems
from openguildkit.tools import (
    CATEGORIES, NOT_DOCUMENTED, _validate_tool, apply_connections, check_tool_links, choose_server, connection_status,
    detect_tools, load_mock, load_tools, match_tools, mock_ids, plan_connections, read_manifest, remove_connections,
    scenario_records,
)

TOOLS = load_tools()
REMOTE = {
    "id": "acme-remote", "name": "Acme MCP", "publisher": "vendor", "maintainer": "Acme", "transport": "streamable-http",
    "url": "https://mcp.acme.example/mcp", "auth": "oauth", "env": [], "status": "ga",
    "capabilities": "Read tickets.", "source": "https://docs.acme.example/mcp", "verified": "2026-11-21",
}
TOOL = {
    "id": "acme", "title": "Acme", "vendor": "Acme", "summary": "A tracker.", "homepage": "https://acme.example",
    "brains": ["qa"], "servers": [REMOTE],
}


def run(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()


class RegistryTests(unittest.TestCase):
    def test_the_bundled_registry_is_complete_and_linked_to_the_brains(self):
        check_tool_links(TOOLS, load_catalog()["boards"])
        self.assertGreaterEqual(len(TOOLS), 130)
        self.assertEqual({tool["category"] for tool in TOOLS.values()} - set(CATEGORIES), set())
        for name in ("jira", "factorial", "gryzzly", "snyk", "obscura", "storybook", "documentalist"):
            self.assertIn(name, TOOLS)
        self.assertEqual(TOOLS["gryzzly"]["servers"], [])
        self.assertIn("api", TOOLS["gryzzly"])

    def test_every_server_names_its_source_and_never_a_credential(self):
        for tool in TOOLS.values():
            for server in tool["servers"]:
                label = f"{tool['id']}/{server['id']}"
                self.assertTrue(server["source"].startswith("https://"), label)
                self.assertRegex(server["verified"], r"^\d{4}-\d{2}-\d{2}$", label)
                text = json.dumps(server)
                self.assertNotRegex(text, r"(?i)(sk|pk|ghp|xox[bp])[-_][A-Za-z0-9]{12,}", label)
                self.assertNotRegex(server.get("url", ""), r"(?i)[?&][^=]*(token|key|secret)=", label)
                for name in server["env"]:
                    self.assertRegex(name, r"^[A-Z][A-Z0-9_]+$", label)

    def test_one_server_shared_by_several_tools_keeps_one_endpoint(self):
        self.assertEqual(TOOLS["jira"]["servers"][0]["id"], TOOLS["confluence"]["servers"][0]["id"])
        self.assertEqual(TOOLS["jira"]["servers"][0]["url"], TOOLS["confluence"]["servers"][0]["url"])

    def test_entries_with_credentials_or_undeclared_placeholders_are_refused(self):
        cases = {
            "credential in its query": {"url": "https://mcp.acme.example/mcp?api_key=abc"},
            "https URL": {"url": "http://mcp.acme.example/mcp"},
            "declare exactly the placeholders": {"url": "https://{subdomain}.acme.example/mcp"},
            "verified is the date": {"verified": "yesterday"},
            "list of unique names": {"env": ["acme token"]},
            "transport is one of": {"transport": "websocket"},
        }
        for message, change in cases.items():
            tool = copy.deepcopy(TOOL)
            tool["servers"][0].update(change)
            with self.assertRaisesRegex(CatalogError, message):
                _validate_tool(tool, "testing")
        local = copy.deepcopy(TOOL)
        local["servers"][0] = {
            **{key: value for key, value in REMOTE.items() if key != "url"}, "transport": "stdio", "command": "docker",
            "args": ["run", "-e", "ACME_TOKEN=abc123"], "package": {"registry": "docker", "name": "acme/mcp"},
        }
        with self.assertRaisesRegex(CatalogError, "must come from the environment"):
            _validate_tool(local, "testing")
        local["servers"][0]["args"] = ["run", "-e", "ACME_TOKEN", "--site=<your-site>"]
        with self.assertRaisesRegex(CatalogError, "placeholders as"):
            _validate_tool(local, "testing")

    def test_a_loopback_endpoint_is_accepted_for_servers_that_run_on_the_workstation(self):
        tool = copy.deepcopy(TOOL)
        tool["servers"][0]["url"] = "http://127.0.0.1:3845/mcp"
        _validate_tool(tool, "testing")

    def test_a_project_adds_its_own_tools_and_cannot_redefine_a_bundled_one(self):
        with tempfile.TemporaryDirectory() as directory:
            extra = Path(directory)
            (extra / "testing.json").write_text(json.dumps({"id": "testing", "title": "Ours", "tools": [TOOL]}), encoding="utf-8")
            self.assertIn("acme", load_tools(extra))
            clash = {**TOOL, "id": "jira"}
            (extra / "testing.json").write_text(json.dumps({"id": "testing", "title": "Ours", "tools": [clash]}), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "already defined"):
                load_tools(extra)


class MatchingTests(unittest.TestCase):
    def test_names_written_by_a_team_resolve_to_registry_ids(self):
        matched, unknown = match_tools(["Jira Cloud", "github", "Factorial HR", "Our intranet", "GA4", "jira"], TOOLS)
        self.assertEqual(matched, ["jira", "github", "factorial", "google-analytics"])
        self.assertEqual(unknown, ["Our intranet"])

    def test_the_repository_shows_which_tools_it_uses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
            (root / "package.json").write_text(json.dumps({"devDependencies": {"@playwright/test": "^1.50.0", "storybook": "^10"}}), encoding="utf-8")
            (root / "api").mkdir()
            (root / "api" / "requirements.txt").write_text("sentry-sdk==2.0\n# comment\nfastapi\n", encoding="utf-8")
            found = {item["tool"]: item["signals"] for item in detect_tools(root, TOOLS)}
        self.assertEqual(found["github"], [".github/workflows/*.yml"])
        self.assertIn("npm:@playwright/test", found["playwright"])
        self.assertIn("npm:storybook", found["storybook"])
        self.assertEqual(found["sentry"], ["pypi:sentry-sdk"])
        self.assertNotIn("jira", found)

    def test_the_vendor_remote_server_comes_first_and_community_servers_need_consent(self):
        self.assertEqual(choose_server(TOOLS["github"])["id"], "github-remote")
        self.assertIsNone(choose_server(TOOLS["redmine"]))
        self.assertEqual(choose_server(TOOLS["redmine"], community=True)["publisher"], "community")
        with self.assertRaisesRegex(ValueError, "community server"):
            choose_server(TOOLS["redmine"], TOOLS["redmine"]["servers"][0]["id"])
        self.assertIsNone(choose_server(TOOLS["gryzzly"], community=True))


class PlanTests(unittest.TestCase):
    def test_a_plan_names_what_each_person_provides_and_writes_no_value(self):
        plan = plan_connections(TOOLS, ["jira", "confluence", "github/github-local", "gryzzly"], "claude-code")
        jira, github, gryzzly = plan
        self.assertEqual(jira["covers"], ["jira", "confluence"])
        self.assertEqual(jira["entry"], {"type": "http", "url": TOOLS["jira"]["servers"][0]["url"]})
        self.assertEqual(github["entry"]["env"], {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"})
        self.assertEqual(github["needs"]["env"], ["GITHUB_PERSONAL_ACCESS_TOKEN"])
        self.assertIn("no MCP server on record", gryzzly["skipped"])
        self.assertIn("API:", gryzzly["skipped"])

    def test_codex_entries_forward_variable_names_and_bearer_tokens_by_name(self):
        local = plan_connections(TOOLS, ["github/github-local"], "codex")[0]["entry"]
        self.assertEqual(local["env_vars"], ["GITHUB_PERSONAL_ACCESS_TOKEN"])
        self.assertNotIn("env", local)
        remote = plan_connections(TOOLS, ["linear"], "codex", token_env={"linear": "LINEAR_API_KEY"})[0]
        self.assertEqual(remote["entry"], {"url": "https://mcp.linear.app/mcp", "bearer_token_env_var": "LINEAR_API_KEY"})
        claude = plan_connections(TOOLS, ["linear"], "claude-code", token_env={"linear": "LINEAR_API_KEY"})[0]
        self.assertEqual(claude["entry"]["headers"], {"Authorization": "Bearer ${LINEAR_API_KEY}"})

    def test_settings_fill_the_endpoint_and_refuse_anything_that_looks_like_a_secret(self):
        missing = plan_connections(TOOLS, ["zendesk"], "claude-code")[0]
        self.assertEqual(missing["needs"]["settings"], ["subdomain"])
        filled = plan_connections(TOOLS, ["zendesk"], "claude-code", settings={"zendesk": {"subdomain": "acme"}})[0]
        self.assertEqual(filled["entry"]["url"], "https://acme.zendesk.com/mcp")
        with self.assertRaisesRegex(ValueError, "no setting"):
            plan_connections(TOOLS, ["zendesk"], "claude-code", settings={"zendesk": {"token": "abc"}})
        with self.assertRaisesRegex(ValueError, "plain value"):
            plan_connections(TOOLS, ["zendesk"], "claude-code", settings={"zendesk": {"subdomain": "a b;rm"}})
        with self.assertRaisesRegex(ValueError, "names an environment variable"):
            plan_connections(TOOLS, ["linear"], "codex", token_env={"linear": "lin_api_abc123"})

    def test_known_credential_formats_never_enter_a_plan(self):
        formats = (
            "sk_live_" + "s" * 24, "sk_test_" + "t" * 24, "ghp_" + "p" * 36, "gho_" + "o" * 36,
            "github_pat_" + "x" * 24, "AKIA" + "A" * 16, "xoxb-" + "8" * 20,
        )
        for value in formats:
            with self.assertRaisesRegex(ValueError, "never a credential") as error:
                plan_connections(TOOLS, ["zendesk"], "claude-code", settings={"zendesk": {"subdomain": value}})
            self.assertNotIn(value, str(error.exception))
            with self.assertRaisesRegex(ValueError, "names an environment variable") as error:
                plan_connections(TOOLS, ["jira"], "codex", mock=True, mocks=mock_ids(), token_env={"jira": value})
            self.assertNotIn(value, str(error.exception))

    def test_plan_exposes_scope_alternatives_and_read_only_configuration(self):
        workspace = plan_connections(TOOLS, ["Google-Workspace"], "codex")[0]
        self.assertIn("read and write", workspace["review"]["access"])
        self.assertIn("gmail.modify", workspace["review"]["scopes"])
        self.assertTrue(any(line.startswith("google-workspace/calendar-mcp") for line in workspace["review"]["alternatives"]))
        # --read-only prefers the tool's server that documents a read-only mode.
        search = plan_connections(TOOLS, ["Google-Workspace"], "codex", read_only=True)[0]
        self.assertEqual(search["server"], "workspace-universal-search-mcp")
        self.assertTrue(search["read_only"])
        self.assertIn("read-only", search["review"]["read_only"])
        sonar = plan_connections(TOOLS, ["sonarqube"], "codex", read_only=True)[0]
        self.assertIn("without a tag", sonar["review"]["version"])
        args = sonar["entry"]["args"]
        self.assertLess(args.index("SONARQUBE_READ_ONLY=true"), args.index("sonarsource/sonarqube-mcp"))
        self.assertEqual(args[args.index("SONARQUBE_READ_ONLY=true") - 1], "-e")
        # A named server without a read-only mode is planned as it is, with a warning, never silently.
        gmail = plan_connections(TOOLS, ["google-workspace/gmail-mcp"], "codex", read_only=True)[0]
        self.assertFalse(gmail["read_only"])
        self.assertTrue(any("No read-only mode is documented" in warning for warning in gmail["warnings"]))

    def test_remote_read_only_variants_change_the_endpoint_for_both_hosts(self):
        endpoints = {
            "buildkite": "https://mcp.buildkite.com/mcp/readonly",
            "neon": "https://mcp.neon.tech/mcp?readonly=true",
            "salesforce": "https://api.salesforce.com/platform/mcp/v1/platform/sobject-reads",
            "supabase": "https://mcp.supabase.com/mcp?read_only=true",
        }
        for host in ("codex", "claude-code"):
            for tool_id, endpoint in endpoints.items():
                with self.subTest(tool=tool_id, host=host):
                    regular = plan_connections(TOOLS, [tool_id], host)[0]
                    restricted = plan_connections(TOOLS, [tool_id], host, read_only=True)[0]
                    self.assertNotEqual(regular["entry"]["url"], endpoint)
                    self.assertEqual(restricted["entry"]["url"], endpoint)
                    self.assertTrue(restricted["read_only"])
                    self.assertFalse(regular["read_only"])
        self.assertIn("read-only Postgres", plan_connections(TOOLS, ["supabase"], "codex",
                      read_only=True)[0]["review"]["read_only"])

    def test_local_read_only_flags_preserve_the_original_invocation(self):
        for tool_id, flag in (("azure", "--read-only"), ("basecamp/basecamp-cli", "--read-only"),
                              ("grafana", "--disable-write"), ("kubernetes", "--read-only")):
            with self.subTest(tool=tool_id):
                normal = plan_connections(TOOLS, [tool_id], "codex", community=True)[0]
                restricted = plan_connections(TOOLS, [tool_id], "codex", community=True, read_only=True)[0]
                self.assertEqual(restricted["entry"]["args"], normal["entry"]["args"] + [flag])
        basecamp = plan_connections(TOOLS, ["basecamp"], "codex", read_only=True)[0]
        self.assertEqual(basecamp["server"], "basecamp-cli")

    def test_read_coverage_is_not_an_enforced_read_only_mode(self):
        plan = plan_connections(TOOLS, ["cypress"], "codex")[0]
        self.assertIn("no enforced read-only mode", plan["review"]["access"])
        self.assertFalse(plan["read_only"])
        restricted = plan_connections(TOOLS, ["cypress"], "codex", read_only=True)[0]
        self.assertFalse(restricted["read_only"])
        self.assertTrue(any("read-only permissions instead" in warning for warning in restricted["warnings"]))
        mongo = plan_connections(TOOLS, ["mongodb"], "codex", read_only=True)[0]
        self.assertEqual(mongo["entry"]["args"].count("--readOnly"), 1)

    def test_mailchimp_plan_names_newsletter_alternative_and_requires_community_opt_in(self):
        plan = plan_connections(TOOLS, ["mailchimp"], "codex")[0]
        self.assertEqual(plan["server"], "mailchimp-transactional-mcp")
        alternatives = {line.partition(" ")[0]: line for line in plan["review"]["alternatives"]}
        self.assertIn("public Marketing API documentation", alternatives["mailchimp/mailchimp-docs-mcp"])
        marketing = alternatives["mailchimp/mailchimp-marketing-local"]
        self.assertIn("(community,", marketing)
        self.assertIn("audiences", marketing)
        self.assertIn("read-only mode available", marketing)
        self.assertIn("--community --read-only", plan["review"]["notes"])
        with self.assertRaisesRegex(ValueError, "review its source, then pass --community"):
            plan_connections(TOOLS, ["mailchimp/mailchimp-marketing-local"], "codex", read_only=True)

    def test_a_server_two_tools_share_is_planned_once_with_each_tools_alternatives_and_notes(self):
        plan = plan_connections(TOOLS, ["jira", "Confluence", "JIRA"], "codex")
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["covers"], ["jira", "confluence"])
        review = plan[0]["review"]
        self.assertIn("The rest API without MCP: https://developer.atlassian.com/cloud/confluence/rest/v2/",
                      review["alternatives"])
        self.assertIn("Confluence: ", review["notes"])

    def test_a_server_that_only_reads_as_registered_needs_nothing_selected(self):
        normal = plan_connections(TOOLS, ["pennylane"], "codex")[0]
        restricted = plan_connections(TOOLS, ["pennylane"], "codex", read_only=True)[0]
        self.assertEqual(restricted["entry"], normal["entry"])
        self.assertTrue(restricted["read_only"])
        self.assertNotIn("Select it with --read-only", restricted["review"]["read_only"])
        self.assertIn("Select it with --read-only", plan_connections(TOOLS, ["linear"], "codex")[0]["review"]["read_only"])

    def test_read_only_selects_a_live_server_never_a_mock(self):
        with self.assertRaisesRegex(ValueError, "--read-only selects a live server"):
            plan_connections(TOOLS, ["jira"], "codex", mock=True, mocks=mock_ids(), read_only=True)

    def test_a_read_only_environment_holds_plain_values_for_a_local_server_only(self):
        local = {**REMOTE, "id": "acme-local", "transport": "stdio", "command": "uvx", "args": ["acme-mcp"],
                 "package": {"registry": "pypi", "name": "acme-mcp"}, "env": ["ACME_KEY"]}
        local.pop("url")
        for variant, message in (({"how": "Env.", "env": {"ACME_TOKEN": "x"}}, "never a credential"),
                                 ({"how": "Env.", "env": {"ACME_KEY": "true"}}, "never a credential"),
                                 ({"how": "Env.", "headers": {"X": "true"}}, "read_only has how")):
            tool = {**copy.deepcopy(TOOL), "servers": [{**local, "read_only": variant}]}
            with self.subTest(variant=variant), self.assertRaisesRegex(CatalogError, message):
                _validate_tool(tool, "testing")
        docker = {**local, "command": "docker", "args": ["run", "-i", "--rm", "-e", "ACME_KEY", "acme/mcp"],
                  "package": {"registry": "docker", "name": "acme/mcp"}}
        tool = {**copy.deepcopy(TOOL), "servers": [{**docker, "read_only": {"how": "Env.", "env": {"ACME_READ_ONLY": "true"}}}]}
        with self.assertRaisesRegex(CatalogError, "not run by docker|non-docker"):
            _validate_tool(tool, "testing")
        tool["servers"][0]["read_only"] = {"how": "Args.", "args": ["run", "-i", "--rm", "acme/mcp"]}
        with self.assertRaisesRegex(CatalogError, "add -e ACME_KEY"):
            _validate_tool(tool, "testing")
        tool["servers"][0]["read_only"] = {"how": "Args.", "args": ["run", "-i", "--rm", "-e", "ACME_KEY", "-e",
                                                                     "ACME_READ_ONLY=true", "acme/mcp"]}
        _validate_tool(tool, "testing")

    def test_mock_mode_replaces_every_server_with_a_local_one(self):
        plan = plan_connections(TOOLS, ["jira", "gryzzly"], "codex", mock=True, mocks=mock_ids(), log="calls.jsonl")
        self.assertEqual(plan[0]["entry"], {"command": "openguildkit", "args": ["tools", "mock", "jira", "--log", "calls.jsonl"]})
        self.assertIn("No mock", plan[1]["skipped"])


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.state = self.root / ".openguildkit"
        self.state.mkdir()

    def test_claude_code_file_keeps_the_persons_own_servers(self):
        (self.root / ".mcp.json").write_text(json.dumps({"mcpServers": {"mine": {"command": "my-server"}}}), encoding="utf-8")
        plan = plan_connections(TOOLS, ["jira", "snyk"], "claude-code")
        result = apply_connections(self.root, self.state, "claude-code", plan)
        self.assertEqual(result["applied"], ["atlassian-rovo", "snyk-cli-mcp"])
        servers = json.loads((self.root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(set(servers), {"mine", "atlassian-rovo", "snyk-cli-mcp"})
        first = (self.root / ".mcp.json").read_bytes()
        apply_connections(self.root, self.state, "claude-code", plan)
        self.assertEqual((self.root / ".mcp.json").read_bytes(), first)
        remove_connections(self.root, self.state, "claude-code", ["jira"])
        servers = json.loads((self.root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(set(servers), {"mine", "snyk-cli-mcp"})

    def test_a_server_the_person_already_defined_is_never_overwritten(self):
        (self.root / ".mcp.json").write_text(json.dumps({"mcpServers": {"atlassian-rovo": {"type": "http", "url": "https://other.example/mcp"}}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already defines atlassian-rovo"):
            apply_connections(self.root, self.state, "claude-code", plan_connections(TOOLS, ["jira"], "claude-code"))
        self.assertEqual(read_manifest(self.state)["connections"], [])

    def test_codex_block_is_valid_toml_beside_the_persons_configuration(self):
        config = self.root / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('web_search = "disabled"\n\n[mcp_servers.mine]\ncommand = "my-server"\n', encoding="utf-8")
        plan = plan_connections(TOOLS, ["github/github-local", "linear"], "codex", token_env={"linear": "LINEAR_API_KEY"})
        apply_connections(self.root, self.state, "codex", plan)
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(parsed["web_search"], "disabled")
        self.assertEqual(set(parsed["mcp_servers"]), {"mine", "github-local", "linear-remote"})
        self.assertEqual(parsed["mcp_servers"]["github-local"]["env_vars"], ["GITHUB_PERSONAL_ACCESS_TOKEN"])
        first = config.read_text(encoding="utf-8")
        apply_connections(self.root, self.state, "codex", plan)
        self.assertEqual(config.read_text(encoding="utf-8"), first)
        remove_connections(self.root, self.state, "codex", ["github", "linear"])
        self.assertEqual(config.read_text(encoding="utf-8"), 'web_search = "disabled"\n\n[mcp_servers.mine]\ncommand = "my-server"\n')
        config.write_text(first + '\n[mcp_servers.linear-remote]\ncommand = "x"\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_connections(self.root, self.state, "codex", plan)

    def test_applied_read_only_headers_are_preserved_in_both_host_formats(self):
        for host, header_key in (("codex", "http_headers"), ("claude-code", "headers")):
            plan = plan_connections(TOOLS, ["Azure-DevOps"], host, read_only=True,
                                    settings={"Azure-DevOps": {"organization": "my-organization"}})
            self.assertEqual(plan[0]["entry"][header_key], {"X-MCP-Readonly": "true"})
            apply_connections(self.root, self.state, host, plan)
        self.assertTrue(all(item["configured"] for item in connection_status(self.root, self.state)))

    def test_applied_read_only_environment_preserves_credential_references(self):
        target = "mailchimp/mailchimp-marketing-local"
        server_id = "mailchimp-marketing-local"
        for host in ("codex", "claude-code"):
            plan = plan_connections(TOOLS, [target], host, community=True, read_only=True)
            apply_connections(self.root, self.state, host, plan)
        config = (self.root / ".codex" / "config.toml").read_text(encoding="utf-8")
        codex = tomllib.loads(config)["mcp_servers"][server_id]
        self.assertEqual(codex["env"], {"MAILCHIMP_READ_ONLY": "true"})
        self.assertEqual(codex["env_vars"], ["MAILCHIMP_API_KEY"])
        config = (self.root / ".mcp.json").read_text(encoding="utf-8")
        claude = json.loads(config)["mcpServers"][server_id]
        self.assertEqual(claude["env"], {
            "MAILCHIMP_READ_ONLY": "true", "MAILCHIMP_API_KEY": "${MAILCHIMP_API_KEY}",
        })
        quickbooks = plan_connections(TOOLS, ["quickbooks"], "codex", read_only=True)[0]
        self.assertEqual(quickbooks["entry"]["env"], {
            "QUICKBOOKS_DISABLE_WRITE": "true", "QUICKBOOKS_DISABLE_UPDATE": "true",
            "QUICKBOOKS_DISABLE_DELETE": "true",
        })

    def test_missing_settings_block_the_write(self):
        with self.assertRaisesRegex(ValueError, "Settings are missing"):
            apply_connections(self.root, self.state, "claude-code", plan_connections(TOOLS, ["zendesk"], "claude-code"))
        self.assertFalse((self.root / ".mcp.json").exists())

    def test_status_reports_drift_and_variables_missing_on_this_workstation(self):
        apply_connections(self.root, self.state, "claude-code", plan_connections(TOOLS, ["github/github-local"], "claude-code"))
        status = connection_status(self.root, self.state, environment={})
        self.assertEqual((status[0]["configured"], status[0]["missing_env"]), (True, ["GITHUB_PERSONAL_ACCESS_TOKEN"]))
        self.assertEqual(connection_status(self.root, self.state, environment={"GITHUB_PERSONAL_ACCESS_TOKEN": "x"})[0]["missing_env"], [])
        (self.root / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
        self.assertFalse(connection_status(self.root, self.state, environment={})[0]["configured"])

    def test_nothing_written_holds_a_secret_value(self):
        for host in ("claude-code", "codex"):
            wanted = [tool_id for tool_id, tool in TOOLS.items() if choose_server(tool) and not choose_server(tool).get("settings")]
            apply_connections(self.root, self.state, host, plan_connections(TOOLS, wanted, host))
        for path in (self.root / ".mcp.json", self.root / ".codex" / "config.toml", self.state / "tools.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?i)(password|secret)\s*[\"']?\s*[:=]\s*[\"'][^$\"']", path.name)
            for value in re.findall(r"Bearer ([^\"]+)", text):
                self.assertRegex(value, r"^\$\{[A-Z0-9_]+\}$")
        tomllib.loads((self.root / ".codex" / "config.toml").read_text(encoding="utf-8"))


class CommandTests(unittest.TestCase):
    def test_list_show_and_call_work_without_a_project(self):
        with tempfile.TemporaryDirectory() as directory:
            code, out, _ = run("--project", directory, "tools", "list", "--category", "time-tracking")
            self.assertEqual(code, 0)
            self.assertIn("gryzzly", out)
            self.assertIn("no MCP server", out)
            code, out, _ = run("--project", directory, "tools", "show", "snyk")
            self.assertIn("Verified 2026-11-21 on https://", out)
            code, _, err = run("--project", directory, "tools", "show", "nope")
            self.assertEqual(code, 1)
            self.assertIn("Unknown tool", err)

    def test_applying_live_connections_can_be_confirmed_in_the_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            answers = root / "profile.json"
            answers.write_text(json.dumps({"name": "Portal", "host": "claude-code"}), encoding="utf-8")
            self.assertEqual(run("--project", root, "init", "--answers", answers)[0], 0)
            apply = ("--project", root, "tools", "apply", "Sentry")
            config = root / ".mcp.json"
            for response, expected in (("no\n", 1), ("yes\n", 0)):
                stdin = io.StringIO(response)
                with patching.patch("sys.stdin", stdin), patching.patch.object(stdin, "isatty", return_value=True):
                    code, plan, prompt = run(*apply)
                self.assertEqual(code, expected, prompt)
                self.assertIn("Type yes", prompt)
                self.assertIn("Covers:", plan)
                self.assertEqual(config.exists(), expected == 0)

            stdin = io.StringIO("yes\n")
            with patching.patch("sys.stdin", stdin), patching.patch.object(stdin, "isatty", return_value=True):
                code, output, prompt = run(*apply, "--json")
            self.assertEqual(code, 0, prompt)
            self.assertEqual(json.loads(output)["applied"], ["sentry-remote"])
            self.assertIn("Covers:", prompt)
            self.assertIn("Type yes", prompt)

    def test_call_lists_a_mocks_tools_and_answers_one_call(self):
        with tempfile.TemporaryDirectory() as directory:
            code, out, _ = run("--project", directory, "tools", "call", "jira")
            self.assertEqual(code, 0)
            self.assertRegex(out, r"search_issues\s+\[read\]")
            self.assertRegex(out, r"create_issue\s+\[write\]")
            code, out, _ = run("--project", directory, "tools", "call", "jira", "search_issues", "--args", '{"query": "export"}')
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["issues"][0]["key"], "SUP-142")
            code, out, _ = run("--project", directory, "tools", "call", "jira", "get_issue", "--args", '{"key": "NOPE-1"}')
            self.assertEqual(code, 1)
            self.assertIn("not found", out)
            self.assertIn("Known key values: SUP-120, SUP-142, SUP-143", out)
            code, _, err = run("--project", directory, "tools", "call", "jira", "search_issues", "--args", "{not json")
            self.assertEqual(code, 1)
            self.assertIn("--args is not valid JSON", err)
            code, out, err = run("--project", directory, "tools", "call", "hubspot", "create_note",
                                 "--args", '{"deal_id": "deal-1", "body": "Synthetic note"}')
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["body"], "Synthetic note")
            self.assertIn("openguildkit task authorize", err)

    def test_every_bundled_mock_loads_and_names_a_registry_tool(self):
        ids = mock_ids()
        self.assertGreaterEqual(len(ids), 15)
        for tool_id in ids:
            self.assertIn(tool_id, TOOLS, tool_id)
            mock = load_mock(tool_id)
            text = json.dumps(mock)
            for address in re.findall(r"[\w.+-]+@[\w.-]+", text):
                self.assertTrue(address.endswith("example.test"), f"{tool_id}: {address}")



def answer(tool_id: str, name: str, arguments: dict, mock: dict | None = None) -> dict:
    result = call_tool(mock or load_mock(tool_id), name, arguments)
    return {"error": result["isError"], "text": result["content"][0]["text"], "data": result.get("structuredContent")}


class MockDataTests(unittest.TestCase):
    """Mocks whose arguments can be found, whose ids agree, and whose data a project can replace."""

    def test_the_listing_gives_each_argument_its_type_whether_required_and_an_example_that_works(self):
        with tempfile.TemporaryDirectory() as directory:
            code, out, _ = run("--project", directory, "tools", "call", "google-analytics")
        self.assertEqual(code, 0)
        self.assertIn("Arguments: page_path (string, required), metric (string: page_views|users, optional)", out)
        self.assertIn("Example: openguildkit tools call google-analytics run_report --args '{\"page_path\": \"/requests\"}'", out)
        self.assertIn("Generic sample data, not your project's", out)
        self.assertIn("Every record: --args '{\"query\": \"\"}'", run("tools", "call", "jira")[1])
        for tool_id in mock_ids():
            mock = load_mock(tool_id)
            listing = "\n".join(describe(mock))
            for tool in mock["tools"]:
                self.assertIn(f"{tool['name']}  [", listing, tool_id)
                self.assertFalse(answer(tool_id, tool["name"], example_arguments(mock, tool), mock)["error"], f"{tool_id}/{tool['name']}")

    def test_a_missing_or_unknown_argument_names_the_arguments_and_an_example(self):
        with tempfile.TemporaryDirectory() as directory:
            code, out, err = run("--project", directory, "tools", "call", "google-analytics", "run_report", "--args", "{}")
            self.assertEqual(code, 1)
            self.assertIn("Missing argument: page_path. run_report takes: page_path (string, required)", out)
            self.assertIn("Example: openguildkit tools call google-analytics run_report", err)
            code, out, err = run("--project", directory, "tools", "call", "jira", "search_issues", "--args", '{"query": "x", "text": "x"}')
            self.assertIn("Unknown argument: text. search_issues takes: query (string, required)", out)
            self.assertIn("Example:", err)

    def test_every_id_a_list_returns_is_accepted_by_the_get_tools_of_the_same_mock(self):
        walked = 0
        for tool_id in mock_ids():
            mock = load_mock(tool_id)
            self.assertEqual(reference_problems(mock), [], tool_id)
            gets = [tool for tool in mock["tools"] if tool.get("serve", {}).get("action") == "get"]
            for listing in (tool for tool in mock["tools"] if tool.get("serve", {}).get("action") == "list"):
                result = answer(tool_id, listing["name"], list_all_arguments(listing), mock)
                self.assertFalse(result["error"], f"{tool_id}/{listing['name']}")
                rows = result["data"][listing["serve"]["records"]]
                self.assertEqual(len(rows), len(mock["records"][listing["serve"]["records"]]["items"]), f"{tool_id}/{listing['name']}")
                for get in gets:
                    key = mock["records"][get["serve"]["records"]]["key"]
                    argument = get["serve"].get("argument", key)
                    for row in rows:
                        value = row.get(key) if get["serve"]["records"] == listing["serve"]["records"] else None
                        if value is None:
                            continue
                        walked += 1
                        self.assertFalse(answer(tool_id, get["name"], {argument: value}, mock)["error"],
                                         f"{tool_id}: {listing['name']} returns {key} {value}, {get['name']} refuses it")
        self.assertGreater(walked, 20)
        self.assertFalse(answer("zendesk", "get_ticket", {"ticket_id": 4104})["error"])
        self.assertFalse(answer("figma", "get_node", {"node_id": "1:2"})["error"])

    def test_a_search_ignores_case_and_finds_part_of_a_name(self):
        for query in ("Logistics", "logistics", "LOGIST", "example logistics"):
            deals = answer("hubspot", "search_deals", {"query": query})["data"]["deals"]
            self.assertEqual([deal["deal_id"] for deal in deals], ["deal-1"], query)
        self.assertEqual(answer("jira", "search_issues", {"query": "CSV export"})["data"]["issues"][0]["key"], "SUP-142")
        self.assertEqual(answer("jira", "search_issues", {"query": "", "status": "Blocked"})["data"]["issues"][0]["key"], "SUP-120")

    def test_an_empty_result_says_the_data_is_generic_and_how_to_list_everything(self):
        empty = answer("jira", "search_issues", {"query": "permit"})["data"]
        self.assertEqual(empty["issues"], [])
        self.assertIn("generic sample data", empty["hint"])
        self.assertIn('search_issues {"query": ""} lists every record', empty["hint"])
        self.assertIn("Export my requests as CSV", empty["hint"])
        self.assertIn("Known severity values: high.", answer("github", "list_security_alerts", {"severity": "low"})["data"]["hint"])

    def test_the_stripe_mock_rehearses_a_refund(self):
        arguments = {"invoice_id": "in_test_001", "amount_cents": 5000, "reason": "duplicate"}
        refund = answer("stripe", "create_refund", arguments)
        self.assertFalse(refund["error"])
        self.assertEqual((refund["data"]["invoice_id"], refund["data"]["amount_cents"]), ("in_test_001", 5000))
        other = answer("stripe", "create_refund", {**arguments, "amount_cents": 4000})["data"]["refund_id"]
        self.assertNotEqual(refund["data"]["refund_id"], other)
        self.assertEqual(answer("stripe", "create_refund", arguments)["data"]["refund_id"], refund["data"]["refund_id"])
        for change, message in (({"amount_cents": -5}, "must be at least 1"), ({"amount_cents": 99999999}, "exceeds the amount_cents"),
                                ({"invoice_id": "in_test_002"}, "needs status paid"), ({"invoice_id": "in_nope"}, "not found")):
            refused = answer("stripe", "create_refund", {**arguments, **change})
            self.assertTrue(refused["error"], change)
            self.assertIn(message, refused["text"])
        self.assertEqual(answer("stripe", "list_refunds", {"invoice_id": "in_test_001"})["data"]["count"], 1)

    def test_a_projects_scenario_replaces_the_bundled_records_and_stays_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            scenario = {"about": "Ours", "records": {"hubspot": {
                "deals": [{"deal_id": "d-1", "name": "Riverside Clinic: booking pilot", "company_id": "c-1"}],
                "companies": [{"company_id": "c-1", "name": "Riverside Clinic", "contact": "desk@example.test"}]}}}
            (folder / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
            mock = load_mock("hubspot", folder)
            self.assertNotIn("scenario", mock_ids(folder))
            self.assertEqual(answer("hubspot", "search_deals", {"query": "booking"}, mock)["data"]["deals"][0]["deal_id"], "d-1")
            self.assertFalse(answer("hubspot", "get_company", {"company_id": "C-1"}, mock)["error"])
            self.assertIn("project's scenario", answer("hubspot", "search_deals", {"query": "zzz"}, mock)["data"]["hint"])
            self.assertEqual(load_mock("jira", folder)["records"]["issues"]["items"][0]["key"], "SUP-142")
            for change, message in (
                ({"deals": [{"deal_id": "d-1", "name": "x", "company_id": "c-9"}]}, "c-9, which companies does not hold"),
                ({"companies": [{"company_id": "c-1", "contact": "real.person@gmail.com"}]}, "not a test address"),
                ({"leads": []}, "no collection leads"),
                ({"deals": [{"name": "no id"}]}, "unique deal_id"),
            ):
                (folder / "scenario.json").write_text(json.dumps({"records": {"hubspot": change}}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    load_mock("hubspot", folder)

    def test_a_starting_scenario_keeps_the_bundled_records_and_adds_one_tracker_record_for_the_task(self):
        brief = "Let patients book an appointment online.\nMore."
        scenario = scenario_records(["jira", "stripe"], "Clinic booking", TOOLS, "booking", brief)
        issues = scenario["records"]["jira"]["issues"]
        self.assertEqual((issues[0]["key"], issues[0]["summary"], issues[0]["task"]),
                         ("BOOKING-1", "Let patients book an appointment online", "booking"))
        self.assertEqual(issues[0]["description"], brief.strip())
        self.assertEqual(issues[1:], load_mock("jira")["records"]["issues"]["items"])
        self.assertEqual(scenario["records"]["stripe"]["customers"], load_mock("stripe")["records"]["customers"]["items"])
        self.assertNotIn("appointment", json.dumps(scenario["records"]["stripe"]))
        self.assertIn("Clinic booking", scenario["about"])
        self.assertIn("replace them with records that tell your project's story", scenario["about"])
        self.assertEqual(scenario_records(["jira"], "Clinic", TOOLS)["records"]["jira"]["issues"],
                         load_mock("jira")["records"]["issues"]["items"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"name": "Clinic booking", "host": "codex", "tools": ["Jira", "Zendesk", "Gryzzly"]}),
                                         encoding="utf-8")
            self.assertEqual(run("--project", directory, "init", "--answers", root / "a.json")[0], 0)
            self.assertEqual(run("--project", directory, "task", "new", brief, "--id", "booking")[0], 0)
            code, out, _ = run("--project", directory, "tools", "scenario", "--task", "booking")
            self.assertEqual(code, 0, out)
            self.assertIn("for jira, zendesk", out)
            self.assertIn("one jira record for the task", out)
            self.assertIn("Replace them with records that tell your project's story, synthetic values only", out)
            self.assertIn("    zendesk: tickets (ticket_id, subject, status)", out)
            written = json.loads((root / ".openguildkit" / "catalog" / "tool-mocks" / "scenario.json").read_text(encoding="utf-8"))
            self.assertEqual(set(written["records"]), {"jira", "zendesk"})
            code, out, _ = run("--project", directory, "tools", "call", "Jira", "get_issue", "--args", '{"key": "booking-1"}')
            self.assertEqual(json.loads(out)["task"], "booking")
            code, _, err = run("--project", directory, "tools", "scenario", "jira")
            self.assertEqual(code, 1)
            self.assertIn("--force", err)
            self.assertEqual(run("--project", directory, "tools", "scenario", "jira", "--force")[0], 0)


class ReviewPlanTests(unittest.TestCase):
    """What a security officer needs to accept a real server, from the publisher or marked missing."""

    def test_every_docker_server_forwards_each_variable_it_declares(self):
        for tool in TOOLS.values():
            for server in tool["servers"]:
                if server.get("command") == "docker":
                    args = server["args"]
                    forwarded = {args[index + 1] for index, arg in enumerate(args[:-1]) if arg == "-e"}
                    self.assertLessEqual(set(server["env"]), forwarded, f"{tool['id']}/{server['id']}")
        entry = plan_connections(TOOLS, ["sonarqube"], "codex")[0]["entry"]
        self.assertIn("SONARQUBE_URL", entry["args"][entry["args"].index("sonarsource/sonarqube-mcp") - 1])
        local = copy.deepcopy(TOOL)
        local["servers"][0] = {
            **{key: value for key, value in REMOTE.items() if key != "url"}, "transport": "stdio", "command": "docker",
            "args": ["run", "-i", "-e", "ACME_TOKEN", "acme/mcp"], "package": {"registry": "docker", "name": "acme/mcp"},
            "env": ["ACME_TOKEN", "ACME_URL"],
        }
        with self.assertRaisesRegex(CatalogError, "add -e ACME_URL"):
            _validate_tool(local, "testing")

    def test_every_live_plan_names_publisher_access_scopes_version_credentials_and_alternatives(self):
        wanted = [tool_id for tool_id, tool in TOOLS.items() if choose_server(tool)]
        for item in plan_connections(TOOLS, wanted, "claude-code"):
            if "skipped" in item:
                continue
            review = item["review"]
            for key in ("publisher", "status", "covers", "access", "scopes", "read_only", "version", "credentials"):
                self.assertTrue(review[key], f"{item['key']}: {key}")
        teams = plan_connections(TOOLS, ["microsoft-teams"], "claude-code")[0]["review"]
        self.assertIn("tenant-wide admin consent", teams["scopes"])
        self.assertEqual(teams["read_only"], NOT_DOCUMENTED + " (looked for on 2026-11-21)")
        self.assertTrue(any(line.startswith("microsoft-teams/work-iq-cli") for line in teams["alternatives"]))
        sonar = plan_connections(TOOLS, ["sonarqube"], "codex")[0]["review"]
        self.assertIn("without a tag: the documented command pulls latest at every start", sonar["version"])
        self.assertIn("SONARQUBE_URL", sonar["credentials"])
        self.assertIn("pinned by tag", plan_connections(TOOLS, ["terraform/terraform-mcp-server"], "codex")[0]["review"]["version"])
        self.assertIn("no version to pin", plan_connections(TOOLS, ["jira"], "codex")[0]["review"]["version"])
        google = plan_connections(TOOLS, ["google-workspace"], "codex")[0]["review"]
        self.assertEqual(len([line for line in google["alternatives"] if line.startswith("google-workspace/")]), 3)
        self.assertIn("gmail.modify", google["scopes"])
        self.assertIn("Transactional email (Mandrill) only", plan_connections(TOOLS, ["mailchimp"], "codex", token_env={"mailchimp": "MANDRILL_KEY"})[0]["review"]["covers"])

    def test_not_documented_is_said_only_where_the_page_was_read(self):
        reviewed = {tool_id for tool_id, tool in TOOLS.items() for server in tool["servers"] if "reviewed" in server}
        self.assertLessEqual({"github", "jira", "slack", "notion", "linear", "sentry", "snyk", "stripe", "hubspot", "figma",
                              "datadog", "zendesk", "sonarqube", "microsoft-teams", "google-workspace", "mailchimp"}, reviewed)
        for tool in TOOLS.values():
            for server in tool["servers"]:
                if "reviewed" in server:
                    self.assertEqual(server["verified"], server["reviewed"], server["id"])
        # Obscura's access is recorded, its scopes are not, and nobody read its page for them.
        obscura = plan_connections(TOOLS, ["obscura"], "codex")[0]["review"]
        self.assertEqual(obscura["scopes"], "not recorded in the registry yet: read https://github.com/h4ckf0r0day/obscura")
        self.assertNotIn(NOT_DOCUMENTED, json.dumps(obscura))
        slack = plan_connections(TOOLS, ["slack"], "codex", read_only=True)[0]
        self.assertIn("chat:write", slack["review"]["scopes"])
        self.assertTrue(slack["review"]["read_only"].startswith(NOT_DOCUMENTED))
        github = plan_connections(TOOLS, ["github"], "claude-code", read_only=True)[0]
        self.assertEqual(github["entry"]["url"], "https://api.githubcopilot.com/mcp/readonly")
        linear = plan_connections(TOOLS, ["linear"], "codex", read_only=True)[0]
        self.assertEqual(linear["entry"]["url"], "https://mcp.linear.app/mcp/readonly")
        warned = plan_connections(TOOLS, ["obscura"], "codex", read_only=True)[0]["warnings"]
        self.assertTrue(any("recorded in the registry yet" in warning for warning in warned))

    def test_read_only_mode_is_shown_and_selected_when_the_publisher_documents_one(self):
        azure = plan_connections(TOOLS, ["azure-devops"], "claude-code", settings={"azure-devops": {"organization": "acme"}},
                                 read_only=True)[0]
        self.assertEqual(azure["entry"]["headers"], {"X-MCP-Readonly": "true"})
        self.assertTrue(azure["read_only"])
        codex = plan_connections(TOOLS, ["azure-devops"], "codex", settings={"azure-devops": {"organization": "acme"}},
                                 read_only=True)[0]
        self.assertEqual(codex["entry"]["http_headers"], {"X-MCP-Readonly": "true"})
        sonar = plan_connections(TOOLS, ["sonarqube"], "codex", read_only=True)[0]["entry"]["args"]
        self.assertIn("SONARQUBE_READ_ONLY=true", sonar)
        self.assertNotIn("SONARQUBE_READ_ONLY=true", plan_connections(TOOLS, ["sonarqube"], "codex")[0]["entry"]["args"])
        teams = plan_connections(TOOLS, ["microsoft-teams"], "codex", read_only=True)[0]
        self.assertFalse(teams["read_only"])
        self.assertTrue(any("No read-only mode is documented" in warning for warning in teams["warnings"]))
        tool = copy.deepcopy(TOOL)
        tool["servers"][0]["read_only"] = {"how": "Header.", "headers": {"Authorization": "x"}}
        with self.assertRaisesRegex(CatalogError, "never a credential"):
            _validate_tool(tool, "testing")

    def test_tool_names_are_accepted_whatever_their_case(self):
        self.assertEqual(plan_connections(TOOLS, ["Notion", "JIRA", "GitHub/GitHub-Local"], "codex")[2]["key"], "github-local")
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.json").write_text(json.dumps({"name": "x", "host": "codex"}), encoding="utf-8")
            run("--project", directory, "init", "--answers", Path(directory) / "a.json")
            code, out, _ = run("--project", directory, "tools", "plan", "Notion", "SonarQube", "--read-only")
            self.assertEqual(code, 0)
            self.assertIn("notion: server `notion-remote`", out)
            self.assertIn("Read-only mode: not documented by the publisher (looked for on 2026-11-21)", out)
            self.assertIn("Read-only mode selected: SONARQUBE_READ_ONLY=true", out)
            self.assertIn("Alternatives: The API without MCP: https://", run("--project", directory, "tools", "plan", "obscura")[1])
            self.assertEqual(run("--project", directory, "tools", "show", "Notion")[0], 0)

    def test_applying_a_live_server_needs_a_yes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"name": "x", "host": "claude-code"}), encoding="utf-8")
            run("--project", directory, "init", "--answers", root / "a.json")
            with patching.patch("sys.stdin", io.StringIO("")):
                code, _, err = run("--project", directory, "tools", "apply", "sentry")
            self.assertEqual(code, 1)
            self.assertIn("--yes", err)
            self.assertFalse((root / ".mcp.json").exists())
            terminal = io.StringIO("")
            terminal.isatty = lambda: True
            with patching.patch("sys.stdin", terminal), patching.patch("builtins.input", return_value="n"):
                code, out, err = run("--project", directory, "tools", "apply", "sentry")
            self.assertEqual(code, 1)
            self.assertIn("Access:", out)
            self.assertIn("not accepted", err)
            self.assertFalse((root / ".mcp.json").exists())
            with patching.patch("sys.stdin", terminal), patching.patch("builtins.input", return_value="y"):
                self.assertEqual(run("--project", directory, "tools", "apply", "sentry")[0], 0)
            self.assertIn("sentry-remote", (root / ".mcp.json").read_text(encoding="utf-8"))
            with patching.patch("sys.stdin", io.StringIO("")):
                self.assertEqual(run("--project", directory, "tools", "apply", "jira", "--yes")[0], 0)
                self.assertEqual(run("--project", directory, "tools", "apply", "jira", "--mock")[0], 0)



class ApplyOutcomeTests(unittest.TestCase):
    """What apply connected, what it could not, and an exit status a script can test."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        (self.root / "a.json").write_text(json.dumps({"name": "x", "host": "codex"}), encoding="utf-8")
        run("--project", self.root, "init", "--answers", self.root / "a.json")

    def apply(self, *args: str) -> tuple[int, str, str]:
        with patching.patch("sys.stdin", io.StringIO("")):
            return run("--project", self.root, "tools", "apply", *args)

    def test_the_exit_status_tells_all_connected_some_connected_and_none_connected(self):
        self.assertEqual(self.apply("jira", "--mock")[0], 0)
        code, out, _ = self.apply("jira", "gryzzly", "--mock")
        self.assertEqual(code, 2)
        self.assertEqual(out.splitlines()[-1], "Connected mocks: jira. Tools without a mock: gryzzly.")
        code, out, _ = self.apply("lucca", "--mock")
        self.assertEqual(code, 1)
        self.assertIn("Nothing written to .codex/config.toml", out)
        self.assertEqual(out.splitlines()[-1], "Connected mocks: none. Tools without a mock: lucca.")

    def test_a_tool_without_an_mcp_server_is_reported_and_kept_in_status(self):
        code, out, _ = self.apply("gryzzly", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("gryzzly: skipped. It has no MCP server on record.", out)
        self.assertEqual(out.splitlines()[-1], "Connected servers: none. Tools not connected: gryzzly.")
        code, out, _ = self.apply("jira", "gryzzly", "--yes")
        self.assertEqual(code, 2)
        status = json.loads(run("--project", self.root, "tools", "status", "--json")[1])
        unconnected = next(item for item in status if item["key"] == "gryzzly")
        self.assertEqual((unconnected["mode"], unconnected["configured"]), ("live", False))
        self.assertIn("no MCP server", unconnected["reason"])
        self.assertIn("gryzzly                  codex        live  not connected.", run("--project", self.root, "tools", "status")[1])

    def test_the_plan_ends_with_the_apply_command_to_paste(self):
        code, _, err = run("--project", self.root, "tools", "plan", "github/github-local", "zendesk", "--set", "zendesk.subdomain=acme",
                           "--read-only", "--community")
        self.assertEqual(code, 0)
        self.assertIn("    openguildkit tools apply github/github-local zendesk --host codex --community --read-only "
                      "--set zendesk.subdomain=acme\n", err)
        code, _, err = run("--project", self.root, "tools", "plan", "jira", "--mock", "--log", "my calls.jsonl", "--host", "claude-code")
        self.assertIn('openguildkit tools apply jira --host claude-code --mock --log "my calls.jsonl"', err)



class MockEvidenceTests(unittest.TestCase):
    """Evidence read from a mock is labelled as synthetic in the approval prompt, the decision brief and the record."""

    def test_an_approved_decision_that_cites_a_mock_says_so_everywhere(self):
        from openguildkit.storage import write_json
        example = Path(__file__).resolve().parents[1] / "examples" / "request-status"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "profile.json", {"name": "Support portal", "stack": ["Python"], "packs": [], "host": "codex"})
            run("--project", root, "init", "--answers", root / "profile.json")
            self.assertEqual(run("--project", root, "tools", "apply", "jira", "--mock")[0], 0)
            run("--project", root, "task", "new", "--file", example / "brief.md", "--id", "status")
            answers = {**json.loads((example / "answers.json").read_text(encoding="utf-8")), "outcome": "Customers see status."}
            write_json(root / "answers.json", answers)
            run("--project", root, "task", "consult", "status", "--answers", root / "answers.json")
            template = json.loads(run("--project", root, "task", "template", "status")[1])
            review = {"consultation_id": template["consultation_id"], **json.loads((example / "review.json").read_text(encoding="utf-8"))}
            product = next(entry for entry in review["boards"] if entry["id"] == "product")
            product["evidence"].append({"source": "tool", "ref": "jira:SUP-142", "supports": "The request is tracked."})
            write_json(root / "review.json", review)
            code, _, err = run("--project", root, "task", "review", "status", "--file", root / "review.json")
            self.assertEqual(code, 0, err)
            self.assertIn("comes from the jira mock, synthetic sample data", err)
            line = "Mock data: 1 evidence item(s) come from mock tools, synthetic sample data and not the real systems: " \
                   f"product #{len(product['evidence'])} jira:SUP-142."
            self.assertIn(line, run("--project", root, "task", "challenge", "status")[1])
            with patching.patch("sys.stdin.isatty", return_value=True), patching.patch("builtins.input", return_value="status"):
                code, _, prompt = run("--project", root, "task", "decide", "status", "--approve", "--by", "Camille", "--reason", "Agreed")
            self.assertEqual(code, 0, prompt)
            self.assertIn(line, prompt)
            self.assertEqual(run("--project", root, "task", "export", "status")[0], 0)
            record = json.loads((root / ".openguildkit" / "decisions" / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(record["mock_evidence"], [f"product #{len(product['evidence'])} jira:SUP-142"])



class MockWriteAndApplyDetailTests(unittest.TestCase):
    """Writes over MCP say nothing changed and are marked in the journal; smaller apply and remove details."""

    def test_a_write_over_mcp_says_nothing_changed_and_is_marked_in_the_journal(self):
        from openguildkit.mcp_mock import serve
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "calls.jsonl"
            calls = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
                     for name, arguments in (("create_note", {"deal_id": "deal-1", "body": "x"}),
                                             ("search_deals", {"query": "renewal"}))]
            out = io.BytesIO()
            serve(load_mock("hubspot"), io.BytesIO("".join(json.dumps(c) + "\n" for c in calls).encode("utf-8")), out, journal)
            write, read = [json.loads(line)["result"] for line in out.getvalue().decode("utf-8").splitlines()]
            self.assertIn("nothing was changed anywhere", write["content"][1]["text"])
            self.assertIn("task authorize", write["content"][1]["text"])
            self.assertEqual(len(read["content"]), 1)
            logged = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([item.get("write") for item in logged], [True, None])
        self.assertIn("must be an integer", answer("zendesk", "get_ticket", {"ticket_id": "4101"})["text"])

    def test_plan_apply_remove_and_recommend_details(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"name": "x", "host": "codex", "tools": ["Jira"]}), encoding="utf-8")
            run("--project", root, "init", "--answers", root / "a.json")
            code, _, err = run("--project", root, "tools", "plan", "kubernetes")
            self.assertEqual(code, 0)
            self.assertIn("nothing in this plan can be connected", err)
            self.assertNotIn("tools apply", err)
            code, _, err = run("--project", root, "tools", "plan", "jira", "kubernetes")
            self.assertIn("    openguildkit tools apply jira --host codex\n", err)
            with patching.patch("sys.stdin", io.StringIO("")):
                code, _, err = run("--project", root, "tools", "apply", "github", "--read-only")
            self.assertEqual(code, 1)
            self.assertIn("then write it with: openguildkit tools apply github --host codex --read-only --yes", err)
            code, out, _ = run("--project", root, "tools", "apply", "jira", "--mock", "--log", "calls.jsonl")
            self.assertIn("recorded it in", out)
            code, _, err = run("--project", root, "tools", "apply", "Jira", "--mock")
            self.assertIn("Kept the journal calls.jsonl", err)
            config = tomllib.loads((root / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(config["mcp_servers"]["jira"]["args"][-2:], ["--log", "calls.jsonl"])
            self.assertEqual(run("--project", root, "tools", "apply", "lucca", "--mock")[0], 1)
            code, out, _ = run("--project", root, "tools", "apply", "snyk", "--mock")
            self.assertEqual(code, 0)
            self.assertIn("Still not connected from earlier requests: lucca", out)
            code, out, _ = run("--project", root, "tools", "recommend")
            self.assertIn("lucca                requested for codex (mock), not connected: No mock", out)
            recommended = json.loads(run("--project", root, "tools", "recommend", "--json")[1])
            self.assertEqual(recommended["requested_not_connected"][0]["id"], "lucca")
            code, out, _ = run("--project", root, "tools", "remove", "JIRA", "Lucca")
            self.assertEqual(code, 0)
            self.assertIn("Removed jira", out)
            self.assertIn("Cleared the unconnected requests for lucca", out)



class PolishTests(unittest.TestCase):
    """Last field points: more key shapes, hints without values, variable names, unknown tools, mock state."""

    def test_other_vendors_key_shapes_are_refused_as_settings(self):
        for value in ("gl" + "pat-" + "k" * 20, "AI" + "za" + "m" * 35, "sk" + "-ant-" + "n" * 40, "xo" + "xe-" + "7" * 16):
            with self.subTest(value=value[:6]), self.assertRaisesRegex(ValueError, "never a credential"):
                plan_connections(TOOLS, ["zendesk"], "claude-code", settings={"zendesk": {"subdomain": value}})

    def test_a_hint_never_repeats_a_credential_shaped_setting(self):
        import argparse
        from openguildkit.tools_cli import _apply_command
        secret = "gl" + "pat-" + "k" * 20
        args = argparse.Namespace(tool=["zendesk"], mock=False, community=False, read_only=False, log=None,
                                  settings=[f"zendesk.subdomain={secret}", "zendesk.region=eu"], token_env=[])
        command = _apply_command(args, "codex", [], TOOLS)
        self.assertNotIn(secret, command)
        self.assertIn("--set zendesk.subdomain=VALUE --set zendesk.region=eu", command)

    def test_a_lowercase_variable_name_is_accepted_for_a_bearer_token(self):
        item = plan_connections(TOOLS, ["linear"], "codex", token_env={"linear": "linear_token"})[0]
        self.assertEqual(item["entry"]["bearer_token_env_var"], "linear_token")
        with self.assertRaisesRegex(ValueError, "names an environment variable"):
            plan_connections(TOOLS, ["linear"], "codex", token_env={"linear": "1linear"})

    def test_an_unknown_tool_is_left_unconnected_and_the_others_connect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"name": "x", "host": "codex", "tools": ["Jira", "Steam"]}), encoding="utf-8")
            run("--project", root, "init", "--answers", root / "a.json")
            code, out, err = run("--project", root, "tools", "apply", "jira", "steam", "--mock")
            self.assertEqual(code, 2, err)
            self.assertEqual(out.splitlines()[-1], "Connected mocks: jira. Tools without a mock: steam.")
            status = json.loads(run("--project", root, "tools", "status", "--json")[1])
            steam = next(item for item in status if item["key"] == "steam")
            self.assertIn("Not in the registry", steam["reason"])
            code, _, err = run("--project", root, "tools", "plan", "jira", "Steam")
            self.assertEqual(code, 0)
            self.assertIn("    openguildkit tools apply jira --host codex\n", err)

    def test_a_deliverable_input_without_data_is_worded_plainly(self):
        from openguildkit.deliverables import launch_notice
        lines = launch_notice({"inputs": [{"label": "Campaign name", "data": "none"},
                                          {"label": "Audience", "data": "personal"}], "tool_actions": []})
        self.assertEqual(lines, ["Campaign name (no sensitive data)", "Audience (personal data)"])

    def test_a_simulated_write_says_the_mock_keeps_nothing(self):
        created = call_tool(load_mock("stripe"), "create_refund",
                            {"invoice_id": "in_test_001", "amount_cents": 500, "reason": "duplicate"})
        self.assertIn("the mock keeps nothing: later calls will not show this record", created["content"][1]["text"])
        self.assertEqual(answer("stripe", "list_refunds", {"invoice_id": "in_test_001"})["data"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
