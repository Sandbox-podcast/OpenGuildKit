"""Host settings follow the research policy and keep `.codex/config.toml` valid."""

import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import consultation, hosts
from openguildkit.storage import write_json

from tests.support import CapturedCli

REPO = Path(__file__).resolve().parents[1]

MULTILINE = 'developer_instructions = """\nFollow the plan.\n  [1] run tests\n[2] open a pull request\n"""\n'
TOOLS_BLOCK = (
    "# >>> OpenGuildKit tools (openguildkit tools apply rewrites this block)\n"
    '[mcp_servers.tracker]\ncommand = "tracker-mcp"\n'
    "# <<< OpenGuildKit tools\n"
)


class HostResearchTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / ".codex" / "config.toml"
        self.settings = self.root / ".claude" / "settings.json"

    def init(self, host, config=None):
        if config is not None:
            self.config.parent.mkdir(parents=True, exist_ok=True)
            self.config.write_bytes(config.encode("utf-8"))
        write_json(self.root / "answers.json", {"name": "Portal", "stack": ["Python"], "host": host, "guard": "off"})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def set_research(self, research):
        path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile["research"] = research
        write_json(path, profile)
        self.run_cli("sync")

    def parsed_config(self):
        return tomllib.loads(self.config.read_text(encoding="utf-8"))

    def web_search_lines(self):
        return [line for line in self.config.read_text(encoding="utf-8").splitlines() if line.startswith("web_search")]

    def apply_three_times(self):
        for _ in range(3):
            self.run_cli("host", "apply")
        self.run_cli("check")

    def test_a_file_without_final_newline_and_a_multiline_string_stays_valid(self):
        self.init("codex", '# Team settings\nmodel = "gpt-5"\n' + MULTILINE + '\n[profiles.fast]\nmodel = "small"')
        self.apply_three_times()
        parsed = self.parsed_config()
        self.assertEqual(parsed["web_search"], "disabled")
        self.assertEqual(parsed["developer_instructions"], "Follow the plan.\n  [1] run tests\n[2] open a pull request\n")
        self.assertEqual(parsed["profiles"], {"fast": {"model": "small"}})
        self.assertEqual(len(self.web_search_lines()), 1)
        self.assertTrue(self.config.read_text(encoding="utf-8").startswith("# Team settings\n"))

    def test_a_single_line_file_without_newline_gets_a_separate_line(self):
        self.init("codex", 'model = "gpt-5"')
        self.apply_three_times()
        self.assertEqual(self.parsed_config(), {"model": "gpt-5", "web_search": "disabled"})
        self.assertEqual(len(self.web_search_lines()), 1)

    def test_windows_newlines_are_kept(self):
        self.init("codex", 'model = "gpt-5"\r\n\r\n[profiles.fast]\r\nmodel = "small"\r\n')
        self.apply_three_times()
        text = self.config.read_bytes().decode("utf-8")
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertEqual(self.parsed_config()["web_search"], "disabled")

    def test_the_line_stays_out_of_the_managed_tools_block(self):
        self.init("codex", 'model = "gpt-5"\n' + MULTILINE + TOOLS_BLOCK)
        self.apply_three_times()
        text = self.config.read_text(encoding="utf-8")
        self.assertTrue(text.endswith(TOOLS_BLOCK))
        self.assertEqual(self.parsed_config()["mcp_servers"], {"tracker": {"command": "tracker-mcp"}})
        self.assertEqual(self.parsed_config()["web_search"], "disabled")
        self.assertEqual(len(self.web_search_lines()), 1)

    def test_apply_refuses_to_write_when_the_result_does_not_disable_search(self):
        original = 'model = "gpt-5"\n' + MULTILINE
        self.init("codex", original)
        inside_string = original.index("  [1]")
        with patch.object(hosts, "_top_level_positions", return_value=[inside_string]):
            _, error = self.run_cli("host", "apply", code=1)
        self.assertIn("web_search", error)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_public_sources_lifts_the_claude_code_denies(self):
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps({"permissions": {"deny": ["Read(./.env)"]}}), encoding="utf-8")
        self.init("claude-code")
        self.run_cli("host", "apply")
        self.assertIn("WebSearch", json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["deny"])
        self.set_research("public-sources")
        report, _ = self.run_cli("host", "check", code=1)
        self.assertIn("[missing] Public research stays available", report)
        _, error = self.run_cli("check", code=1)
        self.assertIn("host apply", error)
        self.run_cli("host", "apply")
        deny = json.loads(self.settings.read_text(encoding="utf-8"))["permissions"]["deny"]
        self.assertNotIn("WebSearch", deny)
        self.assertNotIn("WebFetch", deny)
        self.assertIn("Read(./.env)", deny)
        self.assertIn("Bash(openguildkit task decide:*)", deny)
        self.run_cli("check")

    def test_public_sources_lifts_the_codex_line_openguildkit_wrote(self):
        self.init("codex", '# Team settings\nmodel = "gpt-5"\n' + TOOLS_BLOCK)
        self.run_cli("host", "apply")
        self.set_research("public-sources")
        report, _ = self.run_cli("host", "check", code=1)
        self.assertIn("[missing] Public research stays available", report)
        self.run_cli("check", code=1)
        self.run_cli("host", "apply")
        self.assertEqual(self.config.read_text(encoding="utf-8"), '# Team settings\nmodel = "gpt-5"\n' + TOOLS_BLOCK)
        self.run_cli("check")
        self.set_research("local-only")
        self.run_cli("host", "apply")
        self.assertEqual(self.parsed_config()["web_search"], "disabled")

    def test_a_search_setting_written_by_the_team_is_left_to_the_team(self):
        self.init("codex", 'web_search = "disabled"\n')
        self.set_research("public-sources")
        report, _ = self.run_cli("host", "check", code=1)
        self.assertIn("[missing] Public research stays available", report)
        _, error = self.run_cli("host", "apply", code=1)
        self.assertIn('sets web_search = "disabled"', error)
        self.assertEqual(self.config.read_text(encoding="utf-8"), 'web_search = "disabled"\n')


