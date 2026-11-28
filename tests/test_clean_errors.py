import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.catalog import CatalogError, load_catalog, validate_entry
from openguildkit.cli import main
from openguildkit.prompts import prompt_choices
from openguildkit.storage import write_json
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"


class CleanErrorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments, code=1):
        return run_cli(self.root, *arguments, expect=code).stderr

    def init(self):
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
        self.run_cli("init", "--answers", self.root / "answers.json", code=0)

    def output(self, *arguments) -> str:
        return run_cli(self.root, *arguments).stdout

    def consulted(self, profile=None):
        write_json(self.root / "profile.json", profile or json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")))
        self.run_cli("init", "--answers", self.root / "profile.json", code=0)
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK, code=0)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json", code=0)
        template = json.loads(self.output("task", "template", TASK))
        return {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}

    def reviewed(self):
        write_json(self.root / "review.json", self.consulted())
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json", code=0)

    def approved(self):
        self.reviewed()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", code=0)

    def test_deeply_nested_json_is_an_input_error(self):
        # OGK-CORE-009
        nested = self.root / "nested.json"
        nested.write_text('{"a":' + "[" * 300000 + "]" * 300000 + "}", encoding="utf-8")
        error = self.run_cli("recommend", "--answers", nested)
        self.assertIn("nested too deeply", error)

    def test_json_nested_too_deeply_in_a_file_of_the_project_is_one_line(self):
        """Issue #460: a file of 200 000 [ then 200 000 ] gave a RecursionError traceback in six commands."""
        # OGK-CORE-002, OGK-TOOLS-001, OGK-TOOLS-005
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"],
                                                "host": "claude-code", "guard": "observe"})
        self.run_cli("init", "--answers", self.root / "profile.json", code=0)
        refused = [(".openguildkit/catalog/tools/deep.json", ("tools", "list")),
                   (".openguildkit/catalog/deliverables/deep.json", ("deliverable", "list")),
                   (".openguildkit/catalog/tool-mocks/github.json", ("tools", "call", "github", "x")),
                   (".openguildkit/catalog/references/deep.json", ("references", "x")),
                   (".openguildkit/catalog/packs/deep.json", ("tools", "list")),
                   (".claude/settings.json", ("host", "check")),
                   (".claude/settings.json", ("check",)),
                   (".mcp.json", ("tools", "status")),
                   ("package.json", ("init", "--questions"))]
        for name, command in refused:
            with self.subTest(name=name, command=command):
                target = self.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
                result = run_cli(self.root, *command, expect=None, subprocess_mode=True)
                target.unlink()
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
                self.assertIn(f"{Path(name).as_posix()}", result.stderr.replace("\\", "/"))
                self.assertIn("nested too deeply", result.stderr)

    def test_end_of_input_has_a_message(self):
        self.init()
        self.run_cli("task", "new", "Show statuses.", "--id", "status", code=0)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=EOFError):
            error = self.run_cli("task", "consult", "status")
        self.assertIn("Input ended before completion.", error)

    def test_undecodable_arguments_are_reported_without_a_traceback(self):
        if os.name != "posix":
            self.skipTest("byte arguments are a POSIX case")
        result = subprocess.run(
            [sys.executable, "-m", "openguildkit", "--project", str(self.root), "brains", "--id", b"\xff"],
            capture_output=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"OpenGuildKit [OGK-CATALOG-002]: Unknown brain", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_a_project_folder_that_does_not_exist_is_named_in_one_sentence(self):
        missing = self.root / "nowhere"
        for command in (("check",), ("task", "list")):
            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["--project", str(missing), *command]), 1)
            self.assertEqual(stderr.getvalue().strip(), f"OpenGuildKit: The project folder {missing.as_posix()} does not "
                             "exist. Check --project, or create the folder and run openguildkit init in it.")
        (self.root / "file.txt").write_text("x", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["--project", str(self.root / "file.txt"), "check"]), 1)
        self.assertIn("file.txt is not a folder", stderr.getvalue())

    def test_hand_edited_task_records_are_reported_as_damaged(self):
        self.init()
        self.run_cli("task", "new", "Show statuses.", "--id", "status", code=0)
        path = self.root / ".openguildkit" / "tasks" / "status.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for change in ({"brief": 5}, {"status": "approved"}, {"rounds": 5}, {"rounds": [1]}, {"status": "unknown"},
                       {"status": [["x"]]}, {"created_at": {"x": "y"}}):
            path.write_text(json.dumps({**original, **change}), encoding="utf-8")
            for command in (("task", "questions", "status"), ("task", "handoff", "status"), ("task", "list")):
                error = self.run_cli(*command, code=0 if command == ("task", "list") else 1)
                if command != ("task", "list"):
                    self.assertIn("Task record status is damaged: ", error)
                    self.assertIn("Restore .openguildkit/tasks/status.json from a backup, or delete that file and open a "
                                  "new task with openguildkit task new.", error)
        path.write_text(json.dumps({key: value for key, value in original.items() if key != "status"}), encoding="utf-8")
        self.assertIn("is damaged", self.run_cli("task", "show", "status"))

    def test_a_damaged_field_deep_in_a_task_record_is_named_once_at_load(self):
        """The crashes the robustness suite found: each wrong type is one message naming the field."""
        self.reviewed()
        path = self.root / ".openguildkit" / "tasks" / "request-status.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        cases = {
            "review.boards[0].challenge must be an object": lambda r: r["review"]["boards"][0].update(challenge="x"),
            "review.boards[0].challenge.blockers must be a list": lambda r: r["review"]["boards"][0]["challenge"]
            .update(blockers=5),
            "consultation.review_template.boards[0] must be an object": lambda r: r["consultation"]["review_template"]
            .update(boards=[["x"]]),
            "consultation.review_template.boards[0].challenge.specialists[0] must be an object":
                lambda r: r["consultation"]["review_template"]["boards"][0]["challenge"].update(specialists=["x"]),
            "created_at must be text": lambda r: r.update(created_at={"x": "y"}),
            "status must be one of": lambda r: r.update(status=[["x"]]),
        }
        for field, change in cases.items():
            damaged = json.loads(json.dumps(record))
            change(damaged)
            path.write_text(json.dumps(damaged), encoding="utf-8")
            for command in (("task", "show"), ("task", "challenge"), ("task", "progress")):
                error = self.run_cli(*command, "request-status")
                self.assertTrue(error.startswith(f"OpenGuildKit [OGK-TASK-023]: Task record request-status is damaged: {field}"),
                                error)
                self.assertEqual(len(error.strip().splitlines()), 1, error)
                self.assertTrue(error.strip().endswith("or delete that file and open a new task with openguildkit task new."),
                                error)
            listed = json.loads(self.list_json())
            self.assertEqual(listed[0]["status"], "unreadable")

    def list_json(self):
        return self.output("task", "list", "--json")

    def refusal(self, *arguments) -> str:
        """The one-line refusal of a command; a traceback fails the test."""
        error = self.run_cli(*arguments)
        self.assertRegex(error, r"^OpenGuildKit(?: \[OGK-[A-Z]+-\d{3}\])?: ")
        return error.strip()

    def test_task_answers_of_the_wrong_type_name_the_file_and_the_field(self):
        self.init()
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK, code=0)
        answers = json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8"))
        path = self.root / "answers.json"
        for change, field in (({"kind": ["feature"]}, "kind"), ({"kind": {}}, "kind"), ({"surface": [["customer"]]}, "surface")):
            write_json(path, {**answers, **change})
            for action in ("questions", "route", "consult"):
                error = self.refusal("task", action, TASK, "--answers", path)
                self.assertIn(f"{path.as_posix()}: Choose", error)
                self.assertIn(field, error)

    def test_a_deliberation_response_of_the_wrong_type_names_the_file(self):
        self.reviewed()
        payload = json.loads(self.output("task", "deliberate", TASK))["template"]
        path = self.root / "deliberation.json"
        for field, value in (("objection", 7), ("board", {"id": "x"}), ("position", ["maintain"])):
            broken = json.loads(json.dumps(payload))
            broken["responses"][0][field] = value
            write_json(path, broken)
            error = self.refusal("task", "respond", TASK, "--file", path)
            self.assertIn(path.as_posix(), error)
            self.assertIn(field, error)

    def test_every_refusal_of_a_result_names_the_accepted_values_and_the_template(self):
        """task result with a list or a number as check was fixed by the results change; the hint is new."""
        self.approved()
        rule = next(check["id"] for check in json.loads(self.output("task", "checks", TASK, "--json")) if check["kind"] == "rule")
        path = self.root / "result.json"
        cases = {
            "names its ID as text": {"revision": "abc1234", "checks": [{"check": ["command:1"], "status": "passed"}]},
            "names its ID as text.": {"revision": "abc1234", "checks": [{"check": 5, "status": "passed"}]},
            "met or not-met, not 'done'": {"revision": "abc1234",
                                           "criteria": [{"criterion": "x", "status": "done", "evidence": "y"}]},
            "passed, failed, skipped, not-applicable": {"revision": "abc1234",
                                                        "checks": [{"check": rule, "status": "ok"}]},
            "revision or pull request": {"criteria": []},
            "criteria must be a list": {"revision": "abc1234", "criteria": "met"},
        }
        for message, payload in cases.items():
            write_json(path, payload)
            error = self.refusal("task", "result", TASK, "--file", path)
            self.assertIn(path.as_posix(), error)
            self.assertIn(message, error)
            self.assertIn(f"task result {TASK} --template", error)

    def test_evidence_dates_must_be_real_and_past_and_cited_files_must_exist(self):
        # OGK-BOARD-004
        review = self.consulted()
        path = self.root / "review.json"
        later = (clock.real_today() + timedelta(days=3)).isoformat()
        for change, message in (({"source": "measurement", "date": "2026-99-99"}, "not a real date"),
                                ({"source": "measurement", "date": later}, "in the future"),
                                ({"source": "project-file", "ref": "nowhere/does-not-exist.txt"}, "not a file or folder"),
                                # OGK-BOARD-015
                                ({"source": "test", "ref": "tests/missing.py::test_x"}, "not a file or folder")):
            broken = json.loads(json.dumps(review))
            broken["boards"][0]["evidence"][0].update(change)
            write_json(path, broken)
            error = self.refusal("task", "review", TASK, "--file", path)
            self.assertIn(message, error)
            self.assertIn(path.as_posix(), error)
        self.assertEqual(json.loads(self.output("task", "show", TASK, "--json"))["status"], "consulting")
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        cited = json.loads(json.dumps(review))
        cited["boards"][0]["evidence"][0].update(source="project-file", ref="src/app.py:1")
        write_json(path, cited)
        self.run_cli("task", "review", TASK, "--file", path, code=0)

    def test_task_creation_warns_about_sensitive_values_without_echoing_them(self):
        self.init()
        credential = "AKIA" + "A" * 16
        email = "alex@example.org"
        password = "only synthetic data"
        brief = self.root / "brief.txt"
        brief.write_text(f'Publish with {credential} and password="{password}". Contact {email}.', encoding="utf-8")
        warning = self.run_cli("task", "new", "--file", brief, "--id", TASK, code=0)
        self.assertIn("replaced a possible credential", warning)
        self.assertIn("contains an email address", warning)
        saved = json.loads(self.output("task", "show", TASK, "--json"))["brief"]
        self.assertEqual(saved, f"Publish with [credential] and password=[password]. Contact {email}.")
        for value in (credential, email, password):
            self.assertNotIn(value, warning)

    def test_public_evidence_rejects_private_hosts_and_credentials(self):
        # OGK-GUARD-016
        review = self.consulted()
        path = self.root / "review.json"
        evidence = review["boards"][0]["evidence"][0]
        evidence.update(source="public", date="2026-01-01")
        for link, message in (
            ("https://localhost:8000/report", "needs a public host"),
            ("https://wiki.company.internal/report", "needs a public host"),
            ("https://192.168.4.1/report", "needs a public host"),
            ("https://[::1]/report", "needs a public host"),
            ("https://user:password@example.org/report", "without credentials"),
            ("https://example.org/report?%61ccess_token=demo", "without credentials"),
            ("https://example.org/report?key=sk_test_" + "x" * 24, "without credentials"),
        ):
            evidence["ref"] = link
            write_json(path, review)
            error = self.refusal("task", "review", TASK, "--file", path)
            self.assertIn(message, error)
            self.assertNotIn(link, error)
        evidence["ref"] = "https://docs.example.org/report?section=projects"
        write_json(path, review)
        self.run_cli("task", "review", TASK, "--file", path, code=0)

    def test_the_review_template_shows_an_evidence_item_and_every_board_problem_comes_at_once(self):
        review = self.consulted()
        template = json.loads(self.output("task", "template", TASK))
        self.assertEqual(set(template["evidence_item"]), {"source", "ref", "supports", "date", "revision"})
        self.assertIn("Write each evidence item in this shape", self.output("task", "pass", TASK, "security"))
        broken = {**review, "evidence_item": template["evidence_item"]}
        for entry in broken["boards"][:3]:
            entry["recommendation"] = ""
        write_json(self.root / "review.json", broken)
        error = self.refusal("task", "review", TASK, "--file", self.root / "review.json")
        # OGK-BOARD-013
        self.assertIn("The review has 3 problems", error)
        for entry in broken["boards"][:3]:
            self.assertIn(f"{entry['id']}.recommendation must contain text", error)

    def test_malformed_host_hook_files_name_the_file_and_the_field(self):
        for host, name in (("codex", ".codex/hooks.json"), ("claude-code", ".claude/settings.json")):
            with self.subTest(host=host):
                shutil.rmtree(self.root / ".openguildkit", ignore_errors=True)
                write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], "host": host, "guard": "observe"})
                self.run_cli("init", "--answers", self.root / "profile.json", code=0)
                target = self.root / name
                target.parent.mkdir(exist_ok=True)
                for text, message in (("[]", "must hold a JSON object"), ("{bad", "is not valid JSON"),
                                      ('{"hooks": {"Stop": [{"hooks": null}]}}', "hooks.Stop[0].hooks must be a list")):
                    target.write_text(text, encoding="utf-8")
                    for command in (("host", "check"), ("host", "apply"), ("check",)):
                        error = self.refusal(*command)
                        self.assertIn(name, error)
                        self.assertIn(message, error)
                target.unlink()

    def test_messages_point_to_a_step_that_can_be_taken(self):
        # A project pack declares the conflict: no two bundled packs conflict any more.
        write_json(self.root / ".openguildkit" / "catalog" / "packs" / "fixed-sprint-scope.json", {
            "id": "fixed-sprint-scope", "title": "Fixed sprint scope", "version": "1.0.0",
            "description": "For a team that freezes its work for the length of a sprint.", "sources": [],
            "conflicts_with": ["kanban-delivery"],
            "rules": [{"id": "freeze-sprint-scope", "instruction": "Start no new item before the sprint ends.",
                       "verification": "Compare the items started with the sprint plan."}],
        })
        write_json(self.root / "conflict.json", {"personal_data": "no", "name": "c", "packs": ["kanban-delivery", "fixed-sprint-scope"]})
        error = self.refusal("init", "--answers", self.root / "conflict.json")
        self.assertIn("the file passed to init --answers", error)
        self.assertFalse((self.root / ".openguildkit" / "project.json").exists())
        self.consulted()
        brief = self.output("task", "brief", TASK)
        self.assertIn("Public research is off for this project and this host agent has no setting that enforces it", brief)
        self.assertNotIn("does not block public research", brief)
        profile = self.root / ".openguildkit" / "project.json"
        profile.write_text(profile.read_text(encoding="utf-8").replace('"general"', '"retired-sector"'), encoding="utf-8")
        error = self.refusal("task", "list")
        self.assertIn("set it in .openguildkit/project.json", error)

    def test_a_decision_handoff_and_a_completion_with_open_points_say_how_to_link_a_follow_up(self):
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")),
                                                "checks": [], "waivers": {"allowed_by": ["Camille"], "max_days": 30}})
        self.run_cli("init", "--answers", self.root / "profile.json", code=0)
        self.run_cli("task", "new", "Choose how customers follow their requests.", "--id", "choice", code=0)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")), "kind": "decision",
                   "options": "A portal page or emails."}
        answers.pop("outcome", None)
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", "choice", "--answers", self.root / "answers.json", code=0)
        template = json.loads(self.output("task", "template", "choice"))
        review = json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"], **review})
        self.run_cli("task", "review", "choice", "--file", self.root / "review.json", code=0)
        payload = json.loads(self.output("task", "deliberate", "choice"))["template"]
        for response in payload["responses"]:
            response.update(position="maintain", response="Holds.", evidence_refs=[1])
        payload["decision_needed"] = "Choose the channel."
        write_json(self.root / "deliberation.json", payload)
        self.run_cli("task", "respond", "choice", "--file", self.root / "deliberation.json", code=0)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="choice"):
            self.run_cli("task", "decide", "choice", "--approve", "--by", "Camille", "--reason", "Agreed", code=0)
        self.assertIn('openguildkit task new "BRIEF" --follows choice', self.output("task", "handoff", "choice"))
        checks = json.loads(self.output("task", "checks", "choice", "--json"))
        outcomes = [{"check": check["id"], "status": "skipped", "reason": "Not this time.", "owner": "Camille"}
                    for check in checks if check["kind"] == "rule" and not check["mandatory"]]
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": outcomes})
        self.run_cli("task", "result", "choice", "--file", self.root / "result.json", code=0)
        # Security rules are skipped: closing over them needs the person's name at a terminal.
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="choice"):
            output = self.output("task", "complete", "choice", "--by", "Camille")
        self.assertIn("done-with-reservations", output)
        # The open points were shown at the confirmation prompt; the record keeps them.
        record = json.loads(self.output("task", "show", "choice", "--json"))
        self.assertIn("Disagreements between boards left open", json.dumps(record["result"]["closing"]["open_points"]))
        self.assertIn('openguildkit task new "BRIEF" --follows choice', output)
        self.run_cli("task", "new", "Add the portal page.", "--id", "page", "--follows", "choice", code=0)

    @unittest.skipUnless(os.name == "posix", "file modes are POSIX")
    def test_new_files_follow_the_umask(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.init()
        for name in ("AGENTS.md", "CLAUDE.md", ".openguildkit/project.json"):
            self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o644, name)

    def test_a_failed_command_leaves_no_state_folder(self):
        # OGK-PROJECT-026
        self.assertIn("No OpenGuildKit project found", self.run_cli("sync"))
        self.assertFalse((self.root / ".openguildkit").exists())

    def test_outside_a_project_the_message_says_so_before_proposing_init(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()), \
                patch("openguildkit.project.Path.cwd", return_value=outside):
            self.assertEqual(main(["check"]), 1)
        message = stderr.getvalue()
        self.assertIn("No OpenGuildKit project found", message)
        self.assertIn(".openguildkit/project.json does not exist", message)
        self.assertIn(outside.resolve().as_posix(), message)
        for words in ("cd ", "--project", "openguildkit init"):
            self.assertIn(words, message)
        self.assertLess(message.index("--project"), message.index("openguildkit init"))
        self.assertEqual(len(message.strip().splitlines()), 1)

    def test_an_unknown_task_id_proposes_the_closest_one_or_task_list(self):
        self.consulted()
        self.assertIn(f"Did you mean {TASK}?", self.run_cli("task", "handoff", "request-staus"))
        message = self.run_cli("task", "show", "zzz")
        self.assertIn("Unknown task: zzz", message)
        self.assertIn("openguildkit task list", message)
        self.assertNotIn("Did you mean", message)

    def test_prompt_and_identifier_messages_are_precise(self):
        # OGK-TASK-019
        question = {"type": "multi-select", "choices": [{"id": "a"}, {"id": "b"}]}
        self.assertEqual(prompt_choices(question, "1,"), ["a"])
        self.init()
        self.assertIn("reserved file name", self.run_cli("task", "new", "x", "--id", "con"))
        self.assertIn("task ID is empty", self.run_cli("task", "new", "x", "--id", ""))
        write_json(self.root / "policy.json", {"personal_data": "no", "name": "x", "packs": ["export-link-expiry"]})
        self.assertIn("--policy-repo", self.run_cli("preview", "--answers", self.root / "policy.json"))

    def test_catalog_text_refuses_control_characters_and_misnamed_files(self):
        pack = json.loads(json.dumps(load_catalog()["packs"]["python"]))
        for text in ("Bar\u0085", "x\u007fy", "a b"):
            with self.assertRaises(CatalogError):
                validate_entry("packs", {**pack, "title": text})
        packs = self.root / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        write_json(packs / "foo.json", {**pack, "id": "team-python"})
        with self.assertRaisesRegex(CatalogError, "team-python.json"):
            load_catalog(self.root / ".openguildkit" / "catalog")

    def test_replay_refuses_a_file_as_project(self):
        target = self.root / "file.txt"
        target.write_text("x", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(REPO / "examples" / "request-status" / "replay.py"), "--project", str(target)],
            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is a file", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
