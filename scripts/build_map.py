"""Write docs/agents/map.json from the code and the tests, keeping the fields a person writes.

    python scripts/build_map.py [--check]

A person writes the role, entry points, documentation page and `covers` of each module, the tests attached by
hand, and the `paths` entries: files and folders outside the package (scripts, web/src, integrations/ci/lib, the
documentation) with the tests and commands scripts/check_fast.py runs for them. The script adds what the code says:
an entry for each module of src/openguildkit (a new one gets an empty role to write), each test file that imports a
module directly, the tests that name each fixture of tests/, and the `commands` section, one entry per terminal
command with the function that runs it, its module and the line of that function, or of the branch that
handles the command inside a larger function. The tests of a command are those of its module. The file holds one entry per
line, so `grep -n '"src/openguildkit/results.py"' docs/agents/map.json` prints a whole entry.

--check writes nothing: it names each entry that differs from docs/agents/map.json and exits 1.
"""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - INTENTIONAL(#520): the one line an older Python gets
    raise SystemExit("OpenGuildKit needs Python 3.11 or later; this is Python %d.%d. Run it with python3.11 or newer."
                     % sys.version_info[:2])

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs" / "agents" / "map.json"
PACKAGE = ROOT / "src" / "openguildkit"
# Calls a command branch makes before the one that does its work: reading the profile, the answers or the catalog.
PREPARATION = {"load_profile", "read_json", "_setup_questions", "setup_profile", "complete_answers", "project_catalog",
               "load_references", "with_pattern_references", "profile_recommendations", "rule_plan"}


def test_files(root: Path) -> list[Path]:
    return sorted((root / "tests").rglob("test_*.py"))


def imported_modules(tree: ast.AST, modules: set[str]) -> set[str]:
    """The modules of the package (file names) a test file imports directly."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "openguildkit":
                    found.add(f"{parts[1]}.py" if len(parts) > 1 and f"{parts[1]}.py" in modules else "__init__.py")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] != "openguildkit":
                continue
            if len(parts) > 1:
                found.add(f"{parts[1]}.py" if f"{parts[1]}.py" in modules else "__init__.py")
            else:
                found.update(f"{alias.name}.py" if f"{alias.name}.py" in modules else "__init__.py"
                             for alias in node.names)
    return found & modules


def module_tests(root: Path, modules: set[str]) -> dict[str, set[str]]:
    """For each module file name, the test files that import it."""
    found: dict[str, set[str]] = {name: set() for name in modules}
    for path in test_files(root):
        for name in imported_modules(ast.parse(path.read_text(encoding="utf-8")), modules):
            found[name].add(path.relative_to(root).as_posix())
    return found


def fixture_entries(root: Path) -> list[dict]:
    """A path entry for each data file of tests/, with the test files that name it, or that name its folder."""
    texts = {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in test_files(root)}
    entries = []
    for path in sorted((root / "tests").rglob("*")):
        if not path.is_file() or path.suffix == ".py" or "__pycache__" in path.parts:
            continue
        names = (path.name, path.stem)
        tests = sorted(test for test, text in texts.items() if any(name in text for name in names))
        if not tests:
            folder = f'"{path.parent.name}"'
            tests = sorted(test for test, text in texts.items() if '"fixtures"' in text and folder in text)
        entries.append({"path": path.relative_to(root).as_posix(), "tests": tests, "generated": "fixture"})
    return entries


class Module:
    """The functions, imports and dictionaries of one module of the package."""

    def __init__(self, path: Path):
        self.path = path
        self.tree = ast.parse(path.read_text(encoding="utf-8"))
        self.functions = {node.name: node for node in self.tree.body if isinstance(node, ast.FunctionDef)}
        self.imports: dict[str, str] = {}  # local name -> module file name, or "module.py:function"
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                for alias in node.names:
                    local = alias.asname or alias.name
                    self.imports[local] = f"{alias.name}.py" if node.module is None else f"{node.module}.py:{alias.name}"

    def callee(self, call: ast.Call) -> tuple[str, str] | None:
        """(module file name, function) of a call to a function of the package, or None."""
        func = call.func
        if isinstance(func, ast.Name):
            if func.id in PREPARATION:
                return None
            if func.id in self.functions:
                return self.path.name, func.id
            target = self.imports.get(func.id, "")
            if ":" in target:
                name, _, function = target.partition(":")
                return name, function
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            target = self.imports.get(func.value.id, "")
            if target.endswith(".py") and ":" not in target:
                return target, func.attr
        return None

    def delegate(self, body: list[ast.stmt], word: str) -> tuple[str, str] | None:
        """The function a branch hands the command to, when its first statement only calls it."""
        value = body[0].value if isinstance(body[0], (ast.Return, ast.Expr)) else None
        if isinstance(value, ast.IfExp):
            value = value.body if _compares_to(value.test, word) else value.orelse
        if isinstance(value, ast.Lambda):
            value = value.body
        return self.callee(value) if isinstance(value, ast.Call) else None

    def branch(self, function: str, word: str, depth: int = 1) -> tuple[str, str, int] | None:
        """Where `function` handles `word`: (module, function, line) of the function its branch hands the command to,
        or of the branch itself. Looks in a module-level dictionary of actions too, and in the functions of this module
        that `function` calls."""
        node = self.functions.get(function)
        if node is None:
            return None
        for statement in ast.walk(node):
            if isinstance(statement, ast.If) and _compares_to(statement.test, word):
                found = self.delegate(statement.body, word)
                return (*found, 0) if found else (self.path.name, function, statement.lineno)
        for statement in self.tree.body:
            if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Dict):
                for key, value in zip(statement.value.keys, statement.value.values):
                    if isinstance(key, ast.Constant) and key.value == word:
                        found = self.delegate([ast.Expr(value)], word) if isinstance(value, ast.Lambda) else (
                            (self.path.name, value.id) if isinstance(value, ast.Name) and value.id in self.functions
                            else None)
                        if found:
                            return (*found, 0)
        for call in (item for item in ast.walk(node) if isinstance(item, ast.Call) and depth):
            if isinstance(call.func, ast.Name) and call.func.id in self.functions and call.func.id != function:
                found = self.branch(call.func.id, word, depth - 1)
                if found:
                    return found
        return None


def _compares_to(test: ast.expr, word: str) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    right = test.comparators[0]
    if isinstance(test.ops[0], ast.Eq):
        return isinstance(right, ast.Constant) and right.value == word
    if isinstance(test.ops[0], ast.In) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
        return any(isinstance(item, ast.Constant) and item.value == word for item in right.elts)
    return False


def terminal_commands() -> list[list[str]]:
    """Each terminal command of the CLI, as its words, in the order of the parser."""
    sys.path.insert(0, str(ROOT / "src"))
    from openguildkit.cli import command_parser

    def walk(parser: argparse.ArgumentParser, words: list[str]):
        actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
        if not actions:
            yield words
        for action in actions:
            seen = set()
            for name, child in action.choices.items():
                if id(child) not in seen:
                    seen.add(id(child))
                    yield from walk(child, [*words, name])

    return list(walk(command_parser(), []))


def command_entries(root: Path) -> list[dict]:
    modules: dict[str, Module] = {}

    def module(name: str) -> Module:
        if name not in modules:
            modules[name] = Module(PACKAGE / name)
        return modules[name]

    entries = []
    for words in terminal_commands():
        cli = module("cli.py")
        found = cli.branch("_run", words[0], 0) or cli.branch("_project_command", words[0], 0)
        if found and len(words) > 1:
            found = module(found[0]).branch(found[1], words[1]) or found
        if found is None:
            entries.append({"command": " ".join(words), "function": None, "module": None, "line": None})
            continue
        name, function, line = found
        entries.append({"command": " ".join(words), "function": function, "module": f"src/openguildkit/{name}",
                        "line": line or module(name).functions[function].lineno})
    return entries


def build(current: dict, root: Path = ROOT) -> dict:
    """The map: the hand-written fields of `current`, completed from the code and the tests."""
    names = sorted(path.name for path in (root / "src" / "openguildkit").glob("*.py"))
    importers = module_tests(root, set(names))
    by_module = {item["module"]: item for item in current.get("modules", [])}
    modules = []
    for name in names:
        path = f"src/openguildkit/{name}"
        item = dict(by_module.get(path) or {"module": path, "role": "", "entry": [], "tests": [], "doc": "docs/architecture.md"})
        kept = {test for test in item.get("tests", []) if (root / test).is_file()}  # A removed test file leaves.
        item["tests"] = sorted(kept | importers[name])
        modules.append(item)
    paths = [{**item, "tests": [test for test in item["tests"] if (root / test).is_file()]}
             for item in current.get("paths", []) if item.get("generated") != "fixture"]
    paths = sorted([*paths, *fixture_entries(root)], key=lambda item: item["path"])
    return {"modules": modules, "paths": paths, "commands": command_entries(root)}


def dumps(module_map: dict) -> str:
    """One entry per line."""
    sections = []
    for key in ("modules", "paths", "commands"):
        lines = ",\n".join("    " + json.dumps(item, ensure_ascii=False) for item in module_map.get(key, []))
        sections.append(f'  "{key}": [\n{lines}\n  ]')
    return "{\n" + ",\n".join(sections) + "\n}\n"


def differences(current: dict, built: dict) -> list[str]:
    """The entries of the built map that the current one lacks or holds otherwise, by name."""
    found = []
    for key, name in (("modules", "module"), ("paths", "path"), ("commands", "command")):
        old = {item[name]: item for item in current.get(key, [])}
        new = {item[name]: item for item in built.get(key, [])}
        for entry in sorted(old.keys() | new.keys()):
            if entry not in new:
                found.append(f"{key}: {entry} is no longer there")
            elif entry not in old:
                found.append(f"{key}: {entry} is missing")
            elif old[entry] != new[entry]:
                changed = sorted(field for field in old[entry].keys() | new[entry].keys()
                                 if old[entry].get(field) != new[entry].get(field))
                found.append(f"{key}: {entry} differs in {', '.join(changed)}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write docs/agents/map.json from the code and the tests.")
    parser.add_argument("--check", action="store_true", help="write nothing; name the entries that differ and exit 1")
    args = parser.parse_args(argv)
    text = MAP.read_text(encoding="utf-8")
    current = json.loads(text)
    built = build(current)
    if args.check:
        found = differences(current, built)
        if not found and dumps(built) != text:
            found = ["the layout differs: one entry per line"]
        for line in found:
            print(f"build_map: {line}")
        if found:
            print("build_map: run python scripts/build_map.py and review the diff of docs/agents/map.json.")
        return 1 if found else 0
    MAP.write_text(dumps(built), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
