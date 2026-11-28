"""Stable error codes of the boards, results, decisions and routing (#487): the refusals no other test meets, each
provoked by calling the function that builds it with the input a person or an agent could write."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import (
    board_brief,
    board_entries,
    brains,
    decisions,
    deliverables,
    delivered_review,
    prompts,
    questionnaire,
    result_form,
    results,
    routing,
)
from openguildkit.errors import OgkError
from tests import test_brain_selection, test_deliberation


class CodedCase(unittest.TestCase):
    # The example consultation of the deliberation tests, without their test methods.
    setUp = test_deliberation.DeliberationTests.setUp
    reviewed = test_deliberation.DeliberationTests.reviewed

    def assertCodes(self, cases):
        for code, call in cases:
            with self.subTest(code=code), self.assertRaises(OgkError) as raised:
                call()
            self.assertEqual(raised.exception.code, code, raised.exception)

    def folder(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()


class BoardCodeTests(CodedCase):
    """Issue #487: a board brief, entry, review, brain skeleton or prompt answer refused without a code."""

    def test_issue_487_each_refused_board_input_has_its_code(self):
        """Issue #487: pack_rules, board_brief, validate_board_entry and validate_review."""
        consultation = self.consultation
        review = {"consultation_id": consultation["id"], "summary": "One summary.", "boards": []}
        self.assertCodes([
            ("OGK-BOARD-017", lambda: board_brief.pack_rules(consultation, "no-such-pack")),
            ("OGK-BOARD-018", lambda: board_brief.board_brief(consultation, "no-such-board")),
            ("OGK-BOARD-019", lambda: board_entries._evidence_outcome(None, ["evidence: one problem."], None)),
            ("OGK-BOARD-020", lambda: board_entries._check_reference(
                "http://example.org", "public", "evidence[0].ref", frozenset(), frozenset(), frozenset(), None)),
            ("OGK-BOARD-021", lambda: board_entries.validate_board_entry(consultation, [])),
            ("OGK-BOARD-022", lambda: board_entries.validate_review(consultation, {"summary": "Only."})),
            ("OGK-BOARD-023", lambda: board_entries.validate_review(consultation, {**review, "execution": "fast"})),
            ("OGK-BOARD-024", lambda: board_entries.validate_review(consultation, {**review, "boards": {}})),
        ])

    def test_issue_487_a_brain_skeleton_and_a_prompt_answer_refused_have_their_code(self):
        """Issue #487: write_brain_skeleton, prompt_choices and prompt_questions."""
        root = self.folder()
        (root / "boards").mkdir()
        (root / "boards" / "taken.json").write_text("{}", encoding="utf-8")
        catalog = {"boards": {}, "patterns": {}, "packs": {"risk-rules": {}}}
        question = {"id": "kind", "choices": [{"id": "feature"}, {"id": "fix"}]}
        with patch.object(prompts, "interactive", return_value=False):
            self.assertCodes([
                ("OGK-BOARD-025", lambda: brains.write_brain_skeleton(root, "Risk Office", catalog)),
                ("OGK-BOARD-026", lambda: brains.write_brain_skeleton(root, "risk", catalog)),
                ("OGK-BOARD-027", lambda: brains.write_brain_skeleton(root, "taken", catalog)),
                ("OGK-BOARD-028", lambda: prompts.prompt_choices(question, "9")),
                ("OGK-BOARD-029", lambda: prompts.prompt_questions([question], "task consult")),
            ])


