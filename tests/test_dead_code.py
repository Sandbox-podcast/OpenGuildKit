"""The package keeps no code that nothing uses, and its modules use each other only through public names."""

import ast
import re
import tomllib
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "openguildkit"
# Where a name of the package may be used: the package, the maintainers' scripts, and the examples and integrations
# shipped with the repository. A name only the tests read is code nothing runs: it hides a check that never happens.
READERS = ("src", "scripts", "examples", "integrations")
# The names only the tests read, kept on purpose, and why.
TESTED_ONLY = {
    "LEGAL_BASIS": "relevance.py: the legal reason of each regulatory pack, a table for maintainers (docs/workflow.md); "
                   "its test checks that every regulatory pack has one.",
}


def used_names(tree: ast.AST) -> Counter:
    """Every name a piece of code reads: a variable, an attribute or an imported name."""
    found = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            found[node.id] += 1
        elif isinstance(node, ast.Attribute):
            found[node.attr] += 1
        elif isinstance(node, ast.alias):
            found[node.name.rpartition(".")[2]] += 1
    return found


def defined_names(statement: ast.stmt) -> list[str]:
    """The names a top-level statement of a module defines, dunder names aside."""
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names = [statement.name]
    elif isinstance(statement, ast.Assign):
        names = [node.id for target in statement.targets for node in ast.walk(target) if isinstance(node, ast.Name)]
    elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        names = [statement.target.id]
    else:
        names = []
    return [name for name in names if not (name.startswith("__") and name.endswith("__"))]


def package_modules() -> dict[Path, ast.Module]:
    return {path: ast.parse(path.read_text(encoding="utf-8")) for path in sorted(PACKAGE.rglob("*.py"))}


class DeadCodeTests(unittest.TestCase):
    def test_every_top_level_name_of_the_package_is_used_somewhere(self):
        uses = Counter()
        for folder in READERS:
            for path in (REPO / folder).rglob("*.py"):
                uses.update(used_names(ast.parse(path.read_text(encoding="utf-8"))))
        scripts = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
        uses.update(target.rpartition(":")[2] for target in scripts.values())
        unused, kept = [], set()
        for path, tree in package_modules().items():
            for statement in tree.body:
                inside = used_names(statement)  # A function that calls itself is not used by that call.
                for name in defined_names(statement):
                    if uses[name] - inside[name] > 0:
                        continue
                    if name in TESTED_ONLY:
                        kept.add(name)
                    else:
                        unused.append(f"{path.relative_to(REPO).as_posix()}:{statement.lineno} {name}")
        self.assertEqual(unused, [], "remove these names, call them, or give the reason to keep them in TESTED_ONLY")
        self.assertEqual(sorted(TESTED_ONLY.keys() - kept), [], "the package now uses these names: drop them from TESTED_ONLY")

    def test_no_module_imports_a_private_name_of_another(self):
        private = []
        for path, tree in package_modules().items():
            modules = set()  # The package's modules this one imports whole, as in "from . import cli".
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("openguildkit")):
                    private += [f"{path.relative_to(REPO).as_posix()}:{node.lineno} {alias.name}"
                                for alias in node.names if re.match(r"_[a-z]", alias.name)]
                    if node.level == 1 and node.module is None:
                        modules.update(alias.asname or alias.name for alias in node.names)
            private += [f"{path.relative_to(REPO).as_posix()}:{node.lineno} {node.value.id}.{node.attr}"
                        for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name) and node.value.id in modules and re.match(r"_[a-z]", node.attr)]
        self.assertEqual(private, [], "give these names a public name in their module, or keep them in it")


if __name__ == "__main__":
    unittest.main()
