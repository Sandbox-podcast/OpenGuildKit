"""web/scripts/sample-project.py reads its options before it creates a project."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import subprocess_environment

SCRIPT = Path(__file__).resolve().parents[1] / "web" / "scripts" / "sample-project.py"


class SampleProjectOptionsTests(unittest.TestCase):
    def run_script(self, *arguments: str) -> tuple[subprocess.CompletedProcess, list[str]]:
        """Run the script in an empty folder; return its result and what it left in the folder."""
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(SCRIPT), *arguments], cwd=folder, capture_output=True,
                                    text=True, encoding="utf-8", env=subprocess_environment(), timeout=120)
            return result, sorted(path.name for path in Path(folder).iterdir())

    def test_help_prints_the_usage_and_creates_nothing(self):
        result, created = self.run_script("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("--gdpr", result.stdout)
        self.assertEqual(created, [])

    def test_an_argument_that_starts_with_a_dash_is_refused_with_the_usage(self):
        for argument in ("-v", "--gpdr"):
            with self.subTest(argument=argument):
                result, created = self.run_script(argument)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("usage:", result.stderr)
                self.assertEqual(created, [])


if __name__ == "__main__":
    unittest.main()
