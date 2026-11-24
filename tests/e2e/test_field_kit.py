"""The field campaign kit: thirty testers, their briefs, the scripted scenarios and the collection of reports."""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import openguildkit_on_path, run_cli

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "examples" / "field-tests"
EXAMPLE = ROOT / "examples" / "request-status"
POSIX_ONLY = "the campaign's stand-in for the person types at a pseudo-terminal, available on Linux and macOS"
_ADDRESS = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")


def load(name: str):
    """Import a script of the kit, which lives outside the package."""
    if str(KIT) not in sys.path:
        sys.path.insert(0, str(KIT))
    spec = importlib.util.spec_from_file_location(f"field_kit_{name}", KIT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


field = load("field")


class KitTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name).resolve()
        # Testers install the CLI with pipx or uv: its hooks find it on the PATH, which host apply requires. The kit
        # copies os.environ for each command (field_cli.environment), so it sees this PATH.
        openguildkit_on_path(self)


class CampaignTests(KitTestCase):
    def test_an_installed_campaign_keeps_its_interpreter_and_ignores_the_checkout(self):
        cli = load("field_cli")
        with mock.patch.dict(os.environ, {cli.INSTALLED_ENV: "1", "PYTHONPATH": str(ROOT / "src")}):
            self.assertEqual(cli.command("--version"), [sys.executable, "-I", "-X", "utf8", "-m", "openguildkit", "--version"])
            self.assertNotIn("PYTHONPATH", cli.environment())
            for name in ("logged.py", "person_decide.py", "person_act.py", "fingerprint.py"):
                launcher = self.out / name
                field._wrapper(launcher, name)
                self.assertIn(f"{cli.INSTALLED_ENV}=1 exec ", launcher.read_text(encoding="utf-8"))

    def test_the_campaign_has_thirty_testers_in_three_groups_and_no_problem(self):
        campaign = field.load_campaign()
        testers = field.testers(campaign)
        groups = [tester["group"] for tester in testers]
        self.assertEqual((len(testers), groups.count("persona"), groups.count("scenario"), groups.count("teammate")),
                         (30, 18, 9, 3))
        self.assertEqual(len({tester["id"] for tester in testers}), 30)
        self.assertEqual(field.campaign_problems(campaign), [])

    def test_a_broken_campaign_file_is_named_before_a_campaign_starts(self):
        campaign = field.load_campaign()
        campaign["personas"][0]["task"] = " "
        campaign["personas"][1]["id"] = campaign["personas"][2]["id"]
        campaign["scenarios"][0]["teams"] = 1
        problems = field.campaign_problems(campaign)
        self.assertIn(f"Persona {campaign['personas'][0]['id']} lacks: task", problems)
        self.assertIn(f"Tester ID used twice: {campaign['personas'][2]['id']}", problems)
        self.assertIn("Scenario s1 needs at least two teams to compare", problems)

    def test_every_address_in_the_kit_is_an_example_address(self):
        real = []
        for path in sorted(KIT.rglob("*")):
            if path.is_file() and path.suffix in (".json", ".md", ".py", ".js", ".ts", ".toml"):
                for domain in _ADDRESS.findall(path.read_text(encoding="utf-8")):
                    if not domain.endswith("example.test"):
                        real.append(f"{path.relative_to(KIT).as_posix()}: {domain}")
        self.assertEqual(real, [])

    def test_a_brief_gives_the_rules_the_workspace_and_the_scenario_with_nothing_left_to_fill(self):
        for tester in field.testers(field.load_campaign()):
            with self.subTest(tester=tester["id"]):
                text = field.brief(tester["id"], self.out)
                self.assertIn("# Field test: how to work", text)
                self.assertIn(f"{self.out.as_posix()}/runs/{tester['id']}/", text)
                self.assertIn(f"export PATH={self.out.as_posix()}/bin:$PATH", text)
                self.assertNotRegex(text, r"\{(out|repo|kit)\}")
        self.assertIn("person-decide", field.brief("s1-team1", self.out))
        self.assertIn("person-act --project DIR task clear", field.brief("s1-team1", self.out))
        self.assertIn((self.out / "shared" / "remote.git").as_posix(), field.brief("mate-ada", self.out))
        with self.assertRaisesRegex(ValueError, "Unknown tester: nobody"):
            field.brief("nobody", self.out)


