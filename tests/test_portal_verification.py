"""Verify portal comparisons without contacting a real Documentalist instance."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from openguildkit.portal_verification import verify_portal
from openguildkit.publishing import share_status
from openguildkit.storage import write_json


class PortalHandler(BaseHTTPRequestHandler):
    supported = True
    redirect_login = False
    login_count = 0
    logout_count = 0
    redirected = False

    def log_message(self, *args):
        pass

    def reply(self, data, status=200, headers=None):
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/api/auth/login":
            type(self).login_count += 1
            if self.redirect_login:
                self.reply({}, 302, {"Location": "/redirected"})
            else:
                self.reply({"ok": True}, headers={"Set-Cookie": "session=temporary; Path=/"})
        elif self.path == "/api/auth/logout":
            type(self).logout_count += 1
            self.reply({"ok": True})
        else:
            type(self).redirected = True
            self.reply({}, 404)

    def do_GET(self):
        if self.headers.get("Cookie") != "session=temporary":
            self.reply({}, 401)
        elif self.path == "/api/spaces":
            self.reply({"spaces": [{"id": "space-1", "slug": "demo"}]})
        elif self.path == "/api/spaces/space-1/access/invites":
            data = {"emails": ["a@example.org", "b@example.org"]}
            if self.supported:
                data["expirations"] = {"a@example.org": "2031-12-31", "b@example.org": "2030-12-31"}
            self.reply(data)
        else:
            self.reply({}, 404)


class PortalVerificationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name) / ".openguildkit"
        PortalHandler.supported, PortalHandler.redirect_login = True, False
        PortalHandler.login_count = PortalHandler.logout_count = 0
        PortalHandler.redirected = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), PortalHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.portal = f"http://127.0.0.1:{self.server.server_port}/p/demo"
        rows = [
            {"id": "one", "recipients": ["A@example.org", "b@example.org"], "until": "2030-12-31", "portal": self.portal,
             "revoked_at": None, "deliverable": "one.md", "by": "CM"},
            {"id": "two", "recipients": ["a@example.org"], "until": "2031-12-31", "portal": self.portal,
             "revoked_at": None, "deliverable": "two.md", "by": "CM"},
        ]
        write_json(self.state / "shares" / "shares.json", {"shares": rows})

    def verify(self):
        with patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", return_value="private-password"):
            return verify_portal(self.state, self.portal, "editor@example.org")

    def test_overlapping_shares_use_latest_date_and_keep_observation(self):
        report = self.verify()
        self.assertEqual(report["source"], "documentalist-api")
        self.assertEqual([(r["recipient"], r["register_until"], r["status"]) for r in report["rows"]],
                         [("a@example.org", "2031-12-31", "matches"), ("b@example.org", "2030-12-31", "matches")])
        self.assertEqual((PortalHandler.login_count, PortalHandler.logout_count), (1, 1))
        saved = (self.state / "shares" / "portal-observations.json").read_text(encoding="utf-8")
        self.assertNotIn("private-password", saved)
        self.assertEqual(share_status(self.state)[0]["portal_observation"]["source"], "documentalist-api")

    def test_old_instance_stays_unverified_and_lists_the_manual_action(self):
        PortalHandler.supported = False
        report = self.verify()
        self.assertEqual(report["source"], "local-register")
        self.assertTrue(all(row["status"] == "unverified" and row["action"] for row in report["rows"]))
        self.assertEqual(PortalHandler.logout_count, 1)

    def test_credentials_are_not_forwarded_to_a_redirect(self):
        PortalHandler.redirect_login = True
        report = self.verify()
        self.assertEqual(report["source"], "local-register")
        self.assertFalse(PortalHandler.redirected)
        self.assertEqual(PortalHandler.logout_count, 0)


if __name__ == "__main__":
    unittest.main()
