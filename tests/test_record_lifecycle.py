"""What CI accepts of an exported record over its life: where it sits, the history its approval names, its
withdrawal, and the closing order the README gives (issues #275, #277, #279, #280)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.decisions import export_digest
from openguildkit.guard_ci import _base_files, _earlier_records
from openguildkit.storage import write_json
from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
RECORD = f".openguildkit/decisions/{TASK}.json"


@unittest.skipIf(shutil.which("git") is None, "needs git")
class RecordLifecycleTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True,
                              env=GIT_ENV).stdout

    def init(self, **extra):
        command = f'"{sys.executable}" -c "print(1)"'
        profile = {"name": "Support portal", "stack": ["Python"], "packs": [], "checks": [command],
                   "guard": "enforce", "personal_data": "no", **extra}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")
        (self.root / "profile.json").unlink()

    def main_branch(self, **extra):
        self.git("init", "-q", "-b", "main")
        (self.root / "README.md").write_text("Suport portal\n", encoding="utf-8")
        self.init(**extra)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def reviewed(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each request's status."}
        write_json(self.root.parent / f"{self.root.name}-answers.json", answers)
        self.run_cli("task", "consult", TASK, "--answers", self.root.parent / f"{self.root.name}-answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root.parent / f"{self.root.name}-review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root.parent / f"{self.root.name}-review.json")
        for name in ("answers", "review"):
            self.addCleanup((self.root.parent / f"{self.root.name}-{name}.json").unlink, missing_ok=True)

    def approve(self):
        self.reviewed()
        self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", typed=TASK)

    def complete(self):
        self.run_cli("task", "verify", TASK)
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        rules = [{"check": c["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"}
                 for c in checks if c["kind"] == "rule"]
        result = self.root.parent / f"{self.root.name}-result.json"
        self.addCleanup(result.unlink, missing_ok=True)
        write_json(result, {"pull_request": "https://github.com/example/portal/pull/7", "checks": rules,
                            "criteria": [{"criterion": "Users only see their own requests.", "status": "met",
                                          "evidence": "tests/test_access.py"}]})
        self.run_cli("task", "result", TASK, "--file", result)
        return self.run_cli("task", "complete", TASK)

    def write(self, relative, text="x\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def ci(self, code=0):
        return json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json", code=code)[0])

    def commit_all(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    # Issue #275: a record anywhere below decisions/.

    def test_ci_refuses_a_record_below_the_decisions_folder_and_reads_the_base_at_any_depth(self):
        self.main_branch()
        self.approve()
        self.write("README.md", "Support portal\n")
        self.git("commit", "-q", "-am", "fix the typo")
        archived = ".openguildkit/decisions/archive/request-status.json"
        self.run_cli("task", "export", TASK, "--output", self.root / archived)
        self.git("add", "-f", archived)
        self.git("commit", "-q", "-m", "merged decision, archived")
        self.assertIn(TASK, _earlier_records(_base_files(self.root, "main", [archived])))

        self.git("checkout", "-q", "-b", "payments")
        self.write("payments.py", "charge()\n")
        record = json.loads((self.root / archived).read_text())
        record["files"] = [*record["files"], "payments.py"]
        record["record_sha256"] = export_digest(record)
        write_json(self.root / archived, record)
        self.commit_all("payments")
        result = self.ci(code=1)
        self.assertEqual(result["decisions"], [])
        self.assertIn(f"{archived} is not directly under .openguildkit/decisions/", result["problems"][0])
        text = self.run_cli("guard", "--ci", "--base", "main", code=1)[0]
        self.assertNotIn("Covered by", text)

        # Moved to the folder itself, the stretched list meets the base record at its depth: only README.md counts.
        self.git("mv", archived, RECORD)
        self.git("commit", "-q", "-m", "move the record")
        result = self.ci(code=1)
        self.assertEqual(result["decisions"], [TASK])
        self.assertIn("in no decision record of this change: payments.py", result["problems"][-1])

    def test_covered_names_the_record_it_read(self):
        self.main_branch()
        self.git("checkout", "-q", "-b", "typo")
        self.approve()
        self.write("README.md", "Support portal\n")
        self.git("commit", "-q", "-am", "fix the typo")
        self.git("add", self.run_cli("task", "export", TASK)[0].strip())
        self.git("commit", "-q", "-m", "decision")
        self.assertEqual(self.ci()["records"], {TASK: RECORD})
        self.assertIn(f"Covered by the decision of task {TASK} ({RECORD}).",
                      self.run_cli("guard", "--ci", "--base", "main")[0])

    # Issue #280: an approval given on a revision the pull request does not contain.

    def abandoned_approval(self, **extra):
        """t2 approved on a throwaway branch at its own commit, exported, the branch deleted."""
        self.main_branch(**extra)
        self.git("checkout", "-q", "-b", "throwaway")
        self.write("scratch.py", "pass\n")
        self.commit_all("throwaway work")
        commit = self.git("rev-parse", "HEAD").strip()
        return commit

    def copy_into_another_pull_request(self, record):
        self.git("checkout", "-q", "main")
        self.git("branch", "-q", "-D", "throwaway")
        self.git("checkout", "-q", "-b", "other")
        self.write("README.md", "Support portal\n")
        path = self.root / RECORD
        write_json(path, record)
        self.git("add", "-f", "README.md", RECORD)
        self.git("commit", "-q", "-m", "work with a copied record")

    def test_ci_refuses_an_approval_whose_revision_the_pull_request_does_not_contain(self):
        commit = self.abandoned_approval()
        self.approve()
        self.write("README.md", "Support portal\n")
        record = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text())
        self.assertEqual(record["decision"]["base_revision"]["commit"], commit)
        self.copy_into_another_pull_request(record)
        local = self.run_cli("task", "list")[0]
        message = f"The approved revision {commit[:12]} of {TASK} is no longer in the project history"
        self.assertIn(message, local)
        result = self.ci(code=1)
        self.assertEqual(result["decisions"], [])
        self.assertIn(message, result["problems"][0])

    @unittest.skipIf(shutil.which("ssh-keygen") is None, "needs ssh-keygen")
    def test_ci_refuses_a_signed_approval_from_an_abandoned_branch_copied_into_another_pull_request(self):
        keys = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keys, ignore_errors=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "cm")], check=True)
        (self.root / "allowed_signers").write_text(f"cm@example.org {(keys / 'cm.pub').read_text().strip()}\n",
                                                   encoding="utf-8")
        commit = self.abandoned_approval(approval={"mode": "signed", "allowed_signers": "allowed_signers",
                                                   "approvers": ["cm@example.org"]})
        self.reviewed()
        self.run_cli("task", "decision-payload", TASK, "--by", "CM", "--reason", "Agreed", "--output", keys / "d.json")
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / "cm"), "-n", "openguildkit-decision",
                        str(keys / "d.json")], check=True, capture_output=True)
        self.run_cli("task", "decide", TASK, "--approve", "--by", "CM", "--reason", "Agreed",
                     "--signer", "cm@example.org", "--signature", keys / "d.json.sig")
        self.write("README.md", "Support portal\n")
        record = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text())
        self.assertIn("signature", record["decision"])
        self.copy_into_another_pull_request(record)
        problems = self.ci(code=1)["problems"]
        self.assertIn(f"The approved revision {commit[:12]} of {TASK} is no longer in the project history", problems[0])

    # Issue #277: a withdrawn approval and its exported record.

    def exported_on_a_branch(self):
        self.main_branch()
        self.git("checkout", "-q", "-b", "feature")
        self.approve()
        self.write("README.md", "Support portal\n")
        self.git("commit", "-q", "-am", "work")
        self.git("add", self.run_cli("task", "export", TASK)[0].strip())
        self.git("commit", "-q", "-m", "decision")
        self.assertTrue(self.ci()["ok"])

    def revoke(self):
        return self.run_cli("task", "revoke", TASK, "--by", "CM", "--reason", "Support moves the portal", typed=TASK)

    def test_a_withdrawal_reaches_the_exported_record_and_ci_refuses_it(self):
        self.exported_on_a_branch()
        approved = json.loads((self.root / RECORD).read_text())
        _, said = self.revoke()
        self.assertIn(f"{RECORD} still says {TASK} is approved", said)
        self.assertIn(f"openguildkit task export {TASK}", said)

        # Before the new export, check and task list --decisions name the record the local withdrawal contradicts.
        _, error = self.run_cli("check", code=1)
        self.assertIn(f"{RECORD}: the approval of {TASK} was withdrawn in this copy by CM", error)
        listed = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertEqual(listed[0]["problem"]["kind"], "withdrawn-here")
        self.assertIn("was withdrawn in this copy", self.run_cli("task", "list", "--decisions")[0])

        output, error = self.run_cli("task", "export", TASK)
        self.assertEqual(output.strip(), RECORD)
        self.assertIn("withdrawal", error)
        record = json.loads((self.root / RECORD).read_text())
        self.assertEqual({key: record["withdrawn"][key] for key in ("by", "reason")},
                         {"by": "CM", "reason": "Support moves the portal"})
        self.assertIn("at", record["withdrawn"])
        self.assertEqual(record["decision"], approved["decision"])
        self.assertIn(RECORD, self.git("status", "--porcelain"))
        self.git("commit", "-q", "-am", "withdrawal")

        result = self.ci(code=1)
        self.assertEqual(result["decisions"], [])
        self.assertIn(f"{RECORD}: the approval of {TASK} was withdrawn by CM", result["problems"][0])
        self.assertNotIn("Covered by", self.run_cli("guard", "--ci", "--base", "main", code=1)[0])
        listed = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertEqual((listed[0]["problem"]["kind"], listed[0]["problem"]["severity"]), ("withdrawn", "note"))
        self.run_cli("check")

        # Merged, the withdrawn record keeps the earlier copy of the same approval from covering anything.
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-ff", "feature", "-m", "merge")
        self.git("checkout", "-q", "-b", "again")
        self.write("app.py", "print(1)\n")
        write_json(self.root / RECORD, approved)
        self.commit_all("the approval before its withdrawal")
        self.assertIn("was withdrawn by CM", self.ci(code=1)["problems"][0])

    def test_a_forged_withdrawal_or_one_without_a_record_is_refused(self):
        # OGK-GUARD-012
        self.exported_on_a_branch()
        record = json.loads((self.root / RECORD).read_text())
        record["withdrawn"] = "yes"
        record["record_sha256"] = export_digest(record)
        write_json(self.root / RECORD, record)
        self.git("commit", "-q", "-am", "forged")
        self.assertIn("withdrawn must name who", " ".join(self.ci(code=1)["problems"]))
        self.git("rm", "-q", RECORD)
        self.git("commit", "-q", "-m", "no record")
        self.revoke()
        _, error = self.run_cli("task", "export", TASK, code=1)
        self.assertIn("no exported record to write the withdrawal into", error)

    # Issue #279: the closing order of the README.

    def test_the_readme_closing_order_passes_ci_with_new_files(self):
        self.main_branch()
        self.git("checkout", "-q", "-b", "feature")
        self.approve()
        for path in ("docs/privacy/dpia-decision.md", "docs/privacy/ropa.md", "tests/test_export.py"):
            self.write(path)
        _, said = self.complete()
        self.assertIn("commit the work (git add, git commit), then export the decision record", said)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "the work")
        exported = self.run_cli("task", "export", TASK)[0].strip()
        self.git("add", exported)
        self.git("commit", "-q", "-m", "the decision record")
        result = self.ci()
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["mode"], "enforce")

    def test_export_names_the_new_files_it_does_not_cover(self):
        self.main_branch()
        self.git("checkout", "-q", "-b", "feature")
        self.approve()
        self.write("README.md", "Support portal\n")
        self.write("docs/privacy/ropa.md")
        self.write("tests/test_export.py")
        _, error = self.run_cli("task", "export", TASK)
        self.assertIn("2 new files Git does not track yet are not in the record: docs/privacy/ropa.md, "
                      "tests/test_export.py", error)
        record = json.loads((self.root / RECORD).read_text())
        self.assertEqual(record["files"], ["README.md"])
        self.git("add", "-A")
        _, error = self.run_cli("task", "export", TASK)
        self.assertNotIn("Git does not track", error)
        self.assertEqual(json.loads((self.root / RECORD).read_text())["files"],
                         ["README.md", "docs/privacy/ropa.md", "tests/test_export.py"])


if __name__ == "__main__":
    unittest.main()
