"""The lint ratchet: ruff and mypy counted per rule against a baseline that only goes down."""

import contextlib
import importlib.util
import io
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lint_ratchet.py"
spec = importlib.util.spec_from_file_location("lint_ratchet", SCRIPT)
lint_ratchet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint_ratchet)

CONFIG = {"ruff": "1.0.0", "mypy": "2.0.0", "mypy_excluded": ["src/openguildkit/old.py"]}
BASELINE = {"mypy": {"arg-type": 3}, "ruff": {"F401": 2, "I001": 5}}


def findings(ruff=None, mypy=None, stray=()):
    """What a measure returns: counts per tool and rule, and the errors in modules that must be clean."""
    return {"counts": {"ruff": dict(ruff or {}), "mypy": dict(mypy or {})}, "stray": list(stray)}


class RatchetCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.baseline = Path(temporary.name) / "lint-baseline.json"

    def write(self, data):
        self.baseline.write_text(json.dumps(data), encoding="utf-8")

    def read(self):
        return json.loads(self.baseline.read_text(encoding="utf-8"))

    def run_ratchet(self, measured, *flags):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lint_ratchet.main([*flags, "--baseline", str(self.baseline)], measure=lambda: measured)
        return code, out.getvalue() + err.getvalue()


class ParseTests(unittest.TestCase):
    def test_ruff_findings_are_counted_per_rule(self):
        text = json.dumps([{"code": "I001", "filename": "a.py"}, {"code": "I001", "filename": "b.py"},
                           {"code": "F401", "filename": "a.py"}, {"code": None, "filename": "c.py"}])
        self.assertEqual(lint_ratchet.parse_ruff(text), {"I001": 2, "F401": 1, "syntax-error": 1})

    def test_mypy_errors_are_kept_with_their_file_and_notes_are_dropped(self):
        text = "\n".join(json.dumps(row) for row in (
            {"file": "src/a.py", "code": "arg-type", "severity": "error"},
            {"file": "src/a.py", "code": "arg-type", "severity": "error"},
            {"file": "src/b.py", "code": "union-attr", "severity": "error"},
            {"file": "src/b.py", "code": "note", "severity": "note"},
        ))
        self.assertEqual(lint_ratchet.parse_mypy(text), [("src/a.py", "arg-type"), ("src/a.py", "arg-type"),
                                                       ("src/b.py", "union-attr")])
        self.assertEqual(lint_ratchet.parse_mypy(""), [])


