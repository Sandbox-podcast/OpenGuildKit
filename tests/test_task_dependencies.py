"""Dependencies between tasks (issue #432): a task can wait for others, task list says what it waits for, --ready
lists the tasks nothing holds back, and the handoff says what to deliver first. A task without --after is unchanged."""

import json
import unittest

from openguildkit.storage import write_json
from openguildkit.tasks import record_problem, waiting_for
from tests.test_approval_lifecycle import EXAMPLE, ApprovalCase


class DependencyTests(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.init()

    def new(self, task_id, *after, code=0):
        arguments = [argument for name in after for argument in ("--after", name)]
        return self.run_cli("task", "new", f"Work {task_id}.", "--id", task_id, *arguments, code=code)

    def test_a_new_task_records_what_it_waits_for_and_says_their_status(self):
        self.new("api-schema")
        self.new("auth-flow")
        output, error = self.new("portal", "api-schema", "auth-flow")
        self.assertEqual(output, "portal\n")
        self.assertIn("Waits for api-schema (draft) and auth-flow (draft).", error)
        self.assertEqual(self.task("portal")["after"], ["api-schema", "auth-flow"])
        self.assertIsNone(record_problem(self.task("portal")))

    def test_an_unknown_task_itself_or_a_cycle_is_refused(self):
        self.new("api-schema")
        _, error = self.new("portal", "api-shema", code=1)
        self.assertIn("Unknown task: api-shema. Did you mean api-schema?", error)
        _, error = self.new("portal", "portal", code=1)
        self.assertIn("A task cannot wait for itself: portal.", error)
        # A task that waits for one deleted since: a new task under that ID would close a cycle.
        self.new("later", "api-schema")
        (self.state / "tasks" / "api-schema.json").unlink()
        _, error = self.new("api-schema", "later", code=1)
        self.assertIn("api-schema -> later -> api-schema", error)
        self.assertFalse((self.state / "tasks" / "api-schema.json").exists())

    def test_task_list_shows_what_each_task_waits_for_and_ready_hides_them(self):
        self.approve("sx")
        self.new("other")
        self.new("portal", "sx", "other")
        output, _ = self.run_cli("task", "list")
        self.assertIn("portal [draft] Work portal.\n    next: Answer the questionnaire and consult the boards.\n"
                      "    waits for: sx (approved), other (draft)\n", output)
        rows = {row["id"]: row for row in json.loads(self.run_cli("task", "list", "--json")[0])}
        self.assertEqual(rows["portal"]["waiting_for"], [{"task": "sx", "status": "approved"},
                                                         {"task": "other", "status": "draft"}])
        self.assertNotIn("waiting_for", rows["other"])
        ready = [row["id"] for row in json.loads(self.run_cli("task", "list", "--ready", "--json")[0])]
        self.assertEqual(ready, ["other", "sx"])
        output, _ = self.run_cli("task", "list", "--ready")
        self.assertNotIn("portal", output)

    def test_a_done_dependency_no_longer_holds_a_task_back_and_a_deleted_one_still_does(self):
        self.assertEqual(waiting_for({"after": ["a", "b", "c"]}, {"a": "done", "b": "done-with-reservations",
                                                                 "c": "approved"}),
                         [{"task": "c", "status": "approved"}])
        self.new("first")
        self.new("second", "first")
        (self.state / "tasks" / "first.json").unlink()
        rows = {row["id"]: row for row in json.loads(self.run_cli("task", "list", "--json")[0])}
        self.assertEqual(rows["second"]["waiting_for"], [{"task": "first", "status": "unknown"}])

    def test_the_handoff_says_first_what_to_deliver_before_and_does_not_block(self):
        self.new("auth-flow")
        self.approve_waiting("sx", "auth-flow")
        output, _ = self.run_cli("task", "handoff", "sx")
        self.assertTrue(output.startswith("Waits for auth-flow (draft): deliver it first; the order stays the "
                                          "person's decision.\n"), output[:200])
        self.assertIn("# Approved task handoff", output)

    def approve_waiting(self, task_id, after):
        """approve() with --after on task new."""
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id, "--after", after)
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", task_id, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        write_json(self.root / "review.json",
                   {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Agreed", typed=task_id)

    def test_a_task_without_after_is_written_and_listed_as_before(self):
        self.new("plain")
        self.assertNotIn("after", self.task("plain"))
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual(set(row), {"id", "status", "created", "owner", "brief", "next"})

    def test_a_damaged_after_field_is_named(self):
        self.new("plain")
        task = self.task("plain")
        self.assertEqual(record_problem({**task, "after": "x"}), "after must be a list")


if __name__ == "__main__":
    unittest.main()
