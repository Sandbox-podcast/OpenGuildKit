"""Machine checks and named evidence declared by pack rules; tests/test_regulation_checks.py holds the regulation packs
that use them."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import CatalogError, load_catalog, validate_entry
from openguildkit.rule_checks import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_SIZE_BYTES,
    describe_check,
    evaluate_check,
    validate_check,
)
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

    def test_each_asks_every_matched_file_to_hold_one_of_the_texts(self):
        # OGK-RULE-010
        self.write(".github/workflows/a.yml", "permissions: write-all\n")
        self.write(".github/workflows/b.yml", "on: push\n")
        anywhere = {"kind": "text", "paths": [".github/workflows/*.yml"], "contains": ["permissions:"],
                    "expect": "present"}
        self.assertEqual(evaluate_check(self.root, anywhere)["status"], "passed")
        each = {**anywhere, "each": True}
        validate_check(each, "check", allow_command=False)
        outcome = evaluate_check(self.root, each)
        self.assertEqual(outcome["status"], "failed")
        self.assertIn(".github/workflows/b.yml", outcome["evidence"])
        self.assertNotIn("a.yml", outcome["evidence"])
        self.write(".github/workflows/b.yml", "permissions:\n  contents: read\n")
        outcome = evaluate_check(self.root, each)
        self.assertEqual(outcome["status"], "passed", outcome)
        self.assertIn("each", outcome["evidence"])
        self.assertEqual(evaluate_check(self.root, {**each, "paths": ["missing/*.yml"]})["status"], "failed")
        for refused in ({**each, "each": False}, {**each, "expect": "absent"}):
            with self.subTest(check=refused), self.assertRaisesRegex(ValueError, "each"):
                validate_check(refused, "check", allow_command=False)

    def test_the_workflow_permission_rules_fail_without_a_declaration_and_on_write_all(self):
        rules = {rule["id"]: rule["check"] for rule in load_catalog()["packs"]["github-actions-security"]["rules"]
                 if "check" in rule}
        self.write(".github/workflows/a.yml", "permissions: write-all\n")
        self.write(".github/workflows/b.yml", "on: push\n")
        outcomes = {rule: evaluate_check(self.root, check)["status"] for rule, check in rules.items()}
        self.assertEqual(outcomes, {"declare-workflow-permissions": "failed", "refuse-write-all-permissions": "failed"})
        self.write(".github/workflows/a.yml", "permissions:\n  contents: read\n")
        self.assertEqual(evaluate_check(self.root, rules["declare-workflow-permissions"])["status"], "failed")
        self.write(".github/workflows/b.yml", "permissions:\n  contents: read\n")
        outcomes = {rule: evaluate_check(self.root, check)["status"] for rule, check in rules.items()}
        self.assertEqual(set(outcomes.values()), {"passed"})

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
        # OGK-RULE-006
        for path in ("../secret.json", "/etc/passwd.json", "C:/x.json", "a/./b.json", "a\\b.json", "a//b.json", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_check({"kind": "field", "path": path, "field": "a", "equals": 1}, "check", allow_command=False)
        with self.assertRaisesRegex(ValueError, "wildcards"):
            validate_check({"kind": "field", "path": "*.json", "field": "a", "equals": 1}, "check", allow_command=False)

    def test_a_check_cannot_name_a_path_inside_git_or_the_project_state(self):
        # OGK-RULE-007
        for check in (
            {"kind": "text", "paths": [".git/config"], "contains": ["tok"], "expect": "present"},
            {"kind": "text", "paths": ["*.md", "vendor/.GIT/config"], "contains": ["tok"], "expect": "absent"},
            {"kind": "file-exists", "paths": [".git/config"]},
            {"kind": "file-exists", "paths": [".openguildkit/project.json"]},
            {"kind": "field", "path": ".openguildkit/project.json", "field": "name", "equals": "x"},
        ):
            with self.subTest(check=check), self.assertRaisesRegex(ValueError, "not searched"):
                validate_check(check, "check", allow_command=False)
        for path in (".github/workflows/ci.yml", ".gitignore", ".gitattributes", "docs/.git-notes.md"):
            with self.subTest(path=path):
                validate_check({"kind": "file-exists", "paths": [path]}, "check", allow_command=False)
        leak = pack([{"id": "leak", "check": {"kind": "text", "paths": [".git/config"], "contains": ["tok"],
                                               "expect": "present"}}])
        with self.assertRaisesRegex(CatalogError, "not searched"):
            validate_entry("packs", leak)

    @unittest.skipIf(os.name == "nt", "Creating a symbolic link needs a privilege Windows does not grant by default.")
    def test_a_link_that_leaves_the_project_is_not_read(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "SECURITY.md").write_text("outside", encoding="utf-8")
        (self.root / "SECURITY.md").symlink_to(Path(outside.name, "SECURITY.md"))
        self.assertEqual(evaluate_check(self.root, {"kind": "file-exists", "paths": ["SECURITY.md"]})["status"], "failed")

    def test_the_work_is_bounded(self):
        # OGK-RULE-009
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


class SizeCheckTests(unittest.TestCase):
    """The size kind bounds the bytes of the files its paths name, without reading them."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, size):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    def check(self, **fields):
        return {"kind": "size", "paths": ["AGENTS.md"], "max_bytes": 100, **fields}

    def test_a_valid_size_check_is_accepted(self):
        validate_check(self.check(), "check", allow_command=False)
        validate_check(self.check(paths=["docs/**/*.md", "CLAUDE.md"], max_bytes=MAX_SIZE_BYTES), "check",
                       allow_command=False)

    def test_fields_are_required_and_nothing_else_is_accepted(self):
        # OGK-RULE-002, OGK-RULE-003
        for fields, message in (({"paths": None}, "missing fields: paths"), ({"max_bytes": None}, "missing fields: max_bytes"),
                                ({"contains": ["x"]}, "unknown fields: contains"), ({"max": 5}, "unknown fields: max")):
            check = {key: value for key, value in self.check(**fields).items() if value is not None}
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, message):
                validate_check(check, "check", allow_command=False)

    def test_max_bytes_is_a_whole_positive_number_below_the_limit(self):
        # OGK-RULE-011
        for value in (0, -1, True, False, 1.5, 100.0, "100", None, [100], MAX_SIZE_BYTES + 1):
            with self.subTest(max_bytes=value), self.assertRaisesRegex(ValueError, "max_bytes"):
                validate_check(self.check(max_bytes=value), "check", allow_command=False)

    def test_paths_are_relative_to_the_project_and_limited_in_number(self):
        # OGK-RULE-004, OGK-RULE-005, OGK-RULE-008
        for paths in (["../AGENTS.md"], ["/etc/passwd"], ["a/./b"], ["a//b"], [""], [], "AGENTS.md",
                      [f"f{index}.md" for index in range(21)]):
            with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, "paths"):
                validate_check(self.check(paths=paths), "check", allow_command=False)

    def test_a_file_at_or_below_the_limit_passes_and_a_file_above_it_fails(self):
        for size, status in ((99, "passed"), (100, "passed"), (101, "failed")):
            with self.subTest(size=size):
                self.write("AGENTS.md", size)
                outcome = evaluate_check(self.root, self.check())
                self.assertEqual(outcome["status"], status)
                self.assertIn(f"AGENTS.md is {size} bytes", outcome["evidence"])

    def test_the_evidence_names_the_largest_file_and_every_file_above_the_limit(self):
        self.write("docs/a.md", 50)
        self.write("docs/b.md", 130)
        self.write("docs/c.md", 120)
        self.write("docs/d.md", 90)
        passed = evaluate_check(self.root, self.check(paths=["docs/a.md", "docs/d.md"]))
        self.assertEqual(passed["status"], "passed")
        self.assertIn("docs/d.md is 90 bytes", passed["evidence"])
        failed = evaluate_check(self.root, self.check(paths=["docs/*.md"]))
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(failed["evidence"].startswith("docs/b.md is 130 bytes"), failed["evidence"])
        self.assertIn("docs/c.md is 120 bytes", failed["evidence"])
        self.assertNotIn("docs/d.md", failed["evidence"])
        self.assertIn("above 100", failed["evidence"])

    def test_wildcards_match_files_at_any_depth_like_the_other_kinds(self):
        self.write("a/b/deep.md", 150)
        self.write("top.md", 10)
        self.assertEqual(evaluate_check(self.root, self.check(paths=["*.md"]))["status"], "passed")
        self.assertEqual(evaluate_check(self.root, self.check(paths=["**/*.md"]))["status"], "failed")
        self.assertEqual(evaluate_check(self.root, self.check(paths=["a/?/deep.md"]))["status"], "failed")

    def test_no_matching_file_passes_because_nothing_is_above_the_limit(self):
        outcome = evaluate_check(self.root, self.check(paths=["AGENTS.md", "docs/*.md"]))
        self.assertEqual(outcome["status"], "passed")
        self.assertIn("No file matches AGENTS.md, docs/*.md", outcome["evidence"])
        self.write("docs/folder.md/inner.txt", 500)
        self.assertEqual(evaluate_check(self.root, self.check(paths=["docs/*.md"]))["status"], "passed")

    def test_a_directory_is_not_measured_and_the_folders_of_the_kit_are_not_searched(self):
        self.write(".openguildkit/big.md", 500)
        self.write(".git/big.md", 500)
        self.assertEqual(evaluate_check(self.root, self.check(paths=["**/*.md"]))["status"], "passed")

    def test_a_file_is_measured_without_being_read(self):
        # The file read limit does not apply: its bytes are never read, only counted.
        self.write("bundle.js", MAX_FILE_BYTES + 1)
        outcome = evaluate_check(self.root, self.check(paths=["bundle.js"], max_bytes=MAX_FILE_BYTES + 10))
        self.assertEqual(outcome["status"], "passed")
        self.assertIn(f"bundle.js is {MAX_FILE_BYTES + 1} bytes", outcome["evidence"])
        with patch.object(Path, "read_bytes", side_effect=AssertionError("read")):
            self.assertEqual(evaluate_check(self.root, self.check(paths=["bundle.js"]))["status"], "failed")

    def test_the_number_of_files_is_bounded(self):
        for index in range(MAX_FILES + 1):
            self.write(f"many/{index}.txt", 1)
        outcome = evaluate_check(self.root, self.check(paths=["many/*.txt"]))
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("narrow", outcome["evidence"])

    @unittest.skipIf(os.name == "nt", "Creating a symbolic link needs a privilege Windows does not grant by default.")
    def test_a_link_that_leaves_the_project_is_not_measured(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "AGENTS.md").write_bytes(b"x" * 500)
        (self.root / "AGENTS.md").symlink_to(Path(outside.name, "AGENTS.md"))
        outcome = evaluate_check(self.root, self.check())
        self.assertEqual(outcome["status"], "passed")
        self.assertIn("No file matches", outcome["evidence"])

    def test_the_derived_instruction_says_the_limit(self):
        self.assertEqual(describe_check(self.check(paths=["AGENTS.md", "docs/*.md"], max_bytes=8000)),
                         "Each file matching `AGENTS.md`, `docs/*.md` is at most 8000 bytes.")

    def test_a_pack_rule_can_declare_the_check_and_the_catalog_refuses_a_malformed_one(self):
        # OGK-CATALOG-033
        rule = {"id": "small-instructions", "check": self.check(max_bytes=8000)}
        validate_entry("packs", pack([rule]))
        with self.assertRaisesRegex(CatalogError, "max_bytes"):
            validate_entry("packs", pack([{"id": "small-instructions", "check": self.check(max_bytes=0)}]))


