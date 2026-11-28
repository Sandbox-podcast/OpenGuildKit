"""Stable error codes (#487): each error a person reads from the task commands carries a code raised from one place,
listed in docs/errors.md and docs/agents/errors.json with its function and the tests that cite it."""

import argparse
import ast
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import (
    alerts,
    controls,
    guard_export,
    lock,
    market,
    mcp_mock,
    profile_edits,
    project,
    rule_checks,
    storybook,
    tasks_closing,
    tasks_decide_cli,
)
from openguildkit.catalog import CatalogError, load_catalog
from openguildkit.errors import OgkError, error_line
from openguildkit.storage import write_json
from openguildkit.tasks import create_task
from tests.test_approval_lifecycle import ApprovalCase

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_errors", REPO / "scripts" / "build_errors.py")
build_errors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_errors)

CODE = re.compile(r"OGK-[A-Z]+-\d{3}")
# The errors a person can read: ValueError and the classes that derive from it or answer the web page. No error a person
# reads may be built without a code (#487), in any module; a broken invariant of the code raises errors.InternalError.
PERSON_ERRORS = ("ValueError", "CatalogError", "TaskStateError", "Refused", "RuleError", "SignerNotCurrent",
                 "InvalidProfile", "EntryProblems", "Weakening", "ExcludedPath", "NestedTooDeeply")
UNCODED_CEILING = 0  # Stays 0: every error a person reads takes its code first.


def uncoded_sites(path: Path) -> list[int]:
    """The lines of a module that build an error a person reads without its code as first argument."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PERSON_ERRORS \
                and (node.args or node.keywords):
            first = node.args[0] if node.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str) and CODE.fullmatch(first.value)):
                found.append(node.lineno)
    return found


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
        """Issue #487: the errors a person read were bare ValueError, their text the only identifier."""
        package = REPO / "src" / "openguildkit"
        uncoded = {path.name: uncoded_sites(path) for path in sorted(package.glob("*.py")) if uncoded_sites(path)}
        self.assertEqual(sum(len(lines) for lines in uncoded.values()), UNCODED_CEILING,
                         f"no error a person reads may be built without a code: give each its code (errors.OgkError), "
                         f"or raise errors.InternalError for a broken invariant of the code: {uncoded}")

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


class RuleCheckErrorTests(CodedRefusals):
    """Issue #487: each part of a rule check that is wrong is refused with its own code."""

    def test_issue_487_each_wrong_part_of_a_check_has_its_code(self):
        text = {"kind": "text", "paths": ["README.md"], "contains": ["x"], "expect": "present"}
        field = {"kind": "field", "path": "package.json", "field": "name", "equals": "x"}

        def check(base, allow_command=False, **fields):
            return lambda: rule_checks.validate_check({**base, **fields}, "check", allow_command=allow_command)

        self.assertCodes([
            ("OGK-RULE-015", check(text, contains=[])),
            ("OGK-RULE-016", check(text, expect="maybe")),
            ("OGK-RULE-017", check(text, ignore_case="yes")),
            ("OGK-RULE-018", check(field, path="setup.cfg")),
            ("OGK-RULE-019", check(field, field="tool..name")),
            ("OGK-RULE-020", check({key: value for key, value in field.items() if key != "equals"})),
            ("OGK-RULE-021", check(field, min="1")),
            ("OGK-RULE-022", check(field, min=2, max=1)),
            ("OGK-RULE-023", check(field, equals=[1])),
            ("OGK-RULE-024", check(field, one_of=[])),
            ("OGK-RULE-025", lambda: rule_checks.validate_check([], "check", allow_command=False)),
            ("OGK-RULE-026", check({"kind": "command"}, allow_command=True, command=" ")),
            ("OGK-RULE-027", lambda: rule_checks.parse_fields(b"name = ", "pyproject.toml")),
        ])


