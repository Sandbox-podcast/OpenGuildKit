"""The host validation scenario runs end to end with the CLI, as a host without subagents."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import run_cli

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "examples" / "host-validation" / "rehearse.py"


def load_rehearsal():
    spec = importlib.util.spec_from_file_location("host_rehearsal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_here(project: Path, *args: str) -> subprocess.CompletedProcess:
    """The script's run(), with the CLI in this process; the person's decision still types at a real terminal."""
    return run_cli(project, *args, stdin="", expect=None)


class HostRehearsalTests(unittest.TestCase):
    def test_rehearsal_covers_disagreement_insufficient_evidence_decision_and_results(self):
        rehearsal = load_rehearsal()
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            argv = [str(SCRIPT), "--project", str(Path(directory) / "project-root"), "--report", str(report)]
            with mock.patch.object(rehearsal, "run", run_here), mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(io.StringIO()):
                rehearsal.main()
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

    def test_the_script_runs_on_its_own(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                                encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--report", result.stdout)


if __name__ == "__main__":
    unittest.main()
