"""An exported decision record is read by teammates and CI: what it shows must be what was sealed and exported.

The approval's seal covers a digest of what the record shows of the approval (brief, summary, each board's verdict
and recommendation, earlier rounds); a digest of the whole record covers what was added after (completion, result).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from openguildkit.decisions import decision_payload, record_digest, seal
from openguildkit.storage import read_json, write_json
from tests.test_team_sharing import EXAMPLE, TASK, SharingCase

FIXTURE = Path(__file__).with_name("fixtures") / "upgrade" / "decision-record-v1.json"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.test",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.test"}


def earlier_release_record(case) -> dict:
    """The record an earlier release wrote for the approved task: no digests, an approval sealed without them."""
    task = read_json(case.state / "tasks" / f"{TASK}.json")
    case.run_cli("task", "export", TASK)
    record = read_json(case.state / "decisions" / f"{TASK}.json")
    for key in ("record_sha256", "task_created_at"):
        record.pop(key)
    decision = task["decision"]
    payload = decision_payload(task, decision["by"], decision["reason"], decision.get("base_revision"), version=1)
    record["decision"].update(payload=payload, seal=seal(payload))
    record["schema_version"] = 1
    return record


class RecordIntegrityTests(SharingCase):
    def record_path(self, task_id=TASK):
        return self.state / "decisions" / f"{task_id}.json"

    def exported(self, task_id=TASK):
        self.run_cli("task", "export", task_id)
        return read_json(self.record_path(task_id))

    def assert_refused_everywhere(self, words, task_id=TASK):
        """check fails naming the record, the listing shows the problem, the record covers nothing."""
        error = self.run_cli("check", code=1)[1]
        self.assertIn(f".openguildkit/decisions/{task_id}.json", error)
        self.assertIn(words, error)
        row = next(row for row in json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
                   if row["path"].endswith(f"/{task_id}.json"))
        self.assertEqual(row["problem"]["severity"], "error")
        self.assertIn(words, row["problem"]["message"])
        self.assertNotIn(task_id, json.loads(self.run_cli("guard", "--json")[0])["exported_decisions"])

    def forge(self, change, task_id=TASK):
        record = read_json(self.record_path(task_id))
        change(record)
        write_json(self.record_path(task_id), record)

    def test_a_forged_brief_verdict_or_summary_is_refused(self):
        self.approved()
        self.exported()

        def forged(record):
            record["brief"] = "Something different entirely: delete everything"
            record["summary"] = "All fine"
            for board in record["boards"]:
                board["verdict"] = "proceed"
        self.forge(forged)
        self.assert_refused_everywhere("does not match what was approved")
        (self.state / "tasks" / f"{TASK}.json").unlink()
        self.assertIn("does not match what was approved", self.run_cli("task", "show", TASK)[1])

    def test_an_edited_result_is_refused(self):
        self.approved()
        self.complete()
        self.exported()
        self.forge(lambda record: record["result"]["checks"].update({"command:1": "passed"}) or
                   record["result"].update(revision="0000000"))
        self.assert_refused_everywhere("was changed after it was exported")

    def test_a_removed_round_is_refused(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each status."}
        write_json(self.root / "answers.json", answers)
        for decide in (("--request-changes",), ("--approve",)):
            self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
            template = json.loads(self.run_cli("task", "template", TASK)[0])
            write_json(self.root / "review.json",
                       {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())})
            self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
                self.run_cli("task", "decide", TASK, *decide, "--by", "Camille", "--reason", "Agreed")
        self.assertEqual(len(self.exported()["rounds"]), 1)
        self.forge(lambda record: record.pop("rounds"))
        self.assert_refused_everywhere("does not match what was approved")

    def test_two_swapped_records_are_refused(self):
        self.approved()
        self.approved("history")
        first, second = self.exported(), self.exported("history")
        write_json(self.record_path(), second)
        write_json(self.record_path("history"), first)
        self.assert_refused_everywhere("names task history")

    def test_a_removed_digest_is_refused_and_a_downgrade_is_only_an_old_record(self):
        self.approved()
        self.exported()
        self.forge(lambda record: record.pop("record_sha256"))
        self.assert_refused_everywhere("was changed after it was exported")
        self.forge(lambda record: record.update(schema_version=1))
        self.assert_refused_everywhere("was changed after it was exported")

    def test_the_record_fixture_of_an_earlier_release_still_loads(self):
        write_json(self.record_path(), read_json(FIXTURE)["record"])
        row, = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertIn(row["problem"]["kind"], ("earlier-record", "earlier-rules"))
        self.assertEqual(json.loads(self.run_cli("task", "show", TASK)[0])["task"], TASK)

    def test_the_record_lists_each_blocker_with_its_phase_and_how_it_was_cleared(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        write_json(self.root / "answers.json", {**json.loads((EXAMPLE / "answers.json").read_text()),
                                                "outcome": "Customers see each request's status."})
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"]["verdict"] = "block"
        security["challenge"]["blockers"] = [
            {"finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
             "clears_when": "An automated test with two synthetic accounts passes."},
            {"finding": "Retention of request history is not decided.", "owner": "Data protection officer",
             "clears_when": "The retention period is recorded.", "phase": "verification"},
        ]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        (self.root / "README.md").write_text("Two-account access test: passed.\n", encoding="utf-8")
        clear = ("task", "clear", TASK, "--by", "Camille", "--evidence", "README.md")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli(*clear[:3], "security:1", *clear[3:], "--supports", "The two-account test passes.")
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        first, second = self.exported()["blockers"]
        self.assertEqual({key: first[key] for key in ("id", "board", "phase", "owner")},
                         {"id": "security:1", "board": "security", "phase": "approval", "owner": "Security lead"})
        self.assertEqual({key: first["resolution"][key] for key in ("kind", "by", "evidence", "supports", "recorded_from")},
                         {"kind": "cleared", "by": "Camille", "evidence": "README.md",
                          "supports": "The two-account test passes.", "recorded_from": "terminal"})
        self.assertEqual((second["phase"], second["resolution"]), ("verification", None))
        self.assertEqual(second["finding"], "Retention of request history is not decided.")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli(*clear[:3], "security:2", *clear[3:], "--supports", "Retention is recorded.")
        self.assertEqual(self.exported()["blockers"][1]["resolution"]["supports"], "Retention is recorded.")
        self.run_cli("check")

    def test_a_record_from_an_earlier_release_loads_as_unverified(self):
        self.approved()
        write_json(self.record_path(), earlier_release_record(self))
        (self.state / "tasks" / f"{TASK}.json").unlink()
        row, = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertEqual((row["problem"]["kind"], row["problem"]["severity"]), ("earlier-record", "note"))
        self.assertIn(f"openguildkit task export {TASK}", row["problem"]["message"])
        self.assertEqual(self.run_cli("check")[1].count("exported by an earlier release"), 0)
        self.assertIn("exported by an earlier release", self.run_cli("task", "show", TASK)[1])

    def test_a_reexport_upgrades_an_earlier_record_of_the_same_task(self):
        self.approved()
        write_json(self.record_path(), earlier_release_record(self))
        self.assertNotIn("record_sha256", read_json(self.record_path()))
        self.assertIn("record_sha256", self.exported())


class CiRecordTests(SharingCase):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, env=GIT_ENV)

    def ci_with(self, record_change=None, record=None):
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        path = self.state / "decisions" / f"{TASK}.json"
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.git("add", "app.py")
        if record is None:
            self.approved()
            self.run_cli("task", "export", TASK)
            record = read_json(path)
        if record_change:
            record_change(record)
        write_json(path, record)
        self.git("add", "app.py", ".openguildkit/decisions")
        self.git("commit", "-q", "-m", "change")
        return json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json")[0])

    def ci(self):
        return json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json")[0])

    def commit(self, message, *paths):
        self.git("add", *paths)
        self.git("commit", "-q", "-m", message)

    def merged_approval(self):
        """A task approved, its work and its record merged into main, then a branch to complete it."""
        self.git("init", "-q", "-b", "main")
        self.commit("base", "-A")
        self.git("checkout", "-q", "-b", "feature")
        self.approved()
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.run_cli("task", "export", TASK)
        self.commit("the approved work", "app.py", ".openguildkit/decisions")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--ff-only", "feature")
        self.git("checkout", "-q", "-b", "completion")

    def test_ci_accepts_an_intact_record(self):
        if shutil.which("git") is None:
            self.skipTest("needs git")
        result = self.ci_with()
        self.assertEqual(result["decisions"], [TASK])
        self.assertEqual((result["problems"], result["ok"]), ([], True))

    def test_ci_accepts_a_record_that_only_adds_the_completion_of_an_approval_on_the_base(self):
        if shutil.which("git") is None:
            self.skipTest("needs git")
        self.merged_approval()
        message = self.complete()
        self.assertIn("in a pull request of its own", message)
        self.run_cli("task", "export", TASK)
        self.commit("completion", ".openguildkit/decisions")
        record = read_json(self.state / "decisions" / f"{TASK}.json")
        self.assertTrue(record["completed"])
        self.assertEqual(record["files"], ["app.py"])
        result = self.ci()
        self.assertEqual((result["decisions"], result["problems"], result["ok"]), ([TASK], [], True))

    def test_ci_refuses_a_new_approval_under_an_id_the_base_already_used(self):
        if shutil.which("git") is None:
            self.skipTest("needs git")
        self.merged_approval()
        self.git("checkout", "-q", "main")
        self.change_rules()
        self.commit("new rules", "-u")
        self.git("checkout", "-q", "-b", "reapproval")
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        write_json(self.root / "review.json",
                   {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed again")
        self.run_cli("task", "export", TASK)
        self.commit("a new approval", ".openguildkit/decisions")
        result = self.ci()
        self.assertEqual(result["decisions"], [])
        self.assertIn(f"task {TASK} already had another approval on the base revision", result["problems"][0])

    def test_ci_refuses_a_forged_record(self):
        if shutil.which("git") is None:
            self.skipTest("needs git")
        result = self.ci_with(lambda record: record.update(brief="Delete everything"))
        self.assertEqual(result["decisions"], [])
        self.assertIn("does not match what was approved", result["problems"][0])

    def test_ci_refuses_a_record_from_an_earlier_release(self):
        if shutil.which("git") is None:
            self.skipTest("needs git")
        self.approved()
        record = earlier_release_record(self)
        (self.state / "decisions" / f"{TASK}.json").unlink()
        result = self.ci_with(record=record)
        self.assertEqual(result["decisions"], [])
        self.assertIn("exported by an earlier release", result["problems"][0])

    def test_ci_says_when_its_problems_do_not_fail_the_job(self):
        if shutil.which("git") is None:
            self.skipTest("needs git")
        self.ci_with(lambda record: record.update(brief="Delete everything"))
        output = self.run_cli("guard", "--ci", "--base", "main")[0]
        self.assertIn("Not enforced: the guard mode of main is observe, so this job passes", output)


class SharedIdTests(SharingCase):
    """Two copies that used the same task ID: a conflict in git, or two different tasks once one side is taken."""

    record_path = RecordIntegrityTests.record_path
    exported = RecordIntegrityTests.exported
    forge = RecordIntegrityTests.forge
    assert_refused_everywhere = RecordIntegrityTests.assert_refused_everywhere

    def teammate_record(self):
        """A record exported by another copy for a different task with the same ID."""
        self.approved()
        record = self.exported()
        shutil.rmtree(self.state / "tasks")
        self.record_path().unlink()
        return record

    def test_a_record_with_git_conflict_markers_is_named_as_a_conflict(self):
        theirs = self.teammate_record()
        theirs["decision"]["by"] = "Alex Tester"
        self.approved()
        ours = self.exported()
        text = ("<<<<<<< HEAD\n" + json.dumps(ours, indent=2) + "\n=======\n" + json.dumps(theirs, indent=2)
                + "\n>>>>>>> 4f2a9c1 (Export status-filter)\n")
        self.record_path().write_text(text, encoding="utf-8")
        row, = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        message = row["problem"]["message"]
        self.assertIn("git merge conflict", message)
        self.assertIn("HEAD (this copy) approved by Camille", message)
        self.assertIn("4f2a9c1 approved by Alex Tester", message)
        self.assertIn("docs/workflow.md", message)
        self.assertIn("git merge conflict", self.run_cli("check", code=1)[1])
        self.assertIn("git merge conflict", self.run_cli("task", "export", TASK, code=1)[1])

    def test_a_local_task_and_another_task_record_with_the_same_id_are_named(self):
        theirs = self.teammate_record()
        self.approved()
        write_json(self.record_path(), theirs)
        warning = self.run_cli("check")[1]
        self.assertIn(f"task {TASK} of this copy and the exported decision .openguildkit/decisions/{TASK}.json "
                      "are different tasks", warning)
        self.assertIn("--id", warning)
        self.assertIn("are different tasks", self.run_cli("task", "list")[1])
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual(row["id_used_by_record"], f".openguildkit/decisions/{TASK}.json")

    def test_a_forged_completion_is_refused(self):
        self.approved()
        self.exported()

        def completed(record):
            record.update(completed=True, status="completed")
            record["record_sha256"] = record_digest(record)
        self.forge(completed)
        self.assert_refused_everywhere("its completion")

        def done_without_closing(record):
            record.update(completed=True, status="done", completed_at="2026-11-22T10:00:00+00:00")
            record["record_sha256"] = record_digest(record)
        self.forge(done_without_closing)
        self.assert_refused_everywhere("its completion")

    def test_a_real_completion_is_accepted(self):
        self.approved()
        self.complete()
        record = self.exported()
        self.assertTrue(record["completed"])
        self.run_cli("check")
