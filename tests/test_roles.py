"""Roles by committee (#475): `approval.roles`, an option off by default.

With `profile set approver-roles BOARD NAME...`, a blocker that a board raised is cleared or waived only by a member of
that board's role, and a task whose protected board gave a blocking advice is approved only by a member of one of
the roles of those boards; `guard --ci` reads the roles at the base revision. Without roles nothing changes, and the
records written before them read as before.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json

from tests.support import run_cli
from tests.test_approval_lifecycle import ApprovalCase

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
BEFORE = json.loads((REPO / "tests" / "fixtures" / "upgrade" / "before-light-lane.json").read_text(encoding="utf-8"))
ROLE = ("profile", "set", "approver-roles", "security", "CM", "--by", "Sam", "--reason", "Security signs for security")


class RoleCase(ApprovalCase):
    """A project where the security board blocks the task with a condition of approval."""

    def setUp(self):
        super().setUp()
        self.keys = self.copies / "keys"
        self.keys.mkdir()

    def reviewed(self, task_id="sx"):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
        write_json(self.keys / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", task_id, "--answers", self.keys / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"]["verdict"] = "block"
        security["challenge"]["blockers"] = [{"finding": "Retention is not decided.", "owner": "Data protection officer",
                                              "clears_when": "The retention period is recorded."}]
        write_json(self.keys / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.keys / "review.json")

    def clear(self, by, code=0, task_id="sx"):
        return self.run_cli("task", "clear", task_id, "security:1", "--evidence", "README.md", "--supports",
                            "Retention is recorded.", "--by", by, typed=task_id, code=code)

    def decide(self, by, code=0, task_id="sx"):
        return self.run_cli("task", "decide", task_id, "--approve", "--by", by, "--reason", "Agreed", typed=task_id,
                            code=code)

    def roles(self) -> dict:
        return (json.loads((self.state / "project.json").read_text(encoding="utf-8")).get("approval") or {}).get("roles")


class WithoutRolesTests(RoleCase):
    def test_issue_475_without_roles_any_person_clears_and_approves(self):
        """Issue #475: a project that sets no roles is judged as before: any person clears a blocker and approves."""
        self.init()
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.reviewed()
        self.clear("PL")
        self.decide("PL")
        self.assertEqual(self.covered(), ["sx"])
        self.assertIsNone(self.roles())


