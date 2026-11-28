"""The package keeps modules a reader can hold in mind, and one way to wire a command."""

import ast
import inspect
import unittest
from pathlib import Path

from openguildkit import (
    alerts_cli, market_cli, profile_cli, projects_cli, storybook_cli, tasks_cli, tools_cli, trace_cli,
)

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "openguildkit"
MAX_MODULE_LINES = 2000
MAX_CLI_LINES = 1500
MAX_CLI_FUNCTION_LINES = 120
# Top-level function names that more than one module of the package defines (#530): a name searched from its
# command should lead to one function. Lower the ceiling when a copy goes; never raise it.
MAX_SHARED_FUNCTION_NAMES = 75
# The public names several modules define: the entry points every command module has, and the homonyms #530 lists
# that are not merged yet. A public name added to two modules fails.
SHARED_PUBLIC_NAMES = {
    "add_parser", "run", "main", "add_options", "serve", "describe", "parse", "fingerprint", "timestamp",
    "approval_problem", "board_brief", "changed_files", "frozen_text", "open_points", "record_digest", "scope_entry",
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


class ModuleShapeTests(unittest.TestCase):
    def test_no_module_of_the_package_passes_two_thousand_lines(self):
        long = {path.name: count for path in PACKAGE.glob("*.py")
                if (count := len(path.read_text(encoding="utf-8").splitlines())) > MAX_MODULE_LINES}
        self.assertEqual(long, {})

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
                if module != "tasks_cli":  # Left to the split of tasks_cli, which is under way apart.
                    run = import_module(f"openguildkit.{module}").run
                    self.assertEqual(list(inspect.signature(run).parameters), ["command"])
        text = (PACKAGE / "cli.py").read_text(encoding="utf-8")
        self.assertNotIn("_on_first_call", text)
        self.assertEqual(text.count("args.command =="), 2)  # The exit code 2 of ci-check, in main.
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
