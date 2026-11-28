"""Write the register of error codes, docs/agents/errors.json and docs/errors.md, from the code and the tests (#487).

    python scripts/build_errors.py [--check]

Each `OgkError("OGK-AREA-NNN", message)` of src/openguildkit, raised or returned, is one entry (and each error of a
class of CODED, which takes its code first): the code, the module, the function
that raises it, the message as written (a value computed at run time in braces) and the test files that cite the
code. The JSON file holds one entry per line, so `grep -n OGK-TASK-004 docs/agents/errors.json` prints a whole entry.

It names, and exits 1 on, a code raised from two places, a code no test cites and a code not written OGK-AREA-NNN.
--check writes nothing: it also names each file that differs and exits 1.
"""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - INTENTIONAL(#520): the one line an older Python gets
    raise SystemExit(f"OpenGuildKit needs Python 3.11 or later; this is Python {sys.version_info[0]}.{sys.version_info[1]}. "
                     "Run it with python3.11 or newer.")

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = Path("docs", "agents", "errors.json")
PAGE = Path("docs", "errors.md")
CODE = re.compile(r"OGK-[A-Z]+-\d{3}")


def _template(node: ast.expr) -> str:
    """The message as the code writes it: literal text, and each value computed at run time as {expression}."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "{" + ast.unparse(part.value)
                       + ("!" + chr(part.conversion) if part.conversion > 0 else "") + "}"
                       for part in node.values if isinstance(part, (ast.Constant, ast.FormattedValue)))
    return "{" + ast.unparse(node) + "}"


# The classes whose first argument is the code: OgkError and the errors of one area that derive from it.
CODED = ("OgkError", "NestedTooDeeply", "ExcludedPath", "SignerNotCurrent", "InvalidProfile", "Weakening", "EntryProblems", "RuleError", "TaskStateError", "CatalogError", "Refused")


def raise_sites(root: Path) -> list[dict]:
    """Every construction of a coded error, `OgkError(CODE, message)` or a class of CODED, raised or returned, in the
    order of the files and lines."""
    found = []
    for path in sorted((root / "src" / "openguildkit").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        calls = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in CODED and node.args), key=lambda node: (node.lineno, node.col_offset))
        for call in calls:
            code = call.args[0].value if isinstance(call.args[0], ast.Constant) else None
            owner = min((function for function in functions
                         if function.lineno <= call.lineno <= (function.end_lineno or function.lineno)),
                        key=lambda function: (function.end_lineno or 0) - function.lineno, default=None)
            found.append({"code": code, "module": path.relative_to(root).as_posix(),
                          "function": owner.name if owner else None, "line": call.lineno,
                          "message": _template(call.args[1]) if len(call.args) > 1 else ""})
    return found


def citing_tests(root: Path, codes: set[str]) -> dict[str, list[str]]:
    """For each code, the test files whose text cites it."""
    found: dict[str, list[str]] = {code: [] for code in codes}
    for path in sorted((root / "tests").rglob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for code in codes:
            if code in text:
                found[code].append(path.relative_to(root).as_posix())
    return found


def build(root: Path = ROOT) -> list[dict]:
    """One entry per code, ordered by code."""
    sites = raise_sites(root)
    tests = citing_tests(root, {site["code"] for site in sites if site["code"]})
    return sorted(({key: site[key] for key in ("code", "module", "function", "message")}
                   | {"tests": tests.get(site["code"], [])} for site in sites), key=lambda entry: str(entry["code"]))


def problems(sites: list[dict], entries: list[dict]) -> list[str]:
    """A code raised from two places, a code no test cites, and a code not written as OGK-AREA-NNN."""
    found = []
    for code in sorted({site["code"] for site in sites if isinstance(site["code"], str) and CODE.fullmatch(site["code"])}):
        places = [f"{site['module']}:{site['line']}" for site in sites if site["code"] == code]
        if len(places) > 1:
            found.append(f"{code} is raised from {len(places)} places: {', '.join(places)}")
        if not any(entry["tests"] for entry in entries if entry["code"] == code):
            found.append(f"{code}: no test cites it")
    found += [f"{site['module']}:{site['line']}: the code must be written as OGK-AREA-NNN" for site in sites
              if not (isinstance(site["code"], str) and CODE.fullmatch(site["code"]))]
    return found


def register_text(entries: list[dict]) -> str:
    lines = ",\n".join("  " + json.dumps(entry, ensure_ascii=False) for entry in entries)
    return "[\n" + lines + "\n]\n"


# What every --json output shares (#484).
JSON_OUTPUT = """
## JSON output

With `--json`, a command prints its answer as JSON on standard output.
With `OPENGUILDKIT_JSON_ENVELOPE=1` in the environment, every answer comes in one object, `{"schema_version": 1, "command": "task checks", "data": ...}`, whose `data` is the answer printed without the variable; the default keeps the shape scripts and the web interface read.
Under `--json`, an error is JSON on standard output too, with the same exit code and its line on standard error: `{"schema_version": 1, "error": {"code": "OGK-TASK-004", "message": ..., "next": ...}}`.
`code` is null for an error that has no code yet, and `next` is the command the message names, or null.
"""


def page_text(entries: list[dict]) -> str:
    by_module: dict[str, dict[str, list[str]]] = {}
    for entry in entries:
        functions = by_module.setdefault(entry["module"].rsplit("/", 1)[-1], {})
        functions.setdefault(str(entry["function"]), []).append(entry["code"])
    rows = "".join(f"\n### {module}\n\n" + "".join(f"- `{function}`: {', '.join(codes)}\n"
                                                  for function, codes in sorted(functions.items()))
                   for module, functions in sorted(by_module.items()))
    return ("# Error codes\n\n"
            "For: a person or an agent that reads an error of the CLI and looks for where it comes from.\n\n"
            "An error that carries a code starts with it: `OpenGuildKit [OGK-TASK-004]: Task already exists: x`, and "
            "under `--json` its object holds the same code in `error.code` ([JSON output](#json-output)).\n"
            "A code is raised from one place and keeps its meaning when its words change: search the code, not the "
            "sentence. `python scripts/build_errors.py` writes this page and [`agents/errors.json`](agents/errors.json) "
            "from the code; the other errors still print `OpenGuildKit: message`.\n"
            "The register holds the message of each code as the code writes it and the tests that cite it: "
            "`grep -n OGK-TASK-004 docs/agents/errors.json`. This page lists the codes by module and function.\n\n"
            "## Codes by module\n" + rows + JSON_OUTPUT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the register of error codes from the code and the tests.")
    parser.add_argument("--check", action="store_true", help="write nothing; name the files that differ and exit 1")
    args = parser.parse_args(argv)
    entries = build()
    found = problems(raise_sites(ROOT), entries)
    for line in found:
        print(f"build_errors: {line}")
    wanted = {REGISTER: register_text(entries), PAGE: page_text(entries)}
    differ = [path for path, text in wanted.items()
              if not (ROOT / path).is_file() or (ROOT / path).read_text(encoding="utf-8") != text]
    if args.check:
        for path in differ:
            print(f"build_errors: {path.as_posix()} differs: run python scripts/build_errors.py")
        return 1 if differ or found else 0
    for path in differ:
        (ROOT / path).write_text(wanted[path], encoding="utf-8")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
