"""Performance: time budgets that catch a slowdown of an order of magnitude.

The measures come from scripts/bench.py: real processes, median of three runs.
Budgets are ratios to the time of openguildkit --version measured in the same
run, so a slow CI runner slows the budget down with the commands. Each budget is
at most ten times the ratio docs/testing.md records, so a tenfold regression
fails, and at least three times the highest ratio seen, so a busy machine passes. The start itself is held
to a ratio of a bare interpreter start, and every command to an absolute ceiling
against hangs.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import catalog, webui
from openguildkit.__main__ import hook_call
from openguildkit.cli import main
from openguildkit.storage import write_json

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bench.py"
spec = importlib.util.spec_from_file_location("openguildkit_bench", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

# Times openguildkit --version: at most ten times the lowest ratio docs/testing.md records, and at least
# three times the highest.
BUDGETS = {
    "catalog --json": 6,
    "init": 6,
    "task consult": 9,
    f"task list ({bench.TASKS} tasks)": 13,
    "references search": 6,
    f"guard --hook pre-edit ({bench.TASKS} tasks)": 5,
    f"guard --hook prompt ({bench.TASKS} tasks)": 5,
    f"detect (monorepo, {bench.PACKAGES} packages)": 11,
    f"init (monorepo, {bench.PACKAGES} packages)": 11,
}
START_BUDGET = 25  # times a bare interpreter start
CEILING_SECONDS = 60


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = bench.measure(repeat=3)
        if cls.over_budget(cls.results):
            # Measure once more before failing: a burst of load rarely lasts two measures, a regression does.
            again = bench.measure(repeat=3)
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

    def test_a_load_hands_out_its_own_copy(self):
        first = catalog.load_catalog()
        first["packs"].clear()
        next(iter(first["boards"].values()))["title"] = "Changed"
        second = catalog.load_catalog()
        self.assertTrue(second["packs"])
        self.assertNotIn("Changed", [board["title"] for board in second["boards"].values()])


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
        result = python("-X", "importtime", "-c", "import openguildkit.cli")
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = imported(result.stderr)
        self.assertIn("openguildkit.cli", loaded)
        for module in ("openguildkit.webui", "http.server", "openguildkit.storybook", "openguildkit.deliverables"):
            with self.subTest(module=module):
                self.assertNotIn(module, loaded)

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
                              ["guard", "--hook"], ["guard", "--ci"], ["--policy-repo", folder, "guard", "--hook", "prompt"],
                              ["--project", str(Path(folder) / "missing"), "guard", "--hook", "pre-edit"],
                              ["--project", "--version", "guard", "--hook", "pre-edit"], ["--version"], []):
                with self.subTest(arguments=arguments):
                    self.assertIsNone(hook_call(arguments))

    def test_the_installed_command_starts_from_the_same_entry_point_as_python_m(self):
        project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["scripts"]["openguildkit"], "openguildkit.__main__:main")


if __name__ == "__main__":
    unittest.main()
