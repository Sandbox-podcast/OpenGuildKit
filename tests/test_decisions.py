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
from openguildkit.decisions import decision_payload, seal
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
        for command in ("handoff", "export"):
            _, error = self.run_cli("task", command, TASK, code=1)
            self.assertIn("no longer matches what was approved", error)
        output, _ = self.run_cli("task", "list", "--json")
        task, = json.loads(output)
        self.assertIsNone(task["owner"])
        self.assertEqual(task["approval_problem"], "invalid-seal")
        _, error = self.run_cli("check", code=1)
        self.assertIn("no longer matches what was approved", error)

    def keys(self, *names):
        """A folder outside the project with a synthetic SSH key pair per name."""
        keys = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keys, ignore_errors=True)
        for name in names:
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / name)], check=True)
        return keys

    def sign(self, keys, name, payload_name="decision.json"):
        """Sign the payload with a key; ssh-keygen would ask before replacing an earlier signature."""
        signature = keys / f"{payload_name}.sig"
        signature.unlink(missing_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / name), "-n", "openguildkit-decision",
                        str(keys / payload_name)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
        return signature

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_a_signed_project_verifies_the_approver(self):
        keys = self.keys("camille", "intruder")
        public = (keys / "camille.pub").read_text().strip()
        (self.root / "allowed_signers").write_text(f"camille@example.org {public}\n", encoding="utf-8")
        self.git("init", "-q")
        self.reviewed({"approval": {"mode": "signed", "allowed_signers": "allowed_signers", "approvers": ["camille@example.org"]}})
        self.git("add", "allowed_signers")
        self.git("commit", "-q", "-m", "signers")
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

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_a_signature_is_verified_against_the_signers_file_committed_in_git(self):
        keys = self.keys("camille")
        signers = self.root / "allowed_signers"
        signers.write_text(f"camille@example.org {(keys / 'camille.pub').read_text().strip()}\n", encoding="utf-8")
        self.git("init", "-q")
        self.reviewed({"approval": {"mode": "signed", "allowed_signers": "allowed_signers", "approvers": ["camille@example.org"]}})
        self.run_cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed", "--output", keys / "decision.json")
        decide = ["task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed",
                  "--signer", "camille@example.org", "--signature", self.sign(keys, "camille")]
        _, error = self.run_cli(*decide, code=1)
        self.assertIn("The allowed signers file allowed_signers is not committed", error)
        self.git("add", "allowed_signers")
        _, error = self.run_cli(*decide, code=1)
        self.assertIn("allowed_signers is not committed", error)
        self.git("commit", "-q", "-m", "signers")
        with signers.open("a", encoding="utf-8") as handle:
            handle.write("alex@example.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK\n")
        _, error = self.run_cli(*decide, code=1)
        self.assertIn("The allowed signers file allowed_signers differs from its version at HEAD", error)
        self.git("checkout", "--", "allowed_signers")
        self.run_cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed", "--output", keys / "decision.json")
        decide[-1] = self.sign(keys, "camille")
        self.assertEqual(self.run_cli(*decide)[0].strip(), "approved")

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_a_key_the_agent_adds_to_the_signers_file_approves_nothing(self):
        """The audit's replay: the agent appends its key, signs with it and approves with no terminal."""
        keys = self.keys("pat", "agent")
        signers = self.root / ".openguildkit" / "allowed_signers"
        signers.parent.mkdir()
        signers.write_text(f"pat@example.org {(keys / 'pat.pub').read_text().strip()}\n", encoding="utf-8")
        self.git("init", "-q")
        self.reviewed({"guard": "enforce", "approval": {
            "mode": "signed", "allowed_signers": ".openguildkit/allowed_signers", "approvers": ["pat@example.org"]}})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        edit = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": ".openguildkit/allowed_signers"}})
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch("sys.stdin", io.StringIO(edit)):
            self.assertEqual(main(["--project", str(self.root), "guard", "--hook", "pre-edit"]), 2)
        self.assertIn(".openguildkit/allowed_signers lists the keys that may sign approvals", stderr.getvalue())

        with signers.open("a", encoding="utf-8") as handle:
            handle.write(f'pat@example.org namespaces="openguildkit-decision" {(keys / "agent.pub").read_text().strip()}\n')
        self.run_cli("task", "decision-payload", TASK, "--by", "Pat Example", "--reason", "Looks fine to me",
                     "--output", keys / "decision.json")
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("task", "decide", TASK, "--approve", "--by", "Pat Example", "--reason", "Looks fine to me",
                                    "--signature", self.sign(keys, "agent"), "--signer", "pat@example.org", code=1)
        self.assertIn(".openguildkit/allowed_signers differs from its version at HEAD", error)
        self.assertEqual(json.loads(self.task_path().read_text())["status"], "reviewed")
        self.assertEqual(json.loads(self.run_cli("guard", "--json")[0])["covered_by"], [])

    def forge_approval(self):
        """What an agent can do with file access alone: approve the task and recompute its seal."""
        record = json.loads(self.task_path().read_text())
        payload = decision_payload(record, "Camille", "Looks fine", None)
        record["status"] = "approved"
        record["decision"] = {"outcome": "approved", "by": "Camille", "reason": "Looks fine",
                              "at": "2026-11-20T00:00:00+00:00", "base_revision": None, "seal": seal(payload)}
        self.task_path().write_text(json.dumps(record), encoding="utf-8")

    def test_a_signed_project_refuses_an_approval_written_into_the_task_file(self):
        (self.root / "allowed_signers").write_text("camille@example.org ssh-ed25519 AAAA\n", encoding="utf-8")
        self.reviewed({"guard": "enforce", "approval": {
            "mode": "signed", "allowed_signers": "allowed_signers", "approvers": ["camille@example.org"]}})
        self.forge_approval()
        for command in (("task", "handoff", TASK), ("task", "export", TASK)):
            _, error = self.run_cli(*command, code=1)
            self.assertIn("requires a signed approval", error)
        self.assertEqual(json.loads(self.run_cli("guard", "--json")[0])["covered_by"], [])

    def test_a_local_seal_does_not_prove_who_approved_so_the_guard_keeps_agents_out_of_task_files(self):
        self.reviewed({"guard": "enforce"})
        edit = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(self.task_path())}})
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch("sys.stdin", io.StringIO(edit)):
            self.assertEqual(main(["--project", str(self.root), "guard", "--hook", "pre-edit"]), 2)
        self.forge_approval()
        self.run_cli("task", "handoff", TASK)


if __name__ == "__main__":
    unittest.main()
