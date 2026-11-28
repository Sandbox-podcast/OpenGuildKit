"""Features: a team turns a tool, or one of its three best-known alternatives, on or off, with who and why."""

import argparse
import json
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import CatalogError
from openguildkit.cli import command_parser
from openguildkit.features import _feature, load_features
from openguildkit.storage import write_json
from openguildkit.tool_registry import load_tools
from tests.support import run_cli

DAY = {"SOURCE_DATE_EPOCH": "1795219200"}  # 2026-11-21
ASKED = ("documentalist", "jira", "confluence", "microsoft-teams", "payfit", "gryzzly", "factorial", "slack", "github",
         "docker-hub", "portainer", "npm", "keycloak", "jetbrains", "grafana", "kibana", "gravitee", "dynatrace",
         "chrome-devtools", "apache-spark")


class FeatureCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_tools()

    def test_every_feature_has_a_lead_and_three_other_tools_of_the_registry(self):
        features = load_features(self.tools)
        self.assertEqual(sorted(ASKED), sorted(feature["id"] for feature in features))
        for feature in features:
            tools = [option["tool"] for option in feature["options"]]
            self.assertEqual(len(set(tools)), 4, feature["id"])
            self.assertTrue(set(tools) <= self.tools.keys(), feature["id"])

    def test_a_feature_names_exactly_three_distinct_alternatives_of_the_registry(self):
        record = {"id": "chat", "purpose": "Chat", "lead": {"tool": "slack"},
                  "alternatives": [{"tool": "discord"}, {"tool": "mattermost"}]}
        with self.assertRaisesRegex(CatalogError, "exactly 3 alternatives"):
            _feature(record, self.tools)
        record["alternatives"].append({"tool": "slack"})
        with self.assertRaisesRegex(CatalogError, "different tools"):
            _feature(record, self.tools)
        record["alternatives"][-1] = {"tool": "no-such-tool"}
        with self.assertRaisesRegex(CatalogError, "not a tool of the registry"):
            _feature(record, self.tools)


class FeatureCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"],
                                                "tools": ["Jira Cloud"]})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def run_cli(self, *arguments, code=0):
        result = run_cli(self.root, *arguments, expect=code, env=DAY)
        return result.stdout, result.stderr

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def on(self) -> dict[str, list[str]]:
        view = json.loads(self.run_cli("features", "list", "--json")[0])
        return {feature["id"]: [option["tool"] for option in feature["options"] if option["enabled"]] for feature in view}

    def test_a_tool_the_team_already_named_shows_its_feature_on(self):
        self.assertEqual(self.on()["jira"], ["jira"])
        self.assertEqual(self.on()["gryzzly"], [])

    def test_enabling_adds_the_tool_to_the_profile_with_who_when_and_why(self):
        output, _ = self.run_cli("features", "enable", "kibana", "Harvest", "--by", "Camille", "--reason", "Logs, time")
        self.assertIn("Profile changed: features enable kibana, Harvest, by Camille on 2026-11-21", output)
        self.assertIn("openguildkit tools plan elastic, then", output)
        self.assertEqual(self.profile()["tools"], ["Jira Cloud", "Elastic", "Harvest"])
        self.assertEqual(self.profile()["changes"][-1]["reason"], "Logs, time")
        self.assertEqual(self.on()["kibana"], ["elastic"])
        self.assertEqual(self.on()["gryzzly"], ["harvest"])

    def test_disabling_removes_every_name_that_resolves_to_the_tool(self):
        self.run_cli("features", "disable", "jira", "--by", "Camille", "--reason", "We moved to Linear")
        self.assertNotIn("tools", self.profile())
        _, error = self.run_cli("features", "disable", "jira", "--by", "Camille", "--reason", "Again", code=1)
        # OGK-FEATURE-002
        self.assertIn("jira is not on. Nothing was written.", error)

    def test_shared_github_is_listed_in_each_use_and_cannot_be_disabled_from_a_feature(self):
        # OGK-FEATURE-003
        self.run_cli("features", "enable", "github", "--by", "Camille", "--reason", "Source control")
        uses = [feature for feature, tools in self.on().items() if "github" in tools]
        self.assertGreaterEqual(len(uses), 3)
        before = self.profile()
        _, error = self.run_cli("features", "disable", "github", "--by", "Camille", "--reason", "Packages", code=1)
        for feature in uses:
            self.assertIn(feature, error)
        self.assertEqual(self.profile(), before)

    def test_a_tool_outside_the_features_goes_through_profile_add_tool(self):
        # OGK-FEATURE-001
        _, error = self.run_cli("features", "enable", "figma", "--by", "Camille", "--reason", "Design", code=1)
        self.assertIn("openguildkit profile add tool", error)
        _, error = self.run_cli("features", "enable", "jira", "--by", "Camille", "--reason", "Again", code=1)
        self.assertIn("jira is already on", error)
        self.assertEqual(self.profile()["tools"], ["Jira Cloud"])



