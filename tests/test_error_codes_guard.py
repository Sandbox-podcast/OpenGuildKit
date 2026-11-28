"""Stable error codes of the guard, the portal check, the shares and the documentation commands (#487): the refusals
no other test meets, each provoked by the command a person runs, or by calling the function with the input a person,
an agent or a portal could give."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import allowlist, guard, guard_ci, guard_export, portal_verification, publishing, sensitive
from openguildkit.errors import OgkError
from tests.support import run_cli


class CodedCase(unittest.TestCase):
    def assertCodes(self, cases):
        for code, call in cases:
            with self.subTest(code=code), self.assertRaises(OgkError) as raised:
                call()
            self.assertEqual(raised.exception.code, code, raised.exception)

    def assertCaught(self, code, errors):
        """The function turns the error into a line it reports; the error it caught carries the code."""
        self.assertEqual([getattr(error, "code", None) for error in errors], [code], errors)

    def folder(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name).resolve()


class GuardCodeTests(CodedCase):
    """Issue #487: a hook input, a Git listing, an exported withdrawal, an allow list or a citation without a code."""

    def test_issue_487_a_refused_guard_input_has_its_code(self):
        """Issue #487: _git_lines, export_withdrawal, load_allow and public_evidence_url."""
        root = self.folder()
        record = root / "decision.json"
        record.write_text(json.dumps({"decision": {"seal": "a later approval"}}), encoding="utf-8")
        task = {"id": "t1", "rounds": [{"decision": {"seal": "the withdrawn approval"},
                                        "revoked": {"by": "CM", "reason": "Scope changed.", "at": "2026-11-28"}}]}
        allow = root / "allow.json"
        allow.write_text(json.dumps({"mcp_servers": [{"server": "npx one", "name": "docs"},
                                                     {"server": "npx two", "name": "docs"}]}), encoding="utf-8")
        with patch.object(guard_export, "_refuse_foreign_record"), patch.object(guard_export, "record_shape"):
            self.assertCodes([
                ("OGK-GUARD-020", lambda: guard_ci._git_lines(root, "ls-files")),
                ("OGK-GUARD-021", lambda: guard_export.export_withdrawal(root, root, task, record)),
                ("OGK-GUARD-022", lambda: allowlist.load_allow(allow)),
                ("OGK-GUARD-023", lambda: sensitive.public_evidence_url("http://example.org/a", "evidence[0].ref")),
            ])

    def test_issue_487_a_hook_input_that_could_not_be_read_has_its_code(self):
        """Issue #487: _decide_hook when standard input could not be read reports the error it caught."""
        root = self.folder()
        caught = []
        real = guard._one_line

        def one_line(error):
            caught.append(error)
            return real(error)

        with patch.object(guard, "declared_mode", return_value="enforce"), patch.object(guard, "_one_line", one_line):
            guard._decide_hook("pre-edit", None, root, lambda: (root, root, {"guard": "enforce"}, {}))
        self.assertCaught("OGK-GUARD-019", caught)


class PortalCodeTests(CodedCase):
    """Issue #487: an answer of a Documentalist instance refused without a code."""

    class Answer:
        def __init__(self, content: bytes):
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size):
            return self.content[:size]

        def open(self, *_request, **_timeout):  # The opener answers with itself.
            return self

    def opener(self, content: bytes):
        return self.Answer(content)

    def test_issue_487_an_answer_too_large_or_not_an_object_has_its_code(self):
        """Issue #487: _json reads at most 2 MB, and only an object."""
        origin = "https://docs.example.test"
        self.assertCodes([
            ("OGK-PORTAL-005", lambda: portal_verification._json(self.opener(b" " * 2_000_001), origin, "/api")),
            ("OGK-PORTAL-006", lambda: portal_verification._json(self.opener(b"[]"), origin, "/api")),
        ])

    def test_issue_487_an_instance_without_the_space_or_its_lists_has_its_code(self):
        """Issue #487: verify_portal reports the error it caught as the problem of the check."""
        portal = "https://docs.example.test/p/demo"
        space = portal_verification._origin(portal)[1]
        answers = {
            "OGK-PORTAL-007": [{}, {"spaces": None}],
            "OGK-PORTAL-008": [{}, {"spaces": [{"id": "spc_2", "slug": "other"}]}],
            "OGK-PORTAL-009": [{}, {"spaces": [{"id": "spc_1", "slug": "demo"}]}, {"emails": None}],
        }
        caught = []

        def reason(error, *_where):
            caught.append(error)
            return str(error)

        for code, replies in answers.items():
            with self.subTest(code=code):
                state = self.folder()
                caught.clear()
                with patch.object(portal_verification, "load_shares", return_value=[{"space": space}]), \
                        patch.object(portal_verification, "interactive", return_value=True), \
                        patch("getpass.getpass", return_value="test-password"), \
                        patch.object(portal_verification, "_rows", return_value=[]), \
                        patch.object(portal_verification, "_reason", reason), \
                        patch.object(portal_verification, "_json", side_effect=[*replies, {}]):
                    report = portal_verification.verify_portal(state, portal, "editor@example.test")
                self.assertCaught(code, caught)
                self.assertEqual(report["source"], "local-register")


class PublishCodeTests(CodedCase):
    """Issue #487: an export or a share refused without a code."""

    def test_issue_487_a_refused_export_or_share_has_its_code(self):
        """Issue #487: export_docs, add_share and revoke_share."""
        state = self.folder()
        self.assertCodes([
            ("OGK-PUBLISH-016", lambda: publishing.export_docs(state, [], state / "site", "1.0.0", sections=())),
            ("OGK-PUBLISH-017", lambda: publishing.add_share(state, " ", [], "", "", "CM")),
            ("OGK-PUBLISH-019", lambda: publishing.revoke_share(state, "no-such-share", "CM")),
        ])


class DocsCodeTests(CodedCase):
    """Issue #487: deliverable check, docs share and references print the code of their refusals."""

    def test_issue_487_the_documentation_commands_print_their_codes(self):
        """Issue #487: a file that is not a draft, missing share options, and a search without a word."""
        root = self.folder()
        (root / "profile.json").write_text(json.dumps({"personal_data": "no", "name": "Portal", "stack": ["Python"],
                                                       "packs": [], "checks": []}), encoding="utf-8")
        run_cli(root, "init", "--answers", root / "profile.json")
        (root / "plain.md").write_text("# Plain\n", encoding="utf-8")
        for code, arguments in (("OGK-DOCS-026", ("deliverable", "check", "plain.md")),
                                ("OGK-DOCS-027", ("docs", "share", "add", "--deliverable", "plain.md")),
                                ("OGK-DOCS-028", ("docs", "share", "revoke", "--id", "s1")),
                                ("OGK-DOCS-029", ("references", "--id", "owasp", "access")),
                                ("OGK-DOCS-030", ("references", " ,, "))):
            with self.subTest(code=code):
                error = run_cli(root, *arguments, expect=1).stderr
                self.assertTrue(error.splitlines()[-1].startswith(f"OpenGuildKit [{code}]: "), error)


if __name__ == "__main__":
    unittest.main()
