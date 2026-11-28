"""host scan --allow: the servers, models and provider addresses a list does not name, and a list that cannot be read."""

import json
import socket
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import run_cli
from tests.test_host_scan import fingerprint, write
from tests.test_host_surfaces import SurfaceCase


class AllowListTests(SurfaceCase):
    """Issue #480: a server, a model or an address that no list names was no finding at all."""

    UNKNOWN = {"mcpServers": {"shadow": {"command": "npx", "args": ["-y", "totally-unknown-mcp-server@1.2.3"]},
                              "remote": {"url": "https://mcp.unknown-vendor.example/mcp"}}}
    SETTINGS = {"model": "some-unapproved-model",
                "env": {"ANTHROPIC_BASE_URL": "https://gateway.unknown.example/v1?key=sk-ant-secret-value",
                        "ANTHROPIC_API_KEY": "sk-ant-secret-value"}}

    def allow(self, document) -> Path:
        path = self.root / "policy" / "allow.json"
        write(self.root, "policy/allow.json", json.dumps(document))
        return path

    def scan(self, allow=None, code=None) -> dict:
        arguments = ["--json", *(["--allow", self.allow(allow)] if allow is not None else [])]
        return json.loads(self.cli(*arguments, code=code).stdout)

    def not_allowed(self, result: dict, code: str) -> list[dict]:
        return [item for item in result["findings"] if item["code"] == code]

    def test_a_server_the_list_does_not_name_is_an_error_with_its_name_its_file_and_its_line_and_the_scan_exits_1(self):
        write(self.root, ".mcp.json", '{\n  "mcpServers": {\n    "shadow": {"command": "npx", "args": ["-y", '
                                      '"totally-unknown-mcp-server@1.2.3"]},\n    "remote": {"url": '
                                      '"https://mcp.unknown-vendor.example/mcp"}\n  }\n}\n')
        result = self.scan({"allow": {"mcp_servers": ["npm:@playwright/mcp@1.2.3"]}}, code=1)
        found = self.not_allowed(result, "mcp-not-allowed")
        self.assertEqual([(item["level"], item["path"], item["line"]) for item in found],
                         [("error", ".mcp.json", 3), ("error", ".mcp.json", 4)])
        self.assertIn('"shadow"', found[0]["message"])
        self.assertIn("totally-unknown-mcp-server", found[0]["message"])
        self.assertIn("mcp.unknown-vendor.example", found[1]["message"])
        text = self.cli("--allow", self.root / "policy" / "allow.json", code=1).stdout
        self.assertRegex(text, r"error\s+mcp-not-allowed x2\s+\.mcp\.json:3")

    def test_a_server_is_allowed_by_its_package_with_or_without_a_version_its_image_its_address_or_its_command(self):
        write(self.root, ".mcp.json", json.dumps({"mcpServers": {
            "a": {"command": "npx", "args": ["-y", "pkg@1.2.3"]}, "b": {"command": "uvx", "args": ["other==2.0"]},
            "c": {"command": "docker", "args": ["run", "-i", "ghcr.io/o/image:1.0"]},
            "d": {"url": "https://mcp.example.com/mcp?token=abc"}, "e": {"command": "my-server", "args": ["--stdio"]}}}))
        listed = ["npm:pkg@1.2.3", "pypi:other", "docker:ghcr.io/o/image", "https://mcp.example.com/mcp", "command:my-server"]
        self.assertEqual(self.not_allowed(self.scan({"mcp_servers": listed}), "mcp-not-allowed"), [])
        wrong_version = self.scan({"mcp_servers": ["npm:pkg@1.2.4", *listed[1:]]}, code=1)
        self.assertEqual([item["message"].split('"')[1] for item in self.not_allowed(wrong_version, "mcp-not-allowed")], ["a"])

    def test_the_bare_lists_and_the_block_of_a_policy_read_the_same(self):
        write(self.root, ".mcp.json", json.dumps(self.UNKNOWN))
        wanted = {"mcp_servers": ["npm:totally-unknown-mcp-server"]}
        for document in (wanted, {"allow": wanted}):
            self.assertEqual([item["message"].split('"')[1] for item in
                              self.not_allowed(self.scan(document, code=1), "mcp-not-allowed")], ["remote"])

    def test_without_a_list_the_output_and_the_exit_code_do_not_change(self):
        write(self.root, ".mcp.json", json.dumps(self.UNKNOWN))
        write(self.root, ".claude/settings.json", json.dumps(self.SETTINGS))
        result = self.scan(code=0)
        self.assertEqual({item["code"] for item in result["findings"]}, {"surface-uncovered"})
        self.assertNotIn("not-allowed", json.dumps(result))
        self.assertEqual(self.cli(code=0).stdout.count("not-allowed"), 0)

    def test_an_axis_the_list_does_not_have_is_not_restricted_and_an_empty_one_allows_nothing(self):
        write(self.root, ".mcp.json", json.dumps(self.UNKNOWN))
        write(self.root, ".claude/settings.json", json.dumps(self.SETTINGS))
        only_models = self.scan({"models": ["some-unapproved-model"]}, code=0)
        self.assertEqual(self.not_allowed(only_models, "mcp-not-allowed"), [])
        empty = self.scan({"mcp_servers": [], "models": [], "endpoints": []}, code=1)
        self.assertEqual({item["code"] for item in empty["findings"] if item["level"] == "error"},
                         {"mcp-not-allowed", "model-not-allowed", "endpoint-not-allowed"})

    def test_a_model_and_a_provider_address_outside_the_list_are_errors_that_show_no_value_of_the_environment(self):
        write(self.root, ".claude/settings.json", json.dumps(self.SETTINGS, indent=2))
        result = self.scan({"models": ["claude-sonnet-4-5"], "endpoints": ["https://gateway.company.example"]}, code=1)
        [model] = self.not_allowed(result, "model-not-allowed")
        [endpoint] = self.not_allowed(result, "endpoint-not-allowed")
        self.assertEqual((model["path"], model["line"], endpoint["path"], endpoint["line"]),
                         (".claude/settings.json", 2, ".claude/settings.json", 4))
        self.assertIn("some-unapproved-model", model["message"])
        self.assertIn("gateway.unknown.example", endpoint["message"])
        self.assertNotIn("excerpt", model)
        self.assertNotIn("excerpt", endpoint)
        self.assertNotIn("sk-ant-secret-value", json.dumps(result))
        self.assertNotIn("sk-ant-secret-value", self.cli("--allow", self.root / "policy" / "allow.json", code=1).stdout)

    def test_a_listed_model_and_a_listed_address_or_a_path_below_it_are_allowed(self):
        write(self.root, ".claude/settings.json", json.dumps(self.SETTINGS))
        for listed in ("https://gateway.unknown.example", "https://gateway.unknown.example/v1",
                       "HTTPS://Gateway.Unknown.Example/v1/"):
            with self.subTest(listed=listed):
                result = self.scan({"models": ["some-unapproved-model"], "endpoints": [listed]}, code=0)
                self.assertEqual([item["code"] for item in result["findings"] if item["code"].endswith("not-allowed")], [])
        result = self.scan({"models": [], "endpoints": ["https://gateway.unknown.example/v10"]}, code=1)
        self.assertEqual(len(self.not_allowed(result, "endpoint-not-allowed")), 1)

    def test_codex_model_and_provider_address_are_read_too(self):
        write(self.root, ".codex/config.toml", 'model = "gpt-unlisted"\n\n[model_providers.proxy]\nbase_url = "https://llm.unknown.example/v1"\n')
        result = self.scan({"models": ["gpt-listed"], "endpoints": ["https://llm.company.example"]}, code=1)
        self.assertEqual([item["path"] for item in self.not_allowed(result, "model-not-allowed")], [".codex/config.toml"])
        self.assertEqual([item["path"] for item in self.not_allowed(result, "endpoint-not-allowed")], [".codex/config.toml"])

    def test_a_list_that_cannot_be_read_is_one_line_naming_the_file(self):
        # OGK-GUARD-001
        for document in ("{", "[]", {"mcp_servers": "npm:x"}, {"servers": []}, {"models": [1]}, {"models": [""]}):
            with self.subTest(document=document):
                path = self.root / "policy" / "allow.json"
                write(self.root, "policy/allow.json", document if isinstance(document, str) else json.dumps(document))
                result = self.cli("--allow", path, code=1)
                self.assertEqual(len(result.stderr.strip().splitlines()), 1)
                self.assertIn("allow.json", result.stderr)
        self.assertIn("missing.json", self.cli("--allow", self.root / "policy" / "missing.json", code=1).stderr)

    def test_allow_is_an_option_of_scan_only_and_the_scan_stays_read_only(self):
        write(self.root, ".mcp.json", json.dumps(self.UNKNOWN))
        path = self.allow({"mcp_servers": []})
        for mode in ("check", "apply"):  # host managed takes it too, to write the locks of the hosts (#480)
            with self.subTest(mode=mode):
                self.assertIn("--allow is an option of openguildkit host scan",
                              run_cli(self.root, "host", mode, "--allow", path, expect=1).stderr)
        before = fingerprint(self.root)
        refuse = AssertionError("host scan must not do this")
        with patch.object(socket, "socket", side_effect=refuse), patch.object(subprocess, "Popen", side_effect=refuse):
            self.cli("--allow", path, code=1)
        self.assertEqual(fingerprint(self.root), before)


if __name__ == "__main__":
    unittest.main()
