"""The short lane (#422): off by default, turned on by a person, limited to the paths a profile names.

The rules of paths (what the lane never covers, what a path may be) come first; then the activation of the lane in the
profile, and a project written before the lane existed.
"""

import json
import shlex
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openguildkit import light_lane, profile_cli, surfaces
from openguildkit.decisions import check_decision_seal, record_digest
from openguildkit.project import profile_fingerprint, validate_profile
from openguildkit.storage import write_json

from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
DOCS_AND_TESTS = ["docs/**", "tests/**"]


class PathRuleTests(unittest.TestCase):
    def test_an_entry_is_a_folder_or_file_glob_inside_the_project(self):
        self.assertEqual(light_lane.normalize_entries(["tests/**", "docs/", " docs/** ", "README.md"], "light_paths"),
                         ["README.md", "docs/**", "tests/**"])
        for entry in ("", "  ", "/etc/passwd", "../x", "docs/../x", "docs/./x", "docs//x", "docs\\x", "**", "**/*.md",
                      "docs/[ab].md", "docs/{a,b}", "docs/!x", "docs/a**b", ".", 3, None):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                light_lane.normalize_entries([entry], "light_paths")
        with self.assertRaises(ValueError):
            light_lane.normalize_entries([], "paths")
        with self.assertRaises(ValueError):
            light_lane.normalize_entries([f"docs/f{index}.md" for index in range(light_lane.MAX_PATHS + 1)], "paths")

    def test_rules_dependencies_the_profile_and_the_instructions_are_never_in_the_lane(self):
        excluded = (
            ".openguildkit/project.json", ".openguildkit/decisions/x.json", ".OpenGuildKit/catalog/packs/p.json",
            "package.json", "web/package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
            "pyproject.toml", "setup.py", "requirements.txt", "requirements-dev.txt", "Pipfile", "poetry.lock",
            "uv.lock", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "composer.json", "composer.lock", "Gemfile",
            "Gemfile.lock", "pom.xml", "build.gradle.kts", "app/App.csproj", "docs/example/package.json",
            ".github/workflows/ci.yml", ".GitHub/Workflows/ci.yml", "AGENTS.md", "CLAUDE.md", "docs/AGENTS.md",
            "tests/CLAUDE.md", ".claude/settings.json", ".codex/config.toml", ".cursor/rules/style.mdc",
            ".github/copilot-instructions.md", ".mcp.json",
        )
        for path in excluded:
            with self.subTest(path=path):
                self.assertTrue(light_lane.excluded_reason(path), path)
        for path in ("docs/guide.md", "tests/test_a.py", "README.md", "src/app.py", "docs/package-notes.md",
                     ".github/CODEOWNERS", "CHANGELOG.md", "docs/workflows.md"):
            with self.subTest(path=path):
                self.assertIsNone(light_lane.excluded_reason(path), path)

    def test_the_lane_never_covers_what_the_host_scan_reads_as_instructions_or_settings(self):
        for entry in (*surfaces.INSTRUCTION_PATHS, *surfaces.CONFIG_PATHS):
            with self.subTest(entry=entry):
                self.assertTrue(light_lane.excluded_reason(entry), entry)
                if not Path(entry).suffix:  # A folder of the scan: what it holds is out too.
                    self.assertTrue(light_lane.excluded_reason(f"{entry}/inside.md"), entry)

    def test_a_declared_path_that_names_an_excluded_file_or_reaches_into_a_folder_is_refused(self):
        for entry in (".openguildkit/**", ".openguildkit/project.json", "package.json", "docs/**/package.json",
                      ".github/**", ".github/workflows/*", ".github/workflows/ci.yml", "AGENTS.md", ".claude/**",
                      "**/requirements.txt".replace("**/", "docs/**/")):
            with self.subTest(entry=entry):
                self.assertTrue(light_lane.declared_excluded(entry), entry)
        for entry in ("docs/**", "tests/**", "*.md", "docs/*.md", "README.md", ".github/CODEOWNERS"):
            with self.subTest(entry=entry):
                self.assertIsNone(light_lane.declared_excluded(entry), entry)
    def test_a_glob_matches_whole_paths_and_a_star_never_crosses_a_folder(self):
        cases = (
            ("docs/**", "docs/guide.md", True), ("docs/**", "docs/api/v1/index.md", True),
            ("docs/**", "docs", False), ("docs/**", "docsx/guide.md", False), ("docs/**", "src/docs/guide.md", False),
            ("*.md", "README.md", True), ("*.md", "docs/guide.md", False),
            ("docs/*.md", "docs/guide.md", True), ("docs/*.md", "docs/api/guide.md", False),
            ("docs/**/*.md", "docs/guide.md", True), ("docs/**/*.md", "docs/a/b/guide.md", True),
            ("docs/**/*.md", "docs/a/b/guide.txt", False), ("docs/g?ide.md", "docs/guide.md", True),
            ("docs/g?ide.md", "docs/gide.md", False), ("README.md", "README.md", True), ("README.md", "readme.md", False),
        )
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertIs(light_lane.matches(pattern, path), expected)

    def test_a_declared_path_is_covered_by_a_folder_of_the_profile_or_by_the_same_glob(self):
        light = ["docs/**", "tests/**", "README.md"]
        for entry in ("docs/**", "docs/guide.md", "docs/api/*.md", "tests/unit/**", "README.md", "tests/**"):
            with self.subTest(entry=entry):
                self.assertTrue(light_lane.declared_covered(entry, light), entry)
        for entry in ("src/**", "docs", "*.md", "documents/**", "docs-old/**", "CHANGELOG.md", "test/**"):
            with self.subTest(entry=entry):
                self.assertFalse(light_lane.declared_covered(entry, light), entry)
        self.assertEqual(light_lane.outside_light_paths(["docs/a.md", "src/b.py", "x.txt"], ["docs/**"]),
                         ["src/b.py", "x.txt"])

    def test_the_board_follows_the_paths_documentation_then_tests_else_engineering(self):
        cases = (
            (["docs/**"], "developer-relations-and-docs"), (["README.md", "docs/guide.md"], "developer-relations-and-docs"),
            (["CHANGELOG.md"], "developer-relations-and-docs"), (["tests/**"], "qa"),
            (["tests/unit/test_a.py", "spec/b.rb"], "qa"), (["src/app/foo.test.ts"], "qa"),
            (["docs/**", "tests/**"], "engineering"), (["src/**"], "engineering"), (["docs/**", "src/a.py"], "engineering"),
        )
        for paths, board in cases:
            with self.subTest(paths=paths):
                self.assertEqual(light_lane.board_for(paths)[0], board)
                self.assertIn(paths[0], light_lane.board_for(paths)[1])

    def test_the_boards_the_lane_calls_for_are_boards_of_the_catalog(self):
        from openguildkit.catalog import load_catalog

        boards = load_catalog()["boards"]
        for board in (light_lane.DOCS_BOARD, light_lane.TESTS_BOARD, light_lane.DEFAULT_BOARD):
            self.assertIn(board, boards)


