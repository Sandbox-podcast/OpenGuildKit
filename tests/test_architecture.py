"""The package keeps modules a reader can hold in mind, and one way to wire a command."""

import ast
import inspect
import unittest
from pathlib import Path

from openguildkit import alerts_cli, market_cli, profile_cli, storybook_cli, tasks_cli, tools_cli, trace_cli

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "openguildkit"
MAX_MODULE_LINES = 2000
MAX_CLI_LINES = 1500
MAX_CLI_FUNCTION_LINES = 120


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
        allowed = {"args", "root", "state", "profile", "catalog"}
        for module in (alerts_cli, market_cli, profile_cli, storybook_cli, tasks_cli, tools_cli, trace_cli):
            with self.subTest(module=module.__name__):
                self.assertEqual(list(inspect.signature(module.add_parser).parameters), ["commands"])
                parameters = list(inspect.signature(module.run).parameters)
                self.assertEqual(parameters[0], "args")
                self.assertLessEqual(set(parameters), allowed)
        self.assertNotIn("cli", imported_modules(parsed(PACKAGE / "profile_cli.py"), top_level=True))

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
