"""Say in one line per problem what this workstation lacks to work on OpenGuildKit.

    python scripts/doctor.py

Checks Python against requires-python, Git, Node against .nvmrc, npm, the origin/main revision that
scripts/check_fast.py compares with, and web/node_modules. Exits 0 when nothing is missing, 1 otherwise.
"""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - INTENTIONAL(#520): the one line an older Python gets
    raise SystemExit("OpenGuildKit needs Python 3.11 or later; this is Python %d.%d. Run it with python3.11 or newer."
                     % sys.version_info[:2])

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _output(command: list[str], cwd: Path) -> str | None:
    """What a command prints, or None when it is missing or fails."""
    if shutil.which(command[0]) is None:
        return None
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def probe(root: Path = ROOT) -> dict:
    """The versions and revisions this machine has: None for what is missing."""
    return {
        "python": "%d.%d" % sys.version_info[:2],
        "git": _output(["git", "--version"], root),
        "node": _output(["node", "--version"], root),
        "npm": _output(["npm", "--version"], root),
        "origin/main": _output(["git", "rev-parse", "--verify", "--quiet", "origin/main^{commit}"], root),
    }


def _numbers(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def problems(found: dict, root: Path = ROOT) -> list[str]:
    """One line per missing tool or wrong version."""
    lines = []
    floor = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    if _numbers(found["python"]) < _numbers(floor):
        lines.append(f"Python {found['python']}: OpenGuildKit needs Python {floor.removeprefix('>=')} or later.")
    if not found["git"]:
        lines.append("git is not on PATH: install Git.")
    node = (root / ".nvmrc").read_text(encoding="utf-8").strip()
    if not found["node"]:
        lines.append(f"node is not on PATH: install Node {node} (.nvmrc) for web/ and integrations/ci/.")
    elif _numbers(found["node"])[:1] != _numbers(node)[:1]:
        lines.append(f"Node {found['node'].lstrip('v')}: web/ and CI use Node {node} (.nvmrc).")
    if not found["npm"]:
        lines.append("npm is not on PATH: it comes with Node.")
    if found["git"] and not found["origin/main"]:
        lines.append("origin/main is unknown: run git fetch origin main, or give scripts/check_fast.py --base HEAD.")
    if not (root / "web" / "node_modules").is_dir():
        lines.append("web/node_modules is missing: run cd web && npm ci --ignore-scripts.")
    return lines


def main() -> int:
    found = problems(probe())
    for line in found:
        print(f"doctor: {line}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
