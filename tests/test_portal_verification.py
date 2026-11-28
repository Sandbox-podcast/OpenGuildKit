"""docs share verify against a local stand-in for Documentalist's reader settings.

The stand-in answers the four routes the command calls, as Documentalist does: login with
the Origin header and a session cookie, the space list, the invitation list of a space (with
or without end dates, 409 outside magic-link mode) and logout. No real instance is contacted.
"""

import contextlib
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from openguildkit import clock
from openguildkit.portal_verification import verify_portal
from openguildkit.publishing import share_status
from openguildkit.storage import read_json, write_json
from tests.support import CapturedCli, copy_initialized_project

PASSWORD = "stand-in-password"


def day(offset: int) -> str:
    """A UTC day relative to today, as Documentalist counts end dates."""
    return (clock.real_now().date() + timedelta(days=offset)).isoformat()


class Portal(BaseHTTPRequestHandler):
    """Documentalist's reader settings for one space, slug demo; class attributes set by each test."""

    emails: list = []
    expirations: dict | None = {}
    mode = "magic_link"
    redirect_login = False
    secure_cookie = False  # As an instance started for production without DOCUMENTALIST_COOKIE_SECURE=false.
    limited: str | None = None  # "sign-in" or "route": the instance's two 429 answers.
    calls: list = []
    garbage: str | None = None  # The route answered with bytes that are not HTTP: "login" or "logout".

    def log_message(self, *args):
        pass

    def not_http(self):
        self.wfile.write(b"garbage not http\r\n\r\n")
        self.close_connection = True

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
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        type(self).calls.append(("POST", self.path, self.headers.get("Origin")))
        if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
            self.reply({"error": "Origine de la requête refusée."}, 400)
        elif self.path == f"/api/auth/{self.garbage}":
            self.not_http()
        elif self.path == "/api/auth/login" and self.limited == "sign-in":
            self.reply({"error": "Trop de tentatives. Réessayez dans dix minutes."}, 429)
        elif self.path == "/api/auth/login" and self.limited == "route":
            self.reply({"error": "Trop de requêtes. Réessayez dans une minute."}, 429, {"Retry-After": "60"})
        elif self.path == "/api/auth/login" and self.redirect_login:
            self.reply({}, 302, {"Location": "/elsewhere"})
        elif self.path == "/api/auth/login":
            if body.get("password") != PASSWORD:
                self.reply({"error": f"Invalid credentials: {body.get('password')}"}, 401)
            else:
                secure = "; Secure" if self.secure_cookie else ""
                self.reply({"ok": True}, headers={"Set-Cookie": f"documentalist-session=s1; Path=/; HttpOnly{secure}"})
        elif self.path == "/api/auth/logout":
            self.reply({"ok": True}, headers={"Set-Cookie": "documentalist-session=; Path=/; Max-Age=0"})
        else:
            self.reply({}, 404)

    def do_GET(self):
        type(self).calls.append(("GET", self.path, None))
        if self.headers.get("Cookie") != "documentalist-session=s1":
            self.reply({"error": "Connexion requise."}, 401)
        elif self.path == "/api/spaces":
            self.reply({"spaces": [{"id": "spc_1", "slug": "demo"}, {"id": "spc_2", "slug": "other"}]})
        elif self.path == "/api/spaces/spc_1/access/invites":
            if self.mode != "magic_link":
                self.reply({"error": "Choisissez d’abord le mode « lien magique »."}, 409)
            elif self.expirations is None:  # Documentalist before end dates (947429b).
                self.reply({"emails": self.emails})
            else:
                self.reply({"emails": self.emails, "expirations": self.expirations})
        else:
            self.reply({}, 404)


