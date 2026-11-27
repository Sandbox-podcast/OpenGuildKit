"""The module map, the fast check, the pass budget and a local transcript total."""

import importlib.util
import inspect
import io
import json
import re
import subprocess
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
            "scripts/install.sh",
            "docs/not-a-module.md",
        ], module_map)
        self.assertIn("tests/test_results.py", selected["tests"])
        self.assertIn("tests/test_guard.py", selected["tests"])
        self.assertIn("tests/test_agent_native.py", selected["tests"])
        self.assertIn("tests/test_integrations.py", selected["tests"])
        self.assertIn("tests/test_product_docs.py", selected["tests"])
        self.assertEqual(selected["commands"], ["catalog", "web-typecheck", "node-tests"])
        self.assertNotIn("tests/test_deleted_example.py", selected["tests"])
        self.assertIn("tests/test_workflows.py", selected["tests"])
        self.assertIn("tests/test_install_script.py", selected["tests"])
        self.assertEqual(selected["unattached"], ["integrations/chaosfolk/README.md"])

    def test_documentation_workflow_script_and_coordinator_changes_each_have_a_test(self):
        module_map = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))
        scripts = {
            "scripts/check_links.py": "tests/test_check_links.py",
            "scripts/watch_editions.py": "tests/test_edition_watch.py",
            "scripts/coverage.py": "tests/test_coverage.py",
            "scripts/bench.py": "tests/test_performance.py",
        }
        for script, test in scripts.items():
            self.assertEqual(check_fast.plan([script], module_map),
                             {"tests": [test], "commands": [], "unattached": []}, script)
        documents = {
            "README.md": "tests/test_release.py",
            "CHANGELOG.md": "tests/test_release.py",
            "pyproject.toml": "tests/test_release.py",
            "docs/install.md": "tests/test_product_docs.py",
            ".github/workflows/ci.yml": "tests/test_workflows.py",
            "examples/export-expiry/project.json": "tests/test_doc_promises.py",
        }
        for path, test in documents.items():
            selected = check_fast.plan([path], module_map)
            self.assertEqual(selected["unattached"], [], path)
            self.assertIn(test, selected["tests"], path)
        self.assertEqual(check_fast.plan(["integrations/ci/lib/watch.mjs"], module_map),
                         {"tests": [], "commands": ["node-tests"], "unattached": []})
        listed = [path.relative_to(REPO).as_posix() for folder in ("docs", ".github", "examples", "integrations/ci")
                  for path in (REPO / folder).rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts and "node_modules" not in path.parts]
        self.assertEqual(check_fast.plan(listed, module_map)["unattached"], [])

    def test_a_pull_request_that_touches_a_script_the_readme_and_a_workflow_has_no_unattached_file(self):
        module_map = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        files = ("scripts/check_links.py", "README.md", ".github/workflows/ci.yml")
        for name in files:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text("first\n", encoding="utf-8")
        git = ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
               "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        for name in files:
            with (root / name).open("a", encoding="utf-8") as handle:
                handle.write("# touch\n")
        changed = check_fast.changed_files(root, "HEAD")
        self.assertEqual(sorted(changed), sorted(files))
        selected = check_fast.plan(changed, module_map)
        self.assertEqual(selected["unattached"], [])
        for test in ("tests/test_check_links.py", "tests/test_release.py", "tests/test_workflows.py"):
            self.assertIn(test, selected["tests"])

    def test_a_changed_module_with_only_removed_tests_is_unattached(self):
        module_map = {"modules": [{
            "module": "src/openguildkit/results.py",
            "tests": ["tests/test_deleted_example.py"],
            "covers": ["integrations/mapped/"],
        }]}
        changed = ["src/openguildkit/results.py", "integrations/mapped/sample.md"]
        self.assertEqual(check_fast.plan(changed, module_map),
                         {"tests": [], "commands": [], "unattached": changed})


class RootInstructionsTests(unittest.TestCase):
    """AGENTS.md is what an agent reads first: short, and every path and command in it exists."""

    def test_agents_md_stays_under_four_kilobytes_and_claude_md_imports_it(self):
        self.assertLessEqual(len((REPO / "AGENTS.md").read_bytes()), 4096)
        self.assertEqual((REPO / "CLAUDE.md").read_text(encoding="utf-8"), "@AGENTS.md\n")

    def test_every_path_and_test_module_agents_md_names_exists(self):
        text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        built = {"web/dist", "src/openguildkit/web_dist"}
        paths = [path for path in re.findall(r"`((?:src|scripts|tests|docs|web|integrations)/[\w./-]+)`", text)
                 if path not in built]
        modules = re.findall(r"\b(tests\.test_\w+)\b", text)
        self.assertGreater(len(paths), 5)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((REPO / path.split(" ")[0]).exists(), path)
        for module in modules:
            with self.subTest(module=module):
                self.assertTrue((REPO / (module.replace(".", "/") + ".py")).is_file(), module)
        for script in re.findall(r"python (scripts/\w+\.py)", text):
            with self.subTest(script=script):
                self.assertIn(script, check_fast.EXTRA)

    def test_each_convention_has_a_rule_a_reason_a_check_and_an_issue(self):
        text = (REPO / "docs" / "agents" / "conventions.md").read_text(encoding="utf-8")
        sections = re.split(r"^### ", text, flags=re.M)[1:]
        ids = [section.split("\n", 1)[0].strip().strip("`") for section in sections]
        self.assertGreaterEqual(len(ids), 20)
        self.assertEqual(len(ids), len(set(ids)))
        for identifier, section in zip(ids, sections):
            with self.subTest(convention=identifier):
                self.assertRegex(identifier, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                for field in ("**Rule.**", "**Why.**", "**Check.**", "**Today.**"):
                    self.assertIn(field, section)
                self.assertRegex(section, r"#\d+")


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
