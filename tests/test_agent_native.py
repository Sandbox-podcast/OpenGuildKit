"""The module map, the fast check, the pass budget and a local transcript total."""

import importlib.util
import inspect
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from openguildkit.consultation import board_brief
from openguildkit.integrations import packaged_file
from openguildkit.storage import write_json

from tests.support import CapturedCli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
BUDGET = (
    'Read only the files named in this brief, then stop. If that is not enough, return verdict '
    '"insufficient-evidence" and name what is still unread.'
)
AGENTS = ("guild-board", "market-analyst", "dependency-watch")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_fast = _load("check_fast")
agent_cost = _load("agent_cost")


def _roles() -> dict[str, str]:
    found = {}
    for line in (REPO / "docs" / "architecture.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| `") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            found[cells[0].strip("`")] = cells[1]
    return found


class MapTests(unittest.TestCase):
    def setUp(self):
        self.map = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))
        self.entries = self.map["modules"]

    def test_every_module_has_one_entry_and_every_test_is_attached(self):
        modules = sorted(path.name for path in (REPO / "src" / "openguildkit").glob("*.py"))
        listed = [item["module"] for item in self.entries]
        self.assertEqual(listed, [f"src/openguildkit/{name}" for name in modules])
        roles = _roles()
        attached = set()
        for item in self.entries:
            name = item["module"].rsplit("/", 1)[-1]
            self.assertEqual(item["role"], roles[name])
            self.assertNotIn("\n", item["role"])
            self.assertTrue(item["role"])
            self.assertTrue(item["tests"], item["module"])
            self.assertIsInstance(item["entry"], list)
            self.assertTrue(all(isinstance(entry, str) and entry for entry in item["entry"]))
            source = (REPO / item["module"]).read_text(encoding="utf-8")
            for entry in item["entry"]:
                if entry == "module":
                    self.assertEqual(name, "__init__.py")
                    continue
                self.assertTrue(
                    f"def {entry}" in source or f"class {entry}" in source or f"{entry} =" in source,
                    item["module"],
                )
            self.assertTrue((REPO / item["doc"]).is_file())
            for test in item["tests"]:
                self.assertTrue((REPO / test).is_file(), test)
                attached.add(test)
            for prefix in item.get("covers", []):
                self.assertFalse(prefix.startswith("/") or ".." in prefix)
        files = sorted(path.relative_to(REPO).as_posix() for path in (REPO / "tests").rglob("test_*.py"))
        self.assertEqual([relative for relative in files if relative not in attached], [])


class CheckFastTests(unittest.TestCase):
    def test_changed_files_select_their_tests_and_an_unattached_file_is_named(self):
        module_map = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))
        selected = check_fast.plan([
            "src/openguildkit/results.py",
            "tests/test_guard.py",
            "src/openguildkit/registry/packs/python.json",
            "web/src/App.tsx",
            "scripts/check_fast.py",
            "integrations/claude-code/agents/guild-board.md",
            "tests/test_deleted_example.py",
            "integrations/ci/package.json",
            "integrations/chaosfolk/README.md",
            "integrations/github/openguildkit-guard.yml",
            "docs/not-a-module.md",
        ], module_map)
        self.assertIn("tests/test_results.py", selected["tests"])
        self.assertIn("tests/test_guard.py", selected["tests"])
        self.assertIn("tests/test_agent_native.py", selected["tests"])
        self.assertIn("tests/test_integrations.py", selected["tests"])
        self.assertEqual(selected["commands"], ["catalog", "web-typecheck"])
        self.assertNotIn("tests/test_deleted_example.py", selected["tests"])
        self.assertEqual(selected["unattached"], [
            "integrations/ci/package.json", "integrations/chaosfolk/README.md",
            "integrations/github/openguildkit-guard.yml", "docs/not-a-module.md",
        ])


    def test_a_changed_module_with_only_removed_tests_is_unattached(self):
        module_map = {"modules": [{
            "module": "src/openguildkit/results.py",
            "tests": ["tests/test_deleted_example.py"],
            "covers": ["examples/mapped/"],
        }]}
        changed = ["src/openguildkit/results.py", "examples/mapped/sample.md"]
        self.assertEqual(check_fast.plan(changed, module_map),
                         {"tests": [], "commands": [], "unattached": changed})


class BudgetTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_the_pass_and_the_agents_stop_when_the_brief_is_not_enough(self):
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")
        self.run_cli("task", "consult", "request-status", "--answers", EXAMPLE / "answers.json")
        record = json.loads(self.run_cli("task", "show", "request-status"))
        board = record["consultation"]["boards"][0]
        self.assertIn(BUDGET, self.run_cli("task", "pass", "request-status", board))
        self.assertIn("Read only the files named in this brief, then stop.", inspect.getsource(board_brief))
        for name in AGENTS:
            self.assertIn(BUDGET, packaged_file(f"agents/{name}.md"))
            copy = REPO / "integrations" / "claude-code" / "agents" / f"{name}.md"
            self.assertIn(BUDGET, copy.read_text(encoding="utf-8"))


class AgentCostTests(unittest.TestCase):
    def test_totals_leave_the_transcript_text_out(self):
        secret = "secret-transcript-phrase"
        lines = [
            {"type": "assistant", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": secret}],
                "usage": {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 10,
                          "cache_creation_input_tokens": 5},
            }},
            {"type": "assistant", "isSidechain": True, "message": {
                "role": "assistant",
                "usage": {"input_tokens": 20, "output_tokens": 8, "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 0},
            }},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": secret, "duration_ms": 2500},
            ]}},
        ]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "transcript.jsonl"
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        report = agent_cost.summarise(path)
        self.assertEqual(report["input_tokens"], 120)
        self.assertEqual(report["output_tokens"], 48)
        self.assertEqual(report["cache_read_input_tokens"], 10)
        self.assertEqual(report["cache_creation_input_tokens"], 5)
        self.assertEqual(report["turns"], 1)
        self.assertEqual(report["subagents"], 1)
        self.assertEqual(report["command_wait_seconds"], 2.5)
        expected = (
            120 * agent_cost.INPUT_USD_PER_MILLION
            + 48 * agent_cost.OUTPUT_USD_PER_MILLION
            + 10 * agent_cost.CACHE_READ_USD_PER_MILLION
            + 5 * agent_cost.CACHE_CREATION_USD_PER_MILLION
        ) / 1_000_000
        self.assertEqual(report["cost_usd"], expected)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(agent_cost.main([str(path)]), 0)
        text = buffer.getvalue()
        self.assertNotIn(secret, text)
        self.assertIn("input_tokens: 120", text)
        self.assertIn("cost_usd:", text)
        broken = Path(temporary.name) / "broken.jsonl"
        broken.write_text(json.dumps(lines[0]) + "\n" + secret + "\n", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            agent_cost.summarise(broken)
        self.assertNotIn(secret, str(caught.exception))
        self.assertRegex(str(caught.exception), re.compile(r"line 2"))


if __name__ == "__main__":
    unittest.main()
