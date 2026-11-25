"""Determinism: the same inputs give byte-identical outputs, wherever and whenever they run.

Two teams that set up the same profile and frame the same task must get the same
instructions, consultation and decision brief. Each run uses a fresh project in a
different folder and a different PYTHONHASHSEED, so set or dict ordering that
depends on the hash seed, or a path that leaks into an output, fails here. The
consultation ID is random by design and is replaced before comparing.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.e2e.test_cli_flow import EXAMPLE, REPO, TASK_ID
from tests.support import run_cli, subprocess_environment

SEEDS = ("0", "1", "4242")


# One process per hash seed: it plays the commands in itself, as the suite does, and prints their outputs as JSON.
CHILD = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from tests.test_determinism import Run\n"
    "run = Run(Path(sys.argv[2]))\n"
    "print(json.dumps(run.play() if sys.argv[3] == 'play' else run.read_only()))\n"
)


def under_seed(folder: Path, seed: str, what: str) -> dict | list:
    """Run.play() or Run.read_only() in a Python process started with this PYTHONHASHSEED."""
    result = subprocess.run([sys.executable, "-c", CHILD, str(REPO), str(folder), what], capture_output=True,
                            text=True, encoding="utf-8", env=subprocess_environment({"PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO / "src")}), timeout=300)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class Run:
    """One fresh project and its outputs, from the commands run in this process."""

    def __init__(self, folder: Path):
        self.project = folder
        self.outputs = {}

    def cli(self, *args) -> str:
        result = run_cli(self.project, *args, stdin="", expect=None)
        if result.returncode:
            raise AssertionError(f"openguildkit {' '.join(map(str, args))}: {result.stderr}")
        return result.stdout

    def read_only(self) -> list:
        return [self.cli("catalog", "--json"), self.cli("brains", "--json"),
                self.cli("recommend", "--answers", EXAMPLE / "profile.json", "--json"), self.cli("references", "--json")]

    def record(self, name: str, *args) -> None:
        self.outputs[name] = self.cli(*args)

    def play(self) -> dict:
        self.record("catalog --json", "catalog", "--json")
        self.record("recommend --json", "recommend", "--answers", EXAMPLE / "profile.json", "--json")
        self.record("preview --json", "preview", "--answers", EXAMPLE / "profile.json", "--json")
        self.cli("init", "--answers", EXAMPLE / "profile.json")
        self.outputs["AGENTS.md"] = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.outputs["CLAUDE.md"] = (self.project / "CLAUDE.md").read_text(encoding="utf-8")
        self.outputs["project.json"] = (self.project / ".openguildkit" / "project.json").read_text(encoding="utf-8")
        self.outputs["catalog.lock.json"] = (self.project / ".openguildkit" / "catalog.lock.json").read_text(encoding="utf-8")
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.record("task route --json", "task", "route", TASK_ID, "--answers", EXAMPLE / "answers.json", "--json")
        self.record("task consult", "task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")
        consultation_id = json.loads(self.cli("task", "template", TASK_ID))["consultation_id"]
        self.record("task template", "task", "template", TASK_ID)
        self.record("task pass security", "task", "pass", TASK_ID, "security")
        review = {"consultation_id": consultation_id, **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        review_file = self.project / "review.json"
        review_file.write_text(json.dumps(review), encoding="utf-8")
        self.cli("task", "review", TASK_ID, "--file", review_file)
        self.record("task challenge", "task", "challenge", TASK_ID)
        self.record("task deliberate", "task", "deliberate", TASK_ID)
        # Two instructions files and the ignore file out of date: three findings, which no hash order may reorder.
        (self.project / ".openguildkit" / ".gitignore").write_text("work/\n", encoding="utf-8")
        (self.project / "CLAUDE.md").write_text("# Notes\n", encoding="utf-8")
        self.outputs["check --format sarif"] = run_cli(self.project, "check", "--format", "sarif", stdin="", expect=1).stdout
        return {name: text.replace(consultation_id, "CONSULTATION-ID") for name, text in self.outputs.items()}


class DeterminismTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="ogk-determinism-")).resolve()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def test_two_teams_get_byte_identical_outputs(self):
        folders = [self.base / "team-a" / "project", self.base / "Équipe B" / "deeper" / "other-name"]
        runs = []
        for folder, seed in zip(folders, SEEDS):
            folder.mkdir(parents=True)
            runs.append(under_seed(folder, seed, "play"))
        first, second = runs
        self.assertEqual(sorted(first), sorted(second))
        for name in first:
            with self.subTest(output=name):
                self.assertEqual(first[name], second[name])
        self.assertIn("<!-- BEGIN OPENGUILDKIT", first["AGENTS.md"])
        self.assertIn("# Decision brief", first["task challenge"])
        self.assertEqual(json.loads(first["check --format sarif"])["runs"][0]["results"][0]["ruleId"], "instructions-drift")
        for name, text in first.items():
            self.assertNotIn(str(self.base), text, name)

    def test_read_only_outputs_do_not_depend_on_the_hash_seed(self):
        folder = self.base / "seeds"
        folder.mkdir()
        outputs = {tuple(under_seed(folder, seed, "read")) for seed in SEEDS}
        self.assertEqual(len(outputs), 1)


if __name__ == "__main__":
    unittest.main()
