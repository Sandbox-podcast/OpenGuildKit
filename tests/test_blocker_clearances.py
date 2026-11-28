"""Clearances of both phases read through one function: evidence, rounds and old records (issue #205)."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.project import validate_profile
from openguildkit.project_rules import resolved_profile
from openguildkit.tasks import (
    _record_problem, archived_round, cited_evidence, record_consultation, record_decision, record_review,
    resolve_blocker, verification_blocker_problems,
)
from openguildkit.consultation import consult
from openguildkit.workflow import blocker_list, blocker_resolutions, exported_blockers
from tests.test_approval_lifecycle import ApprovalCase

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"


class ClearanceAccessTests(unittest.TestCase):
    """An approved task whose condition of approval (phase verification) is cleared after the approval."""

    def setUp(self):
        self.catalog = load_catalog()
        self.profile = validate_profile(json.loads((EXAMPLE / "profile.json").read_text()), self.catalog)
        self.answers = json.loads((EXAMPLE / "answers.json").read_text())
        task = {"id": "sx", "brief": "Show request status.", "answers": self.answers, "status": "consulting",
                "rounds": [], "created_at": "2026-11-22T09:00:00+00:00", "schema_version": 1,
                "profile_fingerprint": "0" * 64}
        consultation = consult(resolved_profile(self.profile, self.catalog), self.catalog, task)
        review = {"consultation_id": consultation["id"], **json.loads((EXAMPLE / "review.json").read_text())}
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"]["verdict"] = "block"
        security["challenge"]["blockers"] = [
            {"finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
             "clears_when": "An automated test with two synthetic accounts passes.", "phase": "verification"},
            {"finding": "Retention is not decided.", "owner": "Data protection officer",
             "clears_when": "The retention period is recorded."},
        ]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "retention.md").write_text("Two years.\n", encoding="utf-8")
        (self.root / "local").mkdir()
        (self.root / "local" / "proof.txt").write_text("Two accounts tested.\n", encoding="utf-8")
        reviewed = record_review({**task, "consultation": consultation}, review)
        reviewed = resolve_blocker(reviewed, "security:2", {
            "kind": "cleared", "by": "Alex", "evidence": "docs/retention.md", "supports": "Retention is recorded."},
            self.profile, self.root)
        approved = record_decision(reviewed, True, "Camille Martin", "Scope agreed")
        self.approved = resolve_blocker(approved, "security:1", {
            "kind": "cleared", "by": "Camille Martin", "evidence": "local/proof.txt", "supports": "Two accounts tested.",
            "signer": "camille@example.test", "signature": "-----BEGIN SSH SIGNATURE-----\nU1NIU0lH\n"},
            self.profile, self.root)
        # A local project keeps no signature: the test stores one as a signed project would.
        self.approved["verification_blocker_resolutions"]["security:1"].update(
            signer="camille@example.test", signature="-----BEGIN SSH SIGNATURE-----\nU1NIU0lH\n")

    def test_one_function_reads_the_clearances_of_both_phases(self):
        self.assertEqual(sorted(self.approved["verification_blocker_resolutions"]), ["security:1"])
        self.assertEqual(sorted(blocker_resolutions(self.approved)), ["security:1", "security:2"])
        self.assertEqual([item["resolution"]["by"] for item in blocker_list(self.approved)], ["Camille Martin", "Alex"])
        self.assertEqual(verification_blocker_problems(self.approved, self.profile), [])

    def test_evidence_cited_by_a_clearance_of_either_phase_is_listed(self):
        self.assertIn("local/proof.txt", cited_evidence(self.approved))
        self.assertIn("docs/retention.md", cited_evidence(self.approved))

    def test_a_new_consultation_keeps_the_clearances_of_both_phases_and_the_signature_in_the_rounds(self):
        reopened = record_consultation(self.approved, self.answers, self.profile, self.catalog, root=self.root)
        archived = reopened["rounds"][-1]
        self.assertIn("earlier rules", archived["reopened"])
        self.assertEqual(archived["blocker_resolutions"]["security:2"]["evidence"], "docs/retention.md")
        cleared = archived["verification_blocker_resolutions"]["security:1"]
        self.assertEqual((cleared["by"], cleared["evidence"], cleared["signer"]),
                         ("Camille Martin", "local/proof.txt", "camille@example.test"))
        self.assertTrue(cleared["signature"].startswith("-----BEGIN SSH SIGNATURE-----"))
        self.assertNotIn("verification_blocker_resolutions", reopened)
        self.assertEqual(archived, {**archived_round(self.approved), "reopened": archived["reopened"]})

    def test_records_with_either_field_read_without_error_and_keep_their_clearances(self):
        self.assertIsNone(_record_problem(self.approved))
        # Before the field of phase verification, a clearance given after approval sat with the others.
        older = copy.deepcopy(self.approved)
        older["blocker_resolutions"]["security:1"] = older.pop("verification_blocker_resolutions")["security:1"]
        self.assertIsNone(_record_problem(older))
        self.assertEqual(blocker_list(older)[0]["resolution"]["evidence"], "local/proof.txt")
        self.assertEqual(verification_blocker_problems(older, self.profile), [])
        self.assertIn("local/proof.txt", cited_evidence(older))

    def test_the_exported_blockers_name_the_phase_who_resolved_and_the_evidence(self):
        shown = {item["id"]: item for item in exported_blockers(self.approved)}
        self.assertEqual((shown["security:1"]["phase"], shown["security:2"]["phase"]), ("verification", "approval"))
        resolution = shown["security:1"]["resolution"]
        self.assertEqual({key: resolution[key] for key in ("kind", "by", "evidence", "supports")},
                         {"kind": "cleared", "by": "Camille Martin", "evidence": "local/proof.txt",
                          "supports": "Two accounts tested."})
        self.assertNotIn("signature", resolution)


@unittest.skipIf(shutil.which("git") is None, "needs git")
class CheckWarningTests(ApprovalCase):
    def test_check_warns_about_ignored_evidence_cited_by_a_condition_cleared_after_approval(self):
        self.git("init", "-q", "-b", "main")
        self.init()
        (self.root / ".gitignore").write_text("local/\n", encoding="utf-8")
        (self.root / "local").mkdir()
        (self.root / "local" / "proof.txt").write_text("Two accounts tested.\n", encoding="utf-8")
        self.approve("sx", verification_blocker=True)
        self.assertNotIn("cites evidence", self.run_cli("check")[1])
        self.run_cli("task", "clear", "sx", "security:1", "--evidence", "local/proof.txt", "--supports",
                     "Two accounts tested.", "--by", "Camille", typed="sx")
        _, error = self.run_cli("check")
        self.assertIn("task sx cites evidence a reviewer cannot open from the repository", error)
        self.assertIn("local/proof.txt", error)


if __name__ == "__main__":
    unittest.main()