class ResearchDecisionTests(unittest.TestCase):
    """Whether a public search needs a recorded task authorize decision, said once per research policy."""

    def test_the_consultation_says_whether_a_public_search_needs_a_recorded_decision(self):
        scope = {"task_id": "status-page", "brief": "Add a status page.", "answers": {"kind": "feature"},
                 "project": "Example", "sector": "general"}
        public = consultation._consultation_markdown({**scope, "research": "public-sources"}, {}, {})
        local = consultation._consultation_markdown({**scope, "research": "local-only"}, {}, {})
        self.assertIn(consultation.research_decision("public-sources"), public)
        self.assertIn(consultation.research_decision("local-only"), local)
        self.assertIn("needs no task authorize decision", public)
        self.assertIn("task authorize ID --action public-research", local)
        self.assertNotIn("needs no task authorize", local)

    def test_the_skill_says_it_for_every_policy_the_profile_accepts(self):
        skill = (REPO / "src/openguildkit/agent_files/skills/openguildkit/SKILL.md").read_text(encoding="utf-8")
        for policy in ("local-only", "public-sources"):
            self.assertIn(consultation.research_decision(policy), skill)
        with self.assertRaises(ValueError):
            consultation.research_decision("anything")

    def test_the_consultation_says_what_made_a_task_local_only(self):
        self.assertIn("this task's research answer is local", consultation.research_decision("local-only", "local"))
        self.assertIn("unsure", consultation.research_decision("local-only", "unsure"))
        self.assertIn("profile does not allow public sources", consultation.research_decision("local-only", "public"))
        scope = {"task_id": "status-page", "brief": "Add a status page.", "answers": {"kind": "feature", "research": "local"},
                 "project": "Example", "sector": "general", "research": "local-only"}
        self.assertIn("this task's research answer is local", consultation._consultation_markdown(scope, {}, {}))



if __name__ == "__main__":
    unittest.main()