class MarketErrorTests(CodedRefusals):
    """Issue #487: each part of a market dossier that is wrong is refused with its own code."""

    def test_issue_487_each_wrong_part_of_a_dossier_has_its_code(self):
        rival = {"id": "rival", "name": "Rival", "kind": "direct"}
        dossier = market.new_dossier("crm", {"market": "CRM", "audience": "Teams", "feature": "Notes"})
        known = market.add_competitor(dossier, rival)
        source = {"competitor": "rival", "url": "https://rival.example.com/", "kind": "pricing"}
        watched = market.watch_source(known, source)
        observation = {"id": "o1", "competitor": "rival", "claim": "Cheap.", "source": {"ref": "Notes.", "date": "2026-01-02"}}

        def check(**fields):
            return lambda: market.validate_dossier({**known, **fields}, "crm")

        def watch(**fields):
            return check(watch={"sources": [], "every_days": 30, **fields})

        self.assertCodes([
            ("OGK-MARKET-014", lambda: market.dossier_path(Path("state"), "CRM")),
            ("OGK-MARKET-015", check(market=" ")),
            ("OGK-MARKET-016", check(observations=[{**observation, "source": {"ref": "Notes."}}])),
            ("OGK-MARKET-017", lambda: market.validate_dossier({"id": "crm"}, "crm")),
            ("OGK-MARKET-018", lambda: market.validate_dossier(known, "erp")),
            ("OGK-MARKET-019", check(competitors=[{"id": "rival"}])),
            ("OGK-MARKET-020", check(competitors=[rival, rival])),
            ("OGK-MARKET-021", check(competitors=[{**rival, "kind": "friend"}])),
            ("OGK-MARKET-022", check(observations=[{"id": "o1"}])),
            ("OGK-MARKET-023", check(observations=[observation, observation])),
            ("OGK-MARKET-024", check(watch={"sources": []})),
            ("OGK-MARKET-025", watch(every_days=0)),
            ("OGK-MARKET-026", watch(sources=[{"competitor": "rival"}])),
            ("OGK-MARKET-027", watch(sources=[{**source, "provided_by": "Sam"}])),
            ("OGK-MARKET-028", watch(changes=[{"competitor": "rival"}])),
            ("OGK-MARKET-029", lambda: market.describe(known, {"title": None})),
            ("OGK-MARKET-030", lambda: market.add_competitor(known, rival)),
            ("OGK-MARKET-031", lambda: market.set_unknown(known, "Price.", remove=True)),
            ("OGK-MARKET-032", lambda: market.mark_checked(known, source["url"])),
            ("OGK-MARKET-033", lambda: market.watch_source(watched, source)),
            ("OGK-MARKET-034", lambda: market.mark_checked(watched, "https://other.example.com/")),
        ])


