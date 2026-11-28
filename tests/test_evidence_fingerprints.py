"""Evidence changed after it was accepted shows before the closing (issue #433): task clear and task result record a
fingerprint of the evidence, the closing and task list name a file changed since, and the export carries the state of
each evidence. A clearance recorded before fingerprints reads as before, shown with no fingerprint.

Whether a changed evidence should fail guard --ci in enforce is not decided yet (question Q2): until then it is an
open point of the closing and a note of task list, and guard --ci does not read it."""

import hashlib
import json
import unittest

from openguildkit.results import evidence_fingerprint, evidence_state
from openguildkit.storage import read_json
from openguildkit.tasks_blockers import _clearance_payload, resolve_blocker
from tests import test_results
from tests.test_approval_lifecycle import ApprovalCase
from tests.test_results import GDPR_RECORD, ResultCase

CHANGED_GROUP = "Evidence changed since it was accepted"


class ClearedCase(ApprovalCase):
    """An approved task with a blocker of phase verification, and its evidence docs/proof.md."""

    def setUp(self):
        super().setUp()
        self.init()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "proof.md").write_bytes(b"Two accounts tested.\n")
        self.approve("sx", verification_blocker=True)


class FingerprintTests(ClearedCase):
    def clear(self, evidence="docs/proof.md"):
        self.run_cli("task", "clear", "sx", "security:1", "--evidence", evidence, "--supports", "Two accounts tested.",
                     "--by", "Camille", typed="sx")
        return self.task("sx")["verification_blocker_resolutions"]["security:1"]

    def test_a_file_a_folder_and_a_link_get_their_fingerprint(self):
        digest = hashlib.sha256(b"Two accounts tested.\n").hexdigest()
        self.assertEqual(evidence_fingerprint(self.root, "docs/proof.md"), f"sha256:{digest}")
        listing = hashlib.sha256(b"proof.md").hexdigest()
        self.assertEqual(evidence_fingerprint(self.root, "docs"), f"sha256:{listing}")
        self.assertEqual(evidence_fingerprint(self.root, "https://example.org/aipd"), "external")
        self.assertEqual(self.clear()["fingerprint"], f"sha256:{digest}")

    def test_a_folder_fingerprint_follows_its_list_of_files_not_their_content(self):
        before = evidence_fingerprint(self.root, "docs")
        (self.root / "docs" / "proof.md").write_text("Rewritten.\n", encoding="utf-8")
        self.assertEqual(evidence_fingerprint(self.root, "docs"), before)
        (self.root / "docs" / "more.md").write_text("More.\n", encoding="utf-8")
        self.assertNotEqual(evidence_fingerprint(self.root, "docs"), before)

    def test_the_states_of_an_evidence(self):
        fingerprint = evidence_fingerprint(self.root, "docs/proof.md")
        self.assertEqual(evidence_state(self.root, "docs/proof.md", fingerprint), "unchanged")
        self.assertEqual(evidence_state(self.root, "docs/proof.md", None), "no fingerprint")
        self.assertEqual(evidence_state(self.root, "https://example.org/aipd", "external"), "external")
        (self.root / "docs" / "proof.md").write_text("Rewritten.\n", encoding="utf-8")
        self.assertEqual(evidence_state(self.root, "docs/proof.md", fingerprint), "changed")
        (self.root / "docs" / "proof.md").unlink()
        self.assertEqual(evidence_state(self.root, "docs/proof.md", fingerprint), "missing")

    def test_a_changed_evidence_is_named_by_task_list_and_task_blockers_until_it_is_restored(self):
        self.clear()
        self.assertIn("fingerprint: unchanged since it was cleared", self.run_cli("task", "blockers", "sx")[0])
        (self.root / "docs" / "proof.md").write_text("Rewritten after the clearance.\n", encoding="utf-8")
        listing = self.run_cli("task", "list")[0]
        self.assertIn("    changed evidence: docs/proof.md changed since blocker security:1 was cleared (cleared on ", listing)
        self.assertIn(" by Camille)", listing)
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual(len(row["evidence_changed"]), 1)
        self.assertIn("fingerprint: changed since it was cleared", self.run_cli("task", "blockers", "sx")[0])
        item, = [item for item in json.loads(self.run_cli("task", "blockers", "sx", "--json")[0])]
        self.assertEqual(item["evidence_state"], "changed")
        (self.root / "docs" / "proof.md").write_bytes(b"Two accounts tested.\n")
        self.assertNotIn("changed evidence", self.run_cli("task", "list")[0])

    def test_the_closing_keeps_a_changed_evidence_open_and_the_export_says_its_state(self):
        self.clear()
        (self.root / "docs" / "proof.md").write_text("Rewritten after the clearance.\n", encoding="utf-8")
        self.complete()
        self.assertEqual(self.task("sx")["status"], "done-with-reservations")
        closing = json.loads(self.run_cli("task", "show", "sx", "--closing")[0])
        group = next(group for group in closing["open_points"] if group["group"] == CHANGED_GROUP)
        self.assertEqual(len(group["points"]), 1)
        self.assertTrue(group["points"][0].startswith("docs/proof.md changed since blocker security:1 was cleared"))
        self.run_cli("task", "export", "sx")
        record = read_json(self.state / "decisions" / "sx.json")
        self.assertEqual(record["evidence_states"], [{"evidence": "docs/proof.md", "for": "blocker security:1",
                                                      "state": "changed"}])
        self.assertTrue(record["blockers"][0]["resolution"]["fingerprint"].startswith("sha256:"))
        # guard --ci does not read it until question Q2 is decided.
        self.assertEqual(self.run_cli("guard", "--json")[1], "")

    def test_a_restored_evidence_leaves_the_closing_as_it_was(self):
        self.clear()
        (self.root / "docs" / "proof.md").write_text("Rewritten after the clearance.\n", encoding="utf-8")
        (self.root / "docs" / "proof.md").write_bytes(b"Two accounts tested.\n")
        self.complete()
        self.assertEqual(self.task("sx")["status"], "done")
        self.run_cli("task", "export", "sx")
        record = read_json(self.state / "decisions" / "sx.json")
        self.assertEqual(record["evidence_states"][0]["state"], "unchanged")

    def test_a_link_is_external_and_never_an_open_point(self):
        self.assertEqual(self.clear("https://example.org/access-test")["fingerprint"], "external")
        self.assertIn("fingerprint: external link, cannot be checked", self.run_cli("task", "blockers", "sx")[0])
        self.complete()
        self.assertEqual(self.task("sx")["status"], "done")

    def complete(self):
        self.run_cli("task", "verify", "sx")
        checks = [{"check": check["id"], "status": "not-applicable", "reason": "No change in this area.",
                   "owner": "Camille"}
                  for check in json.loads(self.run_cli("task", "checks", "sx", "--json")[0]) if check["kind"] == "rule"]
        (self.root / "result.json").write_text(json.dumps({"revision": "working tree", "checks": checks, "criteria": [
            {"criterion": "Users only see their own requests.", "status": "met", "evidence": "docs/proof.md"}]}),
            encoding="utf-8")
        self.run_cli("task", "result", "sx", "--file", self.root / "result.json")
        self.run_cli("task", "complete", "sx", "--by", "Camille", typed="sx")


