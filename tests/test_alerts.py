import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.alerts import (
    accept_alert, blocking_alerts, find_alert, import_report, link_alert, load_register, migrate_task, parse_report,
    set_status, summary, task_alerts,
)
from openguildkit.storage import write_json

from tests.support import CapturedCli

FIXTURES = Path(__file__).with_name("fixtures") / "alerts"
REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
WATCH_TEMPLATE = REPO / "integrations" / "github" / "openguildkit-dependency-watch.yml"
JINJA = "pypi:jinja2:ghsa-h5c8-rqwp-cp95"
CRITICAL = "npm:form-parser:ghsa-xxxx-yyyy-zzzz"


def empty():
    return {"schema_version": 1, "alerts": [], "imports": []}


def imported(*names, task_id=None, register=None):
    register = register or empty()
    for name in names:
        register, _ = import_report(register, FIXTURES / name, task_id, today="2026-11-21")
    return register


class AlertTests(unittest.TestCase):
    def test_each_scanner_report_is_normalized(self):
        tool, alerts = parse_report((FIXTURES / "npm-audit.json").read_bytes(), "npm")
        self.assertEqual(tool, "npm audit")
        self.assertEqual(alerts[0]["advisory"], "GHSA-C2QF-RXJJ-QQGW")
        self.assertEqual(alerts[0]["fix"], "semver 5.7.2")
        tool, alerts = parse_report((FIXTURES / "pip-audit.json").read_bytes(), "pip")
        self.assertEqual((tool, alerts[0]["package"], alerts[0]["version"], alerts[0]["fix"]), ("pip-audit", "jinja2", "3.1.2", "3.1.3"))
        self.assertEqual(alerts[0]["aliases"], ["CVE-2024-22195", "GHSA-H5C8-RQWP-CP95"])
        self.assertEqual(len(alerts), 1)
        tool, alerts = parse_report((FIXTURES / "osv-scanner.json").read_bytes(), "osv")
        self.assertEqual((alerts[0]["ecosystem"], alerts[0]["severity"]), ("go", "moderate"))
        dependabot = [{"state": "open", "html_url": "https://github.com/o/r/security/dependabot/1",
                       "dependency": {"package": {"ecosystem": "npm", "name": "lodash"}},
                       "security_advisory": {"ghsa_id": "GHSA-35jh-r3h4-6jhm", "summary": "Command injection", "severity": "high"},
                       "security_vulnerability": {"vulnerable_version_range": "< 4.17.21", "first_patched_version": {"identifier": "4.17.21"}}}]
        tool, alerts = parse_report(json.dumps(dependabot).encode(), "gh")
        self.assertEqual((tool, alerts[0]["fix"]), ("GitHub Dependabot", "4.17.21"))
        with self.assertRaisesRegex(ValueError, "is not an npm audit"):
            parse_report(b'{"hello": 1}', "x")

    def test_every_page_of_a_paginated_dependabot_export_is_read(self):
        page = json.loads((FIXTURES / "dependabot-jinja2.json").read_text(encoding="utf-8"))
        second = [{**page[0], "number": 5, "dependency": {"package": {"ecosystem": "npm", "name": "lodash"}},
                   "security_advisory": {"ghsa_id": "GHSA-35jh-r3h4-6jhm", "summary": "x", "severity": "high"}}]
        for content in (json.dumps(page) + json.dumps(second), json.dumps([page, second]), json.dumps(page) + "\n" + json.dumps([])):
            tool, alerts = parse_report(content.encode(), "dependabot.json")
            self.assertEqual(tool, "GitHub Dependabot")
            self.assertIn(JINJA, {alert["id"] for alert in alerts})
        self.assertEqual(len(parse_report((json.dumps(page) + json.dumps(second)).encode(), "d")[1]), 2)
        with self.assertRaisesRegex(ValueError, "several JSON documents"):
            parse_report(b'{"results": []}{"results": []}', "x")

    def test_a_clean_report_of_the_same_scanner_resolves_the_alerts_it_no_longer_lists(self):
        register = imported("npm-audit.json", task_id="upgrade")
        self.assertEqual([alert["status"] for alert in register["alerts"]], ["open"])
        register, changes = import_report(register, FIXTURES / "npm-audit-clean.json", today="2026-11-22")
        self.assertEqual(changes["resolved"], ["npm:semver:ghsa-c2qf-rxjj-qqgw"])
        alert = register["alerts"][0]
        self.assertEqual((alert["status"], alert["resolved_on"]), ("resolved", "2026-11-22"))
        self.assertEqual(task_alerts(register, {"id": "upgrade"}), [])
        register, changes = import_report(register, FIXTURES / "npm-audit.json", today="2026-11-23")
        self.assertEqual((changes["reopened"], register["alerts"][0]["status"]), (["npm:semver:ghsa-c2qf-rxjj-qqgw"], "open"))

    def test_another_scanner_report_does_not_resolve_alerts_it_never_listed(self):
        register = imported("npm-audit.json", "osv-scanner.json")
        self.assertEqual(summary(register["alerts"], [])["by_status"]["open"], 2)

    def test_pip_audit_osv_and_dependabot_reports_of_one_advisory_give_one_entry(self):
        register = imported("pip-audit.json", "osv-jinja2.json", "dependabot-jinja2.json")
        self.assertEqual([alert["id"] for alert in register["alerts"]], [JINJA])
        alert = register["alerts"][0]
        self.assertEqual(alert["scanners"], ["GitHub Dependabot", "OSV-Scanner", "pip-audit"])
        self.assertEqual(alert["aliases"], ["CVE-2024-22195", "GHSA-H5C8-RQWP-CP95", "PYSEC-2024-1"])
        self.assertEqual(alert["severity"], "moderate")
        register = set_status(register, "pypi:jinja2:pysec-2024-1", "dismissed", "Alex", "Templates never render user input.")
        self.assertEqual(register["alerts"][0]["status"], "dismissed")
        register = imported("dependabot-jinja2.json", register=register)
        self.assertEqual([(alert["id"], alert["status"]) for alert in register["alerts"]], [(JINJA, "dismissed")])

    def test_an_alert_still_listed_by_another_scanner_stays_open(self):
        register = imported("pip-audit.json", "dependabot-jinja2.json")
        register, changes = import_report(register, FIXTURES / "pip-audit-clean.json", today="2026-11-22")
        self.assertEqual(changes["resolved"], [])
        self.assertEqual((register["alerts"][0]["status"], register["alerts"][0]["scanners"]), ("open", ["GitHub Dependabot"]))
        # The alert is listed as fixed in GitHub: an export of every state shows what was analyzed.
        register, changes = import_report(register, FIXTURES / "dependabot-fixed.json", today="2026-11-22")
        self.assertEqual(changes["resolved"], [JINJA])

    def test_reviews_need_a_name_and_a_reason_to_dismiss(self):
        register = imported("pip-audit.json")
        with self.assertRaisesRegex(ValueError, "reason"):
            set_status(register, JINJA, "dismissed", "Alex", "")
        with self.assertRaisesRegex(ValueError, "--by"):
            set_status(register, JINJA, "confirmed", " ", "")
        with self.assertRaisesRegex(ValueError, "an import marks alerts resolved"):
            set_status(register, JINJA, "resolved", "Alex", "")
        register = set_status(register, JINJA, "to-verify", "Alex", "")
        self.assertEqual(register["alerts"][0]["status"], "open")

    def test_a_confirmed_critical_alert_blocks_until_resolved_or_accepted(self):
        task = {"id": "forms"}
        register = imported("npm-audit-critical.json", task_id="forms")
        self.assertEqual(blocking_alerts(register, task), [])
        register = set_status(register, CRITICAL, "confirmed", "Alex")
        [message] = blocking_alerts(register, task)
        self.assertIn(CRITICAL, message)
        self.assertIn("alerts accept", message)
        self.assertEqual(blocking_alerts(register, {"id": "other"}), [])
        self.assertEqual(blocking_alerts(accept_alert(register, CRITICAL, "Camille", "Fixed upstream next week."), task), [])
        with self.assertRaisesRegex(ValueError, "--reason"):
            accept_alert(register, CRITICAL, "Camille", " ")
        resolved, _ = import_report(register, FIXTURES / "npm-audit-clean.json")
        self.assertEqual(blocking_alerts(resolved, task), [])

    def test_alerts_kept_inside_a_task_by_an_earlier_version_move_to_the_register(self):
        old = {"id": "upgrade", "dependency_alerts": {"alerts": [
            {"id": JINJA, "source": "pip-audit", "ecosystem": "pypi", "package": "jinja2", "version": "3.1.2",
             "advisory": "GHSA-h5c8-rqwp-cp95", "severity": "unknown", "summary": "x", "status": "to-verify"}]}}
        self.assertEqual([alert["status"] for alert in task_alerts(empty(), old)], ["open"])
        register, task = migrate_task(empty(), old)
        self.assertNotIn("dependency_alerts", task)
        self.assertEqual(task_alerts(register, task)[0]["id"], JINJA)
        register = imported("osv-jinja2.json", register=register)
        self.assertEqual(len(register["alerts"]), 1)
        self.assertEqual(link_alert(register, JINJA, "next")["alerts"][0]["tasks"], ["next", "upgrade"])


