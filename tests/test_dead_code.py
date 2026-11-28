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

# Names the resolved reads find unused whose removal is a change of src/ that the tooling branch of #511 leaves to
# the branch that owns those modules: drop each line with its name.
PENDING = {
    "src/openguildkit/patterns.py VERSION_PATTERN": "never read; catalog.VERSION_PATTERN hid it (#511).",
    "src/openguildkit/webui.py weakening_changes": "read by no module; profile_cli.weakening_changes hid it (#511).",
}


def module_of(path: Path) -> str:
    """The dotted name of a module of the package, or a name outside it for another file."""
    if PACKAGE in path.parents:
        parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
        return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
    return "outside." + path.stem


def import_target(module: str, node: ast.ImportFrom, is_package: bool) -> str:
    """The absolute module an import from names."""
    if not node.level:
        return node.module or ""
    base = module.split(".")
    base = base[:len(base) - node.level + (1 if is_package else 0)]
    return ".".join(base + ([node.module] if node.module else []))


def read_names(trees: dict[Path, ast.Module], modules: set[str]) -> Counter:
    """Each (module, name) of the package a file reads, resolved through its imports: a name is counted for the
    module that the read reaches, not for every module that defines the same identifier."""
    found = Counter()
    for path, tree in trees.items():
        module = module_of(path)
        names, whole = {}, {}  # local name -> (module, name); local name -> module
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = import_target(module, node, path.name == "__init__.py")
                for alias in node.names:
                    local = alias.asname or alias.name
                    if f"{target}.{alias.name}" in modules:
                        whole[local] = f"{target}.{alias.name}"
                    elif target in modules:
                        names[local] = (target, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        whole[alias.asname or alias.name] = alias.name
        own = {name: statement for statement in tree.body for name in defined_names(statement)} if module in modules else {}
        for statement in tree.body:
            defines = set(defined_names(statement)) if module in modules else set()
            loops = {}  # for module in (tools_cli, features_cli): module.add_parser(...) reads each module's add_parser.
            for node in ast.walk(statement):
                if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and isinstance(node.iter, ast.Tuple):
                    loops[node.target.id] = [whole[item.id] for item in node.iter.elts
                                             if isinstance(item, ast.Name) and item.id in whole]
            # _on_first_call("surfaces", name) for name in ("scan_report", ...): a module named by a string, and its
            # names as strings in the same statement.
            texts = {node.value for node in ast.walk(statement) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            for named in (f"openguildkit.{text}" for text in texts if f"openguildkit.{text}" in modules):
                for text in texts:
                    found[(named, text)] += 1
            for node in ast.walk(statement):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in loops:
                    for target in loops[node.value.id]:
                        found[(target, node.attr)] += 1
                if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
                    if node.id in names:
                        found[names[node.id]] += 1
                    elif node.id in own and node.id not in defines:  # A function that calls itself is not used by that call.
                        found[(module, node.id)] += 1
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in whole:
                    found[(whole[node.value.id], node.attr)] += 1
    return found


def reexports(trees: dict[Path, ast.Module], modules: set[str]) -> dict[tuple[str, str], tuple[str, str]]:
    """(module, name) a module of the package imports from another -> (that module, its name)."""
    found = {}
    for path, tree in trees.items():
        module = module_of(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = import_target(module, node, path.name == "__init__.py")
                if target in modules:
                    for alias in node.names:
                        found[(module, alias.asname or alias.name)] = (target, alias.name)
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


def unused_names(trees: dict[Path, ast.Module], others: dict[Path, ast.Module]) -> list[str]:
    """FILE:LINE NAME for each top-level name of the package modules in `trees` that no file of `trees` or `others`
    reads, once each read is resolved to the module it reaches."""
    modules = {module_of(path) for path in trees}
    reads = read_names({**trees, **others}, modules)
    imported = reexports(trees, modules)
    resolved = Counter()
    for key, count in reads.items():
        for _ in range(10):  # A name read through a module that imports it counts for the module that defines it.
            if key not in imported:
                break
            key = imported[key]
        resolved[key] += count
    scripts = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    for target in scripts.values():
        module, _, name = target.partition(":")
        resolved[(module, name)] += 1
    return [f"{path.relative_to(REPO).as_posix()}:{statement.lineno} {name}"
            for path, tree in trees.items() for statement in tree.body for name in defined_names(statement)
            if not resolved[(module_of(path), name)]]


class DeadCodeTests(unittest.TestCase):
    def unused(self) -> list[str]:
        others = {path: ast.parse(path.read_text(encoding="utf-8")) for folder in READERS if folder != "src"
                  for path in sorted((REPO / folder).rglob("*.py"))}
        return unused_names(package_modules(), others)

    def test_every_top_level_name_of_the_package_is_used_somewhere(self):
        unused, kept = [], set()
        for line in self.unused():
            name = line.rsplit(" ", 1)[1]
            if name in TESTED_ONLY or line.split(":")[0] + " " + name in PENDING:
                kept.add(name)
            else:
                unused.append(line)
        self.assertEqual(unused, [], "remove these names, call them, or give the reason to keep them in TESTED_ONLY")
        self.assertEqual(sorted(TESTED_ONLY.keys() - kept), [], "the package now uses these names: drop them from TESTED_ONLY")
        self.assertEqual(sorted(key for key in PENDING if key.rsplit(" ", 1)[1] not in kept), [],
                         "these names are gone or used: drop them from PENDING")

    def test_issue_511_a_name_is_used_only_where_a_read_reaches_it_not_by_a_namesake(self):
        """Issue #511: a read of profile_cli.weakening_changes counted for webui.weakening_changes, which nothing calls."""
        source = {
            "profile_cli.py": "def weakening_changes():\n    return []\n",
            "webui.py": "from . import profile_cli\n\n\ndef weakening_changes():\n    return profile_cli.weakening_changes()\n",
            "tasks_cli.py": "from .profile_cli import weakening_changes as changes\n\n\ndef run():\n    return changes()\n",
        }
        trees = {PACKAGE / name: ast.parse(text) for name, text in source.items()}
        self.assertEqual(unused_names(trees, {}), ["src/openguildkit/webui.py:4 weakening_changes",
                                                   "src/openguildkit/tasks_cli.py:4 run"])
        caller = ast.parse("from openguildkit import webui, tasks_cli\nwebui.weakening_changes()\ntasks_cli.run()\n")
        self.assertEqual(unused_names(trees, {REPO / "scripts" / "caller.py": caller}), [])

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
