"""Stable error codes of the organization catalog and the project files (#487): the refusals no other test meets,
each provoked by the command a person runs, or by calling the function with a file a person could write."""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit import org_catalog, org_policy, project_instructions, project_mcp, project_setup, projects_cli
from openguildkit.errors import OgkError
from tests import test_org_catalog
from tests.support import run_cli


class CodedCase(unittest.TestCase):
    def assertCodes(self, cases):
        for code, call in cases:
            with self.subTest(code=code), self.assertRaises(OgkError) as raised:
                call()
            self.assertEqual(raised.exception.code, code, raised.exception)

    def refused(self, root, code, *arguments, typed=None):
        error = run_cli(root, *arguments, expect=1, typed=typed).stderr
        self.assertTrue(error.splitlines()[-1].startswith(f"OpenGuildKit [{code}]: "), error)

    def folder(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()


class OrgCodeTests(CodedCase):
    """Issue #487: an organization catalog, its pin, its history or its policy refused without a code."""

    # The project and the organization copy of the organization catalog tests, without their test methods.
    setUp = test_org_catalog.OrgCatalogTests.setUp
    commit = test_org_catalog.OrgCatalogTests.commit
    cli = test_org_catalog.OrgCatalogTests.cli
    pin = test_org_catalog.OrgCatalogTests.pin

    def test_issue_487_a_refused_copy_pin_history_or_policy_has_its_code(self):
        """Issue #487: _listed_files, _contents, validate_pin, validate_history, parse and given."""
        unknown = "0" * 40
        self.assertCodes([
            ("OGK-ORG-013", lambda: org_catalog._listed_files(self.org, unknown)),
            ("OGK-ORG-014", lambda: org_catalog._contents(self.folder(), [unknown])),
            ("OGK-ORG-015", lambda: org_catalog.validate_pin({}, "catalog.lock.json")),
            ("OGK-ORG-016", lambda: org_catalog.validate_history({}, "catalog.lock.json")),
            ("OGK-ORG-021", lambda: org_policy.parse(b"{not json", unknown)),
            ("OGK-ORG-022", lambda: org_policy.given(str(self.org), self.first, self.root)),
        ])

    def test_issue_487_org_catalog_set_and_accept_print_their_codes(self):
        """Issue #487: a blank --by, --by without --reason, no organization pinned, and a record not replaced."""
        self.refused(self.root, "OGK-ORG-017", "org-catalog", "accept", "packs/org-review", "--by", " ",
                     "--reason", "Kept.")
        self.refused(self.root, "OGK-ORG-018", "org-catalog", "set", "--repo", self.org, "--commit", self.first,
                     "--by", "Camille Martin")
        self.refused(self.root, "OGK-ORG-019", "org-catalog", "accept", "packs/org-review", "--by", "CM",
                     "--reason", "Kept.")
        self.pin(self.first)
        self.refused(self.root, "OGK-ORG-020", "org-catalog", "accept", "packs/org-review", "--by", "CM",
                     "--reason", "Kept.")


class ProjectCodeTests(CodedCase):
    """Issue #487: project instructions, metadata, setup answers or a projects policy refused without a code."""

    def test_issue_487_a_refused_project_file_has_its_code(self):
        """Issue #487: merged_instructions, initialize, _project, complete_answers and read_policy.

        A policy that is not an object stops at OGK-PROJECT-042, in read_json."""
        state = self.folder()
        (state / "project.json").write_text("{}", encoding="utf-8")
        collection = next(iter(project_mcp.COLLECTION_FIELDS))
        (state / "catalog" / collection / "entry.json").mkdir(parents=True)
        policies = self.folder()
        for name, policy in (("approvals", {"approvals": "spoken"}),
                             ("requester", {"separate_requester": False})):
            (policies / f"{name}.json").write_text(json.dumps(policy), encoding="utf-8")
        self.assertCodes([
            ("OGK-PROJECT-078", lambda: project_instructions.merged_instructions("", project_instructions.BEGIN)),
            ("OGK-PROJECT-079", lambda: project_instructions.initialize(state.parent, state, {}, {})),
            ("OGK-PROJECT-080", lambda: project_mcp._project(state)),
            ("OGK-PROJECT-081", lambda: project_setup.complete_answers([], [], {})),
            ("OGK-PROJECT-084", lambda: projects_cli.read_policy(policies / "approvals.json")),
            ("OGK-PROJECT-085", lambda: projects_cli.read_policy(policies / "requester.json")),
        ])

    def test_issue_487_projects_search_with_blank_text_prints_its_code(self):
        """Issue #487: openguildkit projects --search with only spaces."""
        root = self.folder()
        self.refused(root, "OGK-PROJECT-082", "projects", root, "--search", " ")


if __name__ == "__main__":
    unittest.main()
