"""The audit log: one JSON event per line, chained, off by default (issue #454), and signed_at, the date under the seal."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import audit_log
from openguildkit.clock import real_today
from openguildkit.decisions import (
    PAYLOAD_VERSIONS,
    check_decision_seal,
    decision_payload,
    record_digest,
    seal,
    signing_time_of,
)
from openguildkit.storage import read_json, write_json
from tests.support import CapturedCli, openguildkit_on_path
from tests.test_roles import RoleCase

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
ON = {audit_log.VARIABLE: "1"}
POSIX_LINKS = unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "symbolic links need POSIX here")


def tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


class AuditCase(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        openguildkit_on_path(self)
        self.log = self.root / ".openguildkit" / "audit" / "audit.jsonl"

    def init(self, **extra):
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), **extra})
        self.run_cli("init", "--answers", self.root / "profile.json")

    def review(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")

    def approve(self):
        self.review()
        self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", typed=TASK)

    def edit(self, path="app.py", content="SECRET-CONTENT"):
        return json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                           "tool_input": {"file_path": str(self.root / path), "new_string": content}})

    def refuse(self, path="app.py"):
        return self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit(path), code=2)

    def events(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


class OffByDefaultTests(AuditCase):
    def test_a_refusal_with_the_log_off_leaves_the_project_files_as_they_were(self):
        """Issue #454: with the journal off, the files before and after a refusal are the same."""
        self.init(guard="enforce")
        before = tree(self.root)
        self.refuse()
        self.assertEqual(tree(self.root), before)
        self.assertFalse(self.log.exists())


