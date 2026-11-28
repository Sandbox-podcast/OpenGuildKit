import copy
import io
from contextlib import redirect_stderr
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.catalog import load_catalog
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.decisions import check_decision
from openguildkit.tasks_blockers import resolve_blocker, verification_blocker_problems
from openguildkit.tasks_closing import complete_task, record_decision
from openguildkit.tasks_review import record_review
from openguildkit.consultation import consult
from openguildkit.workflow import blocker_list, handoff

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"


class BlockerTests(unittest.TestCase):
    def setUp(self):
        catalog = load_catalog()
        self.profile = validate_profile({
            **json.loads((EXAMPLE / "profile.json").read_text()),
            "waivers": {"allowed_by": ["Camille Martin"], "max_days": 30},
        }, catalog)
        answers = json.loads((EXAMPLE / "answers.json").read_text())
        task = {"id": "request-status", "brief": "Show request status.", "answers": answers, "status": "consulting", "rounds": [],
                "profile_fingerprint": "0" * 64}
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
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_access.py").write_text("def test_access(): pass\n", encoding="utf-8")

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
        }, self.profile, self.root)
        until = (clock.real_today() + timedelta(days=10)).isoformat()
        waiver = {"kind": "waived", "by": "Camille Martin", "reason": "Pilot with internal users only",
                  "scope": "Internal pilot", "until": until}
        task = resolve_blocker(task, "security:2", waiver, self.profile, self.root)
        approved = record_decision(task, True, "Camille Martin", "Scope agreed")
        brief = handoff(approved)
        self.assertIn("## Conditions from resolved blockers", brief)
        self.assertIn(until, brief)
        self.assertIn("tests/test_access.py", brief)
        record_decision(self.task, False, "Camille Martin", "Back to consultation")

    def test_verification_blockers_wait_for_evidence_after_approval_without_changing_its_seal(self):
        review = copy.deepcopy(self.review)
        blockers = next(entry for entry in review["boards"] if entry["id"] == "security")["challenge"]["blockers"]
        blockers[0]["phase"] = "verification"
        task = record_review({**self.task, "status": "consulting"}, review)
        resolution = {"kind": "cleared", "by": "Alex", "evidence": "tests/test_access.py",
                      "supports": "The retention period and access conditions are recorded."}
        with self.assertRaisesRegex(ValueError, "after approval"):
            resolve_blocker(task, "security:1", resolution, self.profile, self.root)
        task = resolve_blocker(task, "security:2", resolution, self.profile, self.root)
        approved = record_decision(task, True, "Camille Martin", "Scope agreed")
        self.assertIn("## Conditions of the approval, to meet before the task completes", handoff(approved))
        with self.assertRaisesRegex(ValueError, "Verification blocker security:1 is open"):
            complete_task(approved, self.profile)
        cleared = resolve_blocker(approved, "security:1", resolution, self.profile, self.root)
        check_decision(cleared, self.root, self.profile)
        self.assertEqual(verification_blocker_problems(cleared, self.profile), [])
        with self.assertRaisesRegex(ValueError, "already has a resolution"):
            resolve_blocker(cleared, "security:1", {**resolution, "by": "Bob"}, self.profile, self.root)
        self.assertEqual(blocker_list(cleared)[0]["resolution"]["by"], "Alex")

    def test_a_waiver_length_follows_the_real_clock_under_source_date_epoch(self):
        until = (clock.real_today() + timedelta(days=10)).isoformat()
        waiver = {"kind": "waived", "by": "Camille Martin", "reason": "Internal pilot", "scope": "Pilot", "until": until}
        for fixed in ("2000000000", "1000000000"):  # 2033-05-18 and 2001-09-09
            with self.subTest(fixed=fixed), patch.dict(os.environ, {"SOURCE_DATE_EPOCH": fixed}), \
                    redirect_stderr(io.StringIO()):
                task = resolve_blocker(self.task, "security:1", waiver, self.profile, self.root)
                self.assertEqual(task["blocker_resolutions"]["security:1"]["until"], until)

    def test_waivers_follow_the_project_policy(self):
        until = (clock.real_today() + timedelta(days=10)).isoformat()
        waiver = {"kind": "waived", "by": "Sam", "reason": "x", "scope": "y", "until": until}
        with self.assertRaisesRegex(ValueError, "cannot grant waivers"):
            resolve_blocker(self.task, "security:1", waiver, self.profile, self.root)
        waiver.update(by="Camille Martin", until=(clock.real_today() + timedelta(days=90)).isoformat())
        with self.assertRaisesRegex(ValueError, "between 1 and 30 days"):
            resolve_blocker(self.task, "security:1", waiver, self.profile, self.root)
        no_policy = {key: value for key, value in self.profile.items() if key != "waivers"}
        with self.assertRaisesRegex(ValueError, "allows no waiver"):
            resolve_blocker(self.task, "security:1", {**waiver, "until": until}, no_policy, self.root)


    def clear(self, evidence, **extra):
        return resolve_blocker(self.task, "security:1", {
            "kind": "cleared", "by": "Alex", "evidence": evidence, "supports": "Cross-account access is refused.", **extra,
        }, self.profile, self.root)

    def test_clearing_evidence_is_a_project_path_or_an_https_link(self):
        for evidence in ("x", "tests/missing.py", "../outside.py", "http://example.test/report", "https://"):
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, "existing file .* https link"):
                self.clear(evidence)
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(outside.rmdir)
        with self.assertRaisesRegex(ValueError, "https link"):
            self.clear(str(outside))
        cleared = self.clear(str(self.root / "tests" / "test_access.py"))
        self.assertEqual(cleared["blocker_resolutions"]["security:1"]["evidence"], "tests/test_access.py")
        linked = self.clear("https://ci.example.test/runs/42")
        self.assertEqual(linked["blocker_resolutions"]["security:1"]["evidence"], "https://ci.example.test/runs/42")

    def test_clearing_records_whether_it_was_run_at_a_terminal(self):
        self.assertEqual(self.clear("tests/test_access.py")["blocker_resolutions"]["security:1"]["recorded_from"], "no terminal")
        at_terminal = self.clear("tests/test_access.py", terminal=True)
        self.assertEqual(at_terminal["blocker_resolutions"]["security:1"]["recorded_from"], "terminal")


if __name__ == "__main__":
    unittest.main()
