"""Machine checks and named evidence declared by pack rules, and the regulation packs that use them."""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import CatalogError, validate_entry, load_catalog
from openguildkit.cli import main
from openguildkit.project import init_questions, profile_recommendations, resolved_profile, validate_profile
from openguildkit.rule_checks import MAX_FILE_BYTES, MAX_FILES, evaluate_check, validate_check
from openguildkit.storage import write_json

from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
SOURCE = Path(__file__).resolve().parents[1] / "src" / "openguildkit"
TASK = "request-status"


def pack(rules, pack_id="team-rules"):
    return {"id": pack_id, "title": "Team rules", "version": "1.0.0", "description": "Rules of the team.",
            "sources": [], "rules": rules}


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_file_exists_passes_when_one_of_the_paths_exists(self):
        check = {"kind": "file-exists", "paths": ["SECURITY.md", ".github/SECURITY.md"]}
        self.assertEqual(evaluate_check(self.root, check)["status"], "failed")
        self.write(".github/SECURITY.md", "Report to security@example.test")
        outcome = evaluate_check(self.root, check)
        self.assertEqual(outcome["status"], "passed")
        self.assertIn(".github/SECURITY.md", outcome["evidence"])

    def test_text_checks_look_for_literal_text_present_or_absent(self):
        self.write(".github/workflows/ci.yml", "on:\n  pull_request_target:\n")
        self.write(".github/workflows/lint.yml", "on: push\n")
        absent = {"kind": "text", "paths": [".github/workflows/*.yml"], "contains": ["pull_request_target"],
                  "expect": "absent"}
        outcome = evaluate_check(self.root, absent)
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("ci.yml contains", outcome["evidence"])
        present = {"kind": "text", "paths": ["**/*.yml"], "contains": ["ON: PUSH"], "expect": "present",
                   "ignore_case": True}
        self.assertEqual(evaluate_check(self.root, present)["status"], "passed")
        # A regular expression is literal text here: no pattern can backtrack.
        literal = {**present, "contains": ["(a+)+$"], "ignore_case": False}
        self.write("slow.txt", "a" * 50_000 + "!")
        self.assertEqual(evaluate_check(self.root, {**literal, "paths": ["slow.txt"]})["status"], "failed")

    def test_field_checks_compare_json_and_toml_values(self):
        self.write("export.json", '{"download": {"minutes": 30}, "mode": "strict"}')
        self.write("pyproject.toml", '[tool.audit]\nlevel = 2\nenabled = true\n')
        cases = [
            ({"path": "export.json", "field": "download.minutes", "integer": True, "min": 1, "max": 60}, "passed"),
            ({"path": "export.json", "field": "download.minutes", "max": 20}, "failed"),
            ({"path": "export.json", "field": "mode", "one_of": ["strict", "audit"]}, "passed"),
            ({"path": "export.json", "field": "missing", "equals": 1}, "failed"),
            ({"path": "pyproject.toml", "field": "tool.audit.enabled", "equals": True}, "passed"),
            ({"path": "pyproject.toml", "field": "tool.audit.level", "equals": True}, "failed"),
            ({"path": "absent.json", "field": "a", "equals": 1}, "failed"),
        ]
        for fields, status in cases:
            with self.subTest(**fields):
                check = {"kind": "field", **fields}
                validate_check(check, "check", allow_command=False)
                self.assertEqual(evaluate_check(self.root, check)["status"], status)
        self.write("broken.json", '{"a": 1, "a": 2}')
        outcome = evaluate_check(self.root, {"kind": "field", "path": "broken.json", "field": "a", "equals": 1})
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("Invalid JSON", outcome["evidence"])

    def test_paths_stay_inside_the_project(self):
        for path in ("../secret.json", "/etc/passwd.json", "C:/x.json", "a/./b.json", "a\\b.json", "a//b.json", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_check({"kind": "field", "path": path, "field": "a", "equals": 1}, "check", allow_command=False)
        with self.assertRaisesRegex(ValueError, "wildcards"):
            validate_check({"kind": "field", "path": "*.json", "field": "a", "equals": 1}, "check", allow_command=False)

    @unittest.skipIf(os.name == "nt", "Creating a symbolic link needs a privilege Windows does not grant by default.")
    def test_a_link_that_leaves_the_project_is_not_read(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "SECURITY.md").write_text("outside", encoding="utf-8")
        (self.root / "SECURITY.md").symlink_to(Path(outside.name, "SECURITY.md"))
        self.assertEqual(evaluate_check(self.root, {"kind": "file-exists", "paths": ["SECURITY.md"]})["status"], "failed")

    def test_the_work_is_bounded(self):
        self.write("big.txt", "x" * (MAX_FILE_BYTES + 1))
        outcome = evaluate_check(self.root, {"kind": "text", "paths": ["big.txt"], "contains": ["x"], "expect": "present"})
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("not read", outcome["evidence"])
        for index in range(MAX_FILES + 1):
            self.write(f"many/{index}.txt", "x")
        outcome = evaluate_check(self.root, {"kind": "file-exists", "paths": ["many/*.txt"]})
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("narrow", outcome["evidence"])
        with self.assertRaisesRegex(ValueError, "1 to 20"):
            validate_check({"kind": "file-exists", "paths": [f"f{index}" for index in range(21)]}, "c", allow_command=False)
        with self.assertRaisesRegex(ValueError, "literal texts"):
            validate_check({"kind": "text", "paths": ["a"], "contains": ["x" * 201], "expect": "absent"}, "c",
                           allow_command=False)


class CatalogFormatTests(unittest.TestCase):
    def test_a_bundled_pack_cannot_run_a_command(self):
        command = pack([{"id": "lint", "check": {"kind": "command", "command": "make lint"}}])
        with self.assertRaisesRegex(CatalogError, r"\.openguildkit/catalog/packs/"):
            validate_entry("packs", command)
        validate_entry("packs", command, allow_command=True)

    def test_a_project_pack_can_run_a_command_and_the_central_policy_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            packs = Path(directory) / "packs"
            packs.mkdir()
            write_json(packs / "team-rules.json", pack([{"id": "lint", "check": {"kind": "command", "command": "make lint"}}]))
            catalog = load_catalog(Path(directory))
            self.assertEqual(catalog["packs"]["team-rules"]["rules"][0]["check"]["kind"], "command")
        central = pack([{"id": "export-link-expiry", "check": {"kind": "command", "command": "true"}}], "export-link-expiry")
        with self.assertRaisesRegex(CatalogError, "command"):
            load_catalog(central_policy=("a" * 40, central))

    def test_a_rule_without_a_check_still_needs_its_text_and_evidence_is_named(self):
        with self.assertRaisesRegex(CatalogError, "missing fields: instruction"):
            validate_entry("packs", pack([{"id": "a", "verification": "Look."}]))
        named = {"id": "a", "instruction": "Do it.", "verification": "Look.",
                 "evidence": [{"id": "record", "title": "Record"}, {"id": "record", "title": "Again"}]}
        with self.assertRaisesRegex(CatalogError, "twice"):
            validate_entry("packs", pack([named]))
        with self.assertRaisesRegex(CatalogError, "kind"):
            validate_entry("packs", pack([{"id": "a", "check": {"kind": "regex", "pattern": "(a+)+"}}]))

    def test_the_export_threshold_is_data_and_ci_check_names_no_field(self):
        source = (SOURCE / "ci.py").read_text(encoding="utf-8")
        self.assertNotIn("downloadLinkMinutes", source)
        self.assertNotIn("max_minutes", source)
        example = Path(__file__).resolve().parents[1] / "examples/export-expiry/policy/packs/export-link-expiry.json"
        check = json.loads(example.read_text(encoding="utf-8"))["rules"][0]["check"]
        self.assertEqual((check["kind"], check["path"], check["field"]), ("field", "export.json", "downloadLinkMinutes"))


class VerifyAndEvidenceTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def approved(self, rules, data="personal", **extra):
        write_json(self.root / ".openguildkit" / "catalog" / "packs" / "team-rules.json", pack(rules))
        write_json(self.root / "profile.json", {"personal_data": False, "name": "Portal", "stack": ["Python"], "packs": ["team-rules"],
                                                 "checks": [], **extra})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")), "data": data}
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

    def report(self, *checks, code=0):
        """Report the given checks, and the bundled agent-workflow rules as not applicable."""
        listed = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        others = [{"check": item["id"], "status": "not-applicable", "reason": "Not in scope.", "owner": "Camille"}
                  for item in listed if item["kind"] == "rule" and not item["id"].startswith("rule:team-rules/")]
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": [*checks, *others]})
        return self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=code)

    def checks(self):
        return {item["check"]: item for item in json.loads(self.run_cli("task", "show", TASK)[0])["result"]["checks"]}

    def test_task_verify_evaluates_each_declared_check_and_records_what_it_found(self):
        command = f'"{sys.executable}" -c "print(\'linted\')"'
        self.approved([
            {"id": "security-policy", "instruction": "Keep a security policy.", "verification": "Open it.",
             "check": {"kind": "file-exists", "paths": ["SECURITY.md"]}},
            {"id": "link-expiry", "check": {"kind": "field", "path": "export.json", "field": "minutes", "max": 60}},
            {"id": "lint", "check": {"kind": "command", "command": command}},
        ], required_rules=["team-rules/link-expiry"])
        (self.root / "export.json").write_text('{"minutes": 90}', encoding="utf-8")
        listing = self.run_cli("task", "checks", TASK)[0]
        self.assertIn("rule:team-rules/link-expiry [mandatory] not reported", listing)
        _, error = self.report({"check": "rule:team-rules/security-policy", "status": "passed", "evidence": "trust me"},
                               code=1)
        self.assertIn("task verify", error)
        output = self.run_cli("task", "verify", TASK)[0]
        self.assertIn("rule:team-rules/security-policy: failed\n    Not found: none of SECURITY.md exists.", output)
        self.assertIn("rule:team-rules/link-expiry: failed", output)
        self.assertIn("rule:team-rules/lint: passed", output)
        checks = self.checks()
        self.assertIn("minutes = 90 (above 60)", checks["rule:team-rules/link-expiry"]["evidence"])
        log = self.root / checks["rule:team-rules/lint"]["evidence"]
        self.assertIn("linted", log.read_text(encoding="utf-8"))
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("rule:team-rules/link-expiry is mandatory and failed", error)

        (self.root / "export.json").write_text('{"minutes": 30}', encoding="utf-8")
        (self.root / "SECURITY.md").write_text("Report to security@example.test", encoding="utf-8")
        output = self.run_cli("task", "verify", TASK)[0]
        self.assertIn("rule:team-rules/security-policy: passed\n    Found SECURITY.md.", output)
        self.assertIn("rule:team-rules/security-policy [verify] passed: Found SECURITY.md.", self.run_cli("task", "checks", TASK)[0])
        self.assertEqual({self.checks()[f"rule:team-rules/{name}"]["status"] for name in ("security-policy", "link-expiry", "lint")},
                         {"passed"})
        self.report()
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")

    RECORD = {"id": "record-processing", "instruction": "Update the record.", "verification": "Link it.",
              "evidence": [{"id": "processing-record", "title": "Record of processing activities"}]}
    CHECK = "evidence:team-rules/record-processing/processing-record"
    RULE = {"check": "rule:team-rules/record-processing", "status": "passed", "evidence": "Updated."}
    NOT_APPLICABLE = {"check": CHECK, "status": "not-applicable", "reason": "Only a stylesheet changes.",
                      "owner": "Camille"}

    def test_a_named_evidence_is_answered_on_every_task_but_may_be_declared_not_applicable(self):
        self.approved([self.RECORD], data="internal")
        output, _ = self.run_cli("task", "result", TASK, "--template")
        entry = next(item for item in json.loads(output)["checks"] if item["check"] == self.CHECK)
        self.assertEqual((entry["evidence_name"], entry["requirement"]),
                         ("Record of processing activities", "passed-or-not-applicable"))
        self.assertNotIn("mandatory", entry)
        self.assertIn("not-applicable", entry["answer"])
        self.assertIn("https", entry["answer"])
        self.report(self.RULE)
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn(f"{self.CHECK} has no answer", error)
        self.assertIn("project path or an https link", error)
        self.assertIn("not-applicable with a reason and an owner", error)
        self.assertIn("Ready: run task complete.", self.report(self.RULE, self.NOT_APPLICABLE)[0])
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")
        exported = self.run_cli("task", "export", TASK)[0].strip()
        record = json.loads((self.root / exported).read_text(encoding="utf-8"))
        self.assertEqual(record["result"]["evidence_not_applicable"],
                         [{"check": self.CHECK, "reason": "Only a stylesheet changes.", "owner": "Camille"}])

    def test_required_rules_make_the_evidence_a_must(self):
        self.approved([self.RECORD], data="internal", required_rules=["team-rules/record-processing"])
        _, error = self.report(self.RULE, self.NOT_APPLICABLE)
        self.assertIn("required_rules", error)
        self.assertIn("project path", self.report({"check": self.CHECK, "status": "passed", "evidence": "../record.md",
                                                   "owner": "Dana"}, code=1)[1])
        self.assertIn("does not exist", self.report({"check": self.CHECK, "status": "passed",
                                                     "evidence": "docs/record.md", "owner": "Dana"})[1])
        (self.root / "docs").mkdir()
        (self.root / "docs" / "record.md").write_text("Processing record", encoding="utf-8")
        self.report(self.RULE, {"check": self.CHECK, "status": "passed", "evidence": "docs/record.md", "owner": "Dana"})
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")
        self.assertEqual(self.checks()[self.CHECK]["evidence"], "docs/record.md")

    def test_an_evidence_that_applies_to_the_task_data_must_be_supplied(self):
        when = {**self.RECORD, "evidence": [{**self.RECORD["evidence"][0], "when": {"data": ["personal", "regulated"]}}]}
        self.approved([when], data="personal")
        output, _ = self.run_cli("task", "result", TASK, "--template")
        entry = next(item for item in json.loads(output)["checks"] if item["check"] == self.CHECK)
        self.assertEqual(entry["requirement"], "passed")
        output, error = self.report(self.RULE, self.NOT_APPLICABLE)
        self.assertIn("Not recorded: " + self.CHECK, error)
        self.assertIn("data is personal", error)
        self.assertIn("rule:team-rules/record-processing: passed", output)

    def test_an_evidence_condition_names_known_data_answers(self):
        bad = {**self.RECORD, "evidence": [{**self.RECORD["evidence"][0], "when": {"data": ["secret"]}}]}
        with self.assertRaisesRegex(CatalogError, "when.data"):
            validate_entry("packs", pack([bad]))
        with self.assertRaisesRegex(CatalogError, "when"):
            validate_entry("packs", pack([{**self.RECORD, "evidence": [{**self.RECORD["evidence"][0], "when": {}}]}]))

    def test_a_named_evidence_can_be_an_https_link_and_appears_in_the_instructions(self):
        self.approved([{"id": "assess-dpia", "instruction": "Ask about the assessment.", "verification": "Link it.",
                        "evidence": [{"id": "dpia-decision", "title": "Decision on the impact assessment"}]}])
        instructions = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Evidence for task result: Decision on the impact assessment", instructions)
        self.report({"check": "rule:team-rules/assess-dpia", "status": "passed", "evidence": "Asked."},
                    {"check": "evidence:team-rules/assess-dpia/dpia-decision", "status": "passed",
                     "evidence": "https://wiki.example.test/privacy/dpia-42", "owner": "Dana"})
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")


class RegulationPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_pci_dss_rules_cite_a_requirement_of_the_edition_read(self):
        pci = self.catalog["packs"]["pci-dss"]
        self.assertIn("PCI DSS v4.0.1", pci["description"])
        for rule in pci["rules"]:
            with self.subTest(rule=rule["id"]):
                self.assertRegex(rule["instruction"], r"Requirements? \d+(\.\d+)*")
        urls = [source["url"] for source in pci["sources"]]
        # The requirements come from the PCI SSC; the secret scanners that the 8.6.2 check looks for, from their projects.
        scanners = {"https://github.com/gitleaks/gitleaks", "https://github.com/trufflesecurity/trufflehog",
                    "https://github.com/Yelp/detect-secrets"}
        self.assertTrue(all(re.match(r"https://(www|blog|listings)\.pcisecuritystandards\.org/", url) or url in scanners
                            for url in urls))

    def test_pci_dss_covers_what_a_development_team_meets_first(self):
        pci = self.catalog["packs"]["pci-dss"]
        rules = {rule["id"]: rule for rule in pci["rules"]}
        for rule_id, requirement in (("mask-displayed-pan", "3.4.1"), ("no-live-pans-before-production", "6.5.5"),
                                     ("remove-test-data-before-production", "6.5.6"),
                                     ("no-hard-coded-passwords", "8.6.2")):
            with self.subTest(rule=rule_id):
                self.assertIn(f"Requirement {requirement}", rules[rule_id]["instruction"])
                self.assertTrue(rules[rule_id]["verification"])
        scanner = rules["no-hard-coded-passwords"]["check"]
        self.assertEqual((scanner["kind"], scanner["expect"]), ("text", "present"))
        self.assertIn("gitleaks", scanner["contains"])
        self.assertIn(".pre-commit-config.yaml", scanner["paths"])
        self.assertIn("PCI SSC Document Library", pci["description"])
        dated = {source["url"]: source["checked"] for source in pci["sources"]}
        self.assertEqual(dated["https://www.pcisecuritystandards.org/document_library/?class=pcidss&doc=pci_dss"],
                         "2026-11-22")
        self.assertEqual(dated["https://listings.pcisecuritystandards.org/documents/PCI-DSS-v4-0-SAQ-D-Merchant.pdf"],
                         "2026-11-22")

    def test_the_pci_dss_proposal_says_the_questionnaire_depends_on_the_integration(self):
        questions = {question["id"]: question for question in init_questions(self.catalog, "Shop")}
        norm = next(norm for norm in questions["norms"]["norms"] if norm["id"] == "pci-dss-cardholder-data")
        self.assertIn("self-assessment questionnaire", norm["help"])
        self.assertIn("depends on the payment integration", norm["help"])
        self.assertIn("https://listings.pcisecuritystandards.org/documents/PCI-DSS-v4-0-SAQ-A.pdf",
                      [source["url"] for source in norm["sources"]])

    def test_iso_27001_names_the_development_controls_and_only_controls_of_annex_a(self):
        rules = self.catalog["packs"]["iso-27001"]["rules"]
        text = " ".join(rule["instruction"] for rule in rules)
        for control in ("8.25", "8.28", "8.29", "8.31", "8.32", "8.33"):
            self.assertRegex(text, rf"\b{re.escape(control)}\b")
        # ISO/IEC 27001:2022 Annex A takes the 93 controls of ISO/IEC 27002:2022: 37 organizational (5.x), 8 people
        # (6.x), 14 physical (7.x) and 34 technological (8.x), as the ISO/IEC JTC 1/SC 27 Journal of July 2022 says.
        annex_a = {f"{clause}.{number}" for clause, count in ((5, 37), (6, 8), (7, 14), (8, 34))
                   for number in range(1, count + 1)}
        self.assertEqual(len(annex_a), 93)
        cited = {(rule["id"], control) for rule in rules if "Annex A" in rule["instruction"]
                 for control in re.findall(r"(?<![\d.])(\d+\.\d+)(?![\d])", rule["instruction"])}
        self.assertGreater(len(cited), 20)
        for rule_id, control in sorted(cited):
            with self.subTest(rule=rule_id, control=control):
                self.assertIn(control, annex_a)

    def test_pci_dss_is_proposed_for_a_payment_stack_and_never_imposed(self):
        with_cards = profile_recommendations({"stack": ["Python", "Stripe"]}, self.catalog)
        self.assertIn("pci-dss-cardholder-data", {entry["id"] for entry in with_cards["matched"]})
        without = profile_recommendations({"stack": ["Python"], "sector": "financial-services"}, self.catalog)
        self.assertNotIn("pci-dss-cardholder-data", {entry["id"] for entry in without["matched"]})
        security = profile_recommendations({"stack": ["Python"], "roles": ["security"]}, self.catalog)
        self.assertIn("pci-dss-cardholder-data", {entry["id"] for entry in security["suggested"]})
        chosen = validate_profile({"name": "Shop", "stack": ["Python"], "patterns": ["pci-dss-cardholder-data"]},
                                  self.catalog)
        self.assertIn("pci-dss", resolved_profile(chosen, self.catalog)["packs"])
        declined = validate_profile({"name": "Shop", "stack": ["Stripe"], "declined": ["pci-dss-cardholder-data"]},
                                    self.catalog)
        self.assertNotIn("pci-dss", resolved_profile(declined, self.catalog)["packs"])

    def test_iso_27001_maps_each_kind_of_change_to_annex_a_controls(self):
        rules = {rule["id"]: rule for rule in self.catalog["packs"]["iso-27001"]["rules"]}
        expected = {
            "annex-a-access-control": "8.5", "annex-a-cryptography": "8.24", "annex-a-logging-monitoring": "8.15",
            "annex-a-suppliers": "5.19", "annex-a-secure-development": "8.4", "annex-a-networks": "8.20",
            "annex-a-incident-handling": "5.26", "annex-a-assets": "5.9",
        }
        for rule_id, control in expected.items():
            with self.subTest(rule=rule_id):
                self.assertIn("ISO/IEC 27001:2022 Annex A", rules[rule_id]["instruction"])
                self.assertRegex(rules[rule_id]["instruction"], rf"\b{re.escape(control)}\b")
        self.assertEqual(rules["map-applicable-controls"]["evidence"][0]["id"], "statement-of-applicability")

    def test_regulation_packs_name_their_evidence_and_checks(self):
        packs = self.catalog["packs"]
        evidence = {pack_id: {item["id"] for rule in packs[pack_id]["rules"] for item in rule.get("evidence", [])}
                    for pack_id in ("gdpr", "dora")}
        self.assertEqual(evidence["gdpr"], {"processing-record", "dpia-decision"})
        for rule in packs["gdpr"]["rules"]:
            for item in rule.get("evidence", []):
                self.assertEqual(item["when"], {"data": ["personal", "regulated", "unsure"]}, item["id"])
        self.assertIn("register-of-information", evidence["dora"])
        for pack_id in ("nis2", "cyber-resilience-act"):
            checks = [rule["check"] for rule in packs[pack_id]["rules"] if "check" in rule]
            self.assertIn({"kind": "file-exists", "paths": ["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"]},
                          checks, pack_id)

    def test_financial_services_has_dora_and_gdpr_by_default_unless_declined(self):
        default = validate_profile({"name": "Ledger", "sector": "financial-services"}, self.catalog)
        self.assertLessEqual({"dora", "gdpr"}, set(resolved_profile(default, self.catalog)["packs"]))
        no_data = validate_profile({"name": "Ledger", "sector": "financial-services", "personal_data": "no"},
                                   self.catalog)
        self.assertNotIn("gdpr", resolved_profile(no_data, self.catalog)["packs"])
        with tempfile.TemporaryDirectory() as directory:
            # A norm is active only once a person accepts it (#153): init stops until each one is answered.
            write_json(Path(directory) / "answers.json", {"personal_data": True, "name": "Ledger", "sector": "financial-services"})
            errors = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                self.assertEqual(main(["--project", directory, "init", "--answers", f"{directory}/answers.json"]), 1)
            self.assertIn("dora-financial-entity", errors.getvalue())
            write_json(Path(directory) / "answers.json", {"personal_data": True, "name": "Ledger", "sector": "financial-services", "norms": {
                "dora-financial-entity": "yes", "gdpr-personal-data": "yes", "european-accessibility-act": "yes"}})
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--project", directory, "init", "--answers", f"{directory}/answers.json"]), 0)
            created = json.loads((Path(directory) / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
            self.assertLessEqual({"dora", "gdpr"}, set(resolved_profile(created, self.catalog)["packs"]))
        declined = validate_profile({"name": "Ledger", "sector": "financial-services",
                                     "declined": ["gdpr-personal-data", "dora-financial-entity"]}, self.catalog)
        self.assertFalse({"dora", "gdpr"} & set(resolved_profile(declined, self.catalog)["packs"]))


if __name__ == "__main__":
    unittest.main()
