import contextlib
import gzip
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.storage import write_json
from openguildkit.webui import make_server

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"


class WebInterfaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "portal"
        self.root.mkdir()
        front = Path(temporary.name).resolve() / "dist"
        (front / "assets").mkdir(parents=True)
        (front / "index.html").write_text("<!doctype html><html><head><title>OGK</title></head></html>", encoding="utf-8")
        (front / "assets" / "app-0123456789.js").write_text("console.log(1)", encoding="utf-8")
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
        default = {"Origin": self.base, "X-OGK-Token": self.app.token, "Content-Type": "application/json"}
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, headers={**default, **(headers or {})},
                                         method=method or ("POST" if body is not None else "GET"))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.headers, error.read()

    def run_cli(self, *argv, uploads=None):
        status, _, body = self.request("/api/run", {"argv": list(argv), "uploads": uploads or {}})
        return status, json.loads(body)

    def test_the_session_gives_the_token_and_the_project(self):
        status, headers, body = self.request("/api/session")
        self.assertEqual(status, 200)
        session = json.loads(body)
        self.assertEqual(session["token"], self.app.token)
        self.assertTrue(session["project"]["initialized"])
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_a_foreign_host_origin_or_token_is_refused(self):
        self.assertEqual(self.request("/api/session", headers={"Host": "evil.example:80"})[0], 421)
        self.assertEqual(self.request("/api/run", {"argv": ["check"]}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/api/run", {"argv": ["check"]}, headers={"X-OGK-Token": "guess"})[0], 403)
        self.assertEqual(self.request("/api/run", {"argv": ["check"]}, headers={"Content-Type": "text/plain"})[0], 415)

    def test_a_command_runs_and_returns_its_json(self):
        status, result = self.run_cli("task", "list", "--json")
        self.assertEqual(status, 200)
        self.assertEqual((result["code"], result["json"]), (0, []))

    def test_concurrent_requests_keep_their_own_output(self):
        results = []

        def call(argv):
            results.append((argv[0], self.run_cli(*argv)[1]))

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
                status, result = self.run_cli(*argv)
                self.assertEqual((status, result["code"]), (200, 0), result["stderr"])
                self.assertIsNotNone(result["json"], result["stdout"][:200])

    def test_the_catalog_kept_between_commands_follows_the_project_files(self):
        self.assertEqual(self.run_cli("catalog", "--json")[1]["code"], 0)
        packs = self.root / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        pack = {"id": "house-rules", "title": "House rules", "version": "1.0.0", "description": "Team rules.",
                "sources": [], "rules": [{"id": "small-changes", "instruction": "Keep changes small.",
                                          "verification": "Check the size of the diff."}]}
        (packs / "house-rules.json").write_text(json.dumps(pack), encoding="utf-8")
        self.assertIn("house-rules", self.run_cli("catalog", "--json")[1]["json"]["packs"])
        (packs / "house-rules.json").unlink()
        self.assertNotIn("house-rules", self.run_cli("catalog", "--json")[1]["json"]["packs"])

    def test_json_answers_drop_the_duplicate_text_and_the_keys_a_page_does_not_need(self):
        self.run_cli("task", "new", "Show request status", "--id", "request-status")
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
        status, result = self.run_cli("task", "new", "--file", "@upload:brief.md", "--id", "request-status",
                                      uploads={"brief.md": (EXAMPLE / "brief.md").read_text(encoding="utf-8")})
        self.assertEqual((status, result["code"]), (200, 0), result["stderr"])
        self.assertEqual(self.run_cli("task", "list", "--json")[1]["json"][0]["id"], "request-status")

    def test_what_needs_a_person_at_a_terminal_is_refused_with_the_command_to_type(self):
        self.run_cli("task", "new", "Show request status", "--id", "request-status")
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
                status, result = self.run_cli(*argv)
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
        self.run_cli("task", "new", "Show request status", "--id", "request-status")
        status, result = self.run_cli("task", "clear", "request-status", "security:1", "--evidence", "x", "--supports",
                                      "y", "--by", "Camille", "--payload", "clear.json")
        self.assertEqual(status, 200)
        self.assertEqual(result["code"], 1)
        self.assertNotIn("command", result)

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
        status, result = self.run_cli("profile", "set", "guard", "observe", "--by", "Camille", "--reason", "Pilot")
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
        self.run_cli("task", "new", "--file", "@upload:brief.md", "--id", "request-status",
                     uploads={"brief.md": (EXAMPLE / "brief.md").read_text(encoding="utf-8")})
        self.run_cli("task", "consult", "request-status", "--answers", "@upload:answers.json",
                     uploads={"answers.json": (EXAMPLE / "answers.json").read_text(encoding="utf-8")})
        template = self.run_cli("task", "template", "request-status")[1]["json"]
        review = {"consultation_id": template["consultation_id"],
                  **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        self.assertEqual(self.run_cli("task", "review", "request-status", "--file", "@upload:review.json",
                                      uploads={"review.json": json.dumps(review)})[1]["code"], 0)

    def test_the_page_revises_the_brief_when_it_consults_again_after_a_request_for_changes(self):
        self.reviewed_task()
        self.assertEqual(self.run_cli("task", "decide", "request-status", "--request-changes", "--by", "Camille",
                                      "--reason", "Name the status labels first")[1]["code"], 0)
        status, result = self.run_cli(
            "task", "consult", "request-status", "--answers", "@upload:answers.json", "--brief-file", "@upload:brief.md",
            uploads={"answers.json": (EXAMPLE / "answers.json").read_text(encoding="utf-8"),
                     "brief.md": "Show the four agreed status labels on each support request."})
        self.assertEqual((status, result["code"]), (200, 0), result["stderr"])
        record = self.run_cli("task", "show", "request-status")[1]["json"]
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
        status, result = self.run_cli("task", "verify", "request-status")
        self.assertEqual((status, result["code"]), (200, 1))
        self.assertIn("command:1: failed", result["stdout"])
        self.assertNotIn("command", result)
        checks = self.run_cli("task", "checks", "request-status", "--json")[1]["json"]
        command = next(item for item in checks if item["id"] == "command:1")
        self.assertEqual(command["result"]["status"], "failed")
        self.assertIn("exit code 3", command["result"]["message"])

    def test_a_terminal_prompt_fails_even_when_the_server_runs_in_a_terminal(self):
        self.run_cli("task", "new", "Show request status", "--id", "request-status")
        with patch("sys.stdin.isatty", return_value=True):
            status, result = self.run_cli("task", "consult", "request-status")
        self.assertEqual(status, 400)
        self.assertIn("answers", result["error"])

    def test_a_cli_refusal_that_needs_a_terminal_comes_with_the_command(self):
        self.run_cli("task", "new", "Show request status", "--id", "request-status")
        status, result = self.run_cli("task", "consult", "request-status", "--answers", "@upload:answers.json",
                                      uploads={"answers.json": "{}"})
        self.assertEqual(status, 200)
        self.assertNotIn("command", result)
        with patch("openguildkit.cli.main", side_effect=lambda argv: print(
                "OpenGuildKit: To dismiss X, a person runs the command at an interactive terminal.",
                file=__import__("sys").stderr) or 1):
            status, result = self.run_cli("alerts", "set", "npm:x:1", "--status", "dismissed", "--by", "Bot", "--reason", "noise")
        self.assertEqual(result["code"], 1)
        self.assertIn("alerts set npm:x:1 --status dismissed", result["command"])

    def test_paths_stay_inside_the_project(self):
        self.run_cli("task", "new", "Show request status", "--id", "request-status")
        status, result = self.run_cli("task", "export", "request-status", "--output", "../outside.json")
        self.assertEqual(status, 400)
        self.assertIn("inside the project", result["error"])
        self.assertEqual(self.run_cli("ui")[0], 403)
        self.assertEqual(self.run_cli("--project", "..", "check")[0], 400)

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
                self.assertEqual(self.run_cli(*argv)[0], expected)

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


if __name__ == "__main__":
    unittest.main()
