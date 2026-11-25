"""Run the tests the module map attaches to files changed since a base revision.

    python scripts/check_fast.py [--base REF]

REF defaults to origin/main. Changed files are the tracked diff against that
revision, working tree included, plus untracked files. Tests come from
docs/agents/map.json. A changed test file runs itself. A change under
src/openguildkit/registry/ validates the catalog. A change under web/ runs
npm run typecheck. A changed file with no attached test is named, and the
command exits non-zero. Success is one line.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs" / "agents" / "map.json"
# Files this repository checks outside the module map.
EXTRA = {
    "scripts/check_fast.py": "tests/test_agent_native.py",
    "scripts/agent_cost.py": "tests/test_agent_native.py",
    "docs/agents/map.json": "tests/test_agent_native.py",
    "docs/testing.md": "tests/test_product_docs.py",
    "CONTRIBUTING.md": "tests/test_workflows.py",
}


def plan(changed: list[str], module_map: dict) -> dict:
    """The tests and commands a set of changed paths needs, and the paths no test covers."""
    by_path = {item["module"]: item for item in module_map["modules"]}
    tests, commands, unattached = [], [], []

    def add_tests(paths: list[str]) -> bool:
        available = [path for path in paths if (ROOT / path).is_file()]
        for path in available:
            if path not in tests:
                tests.append(path)
        return bool(available)

    for path in changed:
        name = path.rsplit("/", 1)[-1]
        if path.startswith("tests/") and path.endswith(".py") and name.startswith("test_"):
            if (ROOT / path).is_file():
                add_tests([path])
            continue
        item = by_path.get(path)
        if item:
            if not add_tests(item["tests"]):
                unattached.append(path)
            continue
        covered = False
        for entry in module_map["modules"]:
            if any(path.startswith(prefix) for prefix in entry.get("covers", [])):
                covered = add_tests(entry["tests"]) or covered
        if covered:
            continue
        if path.startswith("src/openguildkit/registry/"):
            if "catalog" not in commands:
                commands.append("catalog")
            continue
        if path.startswith("web/"):
            if "web-typecheck" not in commands:
                commands.append("web-typecheck")
            continue
        extra = EXTRA.get(path)
        if extra and add_tests([extra]):
            continue
        unattached.append(path)
    return {"tests": tests, "commands": commands, "unattached": unattached}


def _git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "git failed")
    return [line for line in result.stdout.splitlines() if line]


def changed_files(root: Path, base: str) -> list[str]:
    """Tracked changes since base, including the working tree, and untracked files."""
    tracked = _git_lines(root, "diff", "--name-only", "--no-renames", base)
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard")
    found = []
    for path in [*tracked, *untracked]:
        if path not in found:
            found.append(path)
    return found


def _module_name(path: str) -> str:
    return path[:-3].replace("/", ".")


def _run(command: list[str], cwd: Path) -> int:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the tests attached to files changed since a base revision.")
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    module_map = json.loads(MAP.read_text(encoding="utf-8"))
    changed = changed_files(ROOT, args.base)
    if not changed:
        print(f"check_fast: no changes since {args.base}.")
        return 0
    selected = plan(changed, module_map)
    failed = False
    if selected["tests"]:
        modules = [_module_name(path) for path in selected["tests"]]
        failed = _run([sys.executable, "-m", "unittest", *modules], ROOT) != 0
    for command in selected["commands"]:
        if command == "catalog":
            failed = _run([sys.executable, "-m", "openguildkit", "catalog"], ROOT) != 0 or failed
        elif command == "web-typecheck":
            npm = shutil.which("npm")
            if npm is None:
                print("check_fast: npm is not on PATH, so web/ cannot be typechecked.")
                failed = True
            else:
                failed = _run([npm, "run", "typecheck"], ROOT / "web") != 0 or failed
        else:
            raise SystemExit(f"check_fast: unknown command {command}.")
    if selected["unattached"]:
        print("check_fast: no test is attached to:")
        for path in selected["unattached"]:
            print(f"- {path}")
        failed = True
    if not failed:
        parts = []
        if selected["tests"]:
            parts.append(f"{len(selected['tests'])} test module(s)")
        if selected["commands"]:
            parts.append(f"{len(selected['commands'])} command(s)")
        print("check_fast: " + ", ".join(parts) + ".")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