class StorybookErrorTests(CodedRefusals):
    """Issue #487: each wrong Storybook index, record, proposal or option is refused with its own code."""

    def test_issue_487_each_wrong_storybook_input_has_its_code(self):
        story = {"id": "button--primary", "title": "Button", "name": "Primary"}
        index = {"ref": "company", "source": "a", "sha256": "b", "recorded": "2026-01-02", "stories": [story]}
        item = {"key": "button", "status": "proposed", "name": "Button"}
        proposals = {"schema_version": 1, "components": [item], "variants": [], "tokens": []}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".storybook").mkdir()

            def entries(**entry):
                def read():
                    write_json(root / "index.json", {"v": 5, "entries": {"button--primary": {**story, **entry}}})
                    return storybook.read_index(root / "index.json")
                return read

            def record(**fields):
                return lambda: storybook.validate_record({"schema_version": 1, "indexes": [{**index, **fields}]})

            def proposed(**fields):
                return lambda: storybook.validate_proposals({**proposals, **fields})

            write_json(root / "old.json", {"v": 3, "entries": {}})
            write_json(root / "inventory.json", {"schema_version": 2})
            self.assertCodes([
                ("OGK-STORY-014", lambda: storybook.ref_id("Company")),
                ("OGK-STORY-015", lambda: storybook.read_index(root / "old.json")),
                ("OGK-STORY-016", entries(name=" ")),
                ("OGK-STORY-017", entries(type="page")),
                ("OGK-STORY-018", entries(tags="ui")),
                ("OGK-STORY-019", lambda: storybook.compose(root, "company", "https://x.example.com", config_dir="..")),
                ("OGK-STORY-020", lambda: storybook.compose(root, "company", "https://x.example.com", title="A\nB")),
                ("OGK-STORY-021", record(stories=[{"id": "x"}])),
                ("OGK-STORY-022", lambda: storybook.validate_record({"schema_version": 2})),
                ("OGK-STORY-023", lambda: storybook.validate_record({"schema_version": 1, "indexes": [{"ref": "x"}]})),
                ("OGK-STORY-024", lambda: storybook.validate_record({"schema_version": 1, "indexes": [index, index]})),
                ("OGK-STORY-025", record(recorded="today")),
                ("OGK-STORY-026", record(stories={})),
                ("OGK-STORY-027", lambda: list(storybook.source_files([root / "missing"]))),
                ("OGK-STORY-028", lambda: storybook.import_indexes(root, root, ref=storybook.PROJECT_REF)),
                ("OGK-STORY-029", lambda: storybook.import_indexes(root, root)),
                ("OGK-STORY-030", proposed(components=[{**item, "name": " "}])),
                ("OGK-STORY-031", lambda: storybook.validate_proposals({"schema_version": 1})),
                ("OGK-STORY-032", proposed(variants=[{"key": "v", "status": "proposed", "name": "V", "component": "x"}])),
                ("OGK-STORY-033", proposed(components=[item, item])),
                ("OGK-STORY-034", proposed(components=[{**item, "args": []}])),
                ("OGK-STORY-035", proposed(components=[{**item, "callback_props": [""]}])),
                ("OGK-STORY-036", lambda: storybook.propose(root, root, root / "inventory.json")),
            ])


