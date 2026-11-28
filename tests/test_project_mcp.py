"""A stdio client reads the same project metadata as the CLI."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json
from tests.support import subprocess_environment
from tests.test_results import EXAMPLE, TASK, ResultCase

REGISTRY = Path(__file__).resolve().parents[1] / "src" / "openguildkit" / "registry"


def request(identifier, method, **params):
    return {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}


def call(identifier, name, **arguments):
    return request(identifier, "tools/call", name=name, arguments=arguments)


class ProjectMcpTests(ResultCase):
    def exchange(self, *messages, project=True):
        options = ["--project", str(self.root)] if project else []
        stream = "".join(json.dumps(message) + "\n" for message in messages)
        return subprocess.run(
            [sys.executable, "-m", "openguildkit", *options, "mcp"],
            input=stream, capture_output=True, encoding="utf-8",
            env=subprocess_environment(), timeout=60,
        )

    def replies(self, *messages):
        result = self.exchange(*messages)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return [json.loads(line) for line in result.stdout.splitlines()]

    def snapshot(self):
        return {
            path.relative_to(self.root): path.read_bytes()
            for path in (self.root / ".openguildkit").rglob("*") if path.is_file()
        }

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_cli_and_mcp_agree_on_the_active_rule_and_verified_commit(self):
        self.approved(git_project=True, conventions=["Private convention marker"])
        self.run_cli("task", "verify", TASK)
        preview = json.loads(self.run_cli("preview", "--json")[0])
        pack = next(pack for pack in preview["packs"] if pack["id"] == "python")
        ref = {key: pack[key] for key in ("id", "version", "scope")}
        rule_id = pack["rules"][0]
        record = self.record()
        check = record["result"]["checks"][0]
        commit = self.git("rev-parse", "HEAD")
        self.assertEqual((check["check"], check["status"], check["revision"]),
                         ("command:1", "passed", {"commit": commit, "clean": True}))
        snapshot = self.snapshot()

        hello, listed, *responses = self.replies(
            request(1, "initialize", protocolVersion="2025-11-25", capabilities={}, clientInfo={"name": "test", "version": "1"}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            request(2, "tools/list"),
            call(3, "project_profile"),
            call(4, "project_rule", pack_id=pack["id"], rule_id=rule_id),
            call(5, "task_status", task_id=TASK),
            call(6, "task_check_results", task_id=TASK),
        )
        self.assertEqual(hello["result"]["serverInfo"]["name"], "openguildkit")
        tools = listed["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools],
                         ["project_profile", "project_rule", "task_status", "task_check_results",
                          "task_list", "task_next", "task_blockers"])
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))
        results = [response["result"] for response in responses]
        profile, rule, status, outcomes = [result["structuredContent"] for result in results]
        self.assertIn(ref, profile["packs"])
        self.assertEqual(set(profile), {"sector", "components", "packs"})
        self.assertEqual(rule, {"pack": ref, "rule_id": rule_id})
        self.assertEqual(status, {"id": TASK, "status": record["status"]})
        self.assertEqual(outcomes, {"id": TASK, "revision": commit, "checks": [
            {"check": "command:1", "status": "passed", "revision": commit},
        ], "omitted": 0, "failed_omitted": 0})
        for tool, result in zip(tools[:4], results, strict=True):
            self.assertEqual(set(tool["outputSchema"]["required"]), set(result["structuredContent"]))
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        serialized = json.dumps(results)
        for private in ("Private convention marker", "Camille", check["evidence"], str(self.root)):
            self.assertNotIn(private, serialized)
        self.assertEqual(snapshot, self.snapshot())

    def blocked_review(self):
        """The example task reviewed with two security blockers, the first cleared by Camille, and a draft beside it."""
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"],
                                                "packs": ["python"]})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "new", "A draft nobody consulted yet.", "--id", "draft-one")
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"].update(verdict="block", blockers=[
            {"finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
             "clears_when": "An automated test with two synthetic accounts passes."},
            {"finding": "Retention of request history is not decided.", "owner": "Data protection officer",
             "clears_when": "The retention period is recorded."},
        ])
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        (self.root / "proof-marker.txt").write_text("Two accounts tested.\n", encoding="utf-8")
        self.run_cli("task", "clear", TASK, "security:1", "--evidence", "proof-marker.txt", "--supports",
                     "Two accounts tested.", "--by", "Camille", typed=TASK)

    def test_tasks_next_command_and_blockers_match_the_cli_and_name_nobody(self):
        self.blocked_review()
        listed = json.loads(self.run_cli("task", "list", "--json")[0])
        blockers = json.loads(self.run_cli("task", "blockers", TASK, "--json")[0])
        snapshot = self.snapshot()

        tools, *responses = self.replies(
            request(1, "tools/list"),
            call(2, "task_list"),
            call(3, "task_next", task_id=TASK),
            call(4, "task_next", task_id="draft-one"),
            call(5, "task_blockers", task_id=TASK),
            call(6, "task_blockers", task_id="draft-one"),
        )
        schemas = {tool["name"]: tool for tool in tools["result"]["tools"]}
        results = [response["result"] for response in responses]
        for name, result in zip(("task_list", "task_next", "task_next", "task_blockers", "task_blockers"), results,
                                strict=True):
            self.assertNotIn("isError", result)
            self.assertEqual(set(schemas[name]["outputSchema"]["required"]), set(result["structuredContent"]))
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
            self.assertTrue(schemas[name]["annotations"]["readOnlyHint"])
        tasks, reviewed, draft, blocked, unblocked = [result["structuredContent"] for result in results]

        self.assertEqual(tasks, {"tasks": [{key: row[key] for key in ("id", "status", "next")} for row in listed]})
        self.assertEqual([row["id"] for row in tasks["tasks"]], ["draft-one", TASK])
        self.assertEqual(reviewed["needs_person"], True)
        self.assertEqual(reviewed["status"], "reviewed")
        self.assertIn(f"openguildkit task clear {TASK} BLOCKER", reviewed["command"])
        self.assertIn("security:2", reviewed["command"])
        self.assertEqual(draft, {"id": "draft-one", "status": "draft", "needs_person": False,
                                 "command": "read the questions with openguildkit task questions draft-one, then "
                                            "consult the boards with openguildkit task consult draft-one --answers FILE"})
        self.assertEqual(blocked["id"], TASK)
        self.assertEqual(blocked["blockers"], [
            {"id": item["id"], "board": item["board"], "phase": item.get("phase", "approval"),
             "finding": item["finding"], "owner": item["owner"], "clears_when": item["clears_when"],
             "state": item["resolution"]["kind"] if item["resolution"] else "open"} for item in blockers])
        self.assertEqual([item["state"] for item in blocked["blockers"]], ["cleared", "open"])
        self.assertEqual(unblocked, {"id": "draft-one", "blockers": []})

        serialized = json.dumps(results)
        for private in ("Camille", "proof-marker", "Two accounts tested", "A draft nobody", str(self.root)):
            self.assertNotIn(private, serialized)
        self.assertEqual(snapshot, self.snapshot())

    def test_the_task_list_leaves_out_what_a_person_or_a_command_wrote(self):
        self.approved(exit_code=1)
        self.run_cli("task", "verify", TASK, code=1)
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertIn(sys.executable, row["next"])
        (listed,) = self.replies(call(1, "task_list"))
        entry, = listed["result"]["structuredContent"]["tasks"]
        self.assertEqual(entry["status"], "approved")
        self.assertIn("command:1 failed", entry["next"])
        self.assertIn(f"task verify {TASK}", entry["next"])
        self.assertNotIn(sys.executable, json.dumps(listed))
        self.assertNotIn("checked", json.dumps(listed))

        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "revoke", TASK, "--by", "Camille", "--reason", "Reason-marker from the person")
        (listed,) = self.replies(call(1, "task_list"))
        entry, = listed["result"]["structuredContent"]["tasks"]
        self.assertEqual(entry["status"], "changes-requested")
        self.assertIn(f"openguildkit task show {TASK}", entry["next"])
        self.assertNotIn("Reason-marker", json.dumps(listed))
        self.assertNotIn("Camille", json.dumps(listed))

    def test_a_check_whose_name_is_free_text_is_counted_and_a_failure_is_signalled(self):
        self.approved()
        summary = self.root / "qa-results" / "summary.json"
        write_json(summary, {"schema_version": 1, "results": [
            {"name": "checkout_flow.json", "status": "failed", "message": "The cart stays empty"},
            {"name": "login-flow", "status": "passed"},
        ]})
        self.run_cli("task", "verify", TASK, "--chaosfolk", summary)
        recorded = [item["check"] for item in self.record()["result"]["checks"]]
        self.assertIn("chaosfolk:checkout_flow.json", recorded)
        _, listed = self.replies(
            request(1, "initialize", protocolVersion="2025-11-25", capabilities={}, clientInfo={"name": "test", "version": "1"}),
            call(2, "task_check_results", task_id=TASK),
        )
        outcomes = listed["result"]["structuredContent"]
        self.assertEqual([check["check"] for check in outcomes["checks"]], ["chaosfolk:login-flow"])
        self.assertEqual((outcomes.get("omitted"), outcomes.get("failed_omitted")), (1, 1))
        self.assertNotIn("checkout_flow", json.dumps(listed))

    def test_reads_require_a_project_and_refuse_paths_and_mutations(self):
        # OGK-INIT-001
        done = self.exchange(project=False)
        self.assertEqual(done.returncode, 1)
        self.assertIn("--project PATH", done.stderr)
        self.assertEqual(done.stdout, "")

        errors = self.replies(
            call(1, "task_status", task_id="../outside"),
            call(2, "project_profile", path="elsewhere"),
            call(3, "task_approve", task_id="sample"),
            call(4, "task_status", task_id="missing"),
            call(5, "task_list", task_id="sample"),
            call(6, "task_next"),
            call(7, "task_blockers", task_id="missing"),
            call(8, "task_next", task_id="../outside"),
        )
        self.assertEqual([error["error"]["code"] for error in errors], [-32602] * 8)
        self.assertNotIn("../outside", json.dumps(errors))

    def test_damage_in_the_profile_returns_an_error_without_file_content(self):
        state = self.root / ".openguildkit"
        state.mkdir()
        (state / "project.json").write_text('{"sector":"private-sector-marker"}', encoding="utf-8")
        answer, = self.replies(call(1, "project_profile"))
        self.assertTrue(answer["result"]["isError"])
        self.assertNotIn("private-sector-marker", json.dumps(answer))
        self.assertIn("openguildkit check", answer["result"]["content"][0]["text"])

    def link_outside(self, path):
        """Move path to a folder outside the project and leave a symbolic link to it in its place."""
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        moved = Path(outside.name, path.name)
        shutil.move(path, moved)
        try:
            path.symlink_to(moved)
        except OSError as error:
            self.skipTest(f"This account cannot create symbolic links: {error}")

    def assert_refused_without_content(self, *private):
        answer, = self.replies(call(1, "project_profile"))
        self.assertTrue(answer["result"].get("isError"), f"served a file outside the state directory: {answer}")
        self.assertNotIn("structuredContent", answer["result"])
        self.assertEqual(answer["result"]["content"][0]["text"],
                         "Project metadata is unavailable. Run openguildkit check in this project.")
        for text in private:
            self.assertNotIn(text, json.dumps(answer))

    def test_a_profile_linked_outside_the_state_directory_is_not_served(self):
        # OGK-PROJECT-033
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
        self.run_cli("init", "--answers", self.root / "profile.json")
        served, = self.replies(call(1, "project_profile"))
        self.assertEqual(served["result"]["structuredContent"]["sector"], "general")
        self.link_outside(self.root / ".openguildkit" / "project.json")
        self.assert_refused_without_content("sector", "general")

    def test_a_catalog_file_linked_outside_the_state_directory_is_not_served(self):
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
        self.run_cli("init", "--answers", self.root / "profile.json")
        state = self.root / ".openguildkit"
        pack = json.loads((REGISTRY / "packs" / "product-discovery.json").read_text(encoding="utf-8"))
        write_json(state / "catalog" / "packs" / "linked-pack.json", {**pack, "id": "linked-pack"})
        profile = json.loads((state / "project.json").read_text(encoding="utf-8"))
        write_json(state / "project.json", {**profile, "packs": [*profile["packs"], "linked-pack"]})
        served, = self.replies(call(1, "project_profile"))
        self.assertIn("linked-pack", [pack["id"] for pack in served["result"]["structuredContent"]["packs"]])
        self.link_outside(state / "catalog" / "packs" / "linked-pack.json")
        self.assert_refused_without_content("linked-pack", "sector")