class RatchetTests(RatchetCase):
    def test_issue_501_a_count_above_the_baseline_fails_and_names_the_rule(self):
        """Issue #501: an unused import added in a pull request passed every check."""
        self.write(BASELINE)
        code, text = self.run_ratchet(findings({"F401": 3, "I001": 5}, {"arg-type": 3}))
        self.assertEqual(code, 1)
        self.assertIn("ruff F401: 3 > 2", text)
        self.assertNotIn("I001", text)

    def test_issue_501_a_rule_the_baseline_does_not_list_starts_at_zero(self):
        """Issue #501: a new kind of finding must not slip in because its rule was never counted."""
        self.write(BASELINE)
        code, text = self.run_ratchet(findings({"F401": 2, "I001": 5, "B023": 1}, {"arg-type": 3}))
        self.assertEqual(code, 1)
        self.assertIn("ruff B023: 1 > 0", text)

    def test_the_baseline_is_read_and_equal_counts_pass_in_one_line(self):
        self.write(BASELINE)
        code, text = self.run_ratchet(findings({"F401": 2, "I001": 5}, {"arg-type": 3}))
        self.assertEqual(code, 0, text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("ruff 7", text)
        self.assertIn("mypy 3", text)

    def test_a_drop_passes_and_says_how_to_keep_it(self):
        self.write(BASELINE)
        code, text = self.run_ratchet(findings({"F401": 0, "I001": 4}, {"arg-type": 3}))
        self.assertEqual(code, 0, text)
        self.assertIn("--update", text)
        self.assertEqual(self.read(), BASELINE, "a plain check never writes the baseline")

    def test_update_writes_the_lower_counts_and_drops_the_rules_at_zero(self):
        self.write(BASELINE)
        code, text = self.run_ratchet(findings({"F401": 0, "I001": 4}, {"arg-type": 1}), "--update")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.read(), {"mypy": {"arg-type": 1}, "ruff": {"I001": 4}})
        text = self.baseline.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(text, json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n")

    def test_update_never_raises_a_count_even_when_another_one_dropped(self):
        self.write(BASELINE)
        code, text = self.run_ratchet(findings({"F401": 3, "I001": 1}, {"arg-type": 3}), "--update")
        self.assertEqual(code, 1)
        self.assertIn("ruff F401: 3 > 2", text)
        self.assertEqual(self.read(), BASELINE)

    def test_without_a_baseline_a_check_fails_and_update_creates_it(self):
        code, text = self.run_ratchet(findings({"I001": 5}))
        self.assertEqual(code, 2, text)
        self.assertIn("--update", text)
        self.assertFalse(self.baseline.exists())
        code, text = self.run_ratchet(findings({"I001": 5}, {"arg-type": 2}), "--update")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.read(), {"mypy": {"arg-type": 2}, "ruff": {"I001": 5}})

    def test_a_baseline_that_is_not_counts_is_refused(self):
        for data in ([], {"ruff": {"I001": -1}}, {"ruff": {"I001": "5"}}, {"flake8": {"E1": 1}}):
            with self.subTest(data=data):
                self.write(data)
                code, text = self.run_ratchet(findings())
                self.assertEqual(code, 2, text)
                self.assertIn("baseline", text)

    def test_a_module_outside_the_excluded_list_must_stay_clean(self):
        """Issue #501: mypy must exit 0 on every module not declared as still to fix."""
        self.write({"mypy": {"arg-type": 3}})
        code, text = self.run_ratchet(findings(mypy={"arg-type": 2}, stray=["src/openguildkit/new.py"]))
        self.assertEqual(code, 1)
        self.assertIn("src/openguildkit/new.py", text)
        self.assertIn("mypy_excluded", text)