def reason_help(*path: str) -> str:
    """The help of --reason for a command, such as ("features", "enable")."""
    parser = command_parser()
    for name in path:
        commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
        parser = commands.choices[name]
    return next(action.help for action in parser._actions if "--reason" in action.option_strings)


class FeatureReasonTests(unittest.TestCase):
    """The reason of a features or profile change goes where the help says (#336)."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"],
                                                "tools": ["Jira Cloud"]})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def run_cli(self, *arguments, code=0):
        result = run_cli(self.root, *arguments, expect=code, env=DAY)
        return result.stdout, result.stderr

    def test_the_reason_of_a_tool_or_a_setting_stays_in_the_profile_history(self):
        self.run_cli("features", "enable", "linear", "--by", "CM", "--reason", "Try Linear")
        self.run_cli("profile", "add", "tool", "Figma", "--by", "CM", "--reason", "Design files")
        history = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))["changes"]
        self.assertEqual([change["reason"] for change in history[-2:]], ["Try Linear", "Design files"])
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        preview, _ = self.run_cli("preview")
        for reason in ("Try Linear", "Design files"):
            with self.subTest(reason=reason):
                self.assertNotIn(reason, agents)
                self.assertNotIn(reason, preview)
        for path in (("features", "enable"), ("features", "disable"), ("profile", "add"), ("profile", "remove"),
                     ("profile", "set")):
            with self.subTest(command=" ".join(path)):
                self.assertIn("profile history", reason_help(*path))
                self.assertNotIn("AGENTS.md", reason_help(*path))
                self.assertNotIn("preview", reason_help(*path))

    def test_the_reason_of_an_adopted_or_declined_pattern_also_shows_in_agents_md_and_preview(self):
        # tests/test_profile_commands.py holds where these reasons show.
        for action in ("adopt", "decline"):
            with self.subTest(action=action):
                self.assertIn("profile history", reason_help("profile", action))
                self.assertIn("AGENTS.md and preview", reason_help("profile", action))



class FeatureConnectionTests(unittest.TestCase):
    """What follows a features change: the connection tools apply wrote, and tools plan only for a tool with a server
    (#337)."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"],
                                                "host": "claude-code", "tools": ["Jira Cloud"]})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def run_cli(self, *arguments, code=0):
        result = run_cli(self.root, *arguments, expect=code, env=DAY)
        return result.stdout, result.stderr

    def test_disabling_a_connected_tool_names_each_connection_and_the_command_that_removes_it(self):
        self.run_cli("tools", "apply", "jira", "--mock")
        self.run_cli("tools", "apply", "jira", "--mock", "--host", "codex")
        output, _ = self.run_cli("features", "disable", "jira", "--by", "CM", "--reason", "We moved to Linear")
        self.assertIn("The MCP server jira stays connected (claude-code, mock, .mcp.json): the agent keeps access to "
                      "Jira. To remove the connection: openguildkit tools remove jira.", output)
        self.assertIn("The MCP server jira stays connected (codex, mock, .codex/config.toml): the agent keeps access "
                      "to Jira. To remove the connection: openguildkit tools remove jira --host codex.", output)
        for command in re.findall(r"To remove the connection: openguildkit (tools remove [^\n]+)\.$", output, re.M):
            self.run_cli(*command.split())
        self.assertEqual(json.loads(self.run_cli("tools", "status", "--json")[0]), [])

    def test_disabling_a_tool_that_is_not_connected_names_no_connection(self):
        output, _ = self.run_cli("features", "disable", "jira", "--by", "CM", "--reason", "We moved to Linear")
        self.assertNotIn("stays connected", output)
        self.assertNotIn("tools remove", output)

    def test_enabling_proposes_tools_plan_only_for_a_tool_with_an_mcp_server(self):
        output, _ = self.run_cli("features", "enable", "payfit", "--by", "CM", "--reason", "Payroll")
        self.assertNotIn("tools plan", output)
        self.assertIn("payfit: no MCP server on record, so there is nothing to connect.", output)
        output, _ = self.run_cli("features", "enable", "kibana", "Harvest", "--by", "CM", "--reason", "Logs, time")
        self.assertIn("To connect the MCP servers: openguildkit tools plan elastic, then tools apply", output)
        self.assertIn("harvest: no MCP server on record", output)


if __name__ == "__main__":
    unittest.main()
