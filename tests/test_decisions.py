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
from openguildkit.clock import real_now
from openguildkit.decisions import decision_payload, payload_text, seal, verify_recorded_signature
from openguildkit.storage import write_json
from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


class DecisionTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

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

    def signed_by_two(self):
        """A committed signed project where camille and alex may approve, with camille's approval exported."""
        keys = self.keys("camille", "alex")
        lines = [f"{name}@example.org {(keys / f'{name}.pub').read_text().strip()}" for name in ("camille", "alex")]
        (self.root / "allowed_signers").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.git("init", "-q")
        self.reviewed({"approval": {"mode": "signed", "allowed_signers": "allowed_signers",
                                    "approvers": ["camille@example.org", "alex@example.org"]}})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "signers")
        self.run_cli("task", "decision-payload", TASK, "--by", "CM", "--reason", "Agreed", "--output", keys / "decision.json")
        with patch("sys.stdin.isatty", return_value=False):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "CM", "--reason", "Agreed",
                         "--signer", "camille@example.org", "--signature", self.sign(keys, "camille"))
        self.run_cli("task", "export", TASK)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "approved")
        self.publish()
        return keys

    def publish(self):
        """Push the branch to a bare origin, as merged work is: origin/HEAD then names its default branch."""
        origin = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, origin, ignore_errors=True)
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        self.git("fetch", "-q", "origin")
        self.git("remote", "set-head", "origin", "main")

    def camille_leaves(self, *, approvers=True, key=True):
        if approvers:
            project = self.root / ".openguildkit" / "project.json"
            profile = json.loads(project.read_text(encoding="utf-8"))
            profile["approval"]["approvers"] = ["alex@example.org"]
            write_json(project, profile)
            self.run_cli("sync")
        if key:
            signers = self.root / "allowed_signers"
            kept = [line for line in signers.read_text(encoding="utf-8").splitlines() if line.startswith("alex@")]
            signers.write_text("\n".join(kept) + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "camille leaves")

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_an_approval_signed_by_a_departed_approver_keeps_holding(self):
        for approvers, key in ((True, True), (True, False), (False, True)):
            with self.subTest(approvers=approvers, key=key), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                keys = self.signed_by_two()
                self.camille_leaves(approvers=approvers, key=key)
                _, said = self.run_cli("check")
                rows = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
                self.assertEqual([row.get("problem") for row in rows], [None])
                self.run_cli("task", "handoff", TASK)
                # The approval holds through an earlier revision, and task list and check name the signer and it.
                row, = json.loads(self.run_cli("task", "list", "--json")[0])
                self.assertEqual(row["severity"], "note")
                self.assertRegex(row["note"], r"signed by camille@example\.org, who is no longer a current approver: "
                                              r"it holds through the approvers and signers file of revision [0-9a-f]{12}")
                self.assertIn(f"OpenGuildKit: {TASK}: {row['note']}", said)
                self.assertEqual(len(json.loads(self.run_cli("guard", "--json")[0])["covered_by"]), 1)

                self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "second")
                self.run_cli("task", "consult", "second", "--answers", EXAMPLE / "answers.json")
                template = json.loads(self.run_cli("task", "template", "second")[0])
                review = {"consultation_id": template["consultation_id"],
                          **json.loads((EXAMPLE / "review.json").read_text())}
                write_json(self.root / "review.json", review)
                self.run_cli("task", "review", "second", "--file", self.root / "review.json")
                self.run_cli("task", "decision-payload", "second", "--by", "CM", "--reason", "Agreed",
                             "--output", keys / "decision.json")
                with patch("sys.stdin.isatty", return_value=False):
                    _, error = self.run_cli("task", "decide", "second", "--approve", "--by", "CM", "--reason", "Agreed",
                                            "--signer", "camille@example.org", "--signature", self.sign(keys, "camille"),
                                            code=1)
                self.assertRegex(error, "not an approver for this project|does not verify for camille")

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_ci_refuses_a_record_of_a_departed_approver_that_the_base_revision_does_not_carry(self):
        self.signed_by_two()
        self.camille_leaves()
        self.git("branch", "-M", "main")
        self.run_cli("guard", "--ci", "--base", "main")
        record = self.root / ".openguildkit" / "decisions" / f"{TASK}.json"
        kept = record.read_text(encoding="utf-8")
        self.git("rm", "-q", str(record))
        self.git("commit", "-q", "-m", "drop the record")
        self.git("checkout", "-q", "-b", "change")
        record.parent.mkdir(exist_ok=True)
        record.write_text(kept, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "bring it back")
        output, _ = self.run_cli("guard", "--ci", "--base", "main", "--json")
        result = json.loads(output)
        self.assertFalse(result["ok"])
        self.assertIn("camille@example.org is not an approver", " ".join(result["problems"]))

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_a_key_the_agent_committed_then_reverted_approves_nothing(self):
        """The third audit's replay, with no terminal: the agent commits its key as an approver, approves with it,
        then commits the files back. Only the merged branch's revisions can vouch for a departed signer."""
        keys = self.keys("pat", "mal")
        signers = self.root / "allowed_signers"
        signers.write_text(f"pat@example.org {(keys / 'pat.pub').read_text().strip()}\n", encoding="utf-8")
        self.git("init", "-q")
        self.reviewed({"guard": "enforce", "approval": {
            "mode": "signed", "allowed_signers": "allowed_signers", "approvers": ["pat@example.org"]}})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.publish()
        project = self.root / ".openguildkit" / "project.json"
        honest_profile, honest_signers = project.read_text(encoding="utf-8"), signers.read_text(encoding="utf-8")
        profile = json.loads(honest_profile)
        profile["approval"]["approvers"].append("MAL")
        write_json(project, profile)
        with signers.open("a", encoding="utf-8") as handle:
            handle.write(f"MAL {(keys / 'mal.pub').read_text().strip()}\n")
        self.run_cli("sync")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add a key")
        self.run_cli("task", "decision-payload", TASK, "--by", "MAL", "--reason", "Fine", "--output", keys / "decision.json")
        with patch("sys.stdin.isatty", return_value=False):
            approved, _ = self.run_cli("task", "decide", TASK, "--approve", "--by", "MAL", "--reason", "Fine",
                                       "--signer", "MAL", "--signature", self.sign(keys, "mal"))
        self.assertEqual(approved.strip(), "approved")
        project.write_text(honest_profile, encoding="utf-8")
        signers.write_text(honest_signers, encoding="utf-8")
        self.run_cli("sync")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "put the files back")

        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual((row["approval_problem"], row["severity"]), ("invalid-signature", "error"))
        self.assertIn("MAL is not an approver for this project", row["next"])
        self.assertIn("which origin/main does not contain", row["next"])
        self.assertIn("approval no longer holds", self.run_cli("task", "list")[0])
        _, error = self.run_cli("check", code=1)
        self.assertIn("MAL is not an approver", error)
        _, error = self.run_cli("task", "handoff", TASK, code=1)
        self.assertIn("MAL is not an approver", error)
        self.assertEqual(json.loads(self.run_cli("guard", "--json")[0])["covered_by"], [])
        edit = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}})
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch("sys.stdin", io.StringIO(edit)):
            self.assertEqual(main(["--project", str(self.root), "guard", "--hook", "pre-edit"]), 2)

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

    # Issue #478: certificates of an authority, and the time a signature was made.
    PRINCIPAL = "camille@example.org"

    def authority(self, valid: str = "-1h:+1h") -> Path:
        """A folder with an SSH authority, a key certified by it for PRINCIPAL during `valid` (ssh-keygen -V), and an
        allowed signers file that trusts the authority, not the key."""
        keys = self.keys("ca", "camille")
        subprocess.run(["ssh-keygen", "-q", "-s", str(keys / "ca"), "-I", "camille-certificate", "-n", self.PRINCIPAL,
                        "-V", valid, str(keys / "camille.pub")], check=True, capture_output=True)
        authority = " ".join((keys / "ca.pub").read_text().split()[:2])
        (self.root / "allowed_signers").write_text(f"{self.PRINCIPAL} cert-authority {authority}\n", encoding="utf-8")
        return keys

    def signed_project(self):
        self.git("init", "-q", "-b", "main")
        self.reviewed({"guard": "enforce", "approval": {
            "mode": "signed", "allowed_signers": "allowed_signers", "approvers": [self.PRINCIPAL]}})
        self.git("add", "allowed_signers", ".openguildkit/project.json")
        self.git("commit", "-q", "-m", "signers")

    def decide_signed(self, keys, name, signed_at=None, code=0):
        """decision-payload, the signature of `name`, then decide; signed_at goes to both commands."""
        option = ["--signed-at", signed_at] if signed_at else []
        self.run_cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed",
                     "--output", keys / "decision.json", *option)
        with patch("sys.stdin.isatty", return_value=False):
            return self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed",
                                "--signer", self.PRINCIPAL, "--signature", self.sign(keys, name), *option, code=code)

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_issue_478_a_certificate_of_the_authority_signs_an_approval(self):
        """Issue #478: a certificate signed by an authority (cert-authority) verified, and no test or page said so."""
        keys = self.authority()
        self.signed_project()
        self.decide_signed(keys, "camille-cert.pub")
        self.run_cli("task", "handoff", TASK)
        self.assertEqual(len(json.loads(self.run_cli("guard", "--json")[0])["covered_by"]), 1)
        # The authority vouches for the principal, not the key: the bare key signs nothing.
        self.run_cli("task", "revoke", TASK, "--by", "Camille", "--reason", "Again", typed=TASK)
        self.run_cli("task", "consult", TASK, "--reuse-answers")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        _, error = self.decide_signed(keys, "camille", code=1)
        self.assertIn("does not verify", error)

    @unittest.skipIf(shutil.which("ssh-keygen") is None, "needs ssh-keygen")
    def test_issue_478_an_approval_signed_while_the_certificate_was_valid_holds_after_it_expires(self):
        """Issue #478: the check ran at the current time, so an expiry invalidated every approval already recorded."""
        keys = self.authority("20250101:20250102")
        policy = {"mode": "signed", "allowed_signers": "allowed_signers", "approvers": [self.PRINCIPAL]}

        def refusal(**extra) -> str:
            """What verify_recorded_signature says about a payload signed with the certificate, empty when it holds."""
            payload = {"task": TASK, "outcome": "approved", **extra}
            (keys / "payload.json").write_bytes(payload_text(payload).encode("utf-8"))
            signature = self.sign(keys, "camille-cert.pub", "payload.json")
            try:
                verify_recorded_signature(self.root, policy, payload, signature.read_text(), self.PRINCIPAL,
                                          committed=False)
            except ValueError as error:
                return str(error)
            return ""

        self.assertIn("Certificate invalid: expired", refusal())
        self.assertEqual(refusal(signed_at="2025-01-01T12:00:00Z"), "")
        self.assertIn("Certificate invalid: expired", refusal(signed_at="2025-01-03T12:00:00Z"))
        self.assertIn("YYYY-MM-DDTHH:MM:SSZ", refusal(signed_at="yesterday"))

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_issue_478_task_decide_verifies_at_the_current_time_and_refuses_a_signature_after_the_expiry(self):
        """Issue #478: a new approval is judged now, whatever time the signature claims."""
        keys = self.authority("20250101:20250102")
        self.signed_project()
        for claimed in ("2026-01-15T10:00:00Z", "2025-01-01T12:00:00Z"):
            with self.subTest(claimed=claimed):
                _, error = self.decide_signed(keys, "camille-cert.pub", claimed, code=1)
                self.assertIn("Certificate invalid: expired", error)
        for claimed, said in (("2099-01-01T00:00:00Z", "in the future"), ("tomorrow", "YYYY-MM-DDTHH:MM:SSZ")):
            for command in (("decision-payload",), ("decide", "--approve", "--signer", self.PRINCIPAL, "--signature",
                                                    keys / "decision.json.sig")):
                _, error = self.run_cli("task", command[0], TASK, "--by", "Camille", "--reason", "Agreed", *command[1:],
                                        "--signed-at", claimed, code=1)
                self.assertIn(said, error)
        self.assertEqual(json.loads(self.task_path().read_text())["status"], "reviewed")

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_issue_478_the_time_of_the_signature_is_signed_and_changing_it_breaks_the_signature(self):
        """Issue #478: signed_at is part of what the approver signs and of the seal."""
        keys = self.keys("camille")
        (self.root / "allowed_signers").write_text(
            f"{self.PRINCIPAL} {(keys / 'camille.pub').read_text().strip()}\n", encoding="utf-8")
        self.signed_project()
        moment = "2026-01-15T10:00:00Z"
        self.run_cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed", "--signed-at", moment,
                     "--output", keys / "decision.json")
        self.assertEqual(json.loads((keys / "decision.json").read_text())["signed_at"], moment)
        signature = self.sign(keys, "camille")
        decide = ["task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", "--signer",
                  self.PRINCIPAL, "--signature", signature]
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli(*decide, code=1)
            self.assertIn("does not verify", error)
            self.assertIn("--signed-at", error)
            _, error = self.run_cli(*decide, "--signed-at", "2026-01-15T10:00:01Z", code=1)
            self.assertIn("does not verify", error)
            self.run_cli(*decide, "--signed-at", moment)
        record = json.loads(self.task_path().read_text())
        self.assertEqual(record["decision"]["signed_at"], moment)
        self.run_cli("task", "handoff", TASK)
        record["decision"]["signed_at"] = "2026-01-15T10:00:01Z"
        self.task_path().write_text(json.dumps(record), encoding="utf-8")
        _, error = self.run_cli("task", "handoff", TASK, code=1)
        self.assertIn("no longer matches what was approved", error)

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_issue_478_a_signature_without_signed_at_is_what_it_was_before(self):
        """Issue #478: nothing changes for an approver who does not ask for signed_at."""
        keys = self.keys("camille")
        (self.root / "allowed_signers").write_text(
            f"{self.PRINCIPAL} {(keys / 'camille.pub').read_text().strip()}\n", encoding="utf-8")
        self.signed_project()
        refused = self.run_cli("task", "decide", TASK, "--signed-at", "2026-01-15T10:00:00Z", "--request-changes",
                               "--by", "Camille", "--reason", "x", code=1)[1]
        self.assertIn("goes with approving", refused)
        self.decide_signed(keys, "camille")
        self.assertNotIn("signed_at", json.loads((keys / "decision.json").read_text()))
        self.assertNotIn("signed_at", json.loads(self.task_path().read_text())["decision"])

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_issue_478_guard_ci_refuses_a_signature_later_than_the_commit_that_brings_the_record(self):
        """Issue #478: a signed_at after the date of the commit that carries the record cannot be true."""
        keys = self.keys("camille")
        (self.root / "allowed_signers").write_text(
            f"{self.PRINCIPAL} {(keys / 'camille.pub').read_text().strip()}\n", encoding="utf-8")
        self.signed_project()
        self.git("checkout", "-q", "-b", "late")
        moment = real_now().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.decide_signed(keys, "camille", moment)
        self.run_cli("task", "export", TASK)
        record = f".openguildkit/decisions/{TASK}.json"
        self.git("add", "-f", record)
        for branch, date in (("late", "2020-01-01T00:00:00Z"), ("on-time", "2099-01-01T00:00:00Z")):
            if branch == "on-time":
                self.git("checkout", "-q", "-b", branch, "main")
                self.git("checkout", "late", "--", record)
            subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "record"], check=True, capture_output=True,
                           env={**os.environ, "GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date})
            late = branch == "late"
            result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json", code=1 if late else 0)[0])
            self.assertEqual(result["ok"], not late, result)
            if late:
                self.assertIn("signed at", " ".join(result["problems"]))
                sarif = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--format", "sarif", code=1)[0])
                self.assertIn("decision-signed-late", {item["ruleId"] for item in sarif["runs"][0]["results"]})


if __name__ == "__main__":
    unittest.main()
