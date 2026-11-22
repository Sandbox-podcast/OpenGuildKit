"""The suite keeps one way to run the CLI, so that a faster or safer runner reaches every test at once."""

import ast
import re
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

    def test_run_cli_runs_in_this_process_and_reports_the_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            result = support.run_cli(Path(folder), "--version")
            self.assertTrue(result.stdout.strip())
            usage = support.run_cli(Path(folder), "task", "decide", expect=2)
        self.assertIn("usage:", usage.stderr)


if __name__ == "__main__":
    unittest.main()
