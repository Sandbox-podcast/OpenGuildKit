"""Stable error codes of the smaller areas (#487): alerts, audit, catalog, check, CI, core, evidence, features, init,
market, profile, rules and stories. Each refusal no other test meets is provoked by the command a person runs, or by
calling the function with the input a person or an agent could write."""

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from openguildkit import (
    catalog_cli,
    ci,
    evidence_cli,
    features_cli,
    integrations,
    profile_changes,
    project_rules,
    sarif,
    storage,
    storybook_stories,
    trace_cli,
)
from openguildkit.catalog import load_catalog
from openguildkit.errors import OgkError
from openguildkit.project import load_profile
from openguildkit.storage import read_json
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]


class CodedCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "profile.json").write_text(json.dumps({"personal_data": "no", "name": "Portal",
                                                            "stack": ["Python"], "packs": [], "checks": []}),
                                                encoding="utf-8")
        run_cli(self.root, "init", "--answers", self.root / "profile.json")
        self.state = self.root / ".openguildkit"

    def assertCodes(self, cases):
        for code, call in cases:
            with self.subTest(code=code), self.assertRaises(OgkError) as raised:
                call()
            self.assertEqual(raised.exception.code, code, raised.exception)

    def refused(self, code, *arguments):
        error = run_cli(self.root, *arguments, expect=1).stderr
        self.assertTrue(error.splitlines()[-1].startswith(f"OpenGuildKit [{code}]: "), error)


class CommandCodeTests(CodedCase):
    """Issue #487: the commands of the smaller areas print the code of each refusal."""

    def test_issue_487_each_refused_option_prints_its_code(self):
        """Issue #487: task alerts, audit, market, evidence, host managed and mcp."""
        run_cli(self.root, "task", "new", "--file", REPO / "examples" / "request-status" / "brief.md", "--id", "t1")
        (self.root / "dossier").mkdir()
        (self.root / "dossier" / evidence_cli.MANIFEST).write_text("{}", encoding="utf-8")
        for code, arguments in (
            ("OGK-ALERTS-018", ("task", "alerts", "t1", "--set", "A1")),
            ("OGK-AUDIT-007", ("audit", "export", "audit.log")),
            ("OGK-AUDIT-008", ("audit", "verify", "--since", "2026-01-01")),
            ("OGK-MARKET-035", ("market", "due")),
            ("OGK-MARKET-036", ("market", "check")),
            ("OGK-EVIDENCE-004", ("evidence", "export", "--output", "out", "--since", "2026-02-01",
                                  "--until", "2026-01-01")),
            ("OGK-EVIDENCE-006", ("evidence", "verify", "dossier")),
            ("OGK-CORE-023", ("host", "managed", "--host", "codex", "--os", "macos", "--block-on-failure")),
            ("OGK-INIT-006", ("mcp", "--policy-repo", "central")),
        ):
            with self.subTest(code=code):
                self.refused(code, *arguments)


class FunctionCodeTests(CodedCase):
    """Issue #487: the refusals built by functions of the smaller areas, called with what a person could give."""

    def test_issue_487_a_refused_finding_path_rule_role_or_component_has_its_code(self):
        """Issue #487: project_file, print_patterns, _clean_path, _rule, to_sarif, task_scope_profile."""
        catalog = load_catalog()
        profile = load_profile(self.state, catalog)
        rule = {"name": "Rule", "description": "A rule.", "help": "checks.md"}
        self.assertCodes([
            ("OGK-AUDIT-009", lambda: trace_cli.project_file(self.root, self.root)),
            ("OGK-CATALOG-110", lambda: catalog_cli.print_patterns(Namespace(role="no-such-role"), {})),
            ("OGK-CHECK-016", lambda: sarif._clean_path(".")),
            ("OGK-CHECK-017", lambda: sarif._rule("OGK-RULE", rule)),
            ("OGK-CHECK-018", lambda: sarif.to_sarif([], rules={}, tool_version=" ")),
            ("OGK-RULE-028", lambda: project_rules.task_scope_profile(profile, catalog, ["no-such-component"])),
        ])

    def test_issue_487_a_refused_install_lock_or_export_check_has_its_code(self):
        """Issue #487: check_export, install_agent_files and project_lock."""
        target = self.root / next(iter(integrations.HOST_FILES["claude-code"].values()))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(self.root / "elsewhere.md")
        locked = self.root / "locked"
        locked.mkdir()
        (locked / ".lock").symlink_to(self.root / "elsewhere.lock")

        def lock():
            with storage.project_lock(locked):
                pass

        with patch.object(ci, "resolved_profile", return_value={"packs": [ci.EXPORT_EXPIRY_ID]}):
            self.assertCodes([
                ("OGK-CI-006", lambda: ci.check_export({}, {"packs": {ci.EXPORT_EXPIRY_ID: {}}}, self.root, "HEAD")),
                ("OGK-CI-007", lambda: integrations.install_agent_files(self.root, "no-such-host")),
                ("OGK-CI-008", lambda: integrations.install_agent_files(self.root, "claude-code")),
                ("OGK-CORE-024", lock),
            ])

    def test_issue_487_a_refused_feature_profile_edit_or_story_has_its_code(self):
        """Issue #487: _refuse, save_edited of the profile unchanged, and generate with two components of one name."""
        edited = read_json(self.state / "project.json")
        proposals = self.root / "proposals.json"
        components = [{"key": "src/Card.tsx:Card", "status": "validated", "name": "Card"},
                      {"key": "src/card.tsx:card", "status": "validated", "name": "card"}]
        proposals.write_text(json.dumps({"schema_version": 1, "components": components, "variants": [],
                                         "tokens": []}), encoding="utf-8")
        self.assertCodes([
            ("OGK-FEATURE-012", lambda: features_cli._refuse("features off review", [], [])),
            ("OGK-PROFILE-036", lambda: profile_changes.save_edited(self.root, self.state, edited, "CM", "Saved.")),
            ("OGK-STORY-037", lambda: storybook_stories.generate(self.root, self.state, proposals,
                                                                 framework="react")),
        ])
        self.assertFalse((self.root / "src").exists())

    def test_issue_487_a_record_without_an_approval_payload_says_so(self):
        """Issue #487: _signature reports the error it caught as the detail of the signature."""
        built = []

        class Recorded(OgkError):
            def __init__(self, code, message):
                built.append(code)
                super().__init__(code, message)

        decision = {"signature": "c2lnbmVk", "signer": "CM", "payload": None}
        with patch.object(evidence_cli, "OgkError", Recorded):
            answer = evidence_cli._signature(self.root, {"mode": "signed"}, decision)
        self.assertEqual(built, ["OGK-EVIDENCE-005"])
        self.assertEqual(answer["detail"], "the record carries no approval payload")


if __name__ == "__main__":
    unittest.main()
