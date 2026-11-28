"""The package keeps modules a reader can hold in mind, and one way to wire a command."""

import ast
import inspect
import json
import math
import subprocess
import unittest
from pathlib import Path

from openguildkit import (
    alerts_cli,
    market_cli,
    profile_cli,
    projects_cli,
    storybook_cli,
    tasks_cli,
    tools_cli,
    trace_cli,
)

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "openguildkit"
# Issue #486: the code of the repository in files a reader can open whole. A file above MAX_FILE_BYTES is listed in
# tests/byte_budget.json with its size rounded up to the thousand as its ceiling, which only goes down.
MAX_FILE_BYTES = 40_000
BUDGETED = ("src", "tests", "scripts", "web/src", "integrations/ci/lib")
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".mjs", ".js", ".css")
BYTE_BUDGET = REPO / "tests" / "byte_budget.json"
MAX_CLI_LINES = 1500
MAX_CLI_FUNCTION_LINES = 120
# Top-level function names that more than one module of the package defines (#530): a name searched from its
# command should lead to one function. Lower the ceiling when a copy goes; never raise it.
MAX_SHARED_FUNCTION_NAMES = 64
# Issue #508: a function a reader can hold in mind, measured as scripts of the audit measure it. Length is its lines,
# complexity counts one plus each branch (BRANCH, and each extra operand of and/or), nesting the deepest block of NEST
# (an elif does not nest); a nested function, class or lambda counts for itself, not for its parent.
MAX_FUNCTION_LINES = 80
MAX_COMPLEXITY = 25
MAX_NESTING = 4
BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert, ast.comprehension,
          ast.match_case)
NEST = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)
OWN_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
# The functions still above a threshold, with why. The list only shrinks: bring a function under every threshold
# and remove its line; a new function above one fails, and so does a line whose function is now under them all.
SHAPE_EXCEPTIONS = {
    "cli.py:command_parser": "120 lines: the parser of every command, one add_parser call after another (#508)",
    "project_setup.py:init_questions": "88 lines: the questions of init as one list of literals (#508)",
    "catalog.py:_validate_pattern": "cc 32: checks each field of a catalog pattern in turn",
    "code_lookup.py:code_lookup": "cc 26: the file and function names a bug brief cites, each searched",
    "consultation.py:scope_lines": "cc 27: one optional line per field of the scope",
    "detect.py:_parse": "cc 28: one branch per manifest format",
    "detect.py:detect_stack": "cc 29: one branch per detected technology",
    "detect_gradle.py:gradle_components": "cc 33: one pattern per form a Gradle build declares a version in",
    "guard.py:guard_hook": "cc 31: the hook's decision for each host payload and guard mode",
    "guard_export.py:record_shape": "cc 29: checks each field of an exported record in turn",
    "mcp_mock.py:validate_mock": "cc 28: checks each part of a mock definition in turn",
    "patterns.py:recommend_patterns": "cc 26: scores each pattern against the stack and the answers",
    "profile_changes.py:export_answers": "cc 27: one answer per profile field",
    "projects_cli.py:_print": "cc 29: the table of projects with each optional column",
    "questionnaire.py:validate_answers": "cc 26: checks each answer by its question type",
    "result_form.py:_check_entry": "cc 33: checks each field of a check outcome in turn",
    "results.py:completion_problems": "cc 26: each condition task complete refuses",
    "routing.py:scan_triggers": "cc 34: the trigger and exclusion passages of each board",
    "routing.py:select_boards": "cc 34: each reason a board is selected or left out",
    "surface_servers.py:configured_server": "cc 31: each finding about a configured MCP server",
    "tasks.py:list_tasks": "cc 35: reads, judges and filters each task with the status index",
    "tasks_blockers.py:resolve_blocker": "cc 32: checks a clearing or a waiver of a blocker in turn",
    "tasks_consult_cli.py:_print_route": "cc 31: each part of the printed route",
    "tasks_decide_cli.py:run_decide": "cc 30: each option of task decide",
    "workflow.py:challenge_report": "cc 26: each line of the challenge report",
    "workflow.py:validate_deliberation": "cc 29: checks each field of a deliberation in turn",
}
# The public names several modules define: the entry points every command module has, and the homonyms #530 lists
# that are not merged yet. A public name added to two modules fails.
SHARED_PUBLIC_NAMES = {
    "add_parser", "run", "main", "add_options", "serve", "describe", "parse", "fingerprint", "timestamp",
    "approval_problem", "board_brief", "changed_files", "frozen_text", "open_points", "scope_entry",
}


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def imported_modules(tree: ast.Module, top_level: bool) -> set[str]:
    """The modules of the package a module imports, at its top or inside its functions."""
    found = set()
    statements = tree.body if top_level else [node for function in ast.walk(tree)
                                               if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                                               for node in ast.walk(function)]
    for node in statements:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            found.update([node.module] if node.module else [alias.name for alias in node.names])
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("openguildkit"):
            found.add(node.module.removeprefix("openguildkit").lstrip(".") or "openguildkit")
    return found


