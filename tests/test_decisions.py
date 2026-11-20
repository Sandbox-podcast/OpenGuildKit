import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.storage import write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


class DecisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"})

    def reviewed(self, profile_extra=None):
        profile = {**json.loads((EXAMPLE / "profile.json").read_text()), **(profile_extra or {})}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")

    def approve(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Scope agreed")

    def task_path(self):
        return self.root / ".openguildkit" / "tasks" / f"{TASK}.json"

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_the_approval_records_the_consultation_rules_and_base_revision(self):
        self.git("init", "-q")
        self.reviewed()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")
        self.approve()
        decision = json.loads(self.task_path().read_text())["decision"]
        head = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(decision["base_revision"]["commit"], head)
        self.assertEqual(len(decision["seal"]), 64)
        self.run_cli("task", "handoff", TASK)

        self.git("commit", "-q", "--allow-empty", "-m", "rewritten", "--amend")
        _, error = self.run_cli("task", "handoff", TASK, code=1)
        self.assertIn("no longer in the project history", error)

    def test_a_decision_edited_outside_the_cli_is_refused(self):
        self.reviewed()
        record = json.loads(self.task_path().read_text())
        record["status"] = "approved"
        record["decision"] = {"outcome": "approved", "by": "Agent", "reason": "Self-approved", "at": "2026-11-20T00:00:00+00:00"}
        self.task_path().write_text(json.dumps(record), encoding="utf-8")
        _, error = self.run_cli("task", "handoff", TASK, code=1)
        self.assertIn("no seal", error)

        self.task_path().unlink()
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        self.approve()
        record = json.loads(self.task_path().read_text())
        record["review"]["summary"] = "A different review."
        self.task_path().write_text(json.dumps(record), encoding="utf-8")
        _, error = self.run_cli("task", "handoff", TASK, code=1)
        self.assertIn("no longer matches what was approved", error)

    @unittest.skipIf(shutil.which("ssh-keygen") is None, "needs ssh-keygen")
    def test_a_signed_project_verifies_the_approver(self):
        keys = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keys, ignore_errors=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "camille")], check=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "intruder")], check=True)
        public = (keys / "camille.pub").read_text().strip()
        (self.root / "allowed_signers").write_text(f"camille@example.org {public}\n", encoding="utf-8")
        self.reviewed({"approval": {"mode": "signed", "allowed_signers": "allowed_signers", "approvers": ["camille@example.org"]}})
        _, error = self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", code=1)
        self.assertIn("requires a signed approval", error)

        self.run_cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed",
                     "--output", keys / "decision.json")
        for name in ("camille", "intruder"):
            subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / name), "-n", "openguildkit-decision",
                            str(keys / "decision.json")], check=True, capture_output=True)
            (keys / "decision.json.sig").rename(keys / f"{name}.sig")
        common = ["task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", "--signer", "camille@example.org"]
        _, error = self.run_cli(*common, "--signature", keys / "intruder.sig", code=1)
        self.assertIn("does not verify", error)
        with patch("sys.stdin.isatty", return_value=False):
            self.run_cli(*common, "--signature", keys / "camille.sig")
        self.run_cli("task", "handoff", TASK)


if __name__ == "__main__":
    unittest.main()
