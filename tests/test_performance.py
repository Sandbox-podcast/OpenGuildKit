"""Performance: time budgets that catch a doubling of a command's time.

The measures come from scripts/bench.py: real processes, median of three runs.
Budgets are ratios to the time of openguildkit --version measured in the same
run, so a slow CI runner slows the budget down with the commands; the edit hook's
are ratios to a bare interpreter start, so that a slower --version does not loosen
them. Each budget is at most three times the ratio docs/testing.md records (#538),
so a doubling fails, and a run over budget is measured once more before failing,
so a burst of load passes. The start itself is held to a ratio of a bare
interpreter start, and every command to an absolute ceiling against hangs. The bug
consult runs with a small node_modules here: the walk never enters it, which
tests/test_project_walk.py checks without a clock.
"""

import argparse
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
from unittest.mock import MagicMock, patch

from openguildkit import catalog, lock, tasks, webui
from openguildkit.__main__ import hook_call
from openguildkit.cli import main
from openguildkit.storage import write_json
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bench.py"
spec = importlib.util.spec_from_file_location("openguildkit_bench", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

# Times openguildkit --version, each about 2.5 times the highest ratio of the table in docs/testing.md and at most
# three times it (#538): a command twice as slow fails. A run over budget is measured once more before failing.
BUDGETS = {
    "catalog --json": 31,
    "init": 21,
    "task consult": 29,
    f"task consult, bug, {bench.SOURCE_FILES} source files": 38,
    f"task list ({bench.TASKS} tasks)": 62,
    f"check ({bench.TASKS} tasks)": 66,
    f"task list ({bench.TASKS} closed tasks)": 19,
    f"check ({bench.TASKS} closed tasks)": 128,
    f"task challenge ({bench.TASKS} closed tasks)": 22,
    "references search": 22,
    f"detect (monorepo, {bench.PACKAGES} packages)": 20,
    f"init (monorepo, {bench.PACKAGES} packages)": 25,
    f"guard --ci ({bench.MERGED} records on the base)": 39,
    f"projects --surfaces ({bench.FLEET} projects)": 113,
}
# The edit hook, in times a bare interpreter start (x python): a slower --version does not loosen them (#538).
HOOK_BUDGETS = {
    f"guard --hook pre-edit ({bench.TASKS} tasks)": 27,
    f"guard --hook pre-edit, Codex ({bench.TASKS} tasks)": 22,
    f"guard --hook pre-edit, Gemini CLI ({bench.TASKS} tasks)": 24,
    f"guard --hook pre-edit (Git, {bench.APPROVED} approvals)": 28,
    "guard --hook pre-edit, guard off": 4,
    f"guard --hook prompt ({bench.TASKS} tasks)": 27,
}
START_BUDGET = 4  # times a bare interpreter start; 1.4 to 1.6 measured (#539)
CEILING_SECONDS = 60
DEPENDENCY_FILES = 500  # in the web project's node_modules; scripts/bench.py uses 50 000


@unittest.skipUnless(os.environ.get("OPENGUILDKIT_PERF") == "1", "Run the real process benchmarks with OPENGUILDKIT_PERF=1.")
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
        return start >= START_BUDGET or any(results[name]["x_start"] >= budget for name, budget in BUDGETS.items()) \
            or any(results[name]["x_python"] >= budget for name, budget in HOOK_BUDGETS.items())

    def test_every_measured_command_has_a_budget(self):
        self.assertEqual(set(self.results) - {"python -c pass", "start (--version)"}, {*BUDGETS, *HOOK_BUDGETS})

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

    def test_the_edit_hook_stays_within_its_budget_against_a_bare_interpreter(self):
        for name, budget in HOOK_BUDGETS.items():
            with self.subTest(command=name):
                item = self.results[name]
                self.assertLess(item["median"], CEILING_SECONDS)
                self.assertLess(item["x_python"], budget, f"{name}: {item['median']:.3f} s, "
                                f"{item['x_python']:.1f} times a bare interpreter; budget {budget}")


class BudgetTableTests(unittest.TestCase):
    """The budgets follow the ratios docs/testing.md records, without a clock."""

    def test_each_budget_is_at_most_three_times_the_ratio_the_documentation_records(self):
        """Issue #538: budgets were 2.2 to 7.5 times the measure, so a doubling of the hook or the start passed."""
        page = (REPO / "docs" / "testing.md").read_text(encoding="utf-8")
        rows = page.split("| Command | median s | x start | x python |\n", 1)[1].split("\n\n", 1)[0].splitlines()[1:]
        table = {}
        for line in rows:
            name, _, start, floor = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            table[name] = {"x_start": float(start.split(" to ")[1]), "x_python": float(floor.split(" to ")[1])}
        documented = {**{name: (budget, "x_start") for name, budget in BUDGETS.items()},
                      **{name: (budget, "x_python") for name, budget in HOOK_BUDGETS.items()},
                      "start (--version)": (START_BUDGET, "x_python")}
        self.assertEqual(sorted(set(documented) - set(table)), [])
        for name, (budget, ratio) in documented.items():
            with self.subTest(command=name):
                self.assertLessEqual(budget, 3 * table[name][ratio])


class BenchReportTests(unittest.TestCase):
    def test_the_report_says_whether_the_commands_read_the_catalog_bundle(self):
        """Issue #533: a benchmark of a checkout timed the catalog record files, not the bundle the wheel ships,
        without saying so."""
        results = {"start (--version)": {"median": 0.1, "x_start": 1.0}}
        for bundle, read in ((None, False), ({}, True)):
            with self.subTest(read=read), patch("openguildkit.catalog._read_bundle", return_value=bundle):
                self.assertIs(bench.report(results)["catalog_bundle"], read)
                last = bench.table(results).splitlines()[-1]
                self.assertEqual(last.startswith("Bundled catalog read from registry/catalog.bundle.json"), read, last)


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
        with patch("openguildkit.catalog._read_bundled", wraps=catalog._read_bundled) as reader:
            run_cli(self.root, *arguments, expect=code, stdin=stdin)
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

    def test_task_list_loads_the_catalog_once_and_reads_the_lock_once(self):
        """Issue #533: task list loaded the catalog twice and read the lock twice, a deep copy each time."""
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        self.bundled_reads("task", "new", "A brief.", "--id", "one")
        counters = {}
        with contextlib.ExitStack() as stack:
            for module, name in ((catalog, "load_catalog"), (lock, "read_lock")):
                function = getattr(module, name)
                counters[name] = MagicMock(wraps=function)
                holders = [item for key, item in list(sys.modules.items())
                           if key.startswith("openguildkit") and getattr(item, name, None) is function]
                for holder in holders:
                    stack.enter_context(patch.object(holder, name, counters[name]))
            self.bundled_reads("task", "list")
        self.assertEqual({name: counter.call_count for name, counter in counters.items()},
                         {"load_catalog": 1, "read_lock": 1})

    def test_task_list_copies_the_catalog_at_most_25_times(self):
        """Issue #533: task list deep-copied each locked record once more, 46 copies for a lock of 41 records."""
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        original, depth, copies = catalog.json_copy, [0], [0]

        def counted(value):
            copies[0] += depth[0] == 0  # json_copy calls itself for each nested value: count the outer call only
            depth[0] += 1
            try:
                return original(value)
            finally:
                depth[0] -= 1

        with patch.object(catalog, "json_copy", counted), patch.object(lock, "json_copy", counted):
            self.bundled_reads("task", "list")
        self.assertLessEqual(copies[0], 25)

    def rewrite_in_place(self, path: Path, old: bytes, new: bytes) -> None:
        """Rewrite a file in place with the same size and give it back its modification time, as an editor that
        saves in place within one tick of a coarse file system (HFS+, FAT, SMB) leaves it (issue 285)."""
        info = path.stat()
        content = path.read_bytes()
        self.assertEqual(len(old), len(new))
        self.assertIn(old, content)
        with open(path, "r+b") as handle:
            handle.write(content.replace(old, new))
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual((path.stat().st_size, path.stat().st_mtime_ns), (info.st_size, info.st_mtime_ns))

    def test_a_same_size_rewrite_that_keeps_the_modification_time_is_read_again(self):
        self.bundled_reads("init", "--answers", self.root / "profile.json")
        state = self.root / ".openguildkit"
        pack = {"id": "house-rules", "title": "House rules", "version": "1.0.0", "description": "Team rules.",
                "sources": [], "rules": [{"id": "small-changes", "instruction": "Rule EEEE 0049.",
                                          "verification": "Check the size of the diff."}]}
        path = state / "catalog" / "packs" / "house-rules.json"
        write_json(path, pack)
        rule = lambda: catalog.load_catalog(state / "catalog")["packs"]["house-rules"]["rules"][0]["instruction"]
        self.assertEqual(rule(), "Rule EEEE 0049.")
        self.rewrite_in_place(path, b"EEEE", b"FFFF")
        self.assertEqual(rule(), "Rule FFFF 0049.")
        # The CLI, which keeps its caches between commands in one process (openguildkit ui), reads it too.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(["--project", str(self.root), "catalog", "--json"])
        self.assertIn("Rule FFFF 0049", output.getvalue())

        described = lambda: lock.read_lock(state)["records"]["packs"]["python"]["description"]
        self.assertTrue(described().startswith("Repository conventions for Python code"))
        self.rewrite_in_place(state / lock.LOCK_FILE, b"conventions for Python code", b"conventions for PYTHON code")
        self.assertTrue(described().startswith("Repository conventions for PYTHON code"))

    def test_the_task_index_the_catalog_and_the_lock_compare_one_file_signature(self):
        from openguildkit import storage, task_index
        for module in (catalog, lock, task_index):
            with self.subTest(module=module.__name__):
                self.assertIs(module.file_signature, storage.file_signature)

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


def close_and_export(root: Path, task_id: str) -> None:
    """Take the example task the whole way, as the normal path does: consulted, approved, closed and exported. The
    project's profile names no check command, so verify runs none."""
    run_cli(root, "task", "new", "--file", bench.EXAMPLE / "brief.md", "--id", task_id)
    run_cli(root, "task", "consult", task_id, "--answers", bench.EXAMPLE / "answers.json")
    template = json.loads(run_cli(root, "task", "template", task_id).stdout)
    write_json(root / "review.json", {"consultation_id": template["consultation_id"],
                                      **json.loads((bench.EXAMPLE / "review.json").read_text(encoding="utf-8"))})
    run_cli(root, "task", "review", task_id, "--file", root / "review.json")
    run_cli(root, "task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Agreed", typed=task_id)
    run_cli(root, "task", "verify", task_id)
    listed = json.loads(run_cli(root, "task", "checks", task_id, "--json").stdout)
    checks = [{"check": item["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"}
              for item in listed if item["kind"] == "rule"]
    write_json(root / "result.json", {"pull_request": "https://github.com/example/portal/pull/7", "checks": checks,
                                      "criteria": [{"criterion": "Users only see their own requests.", "status": "met",
                                                    "evidence": "tests/test_access.py"}]})
    run_cli(root, "task", "result", task_id, "--file", root / "result.json")
    run_cli(root, "task", "complete", task_id, "--by", "Camille", typed=task_id)
    run_cli(root, "task", "export", task_id)


class ClosedTaskReadTests(unittest.TestCase):
    """task list, check and projects on closed and exported tasks, the records the normal path leaves."""

    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.root = Path(temporary.name).resolve()
        profile = {**json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")), "checks": []}
        write_json(cls.root / "profile.json", profile)
        run_cli(cls.root, "init", "--answers", cls.root / "profile.json")
        cls.ids = [f"task-{index}" for index in range(6)]
        for task_id in cls.ids:
            close_and_export(cls.root, task_id)

    def reads(self, *arguments) -> list[str]:
        """The task records one command read, an ID per read, wherever the command reads them from."""
        reads, original = [], tasks.read_task

        def counting(state, task_id):
            reads.append(task_id)
            return original(state, task_id)

        holders = [module for name, module in sorted(sys.modules.items())
                   if name.startswith("openguildkit") and getattr(module, "read_task", None) is original]
        with contextlib.ExitStack() as stack:
            for module in holders:
                stack.enter_context(patch.object(module, "read_task", counting))
            run_cli(self.root, *arguments)
        return reads

    def test_check_reads_each_closed_and_exported_task_once(self):
        """Issue #534: check read each closed and exported task three times (7.4 s at 1,000 tasks)."""
        self.assertEqual(sorted(self.reads("check")), self.ids)

    def test_task_list_reads_each_closed_and_exported_task_at_most_once(self):
        """Issue #534: task list read each closed and exported task twice (4.9 s at 1,000 tasks)."""
        reads = self.reads("task", "list")
        self.assertLessEqual(set(reads), set(self.ids))
        self.assertEqual(len(reads), len(set(reads)), reads)

    def test_projects_reads_each_closed_and_exported_task_once(self):
        """Issue #534: projects read each closed and exported task four times (10 s at 1,000 tasks)."""
        self.assertEqual(sorted(self.reads("projects", self.root)), self.ids)

    def test_a_task_record_is_written_without_indentation_and_reads_as_before(self):
        """Issue #534: indentation made 29 % of a closed task record, which only the commands read."""
        for task_id in self.ids:
            with self.subTest(task=task_id):
                text = (self.root / ".openguildkit" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8")
                self.assertEqual(text.count("\n"), 1)
                self.assertTrue(text.startswith('{"schema_version":1,'), text[:40])
                # Any JSON reader reads it, so an earlier release does too: the fields are those it wrote.
                self.assertEqual(json.loads(text), tasks.read_task(self.root / ".openguildkit", task_id))


# Counts the expressions the package compiles while the statements run, whatever the standard library compiles on
# its own: json, fnmatch or urllib compile some at import, more of them under Python 3.11 than 3.15 (#539).
COUNT_PACKAGE_EXPRESSIONS = """import sys
import re._compiler as compiler
calls = []
original = compiler.compile


def counted(*args):
    frame = sys._getframe(1)
    while frame is not None and frame.f_globals.get("__name__", "").partition(".")[0] == "re":
        frame = frame.f_back
    if frame is not None and frame.f_globals.get("__name__", "").partition(".")[0] == "openguildkit":
        calls.append(args)
    return original(*args)


compiler.compile = counted
{statements}
print(len(calls))
"""


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

    def project(self, folder: str, guard: str) -> Path:
        """An initialized example project with that guard mode."""
        root = Path(folder)
        profile = {**json.loads((bench.EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": guard}
        write_json(root / "profile.json", profile)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--project", str(root), "init", "--answers", str(root / "profile.json")]), 0)
        return root

    def test_the_edit_hook_of_a_project_whose_guard_is_off_imports_no_guard(self):
        """Issue #539: with guard: off, the hook imported the guard and 150 modules before reading the profile."""
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, "off")
            hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(root / "app.py")}})
            for event in ("pre-edit", "prompt"):
                with self.subTest(event=event):
                    result = python("-X", "importtime", "-m", "openguildkit", "--project", str(root), "guard",
                                    "--hook", event, stdin=hook)
                    self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
                    loaded = imported(result.stderr)
                    self.assertEqual(sorted(name for name in loaded if name.startswith("openguildkit.")),
                                     ["openguildkit.startup", "openguildkit.storage", "openguildkit.terminal"])

    def test_the_active_edit_hook_leaves_out_tempfile_and_the_deferred_commands(self):
        """Issue #539: the hook imported tempfile, and with it shutil's compressors and random, to write nothing."""
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, "enforce")
            hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(root / "app.py")}})
            result = python("-X", "importtime", "-m", "openguildkit", "--project", str(root), "guard", "--hook",
                            "pre-edit", stdin=hook)
        self.assertEqual(result.returncode, 2, result.stderr)
        loaded = imported(result.stderr)
        for module in ("tempfile", "openguildkit.cli", "openguildkit.tools", "openguildkit.mcp_mock"):
            with self.subTest(module=module):
                self.assertNotIn(module, loaded)

    def test_version_answers_without_the_cli(self):
        """Issue #539: --version imported the whole CLI, 115 to 138 ms for 23 ms of interpreter."""
        result = python("-X", "importtime", "-m", "openguildkit", "--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^openguildkit \S+\n$")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            main(["--version"])
        self.assertEqual(output.getvalue(), result.stdout)
        self.assertEqual(sorted(name for name in imported(result.stderr) if name.startswith("openguildkit.")),
                         ["openguildkit.startup"])
        with tempfile.TemporaryDirectory() as folder:  # As scripts/bench.py and a script in a project call it.
            placed = python("-X", "importtime", "-m", "openguildkit", "--project", folder, "--version")
        self.assertEqual(placed.stdout, result.stdout)
        self.assertNotIn("openguildkit.cli", imported(placed.stderr))

    def test_task_list_leaves_out_the_deferred_command_modules(self):
        """Issue #539: every command imported the alerts, market, Storybook and tools commands and the mock MCP server."""
        with tempfile.TemporaryDirectory() as folder:
            root = self.project(folder, "off")
            result = python("-X", "importtime", "-m", "openguildkit", "--project", str(root), "task", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = imported(result.stderr)
        for module in ("alerts_cli", "storybook_cli", "market_cli", "tools_cli", "mcp_mock"):
            with self.subTest(module=module):
                self.assertNotIn(f"openguildkit.{module}", loaded)

    def test_a_deferred_command_has_the_same_line_in_the_root_help_as_in_its_module(self):
        """Issue #539: the root's help gives the line of a command whose module it does not import."""
        from openguildkit import cli, cli_surface, project, startup

        def lines(parser):
            group = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
            return {item.dest: item.help for item in group._choices_actions}

        full, light = lines(cli.command_parser()), lines(cli.command_parser(frozenset(cli_surface.DEFERRED_COMMANDS)))
        self.assertEqual(light, full)
        self.assertEqual(cli_surface.deferred_modules(["--project", "alerts", "task", "list"]),
                         frozenset(cli_surface.DEFERRED_COMMANDS))
        self.assertNotIn("alerts_cli", cli_surface.deferred_modules(["--project=x", "alerts", "--help"]))
        self.assertEqual(cli_surface.deferred_modules(["--", "alerts"]), frozenset())
        self.assertEqual(startup.STATE_DIR, project.STATE_DIR)

    def test_importing_the_cli_compiles_fewer_than_30_expressions(self):
        """Issue #539: importing the CLI compiled 123 to 138 regular expressions, 10 ms before any command ran."""
        result = python("-c", COUNT_PACKAGE_EXPRESSIONS.format(statements="import openguildkit.cli"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(int(result.stdout), 30)

    def test_issue_539_the_count_leaves_out_the_expressions_the_standard_library_compiles(self):
        """Issue #539: Python 3.11 counted 38 expressions, 3.15 23: the standard library compiles its own at import."""
        outside = "import openguildkit.lazy_re\nimport re\nfor number in range(40):\n    re.compile(f'x{number}')"
        inside = "from openguildkit import lazy_re\nfor number in range(3):\n    lazy_re.compile(f'y{number}').match('y')"
        for statements, expected in ((outside, 0), (inside, 3)):
            with self.subTest(statements=statements):
                result = python("-c", COUNT_PACKAGE_EXPRESSIONS.format(statements=statements))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(int(result.stdout), expected)

    def test_issue_539_the_version_is_the_one_importlib_metadata_gave_installed_or_not(self):
        """Issue #539: package_version reads the dist-info folders itself; it must give what importlib.metadata gave,
        the installed version, or the source version with +source in a checkout that is not installed."""
        compare = ("import tomllib\nfrom importlib import metadata\nfrom openguildkit.startup import package_version\n"
                   "try:\n    before = metadata.version('openguildkit')\nexcept metadata.PackageNotFoundError:\n"
                   "    before = tomllib.load(open('pyproject.toml', 'rb'))['project']['version'] + '+source'\n"
                   "print(before, package_version())\n")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        site = Path(folder.name)
        (site / "dist" / "openguildkit-9.8.7.dist-info").mkdir(parents=True)
        (site / "dist" / "openguildkit-9.8.7.dist-info" / "METADATA").write_text(
            "Metadata-Version: 2.4\nName: openguildkit\nVersion: 9.8.7\n\nVersion: 0.0.1 in the description\n",
            encoding="utf-8")
        (site / "egg" / "openguildkit.egg-info").mkdir(parents=True)
        (site / "egg" / "openguildkit.egg-info" / "PKG-INFO").write_text(
            "Metadata-Version: 2.1\nName: openguildkit\nVersion: 9.8.6\n", encoding="utf-8")
        source = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        for extra, expected in ((None, None), ("dist", "9.8.7"), ("egg", "9.8.6")):
            with self.subTest(path=extra):
                # The fake package comes first: an editable install (CI) leaves openguildkit.egg-info in src/.
                path = [str(site / extra) if extra else "", str(REPO / "src"), os.environ.get("PYTHONPATH", "")]
                result = subprocess.run([sys.executable, "-c", compare], cwd=REPO, capture_output=True, text=True,
                                        env={**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, path))}, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                before, now = result.stdout.split()
                self.assertEqual(now, before)
                if expected:
                    self.assertEqual(now, expected)
                else:
                    self.assertIn(now, (f"{source}+source", source))

    def test_the_installed_command_starts_from_the_same_entry_point_as_python_m(self):
        project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["scripts"]["openguildkit"], "openguildkit.__main__:main")


if __name__ == "__main__":
    unittest.main()