def code_sizes() -> dict[str, int]:
    """The size in bytes of each tracked code file of BUDGETED, as committed: without the carriage returns of a
    Windows checkout."""
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", *BUDGETED], capture_output=True, check=True)
    names = [name for name in listed.stdout.decode("utf-8").split("\0") if name.endswith(CODE_SUFFIXES)]
    return {name: len((REPO / name).read_bytes().replace(b"\r\n", b"\n")) for name in names if (REPO / name).is_file()}


def own_nodes(function: ast.AST):
    """The nodes of a function, without those of the functions, classes and lambdas it defines."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, OWN_SCOPE):
            stack.extend(ast.iter_child_nodes(node))


def complexity(function: ast.AST) -> int:
    return 1 + sum(1 if isinstance(node, BRANCH) else len(node.values) - 1 if isinstance(node, ast.BoolOp) else 0
                   for node in own_nodes(function))


def nesting(node: ast.AST, level: int = 0) -> int:
    best = level
    for child in ast.iter_child_nodes(node):
        if isinstance(child, OWN_SCOPE):
            continue
        if isinstance(child, ast.If) and isinstance(node, ast.If) and child in node.orelse and len(node.orelse) == 1:
            best = max(best, nesting(child, level))  # elif does not nest
        else:
            best = max(best, nesting(child, level + isinstance(child, NEST)))
    return best


def functions(node: ast.AST, prefix: str = ""):
    """Every function of a module by qualified name (Class.method, outer.inner), nested ones included."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield f"{prefix}{child.name}", child
            yield from functions(child, f"{prefix}{child.name}.")
        elif isinstance(child, ast.ClassDef):
            yield from functions(child, f"{prefix}{child.name}.")
        else:
            yield from functions(child, prefix)


