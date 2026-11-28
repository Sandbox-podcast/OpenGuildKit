"""Stable error codes of the web interface (#487): each refusal of the local server carries its OGK-WEB code in the
JSON answer, next to its message, its command and its reason."""

import contextlib
import gzip
import io
import json
import shutil
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

from openguildkit import web_requests
from openguildkit.storage import project_lock
from openguildkit.web_requests import Refused
from tests import test_webui


class WebRefusalCodeTests(unittest.TestCase):
    """Issue #487: a refusal of the page was told apart by its English text and its reason, never by a code."""

    # The server of the web tests, without their test methods (a class imported here would run them twice).
    setUp = test_webui.WebInterfaceTests.setUp
    request = test_webui.WebInterfaceTests.request

    def answer(self, path, body=None, headers=None, method=None):
        status, _, raw = self.request(path, body, headers, method)
        return status, json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)

    def assertRefused(self, cases):
        for code, path, body, headers, method in cases:
            with self.subTest(code=code, path=path, body=body):
                status, answer = self.answer(path, body, headers, method)
                self.assertGreaterEqual(status, 400, answer)
                self.assertEqual(answer.get("code"), code, answer)

    def test_issue_487_a_refusal_answers_its_code_next_to_its_message_command_and_reason(self):
        """Issue #487: the JSON answer of a refusal holds code, error, command and reason."""
        refusal = Refused("OGK-WEB-004", "Approve at a terminal.", "openguildkit task decide t1", reason="approve-at-terminal")
        self.assertEqual(refusal.answer(), {"error": "Approve at a terminal.", "code": "OGK-WEB-004",
                                            "command": "openguildkit task decide t1", "reason": "approve-at-terminal"})
        self.assertNotIsInstance(refusal, ValueError)

    def test_issue_487_each_command_the_page_may_not_run_has_its_code(self):
        """Issue #487: the commands refused by check_request, check_paths and the runner."""
        def run(code, argv, uploads=None, **extra):
            return (code, "/api/run", {"argv": argv, **({"uploads": uploads} if uploads is not None else {}), **extra},
                    None, None)

        self.assertRefused([
            run("OGK-WEB-003", ["ui"]),
            run("OGK-WEB-004", ["task", "complete", "t1", "--by", "C"]),
            run("OGK-WEB-005", ["guard", "--hook", "prompt"]),
            run("OGK-WEB-006", ["tools", "mock", "jira"]),
            run("OGK-WEB-007", ["integrations", "--host", "codex", "--user"]),
            run("OGK-WEB-008", ["init"]),
            run("OGK-WEB-009", ["task", "consult", "t1"]),
            run("OGK-WEB-011", ["task", "export", "t1", "--output", "../outside.json"]),
            run("OGK-WEB-012", ["task", "export", "t1", "--output", ".git/record.json"]),
            run("OGK-WEB-026", ["check"], omit="x"),
            run("OGK-WEB-027", ["no-such-command"]),
            run("OGK-WEB-028", []),
            run("OGK-WEB-029", ["--project", "elsewhere"]),
            run("OGK-WEB-030", ["check"], uploads=["a.md"]),
            run("OGK-WEB-031", ["check"], uploads={"../x.md": "x"}),
            run("OGK-WEB-032", ["check"], uploads={"a.md": "\ud800"}),
            run("OGK-WEB-033", ["task", "new", "--file", "@upload:none.md"]),
            ("OGK-WEB-046", "/api/run", {"batch": []}, None, None),
        ])
        with patch.object(Path, "resolve", side_effect=ValueError("embedded null byte")), \
                self.assertRaises(Refused) as raised:
            web_requests._resolved(Path("a\0b.md"))
        self.assertEqual((raised.exception.code, raised.exception.status), ("OGK-WEB-010", HTTPStatus.BAD_REQUEST))

    def test_issue_487_each_file_the_page_may_not_read_or_write_has_its_code(self):
        """Issue #487: the refusals of ProjectFiles."""
        (self.root / ".env").write_text("A=1", encoding="utf-8")
        (self.root / "notes.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "folder.md").mkdir()
        (self.root / "big.txt").write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
        token = "gh" + "p_" + "y" * 36
        (self.root / "settings.json").write_text(json.dumps({"env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token}}),
                                                 encoding="utf-8")
        proposals = ".openguildkit/storybook/proposals.json"

        def read(code, path):
            return (code, "/api/files/read", {"path": path}, None, None)

        def write(code, path, text):
            return (code, "/api/files/write", {"path": path, "text": text}, None, None)

        self.assertRefused([
            read("OGK-WEB-013", "/etc/hosts"), read("OGK-WEB-014", "../x.json"), read("OGK-WEB-015", ".git/config"),
            read("OGK-WEB-016", ".env"), read("OGK-WEB-017", "notes.py"), read("OGK-WEB-018", "folder.md"),
            read("OGK-WEB-019", "big.txt"), read("OGK-WEB-020", "settings.json"),
            write("OGK-WEB-021", ".openguildkit/project.json", "{}"), write("OGK-WEB-022", proposals, 1),
            write("OGK-WEB-023", proposals, "[\"\ud800\"]"), write("OGK-WEB-024", proposals, "{x"),
        ])
        with patch.dict("os.environ", {"OPENGUILDKIT_LOCK_TIMEOUT": "0"}), project_lock(self.root / ".openguildkit"):
            self.assertRefused([write("OGK-WEB-025", proposals, "{}")])

    def test_issue_487_each_refused_request_of_the_server_has_its_code(self):
        """Issue #487: a foreign host, origin or token, a method, a body, an endpoint or a server error."""
        loopback = f"127.0.0.1:{self.app.port}"
        stale = {"Cookie": f"{self.app.cookie}=from-a-stopped-server"}
        self.assertRefused([
            ("OGK-WEB-034", "/api/session", None, {"Host": loopback}, None),
            ("OGK-WEB-035", "/api/session", None, {"Host": "evil.example:80"}, None),
            ("OGK-WEB-036", "/api/session", None, stale, None),
            ("OGK-WEB-037", "/api/run", None, None, "GET"),
            ("OGK-WEB-038", "/missing.js", None, None, "GET"),
            ("OGK-WEB-040", "/api/run", {"argv": ["check"]}, {"Host": "evil.example:80"}, None),
            ("OGK-WEB-041", "/api/run", {"argv": ["check"]}, {"Origin": "https://evil.example"}, None),
            ("OGK-WEB-042", "/api/run", {"argv": ["check"]}, {"X-OGK-Token": "from-a-stopped-server"}, None),
            ("OGK-WEB-043", "/api/run", {"argv": ["check"]}, {"Content-Type": "text/plain"}, None),
            ("OGK-WEB-044", "/api/run", None, {"Content-Length": str(64 * 1024 * 1024)}, "POST"),
            ("OGK-WEB-045", "/api/run", ["task"], None, None),
            ("OGK-WEB-047", "/api/unknown", {}, None, None),
        ])
        with patch.object(self.app, "handle", side_effect=RuntimeError("boom")), contextlib.redirect_stderr(io.StringIO()):
            self.assertRefused([("OGK-WEB-039", "/api/run", {"argv": ["check"]}, None, None)])

    def test_issue_487_each_refused_preference_or_profile_has_its_code(self):
        """Issue #487: the refusals of the preferences and of the profile saved from the page."""
        profile = self.root / ".openguildkit" / "project.json"
        saved = profile.read_text(encoding="utf-8")
        weaker = json.dumps({**json.loads(saved), "research": "public-sources"})
        self.assertRefused([
            ("OGK-WEB-048", "/api/prefs", {"prefs": {}}, None, None),
            ("OGK-WEB-049", "/api/prefs", {"prefs": {"unknown": 1}}, None, None),
            ("OGK-WEB-052", "/api/profile/save", {"text": 1}, None, None),
            ("OGK-WEB-053", "/api/profile/save", {"text": "{not json"}, None, None),
            ("OGK-WEB-055", "/api/profile/save", {"text": weaker}, None, None),
            ("OGK-WEB-056", "/api/profile/save", {"text": saved, "by": ""}, None, None),
        ])
        profile.unlink()
        try:
            self.assertRefused([("OGK-WEB-050", "/api/prefs", {"prefs": {"mode": "focus"}}, None, None),
                                ("OGK-WEB-054", "/api/profile/save", {"text": saved}, None, None)])
        finally:
            profile.write_text(saved, encoding="utf-8")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        work = self.root / ".openguildkit" / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.symlink_to(outside, target_is_directory=True)
        self.assertRefused([("OGK-WEB-051", "/api/prefs", {"prefs": {"mode": "focus"}}, None, None)])


if __name__ == "__main__":
    unittest.main()
