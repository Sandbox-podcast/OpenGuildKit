"""The status index: the edit hook reads only the tasks that can cover an edit, and the index never decides."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import guard, task_index
from openguildkit.cli import main
from openguildkit.storage import write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
HOUR_NS = 3600 * 10 ** 9


class TaskIndexTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tasks = self.root / ".openguildkit" / "tasks"
        self.index = self.tasks / task_index.INDEX_FILE
        profile = {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), "guard": "enforce"}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")

    def run_cli(self, *arguments, code=0, stdin=None, typed=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        replaced = patch("sys.stdin", io.StringIO(stdin)) if stdin is not None else contextlib.nullcontext()
        terminal = patch("sys.stdin.isatty", return_value=True) if typed else contextlib.nullcontext()
        answer = patch("builtins.input", return_value=typed) if typed else contextlib.nullcontext()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), replaced, terminal, answer:
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

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


if __name__ == "__main__":
    unittest.main()
