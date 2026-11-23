"""The task journey reads the same in AGENTS.md, the skill and both READMEs, up to the closing, and the skill carries
the market and dependency procedures for the hosts that install no agent file (issue 42).

Each document writes in full, with `openguildkit`, the commands a step runs; a command named in passing is written
`task ACTION`. Only the commands of the journey below are compared; reading commands such as `task brief` are not.
"""

import argparse
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import command_parser
from openguildkit.storage import write_json
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "src" / "openguildkit" / "agent_files" / "skills" / "openguildkit" / "SKILL.md"
AGENTS = REPO / "src" / "openguildkit" / "agent_files" / "agents"
JOURNEY = {
    "scope": {"new", "questions", "route", "consult"},
    "consult": {"pass", "submit", "progress", "review", "deliberate", "respond", "challenge"},
    "decide": {"blockers", "clear", "decide", "revoke"},
    "deliver": {"handoff", "verify", "result", "complete", "export"},
}
COMMAND = re.compile(r"openguildkit task ([a-z-]+)")


def commands(text: str) -> set[str]:
    return set(COMMAND.findall(text)) & set().union(*JOURNEY.values())


def numbered(text: str, marker: str) -> dict[int, str]:
    """The text of each numbered step, by number: marker is the pattern of a step's first line before its number."""
    parts = re.split(rf"^{marker}(\d)\. ", text, flags=re.M)
    return {int(number): body for number, body in zip(parts[1::2], parts[2::2])}


def section(text: str, heading: str) -> str:
    start = text.index(heading + "\n")
    following = text.find("\n## ", start + len(heading))
    return text[start:following if following > 0 else len(text)]


def agents_steps(text: str) -> dict[str, str]:
    steps = numbered(section(text, "## OpenGuildKit task workflow"), "")
    return {"scope": steps[1], "consult": steps[2], "decide": steps[3], "deliver": steps[4]}


def skill_steps(text: str) -> dict[str, str]:
    steps = numbered(section(text, "## Task"), "### ")
    return {"scope": steps[1], "consult": steps[2] + steps[3], "decide": steps[4], "deliver": steps[5]}


def readme_steps(text: str, heading: str) -> dict[str, str]:
    steps = numbered(section(text, heading), r"\*\*")
    return {"scope": steps[1], "consult": steps[2], "decide": steps[3], "deliver": steps[4]}


def limits(text: str, start: str) -> list[str]:
    """The bullets of the list after the line start."""
    bullets = []
    for line in text[text.index(start + "\n") + len(start):].splitlines():
        if line.startswith("- "):
            bullets.append(line[2:])
        elif line.strip() and bullets:
            break
    return bullets


class JourneyTests(unittest.TestCase):
    def generated_agents(self) -> str:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "setup.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
            run_cli(root, "init", "--answers", root / "setup.json")
            return (root / "AGENTS.md").read_text(encoding="utf-8")

    def documents(self) -> dict[str, dict[str, str]]:
        return {
            "AGENTS.md": agents_steps(self.generated_agents()),
            "SKILL.md": skill_steps(SKILL.read_text(encoding="utf-8")),
            "README.md": readme_steps((REPO / "README.md").read_text(encoding="utf-8"),
                                      "## A task from request to closing"),
            "README.fr.md": readme_steps((REPO / "README.fr.md").read_text(encoding="utf-8"),
                                         "## Le parcours d'une tâche"),
        }

    def test_each_step_names_the_same_commands_in_agents_md_the_skill_and_the_readmes(self):
        for name, steps in self.documents().items():
            for step, expected in JOURNEY.items():
                with self.subTest(document=name, step=step):
                    self.assertEqual(commands(steps[step]), expected)

    def test_the_agents_md_workflow_runs_the_passes_and_goes_on_to_the_closing(self):
        block = section(self.generated_agents(), "## OpenGuildKit task workflow")
        for words in ("openguildkit task pass ID BOARD", "openguildkit task submit ID --file ENTRY",
                      "openguildkit task review ID --summary TEXT", "openguildkit task verify ID",
                      "openguildkit task result ID --file FILE", "openguildkit task complete ID",
                      "openguildkit task export ID"):
            self.assertIn(words, block)
        self.assertNotIn("task review ID --file", block)
        self.assertNotIn("task template", block)
        decision = block[block.index("A task of kind `decision`"):]
        self.assertIn("close it with `openguildkit task complete ID`", " ".join(decision.split()))

    def test_the_task_help_and_the_workflow_chart_go_on_to_the_closing(self):
        commands_parser = next(action for action in command_parser()._actions if isinstance(action, argparse._SubParsersAction))
        help_text = next(action.help for action in commands_parser._choices_actions if action.dest == "task")
        for words in ("consult", "decision", "verify", "complete", "export"):
            self.assertIn(words, help_text)
        chart = (REPO / "docs" / "workflow.md").read_text(encoding="utf-8").split("```mermaid", 1)[1].split("```")[0]
        for words in ("task pass", "task submit", "task review", "task decide", "task handoff", "task verify",
                      "task result", "task complete", "task export", "task revoke"):
            self.assertIn(words, chart)


class AgentProcedureTests(unittest.TestCase):
    def test_the_skill_carries_the_limits_of_the_market_and_dependency_agents(self):
        skill = SKILL.read_text(encoding="utf-8")
        for agent, heading in (("market-analyst", "## Market dossiers"), ("dependency-watch", "## Dependency alerts")):
            with self.subTest(agent=agent):
                text = (AGENTS / f"{agent}.md").read_text(encoding="utf-8")
                expected = limits(text, "## Limits")
                self.assertGreaterEqual(len(expected), 5)
                self.assertEqual(limits(section(skill, heading), "Limits:"), expected)
                self.assertIn(section(text, "## Steps").split("\n", 2)[2].strip(), section(skill, heading))

    def test_the_limits_keep_the_research_and_alert_rules(self):
        market = " ".join(limits((AGENTS / "market-analyst.md").read_text(encoding="utf-8"), "## Limits"))
        for words in ("`local-only`", "Do not search", "no login, no form", "behind a login, a paywall or a form",
                      "no personal data", "never edit the JSON"):
            self.assertIn(words, market)
        watch = " ".join(limits((AGENTS / "dependency-watch.md").read_text(encoding="utf-8"), "## Limits"))
        for words in ("never dismiss a critical alert", "Never run `openguildkit alerts accept`",
                      "only after the task is approved"):
            self.assertIn(words, watch)


if __name__ == "__main__":
    unittest.main()
