"""The module map, the fast check, the pass budget and a local transcript total."""

import importlib
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
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


def _git(root, *args):
    command = ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
               "-c", "commit.gpgsign=false", *args]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def _commit(root, files, message):
    """Write the files (None deletes one) in a repository under root, commit them and return the commit."""
    for name, text in files.items():
        if text is None:
            (root / name).unlink()
            continue
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").strip()


def _repository(case):
    """A temporary repository whose first commit is `main`, with a copy of each script under scripts/."""
    temporary = tempfile.TemporaryDirectory()
    case.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    _git(root, "init", "-q", "-b", "main")
    return root


def _run_script(root, name, *args, env=None):
    """Run a copy of scripts/NAME.py placed in root, so that the script reads the repository under root."""
    (root / "scripts").mkdir(exist_ok=True)
    shutil.copy(REPO / "scripts" / f"{name}.py", root / "scripts" / f"{name}.py")
    return subprocess.run([sys.executable, str(root / "scripts" / f"{name}.py"), *args], cwd=root, check=False,
                          capture_output=True, text=True, env={**os.environ, "PR_BODY": "", "PR_TITLE": "", **(env or {})})


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


class SuppressionTests(unittest.TestCase):
    """A suppression of a check says on its line that it is intended, and why (intent-markers-on-suppressions)."""

    # Written in pieces so that this file does not match its own search.
    SUPPRESSIONS = re.compile("|".join(("no" + "qa", "type: " + "ignore", "eslint-" + "disable",
                                        "@ts-" + "ignore", "@ts-" + "expect-error")))
    MARKER = re.compile(r"INTENTIONAL\(#\d+\): \S")
    FOLDERS = ("src", "tests", "scripts", "web/src", "web/tests", "web/scripts", "integrations/ci")
    SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
    SKIPPED = {"node_modules", "__pycache__", "dist", "web_dist"}

    def test_every_suppression_carries_an_intent_marker_with_its_reason(self):
        found = 0
        missing = []
        for folder in self.FOLDERS:
            for path in sorted((REPO / folder).rglob("*")):
                if path.suffix not in self.SUFFIXES or self.SKIPPED & set(path.parts) or not path.is_file():
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    if self.SUPPRESSIONS.search(line):
                        found += 1
                        if not self.MARKER.search(line):
                            missing.append(f"{path.relative_to(REPO).as_posix()}:{number}")
        self.assertGreaterEqual(found, 24)
        self.assertEqual(missing, [])


class OracleTests(unittest.TestCase):
    """protected-oracle-diff: an assertion a branch removes while it changes src/ is listed in the pull request."""

    TEST_BEFORE = (
        "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n"
        "        self.assertEqual(f(), 2)\n        self.assertTrue(g())\n"
    )
    TEST_AFTER = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertTrue(g())\n"

    def setUp(self):
        self.root = _repository(self)
        _commit(self.root, {"src/mod.py": "def f():\n    return 2\n", "tests/test_mod.py": self.TEST_BEFORE,
                            "web/tests/page.test.ts": "expect(a).toBe(1);\nexpect(b).toBe(2);\n"}, "base")
        _git(self.root, "branch", "base")

    def test_a_removed_assertion_next_to_a_change_of_src_must_be_listed(self):
        _commit(self.root, {"src/mod.py": "def f():\n    return 3\n", "tests/test_mod.py": self.TEST_AFTER}, "weaken")
        result = _run_script(self.root, "check_oracle", "--base", "base")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("tests/test_mod.py: self.assertEqual(f(), 2)", result.stdout)
        self.assertNotIn("assertTrue", result.stdout)
        listed = "## What\n\nx\n\n## Assertions changed\n\n- `self.assertEqual(f(),   2)` became 3.\n\n## Not verified\n\nnothing\n"
        result = _run_script(self.root, "check_oracle", "--base", "base", env={"PR_BODY": listed})
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_an_assertion_of_a_web_test_is_read_as_well(self):
        _commit(self.root, {"src/mod.py": "def f():\n    return 3\n", "web/tests/page.test.ts": "expect(a).toBe(1);\n"}, "weaken")
        result = _run_script(self.root, "check_oracle", "--base", "base")
        self.assertEqual(result.returncode, 1)
        self.assertIn("web/tests/page.test.ts: expect(b).toBe(2);", result.stdout)

    def test_nothing_is_asked_without_a_change_of_src_or_for_a_moved_or_added_assertion(self):
        _commit(self.root, {"tests/test_mod.py": self.TEST_AFTER}, "tests only")
        self.assertEqual(_run_script(self.root, "check_oracle", "--base", "base").returncode, 0)
        _git(self.root, "checkout", "-q", "-B", "second", "base")
        moved = self.TEST_AFTER + "    def test_b(self):\n        self.assertEqual(f(),    2)\n"
        _commit(self.root, {"src/mod.py": "def f():\n    return 2  # x\n", "tests/test_mod.py": moved}, "move")
        self.assertEqual(_run_script(self.root, "check_oracle", "--base", "base").returncode, 0)