class CatalogFormatTests(unittest.TestCase):
    def test_a_bundled_pack_cannot_run_a_command(self):
        # OGK-RULE-014
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
        # OGK-CATALOG-030, OGK-CATALOG-034, OGK-RULE-013
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
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], "packs": ["team-rules"],
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

    def test_task_verify_measures_the_size_of_a_file_a_rule_bounds(self):
        self.approved([{"id": "short-notes", "check": {"kind": "size", "paths": ["notes.md"], "max_bytes": 100}}])
        self.assertIn("rule:team-rules/short-notes: passed\n    No file matches notes.md",
                      self.run_cli("task", "verify", TASK)[0])
        (self.root / "notes.md").write_text("x" * 150, encoding="utf-8")
        self.assertIn("rule:team-rules/short-notes: failed\n    notes.md is 150 bytes, above 100.",
                      self.run_cli("task", "verify", TASK)[0])
        self.assertIn("- short-notes: Each file matching `notes.md` is at most 100 bytes.",
                      self.run_cli("task", "brief", TASK, "--pack", "team-rules")[0])
        self.assertIn("`short-notes`", (self.root / "AGENTS.md").read_text(encoding="utf-8"))

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
        # OGK-RESULT-021
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
        # OGK-CATALOG-007, OGK-CATALOG-029
        bad = {**self.RECORD, "evidence": [{**self.RECORD["evidence"][0], "when": {"data": ["secret"]}}]}
        with self.assertRaisesRegex(CatalogError, "when.data"):
            validate_entry("packs", pack([bad]))
        with self.assertRaisesRegex(CatalogError, "when"):
            validate_entry("packs", pack([{**self.RECORD, "evidence": [{**self.RECORD["evidence"][0], "when": {}}]}]))

    def test_a_named_evidence_can_be_an_https_link_and_appears_in_the_pack_brief(self):
        self.approved([{"id": "assess-dpia", "instruction": "Ask about the assessment.", "verification": "Link it.",
                        "evidence": [{"id": "dpia-decision", "title": "Decision on the impact assessment"}]}])
        brief = self.run_cli("task", "brief", TASK, "--pack", "team-rules")[0]
        self.assertIn("Evidence for task result: Decision on the impact assessment", brief)
        self.assertNotIn("Evidence for task result", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.report({"check": "rule:team-rules/assess-dpia", "status": "passed", "evidence": "Asked."},
                    {"check": "evidence:team-rules/assess-dpia/dpia-decision", "status": "passed",
                     "evidence": "https://wiki.example.test/privacy/dpia-42", "owner": "Dana"})
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")


if __name__ == "__main__":
    unittest.main()
