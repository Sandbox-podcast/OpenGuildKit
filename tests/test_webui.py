import contextlib
import gzip
import http.client
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from openguildkit import webui
from openguildkit.cli import main
from openguildkit.storage import write_json
from openguildkit.webui import make_server

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
ENV = {
    **os.environ,
    "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
    "PYTHONIOENCODING": "utf-8",
    "OPENGUILDKIT_UI_KEY": "",
}


def fetch(port: int, path: str, cookie: str | None = None):
    """A GET as a browser or another local program sends it, without following a redirect."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    finally:
        connection.close()


def fake_front(folder: Path) -> Path:
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<!doctype html><html><head><title>OGK</title></head></html>", encoding="utf-8")
    (folder / "assets" / "app-0123456789.js").write_text("console.log(1)", encoding="utf-8")
    return folder


class WebInterfaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "portal"
        self.root.mkdir()
        front = fake_front(Path(temporary.name).resolve() / "dist")
        write_json(self.root / "profile.json", {"name": "Portal", "stack": ["Python"], "packs": ["python"]})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--project", str(self.root), "init", "--answers", str(self.root / "profile.json")]), 0)
        self.server, self.app = make_server(self.root, 0, front)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.app.port}"

    def request(self, path, body=None, headers=None, method=None):
        """A request of the page: the session cookie set by the printed address, its origin and its token."""
        default = {"Origin": self.base, "X-OGK-Token": self.app.token, "Content-Type": "application/json",
                   "Cookie": f"{self.app.cookie}={self.app.key}"}
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, headers={**default, **(headers or {})},
                                         method=method or ("POST" if body is not None else "GET"))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers, error.read()

    def run_in_page(self, *argv, uploads=None):
        """A command sent by the page to the server: an HTTP call, not a CLI invocation of its own."""
        status, _, body = self.request("/api/run", {"argv": list(argv), "uploads": uploads or {}})
        return status, json.loads(body)

    def test_the_session_gives_the_token_and_the_project(self):
        status, headers, body = self.request("/api/session")
        self.assertEqual(status, 200)
        session = json.loads(body)
        self.assertEqual(session["token"], self.app.token)
        self.assertTrue(session["project"]["initialized"])
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_only_the_printed_address_opens_the_session(self):
        port = self.app.port
        self.assertEqual(self.app.url, f"http://127.0.0.1:{port}/?key={self.app.key}")
        for cookie in (None, f"{self.app.cookie}=guess", f"ogk-{port + 1}={self.app.key}"):
            with self.subTest(cookie=cookie):
                status, _, body = fetch(port, "/api/session", cookie)
                self.assertEqual((status, json.loads(body)["reason"]), (403, "open-printed-link"))
                self.assertNotIn(self.app.token.encode(), body)
                status, _, page = fetch(port, "/", cookie)
                self.assertEqual(status, 403)
                self.assertIn(b"openguildkit ui", page)
                self.assertNotIn(b"openguildkit-ui", page)
        self.assertEqual(fetch(port, "/?key=guess")[0], 403)
        status, headers, _ = fetch(port, f"/?key={self.app.key}")
        self.assertEqual((status, headers["Location"]), (303, "/"))
        cookie = headers["Set-Cookie"]
        self.assertTrue(cookie.startswith(f"{self.app.cookie}={self.app.key};"), cookie)
        for attribute in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, cookie)
        status, _, body = fetch(port, "/api/session", cookie.split(";")[0])
        self.assertEqual((status, json.loads(body)["token"]), (200, self.app.token))
        self.assertEqual(fetch(port, "/assets/app-0123456789.js")[0], 200)

    def test_a_key_set_for_a_scripted_run_is_used_only_when_it_is_long_enough(self):
        from openguildkit.webui import launch_key

        with patch.dict("os.environ", {"OPENGUILDKIT_UI_KEY": "k" * 40}):
            self.assertEqual(launch_key(), "k" * 40)
        for value in ("short", "k" * 31, "k" * 39 + "/"):
            with self.subTest(value=value), patch.dict("os.environ", {"OPENGUILDKIT_UI_KEY": value}):
                with self.assertRaisesRegex(ValueError, "OPENGUILDKIT_UI_KEY"):
                    launch_key()
        with patch.dict("os.environ", {"OPENGUILDKIT_UI_KEY": ""}):
            self.assertGreaterEqual(len(launch_key()), 40)
            self.assertNotEqual(launch_key(), launch_key())

    def test_git_is_out_of_reach_whatever_its_case(self):
        status, result = self.run_in_page("storybook", "extract", "--src", ".", "--output", ".GIT/probe.json")
        self.assertEqual((status, result["reason"]), (400, "outside-project"))
        self.assertFalse((self.root / ".GIT").exists() or (self.root / ".git").exists())
        (self.root / ".Git").mkdir()
        (self.root / ".Git" / "config.json").write_text("{}", encoding="utf-8")
        status, _, body = self.request("/api/files/read", {"path": ".Git/config.json"})
        self.assertEqual((status, json.loads(body)["reason"]), (403, "outside-project"))
        names = [entry["name"] for entry in json.loads(self.request("/api/files/list", {"path": "."})[2])["entries"]]
        self.assertNotIn(".Git", names)

    def test_files_that_hold_tokens_are_neither_listed_nor_read(self):
        names = ("token.json", "tokens-prod.json", "auth.json", "service-account.json", "gcp-service-account-ci.json",
                 "local.settings.json")
        for name in names:
            (self.root / name).write_text("{}", encoding="utf-8")
        (self.root / "authors.json").write_text("{}", encoding="utf-8")
        for name in names:
            with self.subTest(name=name):
                status, _, body = self.request("/api/files/read", {"path": name})
                self.assertEqual((status, json.loads(body)["reason"]), (403, "secret-file"))
        self.assertEqual(self.request("/api/files/read", {"path": "authors.json"})[0], 200)
        listed = [entry["name"] for entry in json.loads(self.request("/api/files/list", {"path": "."})[2])["entries"]]
        self.assertEqual(sorted(set(listed) & {*names, "authors.json"}), ["authors.json"])
        # The tool's own records carry task IDs: the record of a task named token-rotation stays readable.
        record = self.root / ".openguildkit" / "decisions" / "token-rotation.json"
        record.parent.mkdir(parents=True)
        record.write_text("{}", encoding="utf-8")
        self.assertEqual(self.request("/api/files/read", {"path": ".openguildkit/decisions/token-rotation.json"})[0], 200)
        listed = json.loads(self.request("/api/files/list", {"path": ".openguildkit/decisions"})[2])["entries"]
        self.assertEqual([entry["name"] for entry in listed], ["token-rotation.json"])

    def test_a_foreign_host_origin_or_token_is_refused(self):
        self.assertEqual(self.request("/api/session", headers={"Host": "evil.example:80"})[0], 421)
        self.assertEqual(self.request("/api/run", {"argv": ["check"]}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/api/run", {"argv": ["check"]}, headers={"X-OGK-Token": "guess"})[0], 403)
        self.assertEqual(self.request("/api/run", {"argv": ["check"]}, headers={"Content-Type": "text/plain"})[0], 415)

    def test_a_command_runs_and_returns_its_json(self):
        status, result = self.run_in_page("task", "list", "--json")
        self.assertEqual(status, 200)
        self.assertEqual((result["code"], result["json"]), (0, []))

    def test_concurrent_requests_keep_their_own_output(self):
        results = []

        def call(argv):
            results.append((argv[0], self.run_in_page(*argv)[1]))

        threads = [threading.Thread(target=call, args=(argv,)) for _ in range(6)
                   for argv in (["task", "list", "--json"], ["catalog", "--json"], ["check"])]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 18)
        for command, result in results:
            if command == "task":
                self.assertEqual(result["json"], [])
            elif command == "catalog":
                self.assertIn("packs", result["json"])

    def test_the_profile_is_saved_then_synchronized_or_restored(self):
        profile = self.root / ".openguildkit" / "project.json"
        saved = json.loads(profile.read_text(encoding="utf-8"))
        status, _, body = self.request("/api/profile/save", {"text": json.dumps({**saved, "conventions": ["Write tests."]})})
        self.assertEqual((status, json.loads(body)["code"]), (200, 0))
        self.assertIn("Write tests.", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        status, _, body = self.request("/api/profile/save", {"text": json.dumps({**saved, "research": "everywhere"})})
        self.assertTrue(json.loads(body)["restored"])
        self.assertEqual(json.loads(profile.read_text(encoding="utf-8"))["conventions"], ["Write tests."])

    def test_every_read_command_of_the_interface_returns_its_json(self):
        commands = [
            ["preview", "--json"], ["recommend", "--json"], ["detect", "--json"], ["update", "--json"],
            ["host", "check", "--json"], ["guard", "--json"], ["alerts", "list", "--json"],
            ["docs", "share", "list", "--json"], ["tools", "status", "--json"], ["tools", "recommend", "--json"],
            ["brains", "--json"], ["catalog", "--json"], ["patterns", "--json"], ["references", "--json"],
            ["tools", "list", "--json"], ["init", "--questions"], ["task", "list", "--json"],
        ]
        for argv in commands:
            with self.subTest(argv=argv):
                status, result = self.run_in_page(*argv)
                self.assertEqual((status, result["code"]), (200, 0), result["stderr"])
                self.assertIsNotNone(result["json"], result["stdout"][:200])

    def test_the_catalog_kept_between_commands_follows_the_project_files(self):
        self.assertEqual(self.run_in_page("catalog", "--json")[1]["code"], 0)
        packs = self.root / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        pack = {"id": "house-rules", "title": "House rules", "version": "1.0.0", "description": "Team rules.",
                "sources": [], "rules": [{"id": "small-changes", "instruction": "Keep changes small.",
                                          "verification": "Check the size of the diff."}]}
        (packs / "house-rules.json").write_text(json.dumps(pack), encoding="utf-8")
        self.assertIn("house-rules", self.run_in_page("catalog", "--json")[1]["json"]["packs"])
        (packs / "house-rules.json").unlink()
        self.assertNotIn("house-rules", self.run_in_page("catalog", "--json")[1]["json"]["packs"])

    def test_json_answers_drop_the_duplicate_text_and_the_keys_a_page_does_not_need(self):
        self.run_in_page("task", "new", "Show request status", "--id", "request-status")
        status, _, body = self.request("/api/run", {"argv": ["task", "show", "request-status"], "omit": ["brief"]})
        result = json.loads(body)
        self.assertEqual((status, result["stdout"]), (200, ""))
        self.assertEqual(result["json"]["id"], "request-status")
        self.assertNotIn("brief", result["json"])
        status, _, body = self.request("/api/run", {"argv": ["task", "show", "request-status"], "raw": True})
        self.assertIn('"brief"', json.loads(body)["stdout"])
        self.assertEqual(self.request("/api/run", {"argv": ["check"], "omit": "brief"})[0], 400)
        status, _, body = self.request("/api/run", {"batch": {"one": ["task", "show", "request-status"]}, "omit": ["answers"]})
        self.assertNotIn("answers", json.loads(body)["results"]["one"]["json"])

    def test_large_answers_are_compressed_for_browsers_that_accept_it(self):
        status, headers, body = self.request("/api/run", {"argv": ["catalog", "--json"]}, headers={"Accept-Encoding": "gzip"})
        self.assertEqual((status, headers["Content-Encoding"]), (200, "gzip"))
        self.assertIn("packs", json.loads(gzip.decompress(body))["json"])
        status, headers, body = self.request("/api/run", {"argv": ["catalog", "--json"]})
        self.assertIsNone(headers["Content-Encoding"])
        self.assertIn("packs", json.loads(body)["json"])

    def test_the_cache_steps_aside_when_the_cli_no_longer_has_what_it_wraps(self):
        from types import SimpleNamespace

        from openguildkit import cli
        from openguildkit.webui import Speedups

        renamed = SimpleNamespace(build_parser=object, load_catalog=object, read_lock=object)
        with Speedups().active(renamed):
            self.assertIs(renamed.load_catalog, object)
        with Speedups().active(cli):
            self.assertNotEqual(cli.load_catalog.__module__, "openguildkit.catalog")
        self.assertEqual(cli.load_catalog.__module__, "openguildkit.catalog")

    def test_an_upload_becomes_the_file_a_command_reads(self):
        status, result = self.run_in_page("task", "new", "--file", "@upload:brief.md", "--id", "request-status",
                                      uploads={"brief.md": (EXAMPLE / "brief.md").read_text(encoding="utf-8")})
        self.assertEqual((status, result["code"]), (200, 0), result["stderr"])
        self.assertEqual(self.run_in_page("task", "list", "--json")[1]["json"][0]["id"], "request-status")

    def test_what_needs_a_person_at_a_terminal_is_refused_with_the_command_to_type(self):
        self.run_in_page("task", "new", "Show request status", "--id", "request-status")
        for argv in (
            ["task", "decide", "request-status", "--approve", "--by", "Camille", "--reason", "Agreed"],
            ["task", "decide", "request-status", "--appr", "--by", "Camille", "--reason", "Agreed"],
            ["task", "waive", "request-status", "security:1", "--by", "Camille", "--reason", "Pilot",
             "--scope", "Internal", "--until", "2026-12-01"],
            ["task", "authorize", "request-status", "--action", "send-message", "--target", "Brevo", "--allow",
             "--by", "Camille", "--reason", "Launch"],
            ["alerts", "accept", "npm:semver:1", "--by", "Camille", "--reason", "Build time only"],
            ["alerts", "severity", "npm:semver:1", "--level", "high", "--by", "Camille", "--reason", "CVSS 7.5"],
            ["task", "verify", "request-status", "--cannot-run", "command:1", "--by", "Camille", "--reason",
             "No toolchain on this workstation"],
            ["task", "verify", "request-status", "--withdraw", "command:1", "--by", "Camille"],
            ["task", "clear", "request-status", "security:1", "--evidence", "tests/test_access.py",
             "--supports", "Owners only", "--by", "Camille"],
            ["task", "complete", "request-status", "--by", "Camille"],
            ["tools", "apply", "sentry", "--host", "codex"],
        ):
            with self.subTest(argv=argv[:3]):
                status, result = self.run_in_page(*argv)
                self.assertEqual(status, 403, result)
                self.assertIn("terminal", result["error"])
                self.assertTrue(result["command"].startswith("openguildkit --project "))

    def test_the_session_names_every_act_left_to_a_person(self):
        status, _, body = self.request("/api/session")
        human = json.loads(body)["human_only"]
        for command in ("task decide --approve", "task clear", "task waive", "task authorize --allow", "alerts accept",
                        "task verify --cannot-run", "task complete --by", "tools apply (live)"):
            self.assertIn(command, human)

    def test_a_signed_clearance_or_its_payload_is_not_refused_as_a_terminal_act(self):
        self.run_in_page("task", "new", "Show request status", "--id", "request-status")
        status, result = self.run_in_page("task", "clear", "request-status", "security:1", "--evidence", "x", "--supports",
                                      "y", "--by", "Camille", "--payload", "clear.json")
        self.assertEqual(status, 200)
        self.assertEqual(result["code"], 1)
        self.assertNotIn("command", result)

    def test_an_invalid_profile_from_the_page_is_refused_as_invalid_and_nothing_is_written(self):
        profile = self.root / ".openguildkit" / "project.json"
        before = profile.read_text(encoding="utf-8")
        status, _, body = self.request("/api/profile/save",
                                       {"text": json.dumps({"name": "Portail support", "research": "everywhere"})})
        answer = json.loads(body)
        self.assertEqual((status, answer["code"], answer["restored"]), (200, 1, True), answer)
        self.assertIn("research", answer["stderr"])
        self.assertNotIn("command", answer)
        self.assertEqual(profile.read_text(encoding="utf-8"), before)

    def test_a_profile_saved_from_the_page_never_weakens_a_protection(self):
        profile = self.root / ".openguildkit" / "project.json"
        saved = json.loads(profile.read_text(encoding="utf-8"))
        status, _, body = self.request("/api/profile/save", {"text": json.dumps({**saved, "guard": "enforce"})})
        self.assertEqual((status, json.loads(body)["code"]), (200, 0))
        for change, command in (({"guard": "off"}, "profile set guard off --by NAME --reason WHY"),
                                ({"guard": "enforce", "research": "public-sources"},
                                 "profile set research public-sources")):
            with self.subTest(change=change):
                status, _, body = self.request("/api/profile/save", {"text": json.dumps({**saved, **change})})
                answer = json.loads(body)
                self.assertEqual(status, 403, answer)
                self.assertIn("interactive terminal", answer["error"])
                self.assertIn(command, answer["command"])
                self.assertEqual(json.loads(profile.read_text(encoding="utf-8"))["guard"], "enforce")
        status, result = self.run_in_page("profile", "set", "guard", "observe", "--by", "Camille", "--reason", "Pilot")
        self.assertEqual(result["code"], 1)
        self.assertIn("interactive terminal", result["stderr"])
        self.assertIn("profile set guard observe", result["command"])
        self.assertEqual(json.loads(profile.read_text(encoding="utf-8"))["guard"], "enforce")

    def test_a_regulation_stops_being_active_only_at_a_terminal(self):
        from openguildkit.catalog import load_catalog
        from openguildkit.webui import weakening_changes

        patterns = load_catalog()["patterns"]
        regulation = next(pattern_id for pattern_id, item in patterns.items() if item.get("kind") == "regulation")
        method = next(pattern_id for pattern_id, item in patterns.items() if item.get("kind") != "regulation")
        before = {"patterns": [regulation, {"id": method, "components": ["web"]}]}
        self.assertEqual(weakening_changes(self.root, before, {"patterns": [regulation]}), [])
        changes = weakening_changes(self.root, before, {"patterns": [{"id": method}]})
        self.assertEqual(changes, [(f"regulation {regulation} no longer active",
                                    ["profile", "decline", regulation, "--by", "NAME", "--reason", "WHY"])])
        declined = weakening_changes(self.root, {"patterns": []}, {"declined": [{"id": regulation, "by": "A"}]})
        self.assertEqual(declined[0][1][:3], ["profile", "decline", regulation])

    def reviewed_task(self):
        """The example task, consulted and reviewed through the page."""
        self.run_in_page("task", "new", "--file", "@upload:brief.md", "--id", "request-status",
                     uploads={"brief.md": (EXAMPLE / "brief.md").read_text(encoding="utf-8")})
        self.run_in_page("task", "consult", "request-status", "--answers", "@upload:answers.json",
                     uploads={"answers.json": (EXAMPLE / "answers.json").read_text(encoding="utf-8")})
        template = self.run_in_page("task", "template", "request-status")[1]["json"]
        review = {"consultation_id": template["consultation_id"],
                  **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        self.assertEqual(self.run_in_page("task", "review", "request-status", "--file", "@upload:review.json",
                                      uploads={"review.json": json.dumps(review)})[1]["code"], 0)

    def test_the_page_revises_the_brief_when_it_consults_again_after_a_request_for_changes(self):
        self.reviewed_task()
        self.assertEqual(self.run_in_page("task", "decide", "request-status", "--request-changes", "--by", "Camille",
                                      "--reason", "Name the status labels first")[1]["code"], 0)
        status, result = self.run_in_page(
            "task", "consult", "request-status", "--answers", "@upload:answers.json", "--brief-file", "@upload:brief.md",
            uploads={"answers.json": (EXAMPLE / "answers.json").read_text(encoding="utf-8"),
                     "brief.md": "Show the four agreed status labels on each support request."})
        self.assertEqual((status, result["code"]), (200, 0), result["stderr"])
        record = self.run_in_page("task", "show", "request-status")[1]["json"]
        self.assertEqual(record["brief"], "Show the four agreed status labels on each support request.")
        self.assertEqual(record["rounds"][0]["brief"], (EXAMPLE / "brief.md").read_text(encoding="utf-8").strip())

    def test_a_failed_verification_keeps_its_recorded_checks_for_the_page(self):
        project = self.root / ".openguildkit" / "project.json"
        saved = json.loads(project.read_text(encoding="utf-8"))
        status, _, body = self.request("/api/profile/save", {"text": json.dumps(
            {**saved, "checks": ["python3 -c \"raise SystemExit(3)\""]})})
        self.assertEqual(json.loads(body)["code"], 0, body)
        self.reviewed_task()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="request-status"):
            self.assertEqual(main(["--project", str(self.root), "task", "decide", "request-status", "--approve",
                                   "--by", "Camille", "--reason", "Agreed"]), 0)
        status, result = self.run_in_page("task", "verify", "request-status")
        self.assertEqual((status, result["code"]), (200, 1))
        self.assertIn("command:1: failed", result["stdout"])
        self.assertNotIn("command", result)
        checks = self.run_in_page("task", "checks", "request-status", "--json")[1]["json"]
        command = next(item for item in checks if item["id"] == "command:1")
        self.assertEqual(command["result"]["status"], "failed")
        self.assertIn("exit code 3", command["result"]["message"])

    def test_a_terminal_prompt_fails_even_when_the_server_runs_in_a_terminal(self):
        self.run_in_page("task", "new", "Show request status", "--id", "request-status")
        with patch("sys.stdin.isatty", return_value=True):
            status, result = self.run_in_page("task", "consult", "request-status")
        self.assertEqual(status, 400)
        self.assertIn("answers", result["error"])

    def test_a_cli_refusal_that_needs_a_terminal_comes_with_the_command(self):
        self.run_in_page("task", "new", "Show request status", "--id", "request-status")
        status, result = self.run_in_page("task", "consult", "request-status", "--answers", "@upload:answers.json",
                                      uploads={"answers.json": "{}"})
        self.assertEqual(status, 200)
        self.assertNotIn("command", result)
        self.assertNotIn("reason", result)
        with patch("openguildkit.cli.main", side_effect=lambda argv: print(
                "OpenGuildKit: To dismiss X, a person runs the command at an interactive terminal.",
                file=__import__("sys").stderr) or 1):
            status, result = self.run_in_page("alerts", "set", "npm:x:1", "--status", "dismissed", "--by", "Bot", "--reason", "noise")
        self.assertEqual(result["code"], 1)
        self.assertIn("alerts set npm:x:1 --status dismissed", result["command"])
        self.assertEqual(result["reason"], "alert-status-at-terminal")

    def test_the_command_the_cli_names_in_its_refusal_is_the_one_to_type(self):
        message = ("OpenGuildKit: 1 data protection, security or AI point(s) are skipped, failed or declared not "
                   "applicable as a pack. A person confirms closing over them: openguildkit task complete "
                   "request-history --by NAME, at a terminal.")
        with patch("openguildkit.cli.main", side_effect=lambda argv: print(message, file=__import__("sys").stderr) or 1):
            status, result = self.run_in_page("task", "complete", "request-history")
        self.assertEqual((status, result["code"], result["reason"]), (200, 1, "complete-at-terminal"))
        self.assertTrue(result["command"].startswith("openguildkit --project "), result["command"])
        self.assertTrue(result["command"].endswith(" task complete request-history --by NAME"), result["command"])
        batch = self.request("/api/run", {"batch": {"close": ["task", "complete", "request-history", "--by", "Camille"]}})
        closing = json.loads(batch[2])["results"]["close"]
        self.assertEqual(closing["reason"], "complete-at-terminal")
        self.assertTrue(closing["command"].endswith(" task complete request-history --by Camille"), closing["command"])

    def test_the_named_command_keeps_its_words_and_stops_at_the_end_of_the_sentence(self):
        from openguildkit.webui import named_command

        self.assertEqual(named_command("A person confirms closing over them: openguildkit task complete t1 --by NAME, "
                                       "at a terminal."), ["task", "complete", "t1", "--by", "NAME"])
        self.assertEqual(named_command("Run openguildkit task revoke t1 --by NAME --reason WHY."),
                         ["task", "revoke", "t1", "--by", "NAME", "--reason", "WHY"])
        self.assertIsNone(named_command("To dismiss X, a person runs the command at an interactive terminal."))

    def test_every_refusal_carries_a_stable_code(self):
        from types import SimpleNamespace

        from openguildkit.webui import REFUSALS, Refused, check_request

        self.run_in_page("task", "new", "Show request status", "--id", "request-status")
        (self.root / ".env").write_text("A=1", encoding="utf-8")
        (self.root / "notes.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "big.txt").write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")
        seen = {}

        def refused_by_server(code, status, path, body=None, headers=None, method=None):
            answer_status, _, raw = self.request(path, body, headers, method)
            answer = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
            self.assertEqual((answer_status, answer.get("reason")), (status, code), answer)
            self.assertIn("error", answer)
            seen[code] = True

        def run_in_page(code, *argv, status=403):
            refused_by_server(code, status, "/api/run", {"argv": list(argv)})

        run_in_page("approve-at-terminal", "task", "decide", "request-status", "--approve", "--by", "C", "--reason", "R")
        run_in_page("cannot-run-at-terminal", "task", "verify", "request-status", "--cannot-run", "command:1", "--by", "C",
            "--reason", "R")
        run_in_page("clear-at-terminal", "task", "clear", "request-status", "security:1", "--evidence", "x", "--supports", "y",
            "--by", "C")
        run_in_page("complete-at-terminal", "task", "complete", "request-status", "--by", "C")
        run_in_page("live-plan-at-terminal", "tools", "apply", "sentry", "--host", "codex")
        run_in_page("waiver-at-terminal", "task", "waive", "request-status", "security:1", "--by", "C", "--reason", "R",
            "--scope", "S", "--until", "2026-12-01")
        run_in_page("external-action-at-terminal", "task", "authorize", "request-status", "--action", "send-message",
            "--target", "Brevo", "--allow", "--by", "C", "--reason", "R")
        run_in_page("alert-accept-at-terminal", "alerts", "accept", "npm:semver:1", "--by", "C", "--reason", "R")
        run_in_page("alert-severity-at-terminal", "alerts", "severity", "npm:semver:1", "--level", "high", "--by", "C",
            "--reason", "R")
        run_in_page("send-setup-answers", "init", status=400)
        run_in_page("send-task-answers", "task", "consult", "request-status", status=400)
        run_in_page("not-in-page", "ui")
        run_in_page("not-in-page", "guard", "--hook", "prompt")
        run_in_page("outside-project", "task", "export", "request-status", "--output", "../outside.json", status=400)
        run_in_page("outside-project", "task", "export", "request-status", "--output", ".git/record.json", status=400)
        run_in_page("bad-request", "no-such-command", status=400)
        refused_by_server("weakens-protection", 403, "/api/profile/save", {"text": json.dumps(
            {**json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8")),
             "research": "public-sources"})})
        refused_by_server("invalid-profile", 400, "/api/profile/save", {"text": "[1, 2]"})
        refused_by_server("invalid-profile", 400, "/api/profile/save", {"text": "{not json"})
        refused_by_server("secret-file", 403, "/api/files/read", {"path": ".env"})
        refused_by_server("outside-project", 403, "/api/files/read", {"path": ".git/config"})
        refused_by_server("outside-project", 400, "/api/files/read", {"path": "../x.json"})
        refused_by_server("not-readable", 403, "/api/files/read", {"path": "notes.py"})
        refused_by_server("too-large", 413, "/api/files/read", {"path": "big.txt"})
        refused_by_server("not-in-page", 403, "/api/files/write", {"path": ".openguildkit/project.json", "text": "{}"})
        refused_by_server("bad-request", 400, "/api/files/write", {"path": ".openguildkit/storybook/proposals.json", "text": "{x"})
        refused_by_server("not-found", 404, "/api/unknown", {})
        refused_by_server("not-found", 404, "/missing.js", method="GET")
        refused_by_server("bad-request", 405, "/api/run", method="GET")
        refused_by_server("bad-request", 400, "/api/run", ["task"])
        refused_by_server("bad-request", 415, "/api/run", {"argv": ["check"]}, headers={"Content-Type": "text/plain"})
        refused_by_server("too-large", 413, "/api/run", None, headers={"Content-Length": str(64 * 1024 * 1024)}, method="POST")
        refused_by_server("foreign-page", 403, "/api/run", {"argv": ["check"]}, headers={"Origin": "https://evil.example"})
        refused_by_server("foreign-page", 421, "/api/run", {"argv": ["check"]}, headers={"Host": "evil.example:80"})
        refused_by_server("stale-token", 403, "/api/run", {"argv": ["check"]}, headers={"X-OGK-Token": "from-a-stopped-server"})
        refused_by_server("open-printed-link", 403, "/api/session", headers={"Cookie": f"{self.app.cookie}=from-a-stopped-server"})
        with patch.object(self.app, "handle", side_effect=RuntimeError("boom")):
            refused_by_server("server-error", 500, "/api/run", {"argv": ["check"]})
        uninitialized = self.root / ".openguildkit" / "project.json"
        saved = uninitialized.read_text(encoding="utf-8")
        uninitialized.unlink()
        try:
            refused_by_server("not-initialized", 409, "/api/profile/save", {"text": saved})
        finally:
            uninitialized.write_text(saved, encoding="utf-8")
        status, _, body = self.request("/api/run", {"batch": {"ui": ["ui"]}})
        self.assertEqual(json.loads(body)["results"]["ui"]["reason"], "not-in-page")
        seen["not-in-page"] = True
        # The withdrawal of an approval is refused like an approval; it is checked on the parsed command.
        withdrawal = SimpleNamespace(command="task", action="revoke")
        with self.assertRaises(Refused) as refused:
            check_request(withdrawal, ["task", "revoke", "t1", "--by", "C", "--reason", "R"], self.root)
        self.assertEqual(refused.exception.reason, "withdraw-at-terminal")
        self.assertIn("task revoke t1", refused.exception.command)
        seen["withdraw-at-terminal"] = True
        # A refusal of the CLI itself that needs a terminal: the code follows the command the page sent.
        terminal = "OpenGuildKit: a person runs the command at an interactive terminal."
        with patch("openguildkit.cli.main", side_effect=lambda argv: print(terminal, file=__import__("sys").stderr) or 1):
            for code, argv in (("alert-status-at-terminal", ["alerts", "set", "npm:x:1", "--status", "dismissed",
                                                             "--by", "C", "--reason", "R"]),
                               ("weakens-protection", ["profile", "set", "guard", "off", "--by", "C", "--reason", "R"]),
                               ("person-at-terminal", ["host", "apply"])):
                with self.subTest(code=code):
                    self.assertEqual(self.run_in_page(*argv)[1]["reason"], code)
                    seen[code] = True
        self.assertEqual(sorted(seen), sorted(REFUSALS))

    def test_every_code_is_listed_in_the_interface_documentation(self):
        from openguildkit.webui import REFUSALS

        text = (Path(__file__).resolve().parents[1] / "web" / "docs" / "interface-projet.md").read_text(encoding="utf-8")
        missing = [code for code in REFUSALS if f"`{code}`" not in text]
        self.assertEqual(missing, [])

    def test_paths_stay_inside_the_project(self):
        self.run_in_page("task", "new", "Show request status", "--id", "request-status")
        status, result = self.run_in_page("task", "export", "request-status", "--output", "../outside.json")
        self.assertEqual(status, 400)
        self.assertIn("inside the project", result["error"])
        self.assertEqual(self.run_in_page("ui")[0], 403)
        self.assertEqual(self.run_in_page("--project", "..", "check")[0], 400)

    def test_malformed_requests_and_commands_that_do_not_belong_in_a_page_are_refused(self):
        self.assertEqual(self.request("/api/run", method="GET")[0], 405)
        self.assertEqual(self.request("/api/unknown", {})[0], 404)
        self.assertEqual(self.request("/api/run", ["task"])[0], 400)
        self.assertEqual(self.request("/api/run", {"argv": []})[0], 400)
        self.assertEqual(self.request("/api/run", {"argv": ["task", "list"], "uploads": {"../x": "1"}})[0], 400)
        self.assertEqual(self.request("/api/run", {"argv": ["task", "new", "--file", "@upload:missing.md"]})[0], 400)
        self.assertEqual(self.request("/api/run", {"argv": ["no-such-command"]})[0], 400)
        status, _, _ = self.request("/api/run", None, headers={"Content-Length": str(64 * 1024 * 1024)}, method="POST")
        self.assertEqual(status, 413)
        for argv, expected in (
            (["init"], 400),
            (["integrations", "--host", "codex", "--user"], 403),
            (["tools", "mock", "jira"], 403),
            (["guard", "--hook", "prompt"], 403),
            (["ci-check", "--target-repo", ".", "--commit", "0" * 40], 403),
            (["storybook", "extract", "--src", "../elsewhere"], 400),
            (["tools", "apply", "jira", "--mock", "--log", "../calls.jsonl"], 400),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_in_page(*argv)[0], expected)

    def test_a_batch_runs_each_command_and_reports_each_refusal(self):
        status, _, body = self.request("/api/run", {"batch": {"tasks": ["task", "list", "--json"], "ui": ["ui"]}})
        results = json.loads(body)["results"]
        self.assertEqual(status, 200)
        self.assertEqual(results["tasks"]["json"], [])
        self.assertEqual(results["ui"]["code"], 1)
        self.assertEqual(self.request("/api/run", {"batch": {str(i): ["check"] for i in range(41)}})[0], 400)

    def test_only_valid_storybook_proposals_are_written(self):
        path = ".openguildkit/storybook/proposals.json"
        self.assertEqual(self.request("/api/files/write", {"path": path, "text": "{not json"})[0], 400)
        status, _, _ = self.request("/api/files/write", {"path": path, "text": json.dumps({"components": []})})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads((self.root / path).read_text(encoding="utf-8")), {"components": []})
        self.assertEqual(self.request("/api/profile/save", {"text": "[1, 2]"})[0], 400)

    def test_files_are_read_inside_the_project_except_secrets(self):
        (self.root / ".env").write_text("TOKEN=1", encoding="utf-8")
        status, _, body = self.request("/api/files/read", {"path": ".openguildkit/project.json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(json.loads(body)["text"])["name"], "Portal")
        self.assertEqual(self.request("/api/files/read", {"path": ".env"})[0], 403)
        status, _, body = self.request("/api/files/read", {"path": ".openguildkit/storybook/proposals.json"})
        self.assertEqual((status, json.loads(body)["text"], json.loads(body)["missing"]), (200, None, True))
        self.assertEqual(self.request("/api/files/read", {"path": "../x.json"})[0], 400)
        status, _, body = self.request("/api/files/list", {"path": "."})
        self.assertNotIn(".env", [entry["name"] for entry in json.loads(body)["entries"]])
        self.assertEqual(self.request("/api/files/write", {"path": ".openguildkit/project.json", "text": "{}"})[0], 403)

    def test_the_front_end_is_served_with_a_content_security_policy(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"OGK", body)
        self.assertIn(b'<meta name="openguildkit-ui" content="1">', body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("immutable", self.request("/assets/app-0123456789.js")[1]["Cache-Control"])
        self.assertEqual(self.request("/../profile.json")[0], 404)
        self.assertEqual(self.request("/%2e%2e/profile.json")[0], 404)
        self.assertEqual(self.request("/", method="HEAD")[0], 200)


class UiCommandTests(unittest.TestCase):
    """The ui command itself, started in a subprocess as a person starts it, then stopped."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.root = self.folder / "portal"
        self.root.mkdir()
        self.front = fake_front(self.folder / "dist")

    def start(self, *options):
        """Start openguildkit ui and return the process with the address it printed."""
        process = subprocess.Popen(
            [sys.executable, "-m", "openguildkit", "--project", str(self.root), "ui", "--no-browser", *options],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=ENV)
        watchdog = threading.Timer(120, process.kill)
        watchdog.start()
        self.addCleanup(watchdog.cancel)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        for line in process.stdout:
            if line.startswith("http://"):
                return process, line.strip()
        self.fail(f"openguildkit ui printed no address: {process.communicate()[1]}")

    @staticmethod
    def stop(process) -> tuple[int, str]:
        """Ctrl+C where the system can send it; Windows has no such signal for a process of the same console."""
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGINT)
        _, stderr = process.communicate(timeout=60)
        return process.returncode, stderr

    def open_session(self, url: str) -> dict:
        port = int(url.split(":")[2].split("/")[0])
        status, _, body = fetch(port, "/api/session")
        self.assertEqual((status, json.loads(body)["reason"]), (403, "open-printed-link"))
        status, headers, _ = fetch(port, url.split(f":{port}", 1)[1])
        self.assertEqual(status, 303)
        status, _, body = fetch(port, "/api/session", headers["Set-Cookie"].split(";")[0])
        self.assertEqual(status, 200)
        return {**json.loads(body), "port": port, "cookie": headers["Set-Cookie"].split(";")[0]}

    def test_the_command_prints_the_address_that_opens_the_session_and_stops_on_ctrl_c(self):
        process, url = self.start("--port", "0", "--static", str(self.front))
        self.assertRegex(url, r"^http://127\.0\.0\.1:\d+/\?key=[A-Za-z0-9_-]{40,}$")
        session = self.open_session(url)
        self.assertEqual(session["project"]["root"], str(self.root))
        self.assertFalse(session["project"]["initialized"])
        self.assertEqual(fetch(session["port"], "/", session["cookie"])[0], 200)
        code, stderr = self.stop(process)
        if os.name != "nt":
            self.assertEqual(code, 0, stderr)
            self.assertIn("OpenGuildKit interface stopped.", stderr)

    def test_a_busy_port_gives_way_to_a_free_one(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(blocker.close)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        busy = blocker.getsockname()[1]
        process, url = self.start("--port", str(busy), "--static", str(self.front))
        session = self.open_session(url)
        self.assertNotEqual(session["port"], busy)
        _, stderr = self.stop(process)
        self.assertIn(f"Port {busy} is busy; using {session['port']}.", stderr)

    def test_without_a_built_front_end_the_page_says_how_to_build_it(self):
        empty = self.folder / "empty"
        empty.mkdir()
        process, url = self.start("--port", "0", "--static", str(empty))
        session = self.open_session(url)
        status, _, page = fetch(session["port"], "/", session["cookie"])
        self.assertEqual(status, 503)
        self.assertIn(b"npm ci", page)
        _, stderr = self.stop(process)
        self.assertIn("the web interface is not built", stderr)

    def test_the_front_end_is_found_in_the_package_or_the_source_checkout(self):
        package = self.folder / "src" / "openguildkit"
        package.mkdir(parents=True)
        with patch.object(webui, "__file__", str(package / "webui.py")):
            self.assertIsNone(webui.find_front_end(None))
            built = fake_front(self.folder / "web" / "dist")
            self.assertEqual(webui.find_front_end(None), built)
            bundled = fake_front(package / "web_dist")
            os.utime(built / "index.html", (1, 1))
            self.assertEqual(webui.find_front_end(None), bundled)
        self.assertIsNone(webui.find_front_end(self.folder / "empty"))
        self.assertEqual(webui.find_front_end(self.front), self.front)


if __name__ == "__main__":
    unittest.main()
