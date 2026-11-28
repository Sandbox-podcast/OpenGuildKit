"""Stable error codes of the task commands (#487): the refusals no other test meets, provoked through the command a
person runs, or by calling the function when the state that reaches it is long to build."""

import json
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from openguildkit import (
    requester,
    task_files,
    tasks_approval,
    tasks_blockers,
    tasks_close_cli,
    tasks_closing,
    tasks_consult_cli,
    tasks_list_cli,
    tasks_review,
    workflow,
)
from openguildkit.catalog import load_catalog
from openguildkit.errors import OgkError
from openguildkit.project import load_profile
from openguildkit.storage import write_json
from openguildkit.tasks_command import TaskCommand
from tests import test_deliberation
from tests.test_approval_lifecycle import EXAMPLE, ApprovalCase


class TaskCodeTests(ApprovalCase):
    """Issue #487: each refusal of the task commands that no other test met carries its code."""

    def setUp(self):
        super().setUp()
        self.init()
        self.approve("t1", verification_blocker=True)
        self.catalog = load_catalog()
        self.profile = load_profile(self.state, self.catalog)
        self.answers = self.root / "answers.json"
        (self.root / "README.md").write_text("Two accounts are tested.\n", encoding="utf-8")

    def refused(self, code, *arguments, typed=None):
        _, error = self.run_cli(*arguments, code=1, typed=typed)
        # The last line: task show of an exported record first says where the task is.
        self.assertTrue(error.splitlines()[-1].startswith(f"OpenGuildKit [{code}]: "), error)

    def assertCodes(self, cases):
        for code, call in cases:
            with self.subTest(code=code), self.assertRaises(OgkError) as raised:
                call()
            self.assertEqual(raised.exception.code, code, raised.exception)

    def command(self, task, **args):
        return TaskCommand(Namespace(id=task["id"], **args), self.root, self.state, self.profile, self.catalog, task)

    def check_id(self):
        task = self.task("t1")
        return next(check["id"] for check in tasks_close_cli.expected_checks(task, self.profile)
                    if check["kind"] == "command")

    def test_issue_487_the_task_commands_print_the_codes_of_their_arguments(self):
        """Issue #487: task route, questions, consult, verify, complete, clear, decision-payload and show."""
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "fresh")
        self.refused("OGK-TASK-136", "task", "route", "fresh")
        self.refused("OGK-TASK-133", "task", "route", "fresh", "--answers", self.answers, "--delegate", "security")
        self.refused("OGK-TASK-134", "task", "questions", "fresh", "--follow-ups")
        self.refused("OGK-TASK-138", "task", "consult", "fresh", "--reuse-answers")
        self.run_cli("task", "consult", "fresh", "--answers", self.answers)
        check = self.check_id()
        self.refused("OGK-TASK-120", "task", "verify", "t1", "--cannot-run", check)
        self.refused("OGK-TASK-121", "task", "verify", "t1", "--withdraw", check, "--by", "Camille", typed="t1")
        self.refused("OGK-TASK-119", "task", "complete", "t1", "--defer", "no-equals-sign", "--by", "Camille")
        (self.root / "sig").write_text("signature", encoding="utf-8")
        clear = ("task", "clear", "t1", "security:1", "--evidence", "README.md", "--supports", "Tested.", "--by",
                 "Camille", "--signature", self.root / "sig")
        self.refused("OGK-TASK-141", *clear)
        self.refused("OGK-TASK-142", *clear, "--signer", "Camille")
        self.refused("OGK-TASK-143", "task", "decision-payload", "t1", "--by", "Camille", "--reason", "Agreed.")
        self.refused("OGK-TASK-146", "task", "show", "t1", "--summary", "--json")
        write_json(self.state / "decisions" / "gone.json", {"task": "gone"})
        self.refused("OGK-TASK-144", "task", "show", "gone", "--closing")

    def test_issue_487_a_task_that_changed_meanwhile_has_the_code_of_each_command(self):
        """Issue #487: verify, diff-review, respond, consult and review re-read the task under the lock."""
        task = self.task("t1")
        stale = {**task, "brief": "Another brief."}
        payload = self.root / "payload.json"
        write_json(payload, {})
        with patch.object(tasks_close_cli.delivered_review, "delivered_change", return_value={}):
            self.assertCodes([("OGK-TASK-125", lambda: tasks_close_cli.run_diff_review(
                self.command(stale, submit=payload, board=None, json=False)))])
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "fresh")
        fresh = {**self.task("fresh"), "brief": "Another brief."}
        self.assertCodes([
            ("OGK-TASK-124", lambda: tasks_close_cli.run_outcome(self.command(stale, action="result", all=False,
                                                                              file=payload))),
            ("OGK-TASK-135", lambda: tasks_consult_cli.run_respond(self.command(stale, file=payload))),
            ("OGK-TASK-137", lambda: tasks_consult_cli.run_consult(self.command(
                fresh, brief_file=None, revised_brief=None, reuse_answers=False, answers=self.answers))),
            ("OGK-TASK-140", lambda: tasks_consult_cli.run_review(self.command(stale, file=None))),
        ])

    def test_issue_487_a_declaration_and_a_replay_refused_by_verify_have_their_code(self):
        """Issue #487: a withdrawn declaration whose check no longer concerns the task, a replay on a decision."""
        task, check = self.task("t1"), self.check_id()
        with patch.object(tasks_close_cli, "declared_cannot_run", return_value={check: {"owner": "Camille"}}), \
                patch.object(tasks_close_cli, "run_command_checks", return_value=[]), \
                patch.object(tasks_close_cli, "interactive", return_value=True):
            self.assertCodes([("OGK-TASK-122", lambda: tasks_close_cli._withdraw(
                Namespace(withdraw=check, by="Camille"), self.root, self.state, task, self.profile, {}))])
        self.assertCodes([("OGK-TASK-123", lambda: tasks_close_cli._verify_payload(
            Namespace(chaosfolk=Path("summary.json")), self.root, self.state, task, self.profile, {}, True))])

    def test_issue_487_each_refused_blocker_resolution_has_its_code(self):
        """Issue #487: resolve_blocker refuses the wrong phase, a missing name, evidence, date or reason."""
        task = self.task("t1")
        approval_phase = json.loads(json.dumps(task))
        for entry in approval_phase["review"]["boards"]:
            for blocker in entry["challenge"].get("blockers", []):
                blocker["phase"] = "approval"
        waivers = {**self.profile, "waivers": {"allowed_by": ["Camille"], "max_days": 30}}

        def resolve(details, profile=self.profile, record=task, **options):
            return lambda: tasks_blockers.resolve_blocker(record, "security:1", details, profile, self.root, **options)

        cleared = {"kind": "cleared", "by": "Camille", "evidence": "README.md", "supports": "Tested."}
        waived = {"kind": "waived", "by": "Camille", "until": "2026-13-01", "reason": "Later.", "scope": "All."}
        self.assertCodes([
            ("OGK-TASK-113", resolve(cleared, record=approval_phase)),
            ("OGK-TASK-114", resolve({**cleared, "by": " "})),
            ("OGK-TASK-115", resolve({**cleared, "supports": ""})),
            ("OGK-TASK-116", resolve(cleared, signing_payload=True)),
            ("OGK-TASK-117", resolve({**waived, "until": "soon"}, waivers)),
            ("OGK-TASK-118", resolve({**waived, "until": "2099-01-01", "reason": ""},
                                     {**waivers, "waivers": {"allowed_by": ["Camille"], "max_days": 366 * 100}})),
        ])

    def test_issue_487_each_refused_decision_withdrawal_and_authorization_has_its_code(self):
        """Issue #487: record_decision, revoke_approval, record_authorization and defer_evidence."""
        task = self.task("t1")
        reviewed = {**task, "status": "reviewed"}
        follow = {"id": "follow", "follows": {}}
        with patch.object(tasks_closing, "pending_removals", return_value=["security"]):
            self.assertCodes([("OGK-TASK-128", lambda: tasks_closing.record_decision(reviewed, True, "C", "R"))])
        with patch.object(tasks_closing, "waiting_evidence", return_value=[{"check": "evidence:x"}]):
            self.assertCodes([("OGK-TASK-127", lambda: tasks_closing.defer_evidence(
                task, self.profile, [("evidence:x", follow)], "Camille"))])
        self.assertCodes([
            ("OGK-TASK-126", lambda: tasks_closing.defer_evidence(task, self.profile, [("evidence:x", follow)], "C")),
            ("OGK-TASK-129", lambda: tasks_closing.record_decision(reviewed, False, "Camille", " ")),
            ("OGK-TASK-130", lambda: tasks_closing.revoke_approval(task, "", "")),
            ("OGK-TASK-131", lambda: tasks_closing.record_authorization(task, "phone", "x", True, "C", "R")),
            ("OGK-TASK-132", lambda: tasks_closing.record_authorization(task, "publish", "example.org", True, "", "")),
        ])

    def test_issue_487_an_approval_under_other_rules_and_a_bad_record_have_their_code(self):
        """Issue #487: require_approval, require_current_scope, principals, task_path, start_pass, a retro record."""
        task = self.task("t1")
        consulting = {**task, "status": "consulting"}
        changed = {**self.profile, "checks": [*self.profile["checks"], "make test"]}
        tasks_folder = self.state / "tasks"
        (self.root / "elsewhere").mkdir()
        write_json(self.state / "decisions" / "gone.json", {"task": "gone"})
        self.assertCodes([
            ("OGK-TASK-111", lambda: tasks_approval.require_approval(task, changed, self.catalog, self.root)),
            ("OGK-TASK-112", lambda: tasks_approval.require_current_scope(task, changed, self.catalog)),
            ("OGK-TASK-109", lambda: requester.principals(self.root, "missing-signers")),
            ("OGK-TASK-145", lambda: tasks_list_cli._retro_record(self.root, self.state, "gone")),
            ("OGK-TASK-147", lambda: tasks_review.start_pass(consulting, "nobody", "subagent")),
            ("OGK-TASK-148", lambda: tasks_review.start_pass(consulting, "security", "parallel")),
        ])
        moved = self.root / "moved"
        tasks_folder.rename(moved)
        tasks_folder.symlink_to(self.root / "elsewhere")
        self.assertCodes([("OGK-TASK-110", lambda: task_files.task_path(self.state, "t1"))])


class DeliberationCodeTests(unittest.TestCase):
    """Issue #487: a deliberation that is not the object task deliberate prints is refused with its code."""

    setUp = test_deliberation.DeliberationTests.setUp
    reviewed = test_deliberation.DeliberationTests.reviewed

    def test_issue_487_a_deliberation_without_its_three_fields_has_its_code(self):
        """Issue #487: a list instead of the deliberation object."""
        with self.assertRaises(OgkError) as raised:
            workflow.validate_deliberation(self.task, [])
        self.assertEqual(raised.exception.code, "OGK-TASK-149")