class RegistryErrorTests(CodedRefusals):
    """Issue #487: a wrong controls registry, alert register or catalog lock is refused with its own code."""

    def test_issue_487_each_wrong_control_has_its_code(self):
        data = controls.load()
        item = data["controls"][0]

        def registry(**fields):
            return lambda: controls.validate({**data, **fields})

        def control(**fields):
            return registry(controls=[{**item, **fields}])

        self.assertCodes([
            ("OGK-CONTROL-014", control(maps_to=["eu-ai-act"])),
            ("OGK-CONTROL-015", registry(frameworks=["no-such-framework"])),
            ("OGK-CONTROL-016", registry(schema_version=2)),
            ("OGK-CONTROL-017", registry(controls=[{"id": "x"}])),
            ("OGK-CONTROL-018", control(commands="check")),
            ("OGK-CONTROL-019", control(code=[])),
            ("OGK-CONTROL-020", control(maps_to={})),
            ("OGK-CONTROL-021", lambda: controls.update_page("No markers.", data)),
        ])

    def test_issue_487_each_wrong_alert_input_has_its_code(self):
        alert = {"id": "npm:left-pad:ghsa-1", "ecosystem": "npm", "package": "left-pad", "severity": "high"}
        register = {"schema_version": 1, "imports": [], "alerts": [{**alert, "status": "resolved"}]}
        with tempfile.TemporaryDirectory() as folder:
            write_json(Path(folder) / alerts.REGISTER_FILE, {"schema_version": 2})
            self.assertCodes([("OGK-ALERTS-013", lambda: alerts.load_register(Path(folder)))])
        self.assertCodes([
            ("OGK-ALERTS-010", lambda: alerts.read_report(b"{", "report.json")),
            ("OGK-ALERTS-011", lambda: alerts.read_report(b" ", "report.json")),
            ("OGK-ALERTS-012", lambda: alerts.read_report(b'{"vulnerabilities": {"a": 1}}', "report.json")),
            ("OGK-ALERTS-014", lambda: alerts.set_status(register, alert["id"], "confirmed", "Sam")),
            ("OGK-ALERTS-015", lambda: alerts.set_severity(register, alert["id"], "huge", "Sam", "CVSS 9.")),
            ("OGK-ALERTS-016", lambda: alerts.set_severity(register, alert["id"], "low", " ", "CVSS 2.")),
            ("OGK-ALERTS-017", lambda: alerts.accept_alert(register, alert["id"], "Sam", "Accepted.")),
        ])

    def test_issue_487_each_wrong_catalog_lock_has_its_code(self):
        catalog = load_catalog()
        pack = catalog["packs"]["agent-workflow"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "catalog.lock.json"

            def locked(records, version=1):
                def read():
                    write_json(path, {"schema_version": version, "records": records})
                    return lock._validated_lock(path)
                return read

            with patch("openguildkit.lock.validate_dependencies", side_effect=CatalogError("OGK-CATALOG-056", "loop")):
                self.assertCodes([("OGK-CORE-020", lambda: lock.apply_lock(catalog, {"records": {"packs": {}}}))])
            self.assertCodes([
                ("OGK-CORE-015", locked({}, version=2)),
                ("OGK-CORE-016", locked({"widgets": {}})),
                ("OGK-CORE-017", locked({"packs": {"x": {"id": "x"}}})),
                ("OGK-CORE-018", locked({"packs": {"other": pack}})),
                ("OGK-CORE-019", lambda: lock.central_policy(argparse.Namespace(policy_repo="repo", policy_commit=None))),
            ])


class ProfileEditErrorTests(CodedRefusals):
    """Issue #487: each profile command that would change nothing, or whose words do not fit, has its own code."""

    def test_issue_487_each_refused_profile_edit_has_its_code(self):
        catalog = load_catalog()
        profile = project.validate_profile({"name": "Shop", "stack": ["Python"], "patterns": ["a-b-testing"],
                                            "declined": ["account-health-review"]}, catalog)
        roles = {"approval": {"mode": "local", "roles": {"backend": ["Sam"]}}}

        def words(pattern, rule=None):
            return lambda: profile_edits.rule_argument(argparse.Namespace(profile_action="adopt", pattern=pattern, rule=rule))

        self.assertCodes([
            ("OGK-PROFILE-022", lambda: profile_edits._adopt(profile, "no-such-pattern", catalog)),
            ("OGK-PROFILE-023", lambda: profile_edits._adopt(profile, "a-b-testing", catalog)),
            ("OGK-PROFILE-024", lambda: profile_edits._decline(profile, "account-health-review", catalog, "Sam", "No.")),
            ("OGK-PROFILE-025", words("a-b-testing", "python/x")),
            ("OGK-PROFILE-026", words(profile_edits.RULE_WORD)),
            ("OGK-PROFILE-027", lambda: profile_edits._approver_roles_setting("backend", {**roles, "paths": ["backend"]})),
            ("OGK-PROFILE-028", lambda: profile_edits._approver_roles_setting("design", {**roles,
                                                                                         "paths": ["design", "none"]})),
            ("OGK-PROFILE-029", lambda: profile_edits._approver_roles_setting("backend", {**roles,
                                                                                          "paths": ["backend", "Sam"]})),
            ("OGK-PROFILE-030", lambda: profile_edits._restricted_setting("none", {"paths": ["none", "docs"]})),
            ("OGK-PROFILE-031", lambda: profile_edits._light_paths_setting("none", {"paths": ["none", "docs"]})),
        ])


class TaskStateTests(CodedRefusals):
    """Issue #487: an action refused because of the task's status has its own code where no command reaches it."""

    def test_issue_487_a_refusal_of_the_task_status_has_its_code(self):
        task = {"id": "t1", "status": "consulting"}
        self.assertCodes([
            ("OGK-GUARD-017", lambda: guard_export.export_decision(Path("."), Path("."), task, {})),
            ("OGK-TASK-105", lambda: tasks_closing.record_result(task, {}, {})),
        ])


if __name__ == "__main__":
    unittest.main()