class MeasureTests(unittest.TestCase):
    """measure() runs the two tools; the launcher and the parsing are checked without them."""

    def fake_run(self, versions):
        """A run() that answers --version from versions (first word of the command to its output)."""
        calls = []

        def run(command, **_options):
            calls.append(command)
            if command[-1] == "--version":
                version = versions.get(command[0])
                if version is None:
                    raise FileNotFoundError(command[0])
                return SimpleNamespace(returncode=0, stdout=version, stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        return run, calls

    def test_the_tool_of_this_python_is_used_when_its_version_is_the_pin(self):
        run, calls = self.fake_run({lint_ratchet.sys.executable: "ruff 1.0.0"})
        with mock.patch.object(lint_ratchet, "run", run):
            self.assertEqual(lint_ratchet.launcher("ruff", "1.0.0"), [lint_ratchet.sys.executable, "-m", "ruff"])
        self.assertEqual(len(calls), 1)

    def test_uvx_runs_the_pin_when_this_python_has_another_version_or_none(self):
        run, calls = self.fake_run({lint_ratchet.sys.executable: "mypy 1.9.0 (compiled: yes)",
                                    "uvx": "mypy 2.0.0 (compiled: yes)"})
        with mock.patch.object(lint_ratchet, "run", run):
            self.assertEqual(lint_ratchet.launcher("mypy", "2.0.0"), ["uvx", "mypy@2.0.0"])

    def test_no_tool_at_the_pinned_version_stops_with_the_install_command(self):
        run, calls = self.fake_run({lint_ratchet.sys.executable: "ruff 0.9.0"})
        with mock.patch.object(lint_ratchet, "run", run), self.assertRaises(lint_ratchet.ToolError) as stop:
            lint_ratchet.launcher("ruff", "1.0.0")
        self.assertIn("pip install ruff==1.0.0", str(stop.exception))
        self.assertIn("0.9.0", str(stop.exception))

    def test_measure_counts_both_tools_and_flags_errors_outside_the_excluded_list(self):
        ruff = json.dumps([{"code": "I001"}, {"code": "I001"}])
        mypy = "\n".join(json.dumps(row) for row in (
            {"file": "src/openguildkit/old.py", "code": "arg-type", "severity": "error"},
            {"file": "src/openguildkit/new.py", "code": "union-attr", "severity": "error"},
        ))

        def run(command, **_options):
            return SimpleNamespace(returncode=1, stdout=ruff if command[0] == "ruff" else mypy, stderr="")

        with mock.patch.object(lint_ratchet, "launcher", lambda tool, _pin: [tool]), \
                mock.patch.object(lint_ratchet, "run", run):
            result = lint_ratchet.measure(CONFIG)
        self.assertEqual(result["counts"], {"ruff": {"I001": 2}, "mypy": {"arg-type": 1, "union-attr": 1}})
        self.assertEqual(result["stray"], ["src/openguildkit/new.py"])

    def test_a_tool_that_crashes_stops_the_run_instead_of_counting_zero(self):
        crashed = mock.Mock(return_value=SimpleNamespace(returncode=2, stdout="", stderr="boom"))
        with mock.patch.object(lint_ratchet, "launcher", lambda tool, _pin: [tool]), \
                mock.patch.object(lint_ratchet, "run", crashed), \
                self.assertRaises(lint_ratchet.ToolError) as stop:
            lint_ratchet.measure(CONFIG)
        self.assertIn("boom", str(stop.exception))


class CommittedFilesTests(unittest.TestCase):
    """The pins, the baseline and the CI job are written once and must agree."""

    @classmethod
    def setUpClass(cls):
        cls.pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        cls.config = lint_ratchet.read_config(ROOT / "pyproject.toml")
        cls.workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_the_tools_are_pinned_and_configured_in_pyproject(self):
        for tool in ("ruff", "mypy"):
            self.assertRegex(self.config[tool], r"^\d+\.\d+\.\d+$")
        self.assertIn("select", self.pyproject["tool"]["ruff"]["lint"])
        self.assertEqual(self.pyproject["tool"]["mypy"]["python_version"], "3.11")
        self.assertNotIn("dependencies", self.pyproject["project"], "the tools are not a runtime dependency")
        self.assertNotIn("optional-dependencies", self.pyproject["project"])

    def test_the_excluded_modules_exist_and_are_sorted_once(self):
        excluded = self.config["mypy_excluded"]
        self.assertEqual(excluded, sorted(set(excluded)))
        for path in excluded:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_the_baseline_is_counts_per_rule_for_the_two_tools(self):
        data = json.loads((ROOT / "scripts" / "lint-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(data), ["mypy", "ruff"])
        for counts in data.values():
            self.assertTrue(counts)
            self.assertTrue(all(isinstance(n, int) and n > 0 for n in counts.values()))
        text = (ROOT / "scripts" / "lint-baseline.json").read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps(data, indent=2, sort_keys=True) + "\n")

    def test_ci_installs_the_pinned_versions_and_the_gate_waits_for_the_job(self):
        install = re.search(r"pip install (ruff==\S+) (mypy==\S+)", self.workflow)
        self.assertTrue(install, "the lint job installs both tools")
        self.assertEqual(install.groups(), (f"ruff=={self.config['ruff']}", f"mypy=={self.config['mypy']}"))
        self.assertIn("python scripts/lint_ratchet.py", self.workflow)
        gate = self.workflow.split("  contribution-checks:", 1)[1]
        self.assertRegex(gate, r"needs: \[[^\]]*\blint\b")
        self.assertIn("needs.lint.result", gate)

    def test_the_fast_check_and_the_docs_know_the_script(self):
        check_fast = (ROOT / "scripts" / "check_fast.py").read_text(encoding="utf-8")
        self.assertIn('"scripts/lint_ratchet.py": ["tests/test_lint_ratchet.py"]', check_fast)
        self.assertIn("`test_lint_ratchet.py`", (ROOT / "docs" / "testing.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
