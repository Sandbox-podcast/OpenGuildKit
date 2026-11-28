"""End-to-end tests invoke the CLI against temporary projects, with real processes for host tests.

The request status example in examples/request-status is the fixture, so the
example cannot drift from the CLI without failing these tests.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import copy_initialized_project, run_cli, subprocess_environment

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "request-status"
TASK_ID = "request-status"
EXPECTED_BOARDS = {"product", "engineering", "qa", "design", "marketing", "security", "legal"}

ENV = subprocess_environment({
    "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
})


class CliTestCase(unittest.TestCase):
    subprocess_mode = False

    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="ogk-e2e-")).resolve()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def command(self, *args):
        return [sys.executable, "-m", "openguildkit", "--project", str(self.project), *map(str, args)]

    def run_cli(self, *args, stdin_text="", expect=0):
        return run_cli(
            self.project, *args, stdin=stdin_text, expect=expect,
            subprocess_mode=self.subprocess_mode, env=ENV,
        )

    def in_terminal(self, args, typed):
        """(exit code, stdout, stderr) of a command run at a pseudo-terminal where the person types one line.

        The output is captured, so what the command shows the person stays out of the test runner's output."""
        master, slave = os.openpty()
        try:
            process = subprocess.Popen(self.command(*args), stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", env=ENV)
            os.close(slave)
            slave = None
            os.write(master, f"{typed}\n".encode())
            stdout, stderr = process.communicate(timeout=60)
        finally:
            if slave is not None:
                os.close(slave)
            os.close(master)
        return process.returncode, stdout, stderr

    def decide_in_terminal(self, typed, task_id=TASK_ID):
        return self.in_terminal(("task", "decide", task_id, "--approve", "--by", "Test Owner", "--reason", "Scope agreed"),
                                typed)

    def init_example(self):
        if any(self.project.iterdir()):
            self.run_cli("init", "--answers", EXAMPLE / "profile.json")
        else:
            copy_initialized_project(self, EXAMPLE / "profile.json", self.project)

    def consult_example(self):
        self.init_example()
        created = self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.assertEqual(created.stdout.strip(), TASK_ID)
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")

    def task_record(self):
        return json.loads(self.run_cli("task", "show", TASK_ID, "--json").stdout)

    def write_json(self, name, data):
        path = self.project / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def example_review(self, task_id=TASK_ID):
        """The example review, bound to the current consultation as task template prints it."""
        template = json.loads(self.run_cli("task", "template", task_id).stdout)
        review = json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))
        return {"consultation_id": template["consultation_id"], **review}

    def record_example_review(self):
        path = self.write_json("review.json", self.example_review())
        return self.run_cli("task", "review", TASK_ID, "--file", path)


