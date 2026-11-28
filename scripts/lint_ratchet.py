"""Count what ruff and mypy find, per rule, and fail when a count goes above scripts/lint-baseline.json.

    python scripts/lint_ratchet.py [--update] [--baseline FILE]

The two tools run with the settings of pyproject.toml, at the versions pinned in its [tool.lint_ratchet]
table: this Python's own (pip install ruff==X mypy==Y), else `uvx tool@X`. A count may go down and never
up; a rule the baseline does not list starts at zero. A module of src/ that [tool.lint_ratchet] does not
list in mypy_excluded must have no mypy error at all. `--update` writes the lower counts, refuses to write
when one is higher, and creates the file when there is none. Raising a count is a hand edit of the file,
which a review sees. Exit 0 when the counts hold, 1 when one is above its baseline, 2 when a tool or the
baseline cannot be read.
"""

import argparse
import json
import os
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "lint-baseline.json"
TOOLS = ("mypy", "ruff")


class ToolError(Exception):
    """A tool or the baseline cannot be used: the run stops with exit code 2."""


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False, **kwargs)


def read_config(pyproject: Path = ROOT / "pyproject.toml") -> dict:
    """The [tool.lint_ratchet] table: the two pinned versions and the modules mypy still fails on."""
    table = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"]["lint_ratchet"]
    return {"ruff": table["ruff"], "mypy": table["mypy"], "mypy_excluded": list(table["mypy_excluded"])}


def parse_ruff(text: str) -> Counter:
    """Ruff's JSON report to a count per rule; a syntax error has no rule."""
    return Counter(item["code"] or "syntax-error" for item in json.loads(text))


def parse_mypy(text: str) -> list[tuple[str, str]]:
    """Mypy's JSON lines to (file, error code) for each error; notes are left out."""
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [(row["file"], row["code"] or "syntax") for row in rows if row["severity"] == "error"]


def launcher(tool: str, pin: str) -> list[str]:
    """The command that starts the pinned version of a tool: this Python's own, else uvx."""
    found = []
    for command in ([sys.executable, "-m", tool], ["uvx", f"{tool}@{pin}"]):
        try:
            words = run([*command, "--version"]).stdout.split()
        except OSError:
            continue
        version = words[1] if len(words) > 1 else ""
        if version == pin:
            return command
        if version:
            found.append(version)
    seen = f" (found {', '.join(found)})" if found else ""
    raise ToolError(f"{tool} {pin} is not available{seen}: python -m pip install {tool}=={pin}, or install uv.")


def _output(tool: str, command: list[str]) -> str:
    result = run(command, cwd=ROOT)
    if result.returncode not in (0, 1):
        raise ToolError(f"{tool} failed with exit code {result.returncode}: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def measure(config: dict | None = None) -> dict:
    """Counts per tool and rule, and the mypy errors in modules that must be clean."""
    config = config or read_config()
    ruff = launcher("ruff", config["ruff"])
    mypy = launcher("mypy", config["mypy"])
    ruff_counts = parse_ruff(_output("ruff", [*ruff, "check", "--no-cache", "--output-format", "json", "--exit-zero"]))
    errors = parse_mypy(_output("mypy", [*mypy, "--output", "json", "--cache-dir", os.devnull]))
    stray = sorted({path for path, _ in errors if path not in config["mypy_excluded"]})
    return {"counts": {"ruff": dict(ruff_counts), "mypy": dict(Counter(code for _, code in errors))}, "stray": stray}


def read_baseline(path: Path) -> dict | None:
    """The committed counts, None when there is no file; ToolError when it is not counts per rule."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        valid = isinstance(data, dict) and set(data) <= set(TOOLS) and all(
            isinstance(counts, dict) and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0
                                             for n in counts.values()) for counts in data.values())
    except ValueError:
        valid = False
    if not valid:
        raise ToolError(f"{path}: the baseline must be an object of counts per rule for ruff and mypy.")
    return data


def rises(baseline: dict, counts: dict) -> list[str]:
    """One line for each rule whose count is above the baseline."""
    return [f"{tool} {rule}: {n} > {baseline.get(tool, {}).get(rule, 0)}"
            for tool in TOOLS for rule, n in sorted(counts[tool].items())
            if n > baseline.get(tool, {}).get(rule, 0)]


def nonzero(counts: dict) -> dict:
    return {tool: {rule: n for rule, n in sorted(counts.get(tool, {}).items()) if n} for tool in TOOLS}


def main(argv: list[str] | None = None, measure=measure) -> int:
    parser = argparse.ArgumentParser(description="Fail when a ruff or mypy count goes above the baseline.")
    parser.add_argument("--update", action="store_true", help="write the counts when none is higher")
    parser.add_argument("--baseline", type=Path, default=BASELINE, help="the counts file (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        return check(args, measure)
    except ToolError as error:
        print(error, file=sys.stderr)
        return 2


def check(args: argparse.Namespace, measure) -> int:
    baseline = read_baseline(args.baseline)
    if baseline is None and not args.update:
        raise ToolError(f"{args.baseline} does not exist: python scripts/lint_ratchet.py --update creates it.")
    found = measure()
    counts = found["counts"]
    problems = rises(baseline, counts) if baseline is not None else []
    problems += [f"mypy: errors in {path}, which is not in mypy_excluded of pyproject.toml: fix them"
                 for path in found["stray"]]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print("Fix the new findings (run the tool on the files you changed); the baseline never goes up.",
              file=sys.stderr)
        return 1
    hint = ""
    if args.update:
        args.baseline.write_text(json.dumps(nonzero(counts), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif nonzero(counts) != nonzero(baseline):
        hint = " Lower than the baseline: python scripts/lint_ratchet.py --update keeps the gain."
    total = {tool: sum(counts[tool].values()) for tool in TOOLS}
    print(f"Lint ratchet holds: ruff {total['ruff']}, mypy {total['mypy']}.{hint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