class PullRequestTextTests(unittest.TestCase):
    """not-verified-section: the pull request says what was not run, or `nothing`."""

    def test_the_not_verified_section_must_exist_and_say_something(self):
        check = _load("check_pr_text")
        template = (REPO / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        self.assertIn("## Not verified", template)
        self.assertTrue(check.problems("Title", template), "the empty template must be refused")
        ok = "## What changes\n\nx\n\n## Not verified\n\nThe Windows run.\n\n## Assertions changed\n\nnone\n"
        self.assertEqual(check.problems("Title", ok), [])
        self.assertEqual(check.problems("Title", "## Not verified\n\nnothing"), [])
        for body in ("", "## What changes\n\nx", "## Not verified\n\n<!-- say it -->\n\n## Other\n\ntext",
                     "## Not verified\n   \n"):
            with self.subTest(body=body):
                self.assertEqual(len(check.problems("Title", body)), 1)
                self.assertIn("Not verified", check.problems("Title", body)[0])
        for variable, expected in (("", 1), ("## Not verified\n\nnothing", 0)):
            result = _run_script(_repository(self), "check_pr_text", env={"PR_BODY": variable})
            self.assertEqual(result.returncode, expected, result.stdout)


class FixTraceTests(unittest.TestCase):
    """regression-test-names-issue: a branch that closes a bug has a test that names it and a line in the ledger."""

    def setUp(self):
        self.root = _repository(self)
        _commit(self.root, {"src/mod.py": "x = 1\n", "tests/test_mod.py": "import unittest\n",
                            "docs/agents/fixes.jsonl": ""}, "base")
        _git(self.root, "branch", "base")
        self.test = 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        """Issue #7: the page says 500."""\n'
        self.line = json.dumps({"issue": 7, "symptom": "the page says 500", "cause": "src/mod.py:x",
                                "test": "tests.test_mod.T.test_a", "commit": "abcdef0"}) + "\n"

    def run_check(self, *args, body=""):
        return _run_script(self.root, "check_fix_trace", "--base", "base", *args, env={"PR_BODY": body})

    def test_a_bug_closed_without_a_test_that_names_it_and_a_ledger_line_fails(self):
        _commit(self.root, {"src/mod.py": "x = 2\n"}, "Fix the page (#7)\n\nCloses #7")
        result = self.run_check("--bugs", "7")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn('#7: no test under tests/ names "Issue #7"', result.stdout)
        self.assertIn("#7: no line in docs/agents/fixes.jsonl", result.stdout)

    def test_the_test_and_the_line_make_it_pass_and_another_number_does_not_count(self):
        _commit(self.root, {"src/mod.py": "x = 2\n", "tests/test_mod.py": self.test.replace("#7:", "#70:")},
                "Fix the page (#7)\n\nCloses #7")
        self.assertIn('no test under tests/ names "Issue #7"', self.run_check("--bugs", "7").stdout)
        _commit(self.root, {"tests/test_mod.py": self.test, "docs/agents/fixes.jsonl": self.line}, "Test it")
        result = self.run_check("--bugs", "7")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_only_a_bug_is_asked_and_the_body_of_the_pull_request_counts(self):
        _commit(self.root, {"src/mod.py": "x = 2\n"}, "Add a thing (#8)\n\nCloses #8")
        self.assertEqual(self.run_check("--bugs", "7").returncode, 0)
        self.assertEqual(self.run_check("--bugs", "7", body="Fixes #7 and\nresolves: #8").returncode, 1)
        self.assertEqual(self.run_check("--bugs", "8", body="x").returncode, 1)
        self.assertEqual(self.run_check("--bugs", "").returncode, 0)

    def test_without_a_closing_keyword_nothing_is_asked(self):
        _commit(self.root, {"src/mod.py": "x = 2\n"}, "Part of #7\n\nSee #7, it is not fixed yet")
        self.assertEqual(self.run_check("--bugs", "7").returncode, 0)


class FixLedgerTests(unittest.TestCase):
    """fix-ledger: one line per fixed bug, with the cause and the test that can be found."""

    FIELDS = {"issue": int, "symptom": str, "cause": str, "test": str, "commit": str}

    def setUp(self):
        text = (REPO / "docs" / "agents" / "fixes.jsonl").read_text(encoding="utf-8")
        self.entries = [json.loads(line) for line in text.splitlines()]

    def test_each_line_has_its_five_fields_and_the_fifth_audit_is_all_there(self):
        for entry in self.entries:
            with self.subTest(issue=entry.get("issue")):
                self.assertEqual({name: type(entry.get(name)) for name in self.FIELDS}, self.FIELDS)
                self.assertEqual(set(entry), set(self.FIELDS))
                self.assertTrue(all(entry[name] for name in self.FIELDS))
                self.assertRegex(entry["commit"], r"^[0-9a-f]{7,40}$")
                self.assertRegex(entry["cause"], r"^[\w./-]+:[\w.]+$")
        issues = [entry["issue"] for entry in self.entries]
        self.assertEqual(len(issues), len(set(issues)))
        self.assertEqual(sorted(set(range(377, 408)) - set(issues)), [])

    def test_the_file_of_each_cause_names_the_function_and_each_test_loads(self):
        for entry in self.entries:
            with self.subTest(issue=entry["issue"]):
                path, function = entry["cause"].split(":")
                source = (REPO / path).read_text(encoding="utf-8")
                self.assertRegex(source, rf"\b{re.escape(function.rsplit('.', 1)[-1])}\b", entry["cause"])
                if "::" in entry["test"]:
                    file, title = entry["test"].split("::", 1)
                    self.assertIn(title, (REPO / file).read_text(encoding="utf-8"), entry["test"])
                else:
                    module, owner, name = entry["test"].rsplit(".", 2)
                    self.assertTrue(callable(getattr(getattr(importlib.import_module(module), owner), name)), entry["test"])


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


def _assistant(message_id, model, usage, *, when="2026-11-24T10:00:00.000Z", pieces=None):
    """One transcript line the way Claude Code writes it: one line per content block of a message."""
    return {"type": "assistant", "timestamp": when, "message": {
        "id": message_id, "role": "assistant", "model": model,
        "content": pieces or [{"type": "text", "text": "x"}],
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0, **usage},
    }}


