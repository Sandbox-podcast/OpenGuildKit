"""The host validation scenario runs end to end with the CLI, as a host without subagents."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import subprocess_environment

REPO = Path(__file__).resolve().parents[2]


class HostRehearsalTests(unittest.TestCase):
    def test_rehearsal_covers_disagreement_insufficient_evidence_decision_and_results(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, str(REPO / "examples" / "host-validation" / "rehearse.py"),
                 "--project", str(Path(directory) / "project-root"), "--report", str(report)],
                capture_output=True, text=True, encoding="utf-8", timeout=300, stdin=subprocess.DEVNULL,
                env=subprocess_environment({"PYTHONPATH": str(REPO / "src")}),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(observed["passes_done"])
        self.assertTrue(all(observed["briefs_scoped"]))
        self.assertTrue(any(item.startswith("security-to-") for item in observed["objections"]), observed["objections"])
        self.assertTrue(observed["insufficient_evidence"])
        self.assertTrue(observed["agent_cannot_clear"])
        if os.name == "posix":
            self.assertTrue(observed["cleared"])
            self.assertTrue(observed["approved"])
            self.assertTrue(observed["completed"], observed.get("completion_message"))


if __name__ == "__main__":
    unittest.main()
