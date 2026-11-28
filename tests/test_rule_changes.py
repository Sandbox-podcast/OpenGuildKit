"""A change of rules after an approval: one answer, naming what changed, an error for work not yet done and
history for a completed task, and a way back through a new consultation of the same task."""

import json
import shutil
from unittest.mock import patch

from openguildkit.storage import read_json, write_json
from tests.test_team_sharing import EXAMPLE, TASK, SharingCase

TEAM_PACK = {
    "id": "team-review", "title": "Team review", "version": "1.0.0", "description": "Follow the team's review.",
    "rules": [{"id": "owner", "instruction": "Name a change owner.", "verification": "Read the change record."}],
    "sources": [],
}


def read_task_status(state, task_id):
    return read_json(state / "tasks" / f"{task_id}.json")["status"]


class RuleChangeTests(SharingCase):
    def setUp(self):
        super().setUp()
        write_json(self.state / "catalog" / "packs" / "team-review.json", TEAM_PACK)
        profile = read_json(self.state / "project.json")
        profile["packs"].append("team-review")
        write_json(self.state / "project.json", profile)
        self.run_cli("sync")

    def edit_team_rule(self):
        pack = {**TEAM_PACK, "rules": [{**TEAM_PACK["rules"][0], "instruction": "Name a change owner and a backup."}]}
        write_json(self.state / "catalog" / "packs" / "team-review.json", pack)
        self.run_cli("sync")

    def test_an_approved_task_names_the_changed_rule_everywhere_and_check_fails(self):
        self.approved()
        self.edit_team_rule()
        message = f"The approval for {TASK} was recorded under earlier rules (rule team-review/owner changed)."
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual((row["approval_problem"], row["severity"]), ("earlier-rules", "error"))
        self.assertIn(message, row["next"])
        self.assertIn(message, self.run_cli("task", "show", TASK)[1])
        for action in ("handoff", "export", "verify"):
            self.assertIn(message, self.run_cli("task", action, TASK, code=1)[1])
        error = self.run_cli("check", code=1)[1]
        self.assertIn(f"{TASK}: {message}", error)
        self.assertTrue(error.endswith("but 1 approval no longer holds: each line above gives the command to run.\n"))
        self.assertNotIn("instructions match", self.run_cli("check", code=1)[0])
        self.assertIn(message, self.run_cli("task", "checks", TASK)[1])

    def test_a_review_under_earlier_rules_gives_the_same_next_step_everywhere(self):
        """A task reviewed but not decided when the rules change (every reviewed task of a project upgraded from
        0.16.1): task list, task consult and task decide all say that the person requests changes first."""
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each request's status."}
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual(row["next"], "Waiting for the person's decision.")
        self.edit_team_rule()
        message = (f"The rules, checks or boards of the project changed since {TASK} was consulted. The person requests "
                   f"changes (openguildkit task decide {TASK} --request-changes --by INITIALS --reason TEXT), then you "
                   "consult again.")
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual(row["next"], message)
        self.assertIn(message, self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json", code=1)[1])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.assertIn(message, self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason",
                                                "Agreed", code=1)[1])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--request-changes", "--by", "Camille", "--reason", "Rules changed")
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        self.assertEqual(read_task_status(self.state, TASK), "consulting")

    def test_a_new_pack_is_named(self):
        self.approved()
        self.change_rules()
        write_json(self.state / "catalog" / "packs" / "extra.json", {**TEAM_PACK, "id": "extra"})
        profile = read_json(self.state / "project.json")
        profile["packs"].append("extra")
        write_json(self.state / "project.json", profile)
        self.run_cli("sync")
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertIn("(pack extra added; checks changed)", row["next"])

    def test_consulting_again_reopens_the_approval_and_keeps_it_in_the_rounds(self):
        self.approved()
        self.edit_team_rule()
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        task = read_json(self.state / "tasks" / f"{TASK}.json")
        self.assertEqual(task["status"], "consulting")
        self.assertEqual(task["rounds"][-1]["decision"]["by"], "Camille")
        self.assertIn("rule team-review/owner changed", task["rounds"][-1]["reopened"])
        self.assertIn("Name a change owner and a backup.", json.dumps(task["consultation"]["scope"]["packs"]))
        self.run_cli("check")

    def test_a_current_approval_cannot_be_consulted_again(self):
        self.approved()
        error = self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json", code=1)[1]
        self.assertIn("is already approved by Camille", error)
        self.assertIn(f"openguildkit task revoke {TASK} --by INITIALS --reason TEXT", error)

    def test_a_completed_task_under_earlier_rules_is_history(self):
        self.approved()
        self.complete()
        self.edit_team_rule()
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual(row["severity"], "note")
        self.assertIn(f"Task {TASK} was completed under earlier rules (rule team-review/owner changed); its record "
                      "stays as history.", row["next"])
        self.assertEqual(self.run_cli("check")[1], "")
        output, note = self.run_cli("task", "export", TASK)
        self.assertIn("stays as history", note)
        self.assertTrue(read_json(self.root / output.strip())["completed"])
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json", code=1)

    def test_a_task_closed_with_reservations_is_history_too(self):
        self.approved()
        self.complete()
        path = self.state / "tasks" / f"{TASK}.json"
        write_json(path, {**read_json(path), "status": "done-with-reservations"})
        self.edit_team_rule()
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual(row["severity"], "note")
        self.assertEqual(self.run_cli("check")[1], "")

    def test_a_forged_approver_is_not_shown_and_check_fails(self):
        self.approved()
        path = self.state / "tasks" / f"{TASK}.json"
        write_json(path, {**read_json(path), "decision": {**read_json(path)["decision"], "by": "Mallory"}})
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertIsNone(row["owner"])
        self.assertIn("no longer matches what was approved", row["next"])
        self.assertIn("no longer matches what was approved", self.run_cli("check", code=1)[1])

    def test_a_removed_seal_does_not_turn_an_approval_into_history(self):
        self.approved()
        path = self.state / "tasks" / f"{TASK}.json"
        task = read_json(path)
        del task["decision"]["seal"]
        write_json(path, task)
        self.assertIn("has no seal", self.run_cli("check", code=1)[1])
        self.run_cli("task", "handoff", TASK, code=1)

    def test_an_exported_record_of_a_completed_task_is_history_once_rules_change(self):
        self.approved()
        self.complete()
        self.run_cli("task", "export", TASK)
        shutil.rmtree(self.state / "tasks")
        self.edit_team_rule()
        row, = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertEqual(row["problem"]["severity"], "note")
        self.assertNotIn("stays as history", self.run_cli("check")[1])
