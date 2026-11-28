"""A report that analyzed nothing resolves nothing, and the person sees what an import resolved (issue #207)."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.alerts import NOTHING_ANALYZED, find_alert, import_report, set_status
from openguildkit.storage import read_json, write_json
from tests.test_approval_lifecycle import EXAMPLE, ApprovalCase

FIXTURES = Path(__file__).with_name("fixtures") / "alerts"
CRITICAL = "npm:form-parser:ghsa-xxxx-yyyy-zzzz"
JINJA = "pypi:jinja2:ghsa-h5c8-rqwp-cp95"
SEMVER = "npm:semver:ghsa-c2qf-rxjj-qqgw"
MINIMIST = "npm:minimist:ghsa-vh95-rmgr-6w4m"
# What each scanner writes when it analyzed nothing, as an agent could write it to escape an alert.
EMPTY = {
    "npm audit": ("npm-audit-critical.json", CRITICAL, {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {}}),
    "pip-audit": ("pip-audit.json", JINJA, {"dependencies": [], "fixes": []}),
    "OSV-Scanner": ("osv-jinja2.json", JINJA, {"results": []}),
    "GitHub Dependabot": ("dependabot-jinja2.json", JINJA, []),
}


def empty():
    return {"schema_version": 1, "alerts": [], "imports": []}


def lockfile_report(package, severity, advisory, total):
    """What npm audit writes for one lockfile: one vulnerable package among `total` dependencies."""
    via = {"source": 1, "name": package, "title": "x", "url": f"https://github.com/advisories/{advisory}",
           "severity": severity, "range": "<1.0.0"}
    return {"auditReportVersion": 2, "vulnerabilities": {package: {"name": package, "severity": severity, "via": [via],
                                                                   "range": "<1.0.0"}},
            "metadata": {"dependencies": {"total": total}}}


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

    def test_a_report_under_another_name_that_resolves_alerts_names_the_report_before_it(self):
        semver = "npm:semver:ghsa-c2qf-rxjj-qqgw"
        write_json(self.folder / "front.json", lockfile_report("semver", "critical", "GHSA-c2qf-rxjj-qqgw", 10))
        write_json(self.folder / "admin.json", lockfile_report("minimist", "high", "GHSA-vh95-rmgr-6w4m", 20))
        register, changes = import_report(empty(), self.folder / "front.json", today="2026-11-21")
        self.assertNotIn("previous_file", changes)
        register = set_status(register, semver, "confirmed", "Alex")
        register, changes = import_report(register, self.folder / "admin.json", today="2026-11-22")
        self.assertEqual((changes["new"], changes["resolved"]), (["npm:minimist:ghsa-vh95-rmgr-6w4m"], [semver]))
        self.assertEqual(changes["previous_file"], "front.json")
        register, changes = import_report(register, self.folder / "admin.json", today="2026-11-23")
        self.assertEqual((changes["resolved"], "previous_file" in changes), ([], False))
        write_json(self.folder / "admin.json", {**lockfile_report("minimist", "high", "GHSA-vh95-rmgr-6w4m", 20),
                                                "vulnerabilities": {}})
        register, changes = import_report(register, self.folder / "admin.json", today="2026-11-24")
        self.assertEqual(("previous_file" in changes, changes["resolved"]), (False, ["npm:minimist:ghsa-vh95-rmgr-6w4m"]))

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


class ScopeTests(unittest.TestCase):
    """A report imported with --scope resolves, reopens and counts as absent only the alerts of its own scope (#393)."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        semver = lockfile_report("semver", "critical", "GHSA-c2qf-rxjj-qqgw", 10)
        minimist = lockfile_report("minimist", "high", "GHSA-vh95-rmgr-6w4m", 20)
        for name, report in {
            "front.json": semver, "admin.json": minimist,
            "front-clean.json": {**semver, "vulnerabilities": {}}, "admin-clean.json": {**minimist, "vulnerabilities": {}},
            "admin-semver.json": lockfile_report("semver", "critical", "GHSA-c2qf-rxjj-qqgw", 20),
        }.items():
            write_json(self.folder / name, report)

    def load(self, register, name, scope=None, day="2026-11-22"):
        return import_report(register, self.folder / name, scope=scope, today=day)

    @staticmethod
    def states(register):
        return {alert["id"]: alert["status"] for alert in register["alerts"]}

    def test_a_confirmed_critical_alert_of_a_scope_stays_open_when_another_scope_is_imported(self):
        register, changes = self.load(empty(), "front.json", "front", "2026-11-21")
        self.assertEqual((changes["scope"], changes["new"]), ("front", [f"{SEMVER}@front"]))
        register = set_status(register, f"{SEMVER}@front", "confirmed", "Alex")
        register, changes = self.load(register, "admin.json", "admin")
        self.assertEqual((changes["scope"], changes["new"], changes["resolved"]), ("admin", [f"{MINIMIST}@admin"], []))
        self.assertNotIn("previous_file", changes)
        self.assertEqual(self.states(register), {f"{SEMVER}@front": "confirmed", f"{MINIMIST}@admin": "open"})
        self.assertEqual({alert["id"]: alert["scope"] for alert in register["alerts"]},
                         {f"{SEMVER}@front": "front", f"{MINIMIST}@admin": "admin"})
        register, changes = self.load(register, "front-clean.json", "front", "2026-11-23")
        self.assertEqual(changes["resolved"], [f"{SEMVER}@front"])
        self.assertEqual(self.states(register), {f"{SEMVER}@front": "resolved", f"{MINIMIST}@admin": "open"})
        resolved = next(alert for alert in register["alerts"] if alert["status"] == "resolved")
        self.assertEqual(resolved["resolved_by"]["scope"], "front")
        register, changes = self.load(register, "admin.json", "admin", "2026-11-24")
        self.assertEqual((changes["reopened"], changes["new"]), ([], []))
        register, changes = self.load(register, "front.json", "front", "2026-11-25")
        self.assertEqual((changes["reopened"], changes["new"]), ([f"{SEMVER}@front"], []))
        self.assertEqual(self.states(register), {f"{SEMVER}@front": "confirmed", f"{MINIMIST}@admin": "open"})

    def test_an_import_without_a_scope_neither_resolves_nor_reopens_an_alert_of_a_scope(self):
        register, _ = self.load(empty(), "front.json", "front", "2026-11-21")
        register = set_status(register, f"{SEMVER}@front", "confirmed", "Alex")
        register, changes = self.load(register, "admin.json")
        self.assertEqual((changes["new"], changes["resolved"], changes["other_scopes"]), ([MINIMIST], [], ["front"]))
        self.assertNotIn("scope", changes)
        self.assertEqual(self.states(register), {f"{SEMVER}@front": "confirmed", MINIMIST: "open"})
        register, changes = self.load(register, "front-clean.json")
        self.assertEqual(changes["resolved"], [MINIMIST])
        self.assertEqual(self.states(register), {f"{SEMVER}@front": "confirmed", MINIMIST: "resolved"})
        register, _ = self.load(register, "front-clean.json", "front", "2026-11-23")
        self.assertEqual(self.states(register)[f"{SEMVER}@front"], "resolved")
        register, changes = self.load(register, "front.json", day="2026-11-24")
        self.assertEqual((changes["new"], changes["reopened"]), ([SEMVER], []))
        self.assertEqual(self.states(register)[f"{SEMVER}@front"], "resolved")

    def test_an_alert_without_a_scope_that_a_scoped_report_lists_stays_without_one_and_the_import_says_so(self):
        register, _ = self.load(empty(), "front.json", day="2026-11-21")
        register = set_status(register, SEMVER, "confirmed", "Alex")
        register, changes = self.load(register, "front.json", "front")
        self.assertEqual((changes["new"], changes["resolved"], changes["unscoped"]), ([], [], [SEMVER]))
        alert, = register["alerts"]
        self.assertEqual((alert["id"], alert["status"], "scope" in alert), (SEMVER, "confirmed", False))
        register, changes = self.load(register, "front-clean.json", "front", "2026-11-23")
        self.assertEqual((changes["resolved"], "unscoped" in changes), ([], False))
        self.assertEqual(self.states(register), {SEMVER: "confirmed"})
        register, changes = self.load(register, "front-clean.json", day="2026-11-24")
        self.assertEqual(changes["resolved"], [SEMVER])
        register, changes = self.load(register, "front.json", "front", "2026-11-25")
        self.assertEqual((changes["new"], "unscoped" in changes), ([f"{SEMVER}@front"], False))
        self.assertEqual(self.states(register), {SEMVER: "resolved", f"{SEMVER}@front": "open"})

    def test_the_same_advisory_in_two_scopes_gives_one_entry_per_scope(self):
        register, _ = self.load(empty(), "front.json", "front", "2026-11-21")
        register, changes = self.load(register, "admin-semver.json", "admin")
        self.assertEqual(changes["new"], [f"{SEMVER}@admin"])
        self.assertEqual(sorted(self.states(register)), [f"{SEMVER}@admin", f"{SEMVER}@front"])
        register = set_status(register, f"{SEMVER}@front", "confirmed", "Alex")
        register, changes = self.load(register, "admin-clean.json", "admin", "2026-11-23")
        self.assertEqual(changes["resolved"], [f"{SEMVER}@admin"])
        self.assertEqual(self.states(register), {f"{SEMVER}@admin": "resolved", f"{SEMVER}@front": "confirmed"})
        self.assertEqual(find_alert(register, f"{SEMVER}@front")["scope"], "front")

    def test_an_alert_of_a_scope_is_found_by_any_of_its_advisory_ids(self):
        # OGK-ALERTS-005
        register, _ = import_report(empty(), FIXTURES / "pip-audit.json", scope="api", today="2026-11-21")
        self.assertEqual(find_alert(register, "pypi:jinja2:cve-2024-22195@api")["id"], f"{JINJA}@api")
        with self.assertRaisesRegex(ValueError, "Unknown alert"):
            find_alert(register, JINJA)

    def test_a_scope_is_a_short_name_and_anything_else_is_refused(self):
        for scope in ("front", "services/api", "my-app.v2", "a", "0", "a" * 64):
            with self.subTest(scope=scope):
                self.assertEqual(import_report(empty(), self.folder / "front.json", scope=scope)[1]["scope"], scope)
        for scope in ("", "Front", "front end", "a" * 65, "front/", "/front", ".", "..", "-front", "front@x", "front:y",
                      "\u00e9", "front\n"):
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "Invalid scope"):
                import_report(empty(), self.folder / "front.json", scope=scope)


class DecisionTests(ApprovalCase):
    def test_the_prompt_and_challenge_show_a_critical_alert_an_import_resolved(self):
        # OGK-TASK-069
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