class RefusalTests(AuditCase):
    def test_a_refusal_adds_one_line_with_the_path_and_the_host_and_never_the_edited_content(self):
        """Issue #454: a refusal in enforce wrote nothing, so the SOC could not see it."""
        self.init(guard="enforce", host="claude-code")
        with patch.dict(os.environ, ON):
            self.refuse()
        [event] = self.events()
        self.assertEqual((event["v"], event["event"], event["host"], event["paths"], event["mode"]),
                         (1, "guard.refused", "claude-code", ["app.py"], "enforce"))
        self.assertEqual(event["prev"], audit_log.GENESIS)
        self.assertRegex(event["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertNotIn("SECRET-CONTENT", self.log.read_text(encoding="utf-8"))

    def test_each_line_carries_the_hash_of_the_line_before_it(self):
        self.init(guard="enforce")
        with patch.dict(os.environ, ON):
            self.refuse()
            self.refuse("other.py")
        first, second = self.log.read_bytes().split(b"\n")[:2]
        self.assertEqual(json.loads(second)["prev"], hashlib.sha256(first).hexdigest())

    def test_the_log_stays_in_a_folder_git_ignores_and_the_guard_protects(self):
        self.init(guard="enforce")
        with patch.dict(os.environ, ON):
            self.refuse()
        self.assertEqual((self.log.parent / ".gitignore").read_text(encoding="utf-8"), "*\n")
        with patch.dict(os.environ, ON):
            _, error = self.refuse(".openguildkit/audit/audit.jsonl")
        self.assertIn("audit.jsonl", error)
        self.assertIn("is written by the openguildkit commands", error)

    def test_the_variable_names_a_file_of_the_audit_folder_and_nothing_else(self):
        self.init(guard="enforce")
        with patch.dict(os.environ, {audit_log.VARIABLE: "soc.jsonl"}):
            self.refuse()
        self.assertTrue((self.log.parent / "soc.jsonl").is_file())
        for value in ("../outside.jsonl", "/tmp/outside.jsonl", "a/b.jsonl", ".hidden"):
            with self.subTest(value=value), patch.dict(os.environ, {audit_log.VARIABLE: value}):
                _, error = self.refuse()
                self.assertIn("audit log could not be written", error)
                self.assertFalse((self.root.parent / "outside.jsonl").exists())

    @POSIX_LINKS
    def test_a_link_in_place_of_the_folder_or_the_file_is_never_followed(self):
        """A write outside the project (SECURITY.md) must not come from a link in the audit folder."""
        self.init(guard="enforce")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (self.root / ".openguildkit" / "audit").symlink_to(outside, target_is_directory=True)
        with patch.dict(os.environ, ON):
            _, error = self.refuse()
        self.assertIn("audit log could not be written", error)
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / ".openguildkit" / "audit").unlink()
        (self.root / ".openguildkit" / "audit").mkdir()
        target = outside / "target.jsonl"
        target.write_text("", encoding="utf-8")
        self.log.symlink_to(target)
        with patch.dict(os.environ, ON):
            _, error = self.refuse()
        self.assertIn("audit log could not be written", error)
        self.assertEqual(target.read_text(encoding="utf-8"), "")
        # The .gitignore of the folder is a link to a file that does not exist: writing it would create that file.
        self.log.unlink()
        planted = outside / "created-by-the-cli"
        (self.log.parent / ".gitignore").symlink_to(planted)
        with patch.dict(os.environ, ON):
            _, error = self.refuse()
        self.assertIn("audit log could not be written", error)
        self.assertFalse(planted.exists(), "the CLI wrote a file outside the project through a link")

    def test_a_log_that_cannot_be_written_never_changes_the_answer_of_the_hook(self):
        self.init(guard="enforce")
        with patch.dict(os.environ, ON), patch("openguildkit.audit_log._append", side_effect=OSError("disk full")):
            _, error = self.refuse()
        self.assertIn("Edit refused for", error)
        self.assertIn("disk full", error)


class EventTests(AuditCase):
    def test_an_approval_a_withdrawal_and_a_profile_change_are_events(self):
        self.init(guard="enforce")
        with patch.dict(os.environ, ON):
            self.approve()
            sealed = read_json(self.root / ".openguildkit" / "tasks" / f"{TASK}.json")["decision"]["seal"]
            self.run_cli("task", "revoke", TASK, "--by", "Camille", "--reason", "Plans changed", typed=TASK)
            self.run_cli("profile", "set", "host", "claude-code", "--by", "Camille", "--reason", "Open sources")
        approved, revoked, changed = self.events()
        self.assertEqual((approved["event"], approved["task"], approved["by"], approved["seal"]),
                         ("task.approved", TASK, "Camille", sealed))
        self.assertEqual((revoked["event"], revoked["task"], revoked["by"]), ("task.revoked", TASK, "Camille"))
        self.assertEqual((changed["event"], changed["by"], changed["change"]), ("profile.changed", "Camille", "set host claude-code"))
        self.assertNotIn("Plans changed", self.log.read_text(encoding="utf-8"))
        self.assertNotIn("Open sources", self.log.read_text(encoding="utf-8"))

    def test_host_apply_is_an_event_with_the_files_it_wrote(self):
        self.init(guard="enforce", host="claude-code")
        with patch.dict(os.environ, ON):
            self.run_cli("host", "apply", code=0)
        [event] = self.events()
        self.assertEqual((event["event"], event["host"], event["paths"]), ("host.applied", "claude-code", [".claude/settings.json"]))

    def test_issue_454_an_edit_the_guard_flags_in_observe_is_an_event(self):
        """Issue #454: an edit observe let through and flagged wrote nothing, so the SOC saw no sign of it."""
        self.init(guard="observe", host="claude-code")
        with patch.dict(os.environ, ON):
            output, _ = self.run_cli("guard", "--hook", "pre-edit", stdin=self.edit(), code=0)
        self.assertIn("Edit flagged, not blocked", output)
        [event] = self.events()
        self.assertEqual((event["event"], event["mode"], event["paths"]), ("guard.flagged", "observe", ["app.py"]))
        self.assertNotIn("SECRET-CONTENT", self.log.read_text(encoding="utf-8"))

    def test_issue_454_an_authorization_of_an_external_action_is_an_event(self):
        """Issue #454: task authorize wrote the decision in tasks/ only, which Git ignores."""
        self.init(guard="enforce")
        self.approve()
        with patch.dict(os.environ, ON):
            self.run_cli("task", "authorize", TASK, "--action", "external-api", "--target", "status.example.test",
                         "--deny", "--by", "Camille", "--reason", "Not this week")
        [event] = self.events()
        self.assertEqual((event["event"], event["task"], event["action"], event["target"], event["decision"], event["by"]),
                         ("task.authorized", TASK, "external-api", "status.example.test", "deny", "Camille"))
        self.assertNotIn("Not this week", self.log.read_text(encoding="utf-8"))

    def test_the_schema_has_one_documented_example_per_event_type(self):
        text = (Path(__file__).resolve().parents[1] / "docs" / "audit-log.md").read_text(encoding="utf-8")
        examples = [json.loads(line) for line in re.findall(r"^\{\"v\":.*\}$", text, re.MULTILINE)]
        self.assertEqual(sorted(item["event"] for item in examples), sorted(audit_log.EVENTS))
        for item in examples:
            self.assertEqual(audit_log.problem_with_event(item), None, item)
        self.assertIn("unknown event", audit_log.problem_with_event({**examples[0], "event": "guard.seen"}))
        self.assertIn("unknown field", audit_log.problem_with_event({**examples[0], "content": "x"}))


class BlockerEventTests(RoleCase):
    def setUp(self):
        super().setUp()
        self.init()
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.log = self.state / "audit" / "audit.jsonl"

    def test_issue_454_clearing_a_blocker_is_an_event(self):
        """Issue #454: a blocker cleared before the decision left its trace in tasks/ only."""
        self.reviewed()
        with patch.dict(os.environ, ON):
            self.clear("PL")
        [event] = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((event["event"], event["task"], event["blocker"], event["by"]),
                         ("blocker.cleared", "sx", "security:1", "PL"))
        self.assertNotIn("Retention is recorded", self.log.read_text(encoding="utf-8"))

    def test_issue_454_waiving_a_blocker_is_an_event_with_its_end_day(self):
        """Issue #454: a waiver, a lowered protection, was not visible to the SOC."""
        self.run_cli("profile", "set", "waivers", "allowed", "--allowed-by", "PL", "--max-days", "30", "--by", "Sam",
                     "--reason", "Waivers", typed="allowed")
        self.reviewed()
        until = (real_today() + timedelta(days=10)).isoformat()
        with patch.dict(os.environ, ON):
            self.run_cli("task", "waive", "sx", "security:1", "--reason", "Accepted", "--scope", "Pilot", "--until",
                         until, "--by", "PL", typed="sx")
        [event] = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((event["event"], event["blocker"], event["by"], event["until"]),
                         ("blocker.waived", "security:1", "PL", until))


class VerifyTests(AuditCase):
    def lines(self) -> list[bytes]:
        return self.log.read_bytes().split(b"\n")[:-1]

    def setUp(self):
        super().setUp()
        self.init(guard="enforce")
        with patch.dict(os.environ, ON):
            for name in ("a.py", "b.py", "c.py"):
                self.refuse(name)

    def test_an_intact_chain_says_how_many_events_it_holds(self):
        output, _ = self.run_cli("audit", "verify")
        self.assertEqual(output.strip(), "3 events, chain intact")
        self.assertEqual(self.run_cli("audit", "verify", self.log)[0], output)

    def test_a_modified_line_exits_1_and_names_the_line_that_no_longer_follows(self):
        lines = self.lines()
        lines[1] = lines[1].replace(b"b.py", b"z.py")
        self.log.write_bytes(b"\n".join(lines) + b"\n")
        _, error = self.run_cli("audit", "verify", code=1)
        self.assertIn("line 3 does not follow line 2", error)

    def test_a_removed_line_exits_1_and_names_the_line_after_the_gap(self):
        lines = self.lines()
        self.log.write_bytes(b"\n".join([lines[0], lines[2]]) + b"\n")
        _, error = self.run_cli("audit", "verify", code=1)
        self.assertIn("line 2 does not follow line 1", error)

    def test_a_line_that_is_not_json_is_named(self):
        lines = self.lines()
        self.log.write_bytes(b"\n".join([lines[0], b"not json", lines[2]]) + b"\n")
        _, error = self.run_cli("audit", "verify", code=1)
        self.assertIn("line 2 is not a JSON event", error)

    def test_issue_454_a_line_that_follows_the_chain_but_is_not_an_event_of_the_schema_is_named(self):
        """Issue #454: audit verify checked the chain only, so a line of an unknown event or field passed."""
        lines = self.lines()
        planted = json.dumps({"v": 1, "at": "2026-11-27T09:00:00+00:00", "event": "guard.seen", "project": "p",
                              "prev": hashlib.sha256(lines[-1]).hexdigest()}, separators=(",", ":")).encode()
        self.log.write_bytes(b"\n".join([*lines, planted]) + b"\n")
        _, error = self.run_cli("audit", "verify", code=1)
        self.assertIn("3 events intact, then line 4 follows the chain but is not an event of the schema: unknown event "
                      "'guard.seen'", error)

    def test_an_unreadable_path_is_one_line(self):
        _, error = self.run_cli("audit", "verify", self.root / "missing.jsonl", code=1)
        self.assertEqual(len(error.strip().splitlines()), 1)


class ExportTests(AuditCase):
    def test_the_export_rebuilds_the_events_from_the_records_and_the_profile_history_and_verifies(self):
        self.init(guard="enforce")
        self.approve()
        self.run_cli("task", "export", TASK)
        self.run_cli("profile", "set", "host", "claude-code", "--by", "Lou", "--reason", "Open sources")
        output, _ = self.run_cli("audit", "export")
        events = [json.loads(line) for line in output.splitlines()]
        # A profile change carries a day only, so it is dated 00:00:00 UTC and comes before the approval of that day.
        self.assertEqual([item["event"] for item in events], ["profile.changed", "task.approved"])
        change, approval = events
        self.assertEqual((approval["task"], approval["by"], approval["reconstructed"]), (TASK, "Camille", True))
        self.assertEqual(change["by"], "Lou")
        self.assertTrue(change["at"].endswith("T00:00:00+00:00"))
        exported = self.root / "events.jsonl"
        exported.write_text(output, encoding="utf-8")
        self.assertIn("2 events, chain intact", self.run_cli("audit", "verify", exported)[0])
        # Issue #454: on Windows the export written by print ends its lines with \r\n, and verify broke the chain.
        exported.write_bytes(output.replace("\n", "\r\n").encode("utf-8"))
        self.assertIn("2 events, chain intact", self.run_cli("audit", "verify", exported)[0])
        self.assertEqual(self.run_cli("audit", "export", "--since", change["at"][:10])[0].count("\n"), 2)
        self.assertEqual(self.run_cli("audit", "export", "--since", "2999-01-01")[0], "")

    def test_since_is_a_day(self):
        self.init()
        _, error = self.run_cli("audit", "export", "--since", "yesterday", code=1)
        self.assertIn("YYYY-MM-DD", error)


class SealTests(AuditCase):
    def sealed_task(self, on: bool = True) -> dict:
        self.init(guard="enforce")
        with patch.dict(os.environ, ON if on else {}):
            self.approve()
        return read_json(self.root / ".openguildkit" / "tasks" / f"{TASK}.json")

    def test_without_the_log_a_local_approval_is_sealed_as_it_was_before_and_its_date_stays_outside(self):
        """The date joins the seal only for a person who turned the audit log on: the default format does not change."""
        task = self.sealed_task(on=False)
        self.assertNotIn("signed_at", check_decision_seal(task))
        self.assertNotIn("signed_at", task["decision"])
        moved = {**task, "decision": {**task["decision"], "at": "2024-01-01T00:00:00+00:00"}}
        self.assertEqual(check_decision_seal(moved), check_decision_seal(task))

    def test_changing_the_date_of_a_local_approval_breaks_its_seal(self):
        """Issue #454: decision.at was under neither the seal nor a signature."""
        task = self.sealed_task()
        self.assertEqual(task["decision"]["signed_at"], signing_time_of(task["decision"]["at"]))
        self.assertEqual(check_decision_seal(task)["signed_at"], task["decision"]["signed_at"])
        for day in ("2024-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"):
            moved = {**task, "decision": {**task["decision"], "at": day}}
            with self.assertRaisesRegex(ValueError, "date of the approval"):
                check_decision_seal(moved)
        for day in ("2024-01-01T00:00:00Z", "2999-01-01T00:00:00Z"):
            moved = {**task, "decision": {**task["decision"], "signed_at": day}}
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                check_decision_seal(moved)

    def test_approvals_sealed_with_versions_1_to_3_still_verify_whatever_their_date(self):
        """The log has no seal version of its own: the versions are the three that existed before it."""
        task = self.sealed_task()
        self.assertEqual(PAYLOAD_VERSIONS, (3, 2, 1))
        for version in (3, 2, 1):
            payload = decision_payload(task, "Camille", "Agreed", task["decision"].get("base_revision"), version)
            old = {**task, "decision": {**task["decision"], "seal": seal(payload), "at": "2024-01-01T00:00:00+00:00"}}
            del old["decision"]["signed_at"]
            self.assertNotIn("signed_at", check_decision_seal(old))

    def test_the_exported_record_carries_the_date_and_ci_refuses_a_record_whose_date_was_changed(self):
        task = self.sealed_task()
        path = self.root / self.run_cli("task", "export", TASK)[0].strip()
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["decision"]["payload"]["signed_at"], signing_time_of(task["decision"]["at"]))
        from openguildkit.guard import _record_fault

        self.assertIsNone(_record_fault(record, "r.json", self.fingerprint(), {"mode": "local"}, self.root, {}))
        record["decision"]["at"] = "2024-01-01T00:00:00+00:00"
        record["record_sha256"] = record_digest(record)
        fault = _record_fault(record, "r.json", self.fingerprint(), {"mode": "local"}, self.root, {})
        self.assertIsNotNone(fault, "a record whose date was changed after it was sealed passes")
        self.assertEqual(fault[0], "decision-record-invalid")
        self.assertIn("seal does not match", fault[1])

    def fingerprint(self) -> str:
        return read_json(self.root / ".openguildkit" / "tasks" / f"{TASK}.json")["profile_fingerprint"]


