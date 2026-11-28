"""openguildkit projects FOLDER...: several projects at a glance, read only, and a search across them (issue #435)."""

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.shell import shell_word
from openguildkit.storage import write_json
from tests.support import copy_initialized_project, run_cli
from tests.test_org_catalog import git, pack, write_record
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

    def unequipped(self) -> Path:
        """A folder without a profile where agents already work: Cursor rules and two MCP servers, one pinned."""
        folder = self.code / "scratch"
        folder.mkdir()
        (folder / ".cursorrules").write_text("Be careful.\n", encoding="utf-8")
        write_json(folder / ".mcp.json", {"mcpServers": {
            "docs": {"command": "npx", "args": ["-y", "docs-mcp@1.2.3"]},
            "search": {"command": "npx", "args": ["-y", "search-mcp"]}}})
        return folder

    def policy(self, **fields) -> Path:
        path = self.code.parent / "policy.json"
        write_json(path, fields)
        return path

    def row(self, folder: Path, *arguments) -> dict:
        detail = json.loads(self.projects(self.code, *arguments, "--json")[0])
        return next(item for item in detail["projects"] if item["path"] == folder.as_posix())

    def test_surfaces_list_the_agent_tools_and_mcp_servers_host_scan_finds_in_a_folder_without_a_profile(self):
        """Issue #479: a folder without a profile ended in 'Not OpenGuildKit projects' though agents work in it."""
        folder = self.unequipped()
        scan = json.loads(run_cli(folder, "host", "scan", "--json").stdout)
        row = self.row(folder, "--surfaces")
        self.assertEqual(row["state"], "not-a-project")
        self.assertEqual(row["tools"], [item["id"] for item in scan["surfaces"]])
        self.assertEqual(row["tools"], ["claude-code", "cursor"])
        self.assertEqual(row["mcp_servers"], len(scan["mcp_servers"]))
        self.assertEqual(row["mcp_unpinned"], sum(item["pinned"] is False for item in scan["mcp_servers"]))
        self.assertEqual((row["mcp_servers"], row["mcp_unpinned"]), (2, 1))
        out = self.projects(self.code, "--surfaces")[0]
        self.assertIn(f"{folder.as_posix()}: not an OpenGuildKit project; agents at work: claude-code, cursor; "
                      "2 MCP servers (1 not pinned", out)
        self.assertIn(f"Not OpenGuildKit projects (1): {(self.code / 'notes').as_posix()}", out)
        portal = self.row(self.portal, "--surfaces")
        self.assertEqual((portal["host"], portal["hooks"], portal["tools"]), ("other", None, ["claude-code"]))
        self.assertRegex(portal["lock"], r"^openguildkit ")
        self.assertIsNone(portal["last_decision"])
        self.assertNotIn("tools", self.row(self.portal))
        for setting in (("host", "claude-code"), ("guard", "observe")):
            run_cli(self.billing, "profile", "set", *setting, "--by", "CM", "--reason", "Pilot")
        billing = self.row(self.billing, "--surfaces")
        self.assertEqual((billing["host"], billing["hooks"]), ("claude-code", "missing"))
        self.assertIn("host claude-code, hooks missing; agent tools claude-code", self.projects(self.code, "--surfaces")[0])

    def test_surfaces_give_the_day_of_the_last_decision_and_the_commit_of_the_organization_catalog(self):
        self.closed_task(self.portal)
        org = self.code.parent / "org"
        org.mkdir()
        git(org, "init", "-q", "-b", "main")
        write_record(org, "packs", pack("org-review"))
        git(org, "add", "-A")
        git(org, "commit", "-q", "-m", "First edition")
        commit = git(org, "rev-parse", "HEAD")
        run_cli(self.billing, "org-catalog", "set", "--repo", org, "--commit", commit, "--by", "CM", "--reason", "Pilot",
                typed=commit[:12])
        portal, billing = self.row(self.portal, "--surfaces"), self.row(self.billing, "--surfaces")
        self.assertRegex(portal["last_decision"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIsNone(portal["catalog_commit"])
        self.assertEqual((billing["catalog_commit"], billing["last_decision"]), (commit, None))
        self.assertIn(f"organization catalog {commit[:12]}", self.projects(self.code, "--surfaces")[0])

    def test_csv_prints_a_stable_header_and_one_line_per_folder(self):
        """Issue #479: the fleet could be read as text or JSON only, never as a table."""
        # OGK-PROJECT-041
        self.unequipped()
        out = self.projects(self.code, "--surfaces", "--format", "csv")[0]
        lines = out.splitlines()
        self.assertEqual(lines[0], "path,state,name,guard,approvals,tasks,attention,open_points,critical_alerts,check,"
                                   "host,hooks,lock,catalog_commit,last_decision,tools,mcp_servers,mcp_unpinned,"
                                   "mcp_unlisted,permissive,drift")
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual({Path(item["path"]).name: item["state"] for item in rows},
                         {"billing": "project", "notes": "not-a-project", "portal": "project", "scratch": "not-a-project"})
        scratch = next(item for item in rows if item["path"].endswith("scratch"))
        self.assertEqual((scratch["tools"], scratch["mcp_servers"], scratch["mcp_unpinned"]), ("claude-code;cursor", "2", "1"))
        portal = next(item for item in rows if item["path"].endswith("portal"))
        self.assertEqual((portal["guard"], portal["check"], portal["host"], portal["drift"]),
                         ("off", "passes", "other", ""))
        plain = next(csv.DictReader(io.StringIO(self.projects(self.code, "--format", "csv")[0])))
        self.assertEqual(plain["host"], "")  # not asked: empty, where 0 would say that nothing was found
        self.projects(self.code, "--format", "csv", "--json", code=1)
        self.projects(self.code, "--format", "csv", "--search", "x", code=1)

    def test_csv_keeps_a_cell_that_starts_like_a_formula_from_running_in_a_spreadsheet(self):
        """Issue #479: a project name is typed by whoever owns the repository, and a spreadsheet runs '=...'."""
        path = self.portal / ".openguildkit" / "project.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({**profile, "name": '=HYPERLINK("http://example.test","x")'}), encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(self.projects(self.code, "--format", "csv")[0])))
        portal = next(item for item in rows if item["path"].endswith("portal"))
        self.assertEqual(portal["name"], '\'=HYPERLINK("http://example.test","x")')

    def test_a_project_below_the_policy_carries_the_gap_and_strict_ends_in_1(self):
        """Issue #479: nothing compared a project with a target, so there was no drift to see."""
        run_cli(self.billing, "profile", "set", "guard", "observe", "--by", "CM", "--reason", "Pilot")
        policy = self.policy(guard="enforce")
        for name in ("portal", "billing"):
            row = self.row(self.code / name, "--policy", policy)
            self.assertEqual([item["field"] for item in row["drift"]], ["guard"])
        self.assertEqual(self.row(self.billing, "--policy", policy)["drift"],
                         [{"field": "guard", "policy": "enforce", "found": "observe"}])
        out, _ = self.projects(self.code, "--policy", policy)
        self.assertIn("policy gap: guard observe, the policy asks for enforce", out)
        self.projects(self.code, "--policy", policy, "--strict", code=1)
        self.projects(self.code, "--policy", self.policy(guard="off"), "--strict")
        self.assertEqual(self.row(self.billing, "--policy", self.policy(guard="observe"))["drift"], [])
        self.assertNotIn("drift", self.row(self.billing))

    def test_the_policy_names_each_gap_and_an_unequipped_folder_where_agents_work_is_one(self):
        self.unequipped()
        policy = self.policy(guard="observe", approvals="signed", separate_requester=True)
        portal = self.row(self.portal, "--policy", policy)
        self.assertEqual([item["field"] for item in portal["drift"]], ["guard", "approvals", "separate_requester"])
        scratch = self.row(self.code / "scratch", "--policy", policy)
        self.assertEqual(scratch["drift"], [{"field": "project", "policy": "equipped", "found": "not-a-project"}])
        self.assertEqual(self.row(self.code / "notes", "--policy", policy)["drift"], [])
        self.assertEqual(scratch["tools"], ["claude-code", "cursor"])  # a policy reads the surfaces too
        (self.billing / ".openguildkit" / "project.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.row(self.billing, "--policy", policy)["drift"],
                         [{"field": "project", "policy": "readable", "found": "unreadable"}])

    def test_a_policy_that_cannot_be_read_or_names_a_field_it_does_not_know_stops_the_command(self):
        # OGK-PROJECT-040, OGK-PROJECT-042, OGK-PROJECT-043, OGK-PROJECT-044
        _, err = self.projects(self.code, "--policy", self.policy(guards="enforce"), code=1)
        self.assertIn("guards", err)
        self.assertIn("guard, approvals, separate_requester", err)
        _, err = self.projects(self.code, "--policy", self.policy(guard="strict"), code=1)
        self.assertIn("off, observe or enforce", err)
        _, err = self.projects(self.code, "--policy", self.code / "nothing.json", code=1)
        self.assertIn("nothing.json", err)
        _, err = self.projects(self.code, "--strict", code=1)
        self.assertIn("--policy", err)

    def test_surfaces_policy_and_csv_read_and_write_nothing(self):
        self.closed_task(self.portal)
        self.unequipped()
        policy = self.policy(guard="enforce")
        before = snapshot(self.code)
        for arguments in (("--surfaces",), ("--surfaces", "--format", "csv"), ("--policy", policy, "--format", "csv"),
                          ("--policy", policy, "--strict", "--json")):
            self.projects(self.code, *arguments, code=1 if "--strict" in arguments else 0)
        self.assertEqual(snapshot(self.code), before)

    def test_the_root_parser_takes_no_abbreviation_so_policy_is_not_read_as_policy_repo(self):
        """Issue #479: Python 3.11 refused `projects --policy FILE` as an ambiguous prefix of --policy-repo."""
        from openguildkit.cli import command_parser

        self.assertFalse(command_parser().allow_abbrev)
        args = command_parser().parse_args(["projects", "--policy", "policy.json"])
        self.assertEqual(args.policy, Path("policy.json"))

    def test_the_web_interface_refuses_a_folder_outside_its_project(self):
        from openguildkit.cli import command_parser
        from openguildkit.web_requests import Refused, check_paths

        args = command_parser().parse_args(["projects", str(self.billing)])
        with self.assertRaises(Refused) as refused:
            check_paths(args, self.portal.resolve(), set())
        self.assertEqual(refused.exception.reason, "outside-project")
        check_paths(command_parser().parse_args(["projects"]), Path.cwd().resolve(), set())
        args = command_parser().parse_args(["projects", "--policy", str(self.code.parent / "policy.json")])
        with self.assertRaises(Refused):
            check_paths(args, self.portal.resolve(), set())


if __name__ == "__main__":
    unittest.main()