class ProjectCase(unittest.TestCase):
    """A project of one Python component, with no short lane until a test turns it on."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"],
                                                **getattr(self, "profile_answers", {})})
        self.run_cli("init", "--answers", self.root / "answers.json")
        (self.root / "notes.md").write_text("The guide is the only page that names the export.\n", encoding="utf-8")

    def run_cli(self, *arguments, code=0, typed=None):
        # Without a typed line, no terminal: the suite may itself run at one.
        result = run_cli(self.root, *arguments, expect=code, typed=typed, stdin="" if typed is None else None)
        return result.stdout, result.stderr

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def enable(self, *paths):
        paths = paths or DOCS_AND_TESTS
        self.run_cli("profile", "set", "light-paths", *paths, "--by", "Sam", "--reason", "Docs fixes", typed=" ".join(paths))


class ActivationTests(ProjectCase):
    """The lane is off until a person turns it on at a terminal, like every setting that lowers a protection."""

    def test_a_new_project_has_no_short_lane_and_task_new_says_the_command_that_turns_it_on(self):
        self.assertNotIn("light_paths", self.profile())
        before = self.profile()
        _, error = self.run_cli("task", "new", "Fix a typo", "--id", "typo", "--lane", "light", "--paths", "docs/**", code=1)
        self.assertTrue(error.startswith("OpenGuildKit: the short lane is off in this project"), error)
        self.assertIn("openguildkit profile set light-paths 'docs/**' --by NAME --reason WHY", error)
        self.assertIn("at their terminal", error)
        self.assertIn("without --lane", error)
        self.assertFalse((self.root / ".openguildkit" / "tasks" / "typo.json").exists())
        self.assertEqual(self.profile(), before)

    def test_the_command_proposed_for_a_path_the_lane_can_never_cover_names_the_usual_folders(self):
        _, error = self.run_cli("task", "new", "Bump", "--id", "bump", "--lane", "light", "--paths", "package.json", code=1)
        self.assertIn("openguildkit profile set light-paths 'docs/**' 'tests/**' --by NAME --reason WHY", error)

    def test_a_person_turns_the_lane_on_at_a_terminal_and_the_profile_says_who_when_and_why(self):
        output, _ = self.run_cli("profile", "set", "light-paths", "tests/**", "docs/**", "--by", "Sam",
                                 "--reason", "Docs and tests fixes", typed="tests/** docs/**")
        self.assertIn("Profile changed: set light-paths docs/**, tests/**, by Sam on ", output)
        profile = self.profile()
        self.assertEqual(profile["light_paths"], DOCS_AND_TESTS)
        change = profile["changes"][-1]
        self.assertEqual((change["change"], change["by"], change["reason"]),
                         ("set light-paths docs/**, tests/**", "Sam", "Docs and tests fixes"))
        self.assertRegex(change["on"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("task new", output)
        self.run_cli("check")

    def test_an_agent_without_a_terminal_cannot_turn_the_lane_on_and_nothing_is_written(self):
        before = (self.root / ".openguildkit" / "project.json").read_bytes()
        _, error = self.run_cli("profile", "set", "light-paths", "docs/**", "--by", "Agent", "--reason", "Faster",
                                code=1)
        self.assertIn("weakens a protection (short lane turned on for docs/**)", error)
        self.assertIn("it is the person's decision. Ask them to run the same command at an interactive terminal.", error)
        self.assertIn("Nothing was written.", error)
        self.assertEqual((self.root / ".openguildkit" / "project.json").read_bytes(), before)

    def test_the_person_must_type_what_the_command_sets_or_nothing_is_written(self):
        before = (self.root / ".openguildkit" / "project.json").read_bytes()
        _, error = self.run_cli("profile", "set", "light-paths", "docs/**", "--by", "Sam", "--reason", "Docs",
                                typed="yes", code=1)
        self.assertIn("Profile change cancelled. Nothing was written.", error)
        self.assertEqual((self.root / ".openguildkit" / "project.json").read_bytes(), before)

    def test_widening_the_lane_needs_the_person_again_and_narrowing_or_removing_it_does_not(self):
        self.enable("docs/**")
        _, error = self.run_cli("profile", "set", "light-paths", "docs/**", "tests/**", "--by", "Agent", "--reason", "More",
                                code=1)
        self.assertIn("short lane widened: tests/** added", error)
        self.assertEqual(self.profile()["light_paths"], ["docs/**"])
        self.enable("docs/**", "tests/**")
        # Fewer paths, then none: a stricter profile, so no terminal is needed (as for every setting that adds a rule).
        self.run_cli("profile", "set", "light-paths", "docs/**", "--by", "Agent", "--reason", "Tests are out")
        self.assertEqual(self.profile()["light_paths"], ["docs/**"])
        output, _ = self.run_cli("profile", "set", "light-paths", "none", "--by", "Agent", "--reason", "Lane closed")
        self.assertNotIn("light_paths", self.profile())
        self.assertIn("Profile changed: set light-paths none", output)
        self.assertEqual(self.profile()["changes"][-1]["change"], "set light-paths none")
        _, error = self.run_cli("profile", "set", "light-paths", "none", "--by", "Agent", "--reason", "Again", code=1)
        self.assertIn("light-paths is already none. Nothing was written.", error)

    def test_a_path_the_lane_can_never_cover_is_refused_even_at_a_terminal(self):
        for entry in (".openguildkit/**", "package.json", ".github/workflows/*", "AGENTS.md", "**", "/etc", "docs/../x"):
            with self.subTest(entry=entry):
                _, error = self.run_cli("profile", "set", "light-paths", entry, "--by", "Sam", "--reason", "x",
                                        typed=entry, code=1)
                self.assertTrue(error.startswith("OpenGuildKit: "), error)
                self.assertNotIn("Traceback", error)
                self.assertNotIn("light_paths", self.profile())
        self.assertIn("rules, dependencies, the profile", self.run_cli(
            "profile", "set", "light-paths", "package.json", "--by", "Sam", "--reason", "x", typed="package.json", code=1)[1])

    def test_other_settings_take_one_value_and_light_paths_take_no_option_of_another_setting(self):
        _, error = self.run_cli("profile", "set", "guard", "enforce", "tests/**", "--by", "Sam", "--reason", "x", code=1)
        self.assertIn("takes one value", error)
        _, error = self.run_cli("profile", "set", "light-paths", "docs/**", "--signers", "keys", "--by", "Sam",
                                "--reason", "x", typed="docs/**", code=1)
        self.assertIn("--signers belongs to profile set approval signed", error)

    def test_the_weakening_is_named_with_the_command_a_person_types(self):
        from openguildkit.catalog import load_catalog

        catalog = load_catalog()
        before = {**self.profile()}
        after = {**before, "light_paths": ["docs/**", "tests/**"]}
        on = profile_cli.weakening_changes(before, after, catalog)
        self.assertEqual(len(on), 1)
        self.assertEqual(on[0][1], ["profile", "set", "light-paths", "docs/**", "tests/**", "--by", "NAME", "--reason", "WHY"])
        self.assertEqual(profile_cli.weakening_changes(after, {**after, "light_paths": ["docs/**"]}, catalog), [])
        self.assertEqual(profile_cli.weakening_changes(after, before, catalog), [])
        self.assertEqual(profile_cli.weakening_changes(after, after, catalog), [])

    def test_the_web_page_cannot_turn_the_lane_on_and_is_told_the_command(self):
        edited = {**self.profile(), "light_paths": ["docs/**"]}
        with self.assertRaises(profile_cli.Weakening) as raised:
            profile_cli.save_edited(self.root, self.root / ".openguildkit", edited, "Page", "Edited in the page")
        self.assertIn("short lane turned on for docs/**", str(raised.exception))
        self.assertNotIn("light_paths", self.profile())

    def test_the_edit_hook_refuses_an_edit_of_the_profile_even_under_an_approved_task(self):
        self.run_cli("profile", "set", "guard", "enforce", "--by", "Sam", "--reason", "Audit")
        stdin = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(self.root / ".openguildkit" / "project.json")}})
        result = run_cli(self.root, "guard", "--hook", "pre-edit", stdin=stdin, expect=2)
        self.assertIn("written by the openguildkit commands", result.stderr)

    def test_a_profile_is_checked_when_it_is_read(self):
        profile = self.profile()
        for bad in ("docs/**", [3], ["docs/../x"], [".openguildkit/**"], ["**"], ["docs/**", "docs/**x"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.validate({**profile, "light_paths": bad})
        self.assertEqual(self.validate({**profile, "light_paths": ["tests/", "docs/**", "docs/**"]})["light_paths"],
                         DOCS_AND_TESTS)
        self.assertNotIn("light_paths", self.validate({**profile, "light_paths": []}))

    def validate(self, profile: dict) -> dict:
        from openguildkit.catalog import load_catalog

        return validate_profile(profile, load_catalog())

    def test_the_lane_is_not_part_of_what_an_approval_rests_on(self):
        from openguildkit.catalog import load_catalog

        profile, catalog = self.profile(), load_catalog()
        self.assertEqual(profile_fingerprint(validate_profile(profile, catalog), catalog),
                         profile_fingerprint(validate_profile({**profile, "light_paths": DOCS_AND_TESTS}, catalog), catalog))


class LaneCase(ProjectCase):
    """A project whose profile a person turned the short lane on in, for docs, source and tests."""

    def setUp(self):
        super().setUp()
        self.enable("docs/**", "src/**", "tests/**")

    def new(self, task_id="typo", *paths, brief="Fix a typo in the guide", code=0):
        return self.run_cli("task", "new", brief, "--id", task_id, "--lane", "light", "--paths", *(paths or ("docs/**",)),
                            code=code)

    def task(self, task_id="typo") -> dict:
        return json.loads(self.run_cli("task", "show", task_id)[0])

    def review(self, task_id="typo", verdict="proceed", blockers=None):
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        template["summary"] = "The board agrees: a small change."
        for entry in template["boards"]:
            entry.update(recommendation="Make the change.", open_questions=[],
                         evidence=[{"source": "project-file", "ref": "notes.md", "supports": "The guide names the export."}])
            challenge = entry["challenge"]
            for lens in challenge["specialists"]:
                lens.update(finding="Seen in the notes.", basis="observed", evidence_refs=[1])
            challenge.update(verdict=verdict, confidence="medium", alternative="Leave it as it is.",
                             failure_mode="Nothing worth naming.", verification="Read the guide again.")
            if blockers:
                challenge["blockers"] = blockers
        write_json(self.root / f"{task_id}-review.json", template)
        self.run_cli("task", "review", task_id, "--file", self.root / f"{task_id}-review.json")

    def consulted(self, task_id="typo", *paths):
        self.new(task_id, *paths)
        return self.run_cli("task", "consult", task_id)[0]

    def approved(self, task_id="typo", *paths):
        self.consulted(task_id, *paths)
        self.review(task_id)
        return self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Agreed", typed=task_id)


class TaskDeclarationTests(LaneCase):
    def test_a_task_declares_its_lane_and_its_paths_and_a_task_without_a_lane_is_unchanged(self):
        output, error = self.new("typo", "docs/**")
        self.assertEqual(output.strip(), "typo")
        self.assertIn("Short lane for docs/**: no questions", error)
        self.assertIn("openguildkit task consult typo", error)
        record = self.task()
        self.assertEqual((record["lane"], record["paths"], record["status"]), ("light", ["docs/**"], "draft"))
        self.run_cli("task", "new", "Plain", "--id", "plain")
        plain = self.task("plain")
        self.assertEqual(sorted(plain), ["brief", "created_at", "id", "rounds", "schema_version", "status"])

    def test_the_paths_are_kept_sorted_and_without_repeats(self):
        self.new("two", "tests/**", "docs/**", "docs/", "docs/**")
        self.assertEqual(self.task("two")["paths"], ["docs/**", "tests/**"])

    def test_a_path_outside_the_profile_is_refused_with_the_paths_and_the_command_of_the_full_path(self):
        _, error = self.new("wide", "docs/**", "other/a.py", "README.md", code=1)
        self.assertIn("the short lane of this project covers only docs/**, src/**, tests/**", error)
        self.assertIn("these paths are outside it: README.md, other/a.py", error)
        self.assertIn('openguildkit task new "BRIEF" --id ID, without --lane', error)
        self.assertIn("openguildkit profile set light-paths", error)
        self.assertFalse((self.root / ".openguildkit" / "tasks" / "wide.json").exists())

    def test_a_path_the_lane_never_covers_is_refused_with_the_command_of_the_full_path(self):
        for entry in ("package.json", ".openguildkit/project.json", "docs/**/package.json", ".github/workflows/ci.yml",
                      "AGENTS.md", ".claude/**", "src/pyproject.toml"):
            with self.subTest(entry=entry):
                _, error = self.new("never", entry, code=1)
                self.assertIn(entry, error)
                self.assertIn("never covers rules, dependencies, the profile and the instructions of agents", error)
                self.assertIn('openguildkit task new "BRIEF" --id ID', error)
                self.assertFalse((self.root / ".openguildkit" / "tasks" / "never.json").exists())

    def test_paths_need_a_lane_and_a_lane_needs_paths(self):
        _, error = self.run_cli("task", "new", "x", "--paths", "docs/**", code=1)
        self.assertIn("--paths belongs to the short lane: add --lane light", error)
        _, error = self.run_cli("task", "new", "x", "--lane", "light", code=1)
        self.assertIn("Name the paths a short-lane task may change: --paths GLOB...", error)
        _, error = self.run_cli("task", "new", "x", "--lane", "light", "--paths", "docs/../x", code=1)
        self.assertIn("is not a path of the short lane", error)

    def test_task_list_shows_the_lane_and_the_paths_and_a_full_path_row_is_as_before(self):
        self.new("typo", "docs/**")
        self.run_cli("task", "new", "Plain", "--id", "plain")
        text, _ = self.run_cli("task", "list")
        self.assertIn("typo [draft] Fix a typo in the guide (short lane: docs/**)\n", text)
        self.assertIn("plain [draft] Plain\n", text)
        rows = {row["id"]: row for row in json.loads(self.run_cli("task", "list", "--json")[0])}
        self.assertEqual((rows["typo"]["lane"], rows["typo"]["paths"]), ("light", ["docs/**"]))
        self.assertIn("the short lane asks no questions", rows["typo"]["next"])
        self.assertNotIn("lane", rows["plain"])
        self.assertNotIn("paths", rows["plain"])

    def test_the_questionnaire_and_the_route_preview_are_not_part_of_the_lane(self):
        self.new("typo", "docs/**")
        _, error = self.run_cli("task", "questions", "typo", code=1)
        self.assertIn("The short lane asks no questions", error)
        self.assertIn("openguildkit task consult typo", error)
        _, error = self.run_cli("task", "route", "typo", code=1)
        self.assertIn("The short lane picks its board from the paths", error)
        self.assertIn("openguildkit task consult typo", error)


class ConsultationTests(LaneCase):
    def test_the_lane_consults_one_board_by_path_with_careful_default_answers(self):
        cases = ((("docs/**",), "developer-relations-and-docs"), (("tests/**",), "qa"), (("src/**",), "engineering"),
                 (("docs/**", "tests/**"), "engineering"))
        for index, (paths, board) in enumerate(cases):
            with self.subTest(paths=paths):
                task_id = f"lane-{index}"
                consultation = self.consulted(task_id, *paths)
                record = self.task(task_id)
                self.assertEqual(record["status"], "consulting")
                self.assertEqual(record["consultation"]["boards"], [board])
                answers = {key: value for key, value in record["answers"].items() if key != "context"}
                self.assertEqual(answers, {"kind": "maintenance", "surface": ["other"], "data": "none", "research": "local",
                                           "concerns": ["none"]})
                self.assertIn("not the requester's", record["answers"]["context"])
                self.assertEqual(record["consultation"]["scope"]["lane"], {"id": "light", "paths": sorted(paths)})
                self.assertIn("Short lane", consultation)
                self.assertIn(f"- {board} (", consultation)
                template = json.loads(self.run_cli("task", "template", task_id)[0])
                self.assertEqual([entry["id"] for entry in template["boards"]], [board])

    def test_the_lane_takes_no_answers_and_no_other_board(self):
        self.new("typo", "docs/**")
        write_json(self.root / "mine.json", {"kind": "bug", "surface": ["service"], "data": "none", "research": "local",
                                             "concerns": ["none"]})
        for options in (("--answers", self.root / "mine.json"), ("--add", "qa", "--reason", "More"),
                        ("--remove", "qa", "--reason", "Fewer")):
            with self.subTest(options=options):
                _, error = self.run_cli("task", "consult", "typo", *options, code=1)
                self.assertIn("The short lane asks no questions and convenes one board", error)
                self.assertIn('openguildkit task new "BRIEF" --id ID', error)
        self.assertEqual(self.task()["status"], "draft")

    def test_a_board_the_project_has_not_enabled_is_named_with_the_command_that_enables_it(self):
        self.run_cli("profile", "add", "board", "qa", "engineering", "--by", "Sam", "--reason", "Two boards", typed="qa engineering")
        self.new("typo", "docs/**")
        _, error = self.run_cli("task", "consult", "typo", code=1)
        self.assertIn("calls for the developer-relations-and-docs board", error)
        self.assertIn("openguildkit profile add board developer-relations-and-docs --by NAME --reason WHY", error)
        self.assertIn('openguildkit task new "BRIEF" --id ID', error)

    def test_nothing_is_left_to_deliberate_with_one_board(self):
        self.consulted("typo", "docs/**")
        self.review()
        output, error = self.run_cli("task", "deliberate", "typo")
        self.assertEqual(json.loads(output)["objections"], [])
        self.assertIn("nothing to deliberate", error)

    def test_the_lane_is_consulted_again_after_a_request_for_changes_without_arguments(self):
        self.consulted("typo", "docs/**")
        self.review()
        self.run_cli("task", "decide", "typo", "--request-changes", "--by", "Camille", "--reason", "Name the page")
        self.run_cli("task", "consult", "typo", "--brief", "Fix a typo in the export page of the guide")
        record = self.task()
        self.assertEqual((record["status"], record["lane"], len(record["rounds"])), ("consulting", "light", 1))
        self.assertEqual(record["consultation"]["boards"], ["developer-relations-and-docs"])

    def test_a_lane_turned_off_after_the_task_was_opened_stops_its_consultation_and_its_approval(self):
        self.new("typo", "docs/**")
        self.run_cli("profile", "set", "light-paths", "none", "--by", "Sam", "--reason", "Closed")
        _, error = self.run_cli("task", "consult", "typo", code=1)
        self.assertIn("Task typo is in the short lane, and the profile no longer names light_paths", error)
        self.assertIn("openguildkit profile set light-paths docs/** --by NAME --reason WHY", error.replace("'", ""))
        self.assertIn('openguildkit task new "BRIEF" --follows typo', error)
        self.enable("docs/**")
        self.run_cli("task", "consult", "typo")
        self.review()
        self.run_cli("profile", "set", "light-paths", "none", "--by", "Sam", "--reason", "Closed again")
        _, error = self.run_cli("task", "decide", "typo", "--approve", "--by", "Camille", "--reason", "Agreed", typed="typo",
                                code=1)
        self.assertIn("Task typo is in the short lane, and the profile no longer names light_paths", error)
        self.assertEqual(self.task()["status"], "reviewed")


class RequiredBoardTests(LaneCase):
    profile_answers = {"required_boards": ["security"]}

    def test_a_board_the_project_requires_still_reviews_in_the_lane(self):
        self.consulted("typo", "docs/**")
        routing = self.task()["consultation"]["routing"]
        self.assertEqual(list(routing), ["developer-relations-and-docs", "security"])
        self.assertEqual(routing["security"], ["Required by the project"])


class DecisionTests(LaneCase):
    def test_the_approval_covers_the_lane_and_the_paths_and_shows_them_to_the_person(self):
        self.consulted("typo", "docs/**")
        self.review()
        shown, _ = self.run_cli("task", "challenge", "typo")
        self.assertIn("Short lane", shown)
        self.assertIn("docs/**", shown)
        _, prompt = self.run_cli("task", "decide", "typo", "--approve", "--by", "Camille", "--reason", "Agreed", typed="typo")
        self.assertIn("Short lane", prompt)
        self.assertIn("approving also approves the lane and these paths", prompt.replace("Approving", "approving"))
        task = self.task()
        payload = check_decision_seal(task)
        self.assertEqual((payload["lane"], payload["paths"]), ("light", ["docs/**"]))
        record_path = self.root / ".openguildkit" / "tasks" / "typo.json"
        # Wider paths, or the lane and the paths taken out: the record no longer matches what the person approved.
        for change in ({"paths": ["docs/**", "src/**"]}, {"lane": None, "paths": None}):
            with self.subTest(change=change):
                tampered = {**task, **change}
                tampered = {key: value for key, value in tampered.items() if value is not None}
                write_json(record_path, tampered)
                _, error = self.run_cli("task", "handoff", "typo", code=1)
                self.assertIn("no longer matches what was approved", error)
        write_json(record_path, task)
        self.run_cli("task", "handoff", "typo")

    def test_the_blockers_and_the_person_decide_in_the_lane_too(self):
        self.consulted("typo", "docs/**")
        self.review(verdict="block", blockers=[{"finding": "The guide still names the old export.", "owner": "Camille",
                                                "clears_when": "notes.md is read"}])
        _, error = self.run_cli("task", "decide", "typo", "--approve", "--by", "Camille", "--reason", "Agreed",
                                typed="typo", code=1)
        self.assertIn("Resolve each blocker before approving: developer-relations-and-docs:1", error)
        _, error = self.run_cli("task", "clear", "typo", "developer-relations-and-docs:1", "--evidence", "notes.md",
                                "--supports", "The notes were read", "--by", "CM", code=1)
        self.assertIn("Clearing a blocker is the person's act", error)
        self.run_cli("task", "clear", "typo", "developer-relations-and-docs:1", "--evidence", "notes.md",
                     "--supports", "The notes were read", "--by", "CM", typed="typo")
        _, error = self.run_cli("task", "decide", "typo", "--approve", "--by", "Agent", "--reason", "Quick", code=1)
        self.assertIn("interactive terminal", error)
        self.run_cli("task", "decide", "typo", "--approve", "--by", "Camille", "--reason", "Agreed", typed="typo")
        self.assertEqual(self.task()["status"], "approved")

    def test_the_handoff_names_the_lane_and_the_paths(self):
        self.approved("typo", "docs/**")
        handoff, _ = self.run_cli("task", "handoff", "typo")
        self.assertIn("# Approved task handoff", handoff)
        self.assertIn("Short lane: change only docs/**", handoff)
        self.assertIn("- Short lane: docs/**", handoff)

    def test_the_payload_a_signer_reads_names_the_lane_and_the_paths_and_a_full_path_payload_does_not(self):
        self.consulted("typo", "docs/**")
        self.review()
        output, shown = self.run_cli("task", "decision-payload", "typo", "--by", "Camille", "--reason", "Agreed")
        payload = json.loads(output)
        self.assertEqual((payload["lane"], payload["paths"]), ("light", ["docs/**"]))
        self.assertIn("Short lane, covering only docs/**", shown)
        self.run_cli("task", "new", "Add a retry to the export job", "--id", "retry")
        write_json(self.work / "answers-full.json", {"kind": "bug", "surface": ["service"], "data": "none",
                                                     "research": "local", "concerns": ["none"]})
        self.run_cli("task", "consult", "retry", "--answers", self.work / "answers-full.json")
        self.review("retry")
        plain = json.loads(self.run_cli("task", "decision-payload", "retry", "--by", "Camille", "--reason", "Agreed")[0])
        self.assertNotIn("lane", plain)
        self.assertNotIn("paths", plain)

    def test_the_exported_record_carries_the_lane_and_the_paths_and_nothing_else_changes_for_a_full_path_task(self):
        self.approved("typo", "docs/**")
        path = self.root / self.run_cli("task", "export", "typo")[0].strip()
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((record["lane"], record["paths"]), ("light", ["docs/**"]))
        self.assertEqual(record["decision"]["payload"]["paths"], ["docs/**"])
        first = path.read_bytes()
        self.run_cli("task", "export", "typo")
        self.assertEqual(path.read_bytes(), first)
        self.assertIn("holds under the current rules", self.run_cli("task", "list", "--decisions")[0])
        # Whoever widens the paths of the record and recomputes its digest cannot recompute the approval's seal.
        wider = {**record, "paths": ["docs/**", "src/**"]}
        wider["record_sha256"] = record_digest(wider)
        write_json(path, wider)
        listing, _ = self.run_cli("task", "list", "--decisions")
        self.assertIn("the lane or the paths of the record are not those that were approved", listing)
        for broken in ({**record, "paths": "docs/**"}, {key: value for key, value in record.items() if key != "paths"}):
            write_json(path, broken)
            self.assertIn("is not a decision record written by openguildkit task export", self.run_cli("task", "list", "--decisions")[0])
        self.run_cli("task", "new", "Plain", "--id", "plain")
        self.assertNotIn("lane", self.task("plain"))


class OutputBudgetTests(LaneCase):
    """The words the lane adds stay short, since an agent reads them again at every turn: each message at most
    MESSAGE_BUDGET bytes, and a consultation, a pass and a handoff within the budgets of tests/test_output_size.py."""

    MESSAGE_BUDGET = 1_200

    def test_every_new_message_is_short(self):
        messages = {}
        messages["new"] = self.new("typo", "docs/**")[1]
        messages["questions"] = self.run_cli("task", "questions", "typo", code=1)[1]
        messages["route"] = self.run_cli("task", "route", "typo", code=1)[1]
        messages["options"] = self.run_cli("task", "consult", "typo", "--add", "qa", "--reason", "More", code=1)[1]
        messages["outside"] = self.new("wide", "docs/**", "other/a.py", "README.md", "other/b.py", code=1)[1]
        messages["never"] = self.new("never", "docs/**/package.json", code=1)[1]
        messages["paths without a lane"] = self.run_cli("task", "new", "x", "--paths", "docs/**", code=1)[1]
        messages["enable"] = self.run_cli("profile", "set", "light-paths", "docs/**", "src/**", "tests/**", "extra/**",
                                          "--by", "Agent", "--reason", "More", code=1)[1]
        self.run_cli("profile", "set", "light-paths", "none", "--by", "Sam", "--reason", "Closed")
        messages["off"] = self.new("later", "docs/**", code=1)[1]
        messages["turned off"] = self.run_cli("task", "consult", "typo", code=1)[1]
        self.enable("docs/**")
        messages["hint"] = self.run_cli("profile", "set", "light-paths", "docs/**", "tests/**", "--by", "Sam", "--reason", "More",
                                        typed="docs/** tests/**")[0]
        self.run_cli("task", "consult", "typo")
        self.review()
        self.run_cli("task", "decide", "typo", "--approve", "--by", "Camille", "--reason", "Agreed", typed="typo")
        for name, text in messages.items():
            with self.subTest(message=name):
                self.assertGreater(len(text), 0)
                self.assertLessEqual(len(text.encode("utf-8")), self.MESSAGE_BUDGET, text)
        # The lines the lane adds to the decision and to the handoff are short; the approval prompt that carries them
        # also holds the review, which has its own budget.
        task = self.task()
        added = [*light_lane.decision_lines(task), light_lane.handoff_note(task), light_lane.scope_line(
            task["consultation"]["scope"]["lane"])]
        for text in added:
            self.assertLessEqual(len(text.encode("utf-8")), 600, text)

    def test_the_lane_consults_passes_and_hands_off_within_the_budgets_of_the_full_path(self):
        from tests.test_output_size import BUDGETS

        consultation = self.consulted("typo", "docs/**")
        pass_text, _ = self.run_cli("task", "pass", "typo", "developer-relations-and-docs")
        self.assertLessEqual(len(consultation.encode("utf-8")), BUDGETS["consultation"])
        self.assertLessEqual(len(pass_text.encode("utf-8")), BUDGETS["pass"])
        self.review()
        self.run_cli("task", "decide", "typo", "--approve", "--by", "Camille", "--reason", "Agreed", typed="typo")
        handoff, _ = self.run_cli("task", "handoff", "typo")
        self.assertLessEqual(len(handoff.encode("utf-8")), BUDGETS["handoff"])


BEFORE = json.loads((REPO / "tests" / "fixtures" / "upgrade" / "before-light-lane.json").read_text(encoding="utf-8"))
STDIN = {"guard --hook pre-edit": '{"tool_name": "Edit", "tool_input": {"file_path": "$PROJECT/app.py"}}',
         "guard --hook prompt": ""}


class BeforeTheShortLaneTests(unittest.TestCase):
    """A project written by the code before the lane (tests/fixtures/upgrade/before-light-lane.json: its profile, a
    finished task and its exported record, an approved task, a draft, and what each command printed then) reads and
    verifies the same with this code, and the lane stays off in it."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, content in BEFORE["files"].items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        clock = patch("openguildkit.clock.real_now", return_value=datetime.fromisoformat(BEFORE["now"]))
        clock.start()
        self.addCleanup(clock.stop)

    def test_every_command_prints_what_it_printed_before_the_lane(self):
        for name, expected in BEFORE["expected"].items():
            with self.subTest(command=name):
                stdin = STDIN.get(name)
                result = run_cli(self.root, *shlex.split(name), expect=None,
                                 stdin=stdin.replace("$PROJECT", str(self.root)) if stdin is not None else None)
                self.assertEqual(result.returncode, expected["code"])
                self.assertEqual(result.stdout.replace(str(self.root), "$PROJECT"), expected["stdout"])
                self.assertEqual(result.stderr.replace(str(self.root), "$PROJECT"), expected["stderr"])

    def test_an_exported_record_of_the_old_code_is_written_again_byte_for_byte(self):
        target = self.root / "again.json"
        run_cli(self.root, "task", "export", "done-task", "--output", target)
        self.assertEqual(target.read_text(encoding="utf-8"), BEFORE["files"][".openguildkit/decisions/done-task.json"])

    def test_turning_the_lane_on_or_off_voids_no_approval_of_that_project(self):
        output = run_cli(self.root, "profile", "set", "light-paths", "docs/**", "--by", "Sam", "--reason", "Docs fixes",
                         typed="docs/**").stdout
        self.assertIn("No open task was consulted under the previous profile.", output)
        listing = run_cli(self.root, "task", "list").stdout
        self.assertIn("approved-task [approved, approved by Camille]", listing)
        self.assertNotIn("no longer holds", listing)
        self.assertIn("# Approved task handoff", run_cli(self.root, "task", "handoff", "approved-task").stdout)
        output = run_cli(self.root, "profile", "set", "light-paths", "none", "--by", "Sam", "--reason", "Closed").stdout
        self.assertIn("No open task was consulted under the previous profile.", output)
        self.assertIn("# Approved task handoff", run_cli(self.root, "task", "handoff", "approved-task").stdout)

    def test_the_old_records_hold_no_lane_and_the_profile_no_light_paths(self):
        self.assertNotIn("light_paths", json.loads(BEFORE["files"][".openguildkit/project.json"]))
        for name, content in BEFORE["files"].items():
            if name.startswith(".openguildkit/tasks/") or name.startswith(".openguildkit/decisions/"):
                with self.subTest(name=name):
                    self.assertNotIn('"lane"', content)
                    self.assertNotIn('"paths"', content)

    def test_a_full_path_task_runs_as_before_and_leaves_the_profile_as_it_was(self):
        before = (self.root / ".openguildkit" / "project.json").read_bytes()
        run_cli(self.root, "task", "new", "Fix a typo in the export help", "--id", "typo")
        answers = self.root / "answers.json"
        write_json(answers, {"kind": "bug", "surface": ["service"], "data": "none", "research": "local",
                             "concerns": ["none"], "context": "A typo in the export help text."})
        run_cli(self.root, "task", "consult", "typo", "--answers", answers)
        record = json.loads(run_cli(self.root, "task", "show", "typo").stdout)
        self.assertNotIn("lane", record)
        self.assertNotIn("paths", record)
        self.assertEqual(record["consultation"]["boards"], ["engineering"])
        self.assertEqual((self.root / ".openguildkit" / "project.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
