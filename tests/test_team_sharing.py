"""Team sharing through git: exported decisions are read back, and what git cannot share is named."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import read_json, write_json
from tests.support import CapturedCli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"


class SharingCase(CapturedCli, unittest.TestCase):
    """A small project with one approved task, and the commands that complete it or change its rules."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Support portal", "stack": ["Python"], "packs": [], "checks": [command]})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.state = self.root / ".openguildkit"

    def approved(self, task_id=TASK):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each request's status."}
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", task_id, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=task_id):
            self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Agreed")

    def complete(self, task_id=TASK):
        self.run_cli("task", "verify", task_id)
        checks = json.loads(self.run_cli("task", "checks", task_id, "--json")[0])
        rules = [{"check": c["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"}
                 for c in checks if c["kind"] == "rule"]
        write_json(self.root / "result.json", {"revision": "abc1234", "checks": rules, "criteria": [
            {"criterion": "Users only see their own requests.", "status": "met", "evidence": "README.md"}]})
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.run_cli("task", "result", task_id, "--file", self.root / "result.json")
        return self.run_cli("task", "complete", task_id)[1]

    def change_rules(self):
        """Add a check command: an approval rests on the checks, not on the conventions."""
        profile = read_json(self.state / "project.json")
        profile["checks"] = [*profile.get("checks", []), "python -m unittest discover -s tests"]
        write_json(self.state / "project.json", profile)
        self.run_cli("sync")


class TeamSharingTests(SharingCase):
    def test_the_decisions_of_the_repository_are_listed_with_their_status_and_validity(self):
        self.approved()
        self.run_cli("task", "export", TASK)
        shutil.rmtree(self.state / "tasks")
        rows = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertEqual(rows, [{"task": TASK, "status": "approved", "completed": False, "by": "Camille",
                                 "brief": rows[0]["brief"], "local": False, "problem": None,
                                 "path": f".openguildkit/decisions/{TASK}.json"}])
        self.change_rules()
        text = self.run_cli("task", "list", "--decisions")[0]
        self.assertIn(f"{TASK} [approved by Camille, not completed]", text)
        self.assertIn(f"The approval for {TASK} was recorded under earlier rules.", text)
        self.assertIn("no local task record", text)
        problem = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])[0]["problem"]
        self.assertEqual((problem["kind"], problem["severity"]), ("earlier-rules", "error"))

    def test_records_exported_before_the_completed_field_still_list(self):
        self.approved()
        self.run_cli("task", "export", TASK)
        path = self.state / "decisions" / f"{TASK}.json"
        record = read_json(path)
        del record["completed"]
        write_json(path, {**record, "status": "done"})
        write_json(self.state / "decisions" / "broken.json", ["not a record"])
        rows = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertEqual([(row["task"], row["status"]) for row in rows], [("broken", "unreadable"), (TASK, "done")])
        self.assertTrue(rows[1]["completed"])
        self.assertIn("[unreadable]", self.run_cli("task", "list", "--decisions")[0])

    def test_task_show_reads_an_exported_record_when_the_task_is_not_local(self):
        self.approved()
        self.run_cli("task", "export", TASK)
        (self.state / "tasks" / f"{TASK}.json").unlink()
        shown, note = self.run_cli("task", "show", TASK)
        self.assertEqual(json.loads(shown)["decision"]["by"], "Camille")
        self.assertIn(f"only as the exported record .openguildkit/decisions/{TASK}.json", note)
        self.assertIn("Unknown task", self.run_cli("task", "show", "missing", code=1)[1])

    def test_check_names_records_without_a_local_task_and_keeps_its_status(self):
        self.approved()
        self.run_cli("task", "export", TASK)
        shutil.rmtree(self.state / "tasks")
        output, warning = self.run_cli("check")
        self.assertIn("instructions match", output)
        self.assertIn(f"exported decisions name tasks absent from this copy: {TASK}", warning)
        self.assertIn("teammate", warning)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_check_warns_when_cited_evidence_cannot_travel_with_git(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("private/\n", encoding="utf-8")
        (self.root / "private").mkdir()
        (self.root / "private" / "dpia.md").write_text("Assessment\n", encoding="utf-8")
        (self.root / "shared.md").write_text("Assessment\n", encoding="utf-8")
        self.approved()
        path = self.state / "tasks" / f"{TASK}.json"
        task = read_json(path)
        task["result"] = {"checks": [
            {"check": "evidence:gdpr/dpia", "status": "passed", "evidence": "private/dpia.md"},
            {"check": "evidence:gdpr/register", "status": "passed", "evidence": f".openguildkit/tasks/{TASK}.json"},
            {"check": "evidence:gdpr/notice", "status": "passed", "evidence": "shared.md"},
            {"check": "evidence:gdpr/policy", "status": "passed", "evidence": "https://example.test/policy"},
        ]}
        write_json(path, task)
        warning = self.run_cli("check")[1]
        self.assertIn("private/dpia.md", warning)
        self.assertIn(f".openguildkit/tasks/{TASK}.json", warning)
        self.assertNotIn("shared.md", warning)
        self.assertNotIn("example.test", warning)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_check_also_reads_criteria_rule_and_pack_answers_but_not_the_verify_logs(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("private/\n", encoding="utf-8")
        (self.root / "private").mkdir()
        for name in ("criterion.md", "test_case.py", "rule.md", "pack.md"):
            (self.root / "private" / name).write_text("x\n", encoding="utf-8")
        self.approved()
        path = self.state / "tasks" / f"{TASK}.json"
        task = read_json(path)
        log = f".openguildkit/tasks/{TASK}-checks/command-1.log"
        task["result"] = {
            "criteria": [{"criterion": "Works.", "status": "met", "evidence": "private/criterion.md",
                          "verified_by": "private/test_case.py"},
                         {"criterion": "Also works.", "status": "met", "evidence": "Tried by hand."}],
            "checks": [{"check": "rule:python/follow-python-style", "status": "passed", "evidence": "private/rule.md"},
                       {"check": "command:1", "status": "failed", "evidence": log, "exit_code": 1}],
            "packs": [{"pack": "python", "status": "passed", "evidence": "private/pack.md"}],
        }
        write_json(path, task)
        warning = self.run_cli("check")[1]
        for name in ("criterion.md", "test_case.py", "rule.md", "pack.md"):
            self.assertIn(f"private/{name}", warning)
        self.assertNotIn(log, warning)
        self.assertNotIn("Tried by hand", warning)

    def test_export_before_completion_says_so_and_complete_reminds_to_export_again(self):
        self.approved()
        output, warning = self.run_cli("task", "export", TASK)
        record = read_json(self.state / "decisions" / f"{TASK}.json")
        self.assertFalse(record["completed"])
        self.assertIn("not completed yet", warning)
        completed = self.complete()
        self.assertIn(f"openguildkit task export {TASK}", completed)
        self.assertIn("commit", completed)
        # Once completed, the export warns no more and gives the next step only (issue #529).
        self.assertEqual(self.run_cli("task", "export", TASK)[1],
                         "Next: git add .openguildkit/decisions, then commit the record with the work in the pull request.\n")
        record = read_json(self.state / "decisions" / f"{TASK}.json")
        self.assertTrue(record["completed"])
        self.assertIn("completed_at", record)

    def test_a_teammate_record_keeps_its_id_and_is_never_replaced(self):
        self.approved()
        teammate = self.root / "teammate.json"
        self.run_cli("task", "export", TASK)
        shutil.copy(self.state / "decisions" / f"{TASK}.json", teammate)
        shutil.rmtree(self.state / "tasks")
        error = self.run_cli("task", "new", "Another thing", "--id", TASK, code=1)[1]
        self.assertIn(f"already used by the exported decision .openguildkit/decisions/{TASK}.json", error)
        self.assertIn(f"openguildkit task show {TASK}", error)
        self.assertIn("task list --decisions", self.run_cli("task", "handoff", TASK, code=1)[1])
        self.assertIn("task list --decisions", self.run_cli("task", "list")[0])
        (self.state / "decisions" / f"{TASK}.json").unlink()
        self.approved()
        shutil.copy(teammate, self.state / "decisions" / f"{TASK}.json")
        error = self.run_cli("task", "export", TASK, code=1)[1]
        self.assertIn("holds a decision record of another task", error)
        self.assertEqual((self.state / "decisions" / f"{TASK}.json").read_bytes(), teammate.read_bytes())

    def test_a_decisions_line_names_the_path_once(self):
        self.approved()
        self.run_cli("task", "export", TASK)
        self.change_rules()
        line = self.run_cli("task", "list", "--decisions")[0].splitlines()[1]
        self.assertEqual(line.count(f"{TASK}.json"), 1)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_result_and_complete_warn_about_evidence_a_reviewer_cannot_open(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("private/\n", encoding="utf-8")
        self.approved()
        path = self.state / "tasks" / f"{TASK}.json"
        task = read_json(path)
        task["result"] = {"checks": [{"check": "evidence:gdpr/dpia", "status": "passed", "evidence": "private/dpia.md"}]}
        write_json(path, task)
        self.assertIn("private/dpia.md", self.complete())

    def test_guard_json_lists_the_exported_decisions_apart_from_the_covering_tasks(self):
        self.approved()
        self.run_cli("task", "export", TASK)
        shutil.rmtree(self.state / "tasks")
        result = json.loads(self.run_cli("guard", "--json")[0])
        self.assertEqual(result["covered_by"], [])
        self.assertEqual(result["exported_decisions"], [TASK])


if __name__ == "__main__":
    unittest.main()