class ResultCodeTests(CodedCase):
    """Issue #487: a deliverable, a delivered review, task answers or a result refused without a code."""

    def test_issue_487_each_refused_deliverable_and_delivered_review_has_its_code(self):
        """Issue #487: new_draft, require_reviewable and delivered_change."""
        root = self.folder()
        approved = {"id": "t1", "status": "approved", "answers": {"kind": "feature"}, "decision": {}}
        based = {**approved, "decision": {"base_revision": {"commit": "a" * 40}}, "result": {"revision": "b" * 40}}
        with patch.object(delivered_review.git, "names", return_value=None), \
                patch.object(delivered_review.git, "text", return_value=None):
            self.assertCodes([("OGK-RESULT-047", lambda: delivered_review.delivered_change(root, based))])
        self.assertCodes([
            ("OGK-RESULT-043", lambda: deliverables.new_draft({"requires_tool": True}, approved, None, [], root / "d")),
            ("OGK-RESULT-044", lambda: deliverables.new_draft({}, approved, None, [], root)),
            ("OGK-RESULT-045", lambda: delivered_review.require_reviewable({**approved, "answers": {"kind": "decision"}})),
            ("OGK-RESULT-046", lambda: delivered_review.require_reviewable(approved)),
        ])

    def test_issue_487_each_refused_answer_and_result_has_its_code(self):
        """Issue #487: task_questions, validate_answers, an evidence link, a check, a revision, a replay summary."""
        root = self.folder()
        answers = self.draft["answers"]
        summary = root / "summary.json"
        summary.write_text(json.dumps({"schema_version": 1, "results": [{"name": "login", "status": "late"}]}),
                           encoding="utf-8")
        decision = {"answers": {"kind": "decision"}, "decision": {"base_revision": {"commit": "HEAD"}}}
        self.assertCodes([
            ("OGK-RESULT-048", lambda: questionnaire.task_questions("  ")),
            ("OGK-RESULT-049", lambda: questionnaire.validate_answers([])),
            ("OGK-RESULT-050", lambda: questionnaire.validate_answers({**answers, "components": "api"})),
            ("OGK-RESULT-051", lambda: questionnaire.validate_answers({**answers, "context": 3})),
            ("OGK-RESULT-052", lambda: result_form._evidence_reference("https:// spaced", "evidence:x")),
            ("OGK-RESULT-054", lambda: result_form._check_source("rule:none", {}, "report")),
            ("OGK-RESULT-055", lambda: results.decision_changes(root, decision)),
            ("OGK-RESULT-056", lambda: results.chaosfolk_checks(root, summary)),
        ])


class DecisionAndRouteCodeTests(CodedCase):
    """Issue #487: a decision that cannot be verified, a board selection that removes too much."""

    def test_issue_487_each_unverifiable_decision_has_its_code(self):
        """Issue #487: changed_paths_since, committed_signers, verify_signature, _ssh_verify, check_decision."""
        root = self.folder()
        policy = {"mode": "signed", "approvers": ["Sam"], "allowed_signers": "keys"}
        with patch.object(decisions, "decision_problem", return_value=("seal", "The seal does not match.")):
            self.assertCodes([("OGK-DECISION-016", lambda: decisions.check_decision({}, root, {}))])
        with patch.object(decisions.shutil, "which", return_value=None):
            self.assertCodes([("OGK-DECISION-015", lambda: decisions._ssh_verify("", {}, "sig", "Sam"))])
        self.assertCodes([
            ("OGK-DECISION-012", lambda: decisions.changed_paths_since(root, "a" * 40)),
            ("OGK-DECISION-013", lambda: decisions.committed_signers(root, "keys")),
            ("OGK-DECISION-014", lambda: decisions.verify_signature(root, policy, {}, "sig", "Sam")),
        ])

    def test_issue_487_a_removal_of_a_board_not_proposed_or_of_every_board_has_its_code(self):
        """Issue #487: select_boards refuses an unknown removal and an empty consultation."""
        selection = test_brain_selection.BrainSelectionTests
        selection.setUpClass()
        case = selection()
        case.setUp()
        profile = case.profile()
        proposed = routing.select_boards(profile, case.catalog, case.task, case.answers)["routing"]

        def remove(boards):
            return lambda: routing.select_boards(profile, case.catalog, case.task, case.answers,
                                                 {"remove": boards, "reason": "Not needed."})

        self.assertCodes([("OGK-ROUTE-006", remove(["no-such-board"])), ("OGK-ROUTE-007", remove(list(proposed)))])


if __name__ == "__main__":
    unittest.main()