class SignedClearanceTests(ClearedCase):
    def test_the_fingerprint_is_in_what_the_person_signs_and_an_old_payload_is_unchanged(self):
        task = self.task("sx")
        profile = {**read_json(self.state / "project.json"), "approval": {"mode": "signed"}}
        payload = resolve_blocker(task, "security:1", {"kind": "cleared", "by": "Camille", "evidence": "docs/proof.md",
                                                        "supports": "Two accounts tested."}, profile, self.root,
                                  signing_payload=True)
        self.assertEqual(payload["fingerprint"], evidence_fingerprint(self.root, "docs/proof.md"))
        old = {"by": "Camille", "evidence": "docs/proof.md", "supports": "Two accounts tested."}
        self.assertNotIn("fingerprint", _clearance_payload(task, "security:1", old))


class NamedEvidenceTests(ResultCase):
    gdpr_task = test_results.ProportionateResultTests.gdpr_task
    answers = test_results.ProportionateResultTests.answers
    file = test_results.ProportionateResultTests.file
    documents = test_results.ProportionateResultTests.documents

    def test_a_named_evidence_changed_after_the_result_is_named_at_the_closing(self):
        self.gdpr_task()
        self.file(*self.answers(), *self.documents())
        recorded = next(item for item in self.record()["result"]["checks"] if item["check"] == GDPR_RECORD)
        self.assertEqual(recorded["fingerprint"], evidence_fingerprint(self.root, "docs/record.md"))
        (self.root / "docs" / "record.md").write_text("Rewritten.", encoding="utf-8")
        row = json.loads(self.run_cli("task", "list", "--json")[0])[0]
        self.assertEqual(row["evidence_changed"], [f"docs/record.md changed since {GDPR_RECORD} was recorded "
                                                   "(confirmed by Dana (DPO))"])


if __name__ == "__main__":
    unittest.main()
