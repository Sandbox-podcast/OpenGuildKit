import copy
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.tasks import record_decision, record_review, resolve_blocker
from openguildkit.workflow import blocker_list, consult, handoff

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"


class BlockerTests(unittest.TestCase):
    def setUp(self):
        catalog = load_catalog()
        self.profile = validate_profile({
            **json.loads((EXAMPLE / "profile.json").read_text()),
            "waivers": {"allowed_by": ["Camille Martin"], "max_days": 30},
        }, catalog)
        answers = json.loads((EXAMPLE / "answers.json").read_text())
        task = {"id": "request-status", "brief": "Show request status.", "answers": answers, "status": "consulting", "rounds": []}
        consultation = consult(resolved_profile(self.profile, catalog), catalog, task)
        review = {"consultation_id": consultation["id"], **json.loads((EXAMPLE / "review.json").read_text())}
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"]["verdict"] = "block"
        security["challenge"]["blockers"] = [
            {"finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
             "clears_when": "An automated test with two synthetic accounts passes."},
            {"finding": "Retention of request history is not decided.", "owner": "Data protection officer",
             "clears_when": "The retention period is recorded."},
        ]
        self.review = review
        self.task = record_review({**task, "consultation": consultation}, review)

    def test_each_blocker_names_an_owner_and_a_condition(self):
        broken = copy.deepcopy(self.review)
        next(entry for entry in broken["boards"] if entry["id"] == "security")["challenge"]["blockers"] = ["Fix access."]
        task = {**self.task, "status": "consulting"}
        task.pop("review")
        with self.assertRaisesRegex(ValueError, "finding, owner and clears_when"):
            record_review(task, broken)
        self.assertEqual([item["id"] for item in blocker_list(self.task)], ["security:1", "security:2"])

    def test_approval_waits_until_each_blocker_is_cleared_or_waived(self):
        with self.assertRaisesRegex(ValueError, "security:1, security:2"):
            record_decision(self.task, True, "Camille Martin", "Scope agreed")
        task = resolve_blocker(self.task, "security:1", {
            "kind": "cleared", "by": "Alex", "evidence": "tests/test_access.py", "supports": "Cross-account access is refused.",
        }, self.profile)
        until = (date.today() + timedelta(days=10)).isoformat()
        waiver = {"kind": "waived", "by": "Camille Martin", "reason": "Pilot with internal users only",
                  "scope": "Internal pilot", "until": until}
        task = resolve_blocker(task, "security:2", waiver, self.profile)
        approved = record_decision(task, True, "Camille Martin", "Scope agreed")
        brief = handoff(approved)
        self.assertIn("## Conditions from resolved blockers", brief)
        self.assertIn(until, brief)
        self.assertIn("tests/test_access.py", brief)
        record_decision(self.task, False, "Camille Martin", "Back to consultation")

    def test_waivers_follow_the_project_policy(self):
        until = (date.today() + timedelta(days=10)).isoformat()
        waiver = {"kind": "waived", "by": "Sam", "reason": "x", "scope": "y", "until": until}
        with self.assertRaisesRegex(ValueError, "cannot grant waivers"):
            resolve_blocker(self.task, "security:1", waiver, self.profile)
        waiver.update(by="Camille Martin", until=(date.today() + timedelta(days=90)).isoformat())
        with self.assertRaisesRegex(ValueError, "between 1 and 30 days"):
            resolve_blocker(self.task, "security:1", waiver, self.profile)
        no_policy = {key: value for key, value in self.profile.items() if key != "waivers"}
        with self.assertRaisesRegex(ValueError, "allows no waiver"):
            resolve_blocker(self.task, "security:1", {**waiver, "until": until}, no_policy)


if __name__ == "__main__":
    unittest.main()