class RolesTests(RoleCase):
    def setUp(self):
        super().setUp()
        self.init()
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.run_cli(*ROLE)

    def test_issue_475_a_blocker_of_a_committee_with_a_role_is_cleared_only_by_a_member(self):
        """Issue #475: any person cleared the blocker of any board."""
        self.assertEqual(self.roles(), {"security": ["CM"]})
        self.reviewed()
        _, error = self.clear("PL", code=1)
        self.assertIn("security:1 was raised by the security board: a person of role security clears it (CM)", error)
        self.assertIn("PL is not one of them", error)
        self.assertEqual(self.task("sx")["status"], "reviewed")
        self.assertNotIn("blocker_resolutions", self.task("sx"))
        self.clear("cm")
        self.assertEqual(self.task("sx")["blocker_resolutions"]["security:1"]["by"], "cm")

    def test_issue_475_a_blocker_is_waived_only_by_a_member_either(self):
        """Issue #475: a waiver is a way to lift a blocker, so it follows the role too."""
        self.run_cli("profile", "set", "waivers", "allowed", "--allowed-by", "PL", "--allowed-by", "CM", "--max-days",
                     "30", "--by", "Sam", "--reason", "Waivers", typed="allowed")
        self.reviewed()
        until = (date.today() + timedelta(days=10)).isoformat()
        waive = ["task", "waive", "sx", "security:1", "--reason", "Accepted", "--scope", "Pilot", "--until", until]
        _, error = self.run_cli(*waive, "--by", "PL", typed="sx", code=1)
        self.assertIn("a person of role security waives it (CM)", error)
        self.run_cli(*waive, "--by", "CM", typed="sx")

    def test_issue_475_the_approval_of_a_task_with_a_blocking_security_advice_needs_a_member_too(self):
        """Issue #475: the final approval was open to any approver as well."""
        self.reviewed()
        self.clear("CM")
        _, error = self.decide("PL", code=1)
        self.assertIn("The security board gave a blocking advice on sx: a person of role security approves it (CM)",
                      error)
        self.assertIn("PL is not one of them", error)
        self.assertEqual(self.task("sx")["status"], "reviewed")
        self.decide("CM")
        self.assertEqual(self.covered(), ["sx"])

    def test_issue_475_a_board_without_a_role_is_as_before(self):
        """Issue #475: only the boards the profile names have a role."""
        self.run_cli("profile", "set", "approver-roles", "legal", "AB", "--by", "Sam", "--reason", "Legal")
        self.run_cli("profile", "set", "approver-roles", "security", "none", "--by", "Sam", "--reason", "x", code=1)
        self.run_cli("profile", "set", "approver-roles", "security", "none", "--by", "Sam", "--reason", "x",
                     typed="security none")
        self.assertEqual(self.roles(), {"legal": ["AB"]})
        self.reviewed()
        self.clear("PL")
        self.decide("PL")

    def test_issue_475_roles_are_set_without_a_terminal_when_they_restrict_and_widened_by_a_person(self):
        """Issue #475: a new role or a shorter one restricts; a longer one, or none, weakens a protection."""
        self.run_cli("profile", "set", "approver-roles", "security", "CM", "JD", "--by", "Sam", "--reason", "x",
                     code=1)
        self.assertEqual(self.roles(), {"security": ["CM"]})
        self.run_cli("profile", "set", "approver-roles", "security", "CM", "JD", "--by", "Sam", "--reason", "x",
                     typed="security CM JD")
        self.assertEqual(self.roles(), {"security": ["CM", "JD"]})
        self.run_cli("profile", "set", "approver-roles", "security", "JD", "--by", "Sam", "--reason", "Shorter")
        self.assertEqual(self.roles(), {"security": ["JD"]})
        refused = self.run_cli("profile", "set", "approver-roles", "security", "none", "--by", "Sam", "--reason", "x",
                               code=1)[1]
        self.assertIn("role security removed", refused)
        unknown = self.run_cli("profile", "set", "approver-roles", "no-such-board", "CM", "--by", "Sam", "--reason", "x",
                               code=1)[1]
        self.assertIn("Unknown board", unknown)
        self.assertEqual(self.roles(), {"security": ["JD"]})

    def test_issue_475_profile_export_leaves_the_roles_out_and_names_the_command(self):
        """Issue #475: a role names people, so another repository does not get it without a person typing it."""
        exported = self.run_cli("profile", "export")
        self.assertNotIn("roles", json.loads(exported[0]).get("approval", {}))
        self.assertIn("openguildkit profile set approver-roles BOARD NAME...", exported[1])

    def test_issue_475_the_roles_do_not_void_an_approval(self):
        """Issue #475: the approval rests on the rules, not on who may clear a blocker."""
        self.reviewed()
        self.clear("CM")
        self.decide("CM")
        self.run_cli("profile", "set", "approver-roles", "legal", "AB", "--by", "Sam", "--reason", "Legal")
        self.assertEqual(self.covered(), ["sx"])


@unittest.skipIf(shutil.which("git") is None, "needs git")
class CiTests(RoleCase):
    """guard --ci with the roles of the base revision: a record whose blocker was cleared, or whose task was approved,
    by someone outside the role is refused."""

    def branch(self, who):
        """main holds the project; a feature branch carries the task, cleared and approved by `who`, without roles, since
        the roles come to main afterwards: the base revision's roles are what judges the record."""
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.reviewed()
        self.clear(who)
        self.decide(who)
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "work")
        self.run_cli("task", "export", "sx")
        self.git("add", "-f", ".openguildkit/decisions/sx.json")
        self.git("commit", "-q", "-m", "decision")
        self.git("checkout", "-q", "main")
        self.run_cli(*ROLE)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "roles")
        self.git("checkout", "-q", "feature")

    def ci(self, code):
        return json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json", code=code)[0])

    def test_issue_475_guard_ci_refuses_a_record_cleared_and_approved_outside_the_role_of_the_base(self):
        """Issue #475: guard --ci checked no committee of a blocker or of the advice behind the approval."""
        self.branch("PL")
        result = self.ci(1)
        self.assertFalse(result["ok"])
        said = " ".join(result["problems"])
        self.assertIn("security:1 was cleared by PL, not a person of role security (CM)", said)
        self.assertIn("approved by PL, not a person of role security (CM)", said)
        sarif = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--format", "sarif", code=1)[0])
        self.assertIn("decision-role-outside", {item["ruleId"] for item in sarif["runs"][0]["results"]})

    def test_issue_475_guard_ci_accepts_a_record_cleared_and_approved_by_the_role(self):
        """Issue #475: the members of the role pass."""
        self.branch("CM")
        result = self.ci(0)
        self.assertEqual((result["ok"], result["decisions"]), (True, ["sx"]))


@unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
class SignedTests(RoleCase):
    """In a signed project the role is read from the signer, not from the name typed with --by."""

    def sign(self, name, payload):
        signature = Path(f"{payload}.sig")
        signature.unlink(missing_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(self.keys / name), "-n", "openguildkit-decision",
                        str(payload)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
        return signature

    def test_issue_475_a_clearance_signed_outside_the_role_is_refused_and_names_the_signers(self):
        """Issue #475: with roles.security = [CM], a clearance of a security blocker signed by PL is refused."""
        for name in ("cm", "pl"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.keys / name)], check=True)
        lines = [f"{name}@example.org {(self.keys / f'{name}.pub').read_text().strip()}" for name in ("cm", "pl")]
        (self.root / "allowed_signers").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.init(approval={"mode": "signed", "allowed_signers": "allowed_signers",
                            "approvers": ["cm@example.org", "pl@example.org"]})
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.run_cli("profile", "set", "approver-roles", "security", "cm@example.org", "--by", "Sam", "--reason", "x")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "signers")
        self.reviewed()
        clear = ["task", "clear", "sx", "security:1", "--evidence", "README.md", "--supports", "Recorded.", "--by",
                 "Camille"]
        self.run_cli(*clear, "--payload", self.keys / "clear.json")
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli(*clear, "--signature", self.sign("pl", self.keys / "clear.json"), "--signer",
                                    "pl@example.org", code=1)
            self.assertIn("security:1 was raised by the security board: a signer of role security clears it "
                          "(cm@example.org)", error)
            self.assertIn("pl@example.org is not one of them", error)
            self.run_cli(*clear, "--signature", self.sign("cm", self.keys / "clear.json"), "--signer",
                         "cm@example.org")
            self.run_cli("task", "decision-payload", "sx", "--by", "Camille", "--reason", "Agreed", "--output",
                         self.keys / "decision.json")
            decide = ["task", "decide", "sx", "--approve", "--by", "Camille", "--reason", "Agreed", "--signer"]
            _, error = self.run_cli(*decide, "pl@example.org", "--signature", self.sign("pl", self.keys / "decision.json"),
                                    code=1)
            self.assertIn("a signer of role security approves it (cm@example.org)", error)
            self.run_cli(*decide, "cm@example.org", "--signature", self.sign("cm", self.keys / "decision.json"))
        self.assertEqual(self.task("sx")["status"], "approved")


class BeforeTheRolesTests(unittest.TestCase):
    """A project written by an earlier release (tests/fixtures/upgrade/before-light-lane.json) sets no roles: its
    records read and export as before."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, content in BEFORE["files"].items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        clock = patch("openguildkit.clock.real_now", return_value=datetime.fromisoformat(BEFORE["now"]))
        clock.start()
        self.addCleanup(clock.stop)

    def test_issue_475_the_old_records_read_and_export_as_before(self):
        """Issue #475: a project without roles reads its earlier approvals, and writes its record byte for byte."""
        self.assertNotIn("approval", json.loads(BEFORE["files"][".openguildkit/project.json"]))
        run_cli(self.root, "task", "handoff", "approved-task")
        (row,) = [item for item in json.loads(run_cli(self.root, "task", "list", "--json").stdout)
                  if item["id"] == "approved-task"]
        self.assertNotIn("approval_problem", row)
        target = self.root / "again.json"
        run_cli(self.root, "task", "export", "done-task", "--output", target)
        self.assertEqual(target.read_text(encoding="utf-8"), BEFORE["files"][".openguildkit/decisions/done-task.json"])
        run_cli(self.root, "profile", "set", "approver-roles", "security", "CM", "--by", "Sam", "--reason", "x",
                stdin="")
        again = run_cli(self.root, "task", "list", "--json").stdout
        self.assertNotIn("approval_problem", again)
