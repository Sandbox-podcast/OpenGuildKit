"""A stdio client reads the same project metadata as the CLI."""

import json
import shutil
import subprocess
import sys
import unittest

from openguildkit.storage import write_json

from tests.support import subprocess_environment
from tests.test_results import TASK, ResultCase


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
                         ["project_profile", "project_rule", "task_status", "task_check_results"])
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
        for tool, result in zip(tools, results, strict=True):
            self.assertEqual(set(tool["outputSchema"]["required"]), set(result["structuredContent"]))
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])
        serialized = json.dumps(results)
        for private in ("Private convention marker", "Camille", check["evidence"], str(self.root)):
            self.assertNotIn(private, serialized)
        self.assertEqual(snapshot, self.snapshot())

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
        done = self.exchange(project=False)
        self.assertEqual(done.returncode, 1)
        self.assertIn("--project PATH", done.stderr)
        self.assertEqual(done.stdout, "")

        errors = self.replies(
            call(1, "task_status", task_id="../outside"),
            call(2, "project_profile", path="elsewhere"),
            call(3, "task_approve", task_id="sample"),
            call(4, "task_status", task_id="missing"),
        )
        self.assertEqual([error["error"]["code"] for error in errors], [-32602] * 4)
        self.assertNotIn("../outside", json.dumps(errors))

    def test_damage_in_the_profile_returns_an_error_without_file_content(self):
        state = self.root / ".openguildkit"
        state.mkdir()
        (state / "project.json").write_text('{"sector":"private-sector-marker"}', encoding="utf-8")
        answer, = self.replies(call(1, "project_profile"))
        self.assertTrue(answer["result"]["isError"])
        self.assertNotIn("private-sector-marker", json.dumps(answer))
        self.assertIn("openguildkit check", answer["result"]["content"][0]["text"])