class AlertFlowTests(CapturedCli, unittest.TestCase):
    cli_output = "status-stream"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def init(self):
        write_json(self.root / "p.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
        self.cli("init", "--answers", self.root / "p.json")

    def test_alerts_imported_before_consulting_reach_the_boards_until_resolved(self):
        self.init()
        self.cli("task", "new", "Upgrade Jinja in the report service.", "--id", "upgrade")
        output = self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json")
        self.assertIn("Imported 1 alert(s) from pip-audit", output)
        self.assertTrue((self.root / ".openguildkit" / "alerts.json").is_file())
        write_json(self.root / "a.json", {"kind": "maintenance", "surface": ["service"], "data": "none", "research": "local",
                                          "concerns": ["none"]})
        self.assertIn("GHSA-H5C8-RQWP-CP95", self.cli("task", "consult", "upgrade", "--answers", self.root / "a.json"))
        # A subagent gets one board's pass and nothing else: the pass carries the task's alerts too.
        boards = json.loads(self.cli("task", "show", "upgrade"))["consultation"]["boards"]
        self.assertTrue(boards)
        for board in boards:
            self.assertIn(f"- Dependency alert {JINJA} (GHSA-H5C8-RQWP-CP95)",
                          self.cli("task", "brief", "upgrade", "--board", board))
        record = json.loads(self.cli("task", "show", "upgrade"))
        self.assertNotIn("dependency_alerts", record)
        self.cli("task", "new", "Upgrade Jinja again.", "--id", "again")
        self.cli("alerts", "link", JINJA, "--task", "again")
        write_json(self.root / "clean.json", {"dependencies": [{"name": "jinja2", "version": "3.1.3", "vulns": []}]})
        self.assertIn("1 resolved", self.cli("alerts", "import", self.root / "clean.json"))
        self.assertNotIn("GHSA-H5C8", self.cli("task", "consult", "again", "--answers", self.root / "a.json"))
        listed = json.loads(self.cli("alerts", "list", "--status", "resolved", "--json"))
        self.assertEqual([alert["id"] for alert in listed["alerts"]], [JINJA])

    def test_a_person_accepts_a_critical_alert_at_a_terminal_only(self):
        self.init()
        self.cli("alerts", "import", FIXTURES / "npm-audit-critical.json")
        self.cli("alerts", "set", CRITICAL, "--status", "confirmed", "--by", "Alex")
        # Without a terminal (an agent, a pipe), whatever stdin the test runner was given.
        with patch("sys.stdin.isatty", return_value=False):
            self.assertIn("interactive terminal", self.cli("alerts", "set", CRITICAL, "--status", "dismissed",
                                                           "--by", "Bot", "--reason", "noise", code=1))
            self.assertIn("interactive terminal", self.cli("alerts", "accept", CRITICAL, "--by", "Bot", "--reason", "x",
                                                           code=1))
        new = json.loads(self.cli("alerts", "list", "--status", "confirmed", "--without-task", "--json"))
        self.assertEqual([alert["id"] for alert in new["alerts"]], [CRITICAL])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=CRITICAL):
            self.assertIn("(accepted)", self.cli("alerts", "accept", CRITICAL, "--by", "Camille", "--reason", "Behind a VPN."))

    def test_a_person_sets_the_severity_pip_audit_leaves_unknown_and_it_then_blocks(self):
        self.init()
        self.cli("task", "new", "Upgrade Jinja in the report service.", "--id", "upgrade")
        self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json")
        self.cli("alerts", "set", JINJA, "--status", "confirmed", "--by", "Alex")
        register_file = self.root / ".openguildkit" / "alerts.json"
        task = {"id": "upgrade"}

        def register():
            return json.loads(register_file.read_text(encoding="utf-8"))

        self.assertEqual(register()["alerts"][0]["severity"], "unknown")
        self.assertEqual(blocking_alerts(register(), task), [])
        self.assertIn("interactive terminal", self.cli("alerts", "severity", JINJA, "--level", "critical", "--by", "Bot",
                                                       "--reason", "CVSS 9.8", code=1, stdin=""))
        self.assertEqual(register()["alerts"][0]["severity"], "unknown")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=JINJA):
            output = self.cli("alerts", "severity", JINJA, "--level", "critical", "--by", "Camille", "--reason", "CVSS 9.8")
        self.assertIn("severity critical", output)
        alert = register()["alerts"][0]
        self.assertEqual({key: alert["severity_set"][key] for key in ("from", "by", "reason")},
                         {"from": "unknown", "by": "Camille", "reason": "CVSS 9.8"})
        self.assertEqual(len(blocking_alerts(register(), task)), 1)
        self.cli("alerts", "import", FIXTURES / "pip-audit.json")
        self.assertEqual(register()["alerts"][0]["severity"], "critical")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=JINJA):
            self.cli("alerts", "severity", JINJA, "--level", "high", "--by", "Camille", "--reason", "Templates are ours")
        self.assertEqual(blocking_alerts(register(), task), [])
        self.cli("alerts", "import", FIXTURES / "osv-jinja2.json")
        self.assertEqual(register()["alerts"][0]["severity"], "high")

    def test_an_import_after_the_consultation_says_to_consult_again(self):
        self.init()
        self.cli("task", "new", "Upgrade Jinja in the report service.", "--id", "upgrade")
        reminder = "consult it again with openguildkit task consult upgrade --reuse-answers"
        self.assertNotIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json"))
        write_json(self.root / "a.json", {"kind": "maintenance", "surface": ["service"], "data": "none", "research": "local",
                                          "concerns": ["none"]})
        self.cli("task", "consult", "upgrade", "--answers", self.root / "a.json")
        self.assertIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "npm-audit-critical.json"))

    def test_an_import_that_brings_nothing_new_to_the_consultation_asks_nothing(self):
        self.init()
        self.cli("task", "new", "Upgrade Jinja in the report service.", "--id", "upgrade")
        reminder = "consult it again with openguildkit task consult upgrade --reuse-answers"
        self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json")
        write_json(self.root / "a.json", {"kind": "maintenance", "surface": ["service"], "data": "none", "research": "local",
                                          "concerns": ["none"]})
        self.cli("task", "consult", "upgrade", "--answers", self.root / "a.json")
        self.assertNotIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json"))
        self.assertIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "npm-audit-critical.json"))
        self.cli("task", "consult", "upgrade", "--answers", self.root / "a.json")
        self.assertNotIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "npm-audit-critical.json"))

    def test_a_confirmed_critical_alert_blocks_approval_and_completion(self):
        write_json(self.root / "p.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], "packs": ["python"]})
        self.cli("init", "--answers", self.root / "p.json")
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "status")
        self.cli("task", "alerts", "status", "--import", FIXTURES / "npm-audit-critical.json")
        self.cli("task", "alerts", "status", "--set", CRITICAL, "--status", "confirmed", "--by", "Alex")
        self.cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.cli("task", "template", "status"))
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.cli("task", "review", "status", "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="status"):
            error = self.cli("task", "decide", "status", "--approve", "--by", "Camille", "--reason", "Agreed", code=1)
        self.assertIn(f"Dependency alert {CRITICAL}", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=CRITICAL):
            self.cli("alerts", "accept", CRITICAL, "--by", "Camille", "--reason", "Only reachable by admins until 2.0.1.")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="status"):
            self.cli("task", "decide", "status", "--approve", "--by", "Camille", "--reason", "Agreed")
        register_file = self.root / ".openguildkit" / "alerts.json"
        register = json.loads(register_file.read_text(encoding="utf-8"))
        register["alerts"][0].pop("accepted")
        write_json(register_file, register)
        checks = json.loads(self.cli("task", "checks", "status", "--json"))
        outcomes = [{"check": check["id"], "status": "not-applicable", "reason": "No change here.", "owner": "Camille"}
                    for check in checks]
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": outcomes})
        self.assertIn("1 point(s)", self.cli("task", "result", "status", "--file", self.root / "result.json"))
        error = self.cli("task", "complete", "status", code=1)
        self.assertIn(f"Dependency alert {CRITICAL}", error)
        self.cli("alerts", "import", FIXTURES / "npm-audit-clean.json")
        self.assertEqual(self.cli("task", "complete", "status").strip(), "done")

    def test_the_scheduled_job_opens_a_task_per_new_confirmed_alert_and_proposes_the_register(self):
        from tests.test_market import pinned_actions, run_block
        workflow = WATCH_TEMPLATE.read_text(encoding="utf-8")
        repository_pins = set()
        for path in (REPO / ".github" / "workflows").glob("*.yml"):
            repository_pins |= set(pinned_actions(path.read_text(encoding="utf-8")))
        for use in pinned_actions(workflow):
            self.assertRegex(use, r"@[0-9a-f]{40}$")
            self.assertIn(use, repository_pins)
        self.assertIn("contents: write", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertIn("persist-credentials: false", workflow)
        bash, jq, git = shutil.which("bash"), shutil.which("jq"), shutil.which("git")
        if os.name == "nt" or not bash or not jq or not git:
            self.skipTest("Running the workflow steps needs bash, jq and git, as on the GitHub runner.")
        self.init()
        for command in (["init", "-q", "-b", "main"], ["add", "-A"],
                        ["-c", "user.email=dev@example.test", "-c", "user.name=Dev", "commit", "-q", "-m", "base"]):
            subprocess.run(["git", "-C", str(self.root), *command], check=True, capture_output=True)
        shutil.copy(FIXTURES / "npm-audit-critical.json", self.root / "report.json")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "openguildkit").write_text(f'#!/bin/sh\nexec "{sys.executable}" -m openguildkit "$@"\n', encoding="utf-8")
        # A stand-in for gh: lists answer from files, every other call is logged; no branch or pull request exists.
        (bin_dir / "gh").write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$GH_LOG\"\n"
            "if [ \"$1 $2\" = 'issue list' ]; then cat \"$KNOWN\"; exit 0; fi\n"
            "if [ \"$1 $2\" = 'pr list' ]; then exit 0; fi\n"
            "case \"$2\" in repos/*/git/ref/heads/*|repos/*/contents/*\\?ref=*) exit 1;; esac\n", encoding="utf-8")
        for name in ("openguildkit", "gh"):
            (bin_dir / name).chmod(0o755)
        (self.root / "known.txt").write_text("", encoding="utf-8")
        log = self.root / "gh.log"
        environment = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                       "PYTHONPATH": str(REPO / "src"), "GH_LOG": str(log), "KNOWN": str(self.root / "known.txt"),
                       "GITHUB_STEP_SUMMARY": str(self.root / "summary.md"), "GITHUB_REPOSITORY": "example/portal",
                       "BASE": "main", "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1"}

        def step(name):
            log.unlink(missing_ok=True)
            result = subprocess.run([bash, "-e", "-c", run_block(workflow, name)], cwd=self.root, env=environment,
                                    check=True, capture_output=True, text=True)
            return result.stdout, log.read_text(encoding="utf-8") if log.exists() else ""

        step("Import the report into the alert register")
        self.assertIn(f"- {CRITICAL}", (self.root / "summary.md").read_text(encoding="utf-8"))
        self.assertNotIn("issue create", step("Open a task per new confirmed alert")[1])
        _, calls = step("Propose the register in a pull request")
        self.assertIn("api -X POST repos/example/portal/git/refs -f ref=refs/heads/openguildkit/dependency-watch-42-1", calls)
        self.assertIn("api -X PUT repos/example/portal/contents/.openguildkit/alerts.json -f "
                      "branch=openguildkit/dependency-watch-42-1", calls)
        self.assertIn("pr create --head openguildkit/dependency-watch-42-1 --base main", calls)
        self.assertIn(f"- `{CRITICAL}`", (self.root / "body.md").read_text(encoding="utf-8"))

        self.cli("alerts", "set", CRITICAL, "--status", "confirmed", "--by", "Alex")
        task_id = "dep-form-parser-ghsa-xxxx-yyyy-zzzz"
        _, calls = step("Open a task per new confirmed alert")
        self.assertIn(f"issue create --title OpenGuildKit task {task_id}: dependency alert {CRITICAL} --body", calls)
        self.assertIn(f"openguildkit task new \"Fix dependency alert {CRITICAL}", calls)
        self.assertEqual(find_alert(load_register(self.root / ".openguildkit"), CRITICAL)["tasks"], [task_id])
        self.assertEqual(json.loads(self.cli("task", "show", task_id))["status"], "draft")
        self.assertIn(f"`{task_id}` for `{CRITICAL}`", step("Propose the register in a pull request") and
                      (self.root / "body.md").read_text(encoding="utf-8"))
        (self.root / "known.txt").write_text(f"OpenGuildKit task {task_id}: dependency alert {CRITICAL}\n",
                                             encoding="utf-8")
        output, calls = step("Open a task per new confirmed alert")
        self.assertNotIn("issue create", calls)
        self.assertEqual(json.loads((self.root / "opened.json").read_text(encoding="utf-8")), [])
        for command in (["add", ".openguildkit/alerts.json"], ["-c", "user.email=dev@example.test", "-c",
                                                                "user.name=Dev", "commit", "-q", "-m", "register"]):
            subprocess.run(["git", "-C", str(self.root), *command], check=True, capture_output=True)
        self.assertIn("did not change", step("Propose the register in a pull request")[0])

    def test_alerts_tasks_lists_then_opens_one_task_per_confirmed_alert_without_one(self):
        self.init()
        self.cli("alerts", "import", FIXTURES / "npm-audit-critical.json")
        self.assertIn("No confirmed alert waits for a task.", self.cli("alerts", "tasks"))
        self.cli("alerts", "set", CRITICAL, "--status", "confirmed", "--by", "Alex")
        listed = self.cli("alerts", "tasks")
        self.assertIn(f"{CRITICAL} (critical): task dep-form-parser-ghsa-xxxx-yyyy-zzzz\n", listed)
        self.assertFalse((self.root / ".openguildkit" / "tasks" / "dep-form-parser-ghsa-xxxx-yyyy-zzzz.json").exists())
        opened = json.loads(self.cli("alerts", "tasks", "--open", "--json"))
        self.assertEqual([row["task"] for row in opened], ["dep-form-parser-ghsa-xxxx-yyyy-zzzz"])
        task = json.loads(self.cli("task", "show", "dep-form-parser-ghsa-xxxx-yyyy-zzzz"))
        self.assertIn(f"Fix dependency alert {CRITICAL}", task["brief"])
        self.assertEqual(json.loads(self.cli("alerts", "tasks", "--json")), [])
        self.assertIn(CRITICAL, self.cli("alerts", "list", "--task", "dep-form-parser-ghsa-xxxx-yyyy-zzzz"))


if __name__ == "__main__":
    unittest.main()
