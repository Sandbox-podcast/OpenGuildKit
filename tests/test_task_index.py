"""The status index: the edit hook reads only the tasks that can cover an edit, and the index never decides."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import guard, task_index, tasks
from openguildkit.results import evidence_fingerprint
from openguildkit.storage import write_json

from tests.support import CapturedCli, run_cli
from tests.test_performance import close_and_export

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
HOUR_NS = 3600 * 10 ** 9


class TaskIndexTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tasks = self.root / ".openguildkit" / "tasks"
        self.index = self.tasks / task_index.INDEX_FILE
        profile = {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": "enforce"}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")

    def consult(self, task_id):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
        self.run_cli("task", "consult", task_id, "--answers", EXAMPLE / "answers.json")

    def approve(self, task_id):
        self.consult(task_id)
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille Example", "--reason", "Agreed", typed=task_id)

    def age_records(self):
        """Date every task record an hour back, as records written before the index are."""
        for path in self.tasks.glob("*.json"):
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns - HOUR_NS, info.st_mtime_ns - HOUR_NS))

    def edit(self, code=0):
        hook = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.root / "app.py")}})
        return self.run_cli("guard", "--hook", "pre-edit", stdin=hook, code=code)

    def covered(self):
        return json.loads(self.run_cli("guard", "--json")[0])["covered_by"]

    def read_ids(self):
        """The covered tasks, and the task records the guard opened to find them (to check one, or for its status)."""
        with patch("openguildkit.guard.read_task", wraps=guard.read_task) as reader, \
                patch("openguildkit.task_index._record_status", wraps=task_index._record_status) as status:
            covered = self.covered()
        opened = {call.args[1] for call in reader.call_args_list} | {call.args[0].stem for call in status.call_args_list}
        return covered, sorted(opened)

    def test_the_hook_reads_only_the_approved_records_once_the_index_is_built(self):
        self.approve("approved-one")
        for index in range(4):
            self.run_cli("task", "new", f"Draft {index}.", "--id", f"draft-{index}")
        self.consult("consulted")
        self.age_records()
        self.assertEqual(self.read_ids(), (["approved-one"], ["approved-one", "consulted", "draft-0", "draft-1",
                                                              "draft-2", "draft-3"]))
        self.assertTrue(self.index.is_file())
        self.assertEqual(self.read_ids(), (["approved-one"], ["approved-one"]))
        self.edit()

    def test_a_task_that_is_done_is_not_read_again(self):
        self.approve("finished")
        record = json.loads((self.tasks / "finished.json").read_text(encoding="utf-8"))
        write_json(self.tasks / "finished.json", {**record, "status": "done", "result": {"checks": []}})
        self.age_records()
        self.assertEqual(self.read_ids(), ([], ["finished"]))
        self.assertEqual(self.read_ids(), ([], []))
        self.edit(code=2)

    def test_a_task_closed_with_reservations_is_not_read_again_either(self):
        self.approve("finished")
        record = json.loads((self.tasks / "finished.json").read_text(encoding="utf-8"))
        write_json(self.tasks / "finished.json", {**record, "status": "done-with-reservations", "result": {"checks": []}})
        self.age_records()
        self.assertEqual(self.read_ids(), ([], ["finished"]))
        self.assertEqual(self.read_ids(), ([], []))
        self.edit(code=2)

    def test_a_status_change_after_the_index_is_seen(self):
        self.consult("later")
        self.age_records()
        self.edit(code=2)
        self.assertEqual(self.read_ids(), ([], []))
        self.approve("other")
        self.assertEqual(self.covered(), ["other"])
        record = json.loads((self.tasks / "other.json").read_text(encoding="utf-8"))
        write_json(self.tasks / "other.json", {**record, "status": "done", "result": {"checks": []}})
        self.assertEqual(self.covered(), [])
        self.edit(code=2)

    def test_a_missing_or_corrupt_index_costs_time_and_never_changes_the_decision(self):
        self.approve("approved-one")
        self.consult("consulted")
        self.age_records()
        self.edit()
        for content in (None, b"", b"not json", b"[]", b'{"schema_version": 1, "tasks": []}',
                        b'{"schema_version": 1, "tasks": {"approved-one.json": "draft"}}', b"\xff\xfe"):
            with self.subTest(content=content):
                if content is None:
                    self.index.unlink()
                else:
                    self.index.write_bytes(content)
                self.assertEqual(self.read_ids(), (["approved-one"], ["approved-one", "consulted"]))
                self.edit()

    def test_an_index_that_calls_a_draft_approved_does_not_cover_an_edit(self):
        self.consult("consulted")
        self.age_records()
        self.edit(code=2)
        data = json.loads(self.index.read_text(encoding="utf-8"))
        data["tasks"]["consulted.json"]["status"] = "approved"
        self.index.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.read_ids(), ([], ["consulted"]))
        self.edit(code=2)

    def test_an_entry_that_no_longer_matches_its_file_is_read_again(self):
        self.approve("approved-one")
        self.age_records()
        self.covered()
        data = json.loads(self.index.read_text(encoding="utf-8"))
        data["tasks"]["approved-one.json"]["status"] = "draft"
        data["tasks"]["approved-one.json"]["stamp"][0] += 1
        self.index.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.covered(), ["approved-one"])

    def test_a_record_changed_just_before_the_index_is_checked_again(self):
        self.approve("approved-one")
        self.consult("consulted")
        self.covered()
        # Written less than the racy delay before the index: a coarse clock could hide a second change.
        self.assertEqual(self.read_ids(), (["approved-one"], ["approved-one", "consulted"]))

    def test_the_index_is_protected_and_ignored_with_the_task_records(self):
        self.approve("approved-one")
        self.covered()
        relative = self.index.relative_to(self.root).as_posix()
        self.assertTrue(guard._protected(relative))
        ignore = (self.root / ".openguildkit" / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("tasks/", ignore)
        self.assertEqual(sorted(path.name for path in self.tasks.iterdir() if path.name.startswith(".")),
                         [task_index.INDEX_FILE])
        listed = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual([row["id"] for row in listed], ["approved-one"])

    def test_an_index_that_cannot_be_written_only_costs_time(self):
        self.approve("approved-one")
        with patch("openguildkit.task_index.os.replace", side_effect=PermissionError("read-only")):
            self.assertEqual(self.covered(), ["approved-one"])
            self.edit()
        self.assertFalse(self.index.exists())
        self.assertEqual([path.name for path in self.tasks.iterdir() if path.name.endswith(".tmp")], [])


class TaskListIndexTests(unittest.TestCase):
    """task list reads the index first: a filter reads only the records it can list, and the output never depends on
    the index."""

    CLOSED = ["closed-0", "closed-1", "closed-2"]

    @classmethod
    def setUpClass(cls):
        """Three tasks closed and exported, one approved and one consulted, built once and copied for each test."""
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.template = template = Path(temporary.name).resolve()
        write_json(template / "profile.json",
                   {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), "checks": []})
        run_cli(template, "init", "--answers", template / "profile.json")
        for task_id in cls.CLOSED:
            close_and_export(template, task_id)
        for task_id in ("approved-0", "consulted-0"):
            run_cli(template, "task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
            run_cli(template, "task", "consult", task_id, "--answers", EXAMPLE / "answers.json")
        consultation = json.loads(run_cli(template, "task", "template", "approved-0").stdout)["consultation_id"]
        write_json(template / "review.json", {"consultation_id": consultation,
                                              **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))})
        run_cli(template, "task", "review", "approved-0", "--file", template / "review.json")
        run_cli(template, "task", "decide", "approved-0", "--approve", "--by", "Camille", "--reason", "Agreed",
                typed="approved-0")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "project"
        shutil.copytree(self.template, self.root)
        self.tasks = self.root / ".openguildkit" / "tasks"
        self.index = self.tasks / task_index.INDEX_FILE
        self.age_records()

    def age_records(self):
        """Date the task records and their exported records an hour back, as records of earlier days are."""
        for path in [*self.tasks.glob("*.json"), *(self.root / ".openguildkit" / "decisions").glob("*.json")]:
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns - HOUR_NS, info.st_mtime_ns - HOUR_NS))

    def listing(self, *options):
        """What task list prints with these options, and the task records it read."""
        with patch("openguildkit.tasks.read_task", wraps=tasks.read_task) as reader:
            result = run_cli(self.root, "task", "list", *options)
        return result.stdout + result.stderr, sorted(call.args[1] for call in reader.call_args_list)

    def test_a_status_filter_reads_only_the_records_the_index_gives_that_status(self):
        """Issue #534: task list --status approved read every record, 4.9 s to show 5 tasks of 1,000."""
        self.listing()
        out, reads = self.listing("--status", "approved", "--json")
        self.assertEqual([row["id"] for row in json.loads(out)], ["approved-0"])
        self.assertEqual(reads, ["approved-0"])

    def test_ready_reads_none_of_the_closed_records(self):
        """Issue #534: task list --ready read the closed records, which it never lists."""
        self.listing()
        out, reads = self.listing("--ready", "--json")
        self.assertEqual(sorted(row["id"] for row in json.loads(out)), ["approved-0", "consulted-0"])
        self.assertEqual(reads, ["approved-0", "consulted-0"])

    def test_task_list_reads_no_closed_record_once_the_index_keeps_its_line(self):
        """Issue #534: task list read every closed record at every run, 4.9 s at 1,000 tasks and 2.8 s read once."""
        first = self.listing("--json")
        self.assertEqual(first[1], ["approved-0", *self.CLOSED, "consulted-0"])
        self.assertEqual(self.listing("--json"), (first[0], ["approved-0", "consulted-0"]))
        data = json.loads(self.index.read_text(encoding="utf-8"))
        data["tasks"]["closed-1.json"]["line"]["code"] = "another release"
        self.index.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.listing("--json"), (first[0], ["approved-0", "closed-1", "consulted-0"]))

    def test_a_kept_line_gives_way_when_the_rules_change(self):
        """Issue #534: a closed task's line depends on the rules in force, which its record does not hold."""
        self.listing()
        run_cli(self.root, "profile", "add", "check", "python -m unittest", "--by", "Sam", "--reason", "Unit tests")
        out, reads = self.listing("--json")
        self.assertIn("completed under earlier rules", json.loads(out)[1]["next"])
        self.assertEqual(reads, ["approved-0", *self.CLOSED, "consulted-0"])
        self.index.unlink()
        self.assertEqual(self.listing("--json")[0], out)

    def test_a_kept_line_gives_way_when_another_task_takes_its_exported_record(self):
        """Issue #534: a closed task listed from the index must still be named when a teammate's record takes its ID."""
        self.listing()
        decisions = self.root / ".openguildkit" / "decisions"
        shutil.copyfile(decisions / "closed-1.json", decisions / "closed-0.json")
        out, reads = self.listing()
        self.assertIn("task closed-0 of this copy and the exported decision .openguildkit/decisions/closed-0.json", out)
        self.assertEqual(reads, ["approved-0", "closed-0", "consulted-0"])
        self.assertEqual(self.listing(), (out, reads))
        self.index.unlink()
        self.assertEqual(self.listing()[0], out)

    def test_a_closed_task_whose_evidence_has_a_fingerprint_shows_its_evidence_as_it_is_now(self):
        """Issue #534: the evidence a closed task cites can change on disk while its record does not."""
        proof = self.root / "docs" / "proof.md"
        proof.parent.mkdir()
        proof.write_text("Two accounts tested.\n", encoding="utf-8")
        record = json.loads((self.tasks / "closed-2.json").read_text(encoding="utf-8"))
        record["result"]["checks"].append({"check": "evidence:proof", "status": "passed", "evidence": "docs/proof.md",
                                           "fingerprint": evidence_fingerprint(self.root, "docs/proof.md"),
                                           "owner": "Camille"})
        write_json(self.tasks / "closed-2.json", record)
        self.age_records()
        self.assertNotIn("changed evidence", self.listing()[0])
        self.assertNotIn("changed evidence", self.listing()[0])
        proof.write_text("Rewritten.\n", encoding="utf-8")
        out, reads = self.listing()
        self.assertIn("    changed evidence: docs/proof.md changed since evidence:proof was recorded "
                      "(confirmed by Camille)", out)
        self.assertEqual(reads, ["approved-0", "closed-2", "consulted-0"])

    def test_a_missing_stale_or_corrupt_index_lists_the_same_tasks(self):
        """Issue #534: the index only saves reads; whatever its state, task list prints the same."""
        write_json(self.tasks / "broken.json", {"schema_version": 1, "id": "broken", "status": "done"})
        self.age_records()
        options = [(), ("--json",), ("--status", "approved", "--json"), ("--status", "done"), ("--ready", "--json")]
        expected = {}
        for option in options:
            self.index.unlink(missing_ok=True)
            expected[option], reads = self.listing(*option)
            self.assertEqual(reads, ["approved-0", "broken", *self.CLOSED, "consulted-0"])
        self.assertIn("broken [unreadable]", expected[("--status", "done")])

        def garbled(entry):
            return {**entry, "checked": "yes", "line": ["garbage"]}

        for state in ("up to date", "missing", "stale", "not json", "garbled"):
            with self.subTest(index=state):
                self.listing()
                data = json.loads(self.index.read_text(encoding="utf-8"))
                if state == "missing":
                    self.index.unlink()
                elif state == "stale":
                    for entry in data["tasks"].values():
                        entry["stamp"][0] += 1
                    self.index.write_text(json.dumps(data), encoding="utf-8")
                elif state == "not json":
                    self.index.write_bytes(b"{not json")
                elif state == "garbled":
                    data["tasks"] = {name: garbled(entry) for name, entry in data["tasks"].items()}
                    self.index.write_text(json.dumps(data), encoding="utf-8")
                for option in options:
                    self.assertEqual(self.listing(*option)[0], expected[option], option)


if __name__ == "__main__":
    unittest.main()
