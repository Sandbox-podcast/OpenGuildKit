"""Stable error codes (#487): each error a person reads from the task commands carries a code raised from one place,
listed in docs/errors.md and docs/agents/errors.json with its function and the tests that cite it."""

import ast
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit import mcp_mock, project, tasks_decide_cli
from openguildkit.catalog import load_catalog
from openguildkit.errors import OgkError, error_line
from openguildkit.storage import write_json
from openguildkit.tasks import create_task
from tests.test_approval_lifecycle import ApprovalCase

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_errors", REPO / "scripts" / "build_errors.py")
build_errors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_errors)

CODE = re.compile(r"OGK-[A-Z]+-\d{3}")
# The modules whose errors all carry a code: a ValueError raised with a message there fails the test.
CODED = ("tasks.py", "tasks_cli.py")
# The `raise ValueError(...)` left in the package: the count may go down, never up (#487). Lower it with the code.
UNCODED_CEILING = 247


def uncoded_sites(path: Path) -> list[int]:
    """The lines of a module that raise a ValueError with a message and no code."""
    return [node.lineno for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name) and node.exc.func.id == "ValueError" and node.exc.args]


class RegisterTests(unittest.TestCase):
    def test_issue_487_the_register_is_what_build_errors_writes(self):
        """Issue #487: no error had a code, and a message was found only by searching its words."""
        entries = build_errors.build()
        self.assertEqual((REPO / build_errors.REGISTER).read_text(encoding="utf-8"), build_errors.register_text(entries),
                         "run python scripts/build_errors.py")
        self.assertEqual((REPO / build_errors.PAGE).read_text(encoding="utf-8"), build_errors.page_text(entries))
        self.assertIn('"code": "OGK-TASK-012"', (REPO / build_errors.REGISTER).read_text(encoding="utf-8"))

    def test_issue_487_each_code_is_well_formed_raised_from_one_place_and_cited_by_a_test(self):
        """Issue #487: 34 messages were raised from several places, 22 from several modules."""
        self.assertEqual(build_errors.problems(build_errors.raise_sites(REPO), build_errors.build()), [])
        self.assertGreaterEqual(len(build_errors.build()), 13)

    def test_issue_487_a_duplicated_code_a_code_without_test_and_a_bad_code_are_named(self):
        """Issue #487: nothing refused a code raised twice or a code no test cites."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "src" / "openguildkit").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "src" / "openguildkit" / "a.py").write_text(
                'def f():\n    raise OgkError("OGK-A-001", "One.")\n\n\ndef g():\n    raise OgkError("OGK-A-001", "Two.")\n'
                '\n\ndef h(code):\n    raise OgkError(code, "Three.")\n', encoding="utf-8")
            (root / "tests" / "test_a.py").write_text("", encoding="utf-8")
            found = build_errors.problems(build_errors.raise_sites(root), build_errors.build(root))
        self.assertEqual(found, ["OGK-A-001 is raised from 2 places: src/openguildkit/a.py:2, src/openguildkit/a.py:6",
                                 "OGK-A-001: no test cites it",
                                 "src/openguildkit/a.py:10: the code must be written as OGK-AREA-NNN"])

    def test_issue_487_a_coded_module_raises_no_value_error_without_a_code(self):
        """Issue #487: the errors of the task commands were bare ValueError, their text the only identifier."""
        package = REPO / "src" / "openguildkit"
        self.assertEqual({name: uncoded_sites(package / name) for name in CODED if uncoded_sites(package / name)}, {})
        total = sum(len(uncoded_sites(path)) for path in package.glob("*.py"))
        self.assertLessEqual(total, UNCODED_CEILING, "give the new errors a code (errors.OgkError)")
        self.assertEqual(total, UNCODED_CEILING, f"lower UNCODED_CEILING to {total}: it only goes down")

    def test_issue_487_the_line_puts_the_code_before_the_message(self):
        """Issue #487: cli.main printed every error as `OpenGuildKit: message`, without a code."""
        error = OgkError("OGK-TASK-004", "Task already exists: twin")
        self.assertEqual(str(error), "Task already exists: twin")
        self.assertIsInstance(error, ValueError)
        self.assertEqual(error_line(error, str(error)), "OpenGuildKit [OGK-TASK-004]: Task already exists: twin")
        self.assertEqual(error_line(ValueError("Plain."), "Plain."), "OpenGuildKit: Plain.")


