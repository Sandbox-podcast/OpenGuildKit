"""The open points of a closed task say what is open, between whom, and come most serious first."""

import unittest

from openguildkit.tasks_closing import points_left_open
from openguildkit.tasks_status import _approved_step


def closed_task(**extra) -> dict:
    task = {
        "id": "export", "answers": {"kind": "feature"}, "status": "approved",
        "consultation": {"boards": ["security", "legal"], "scope": {"packs": [], "checks": []}},
        "review": {"boards": [
            {"id": "security", "challenge": {"verdict": "block", "blockers": [{"finding": "No rate limit."}]}},
            {"id": "legal", "challenge": {"verdict": "revise", "blockers": []}},
        ]},
        "blocker_resolutions": {"security:1": {"kind": "waived", "by": "Camille", "reason": "Pilot only.",
                                               "scope": "Pilot", "until": "2026-12-31"}},
        "deliberation": {
            "objections": [{"id": "security-to-legal", "from": "security", "to": "legal",
                            "point": "Exports leave the EU through the mail provider."}],
            "responses": [], "agreed": [], "open": ["security-to-legal"],
            "decision_needed": "Choose whether exports may use the mail provider.",
        },
        "result": {"checks": [], "deferred": [{"check": "evidence:gdpr/x/y", "task": "follow", "owner": "the DPO",
                                               "by": "Camille", "at": "2026-11-22T10:00:00+00:00"}]},
    }
    return {**task, **extra}


class ClosingPointsTests(unittest.TestCase):
    def test_a_disagreement_names_its_point_its_boards_and_the_decision_needed(self):
        groups = {group["group"]: group["points"] for group in points_left_open(closed_task(), {})}
        points = groups["Disagreements between boards left open"]
        self.assertIn("security objects to legal: Exports leave the EU through the mail provider.", points[0])
        self.assertIn("Decision needed: Choose whether exports may use the mail provider.", points[-1])

    def test_a_block_not_lifted_comes_before_evidence_handed_to_a_follow_up(self):
        titles = [group["group"] for group in points_left_open(closed_task(), {})]
        self.assertIn("Board blocks not lifted", titles)
        self.assertLess(titles.index("Board blocks not lifted"), titles.index("Named evidence handed to a follow-up task"))
        groups = {group["group"]: group["points"] for group in points_left_open(closed_task(), {})}
        self.assertEqual(groups["Board blocks not lifted"],
                         ["security said block; blocker security:1 is waived until 2026-12-31, not cleared"])
        cleared = closed_task(blocker_resolutions={"security:1": {
            "kind": "cleared", "by": "Camille", "evidence": "tests/test_limit.py", "supports": "A limit exists."}})
        self.assertNotIn("Board blocks not lifted", [group["group"] for group in points_left_open(cleared, {})])

    def test_a_decision_with_an_expected_outcome_asks_for_its_criterion_first(self):
        decision = closed_task(answers={"kind": "decision", "outcome": "A format is chosen."})
        decision.pop("result")
        self.assertIn("task result export --template", _approved_step(decision))
        self.assertIn("then task complete export", _approved_step(decision))
        reported = {**decision, "result": {"criteria": [{"criterion": "A format is chosen.", "status": "met"}]}}
        self.assertTrue(_approved_step(reported).startswith("Decision recorded: close it with task complete export"))
        plain = closed_task(answers={"kind": "decision"})
        self.assertTrue(_approved_step(plain).startswith("Decision recorded: close it with task complete export"))


if __name__ == "__main__":
    unittest.main()
