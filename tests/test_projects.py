"""openguildkit projects FOLDER...: several projects at a glance, read only, and a search across them (issue #435)."""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.shell import shell_word
from openguildkit.storage import write_json

from tests.support import copy_initialized_project, run_cli
from tests.test_trace import snapshot

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TASK = "request-status"
ALERT = "pypi:jinja2:ghsa-h5c8-rqwp-cp95"


class ProjectsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.code = Path(temporary.name) / "code"
        self.code.mkdir()
        self.portal = self.code / "portal"
        self.billing = self.code / "billing"
        profile = Path(temporary.name) / "profile.json"
        write_json(profile, {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), "checks": []})
        for root in (self.portal, self.billing):
            copy_initialized_project(self, profile, root)
        (self.code / "notes").mkdir()
        (self.code / "notes" / "todo.md").write_text("Nothing here.\n", encoding="utf-8")

    def projects(self, *arguments, code=0):
        result = run_cli(self.code, "projects", *arguments, expect=code)
        return result.stdout, result.stderr

    def closed_task(self, root: Path) -> None:
        """A task approved for a reason and closed with one rule failed, in the project at root."""
        run_cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        run_cli(root, "task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(run_cli(root, "task", "template", TASK).stdout)
        write_json(root / "review.json", {"consultation_id": template["consultation_id"],
                                          **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))})
        run_cli(root, "task", "review", TASK, "--file", root / "review.json")
        run_cli(root, "task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Ship the read-only view first",
                typed=TASK)
        run_cli(root, "task", "verify", TASK)
        checks = [{"check": item["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"}
                  for item in json.loads(run_cli(root, "task", "checks", TASK, "--json").stdout) if item["kind"] == "rule"]
        checks[0] = {"check": checks[0]["check"], "status": "failed", "evidence": "The linter reports errors."}
        write_json(root / "result.json", {"pull_request": "https://github.com/example/portal/pull/7", "checks": checks,
                                          "criteria": [{"criterion": "Users only see their own requests.",
                                                        "status": "met", "evidence": "tests/test_access.py"}]})
        run_cli(root, "task", "result", TASK, "--file", root / "result.json")
        run_cli(root, "task", "complete", TASK, "--by", "Camille", typed=TASK)
        self.failed_rule = checks[0]["check"]

    def test_a_folder_of_projects_gives_one_line_per_project_and_names_the_other_folders(self):
        out, _ = self.projects(self.code)
        lines = out.splitlines()
        portal = next(line for line in lines if line.startswith(f"{(self.code / 'portal').as_posix()}: "))
        self.assertIn("guard off", portal)
        self.assertIn("approvals not signed", portal)
        self.assertIn("no task", portal)
        self.assertIn("check passes", portal)
        self.assertTrue(any(line.startswith(f"{(self.code / 'billing').as_posix()}: ") for line in lines))
        self.assertIn(f"Not OpenGuildKit projects (1): {(self.code / 'notes').as_posix()}", out)

    def test_the_folders_a_shell_glob_names_are_listed_and_one_that_is_not_a_project_does_not_stop_the_others(self):
        out, _ = self.projects(self.portal, self.code / "notes", self.billing, self.code / "missing")
        self.assertIn(self.portal.as_posix(), out)
        self.assertIn(self.billing.as_posix(), out)
        self.assertIn(f"{(self.code / 'missing').as_posix()}: does not exist", out)
        self.assertIn("Not OpenGuildKit projects (1)", out)

    def test_an_unreadable_project_is_named_and_the_others_listed(self):
        (self.billing / ".openguildkit" / "project.json").write_text("{broken", encoding="utf-8")
        out, _ = self.projects(self.code)
        self.assertIn(f"{self.billing.as_posix()}: cannot be read: ", out)
        portal = next(line for line in out.splitlines() if line.startswith(f"{self.portal.as_posix()}: "))
        self.assertIn("check passes", portal)
        detail = json.loads(self.projects(self.code, "--json")[0])
        states = {Path(item["path"]).name: item["state"] for item in detail["projects"]}
        self.assertEqual(states, {"billing": "unreadable", "notes": "not-a-project", "portal": "project"})

    def test_tasks_by_status_open_points_critical_alerts_and_a_failing_check_are_counted(self):
        self.closed_task(self.portal)
        run_cli(self.portal, "alerts", "import", FIXTURES / "alerts" / "pip-audit.json")
        run_cli(self.portal, "alerts", "severity", ALERT, "--level", "critical", "--by", "CM", "--reason", "CVSS 9.1",
                typed=ALERT)
        run_cli(self.portal, "alerts", "set", ALERT, "--status", "confirmed", "--by", "CM")
        (self.billing / "AGENTS.md").write_text("Edited by hand.\n", encoding="utf-8")
        detail = json.loads(self.projects(self.code, "--json")[0])
        portal = next(item for item in detail["projects"] if item["path"] == self.portal.as_posix())
        self.assertEqual(portal["tasks"], {"done-with-reservations": 1})
        self.assertGreaterEqual(portal["open_points"], 1)
        self.assertEqual(portal["critical_alerts"], 1)
        billing = next(item for item in detail["projects"] if item["path"] == self.billing.as_posix())
        self.assertFalse(billing["check"]["passes"])
        out, _ = self.projects(self.code)
        self.assertIn("tasks 1 done-with-reservations", out)
        self.assertIn("1 critical alert confirmed", out)
        self.assertIn("check fails: ", out)
        self.assertIn(f"Next: openguildkit --project {shell_word(self.billing.as_posix())} check", out)

    def test_search_names_the_project_of_each_match_in_briefs_decision_reasons_and_rule_ids(self):
        self.closed_task(self.portal)
        out, _ = self.projects(self.code, "--search", "read-only view")
        self.assertIn(f"{self.portal.as_posix()}: {TASK} decision reason: Ship the read-only view first", out)
        out, _ = self.projects(self.code, "--search", "SIGNED-IN USERS")
        self.assertIn(f"{self.portal.as_posix()}: {TASK} brief: ", out)
        out, _ = self.projects(self.code, "--search", self.failed_rule)
        self.assertIn(f"{self.portal.as_posix()}: {TASK} rule: {self.failed_rule} (failed)", out)
        detail = json.loads(self.projects(self.code, "--search", "nothing matches this", "--json")[0])
        self.assertEqual(detail["matches"], [])
        self.assertIn("No task matches", self.projects(self.code, "--search", "nothing matches this")[0])

    def test_projects_reads_and_writes_nothing(self):
        self.closed_task(self.portal)
        (self.billing / ".openguildkit" / "project.json").write_text("{broken", encoding="utf-8")
        before = snapshot(self.code)
        self.projects(self.code)
        self.projects(self.code, "--json")
        self.projects(self.code, "--search", "read-only")
        self.assertEqual(snapshot(self.code), before)


    def test_the_web_interface_refuses_a_folder_outside_its_project(self):
        from openguildkit.cli import command_parser
        from openguildkit.webui import Refused, check_paths

        args = command_parser().parse_args(["projects", str(self.billing)])
        with self.assertRaises(Refused) as refused:
            check_paths(args, self.portal.resolve(), set())
        self.assertEqual(refused.exception.reason, "outside-project")
        check_paths(command_parser().parse_args(["projects"]), Path.cwd().resolve(), set())


if __name__ == "__main__":
    unittest.main()
