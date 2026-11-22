import contextlib
import io
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
    accept_alert, blocking_alerts, import_report, link_alert, migrate_task, parse_report, set_status, summary,
    task_alerts,
)
from openguildkit.cli import main
from openguildkit.storage import write_json

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
        register, changes = import_report(register, FIXTURES / "dependabot-empty.json", today="2026-11-22")
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


class AlertFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def cli(self, *args, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["--project", str(self.root), *map(str, args)]), code, err.getvalue())
        return out.getvalue() if code == 0 else err.getvalue()

    def init(self):
        write_json(self.root / "p.json", {"name": "Portal", "stack": ["Python"]})
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
                                                       "--reason", "CVSS 9.8", code=1))
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
        reminder = "run openguildkit task consult upgrade again"
        self.assertNotIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json"))
        write_json(self.root / "a.json", {"kind": "maintenance", "surface": ["service"], "data": "none", "research": "local",
                                          "concerns": ["none"]})
        self.cli("task", "consult", "upgrade", "--answers", self.root / "a.json")
        self.assertIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "npm-audit-critical.json"))

    def test_an_import_that_brings_nothing_new_to_the_consultation_asks_nothing(self):
        self.init()
        self.cli("task", "new", "Upgrade Jinja in the report service.", "--id", "upgrade")
        reminder = "run openguildkit task consult upgrade again"
        self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json")
        write_json(self.root / "a.json", {"kind": "maintenance", "surface": ["service"], "data": "none", "research": "local",
                                          "concerns": ["none"]})
        self.cli("task", "consult", "upgrade", "--answers", self.root / "a.json")
        self.assertNotIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json"))
        self.assertIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "npm-audit-critical.json"))
        self.cli("task", "consult", "upgrade", "--answers", self.root / "a.json")
        self.assertNotIn(reminder, self.cli("task", "alerts", "upgrade", "--import", FIXTURES / "npm-audit-critical.json"))

    def test_a_confirmed_critical_alert_blocks_approval_and_completion(self):
        write_json(self.root / "p.json", {"name": "Portal", "stack": ["Python"], "packs": ["python"]})
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

    def test_the_scheduled_job_imports_the_report_and_opens_an_issue_per_new_confirmed_alert(self):
        from tests.test_market import pinned_actions, run_block
        workflow = WATCH_TEMPLATE.read_text(encoding="utf-8")
        repository_pins = set()
        for path in (REPO / ".github" / "workflows").glob("*.yml"):
            repository_pins |= set(pinned_actions(path.read_text(encoding="utf-8")))
        for use in pinned_actions(workflow):
            self.assertRegex(use, r"@[0-9a-f]{40}$")
            self.assertIn(use, repository_pins)
        bash, jq = shutil.which("bash"), shutil.which("jq")
        if os.name == "nt" or not bash or not jq:
            self.skipTest("Running the workflow steps needs bash and jq, as on the GitHub runner.")
        self.init()
        shutil.copy(FIXTURES / "npm-audit-critical.json", self.root / "report.json")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "openguildkit").write_text(f'#!/bin/sh\nexec "{sys.executable}" -m openguildkit "$@"\n', encoding="utf-8")
        (bin_dir / "gh").write_text("#!/bin/sh\nif [ \"$2\" = list ]; then cat \"$KNOWN\"; exit 0; fi\n"
                                    "printf '%s\\n' \"$@\" >> \"$GH_LOG\"\n", encoding="utf-8")
        for name in ("openguildkit", "gh"):
            (bin_dir / name).chmod(0o755)
        (self.root / "known.txt").write_text("", encoding="utf-8")
        environment = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                       "PYTHONPATH": str(REPO / "src"), "GH_LOG": str(self.root / "gh.log"),
                       "KNOWN": str(self.root / "known.txt"), "GITHUB_STEP_SUMMARY": str(self.root / "summary.md")}

        def step(name):
            return subprocess.run([bash, "-e", "-c", run_block(workflow, name)], cwd=self.root, env=environment,
                                  check=True, capture_output=True, text=True)

        step("Import the report into the alert register")
        self.assertIn(f"- {CRITICAL}", (self.root / "summary.md").read_text(encoding="utf-8"))
        step("Open an issue per new confirmed alert")
        self.assertFalse((self.root / "gh.log").exists())
        self.cli("alerts", "set", CRITICAL, "--status", "confirmed", "--by", "Alex")
        step("Open an issue per new confirmed alert")
        calls = (self.root / "gh.log").read_text(encoding="utf-8")
        self.assertIn(f"--title\nDependency alert: {CRITICAL}\n--body\n", calls)
        self.assertIn(f"openguildkit task alerts TASK --link {CRITICAL}", calls)
        (self.root / "gh.log").unlink()
        (self.root / "known.txt").write_text(f"Dependency alert: {CRITICAL}\n", encoding="utf-8")
        self.assertIn("Already reported", step("Open an issue per new confirmed alert").stdout)
        self.assertFalse((self.root / "gh.log").exists())


if __name__ == "__main__":
    unittest.main()