def _write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


class AgentCostTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_totals_leave_the_transcript_text_out(self):
        secret = "secret-transcript-phrase"
        lines = [
            {"type": "assistant", "message": {
                "id": "msg_1", "role": "assistant", "model": "claude-sonnet-x",
                "content": [{"type": "text", "text": secret}],
                "usage": {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 10,
                          "cache_creation_input_tokens": 5},
            }},
            _assistant("msg_2", "claude-sonnet-x", {"input_tokens": 20, "output_tokens": 8},
                       pieces=[{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]),
            {"type": "user", "timestamp": "2026-11-24T10:00:02.500Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": secret},
            ]}},
        ]
        path = self.root / "transcript.jsonl"
        _write_lines(path, lines)
        report = agent_cost.summarise(path, rates={"claude-sonnet": (3.0, 15.0, 0.30, 3.75)})
        self.assertEqual(report["input_tokens"], 120)
        self.assertEqual(report["output_tokens"], 48)
        self.assertEqual(report["cache_read_input_tokens"], 10)
        self.assertEqual(report["cache_creation_input_tokens"], 5)
        self.assertEqual(report["turns"], 2)
        self.assertEqual(report["subagents"], 0)
        self.assertEqual(report["command_wait_seconds"], 2.5)
        expected = (120 * 3.0 + 48 * 15.0 + 10 * 0.30 + 5 * 3.75) / 1_000_000
        self.assertEqual(report["cost_usd"], expected)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(agent_cost.main([str(path)]), 0)
        text = buffer.getvalue()
        self.assertNotIn(secret, text)
        self.assertIn("input_tokens: 120", text)
        self.assertIn("cost_usd:", text)

    def test_issue_485_a_message_written_on_three_lines_counts_once(self):
        """Issue #485: a message that fills three lines of the transcript is counted three times."""
        usage = {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 10,
                 "cache_creation_input_tokens": 5}
        once = self.root / "once.jsonl"
        three = self.root / "three.jsonl"
        _write_lines(once, [_assistant("msg_1", "claude-sonnet-x", usage)])
        pieces = [[{"type": "thinking", "thinking": "a"}], [{"type": "text", "text": "b"}],
                  [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]]
        _write_lines(three, [_assistant("msg_1", "claude-sonnet-x", usage, pieces=piece) for piece in pieces])
        names = (*agent_cost._USAGE, "turns", "cost_usd")
        self.assertEqual({name: agent_cost.summarise(three)[name] for name in names},
                         {name: agent_cost.summarise(once)[name] for name in names})
        self.assertEqual(agent_cost.summarise(three)["turns"], 1)
        # The last line of a message holds its final usage.
        _write_lines(three, [_assistant("msg_1", "claude-sonnet-x", {**usage, "output_tokens": 3}),
                             _assistant("msg_1", "claude-sonnet-x", usage)])
        self.assertEqual(agent_cost.summarise(three)["output_tokens"], 40)

    def test_issue_485_a_session_folder_adds_the_subagent_files(self):
        """Issue #485: the files of subagents/*.jsonl are not read, so `subagents` stays 0."""
        usage = {"input_tokens": 10, "output_tokens": 4}
        for layout in ("sibling", "inside"):
            with self.subTest(layout=layout):
                session = self.root / layout / "session-1"
                main = session.parent / "session-1.jsonl" if layout == "sibling" else session / "main.jsonl"
                _write_lines(main, [_assistant("msg_1", "claude-sonnet-x", usage)])
                _write_lines(session / "subagents" / "agent-a.jsonl", [_assistant("msg_2", "claude-sonnet-x", usage)])
                _write_lines(session / "subagents" / "agent-b.jsonl", [
                    _assistant("msg_3", "claude-sonnet-x", usage), _assistant("msg_4", "claude-sonnet-x", usage)])
                (session / "subagents" / "agent-a.meta.json").write_text("{}", encoding="utf-8")
                report = agent_cost.summarise(session)
                self.assertEqual(report["input_tokens"], 40)
                self.assertEqual(report["turns"], 1)
                self.assertEqual(report["subagents"], 2)
                self.assertEqual(len(report["files"]), 3)
                self.assertEqual(report["files"]["subagents/agent-b.jsonl"]["turns"], 2)
        with self.assertRaises(ValueError):
            agent_cost.summarise(self.root / "absent")

    def test_issue_485_each_model_has_its_rate_and_a_model_without_rate_is_named(self):
        """Issue #485: one rate applies whatever model a line names."""
        rates = {"model-a": (1.0, 2.0, 0.0, 0.0), "model-b": (10.0, 20.0, 0.0, 0.0)}
        path = self.root / "transcript.jsonl"
        _write_lines(path, [
            _assistant("msg_1", "model-a-1", {"input_tokens": 1_000_000}),
            _assistant("msg_2", "model-b-2", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}),
            _assistant("msg_3", "model-c", {"input_tokens": 500}),
            _assistant("msg_4", "<synthetic>", {}),
        ])
        report = agent_cost.summarise(path, rates=rates)
        self.assertEqual(report["cost_usd"], 1.0 + 10.0 + 20.0)
        self.assertEqual(report["unpriced_models"], ["model-c"])
        self.assertEqual(report["models"]["model-a-1"]["cost_usd"], 1.0)
        self.assertIsNone(report["models"]["model-c"]["cost_usd"])
        self.assertEqual(report["input_tokens"], 2_000_500)

    def test_issue_485_the_wait_is_the_gap_between_a_tool_call_and_its_result(self):
        """Issue #485: command_wait_seconds reads a duration_ms that no transcript holds and stays 0."""
        path = self.root / "transcript.jsonl"
        call = [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]
        _write_lines(path, [
            _assistant("msg_1", "model-a", {}, when="2026-11-24T10:00:00.000Z", pieces=call),
            {"type": "user", "timestamp": "2026-11-24T10:00:03.250Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
                {"type": "tool_result", "tool_use_id": "toolu_unknown", "content": "ok"}]}},
        ])
        self.assertEqual(agent_cost.summarise(path)["command_wait_seconds"], 3.25)

    def test_issue_485_an_unreadable_line_is_skipped_and_counted(self):
        """Issue #485: one line that is not an object refuses the whole transcript."""
        secret = "secret-transcript-phrase"
        path = self.root / "transcript.jsonl"
        _write_lines(path, [_assistant("msg_1", "model-a", {"input_tokens": 7})])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(secret + "\n[1, 2]\n")
        report = agent_cost.summarise(path)
        self.assertEqual(report["skipped_lines"], 2)
        self.assertEqual(report["input_tokens"], 7)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(agent_cost.main([str(path), "--json"]), 0)
        printed = json.loads(buffer.getvalue())
        self.assertEqual(printed["skipped_lines"], 2)
        self.assertNotIn(secret, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