class TaskErrorTests(ApprovalCase):
    """Each code of the task commands, provoked as a person meets it."""

    def setUp(self):
        super().setUp()
        self.init()

    def refused(self, code, *arguments):
        _, error = self.run_cli(*arguments, code=1)
        self.assertTrue(error.startswith(f"OpenGuildKit [{code}]: "), error)
        return error

    def test_issue_487_the_task_commands_print_their_code(self):
        """Issue #487: each error of task new, task list and task show starts with its stable code."""
        self.run_cli("task", "new", "First.", "--id", "first")
        self.refused("OGK-TASK-001", "task", "new", "Loop.", "--id", "loop", "--after", "loop")
        self.run_cli("task", "new", "Later.", "--id", "later", "--after", "first")
        (self.state / "tasks" / "first.json").unlink()
        self.refused("OGK-TASK-002", "task", "new", "Again.", "--id", "first", "--after", "later")
        self.refused("OGK-TASK-003", "task", "new", "Empty.", "--id", " ")
        error = self.refused("OGK-TASK-004", "task", "new", "Twice.", "--id", "later")
        self.assertEqual(error, "OpenGuildKit [OGK-TASK-004]: Task already exists: later\n")
        self.refused("OGK-TASK-005", "task", "new", "Next.", "--follows", "later")
        self.refused("OGK-TASK-006", "task", "list", "--since", "2026-02-30")
        self.refused("OGK-TASK-007", "task", "new")
        write_json(self.state / "decisions" / "gone.json", {"task": "gone"})
        self.refused("OGK-TASK-008", "task", "new", "Reused.", "--id", "gone")
        self.refused("OGK-TASK-010", "task", "show", "gone", "--summary")
        self.refused("OGK-TASK-011", "task", "handoff", "gone")
        self.refused("OGK-TASK-009", "task", "review", "later", "--summary", "Too early.")

    def test_issue_487_a_decision_on_a_task_that_changed_meanwhile_has_its_code(self):
        """Issue #487: "The task changed while you were deciding" had four sites in tasks_cli.py and no code."""
        create_task(self.state, "Decide.", "decide")
        task = tasks_decide_cli.read_task(self.state, "decide")
        with self.assertRaises(OgkError) as raised:
            tasks_decide_cli._save_decided(self.state, {**task, "brief": "Another brief."}, task)
        self.assertEqual(raised.exception.code, "OGK-TASK-013")


class CodedRefusals(unittest.TestCase):
    """Calls each case and expects the OgkError of its code: the errors no other test meets (#487)."""

    def assertCodes(self, cases):
        for code, call in cases:
            with self.subTest(code=code), self.assertRaises(OgkError) as raised:
                call()
            self.assertEqual(raised.exception.code, code, raised.exception)


class ProfileErrorTests(CodedRefusals):
    """Issue #487: each field of project.json that is wrong is refused with its own code."""

    def test_issue_487_each_wrong_field_of_a_profile_has_its_code(self):
        catalog = load_catalog()
        pack, other = "agent-workflow", "agent-native-engineering"

        def profile(**fields):
            return lambda: project.validate_profile({"name": "Shop", "stack": ["Python"], **fields}, catalog)

        signed = {"mode": "signed", "allowed_signers": "keys", "approvers": ["Sam"]}
        resolution = {"packs": [pack, other], "keep": [pack], "reason": "One."}
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "file").write_text("", encoding="utf-8")
            root = Path(folder).resolve()
            (root / "elsewhere").mkdir()
            (root / project.STATE_DIR).symlink_to(root / "elsewhere")
            self.assertCodes([("OGK-PROJECT-045", lambda: project.project_root(root / "file")),
                              ("OGK-PROJECT-046", lambda: project.state_path(root))])
        self.assertCodes([
            ("OGK-PROJECT-047", profile(components={})),
            ("OGK-PROJECT-048", profile(components=[{"id": "api"}])),
            ("OGK-PROJECT-049", profile(components=[{"id": "API", "stack": ["Python"]}])),
            ("OGK-PROJECT-050", profile(components=[{"id": "api", "stack": ["Python"]}] * 2)),
            ("OGK-PROJECT-051", profile(frozen={"by": "Sam", "on": "today", "reason": "Audit."})),
            ("OGK-PROJECT-052", profile(declined={})),
            ("OGK-PROJECT-053", profile(declined=[{"id": "a-b-testing"}])),
            ("OGK-PROJECT-054", profile(declined_rules={})),
            ("OGK-PROJECT-055", profile(approval={"mode": "local", "roles": {}})),
            ("OGK-PROJECT-056", profile(approval={"mode": "local", "roles": {"backend": []}})),
            ("OGK-PROJECT-057", profile(changes={})),
            ("OGK-PROJECT-058", profile(changes=[{"change": "x"}])),
            ("OGK-PROJECT-059", profile(patterns=[{"id": "a-b-testing"}])),
            ("OGK-PROJECT-060", profile(patterns=["no-such-pattern"])),
            ("OGK-PROJECT-061", profile(resolutions={})),
            ("OGK-PROJECT-062", profile(resolutions=[{"packs": [pack, other]}])),
            ("OGK-PROJECT-063", profile(resolutions=[{**resolution, "packs": [pack]}])),
            ("OGK-PROJECT-064", profile(resolutions=[{**resolution, "reason": "Two\nlines."}])),
            ("OGK-PROJECT-065", profile(resolutions=[resolution, resolution])),
            ("OGK-PROJECT-066", profile(colour="blue")),
            ("OGK-PROJECT-067", profile(name=" ")),
            ("OGK-PROJECT-068", profile(approval={"mode": "remote"})),
            ("OGK-PROJECT-069", profile(approval={"mode": "signed"})),
            ("OGK-PROJECT-070", profile(approval={**signed, "allowed_signers": "../keys"})),
            ("OGK-PROJECT-071", profile(approval={"mode": "local", "approvers": ["Sam"]})),
            ("OGK-PROJECT-072", profile(approval={"mode": "local", "max_age_days": 0})),
            ("OGK-PROJECT-073", profile(waivers={"allowed_by": ["Sam"]})),
            ("OGK-PROJECT-074", profile(waivers={"allowed_by": ["Sam"], "max_days": 400})),
            ("OGK-PROJECT-075", profile(frozen={"by": "Sam"})),
        ])


