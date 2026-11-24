"""Features: a team turns a tool, or one of its three best-known alternatives, on or off, with who and why."""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import CatalogError
from openguildkit.features import _feature, load_features
from openguildkit.storage import write_json
from openguildkit.tools import load_tools
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
        self.assertIn("openguildkit tools plan elastic harvest", output)
        self.assertEqual(self.profile()["tools"], ["Jira Cloud", "Elastic", "Harvest"])
        self.assertEqual(self.profile()["changes"][-1]["reason"], "Logs, time")
        self.assertEqual(self.on()["kibana"], ["elastic"])
        self.assertEqual(self.on()["gryzzly"], ["harvest"])

    def test_disabling_removes_every_name_that_resolves_to_the_tool(self):
        self.run_cli("features", "disable", "jira", "--by", "Camille", "--reason", "We moved to Linear")
        self.assertNotIn("tools", self.profile())
        _, error = self.run_cli("features", "disable", "jira", "--by", "Camille", "--reason", "Again", code=1)
        self.assertIn("jira is not on. Nothing was written.", error)

    def test_a_tool_outside_the_features_goes_through_profile_add_tool(self):
        _, error = self.run_cli("features", "enable", "figma", "--by", "Camille", "--reason", "Design", code=1)
        self.assertIn("openguildkit profile add tool", error)
        _, error = self.run_cli("features", "enable", "jira", "--by", "Camille", "--reason", "Again", code=1)
        self.assertIn("jira is already on", error)
        self.assertEqual(self.profile()["tools"], ["Jira Cloud"])


if __name__ == "__main__":
    unittest.main()
