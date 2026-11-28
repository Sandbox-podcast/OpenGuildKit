"""The suite keeps one way to run the CLI, so that a faster or safer runner reaches every test at once."""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
# A helper that runs the CLI itself: it calls main() or starts python -m openguildkit.
RUNS_THE_CLI = re.compile(r"""(?<![\w.])main\(|["']-m["'],\s*["']openguildkit["']""")
MAX_RUNNERS = 10


def cli_runners() -> list[str]:
    """The helpers outside tests/support.py that run the CLI themselves, as FILE:LINE NAME."""
    found = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name == "support.py":
            continue
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith(("test", "setUp")):
                if RUNS_THE_CLI.search(ast.get_source_segment(text, node)):
                    found.append(f"{path.relative_to(TESTS).as_posix()}:{node.lineno} {node.name}")
    return found


class CliRunnerTests(unittest.TestCase):
    def test_tests_run_the_cli_through_the_shared_support(self):
        runners = cli_runners()
        self.assertLessEqual(len(runners), MAX_RUNNERS,
                             "Run the CLI with tests.support.run_cli or CliMixin.run_cli:\n" + "\n".join(runners))

    def test_the_search_finds_a_new_copy(self):
        copy = 'def run(self):\n    return main(["--project", str(self.root), "check"])\n'
        self.assertTrue(RUNS_THE_CLI.search(copy))
        self.assertFalse(RUNS_THE_CLI.search("def run(self):\n    return run_cli(self.root, 'check')\n"))

    def test_a_child_process_writes_its_bytecode_outside_the_repository(self):
        environment = support.subprocess_environment()
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", environment)
        prefix = Path(environment["PYTHONPYCACHEPREFIX"]).resolve()
        self.assertNotIn(REPO, prefix.parents)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_a_helper_commit_passes_when_the_contributor_signs_every_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            # A contributor's global configuration that signs every commit and tag, with a key and a signing
            # program that do not exist: any commit that reads it fails, and no real key or agent is reached.
            signing = folder / "signing.gitconfig"
            signing.write_text(
                "[user]\n\tname = Signing Contributor\n\temail = signer@example.invalid\n"
                "\tsigningkey = 0000000000000000000000000000000000000000\n"
                "[commit]\n\tgpgsign = true\n[tag]\n\tgpgsign = true\n"
                f"[gpg]\n\tprogram = {(folder / 'no-such-gpg').as_posix()}\n", encoding="utf-8")
            repo = folder / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
            signed = subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "signed"],
                                    capture_output=True, text=True,
                                    env={**os.environ, "GIT_CONFIG_GLOBAL": str(signing)})
            self.assertNotEqual(signed.returncode, 0, "the signing configuration must break a commit")
            self.assertIn("sign", signed.stderr)

            # A fresh test process on that machine: no Git variable but the global configuration.
            environment = {key: value for key, value in support.subprocess_environment().items()
                           if not key.startswith("GIT_")}
            environment.update(GIT_CONFIG_GLOBAL=str(signing),
                               PYTHONPATH=os.pathsep.join([str(REPO), str(REPO / "src")]))
            helper = (
                "import subprocess, sys\n"
                "from tests import support\n"
                "repo = sys.argv[1]\n"
                "subprocess.run(['git', '-C', repo, 'commit', '-q', '--allow-empty', '-m', 'test'], check=True)\n"
                "subprocess.run(['git', '-C', repo, 'commit', '-q', '--allow-empty', '-m', 'child'], check=True,\n"
                "               env=support.subprocess_environment())\n"
                "subprocess.run(['git', '-C', repo, 'tag', '-a', 'v1', '-m', 'tag'], check=True)\n"
            )
            result = subprocess.run([sys.executable, "-c", helper, str(repo)], cwd=REPO, env=environment,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_cli_runs_in_this_process_and_reports_the_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            result = support.run_cli(Path(folder), "--version")
            self.assertTrue(result.stdout.strip())
            usage = support.run_cli(Path(folder), "task", "decide", expect=2)
        self.assertIn("usage:", usage.stderr)


PASSING = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n"
FAILING = ("import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n"
           "        self.assertEqual('kept', 'trace of the failure')\n")
SLOW = "import time\nimport unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        time.sleep(30)\n"


class ParallelRunnerTests(unittest.TestCase):
    """scripts/run_tests.py: one process per test file, several at once, with the verdict of unittest discover."""

    def tree(self, files: dict[str, str]) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        for name, text in {"tests/__init__.py": "", **files}.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
        (root / "scripts").mkdir()
        shutil.copy(REPO / "scripts" / "run_tests.py", root / "scripts" / "run_tests.py")
        return root

    def run_both(self, root: Path) -> tuple[subprocess.CompletedProcess, int]:
        parallel = subprocess.run([sys.executable, "scripts/run_tests.py", "--jobs", "2"], cwd=root,
                                  capture_output=True, text=True, check=False, env=support.subprocess_environment())
        discover = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root,
                                  capture_output=True, text=True, check=False, env=support.subprocess_environment())
        return parallel, discover.returncode

    def test_issue_451_a_failing_file_prints_its_whole_trace_and_fails_like_discover(self):
        """Issue #451: the suite runs one file per process, and a failure keeps its trace and its exit code."""
        root = self.tree({"tests/test_ok.py": PASSING, "tests/test_bad.py": FAILING,
                          "tests/e2e/__init__.py": "", "tests/e2e/test_deep.py": PASSING,
                          "tests/fixtures/test_not_a_package.py": FAILING})
        parallel, discover = self.run_both(root)
        self.assertEqual((parallel.returncode != 0, discover != 0), (True, True), parallel.stdout)
        self.assertIn("===== tests/test_bad.py failed", parallel.stdout)
        self.assertIn("AssertionError: 'kept' != 'trace of the failure'", parallel.stdout)
        self.assertNotIn("test_ok", parallel.stdout)
        self.assertIn("3 test file(s), 3 tests, 1 failed", parallel.stdout)
        (root / "tests" / "test_bad.py").write_text(PASSING, encoding="utf-8")
        parallel, discover = self.run_both(root)
        self.assertEqual((parallel.returncode, discover), (0, 0), parallel.stdout)
        self.assertEqual(parallel.stdout.count("\n"), 1, parallel.stdout)

    def test_issue_451_a_failure_or_the_deadline_stops_what_runs_and_starts_nothing_more(self):
        """Issue #451: with stop_on_failure or past the deadline, the files left are named, not run."""
        root = self.tree({"tests/test_slow.py": SLOW, "tests/test_bad.py": FAILING, "tests/test_ok.py": PASSING})
        runner = support.load_script(root / "scripts" / "run_tests.py")
        stopped = runner.run(["tests/test_slow.py", "tests/test_bad.py", "tests/test_ok.py"], 2, stop_on_failure=True,
                             root=root)
        self.assertEqual([path for path, _ in stopped["failed"]], ["tests/test_bad.py"])
        self.assertEqual((stopped["stopped"], stopped["not_run"]), (["tests/test_slow.py"], ["tests/test_ok.py"]))
        self.assertLess(stopped["seconds"], 20)
        late = runner.run(["tests/test_slow.py", "tests/test_ok.py"], 1, deadline=0, root=root)
        self.assertEqual((late["passed"], late["failed"]), ([], []))
        self.assertEqual(late["stopped"] + late["not_run"], ["tests/test_slow.py", "tests/test_ok.py"])


if __name__ == "__main__":
    unittest.main()