class ModuleShapeTests(unittest.TestCase):
    def test_issue_486_no_code_file_passes_its_byte_budget(self):
        """Issue #486: the only guard counted lines, and 16 modules passed 40 KB, tasks_cli.py at 94,758 bytes."""
        budget = json.loads(BYTE_BUDGET.read_text(encoding="utf-8"))
        over = {name: size for name, size in code_sizes().items() if size > budget.get(name, MAX_FILE_BYTES)}
        self.assertEqual(over, {}, f"split these files below {MAX_FILE_BYTES:,} bytes, or below their ceiling in "
                                   f"{BYTE_BUDGET.name}")

    def test_issue_486_a_ceiling_of_the_byte_budget_only_goes_down(self):
        """Issue #486: a listed file keeps the ceiling of its size rounded up to the thousand, and leaves the list
        once below MAX_FILE_BYTES, so that the ceiling cannot be raised without failing here."""
        sizes = code_sizes()
        for name, ceiling in json.loads(BYTE_BUDGET.read_text(encoding="utf-8")).items():
            with self.subTest(file=name):
                self.assertIn(name, sizes, "remove it from the budget: the file is gone")
                self.assertGreater(sizes[name], MAX_FILE_BYTES, "remove it from the budget: it fits the default")
                self.assertEqual(ceiling, math.ceil(sizes[name] / 1000) * 1000, f"{name} holds {sizes[name]:,} bytes")

    def test_the_cli_stays_short_and_so_do_its_functions(self):
        text = (PACKAGE / "cli.py").read_text(encoding="utf-8")
        self.assertLess(len(text.splitlines()), MAX_CLI_LINES)

    def test_no_function_of_the_cli_or_of_a_command_module_passes_120_lines(self):
        paths = [PACKAGE / "cli.py", *sorted(PACKAGE.glob("*_cli.py"))]
        self.assertGreaterEqual(len(paths), 7)
        for path in paths:
            with self.subTest(module=path.name):
                long = {node.name: node.end_lineno - node.lineno + 1 for node in ast.walk(parsed(path))
                        if isinstance(node, ast.FunctionDef)
                        and node.end_lineno - node.lineno + 1 > MAX_CLI_FUNCTION_LINES}
                self.assertEqual(long, {})

    def test_each_command_module_adds_its_parser_and_runs_without_functions_of_the_cli(self):
        # The same pair everywhere: add_parser(commands), then run(args, ...) with paths and loaded records only.
        for module in (alerts_cli, market_cli, profile_cli, projects_cli, storybook_cli, tasks_cli, tools_cli, trace_cli):
            with self.subTest(module=module.__name__):
                self.assertEqual(list(inspect.signature(module.add_parser).parameters), ["commands"])
        self.assertNotIn("cli", imported_modules(parsed(PACKAGE / "profile_cli.py"), top_level=True))

    def test_no_module_of_the_task_path_passes_500_lines_and_each_action_takes_one_argument(self):
        """Issue #506: tasks.py and tasks_cli.py held the whole task path in 3,235 lines; issue #507: the 25 actions
        took six parameters each, 52 of which they never read."""
        long = {path.name: count for path in PACKAGE.glob("tasks*.py")
                if (count := len(path.read_text(encoding="utf-8").splitlines())) > 500}
        self.assertEqual(long, {})
        for action, handler in tasks_cli.HANDLERS.items():
            with self.subTest(action=action):
                self.assertEqual(list(inspect.signature(handler).parameters), ["command"])

    def test_issue_462_every_command_runs_through_one_table_and_one_signature(self):
        """Issue #462: six signatures of run for ten command modules, a chain of 37 tests on args.command, and 22
        functions bound by their name in a string."""
        from importlib import import_module

        from openguildkit.cli import COMMANDS, command_parser
        from openguildkit.command import NEEDS

        parser_commands = set(command_parser()._subparsers._group_actions[0].choices)
        self.assertEqual(set(COMMANDS), parser_commands)
        for name, (module, needs) in sorted(COMMANDS.items()):
            with self.subTest(command=name):
                self.assertIn(needs, NEEDS)
                run = import_module(f"openguildkit.{module}").run
                self.assertEqual(list(inspect.signature(run).parameters), ["command"])
        text = (PACKAGE / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("_on_first_call", text)
        self.assertEqual(text.count("args.command =="), 1)  # The exit code 2 of ci-check, in _failed (#484).
        for path in [PACKAGE / "cli.py", *(PACKAGE / f"{module}.py" for module in ("init_cli", "catalog_cli",
                                                                                  "check_cli", "docs_cli"))]:
            with self.subTest(module=path.name):
                self.assertLess(len(path.read_text(encoding="utf-8").splitlines()), 400)

    def test_issue_509_only_the_cli_and_its_command_modules_import_a_command_module(self):
        """Issue #509: the profile's security rule lived in profile_cli, which webui, retro and features_cli imported,
        and projects_cli read the output of check back from the standard error."""
        command_modules = {path.stem for path in PACKAGE.glob("*_cli.py")} | {"cli"}
        wrong = {}
        for path in sorted(PACKAGE.glob("*.py")):
            if path.stem in command_modules or path.name == "__main__.py":
                continue
            tree = parsed(path)
            found = (imported_modules(tree, True) | imported_modules(tree, False)) & command_modules
            if path.name == "webui.py":
                found -= {"cli"}  # The page runs each command through cli.main.
            if found:
                wrong[path.name] = sorted(found)
        self.assertEqual(wrong, {})
        projects = (PACKAGE / "projects_cli.py").read_text(encoding="utf-8")
        self.assertNotIn("cli.main", projects)
        self.assertNotIn("redirect_stderr", projects)

    def test_issue_502_each_module_names_its_entry_points_and_its_tests_in_its_header(self):
        """Issue #502: the module headers named no test file and the entry points of 3 modules of 65; the map, written
        by hand, missed 51 tests that import a module."""
        from tests.support import load_script

        header = load_script(REPO / "scripts" / "build_map.py").header
        for path in sorted(PACKAGE.glob("*.py")):
            with self.subTest(module=path.name):
                entry, tests = header(path)
                tree = parsed(path)
                defined = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
                defined |= {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                            if isinstance(target, ast.Name)}
                self.assertTrue(entry, "an Entry: line in the docstring")
                self.assertTrue(tests, "a Tests: line in the docstring")
                self.assertEqual([name for name in entry if name not in defined | {"module"}], [])
                self.assertEqual([test for test in tests if not (REPO / test).is_file()], [])

    def test_issue_530_each_task_action_runs_in_the_function_named_after_it(self):
        """Issue #530: task verify, result and complete ran in _outcome, clear and waive in _resolve, submit in _pass:
        a search for the action's name found no function."""
        for action, handler in tasks_cli.HANDLERS.items():
            with self.subTest(action=action):
                self.assertEqual(handler.__name__, "run_" + action.replace("-", "_"))

    def test_issue_530_a_function_name_leads_to_one_function(self):
        """Issue #530: 68 function names were defined in several modules, with different contracts (_git five
        times), so a search by name found the wrong one."""
        modules: dict[str, set[str]] = {}
        for path in PACKAGE.glob("*.py"):
            for node in parsed(path).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    modules.setdefault(node.name, set()).add(path.name)
        shared = {name for name, found in modules.items() if len(found) > 1}
        self.assertLessEqual(len(shared), MAX_SHARED_FUNCTION_NAMES, sorted(shared))
        self.assertEqual(sorted(name for name in shared if not name.startswith("_") and name not in SHARED_PUBLIC_NAMES), [])

    def test_issue_508_no_function_passes_the_size_complexity_and_nesting_thresholds(self):
        """Issue #508: 13 functions passed 80 lines, 52 a complexity of 25 and 9 a nesting of 4 (ci_guard: 137 lines,
        complexity 65), so a reader could not hold one in mind to find the line a symptom comes from."""
        over = {}
        for path in sorted(PACKAGE.glob("*.py")):
            for name, function in functions(parsed(path)):
                key = f"{path.name}:{name}"
                shape = (function.end_lineno - function.lineno + 1, complexity(function), nesting(function))
                if shape[0] > MAX_FUNCTION_LINES or shape[1] > MAX_COMPLEXITY or shape[2] > MAX_NESTING:
                    over[key] = "lines {}, complexity {}, nesting {}".format(*shape)
        self.assertEqual({key: shape for key, shape in over.items() if key not in SHAPE_EXCEPTIONS}, {},
                         "split these functions under the thresholds")
        self.assertEqual(sorted(key for key in SHAPE_EXCEPTIONS if key not in over), [],
                         "under every threshold now, or gone: remove these lines from SHAPE_EXCEPTIONS")

    def test_routing_the_questionnaire_and_the_agent_text_live_apart_from_the_workflow(self):
        # Routing changes with each catalog edition: its module and its table of cases do without the workflow.
        self.assertIn("routing", imported_modules(parsed(PACKAGE / "workflow.py"), top_level=True))
        for path in (PACKAGE / "project.py", PACKAGE / "routing.py", REPO / "tests" / "test_routing.py"):
            with self.subTest(path=path.name):
                tree = parsed(path)
                self.assertNotIn("workflow", imported_modules(tree, True) | imported_modules(tree, False))

    def test_the_source_analyzer_of_storybook_extract_has_its_own_module(self):
        defined = {node.name for node in parsed(PACKAGE / "storybook.py").body if isinstance(node, ast.FunctionDef)}
        analyzer = {node.name for node in parsed(PACKAGE / "storybook_extract.py").body
                    if isinstance(node, ast.FunctionDef)}
        self.assertLessEqual({"extract", "_scan_components", "_scan_styles", "_strip_js_comments"}, analyzer)
        self.assertEqual(defined & analyzer, set())

    def test_the_web_server_imports_the_cli_at_its_top_only(self):
        tree = parsed(PACKAGE / "webui.py")
        self.assertIn("cli", imported_modules(tree, top_level=True))
        self.assertNotIn("cli", imported_modules(tree, top_level=False))


if __name__ == "__main__":
    unittest.main()
