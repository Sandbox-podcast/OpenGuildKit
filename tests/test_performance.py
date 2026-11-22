"""Performance: time budgets that catch a slowdown of an order of magnitude.

The measures come from scripts/bench.py: real processes, median of three runs.
Budgets are ratios to the time of openguildkit --version measured in the same
run, so a slow CI runner slows the budget down with the commands. Each budget is
at most ten times the lowest ratio recorded (docs/testing.md, or the commit that
added the command to the benchmark), so a tenfold regression fails, and at least
three times the highest ratio seen, so a busy machine passes. The start itself is
held to a ratio of a bare interpreter start, and every command to an absolute
ceiling against hangs. The bug consult runs with a small node_modules here: the
walk never enters it, which tests/test_project_walk.py checks without a clock.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import catalog, lock, tasks, webui
from openguildkit.__main__ import hook_call
from openguildkit.cli import main
from openguildkit.storage import write_json

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bench.py"
spec = importlib.util.spec_from_file_location("openguildkit_bench", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

# Times openguildkit --version: at most ten times the lowest ratio recorded, and at least three times the highest.
BUDGETS = {
    "catalog --json": 6,
    "init": 6,
    "task consult": 9,
    "task consult, bug, with node_modules": 18,
    f"task list ({bench.TASKS} tasks)": 13,
    f"check ({bench.TASKS} tasks)": 29,
    "references search": 6,
    f"guard --hook pre-edit ({bench.TASKS} tasks)": 5,
    f"guard --hook pre-edit (Git, {bench.APPROVED} approvals)": 13,
    "guard --hook pre-edit, guard off": 4,
    f"guard --hook prompt ({bench.TASKS} tasks)": 5,
    f"detect (monorepo, {bench.PACKAGES} packages)": 11,
    f"init (monorepo, {bench.PACKAGES} packages)": 11,
}
START_BUDGET = 25  # times a bare interpreter start
CEILING_SECONDS = 60
DEPENDENCY_FILES = 500  # in the web project's node_modules; scripts/bench.py uses 50 000


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = bench.measure(repeat=3, dependencies=DEPENDENCY_FILES)
        if cls.over_budget(cls.results):
            # Measure once more before failing: a burst of load rarely lasts two measures, a regression does.
            again = bench.measure(repeat=3, dependencies=DEPENDENCY_FILES)
            cls.results = {name: min(item, again[name], key=lambda run: run["x_start"])
                           for name, item in cls.results.items()}

    @staticmethod
    def over_budget(results):
        start = results["start (--version)"]["median"] / results["python -c pass"]["median"]
        return start >= START_BUDGET or any(results[name]["x_start"] >= budget for name, budget in BUDGETS.items())

    def test_every_measured_command_has_a_budget(self):
        self.assertEqual(set(self.results) - {"python -c pass", "start (--version)"}, set(BUDGETS))

    def test_the_cli_starts_quickly(self):
        start = self.results["start (--version)"]["median"]
        floor = self.results["python -c pass"]["median"]
        self.assertLess(start / floor, START_BUDGET, f"--version takes {start:.3f} s, a bare start {floor:.3f} s")

    def test_each_command_stays_within_its_budget(self):
        for name, budget in BUDGETS.items():
            with self.subTest(command=name):
                item = self.results[name]
                self.assertLess(item["median"], CEILING_SECONDS)
                self.assertLess(item["x_start"], budget, f"{name}: {item['median']:.3f} s, "
                                f"{item['x_start']:.1f} times the start; budget {budget}")


class RoutingSpeedTests(unittest.TestCase):
    """Reading a brief compiles each trigger once per process, not once per brief."""

    BUDGET_MS = 5  # per brief; about 1 ms on a laptop, 48 ms when every trigger was compiled for every text

    def test_routing_a_brief_takes_a_few_milliseconds(self):
        from openguildkit.routing import text_routes
        tests = Path(__file__).resolve().parent
        briefs = [case["brief"] for name in ("routing_cases.json", "routing_cases_new_brains.json")
                  for case in json.loads((tests / name).read_text(encoding="utf-8"))]
        boards = catalog.load_catalog()["boards"]
        passes = []
        for _ in range(3):
            started = time.perf_counter()
            for brief in briefs:
                text_routes(boards, brief)
            passes.append((time.perf_counter() - started) * 1000 / len(briefs))
        self.assertGreaterEqual(len(briefs), 228)
        self.assertLess(min(passes), self.BUDGET_MS, f"{min(passes):.1f} ms per brief over {len(briefs)} briefs")


class CatalogLoadTests(unittest.TestCase):
    """Each command reads and validates the bundled catalog once, however many times it loads the catalog."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        profile = {**json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": "enforce"}
        write_json(self.root / "profile.json", profile)

    def bundled_reads(self, *arguments, stdin="", code=0):
        """How many times one command read the bundled catalog, starting as a fresh process does."""
        catalog._BUNDLED.clear()
        with patch("openguildkit.catalog._read_bundled", wraps=catalog._read_bundled) as reader, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error, \
                patch("sys.stdin", io.StringIO(stdin)):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, error.getvalue())
        return reader.call_count

    def test_each_command_validates_the_bundled_catalog_once(self):
        hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "app.py")}})
        commands = [
            ("init", "--answers", self.root / "profile.json"), ("catalog", "--json"), ("sync",), ("check",),
            ("update",), ("task", "new", "A brief.", "--id", "one"), ("task", "list"), ("guard", "--json"),
        ]
        for command in commands:
            with self.subTest(command=command[0]):
                self.assertEqual(self.bundled_reads(*command), 1)
        self.assertEqual(self.bundled_reads("guard", "--hook", "pre-edit", stdin=hook, code=2), 1)

    def test_the_edit_hook_reads_no_catalog_when_the_guard_is_off(self):
        profile = {**json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": "off"}
        write_json(self.root / "profile.json", profile)
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "app.py")}})
        for event in ("pre-edit", "prompt"):
            with self.subTest(event=event):
                self.assertEqual(self.bundled_reads("guard", "--hook", event, stdin=hook), 0)

    def test_task_consult_validates_the_project_catalog_and_the_lock_once(self):
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        pack = {"id": "house-rules", "title": "House rules", "version": "1.0.0", "description": "Team rules.",
                "sources": [], "rules": [{"id": "small-changes", "instruction": "Keep changes small.",
                                          "verification": "Check the size of the diff."}]}
        write_json(self.root / ".openguildkit" / "catalog" / "packs" / "house-rules.json", pack)
        self.bundled_reads("task", "new", (bench.EXAMPLE / "brief.md").read_text(encoding="utf-8"), "--id", "status")
        catalog._MERGED.clear()
        lock._READ.clear()  # As a new process starts.
        with patch("openguildkit.catalog._merged_records", wraps=catalog._merged_records) as merged, \
                patch("openguildkit.lock._validated_lock", wraps=lock._validated_lock) as locks:
            self.bundled_reads("task", "consult", "status", "--answers", bench.EXAMPLE / "answers.json")
        project = [call for call in merged.call_args_list if call.args[1] is not None]
        self.assertEqual((len(project), locks.call_count), (1, 1))

    def test_a_load_hands_out_its_own_copy(self):
        first = catalog.load_catalog()
        first["packs"].clear()
        next(iter(first["boards"].values()))["title"] = "Changed"
        second = catalog.load_catalog()
        self.assertTrue(second["packs"])
        self.assertNotIn("Changed", [board["title"] for board in second["boards"].values()])