class CollectTests(KitTestCase):
    FINDING = {"title": "A message points to the wrong step", "severity": "major", "kind": "confusing",
               "command": "openguildkit check", "observed": "It says to run init.", "expected": "It says to run sync."}

    def write_reports(self):
        """What a complete campaign leaves: a report and findings per tester, a fingerprint per scenario team."""
        for tester in field.testers(field.load_campaign()):
            workspace = self.out / "runs" / tester["id"]
            workspace.mkdir(parents=True)
            (workspace / "REPORT.md").write_text("# Report\n\nSteps and findings.\n", encoding="utf-8")
            findings = {"outcome": "completed", "summary": "Went through.", "commands_run": 60,
                        "findings": [self.FINDING], "worked_well": ["Refusals say what to do next."]}
            (workspace / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
            (workspace / "commands.log").write_text(
                "$ openguildkit task decide x  (in project)\napproved\n[exit 0]\n\n"
                "$ openguildkit task handoff x  (in project)\n# Approved task handoff\n[exit 0]\n\n", encoding="utf-8")
            if tester["group"] == "scenario":
                (workspace / "fingerprint.json").write_text(json.dumps({"route": ["security"], "rule plan": "abc"}),
                                                            encoding="utf-8")

    def test_a_complete_campaign_is_summarised_and_its_findings_merged(self):
        self.write_reports()
        summary, problems = field.collect(self.out)
        self.assertEqual(problems, [])
        self.assertEqual((len(summary["testers"]), summary["findings"]), (30, 30))
        self.assertEqual(summary["scenarios"]["s1"], {"teams": 3, "differing": []})
        merged = json.loads((self.out / "results" / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(merged[0]["ref"], f"{summary['testers'][0]['id']}#1")
        text = (self.out / "results" / "summary.md").read_text(encoding="utf-8")
        self.assertIn("- s1: 3 team(s) compared, identical.", text)
        self.assertIn("Nothing: every tester reported and no scenario diverged.", text)

    def test_a_tester_without_a_report_or_with_unusable_findings_is_named(self):
        self.write_reports()
        (self.out / "runs" / "fintech" / "REPORT.md").unlink()
        (self.out / "runs" / "agency" / "findings.json").write_text(
            json.dumps({"outcome": "completed", "findings": [{**self.FINDING, "severity": "huge"}]}), encoding="utf-8")
        (self.out / "runs" / "oss" / "findings.json").write_text("{not json", encoding="utf-8")
        summary, problems = field.collect(self.out)
        self.assertIn("fintech: no REPORT.md", problems)
        self.assertIn("agency: finding 1 has an unknown severity or kind", problems)
        self.assertTrue(any(problem.startswith("oss: findings.json is not valid JSON") for problem in problems), problems)
        self.assertIn("| fintech | persona | MISSING |", (self.out / "results" / "summary.md").read_text(encoding="utf-8"))

    def test_a_tester_whose_transcript_stops_before_the_handoff_is_named(self):
        self.write_reports()
        (self.out / "runs" / "fintech" / "commands.log").unlink()
        (self.out / "runs" / "agency" / "commands.log").write_text(
            "$ openguildkit task consult x --answers a.json  (in project)\n[exit 0]\n\n"
            "$ openguildkit task show x  (in project)\nhandoff is next\n[exit 0]\n\n", encoding="utf-8")
        (self.out / "runs" / "oss" / "commands.log").write_text(
            "$ openguildkit --project p task complete x  (in .)\ndone\n[exit 0]\n\n", encoding="utf-8")
        summary, problems = field.collect(self.out)
        self.assertIn("fintech: no commands.log, the transcript of its openguildkit commands", problems)
        self.assertIn("agency: commands.log stops before task handoff (last: openguildkit task show x)", problems)
        self.assertFalse(any(problem.startswith("oss:") for problem in problems), problems)
        rows = {row["id"]: row for row in summary["testers"]}
        self.assertEqual((rows["fintech"]["log"], rows["agency"]["log"], rows["oss"]["log"]),
                         ("missing", "before handoff", "handoff or later"))

    def test_open_issues_files_one_issue_per_draft_and_only_when_asked(self):
        self.write_reports()
        (self.out / "runs" / "s2-team3" / "fingerprint.json").write_text(
            json.dumps({"route": ["security", "legal"], "rule plan": "abc"}), encoding="utf-8")
        calls = []

        def gh(command, **options):
            calls.append((command, options))
            return subprocess.CompletedProcess(command, 0, "https://github.example.test/o/r/issues/7\n", "")

        with mock.patch.object(field.subprocess, "run", side_effect=gh):
            field.collect(self.out)
            self.assertEqual(calls, [])
            summary, problems = field.collect(self.out, open_issues=True)
        self.assertEqual(len(calls), 1)
        command, options = calls[0]
        self.assertEqual(command[:4], ["gh", "issue", "create", "--title"])
        self.assertEqual(command[4], "Scenario s2: teams with the same inputs got different results")
        self.assertEqual(command[command.index("--label") + 1:][:3], ["bug", "--label", "field-test"])
        body = Path(command[command.index("--body-file") + 1]).read_text(encoding="utf-8")
        self.assertTrue(body.startswith("## What differs"), body)
        self.assertEqual(options["cwd"], field.REPO)
        self.assertEqual(summary["issues"], ["https://github.example.test/o/r/issues/7"])
        with mock.patch.object(field.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1, "", "gh: not logged in")):
            _, problems = field.collect(self.out, open_issues=True)
        self.assertIn("s2: gh issue create failed: gh: not logged in", problems)

    def test_teams_that_diverge_on_a_scenario_get_an_issue_draft(self):
        self.write_reports()
        (self.out / "runs" / "s2-team3" / "fingerprint.json").write_text(
            json.dumps({"route": ["security", "legal"], "rule plan": "abc"}), encoding="utf-8")
        (self.out / "runs" / "s3-team1" / "fingerprint.json").unlink()
        summary, problems = field.collect(self.out)
        draft = self.out / "results" / "divergence-s2.md"
        self.assertIn(f"s2: 1 key(s) differ between teams; issue draft in {draft.as_posix()}", problems)
        self.assertIn("s3-team1: no readable fingerprint.json", problems)
        self.assertEqual(summary["scenarios"]["s2"]["differing"], ["route"])
        self.assertEqual(summary["scenarios"]["s3"], {"teams": 2, "differing": []})
        text = draft.read_text(encoding="utf-8")
        self.assertIn("title: Scenario s2: teams with the same inputs got different results", text)
        self.assertIn('s2-team3 = ["security", "legal"]', text)
        self.assertFalse((self.out / "results" / "divergence-s1.md").exists())


@unittest.skipUnless(os.name == "posix", POSIX_ONLY)
class PrepareTests(KitTestCase):
    def test_prepare_creates_every_folder_the_commands_and_the_shared_repository(self):
        record = field.prepare(self.out)
        self.assertEqual(len(record["testers"]), 30)
        for name in record["testers"]:
            self.assertTrue((self.out / "runs" / name).is_dir(), name)
        self.assertTrue(os.access(self.out / "bin" / "person-act", os.X_OK))
        version = subprocess.run([str(self.out / "bin" / "openguildkit"), "--version"], capture_output=True, text=True)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertTrue(version.stdout.startswith("openguildkit "), version.stdout)
        self.assertEqual(record["cli_version"], version.stdout.strip())
        remote = self.out / "shared" / "remote.git"
        tracked = field.git(remote, "ls-tree", "-r", "--name-only", "main").splitlines()
        self.assertIn(".openguildkit/project.json", tracked)
        self.assertIn("AGENTS.md", tracked)
        self.assertNotIn("team-answers.json", tracked)
        self.assertEqual(json.loads((self.out / "campaign.json").read_text(encoding="utf-8"))["testers"], record["testers"])
        workspace = self.out / "runs" / "fintech"
        (workspace / "project").mkdir()
        for folder, arguments in ((workspace / "project", ["--version"]),
                                  (self.out, ["--project", str(workspace / "project"), "task", "list"])):
            run = subprocess.run([str(self.out / "bin" / "openguildkit"), *arguments], cwd=folder,
                                 capture_output=True, text=True)
            self.assertIn(run.returncode, (0, 1), run.stderr)
        log = (workspace / "commands.log").read_text(encoding="utf-8")
        self.assertIn("$ openguildkit --version  (in project)\nopenguildkit ", log)
        self.assertIn("[exit 0]", log)
        self.assertIn(f"$ openguildkit --project {(workspace / 'project').as_posix()} task list", log)
        self.assertFalse((self.out / "runs" / "agency" / "commands.log").exists())
        field.prepare(self.out)  # running it again keeps the shared repository
        self.assertEqual(field.git(remote, "rev-list", "--count", "main"), "1")

    def test_prepare_and_cohorts_work_from_a_checkout_where_openguildkit_is_not_installed(self):
        # A maintainer runs the kit from a clean checkout: host apply needs the command on the PATH for its hooks.
        bare = os.pathsep.join(folder for folder in ("/usr/bin", "/bin") if Path(folder).is_dir())
        with mock.patch.dict(os.environ, {"PATH": bare}):
            record = field.prepare(self.out)
            self.assertEqual(os.environ["PATH"], bare)
            with mock.patch.object(field.fingerprint_script, "run", run_here):
                result = field.cohorts(self.out, teams=2)
        self.assertEqual(len(record["testers"]), 30)
        self.assertTrue((self.out / "shared" / "remote.git").is_dir())
        self.assertEqual({scenario: data["differing"] for scenario, data in result.items()},
                         {"s1": {}, "s2": {}, "s3": {}})


def run_here(root: Path, *arguments) -> tuple[int, str, str]:
    """The kit's run(), with the CLI in this process."""
    result = run_cli(root, *arguments, stdin="", expect=None)
    return result.returncode, result.stdout, result.stderr


@unittest.skipUnless(os.name == "posix", POSIX_ONLY)
class SameScenarioTests(KitTestCase):
    def test_two_teams_that_play_the_same_scenario_get_the_same_results(self):
        # The kit starts a process per command; here the commands run in this process, as the rest of the suite.
        with mock.patch.object(field.fingerprint_script, "run", run_here):
            result = field.cohorts(self.out, teams=2)
        self.assertEqual(sorted(result), ["s1", "s2", "s3"])
        for scenario, data in result.items():
            with self.subTest(scenario=scenario):
                self.assertEqual(data["differing"], {})
                self.assertGreaterEqual(data["keys"], 10)

    def test_a_difference_between_two_teams_is_reported_key_by_key(self):
        differing = field.differing_keys({"team1": {"route": ["qa"], "rule plan": "a"},
                                          "team2": {"route": ["qa", "legal"], "rule plan": "a"}})
        self.assertEqual(differing, {"route": {"team1": '["qa"]', "team2": '["qa", "legal"]'}})


@unittest.skipUnless(os.name == "posix", POSIX_ONLY)
class PersonDecideTests(KitTestCase):
    def test_the_stand_in_types_the_decision_at_a_terminal_as_the_person_would(self):
        project = self.out / "project"
        project.mkdir()
        field.cli(project, "init", "--answers", EXAMPLE / "profile.json")
        field.cli(project, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")
        field.cli(project, "task", "consult", "request-status", "--answers", EXAMPLE / "answers.json")
        template = json.loads(field.cli(project, "task", "template", "request-status").stdout)
        review = {"consultation_id": template["consultation_id"],
                  **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        (self.out / "review.json").write_text(json.dumps(review), encoding="utf-8")
        field.cli(project, "task", "review", "request-status", "--file", self.out / "review.json")
        refused = field.cli(project, "task", "decide", "request-status", "--approve", "--by", "Camille Martin",
                            "--reason", "Agreed", check=False)
        self.assertEqual(refused.returncode, 1, "without a terminal the approval is refused")

        code, shown = load("person_decide").decide(project, "request-status", "approve", "Camille Martin", "Agreed", [])
        self.assertEqual(code, 0, shown)
        self.assertIn("request-status", shown)
        self.assertEqual(json.loads(field.cli(project, "task", "show", "request-status").stdout)["status"], "approved")

    def test_the_person_clears_a_condition_of_approval_through_its_own_stand_in(self):
        project = self.out / "project"
        project.mkdir()
        field.cli(project, "init", "--answers", EXAMPLE / "profile.json")
        field.cli(project, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")
        field.cli(project, "task", "consult", "request-status", "--answers", EXAMPLE / "answers.json")
        template = json.loads(field.cli(project, "task", "template", "request-status").stdout)
        review = {"consultation_id": template["consultation_id"],
                  **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        qa = next(entry for entry in review["boards"] if entry["id"] == "qa")
        qa["challenge"]["blockers"] = [{"finding": "No regression test yet", "owner": "Camille Martin",
                                        "clears_when": "the regression test passes", "phase": "verification"}]
        (self.out / "review.json").write_text(json.dumps(review), encoding="utf-8")
        field.cli(project, "task", "review", "request-status", "--file", self.out / "review.json")
        code, shown = load("person_decide").decide(project, "request-status", "approve", "Camille Martin", "Agreed", [])
        self.assertEqual(code, 0, shown)
        (project / "test_status.py").write_text("# regression test\n", encoding="utf-8")
        clear = ["task", "clear", "request-status", "qa:1", "--by", "Camille Martin", "--evidence", "test_status.py",
                 "--supports", "The regression test passes"]
        refused = field.cli(project, *clear, check=False)
        self.assertEqual(refused.returncode, 1, "without a terminal the clearance is refused")
        act = load("person_act").act
        with self.assertRaisesRegex(ValueError, "person-decide"):
            act(project, ["task", "decide", "request-status", "--approve"], [])
        code, shown = act(project, clear, [])
        self.assertEqual(code, 0, shown)
        self.assertIn("Type request-status to clear qa:1", shown)
        self.assertIn("cleared", shown)
        self.assertIn("qa:1 [cleared", field.cli(project, "task", "blockers", "request-status").stdout)

    def test_the_stand_in_passes_a_signature_on_and_never_half_of_one(self):
        decide = load("person_decide").decide
        with self.assertRaisesRegex(ValueError, "both --signature and --signer"):
            decide(self.out, "request-status", "approve", "Camille Martin", "Agreed", [], Path("decision.sig"), None)
        project = self.out / "project"
        project.mkdir()
        field.cli(project, "init", "--answers", EXAMPLE / "profile.json")
        field.cli(project, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")
        code, shown = decide(project, "request-status", "approve", "Camille Martin", "Agreed", [],
                             self.out / "decision.sig", "camille@example.test")
        self.assertEqual(code, 1)
        self.assertNotIn("unrecognized arguments", shown)
        self.assertIn("OpenGuildKit:", shown)


if __name__ == "__main__":
    unittest.main()
