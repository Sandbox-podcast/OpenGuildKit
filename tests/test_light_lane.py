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

class ActivationTests(unittest.TestCase):
    """The lane is off until a person turns it on at a terminal, like every setting that lowers a protection."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"]})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def run_cli(self, *arguments, code=0, typed=None):
        # Without a typed line, no terminal: the suite may itself run at one.
        result = run_cli(self.root, *arguments, expect=code, typed=typed, stdin="" if typed is None else None)
        return result.stdout, result.stderr

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def enable(self, *paths):
        self.run_cli("profile", "set", "light-paths", *(paths or DOCS_AND_TESTS), "--by", "Sam", "--reason", "Docs fixes",
                     typed=" ".join(paths or DOCS_AND_TESTS))

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
