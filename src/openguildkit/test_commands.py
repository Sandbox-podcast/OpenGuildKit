"""Test and lint commands a repository already shows, proposed at setup so that task verify has something to run."""

from __future__ import annotations

import json
from pathlib import Path

MAX_SUGGESTIONS = 4
_IGNORED = {"node_modules", ".git", ".venv", "venv", "dist", "build", "target", "bin", "obj"}


def _find(root: Path, pattern: str, depth: int = 2) -> bool:
    """True when a file matching the pattern sits in the root or up to `depth` folders below it."""
    stack = [(root, 0)]
    while stack:
        folder, level = stack.pop()
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_file() and entry.match(pattern):
                return True
            if entry.is_dir() and level < depth and entry.name not in _IGNORED and not entry.name.startswith("."):
                stack.append((entry, level + 1))
    return False


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def suggest_checks(root: Path) -> list[str]:
    """Commands that the repository's own files point to. Nothing is run: the person accepts or removes each one."""
    found: list[str] = []
    package = root / "package.json"
    if package.is_file():
        try:
            scripts = json.loads(_read(package)).get("scripts", {})
        except (ValueError, AttributeError):
            scripts = {}
        test = scripts.get("test") if isinstance(scripts, dict) else None
        if isinstance(test, str) and test.strip() and "no test specified" not in test:
            found.append("npm test")
        if isinstance(scripts, dict) and isinstance(scripts.get("lint"), str):
            found.append("npm run lint")
    pyproject = _read(root / "pyproject.toml")
    if "pytest" in pyproject or (root / "pytest.ini").is_file() or "pytest" in _read(root / "tox.ini"):
        found.append("python -m pytest")
    elif any(path.is_file() for path in root.glob("tests/**/test_*.py")):
        found.append("python -m unittest discover -s tests")
    elif any(path.is_file() for path in root.glob("test_*.py")):
        found.append("python -m unittest discover")
    if _find(root, "*.sln") or _find(root, "*.csproj"):
        found.append("dotnet test")
    if (root / "pom.xml").is_file():
        found.append("mvn test")
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        found.append("./gradlew test" if (root / "gradlew").is_file() else "gradle test")
    if (root / "go.mod").is_file():
        found.append("go test ./...")
    if (root / "Cargo.toml").is_file():
        found.append("cargo test")
    return list(dict.fromkeys(found))[:MAX_SUGGESTIONS]