class CatalogTests(CliTestCase):
    subprocess_mode = True  # python -m openguildkit itself, as the installed command runs it

    def test_hr_brain_exposes_distinct_review_lenses(self):
        brain = json.loads(self.run_cli("brains", "--id", "hr", "--json").stdout)
        lenses = brain["review"]["specialists"]
        self.assertGreaterEqual(len({lens["id"] for lens in lenses}), 3)
        self.assertTrue(brain["review"]["challenge"])

    def test_reference_library_commands_work_without_an_initialized_project(self):
        groups = self.run_cli("references").stdout
        self.assertIn("references", groups)
        self.assertIn("governance", groups)
        matches = json.loads(self.run_cli("references", "ISO 27001", "--family", "governance", "--json").stdout)
        self.assertEqual(matches[0]["id"], "iso-iec-27001")
        details = self.run_cli("references", "--id", "conventional-commits").stdout
        self.assertIn("Conventional Commits", details)
        self.assertIn("https://www.conventionalcommits.org/", details)
        self.run_cli("references", "--family", "unknown", expect=1)

    def test_bundled_catalog_loads_as_json(self):
        catalog = json.loads(self.run_cli("catalog", "--json").stdout)
        self.assertEqual(set(catalog), {"packs", "boards", "sectors"})
        self.assertIn("agent-workflow", catalog["packs"])
        self.assertIn("performance", catalog["boards"])
        self.assertIn("general", catalog["sectors"])
        for pack in catalog["packs"].values():
            for rule in pack["rules"]:
                self.assertTrue(rule["instruction"] and rule["verification"], f"{pack['id']}/{rule['id']}")

    def test_project_pack_is_loaded_and_applied(self):
        packs = self.project / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        (packs / "house-style.json").write_text(
            json.dumps(
                {
                    "id": "house-style",
                    "title": "House style",
                    "version": "1.0.0",
                    "description": "Conventions specific to this company.",
                    "sources": [],
                    "rules": [
                        {
                            "id": "feature-flags",
                            "instruction": "Ship customer-facing changes behind a feature flag.",
                            "verification": "The pull request names the flag and its default.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.assertIn("house-style", self.run_cli("catalog").stdout)

        profile = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
        profile["packs"] = ["house-style"]
        self.run_cli("init", "--answers", self.write_json("profile.json", profile))
        agents = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("#### House style (`house-style@1.0.0`)\n\n`feature-flags`\n", agents)
        self.assertNotIn("Ship customer-facing changes behind a feature flag.", agents)
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")
        self.assertIn("- feature-flags: Ship customer-facing changes behind a feature flag.\n"
                      "  Verified: The pull request names the flag and its default.",
                      self.run_cli("task", "brief", TASK_ID, "--pack", "house-style").stdout)

    def test_invalid_project_pack_is_rejected_with_its_path(self):
        packs = self.project / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        (packs / "broken.json").write_text(
            json.dumps({"id": "broken", "title": "Broken", "version": "1.0", "description": "x", "sources": [], "rules": []}),
            encoding="utf-8",
        )
        result = self.run_cli("catalog", expect=1)
        self.assertIn("broken.json", result.stderr)

    def test_project_pack_cannot_shadow_a_bundled_pack(self):
        packs = self.project / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        bundled = REPO / "src" / "openguildkit" / "registry" / "packs" / "python.json"
        shutil.copy(bundled, packs / "python.json")
        result = self.run_cli("catalog", expect=1)
        self.assertIn("duplicate", result.stderr)


class ProjectSetupTests(CliTestCase):
    def test_recommends_stack_patterns_and_applies_only_chosen_work_methods(self):
        answers = {"personal_data": "no", 
            "name": "Requests API",
            "sector": "general",
            "stack": ["Python 3.12", "FastAPI", "Postgres@16"],
            "roles": ["engineering", "project-management"],
        }
        path = self.write_json("answers.json", answers)
        plan = json.loads(self.run_cli("recommend", "--answers", path, "--json").stdout)
        matched = [pattern["id"] for pattern in plan["matched"]]
        self.assertIn("python-fastapi-postgresql", matched)
        # Scrum and Kanban are suggested to project management, not preselected (#152): the team picks one.
        suggested = {pattern["id"] for pattern in plan["suggested"]}
        self.assertLessEqual({"scrum", "kanban"}, suggested)
        self.assertIn("scrum", self.run_cli("patterns", "--role", "project-management").stdout)
        self.assertIn("openguildkit patterns --id scrum", self.run_cli("references", "--id", "pattern-scrum").stdout)
        answers["patterns"] = [*matched, "scrum"]
        self.run_cli("init", "--answers", self.write_json("selected.json", answers))
        self.run_cli("check")
        instructions = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`fastapi@", instructions)
        self.assertIn("`postgresql@", instructions)
        self.assertIn("`scrum-delivery@", instructions)
        self.assertNotIn("`kanban-delivery@", instructions)

    def test_detected_components_feed_init_and_a_stack_change_is_flagged(self):
        web = self.project / "apps" / "web"
        web.mkdir(parents=True)
        (web / "package.json").write_text(json.dumps({"dependencies": {"next": "^14.2.0", "react": "^18.3.0"}}), encoding="utf-8")
        detected = json.loads(self.run_cli("detect", "--json").stdout)
        # The declared range stays as written; pattern matching reads its lower bound.
        self.assertEqual(detected["components"][0]["stack"], ["Next.js ^14.2.0", "React ^18.3.0"])

        questions = {question["id"]: question for question in json.loads(self.run_cli("init", "--questions").stdout)}
        components = questions["components"]["default"]
        self.assertEqual(components[0]["path"], "apps/web")

        self.run_cli("init", "--answers", self.write_json("answers.json", {"personal_data": "no", "name": "Portal", "components": components}))
        agents = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Applies to `apps-web` (apps/web).", agents)

        profile_path = self.project / ".openguildkit" / "project.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["components"][0]["stack"] = ["Next.js 12.3", "React 18.3"]
        profile["stack"] = profile["components"][0]["stack"]
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        synced = self.run_cli("sync")
        self.assertIn("review pattern nextjs-react", synced.stderr)
        plan = json.loads(self.run_cli("recommend", "--json").stdout)
        self.assertEqual(plan["review"][0]["id"], "nextjs-react")

    def test_scrum_and_kanban_patterns_install_together(self):
        answers = {"name": "Scrumban team", "personal_data": "no", "patterns": ["scrum", "kanban"]}
        self.run_cli("init", "--answers", self.write_json("answers.json", answers))
        instructions = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`scrum-delivery@", instructions)
        self.assertIn("`kanban-delivery@", instructions)
        self.run_cli("check")

    def test_preview_shows_the_rules_and_init_waits_for_a_conflict_resolution(self):
        packs = self.project / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True)
        fixed_scope = {
            "id": "fixed-sprint-scope", "title": "Fixed sprint scope", "version": "1.0.0",
            "description": "For a team that freezes its work for the length of a sprint.", "sources": [],
            "conflicts_with": ["kanban-delivery"],
            "rules": [{"id": "freeze-sprint-scope", "instruction": "Start no new item before the sprint ends.",
                       "verification": "Compare the items started with the sprint plan."}],
        }
        (packs / "fixed-sprint-scope.json").write_text(json.dumps(fixed_scope), encoding="utf-8")
        answers = {"personal_data": "no", "name": "Team", "stack": ["Python", "FastAPI", "PostgreSQL"], "packs": ["kanban-delivery", "fixed-sprint-scope"]}
        path = self.write_json("answers.json", answers)
        preview = self.run_cli("preview", "--answers", path).stdout
        self.assertIn("agent-workflow@", preview)
        self.assertIn("fixed-sprint-scope / kanban-delivery: unresolved", preview)
        refused = self.run_cli("init", "--answers", path, expect=1)
        self.assertIn("Conflicting rule packs", refused.stderr)
        self.assertFalse((self.project / ".openguildkit" / "project.json").exists())

        answers["resolutions"] = [{"packs": ["kanban-delivery", "fixed-sprint-scope"], "keep": ["kanban-delivery"], "reason": "Continuous demand."}]
        self.run_cli("init", "--answers", self.write_json("answers.json", answers))
        plan = json.loads(self.run_cli("preview", "--json").stdout)
        self.assertEqual(plan["excluded"], ["fixed-sprint-scope"])
        self.assertIn("Reason: Continuous demand.", (self.project / "AGENTS.md").read_text(encoding="utf-8"))
        self.run_cli("check")

    def test_init_writes_profile_and_agent_instructions(self):
        self.init_example()
        profile = json.loads((self.project / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["sector"], "general")
        self.assertEqual(profile["packs"][0], "agent-workflow")
        self.assertIn("secure-sdlc", profile["packs"])

        agents = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- BEGIN OPENGUILDKIT -->", agents)
        self.assertIn("Sector: General", agents)
        self.assertIn("## OpenGuildKit task workflow", agents)
        self.assertIn("@AGENTS.md", (self.project / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertIn("tasks/", (self.project / ".openguildkit" / ".gitignore").read_text(encoding="utf-8"))
        self.run_cli("check")

    def test_init_refuses_to_run_twice(self):
        self.init_example()
        result = self.run_cli("init", "--answers", EXAMPLE / "profile.json", expect=1)
        self.assertIn("already initialized", result.stderr)

    def test_init_without_terminal_needs_answers(self):
        result = self.run_cli("init", expect=1)
        self.assertIn("--answers", result.stderr)

    def test_init_questions_are_printed_as_json(self):
        questions = json.loads(self.run_cli("init", "--questions").stdout)
        ids = [question["id"] for question in questions]
        self.assertEqual(ids[:2], ["name", "sector"])
        self.assertIn("packs", ids)
        self.assertIn("research", ids)

    def test_check_detects_drift_and_sync_repairs_it_without_touching_user_text(self):
        self.init_example()
        agents_path = self.project / "AGENTS.md"
        text = agents_path.read_text(encoding="utf-8")
        agents_path.write_text(
            "# Team notes\n\nKeep this line.\n\n" + text.replace("Sector: General", "Sector: Outdated"),
            encoding="utf-8",
        )
        result = self.run_cli("check", expect=1)
        self.assertIn("sync", result.stderr)

        self.run_cli("sync")
        self.run_cli("check")
        repaired = agents_path.read_text(encoding="utf-8")
        self.assertIn("Keep this line.", repaired)
        self.assertIn("Sector: General", repaired)
        self.assertNotIn("Sector: Outdated", repaired)

    def test_task_new_refuses_stale_instructions(self):
        self.init_example()
        agents_path = self.project / "AGENTS.md"
        agents_path.write_text(agents_path.read_text(encoding="utf-8").replace("Stack:", "Stack: COBOL,"), encoding="utf-8")
        self.run_cli("task", "new", "Anything", expect=1)


class TaskFlowTests(CliTestCase):
    def test_example_flow_until_human_decision(self):
        self.init_example()
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.assertEqual(self.task_record()["status"], "draft")

        # One JSON shape with or without answers (#174).
        listing = json.loads(self.run_cli("task", "questions", TASK_ID).stdout)
        self.assertEqual((listing["follow_ups"], listing["open_points"]), ([], []))
        questions = listing["questions"]
        self.assertEqual([question["id"] for question in questions], ["kind", "surface", "data", "research", "concerns", "context"])

        consultation = self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json").stdout
        self.assertIn("# Board consultation request", consultation)
        for board in EXPECTED_BOARDS:
            self.assertIn(f"- {board} (", consultation)
        self.assertEqual(self.run_cli("task", "brief", TASK_ID).stdout.strip(), consultation.strip())

        template = json.loads(self.run_cli("task", "template", TASK_ID).stdout)
        self.assertEqual({entry["id"] for entry in template["boards"]}, EXPECTED_BOARDS)

        self.assertEqual(self.record_example_review().stdout.strip(), "reviewed")
        brief = self.run_cli("task", "challenge", TASK_ID).stdout
        self.assertIn("# Decision brief", brief)
        self.assertIn('"verdicts"', brief)
        self.assertIn('"failure_mode"', brief)

        refused = self.run_cli(
            "task", "decide", TASK_ID, "--approve", "--by", "Agent", "--reason", "Looks fine",
            stdin_text=f"{TASK_ID}\n", expect=1,
        )
        self.assertIn("interactive terminal", refused.stderr)
        self.assertEqual(self.task_record()["status"], "reviewed")

        blocked = self.run_cli("task", "handoff", TASK_ID, expect=1)
        self.assertIn("approval", blocked.stderr)

    def test_request_changes_then_consult_again_keeps_history(self):
        self.consult_example()
        first_review = self.example_review()
        self.record_example_review()
        decided = self.run_cli(
            "task", "decide", TASK_ID, "--request-changes", "--by", "Service owner", "--reason", "Show the last update date"
        )
        self.assertEqual(decided.stdout.strip(), "changes-requested")

        answers = json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8"))
        answers["context"] += " Show the date of the last status update."
        original = self.task_record()["brief"]
        revised = "Show policyholders the date of their most recent claim update."
        self.run_cli("task", "consult", TASK_ID, "--answers", self.write_json("answers-2.json", answers),
                     "--brief", revised)

        task = self.task_record()
        self.assertEqual(task["status"], "consulting")
        self.assertEqual(len(task["rounds"]), 1)
        self.assertEqual(task["rounds"][0]["decision"]["reason"], "Show the last update date")
        self.assertEqual(task["rounds"][0]["brief"], original)
        self.assertEqual(task["brief"], revised)
        self.assertEqual(task["consultation"]["scope"]["brief"], revised)
        self.assertNotIn("review", task)

        stale = self.run_cli("task", "review", TASK_ID, "--file", self.write_json("stale.json", first_review), expect=1)
        self.assertIn("consultation", stale.stderr)
        self.record_example_review()
        challenge = self.run_cli("task", "challenge", TASK_ID)
        recall = challenge.stdout.splitlines()[0]
        self.assertIn("Round 1: changes requested by Service owner", recall)
        self.assertIn("Show the last update date", recall)
        self.assertIn("The brief was revised since.", recall)

    def test_review_must_cover_exactly_the_selected_boards(self):
        self.consult_example()
        review = self.example_review()

        missing = {**review, "boards": [entry for entry in review["boards"] if entry["id"] != "security"]}
        result = self.run_cli("task", "review", TASK_ID, "--file", self.write_json("missing.json", missing), expect=1)
        self.assertIn("security", result.stderr)

        extra = {**review, "boards": review["boards"] + [{**review["boards"][0], "id": "finance"}]}
        result = self.run_cli("task", "review", TASK_ID, "--file", self.write_json("extra.json", extra), expect=1)
        self.assertIn("finance", result.stderr)

        empty = {**review, "boards": [{**review["boards"][0], "recommendation": " "}] + review["boards"][1:]}
        self.run_cli("task", "review", TASK_ID, "--file", self.write_json("empty.json", empty), expect=1)
        self.assertEqual(self.task_record()["status"], "consulting")

    def test_follow_up_questions_and_open_points(self):
        self.init_example()
        self.run_cli("task", "new", "Improve exports", "--id", "vague")
        answers = self.write_json("vague.json", {"kind": "feature", "surface": ["customer", "service"], "data": "none", "research": "local"})
        plan = json.loads(self.run_cli("task", "questions", "vague", "--answers", answers).stdout)
        self.assertEqual([item["id"] for item in plan["follow_ups"]], ["affected", "assumptions", "concerns", "outcome"])
        answers = self.write_json("vague.json", {"kind": "feature", "surface": ["customer", "service"], "data": "none",
                                                 "research": "local", "concerns": ["none"]})
        self.assertTrue(all(item["prompt"].endswith("?") for item in plan["follow_ups"]))
        self.assertTrue(any("brief is short" in point for point in plan["open_points"]))
        consultation = self.run_cli("task", "consult", "vague", "--answers", answers).stdout
        self.assertIn("## Open points", consultation)

    def test_route_preview_and_requester_adjustments(self):
        self.init_example()
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        preview = self.run_cli("task", "route", TASK_ID, "--answers", EXAMPLE / "answers.json").stdout
        self.assertIn("marketing: Customer expectations and market evidence", preview)
        self.assertNotIn("consultation", self.task_record())
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json",
                     "--remove", "marketing", "--add", "finance", "--reason", "No launch planned")
        consultation = self.task_record()["consultation"]
        self.assertNotIn("marketing", consultation["boards"])
        self.assertEqual(consultation["adjustments"][0]["reason"], "No launch planned")

    def test_other_answer_requires_context(self):
        self.init_example()
        self.run_cli("task", "new", "Something unusual", "--id", "odd")
        answers = {"kind": "other", "surface": "unsure", "data": "none", "research": "local"}
        result = self.run_cli("task", "consult", "odd", "--answers", self.write_json("odd.json", answers), expect=1)
        self.assertIn("context", result.stderr)

    def test_brief_words_route_to_boards(self):
        self.init_example()
        self.run_cli("task", "new", "Réduire la latence de la page de recherche", "--id", "search-speed")
        answers = {"kind": "maintenance", "surface": "unsure", "data": "none", "research": "local", "concerns": ["none"]}
        self.run_cli("task", "consult", "search-speed", "--answers", self.write_json("speed.json", answers))
        routing = self.task_record_for("search-speed")["consultation"]["routing"]
        self.assertIn("performance", routing)
        self.assertNotIn("security", routing)

    def task_record_for(self, task_id):
        return json.loads(self.run_cli("task", "show", task_id, "--json").stdout)

    def test_usage_errors_exit_with_code_2(self):
        result = subprocess.run(
            self.command("task", "decide", TASK_ID), capture_output=True, text=True, encoding="utf-8", env=ENV, timeout=60
        )
        self.assertEqual(result.returncode, 2)


@unittest.skipUnless(os.name == "posix", "approval needs a pseudo-terminal, available on Linux and macOS")
class ApprovalTests(CliTestCase):
    def test_approval_requires_the_typed_id_and_expires_when_rules_change(self):
        self.consult_example()
        self.record_example_review()

        code, _, stderr = self.decide_in_terminal("wrong-id")
        self.assertEqual(code, 1, stderr)
        self.assertEqual(self.task_record()["status"], "reviewed")

        code, stdout, stderr = self.decide_in_terminal(TASK_ID)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout.strip(), "approved")

        handoff = self.run_cli("task", "handoff", TASK_ID).stdout
        self.assertIn("# Approved task handoff", handoff)
        self.assertIn("Test Owner", handoff)
        self.assertIn("check-access-control", handoff)

        profile_path = self.project / ".openguildkit" / "project.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["packs"].append("web-accessibility")
        profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        self.run_cli("sync")

        expired = self.run_cli("task", "handoff", TASK_ID, expect=1)
        self.assertIn("recorded under earlier rules (pack web-accessibility added)", expired.stderr)
        self.assertIn(f"The approval for {TASK_ID} was recorded under earlier rules", expired.stderr)
        self.assertIn(f"--follows {TASK_ID}", expired.stderr)

    def test_an_approved_decision_task_returns_a_decision_record(self):
        self.init_example()
        task_id = "pricing-choice"
        self.run_cli("task", "new", "Recommend whether to bill support per seat or per request.", "--id", task_id)
        answers = {"kind": "decision", "surface": "business", "data": "none", "research": "local", "concerns": ["none"]}
        self.run_cli("task", "consult", task_id, "--answers", self.write_json("decision.json", answers))
        template = json.loads(self.run_cli("task", "template", task_id).stdout)
        template["summary"] = "Bill per seat for the pilot and measure request volume."
        (self.project / "pricing.md").write_text("Per-seat contract.\n", encoding="utf-8")
        for entry in template["boards"]:
            entry.update(recommendation="Keep per-seat billing for the pilot.", evidence=[{"source": "project-file", "ref": "pricing.md", "supports": "Per-seat contract."}], open_questions=[])
            challenge = entry["challenge"]
            for lens in challenge["specialists"]:
                lens.update(finding="The current contract bills per seat.", basis="observed", evidence_refs=[1])
            challenge.update(
                verdict="proceed", confidence="medium", alternative="Bill per request.",
                failure_mode="Heavy users cost more than they pay.", verification="Compare request volume after a month.",
            )
        self.run_cli("task", "review", task_id, "--file", self.write_json("decision-review.json", template))

        code, stdout, stderr = self.decide_in_terminal(task_id, task_id=task_id)
        self.assertEqual(code, 0, stderr)
        record = self.run_cli("task", "handoff", task_id).stdout
        self.assertIn("# Approved decision record", record)
        self.assertIn("Leave the project files unchanged", record)
        self.assertNotIn("Implement the approved scope", record)
        self.assertNotIn("# Approved task handoff", record)

        # Closed without a result file, as the handoff says, the decision's record exports with its closing.
        self.assertIn("done", self.run_cli("task", "complete", task_id).stdout)
        self.run_cli("task", "export", task_id)
        exported = json.loads((self.project / ".openguildkit" / "decisions" / f"{task_id}.json").read_text(encoding="utf-8"))
        self.assertTrue(exported["completed"])
        self.assertEqual(exported["result"]["checks"], {})
        self.assertIn("closing", exported["result"])


if __name__ == "__main__":
    unittest.main()