class RecordingProxy(BaseHTTPRequestHandler):
    """An HTTP proxy that keeps every request. A portal on this machine must never reach it."""

    received: list = []

    def log_message(self, *args):
        pass

    def _record(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        type(self).received.append((self.command, self.path, body))
        self.send_response(502)
        self.end_headers()

    def do_GET(self):
        self._record()

    def do_POST(self):
        self._record()

    def do_CONNECT(self):
        self._record()


class PortalVerificationTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        profile = self.root / "profile.json"
        write_json(profile, {"personal_data": "no", "name": "Support portal", "stack": ["Python"], "packs": [],
                             "checks": [f'"{sys.executable}" -c "print(1)"']})
        copy_initialized_project(self, profile, self.root)
        (self.root / "page.md").write_text("# Page\n", encoding="utf-8")
        self.state = self.root / ".openguildkit"
        Portal.emails, Portal.expirations, Portal.mode = [], {}, "magic_link"
        Portal.redirect_login, Portal.secure_cookie, Portal.limited, Portal.calls = False, False, None, []
        Portal.garbage = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Portal)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.portal = f"http://127.0.0.1:{self.server.server_port}/p/demo"

    def share(self, recipients, until, portal=None):
        output, _ = self.run_cli("docs", "share", "add", "--deliverable", "page.md", "--until", until, "--by", "CM",
                                 "--portal", portal or self.portal, *[part for r in recipients for part in ("--recipient", r)])
        return output.split()[1]

    def set_until(self, share_id, until):
        """Move a recorded last day, as the days passing would: share add refuses a past day."""
        path = self.state / "shares" / "shares.json"
        data = read_json(path)
        for item in data["shares"]:
            if item["id"] == share_id:
                item["until"] = until
        write_json(path, data)

    def verify(self, *extra, code=0, password=PASSWORD, portal=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("sys.stdin.isatty", return_value=True))
            prompt = stack.enter_context(patch("getpass.getpass", return_value=password))
            output, error = self.run_cli("docs", "share", "verify", "--portal", portal or self.portal,
                                         "--user", "editor@example.test", *extra, code=code)
        self.assertEqual(prompt.call_count, 1)
        return output, error

    def test_before_and_after_the_end_the_dates_and_the_access_state_agree(self):
        first = self.share(["Reader@example.test"], day(10))
        Portal.emails, Portal.expirations = ["reader@example.test"], {"reader@example.test": day(10)}
        output, _ = self.verify()
        self.assertIn(f"127.0.0.1:{self.server.server_port}/p/demo: documentalist-api at ", output)
        self.assertIn(f"reader@example.test: register until {day(10)}; portal until {day(10)} (open); matches", output)
        # The last day passes: the portal holds the same day and its policy has ended.
        self.set_until(first, day(-1))
        Portal.expirations = {"reader@example.test": day(-1)}
        output, _ = self.verify()
        self.assertIn(f"register until {day(-1)}; portal until {day(-1)} (ended); matches", output)
        # Today is still the last day: Documentalist closes at 00:00 UTC the next day.
        self.set_until(first, day(0))
        Portal.expirations = {"reader@example.test": day(0)}
        report = json.loads(self.verify("--json")[0])
        self.assertEqual(report["rows"][0]["policy_active"], True)
        self.assertEqual((report["source"], report["rows"][0]["status"]), ("documentalist-api", "matches"))

    def test_a_local_proxy_declared_in_the_environment_receives_nothing(self):
        self.share(["reader@example.test"], day(10))
        Portal.emails, Portal.expirations = ["reader@example.test"], {"reader@example.test": day(10)}
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), RecordingProxy)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(proxy.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(proxy.shutdown)
        RecordingProxy.received = []
        address = f"http://127.0.0.1:{proxy.server_port}"
        # No exclusion for this machine: that is the setting that used to forward the password.
        with patch.dict(os.environ, {"HTTP_PROXY": address, "HTTPS_PROXY": address, "ALL_PROXY": address,
                                     "NO_PROXY": ""}):
            self.verify()
        self.assertEqual(RecordingProxy.received, [])
        self.assertIn("/api/auth/login", [call[1] for call in Portal.calls])

    def test_the_session_is_opened_with_the_instance_origin_then_closed_and_nothing_secret_is_kept(self):
        self.share(["reader@example.test"], day(10))
        Portal.emails, Portal.expirations = ["reader@example.test"], {"reader@example.test": day(10)}
        self.verify()
        origin = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(Portal.calls, [("POST", "/api/auth/login", origin), ("GET", "/api/spaces", None),
                                        ("GET", "/api/spaces/spc_1/access/invites", None),
                                        ("POST", "/api/auth/logout", origin)])
        saved = (self.state / "shares" / "portal-observations.json").read_text(encoding="utf-8")
        self.assertNotIn(PASSWORD, saved)
        self.assertNotIn("documentalist-session", saved)
        self.assertNotIn(PASSWORD, (self.state / "shares" / "shares.json").read_text(encoding="utf-8"))

    def test_several_shares_to_one_recipient_are_one_access_with_the_latest_running_day(self):
        early = self.share(["reader@example.test"], day(5))
        self.share(["reader@example.test", "second@example.test"], day(20))
        later = self.share(["reader@example.test"], day(40))
        self.run_cli("docs", "share", "revoke", "--id", later, "--by", "CM")
        # The revoked share gives no access: the running ones end on day(20) at the latest.
        Portal.emails = ["reader@example.test", "second@example.test"]
        Portal.expirations = {"reader@example.test": day(20), "second@example.test": day(20)}
        report = json.loads(self.verify("--json")[0])
        rows = {row["recipient"]: row for row in report["rows"]}
        self.assertEqual(rows["reader@example.test"]["register_until"], day(20))
        self.assertEqual(sorted(rows["reader@example.test"]["shares"]), sorted([early, rows["second@example.test"]["shares"][0]]))
        self.assertEqual({row["status"] for row in report["rows"]}, {"matches"})
        # share list shows the observation under each share of that space.
        listing, _ = self.run_cli("docs", "share", "list")
        self.assertEqual(listing.count("last portal observation: documentalist-api"), 3)
        self.assertIn(f"reader@example.test: matches, portal until {day(20)} (open)", listing)
        # The portal keeps the earliest day: the later share would end too soon.
        Portal.expirations = {"reader@example.test": day(5), "second@example.test": day(20)}
        output, _ = self.verify(code=1)
        self.assertIn(f"reader@example.test: register until {day(20)}; portal until {day(5)} (open); mismatch", output)
        self.assertIn(f"Change the last day for reader@example.test in the reader settings of space "
                      f"127.0.0.1:{self.server.server_port}/p/demo from {day(5)} to {day(20)}", output)

    def test_adding_a_second_share_names_the_day_to_set_in_the_portal(self):
        self.share(["reader@example.test"], day(5))
        _, warning = self.run_cli("docs", "share", "add", "--deliverable", "page.md", "--until", day(30), "--by", "CM",
                                  "--portal", self.portal, "--recipient", "reader@example.test")
        self.assertIn(f"give it the later last day, {day(30)}, in the portal", warning)

    def test_each_difference_names_what_to_do_in_the_portal(self):
        self.share(["dated@example.test", "missing@example.test"], day(10))
        gone = self.share(["gone@example.test"], day(10))
        self.run_cli("docs", "share", "revoke", "--id", gone, "--by", "CM")
        self.share(["other@example.test"], day(10), portal=self.portal.replace("/p/demo", "/p/other"))
        Portal.emails = ["dated@example.test", "gone@example.test", "other@example.test"]
        Portal.expirations = {}
        output, _ = self.verify(code=1)
        self.assertIn("dated@example.test: register until " + day(10) + "; portal invited with no end date (open); mismatch",
                      output)
        self.assertIn(f"Set the last day {day(10)} for dated@example.test", output)
        self.assertIn("missing@example.test: register until " + day(10) + "; portal not invited; mismatch", output)
        self.assertIn(f"Invite missing@example.test in the reader settings of space 127.0.0.1:{self.server.server_port}/p/demo "
                      f"with the last day {day(10)}", output)
        self.assertIn("gone@example.test: register until no running share; portal invited with no end date (open); mismatch",
                      output)
        self.assertIn("Remove gone@example.test's access", output)
        # Another space's share is not compared with this space.
        self.assertNotIn("other@example.test", output)

    def test_an_older_instance_leaves_the_register_usable_and_names_the_manual_removal(self):
        share_id = self.share(["reader@example.test"], day(10))
        Portal.emails, Portal.expirations = ["reader@example.test"], None
        output, _ = self.verify(code=1)
        self.assertIn("local-register", output)
        self.assertIn("This Documentalist version keeps no end date per reader", output)
        self.assertIn("reader@example.test: register until " + day(10) + "; portal not verified; unverified", output)
        self.assertIn(f"This instance keeps no end date: remove reader@example.test's access in the reader settings of "
                      f"space 127.0.0.1:{self.server.server_port}/p/demo (\"Retirer l'accès\") after {day(10)}, "
                      "then record it with docs share revoke.", output)
        self.assertEqual(Portal.calls[-1][:2], ("POST", "/api/auth/logout"))
        listing, _ = self.run_cli("docs", "share", "list")
        self.assertIn(f"{share_id} page.md", listing)
        self.assertIn("last portal observation: local-register", listing)
        self.run_cli("docs", "share", "check")
        self.set_until(share_id, day(-1))
        checked, _ = self.run_cli("docs", "share", "check", code=1)
        self.assertIn("expired", checked)

    def test_an_unreachable_instance_leaves_the_register_usable(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            closed = probe.getsockname()[1]
        portal = f"http://127.0.0.1:{closed}/p/demo"
        share_id = self.share(["reader@example.test"], day(10), portal=portal)
        output, _ = self.verify(code=1, portal=portal)
        self.assertIn(f"The portal could not be verified: http://127.0.0.1:{closed} did not answer", output)
        self.assertIn(f"Check that reader@example.test has the last day {day(10)}", output)
        self.assertIn(share_id, self.run_cli("docs", "share", "list")[0])
        self.run_cli("docs", "share", "check")

    def test_refusals_of_the_instance_say_what_to_fix(self):
        self.share(["reader@example.test"], day(10))
        password = "test-invalid-password"
        output, _ = self.verify(code=1, password=password)
        self.assertNotIn(password, output)
        observation = self.state / "shares" / "portal-observations.json"
        self.assertNotIn(password, observation.read_text(encoding="utf-8"))
        self.assertIn("Documentalist answered HTTP 401; check the account and its password.",
                      output)
        # The instance accepts changes only from its own address, here 127.0.0.1 and not localhost.
        local = self.portal.replace("127.0.0.1", "localhost")
        self.share(["reader@example.test"], day(10), portal=local)
        output, _ = self.verify(code=1, portal=local)
        self.assertIn("HTTP 400; give --portal the address the instance is configured "
                      "with (DOCUMENTALIST_URL).", output)
        Portal.mode = "password"
        output, _ = self.verify(code=1)
        self.assertIn("HTTP 409", output)
        self.assertIn("set the space's portal access to magic link", output)
        Portal.mode = "magic_link"
        Portal.emails, Portal.expirations = ["reader@example.test"], {"reader@example.test": "31/12/2030"}
        output, _ = self.verify(code=1)
        self.assertIn("not a YYYY-MM-DD day", output)

    def test_a_session_cookie_an_http_address_cannot_return_names_the_instance_setting(self):
        self.share(["reader@example.test"], day(10))
        Portal.secure_cookie = True
        output, _ = self.verify(code=1)
        self.assertIn("HTTP 401; the instance kept no session after the sign-in; over http, start "
                      "it with DOCUMENTALIST_COOKIE_SECURE=false, or give --portal its https address.", output)
        self.assertNotIn("check the account and its password", output)
        self.assertIn(("POST", "/api/auth/logout", f"http://127.0.0.1:{self.server.server_port}"), Portal.calls)

    def test_the_two_request_limits_of_the_instance_name_their_own_wait(self):
        self.share(["reader@example.test"], day(10))
        Portal.limited = "sign-in"
        output, _ = self.verify(code=1)
        self.assertIn("HTTP 429; wait ten minutes", output)
        Portal.limited = "route"
        output, _ = self.verify(code=1)
        self.assertIn("HTTP 429; wait 60 seconds: the instance limits "
                      "requests.", output)

    def test_an_answer_that_is_not_http_gives_an_error_and_not_a_trace(self):
        self.share(["reader@example.test"], day(10))
        Portal.garbage = "login"
        output, error = self.verify(code=1)
        self.assertIn(f"The portal could not be verified: http://127.0.0.1:{self.server.server_port} did not answer in "
                      "valid HTTP (BadStatusLine).", output)
        self.assertNotIn("garbage", output + error)
        self.assertNotIn("Traceback", error)
        space = f"127.0.0.1:{self.server.server_port}/p/demo"
        observed = read_json(self.state / "shares" / "portal-observations.json")["observations"][space]
        self.assertEqual(observed["source"], "local-register")

    def test_a_logout_that_is_not_http_leaves_the_verification_intact(self):
        self.share(["reader@example.test"], day(10))
        Portal.emails, Portal.expirations = ["reader@example.test"], {"reader@example.test": day(10)}
        Portal.garbage = "logout"
        output, _ = self.verify()
        self.assertIn("matches", output)
        self.assertIn(("POST", "/api/auth/logout", f"http://127.0.0.1:{self.server.server_port}"), Portal.calls)

    def test_credentials_are_not_forwarded_to_a_redirect(self):
        self.share(["reader@example.test"], day(10))
        Portal.redirect_login = True
        output, _ = self.verify(code=1)
        # OGK-PORTAL-001
        self.assertIn("Documentalist redirected the request; no credentials were forwarded.", output)
        self.assertEqual([call[1] for call in Portal.calls], ["/api/auth/login"])

    def test_the_password_is_asked_only_at_a_terminal_and_never_on_the_command_line(self):
        self.share(["reader@example.test"], day(10))
        with patch("sys.stdin.isatty", return_value=False), patch("getpass.getpass") as prompt:
            _, error = self.run_cli("docs", "share", "verify", "--portal", self.portal, "--user", "editor@example.test",
                                    code=1)
        self.assertIn("OpenGuildKit [OGK-PORTAL-003]: Portal verification needs an interactive terminal", error)
        self.assertEqual((prompt.call_count, Portal.calls), (0, []))
        _, error = self.run_cli("docs", "share", "verify", "--portal", self.portal, code=1)
        self.assertIn("docs share verify needs --portal and --user", error)
        _, error = self.run_cli("docs", "share", "verify", "--portal",
                                self.portal.replace("http://", f"http://editor:{PASSWORD}@"), "--user", "e@example.test",
                                code=1)
        self.assertIn("Remove credentials from --portal", error)

    def test_http_is_refused_off_this_machine_and_https_is_required_to_trust_the_server(self):
        # OGK-PUBLISH-008
        self.share(["reader@example.test"], day(10))
        _, error = self.run_cli("docs", "share", "verify", "--portal", "http://docs.example.test/p/demo",
                                "--user", "editor@example.test", code=1)
        self.assertIn("Give the https address of the Documentalist portal", error)
        # The stand-in speaks plain HTTP: an https request to it fails before any credential is sent.
        portal = self.portal.replace("http://", "https://")
        self.share(["reader@example.test"], day(10), portal=portal)
        output, _ = self.verify(code=1, portal=portal)
        self.assertIn("The portal could not be verified", output)
        self.assertEqual(Portal.calls, [])

    def test_a_space_without_shares_is_refused_before_the_password(self):
        with patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass") as prompt:
            _, error = self.run_cli("docs", "share", "verify", "--portal", self.portal, "--user", "editor@example.test",
                                    code=1)
        # OGK-PORTAL-002
        self.assertIn("The local register has no shares for", error)
        self.assertEqual(prompt.call_count, 0)

    def test_the_origin_leaves_out_the_default_port_as_a_browser_does(self):
        for portal, origin in (("https://docs.example.test:443/p/demo", "https://docs.example.test"),
                               ("https://Docs.Example.test/p/demo", "https://docs.example.test"),
                               ("http://localhost:80/p/demo", "http://localhost"), ("https://[::1]:443/p/demo", "https://[::1]"),
                               ("https://docs.example.test:8443/p/demo", "https://docs.example.test:8443")):
            with self.subTest(portal=portal):
                self.share(["reader@example.test"], day(10), portal=portal)
                sent = []

                class Opener:
                    def open(self, request, timeout):
                        sent.append((request.full_url, request.get_header("Origin")))
                        raise URLError("stand-in")

                with patch("openguildkit.portal_verification.build_opener", return_value=Opener()):
                    self.verify(code=1, portal=portal)
                self.assertEqual(sent, [(f"{origin}/api/auth/login", origin)])

    def test_verify_portal_can_be_called_directly(self):
        self.share(["reader@example.test"], day(10))
        Portal.emails, Portal.expirations = ["reader@example.test"], {"reader@example.test": day(10)}
        with patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", return_value=PASSWORD):
            report = verify_portal(self.state, self.portal, "editor@example.test")
        self.assertEqual(report["scope"], "Invitation settings only; verify actual reader access separately.")
        self.assertEqual(share_status(self.state)[0]["portal_observation"]["source"], "documentalist-api")


if __name__ == "__main__":
    unittest.main()
