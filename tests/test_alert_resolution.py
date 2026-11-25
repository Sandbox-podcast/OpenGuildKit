"""A report that analyzed nothing resolves nothing, and the person sees what an import resolved (issue #207)."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.alerts import NOTHING_ANALYZED, import_report, set_status
from openguildkit.storage import read_json, write_json
from tests.test_approval_lifecycle import EXAMPLE, ApprovalCase

FIXTURES = Path(__file__).with_name("fixtures") / "alerts"
CRITICAL = "npm:form-parser:ghsa-xxxx-yyyy-zzzz"
JINJA = "pypi:jinja2:ghsa-h5c8-rqwp-cp95"
# What each scanner writes when it analyzed nothing, as an agent could write it to escape an alert.
EMPTY = {
    "npm audit": ("npm-audit-critical.json", CRITICAL, {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {}}),
    "pip-audit": ("pip-audit.json", JINJA, {"dependencies": [], "fixes": []}),
    "OSV-Scanner": ("osv-jinja2.json", JINJA, {"results": []}),
    "GitHub Dependabot": ("dependabot-jinja2.json", JINJA, []),
}


def empty():
    return {"schema_version": 1, "alerts": [], "imports": []}


class EmptyReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def test_a_report_that_analyzed_no_dependency_resolves_nothing_and_says_so(self):
        for tool, (fixture, alert_id, report) in EMPTY.items():
            with self.subTest(tool=tool):
                register, _ = import_report(empty(), FIXTURES / fixture, today="2026-11-21")
                register = set_status(register, alert_id, "confirmed", "Alex")
                write_json(self.folder / "clean.json", report)
                register, changes = import_report(register, self.folder / "clean.json", today="2026-11-22")
                self.assertEqual((changes["tool"], changes["resolved"], changes["analyzed"]), (tool, [], 0))
                self.assertEqual(changes["nothing_analyzed"], NOTHING_ANALYZED[tool])
                alert = next(item for item in register["alerts"] if item["id"] == alert_id)
                self.assertEqual((alert["status"], alert["scanners"]), ("confirmed", [tool]))
                self.assertEqual(register["imports"][-1]["dependencies"], 0)

    def test_a_pip_audit_entry_it_skipped_is_not_analyzed_and_resolves_no_alert_of_its_package(self):
        skipped = {"name": "jinja2", "skip_reason": "Dependency not found on PyPI and could therefore not be audited"}
        register, _ = import_report(empty(), FIXTURES / "pip-audit.json", today="2026-11-21")
        write_json(self.folder / "skipped.json", {"dependencies": [skipped], "fixes": []})
        register, changes = import_report(register, self.folder / "skipped.json", today="2026-11-22")
        self.assertEqual((changes["resolved"], changes["analyzed"]), ([], 0))
        self.assertEqual(changes["nothing_analyzed"], NOTHING_ANALYZED["pip-audit"])
        self.assertEqual(register["alerts"][0]["status"], "open")
        register = set_status(register, JINJA, "confirmed", "Alex")
        audited = {"name": "fastapi", "version": "0.115.0", "vulns": []}
        write_json(self.folder / "mixed.json", {"dependencies": [skipped, audited], "fixes": []})
        register, changes = import_report(register, self.folder / "mixed.json", today="2026-11-23")
        self.assertEqual((changes["resolved"], changes["analyzed"]), ([], 1))
        self.assertEqual((register["alerts"][0]["status"], register["alerts"][0]["scanners"]), ("confirmed", ["pip-audit"]))
        register, changes = import_report(register, FIXTURES / "pip-audit-clean.json", today="2026-11-24")
        self.assertEqual(changes["resolved"], [JINJA])

    def test_a_confirmed_critical_alert_resolved_by_an_import_keeps_the_report(self):
        register, _ = import_report(empty(), FIXTURES / "npm-audit-critical.json", today="2026-11-21")
        register = set_status(register, CRITICAL, "confirmed", "Alex")
        register, changes = import_report(register, FIXTURES / "npm-audit-clean.json", today="2026-11-22")
        self.assertEqual((changes["resolved"], changes["analyzed"]), ([CRITICAL], 42))
        alert, = register["alerts"]
        digest = hashlib.sha256((FIXTURES / "npm-audit-clean.json").read_bytes()).hexdigest()
        self.assertEqual(alert["resolved_by"], {"tool": "npm audit", "file": "npm-audit-clean.json", "sha256": digest,
                                                "date": "2026-11-22", "dependencies": 42})
        self.assertEqual((alert["status"], alert["resolved_from"]), ("resolved", "confirmed"))
        register, changes = import_report(register, FIXTURES / "npm-audit-critical.json", today="2026-11-23")
        self.assertEqual(changes["reopened"], [CRITICAL])
        self.assertNotIn("resolved_by", register["alerts"][0])


class DecisionTests(ApprovalCase):
    def test_the_prompt_and_challenge_show_a_critical_alert_an_import_resolved(self):
        self.init()
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "t1")
        output, _ = self.run_cli("alerts", "import", FIXTURES / "npm-audit-critical.json", "--task", "t1")
        self.run_cli("alerts", "set", CRITICAL, "--status", "confirmed", "--by", "Alex")
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", "t1", "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", "t1")[0])
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", "t1", "--file", self.root / "review.json")
        forged = self.root / ".openguildkit" / "clean.json"
        write_json(forged, {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {}})
        output, _ = self.run_cli("alerts", "import", forged)
        self.assertIn("The report analyzed no dependency (metadata.dependencies counts no audited dependency): it "
                      "resolves no alert.", output)
        self.assertIn("is confirmed and critical", self.run_cli("task", "decide", "t1", "--approve", "--by", "Camille",
                                                               "--reason", "Agreed", code=1, typed="t1")[1])
        self.run_cli("alerts", "import", FIXTURES / "npm-audit-clean.json")
        day = read_json(self.state / "alerts.json")["alerts"][0]["resolved_by"]["date"]
        digest = hashlib.sha256((FIXTURES / "npm-audit-clean.json").read_bytes()).hexdigest()[:12]
        line = (f"Dependency alert {CRITICAL} (form-parser <2.0.1) was confirmed and critical, and an import resolved "
                f"it on {day}, not a person: npm audit report npm-audit-clean.json (sha256 {digest}), 42 dependencies "
                "analyzed. Check that report before deciding.")
        self.assertIn(f"- {line}\n", self.run_cli("task", "challenge", "t1")[0])
        _, prompt = self.run_cli("task", "decide", "t1", "--approve", "--by", "Camille", "--reason", "Agreed",
                                 typed="t1")
        self.assertIn(f"{line}\n", prompt)


if __name__ == "__main__":
    unittest.main()