class CheckReadTests(unittest.TestCase):
    """check, which CI and the agent run at the start of a session, reads the task records as few times as it can."""

    def test_check_reads_each_task_record_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "profile.json", json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")))
            commands = [("init", "--answers", root / "profile.json")]
            commands += [("task", "new", f"Brief {index}.", "--id", f"task-{index}") for index in range(6)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                for command in commands:
                    self.assertEqual(main(["--project", str(root), *map(str, command)]), 0)
            reads = []
            original = tasks.read_task

            def counting(state, task_id):
                reads.append(task_id)
                return original(state, task_id)

            with patch("openguildkit.tasks.read_task", counting), patch("openguildkit.tasks_cli.read_task", counting), \
                    patch("openguildkit.guard.read_task", counting), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(["--project", str(root), "check"]), 0, error.getvalue())
        self.assertEqual(sorted(set(reads)), [f"task-{index}" for index in range(6)])
        self.assertEqual(max(reads.count(task_id) for task_id in set(reads)), 1)


def python(*arguments, stdin=""):
    """Run a fresh interpreter on the source tree, as an installed command or a host hook starts."""
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"),
                                                                            os.environ.get("PYTHONPATH")]))}
    return subprocess.run([sys.executable, *arguments], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          env=environment, timeout=300)


