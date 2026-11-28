"""The module map, the fast check, the pass budget and a local transcript total."""

import importlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from openguildkit.board_brief import board_brief
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
build_map = _load("build_map")


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
        # A test of a script is attached by the script's entry of paths (tests/test_agent_cost.py).
        attached |= {test for item in self.map.get("paths", []) for test in item["tests"]}
        files = sorted(path.relative_to(REPO).as_posix() for path in (REPO / "tests").rglob("test_*.py"))
        self.assertEqual([relative for relative in files if relative not in attached], [])

    def test_issue_502_the_committed_map_is_what_build_map_writes(self):
        """Issue #502: the map was kept by hand and missed 76 attachments of a test to a module it imports."""
        text = (REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8")
        built = build_map.build(self.map)
        self.assertEqual(build_map.differences(self.map, built), [], "run python scripts/build_map.py")
        self.assertEqual(build_map.dumps(built), text)
        line = next(line for line in text.splitlines() if '"src/openguildkit/results.py"' in line)
        self.assertEqual(json.loads(line.strip().rstrip(","))["module"], "src/openguildkit/results.py")

    def test_issue_502_a_test_that_imports_a_module_without_being_attached_is_named(self):
        """Issue #502: a test file that imports a module must be among the tests of that module."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        files = {"src/openguildkit/a.py": '"""R."""\n', "src/openguildkit/b.py": '"""R."""\n', "tests/__init__.py": "",
                 "tests/test_a.py": "from openguildkit import a\nfrom openguildkit.b import thing\n",
                 "tests/fixtures/sample.json": "{}", "tests/test_sample.py": "NAME = 'sample.json'\n"}
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        entry = {"role": "R.", "entry": [], "doc": "docs/architecture.md"}
        current = {"modules": [{"module": "src/openguildkit/a.py", **entry, "tests": ["tests/test_a.py"]},
                               {"module": "src/openguildkit/b.py", **entry, "tests": []}]}
        built = build_map.build(current, root)
        found = [line for line in build_map.differences(current, built) if not line.startswith("commands")]
        self.assertEqual(found, ["modules: src/openguildkit/b.py differs in tests",
                                 "paths: tests/fixtures/sample.json is missing"])
        self.assertEqual(built["paths"][0]["tests"], ["tests/test_sample.py"])
        (root / "src" / "openguildkit" / "c.py").write_text("", encoding="utf-8")
        self.assertIn("modules: src/openguildkit/c.py is missing", build_map.differences(built, build_map.build(built, root)))

    def test_issue_502_each_terminal_command_leads_to_its_function(self):
        """Issue #502: no command of the CLI led to the function that runs it."""
        commands = self.map["commands"]
        self.assertEqual([item["command"] for item in commands],
                         [" ".join(words) for words in build_map.terminal_commands()])
        self.assertGreaterEqual(len(commands), 94)
        for item in commands:
            with self.subTest(command=item["command"]):
                lines = (REPO / item["module"]).read_text(encoding="utf-8").splitlines()
                line = lines[item["line"] - 1].strip()
                self.assertTrue(line.startswith((f"def {item['function']}(", "if ", "elif ")), line)

    def test_issue_502_every_tracked_file_has_a_test_or_a_command_and_every_path_entry_exists(self):
        """Issue #502: tests/support.py, SECURITY.md and the fixtures had no test, and the check failed on them."""
        for item in self.map["paths"]:
            with self.subTest(path=item["path"]):
                self.assertTrue((REPO / item["path"]).exists())
                self.assertTrue(item["tests"] or item.get("commands"))
                self.assertTrue(all((REPO / test).is_file() for test in item["tests"]))
                self.assertTrue(set(item.get("commands", [])) <= check_fast.COMMANDS.keys())
        listed = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=False)
        if listed.returncode:
            self.skipTest("not a Git checkout")
        self.assertEqual(check_fast.plan(listed.stdout.split(), self.map)["unattached"], [])


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
            "integrations/unmapped/README.md",
            "integrations/github/openguildkit-guard.yml",
            "scripts/install.sh",
            "docs/not-a-module.md",
        ], module_map)
        self.assertIn("tests/test_results.py", selected["tests"])
        self.assertIn("tests/test_guard.py", selected["tests"])
        self.assertIn("tests/test_agent_native.py", selected["tests"])
        self.assertIn("tests/test_integrations.py", selected["tests"])
        self.assertIn("tests/test_product_docs.py", selected["tests"])
        self.assertEqual(selected["commands"], ["catalog", "web-typecheck", "web-test", "node-tests"])
        self.assertNotIn("tests/test_deleted_example.py", selected["tests"])
        self.assertIn("tests/test_workflows.py", selected["tests"])
        self.assertIn("tests/test_install_script.py", selected["tests"])
        self.assertEqual(selected["unattached"], ["integrations/unmapped/README.md"])

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

    def test_issue_502_a_catalog_record_a_check_kind_support_security_and_a_fixture_run_tests(self):
        """Issue #502: a renamed rule of a pack and a new check kind left the check green, and tests/support.py,
        SECURITY.md or a fixture made it fail with no test run."""
        module_map = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))
        pack = check_fast.plan(["src/openguildkit/registry/packs/gdpr.json"], module_map)
        self.assertIn("tests/test_regulatory_packs.py", pack["tests"])
        self.assertIn("tests/test_pack_rules.py", pack["tests"])
        self.assertEqual(pack["commands"], ["catalog"])
        self.assertIn("tests/test_catalog_format_doc.py",
                      check_fast.plan(["src/openguildkit/rule_checks.py"], module_map)["tests"])
        for path in ("tests/support.py", "SECURITY.md", "tests/fixtures/upgrade/v0.16.1.json", "tests/__init__.py"):
            with self.subTest(path=path):
                selected = check_fast.plan([path], module_map)
                self.assertTrue(selected["tests"])
                self.assertEqual(selected["unattached"], [])
        self.assertIn("tests/test_personal_data_doc.py", check_fast.plan(["SECURITY.md"], module_map)["tests"])
        self.assertIn("tests/test_upgrade.py",
                      check_fast.plan(["tests/fixtures/upgrade/v0.16.1.json"], module_map)["tests"])

    def test_issue_456_the_plan_of_a_module_fits_in_a_kilobyte_and_runs_nothing(self):
        """Issue #456: the check had no way to print its plan without running the tests."""
        started = time.monotonic()
        shown = subprocess.run([sys.executable, str(REPO / "scripts" / "check_fast.py"), "--plan",
                                "src/openguildkit/results.py", "task new"], capture_output=True, text=True, check=False)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertLessEqual(len(shown.stdout.encode()), 1024, shown.stdout)
        self.assertIn("src/openguildkit/results.py: Records what was delivered", shown.stdout)
        self.assertIn("task new: src/openguildkit/tasks_cli.py:", shown.stdout)
        self.assertIn("test_results", shown.stdout)
        self.assertLess(time.monotonic() - started, 10)

    def fast_repository(self, tests: dict[str, str]) -> Path:
        """A Git repository with a module attached to `tests`, check_fast and its runner, and the module changed.

        It ignores __pycache__/ as the repository does: otherwise the bytecode of run_tests, which check_fast imports,
        is an untracked file with no test attached, and the check fails (#456)."""
        root = _repository(self)
        for name in ("check_fast", "run_tests"):
            (root / "scripts").mkdir(exist_ok=True)
            shutil.copy(REPO / "scripts" / f"{name}.py", root / "scripts" / f"{name}.py")
        module_map = {"modules": [{"module": "src/openguildkit/a.py", "tests": sorted(tests)}], "paths": []}
        _commit(root, {".gitignore": "__pycache__/\n", "src/openguildkit/a.py": "", "tests/__init__.py": "", **tests,
                       "docs/agents/map.json": json.dumps(module_map)}, "base")
        (root / "src" / "openguildkit" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        return root

    def check(self, root: Path, *args: str) -> subprocess.CompletedProcess:
        """check_fast as CI runs it: Python writes the bytecode of the runner it imports next to the script."""
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
        return subprocess.run([sys.executable, str(root / "scripts" / "check_fast.py"), *args], cwd=root,
                              capture_output=True, text=True, check=False, env=environment)

    def test_issue_456_a_failure_comes_first_and_stops_the_run_after_the_announced_count(self):
        """Issue #456: the check ran everything in one process, with no count first and no stop at a failure."""
        slow = "import time\nimport unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        time.sleep(30)\n"
        bad = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail('broken')\n"
        root = self.fast_repository({"tests/test_slow.py": slow, "tests/test_a.py": bad})
        started = time.monotonic()
        failed = self.check(root, "--base", "HEAD", "--jobs", "2")
        self.assertEqual(failed.returncode, 1, failed.stdout)
        self.assertTrue(failed.stdout.startswith("check_fast: 2 test file(s) and 0 command(s), 2 at once: failed in"))
        self.assertEqual(failed.stdout.splitlines()[1], "===== tests/test_a.py failed")
        self.assertIn("AssertionError: broken", failed.stdout)
        self.assertLess(time.monotonic() - started, 20)

    def test_issue_456_past_the_budget_nothing_starts_and_the_files_left_are_named(self):
        """Issue #456: the check took up to 3 minutes for a 30 s budget nothing enforced."""
        slow = "import time\nimport unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        time.sleep(30)\n"
        root = self.fast_repository({"tests/test_slow.py": slow, "tests/test_a.py": "import unittest\n"})
        started = time.monotonic()
        passed = self.check(root, "--base", "HEAD", "--jobs", "1", "--budget", "2")
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertEqual(len(passed.stdout.splitlines()), 1, passed.stdout)
        self.assertIn("Warning: check_fast: 1 test file(s) not run within the 2 s budget (--all runs them): test_slow",
                      passed.stderr)
        self.assertLess(time.monotonic() - started, 20)

    def test_issue_456_an_unknown_base_is_one_line_that_names_base(self):
        """Issue #456: without origin/main, the check printed Git's own error."""
        root = self.fast_repository({"tests/test_a.py": "import unittest\n"})
        missing = self.check(root)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, "")
        self.assertEqual(missing.stderr.strip().count("\n"), 0, missing.stderr)
        self.assertIn("--base HEAD", missing.stderr)

    @unittest.skipUnless(os.environ.get("OPENGUILDKIT_PERF") == "1", "timed: set OPENGUILDKIT_PERF=1")
    def test_issue_456_a_change_of_the_module_with_the_most_tests_ends_within_the_budget(self):
        """Issue #456: a one-line change of storage.py ran 62 test files for 238 s."""
        module_map = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))
        largest = max(module_map["modules"], key=lambda item: len(item["tests"]))["module"]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "copy"
        subprocess.run(["git", "clone", "-q", "--shared", str(REPO), str(root)], check=True)
        with (root / largest).open("a", encoding="utf-8") as handle:
            handle.write("# touched\n")
        started = time.monotonic()
        result = self.check(root, "--base", "HEAD")
        seconds = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stdout[-3000:])
        self.assertLessEqual(seconds, check_fast.BUDGET + 10, f"{largest}: {seconds:.1f} s")


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
        listed = json.loads((REPO / "docs" / "agents" / "map.json").read_text(encoding="utf-8"))["paths"]
        paths_entries = {item["path"] for item in listed}
        self.assertGreater(len(paths), 5)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((REPO / path.split(" ")[0]).exists(), path)
        for module in modules:
            with self.subTest(module=module):
                self.assertTrue((REPO / (module.replace(".", "/") + ".py")).is_file(), module)
        for script in re.findall(r"python (scripts/\w+\.py)", text):
            with self.subTest(script=script):
                self.assertIn(script, paths_entries)

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

    def test_a_title_or_a_subject_names_no_range_and_no_list_of_issues(self):
        check = _load("check_pr_text")
        notes = "\n\n## Not verified\n\nnothing"
        for title in ("Fix the fifth audit findings (#377 to #407) (#409)", "Fix the page (#12, #13)",
                      "Close #12, #13 and more"):
            with self.subTest(title=title):
                found = check.problems(title, notes)
                self.assertEqual(len(found), 1, found)
                self.assertIn("range", found[0])
        for title in ("Fix the page (#12)", "Add 3 to 4 retries (#7)", "Fix #12 and #13 apart"):
            with self.subTest(title=title):
                self.assertEqual(check.problems(title, notes), [])
        self.assertEqual(len(check.problems("Fix it (#1)", notes, ["Fix a (#1 to #4)", "Fix b (#5)"])), 1)
        root = _repository(self)
        _commit(root, {"a.txt": "1"}, "base")
        _git(root, "branch", "base")
        _commit(root, {"a.txt": "2"}, "Fix many things (#377 to #407)")
        _commit(root, {"a.txt": "3"}, "Fix one thing (#5)")
        result = _run_script(root, "check_pr_text", "--base", "base", env={"PR_BODY": notes})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Fix many things (#377 to #407)", result.stdout)
        self.assertNotIn("Fix one thing", result.stdout)

    def test_commits_a_squash_brought_to_the_base_and_merge_commits_are_not_asked_again(self):
        """Issue #483: once the pull request below was squashed into main, its commits came back in the range of the
        next one, retargeted to main, with subjects written before the check existed."""
        notes = "\n\n## Not verified\n\nnothing"
        root = _repository(self)
        _commit(root, {"a.txt": "1"}, "start")
        _git(root, "checkout", "-q", "-b", "lower")
        _commit(root, {"a.txt": "2"}, "Speed things up (#1, #2)")
        _git(root, "checkout", "-q", "-b", "upper")
        _commit(root, {"b.txt": "1"}, "Add a check (#3)")
        _git(root, "checkout", "-q", "main")
        _commit(root, {"a.txt": "2"}, "Lower lot (#4)\n\n* Speed things up (#1, #2)\n")
        _git(root, "checkout", "-q", "upper")
        _git(root, "merge", "-q", "-s", "ours", "main", "-m", "Merge main after the squash (#1, #2)")
        result = _run_script(root, "check_pr_text", "--base", "main", env={"PR_BODY": notes})
        self.assertEqual(result.returncode, 0, result.stdout)
        _commit(root, {"b.txt": "2"}, "Fix more (#5, #6)")
        result = _run_script(root, "check_pr_text", "--base", "main", env={"PR_BODY": notes})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Fix more (#5, #6)", result.stdout)
        self.assertNotIn("Speed things up", result.stdout)

    def test_the_body_has_one_line_for_each_issue_it_closes(self):
        check = _load("check_pr_text")
        notes = "\n\n## Not verified\n\nnothing"
        body = "Closes #12\nFixes #13" + notes
        found = check.problems("Fix it (#12)", body)
        self.assertEqual(len(found), 2)
        self.assertIn("#12", found[0])
        self.assertIn("#13", found[1])
        lines = "Closes #12\nFixes #13\n\n#12 the page says 500 (src/mod.py:render)\n- #13 it hangs (src/mod.py:wait)" + notes
        self.assertEqual(check.problems("Fix it (#12)", lines), [])
        self.assertEqual(check.problems("Fix it", "Part of #12" + notes), [])
        self.assertEqual(len(check.problems("Fix it", "Closes #12\n#12\n" + notes)), 1)


class BlameIgnoreTests(unittest.TestCase):
    """commit-names-its-issues: git blame skips the bulk squashes, and GOVERNANCE.md says how main merges."""

    def revisions(self) -> list[str]:
        lines = (REPO / ".git-blame-ignore-revs").read_text(encoding="utf-8").splitlines()
        found = []
        for number, line in enumerate(lines):
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line, r"^[0-9a-f]{40}$", f"line {number + 1} is not a full SHA")
                self.assertTrue(number and lines[number - 1].startswith("# "), f"{line} has no comment above it")
                found.append(line)
        return found

    def test_issue_483_each_ignored_revision_is_a_full_sha_with_its_reason(self):
        """Issue #483: git blame led to a commit of 523 files for 41 to 77 % of the lines of the central modules."""
        self.assertIn("6ec06a59c240c34e2ccdd4b670da9b071d669971", self.revisions())
        self.assertIn("git config blame.ignoreRevsFile .git-blame-ignore-revs",
                      (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8"))

    def test_ignored_revisions_exist_when_the_history_is_here(self):
        for revision in self.revisions():
            probe = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{revision}^{{commit}}"],
                                   capture_output=True, check=False) if shutil.which("git") else None
            if probe is None or probe.returncode:
                self.skipTest(f"{revision} is not in this clone (shallow, or not a Git checkout)")

    def test_issue_483_governance_says_how_a_pull_request_of_several_issues_merges(self):
        """Issue #483: GOVERNANCE.md did not say which merge method applies to a pull request of several issues."""
        merging = (REPO / "GOVERNANCE.md").read_text(encoding="utf-8").split("## Merging", 1)[1].split("\n## ", 1)[0]
        self.assertIn("squash", merging)
        self.assertIn("several issues", merging)
        line = re.search(r"`(#N [^`]*\(file:function\))`", merging)
        self.assertTrue(line, "the section shows the line of each issue")
        body = "Closes #12\n" + line.group(1).replace("#N", "#12") + "\n\n## Not verified\n\nnothing"
        self.assertEqual(_load("check_pr_text").problems("Fix it (#12)", body), [])


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
        self.assertEqual(self.run_check("--bugs", "7", body='<!-- Use "Closes #7"\nif it resolves it -->').returncode, 0)

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
        record = json.loads(self.run_cli("task", "show", "request-status", "--json"))
        board = record["consultation"]["boards"][0]
        self.assertIn(BUDGET, self.run_cli("task", "pass", "request-status", board))
        self.assertIn("Read only the files named in this brief, then stop.", inspect.getsource(board_brief))
        for name in AGENTS:
            self.assertIn(BUDGET, packaged_file(f"agents/{name}.md"))
            copy = REPO / "integrations" / "claude-code" / "agents" / f"{name}.md"
            self.assertIn(BUDGET, copy.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