class MockErrorTests(CodedRefusals):
    """Issue #487: each part of a mock MCP file that is wrong is refused with its own code."""

    def test_issue_487_each_wrong_part_of_a_mock_has_its_code(self):
        schema = {"type": "object", "properties": {"id": {"type": "string"}}}
        answer = {"name": "find", "description": "Find.", "inputSchema": schema, "responses": [{"result": {}}]}
        items = {"key": "id", "items": [{"id": "a"}]}

        def mock(tools=None, records=None, **top):
            return lambda: mcp_mock.validate_mock({"tool": "crm", "tools": tools or [answer], **(
                {"records": records} if records is not None else {}), **top}, "crm")

        tool = {key: value for key, value in answer.items() if key != "responses"}
        self.assertCodes([
            ("OGK-MCP-006", mock(records=[])),
            ("OGK-MCP-007", mock(records={"people": {"key": "id"}})),
            ("OGK-MCP-008", mock(records={"people": {"items": ["a"]}})),
            ("OGK-MCP-009", mock(records={"people": {"items": [], "title": 3}})),
            ("OGK-MCP-010", mock(records={"people": {**items, "refs": {"team": "teams"}}})),
            ("OGK-MCP-011", mock([{**answer, "serve": {}}])),
            ("OGK-MCP-012", mock([{**tool, "serve": {"records": "people", "action": "delete"}}], {"people": items})),
            ("OGK-MCP-013", mock([{**tool, "serve": {"records": "people", "action": "get", "argument": "x"}}],
                                 {"people": items})),
            ("OGK-MCP-014", mock([{**tool, "serve": {"records": "people", "action": "list", "filters": {"x": "y"}}}],
                                 {"people": items})),
            ("OGK-MCP-015", mock([{**answer, "check": {"x": {"records": "people"}}}], {"people": items})),
            ("OGK-MCP-016", mock([{**answer, "example": []}])),
            ("OGK-MCP-017", mock(extra=1)),
            ("OGK-MCP-018", lambda: mcp_mock.validate_mock({"tool": "erp", "tools": [answer]}, "crm")),
            ("OGK-MCP-019", lambda: mcp_mock.validate_mock({"tool": "crm", "tools": []}, "crm")),
            ("OGK-MCP-020", mock([{"name": "find"}])),
            ("OGK-MCP-021", mock([answer, answer])),
            ("OGK-MCP-022", mock([{**answer, "read_only": "yes"}])),
            ("OGK-MCP-023", mock([{**answer, "inputSchema": {"type": "array"}}])),
            ("OGK-MCP-024", mock([{**answer, "inputSchema": {**schema, "required": ["x"]}}])),
            ("OGK-MCP-025", mock([{**answer, "responses": []}])),
            ("OGK-MCP-026", mock([{**answer, "responses": [{"result": {}, "error": "x"}]}])),
            ("OGK-MCP-027", mock([{**answer, "responses": [{"when": [], "result": {}}]}])),
            ("OGK-MCP-028", mock([{**answer, "responses": [{"when": {"id": "a"}, "result": {}}]}])),
            ("OGK-MCP-029", lambda: mcp_mock.apply_scenario({"tool": "crm"}, [], "scenario.json")),
        ])


if __name__ == "__main__":
    unittest.main()