def imported(importtime: str) -> set[str]:
    """The modules that python -X importtime reports, from its lines on stderr."""
    return {line.rpartition("|")[2].strip() for line in importtime.splitlines()
            if line.startswith("import time:") and "imported package" not in line}


class StartupTests(unittest.TestCase):
    """What a command loads before it runs: the web server and the rarely used modules wait for their command, and
    the edit hook, which runs before every edit an agent makes, skips the CLI."""

    def test_importing_the_cli_leaves_out_the_web_server_storybook_and_deliverables(self):
        result = python("-X", "importtime", "-c", "import sys, openguildkit.cli; print('\\n'.join(sorted(sys.modules)))")
        self.assertEqual(result.returncode, 0, result.stderr)
        listed, modules = imported(result.stderr), set(result.stdout.split())
        self.assertIn("openguildkit.cli", listed & modules)
        for module in ("openguildkit.webui", "http.server", "openguildkit.storybook", "openguildkit.deliverables"):
            with self.subTest(module=module):
                self.assertNotIn(module, listed)
                self.assertNotIn(module, modules)

    def test_ui_help_gives_the_default_port_of_the_server(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            main(["ui", "--help"])
        self.assertEqual(webui.DEFAULT_PORT, 7311)
        self.assertIn(f"default {webui.DEFAULT_PORT};", " ".join(output.getvalue().split()))

    def test_the_edit_hook_runs_without_importing_the_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = {**json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": "enforce"}
            write_json(root / "profile.json", profile)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--project", str(root), "init", "--answers", str(root / "profile.json")]), 0)
            hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(root / "app.py")}})
            result = python("-X", "importtime", "-m", "openguildkit", "--project", str(root), "guard", "--hook",
                            "pre-edit", stdin=hook)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Edit refused for: app.py", result.stderr)
        loaded = imported(result.stderr)
        self.assertIn("openguildkit.guard", loaded)
        self.assertNotIn("openguildkit.cli", loaded)

    def test_only_a_plain_hook_call_skips_the_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(hook_call(["guard", "--hook", "pre-edit"]), ("pre-edit", None))
            self.assertEqual(hook_call(["--project", folder, "guard", "--hook=prompt"]), ("prompt", Path(folder)))
            self.assertEqual(hook_call([f"--project={folder}", "guard", "--hook", "prompt"]), ("prompt", Path(folder)))
            # Anything else goes to cli.main, which parses it and words its own errors.
            for arguments in (["guard", "--hook", "post-edit"], ["guard", "--hook", "pre-edit", "--json"],
                              ["guard", "--hook"], ["guard", "--ci"],
                              ["--policy-repo", folder, "guard", "--hook", "prompt"],
                              ["--project", str(Path(folder) / "missing"), "guard", "--hook", "pre-edit"],
                              ["--project", "--version", "guard", "--hook", "pre-edit"], ["--version"], []):
                with self.subTest(arguments=arguments):
                    self.assertIsNone(hook_call(arguments))

    def test_the_installed_command_starts_from_the_same_entry_point_as_python_m(self):
        project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["scripts"]["openguildkit"], "openguildkit.__main__:main")


if __name__ == "__main__":
    unittest.main()
