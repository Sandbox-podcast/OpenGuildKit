"""A short-lane task from its request to `done` and its exported record, on a trial project with Git.

The lane shortens the framing, the choice of boards and the deliberation; the passes, the review, the person's decision at
a terminal, the handoff, the checks, the results, the closing and the export are the ones of every task. The person
turns the lane on and decides at a pseudo-terminal, as a person does.
"""

import json
import os
import subprocess
import sys
import unittest

from tests.e2e.test_cli_flow import CliTestCase

TASK = "guide-typo"
BOARD = "developer-relations-and-docs"
BRIEF = "Fix the typo in the export page of the guide: it says exprot."


@unittest.skipUnless(os.name == "posix", "the decision needs a pseudo-terminal, available on Linux and macOS")
class ShortLaneJourneyTests(CliTestCase):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

    def setUp(self):
        super().setUp()
        command = f'"{sys.executable}" -c "print(1)"'
        profile = {"personal_data": "no", "name": "Support portal", "stack": ["Python"], "packs": [], "checks": [command],
                   "guard": "enforce"}
        self.run_cli("init", "--answers", self.write_json("profile.json", profile))
        code, _, stderr = self.in_terminal(("profile", "set", "light-paths", "docs/**", "tests/**", "--by", "Test Owner",
                                            "--reason", "Docs and tests fixes"), "docs/** tests/**")
        self.assertEqual(code, 0, stderr)
        (self.project / "docs").mkdir()
        (self.project / "docs" / "guide.md").write_text("# Guide\n\nThe exprot page lists your reports.\n", encoding="utf-8")
        (self.project / "notes.md").write_text("The export page is the only page of the guide that names exports.\n",
                                               encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        # The agent's working files go where Git ignores them: anything else it leaves is a file outside the lane.
        (self.project / ".openguildkit" / "work").mkdir()

    def task_json(self, task_id=TASK):
        return json.loads(self.run_cli("task", "show", task_id, "--json").stdout)

    def entry(self):
        template = json.loads(self.run_cli("task", "template", TASK).stdout)
        entry = template["boards"][0]
        entry.update(recommendation="Fix the typo in the guide.", open_questions=[],
                     evidence=[{"source": "project-file", "ref": "notes.md", "supports": "The export page is the one to fix."}])
        challenge = entry["challenge"]
        for lens in challenge["specialists"]:
            lens.update(finding="The notes name the export page.", basis="observed", evidence_refs=[1])
        challenge.update(verdict="proceed", confidence="medium", alternative="Leave the typo.",
                         failure_mode="A second typo stays on the page.", verification="Read the page again.")
        return entry

    def test_a_short_lane_task_goes_from_the_request_to_done_and_to_its_record(self):
        created = self.run_cli("task", "new", BRIEF, "--id", TASK, "--lane", "light", "--paths", "docs/**")
        self.assertEqual(created.stdout.strip(), TASK)
        self.assertIn("no questions", created.stderr)

        # No questionnaire: the lane's answers, one board chosen by the paths.
        consultation = self.run_cli("task", "consult", TASK).stdout
        record = self.task_json()
        self.assertEqual(record["consultation"]["boards"], [BOARD])
        self.assertEqual(record["answers"]["concerns"], ["none"])
        self.assertIn("- Short lane: docs/**.", consultation)

        # The pass and its submission are the full path's.
        brief = self.run_cli("task", "pass", TASK, BOARD).stdout
        self.assertIn(f"# Board pass: {BOARD}", brief)
        self.assertEqual(self.run_cli("task", "submit", TASK, "--file", self.write_json(".openguildkit/work/entry.json", self.entry())).stdout.strip(),
                         "done")
        self.assertEqual(self.run_cli("task", "review", TASK, "--summary", "The board agrees: fix the one typo.").stdout.strip(),
                         "reviewed")
        deliberation = self.run_cli("task", "deliberate", TASK)
        self.assertEqual(json.loads(deliberation.stdout)["objections"], [])
        self.assertIn("nothing to deliberate", deliberation.stderr)
        self.assertIn("Short lane, covering only docs/**", self.run_cli("task", "challenge", TASK).stdout)

        # The person decides at a terminal, with the lane and the paths in front of them.
        refused = self.run_cli("task", "decide", TASK, "--approve", "--by", "Agent", "--reason", "Quick", expect=1)
        self.assertIn("interactive terminal", refused.stderr)
        code, _, stderr = self.in_terminal(("task", "decide", TASK, "--approve", "--by", "Test Owner", "--reason", "Typo only"),
                                           "wrong-id")
        self.assertEqual(code, 1, stderr)
        code, stdout, stderr = self.in_terminal(("task", "decide", TASK, "--approve", "--by", "Test Owner",
                                                 "--reason", "Typo only"), TASK)
        self.assertEqual((code, stdout.strip()), (0, "approved"), stderr)
        self.assertIn("Short lane, covering only docs/**", stderr)
        self.assertIn("Short lane: change only docs/**", self.run_cli("task", "handoff", TASK).stdout)

        # The work, its checks, the result and the closing are the full path's.
        (self.project / "docs" / "guide.md").write_text("# Guide\n\nThe export page lists your reports.\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "Fix the typo in the guide")
        verified = self.run_cli("task", "verify", TASK).stdout
        self.assertIn("command:1: passed", verified)
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json").stdout)
        rules = [{"check": item["id"], "status": "not-applicable", "reason": "A typo in a guide.", "owner": "Test Owner"}
                 for item in checks if item["kind"] == "rule" and item["concerned"]]
        self.run_cli("task", "result", TASK, "--file", self.write_json(".openguildkit/work/result.json", {"checks": rules}))
        self.assertEqual(self.run_cli("task", "complete", TASK).stdout.strip().splitlines()[0], "done")
        self.assertIn("(short lane: docs/**)", self.run_cli("task", "list").stdout)

        # The exported record says the lane and the paths, and is the same bytes every time.
        exported = self.project / self.run_cli("task", "export", TASK).stdout.strip()
        data = json.loads(exported.read_text(encoding="utf-8"))
        self.assertEqual((data["lane"], data["paths"], data["status"], data["completed"]),
                         ("light", ["docs/**"], "done", True))
        self.assertEqual(data["files"], ["docs/guide.md"])
        first = exported.read_bytes()
        self.run_cli("task", "export", TASK)
        self.assertEqual(exported.read_bytes(), first)
        self.run_cli("check")

        # CI covers the change with that record, the lane read from the base revision.
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "The decision")
        result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json").stdout)
        self.assertEqual((result["ok"], result["decisions"], result["problems"]), (True, [TASK], []))

    def test_a_full_path_task_in_the_same_project_still_asks_its_questions(self):
        self.run_cli("task", "new", "Add a retry to the export job", "--id", "retry")
        self.assertIn("Answer the questionnaire", json.loads(self.run_cli("task", "list", "--json").stdout)[0]["next"])
        questions = json.loads(self.run_cli("task", "questions", "retry").stdout)["questions"]
        self.assertEqual([question["id"] for question in questions],
                         ["kind", "surface", "data", "research", "concerns", "context"])


if __name__ == "__main__":
    unittest.main()
