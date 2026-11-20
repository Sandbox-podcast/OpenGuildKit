import json
import unittest
from pathlib import Path

from openguildkit.alerts import alert_summary, import_alerts, parse_report, set_alert_status

FIXTURES = Path(__file__).with_name("fixtures") / "alerts"


class AlertTests(unittest.TestCase):
    def test_each_scanner_report_is_normalized(self):
        tool, alerts = parse_report((FIXTURES / "npm-audit.json").read_bytes(), "npm")
        self.assertEqual(tool, "npm audit")
        self.assertEqual(alerts[0]["advisory"], "GHSA-c2qf-rxjj-qqgw")
        self.assertEqual(alerts[0]["fix"], "semver 5.7.2")
        tool, alerts = parse_report((FIXTURES / "pip-audit.json").read_bytes(), "pip")
        self.assertEqual((tool, alerts[0]["package"], alerts[0]["version"], alerts[0]["fix"]), ("pip-audit", "jinja2", "3.1.2", "3.1.3"))
        self.assertEqual(len(alerts), 1)
        tool, alerts = parse_report((FIXTURES / "osv-scanner.json").read_bytes(), "osv")
        self.assertEqual((alerts[0]["ecosystem"], alerts[0]["severity"]), ("Go", "moderate"))
        dependabot = [{"state": "open", "html_url": "https://github.com/o/r/security/dependabot/1",
                       "dependency": {"package": {"ecosystem": "npm", "name": "lodash"}},
                       "security_advisory": {"ghsa_id": "GHSA-35jh-r3h4-6jhm", "summary": "Command injection", "severity": "high"},
                       "security_vulnerability": {"vulnerable_version_range": "< 4.17.21", "first_patched_version": {"identifier": "4.17.21"}}}]
        tool, alerts = parse_report(json.dumps(dependabot).encode(), "gh")
        self.assertEqual((tool, alerts[0]["fix"]), ("GitHub Dependabot", "4.17.21"))
        with self.assertRaisesRegex(ValueError, "is not an npm audit"):
            parse_report(b'{"hello": 1}', "x")

    def test_reviewers_mark_alerts_and_the_summary_traces_the_import(self):
        task = import_alerts({"id": "t"}, FIXTURES / "pip-audit.json")
        alert_id = task["dependency_alerts"]["alerts"][0]["id"]
        with self.assertRaisesRegex(ValueError, "reason"):
            set_alert_status(task, alert_id, "dismissed", "Alex", "")
        task = set_alert_status(task, alert_id, "dismissed", "Alex", "Templates never render user input.")
        task = import_alerts(task, FIXTURES / "pip-audit.json")
        self.assertEqual(task["dependency_alerts"]["alerts"][0]["status"], "dismissed")
        summary = alert_summary(task)
        self.assertEqual(summary["by_status"]["dismissed"], 1)
        self.assertEqual(len(summary["imports"]), 2)
        self.assertEqual(len(summary["imports"][0]["sha256"]), 64)


class AlertFlowTests(unittest.TestCase):
    def test_alerts_imported_before_consulting_reach_the_boards(self):
        import contextlib, io, tempfile
        from openguildkit.cli import main
        from openguildkit.storage import write_json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def cli(*args):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["--project", str(root), *map(str, args)]), 0)
                return out.getvalue()
            write_json(root / "p.json", {"name": "Portal", "stack": ["Python"]})
            cli("init", "--answers", root / "p.json")
            cli("task", "new", "Upgrade Jinja in the report service.", "--id", "upgrade")
            output = cli("task", "alerts", "upgrade", "--import", FIXTURES / "pip-audit.json")
            self.assertIn("Imported 1 alert(s) from pip-audit", output)
            write_json(root / "a.json", {"kind": "maintenance", "surface": ["service"], "data": "none", "research": "local"})
            consultation = cli("task", "consult", "upgrade", "--answers", root / "a.json")
            self.assertIn("GHSA-h5c8-rqwp-cp95", consultation)


if __name__ == "__main__":
    unittest.main()