class SignedAtTests(AuditCase):
    """The audit log and `--signed-at` are one mechanism: the time under the seal is signed_at."""

    PRINCIPAL = "camille@example.org"

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"})

    def signed_project(self) -> Path:
        """A Git project that requires signed approvals; returns the folder, outside the project, of the key."""
        keys = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keys, ignore_errors=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "camille")], check=True)
        (self.root / "allowed_signers").write_text(
            f"{self.PRINCIPAL} {(keys / 'camille.pub').read_text().strip()}\n", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce", approval={"mode": "signed", "allowed_signers": "allowed_signers",
                                             "approvers": [self.PRINCIPAL]})
        self.git("add", "allowed_signers", ".openguildkit/project.json")
        self.git("commit", "-q", "-m", "signers")
        self.review()
        return keys

    def decide_signed(self, keys: Path, *option: str) -> dict:
        """decision-payload, the signature of Camille, then decide; the option goes to both commands."""
        self.run_cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed",
                     "--output", keys / "decision.json", *option)
        signature = keys / "decision.json.sig"
        signature.unlink(missing_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / "camille"), "-n", "openguildkit-decision",
                        str(keys / "decision.json")], check=True, capture_output=True, stdin=subprocess.DEVNULL)
        with patch("sys.stdin.isatty", return_value=False):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed",
                         "--signer", self.PRINCIPAL, "--signature", signature, *option)
        return read_json(self.root / ".openguildkit" / "tasks" / f"{TASK}.json")

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_both_options_on_a_signed_approval_keeps_the_time_its_signer_gave_and_the_log_records_it(self):
        """Issue #454: the log and --signed-at (issue #478) work together, with no seal format of their own."""
        keys = self.signed_project()
        moment = "2026-01-15T10:00:00Z"
        with patch.dict(os.environ, ON):
            task = self.decide_signed(keys, "--signed-at", moment)
        self.assertEqual(task["decision"]["signed_at"], moment)  # the signer's time, not the time of the decision
        self.assertNotEqual(signing_time_of(task["decision"]["at"]), moment)
        self.assertEqual(check_decision_seal(task)["signed_at"], moment)
        self.assertEqual(json.loads((keys / "decision.json").read_text())["signed_at"], moment)
        self.run_cli("task", "handoff", TASK)
        self.assertEqual(len(json.loads(self.run_cli("guard", "--json")[0])["covered_by"]), 1)
        [event] = [item for item in self.events() if item["event"] == "task.approved"]
        self.assertEqual((event["task"], event["signer"], event["seal"]), (TASK, self.PRINCIPAL, task["decision"]["seal"]))
        self.assertIn("chain intact", self.run_cli("audit", "verify")[0])
        # The time is sealed: another one breaks the seal, the log being on or not.
        moved = {**task, "decision": {**task["decision"], "signed_at": "2026-01-15T10:00:01Z"}}
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            check_decision_seal(moved)

    @unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
    def test_both_options_on_a_signed_approval_without_signed_at_stays_undated_under_the_log(self):
        """The log adds no time to what a signer signs: the signer signs before the decision is dated."""
        keys = self.signed_project()
        with patch.dict(os.environ, ON):
            task = self.decide_signed(keys)
        self.assertNotIn("signed_at", task["decision"])
        self.assertNotIn("signed_at", check_decision_seal(task))
        self.assertEqual([item["event"] for item in self.events()], ["task.approved"])

    def test_both_options_on_a_local_approval_is_dated_by_signed_at_and_the_record_holds_in_ci(self):
        with patch.dict(os.environ, ON):
            self.init(guard="enforce")
            self.approve()
        task = read_json(self.root / ".openguildkit" / "tasks" / f"{TASK}.json")
        self.assertEqual(task["decision"]["signed_at"], signing_time_of(task["decision"]["at"]))
        self.assertEqual(check_decision_seal(task)["signed_at"], task["decision"]["signed_at"])
        self.assertEqual([item["event"] for item in self.events()], ["task.approved"])

    def test_both_options_off_an_approval_is_sealed_as_before_and_leaves_no_trace_of_either(self):
        """Issue #454, issue #478: without the log and without --signed-at, the payload and the seal are those of a
        release that had neither, and an approval it wrote still reads."""
        self.init(guard="enforce")
        self.review()
        _, error = self.run_cli("task", "decide", TASK, "--signed-at", "2026-01-15T10:00:00Z", "--request-changes",
                                "--by", "Camille", "--reason", "x", code=1)
        self.assertIn("goes with approving", error)
        self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", typed=TASK)
        task = read_json(self.root / ".openguildkit" / "tasks" / f"{TASK}.json")
        self.assertNotIn("signed_at", task["decision"])
        payload = check_decision_seal(task)
        self.assertNotIn("signed_at", payload)
        self.assertNotIn("at", payload)
        before = decision_payload(task, "Camille", "Agreed", task["decision"]["base_revision"], 3)
        self.assertEqual(payload, before)
        self.assertEqual(task["decision"]["seal"], seal(before))
        self.assertFalse((self.root / ".openguildkit" / "audit").exists())
        # An approval written by the release before: the same payload with no time, and its date outside the seal.
        old = {**task, "decision": {**task["decision"], "at": "2024-01-01T00:00:00+00:00"}}
        self.assertEqual(check_decision_seal(old), payload)


if __name__ == "__main__":
    unittest.main()
