"""Proposes the project's test commands at setup and explains why a check command failed.

Nothing is run here: the person confirms each proposed command before it becomes a project check.

Entry: propose_checks, failure_message
Tests: tests/test_project_checks.py
"""

import os
import re
from pathlib import Path

from . import lazy_re
from .detect import MAX_DEPTH, walk
from .storage import load_json


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def _file_names(directory: Path) -> set[str]:
    """The files a folder holds, for a component folder the walk did not list."""
    try:
        with os.scandir(directory) as listing:
            return {entry.name for entry in listing if entry.is_file() and not entry.is_symlink()}
    except OSError:
        return set()


def _npm_scripts(directory: Path, names: set[str]) -> dict:
    """The scripts of the folder's package.json; none when it has none or cannot be read."""
    if "package.json" not in names:
        return {}
    try:
        scripts = load_json(directory / "package.json").get("scripts", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return scripts if isinstance(scripts, dict) else {}


def _npm_script(scripts: dict, name: str) -> str | None:
    """A script of package.json, or None when it is missing or is the npm init placeholder."""
    script = scripts.get(name)
    if not isinstance(script, str) or not script.strip() or "no test specified" in script:
        return None
    return script


PYTHON_MANIFESTS = ("pyproject.toml", "setup.cfg", "tox.ini", "requirements.txt", "requirements-dev.txt", "pytest.ini")


def _python_test(directory: Path, names: set[str]) -> tuple[str, str] | None:
    """pytest when the project names it, python -m unittest when it has a tests folder of test_*.py files."""
    manifests = "\n".join(_read(directory / name) for name in PYTHON_MANIFESTS if name in names)
    if "pytest.ini" in names or re.search(r"\bpytest\b", manifests):
        return "python -m pytest", "pytest named in the project's Python manifests"
    tests = directory / "tests"
    if tests.is_dir() and any(tests.glob("test_*.py")):
        return "python -m unittest discover -s tests", "tests/test_*.py without pytest"
    if any(name.startswith("test_") and name.endswith(".py") for name in names):
        return "python -m unittest discover", "test_*.py files in the folder itself, without pytest"
    return None


def _command(directory: Path, names: set[str], scripts: dict) -> tuple[str, str] | None:
    """The test command a component's manifests show, with the evidence for it.

    names are the files the folder holds, and scripts those of its package.json, both read once per folder.
    """
    if _npm_script(scripts, "test"):
        return "npm test", "a test script in package.json"
    python = _python_test(directory, names)
    if python:
        return python
    if "go.mod" in names:
        return "go test ./...", "go.mod"
    if "Cargo.toml" in names:
        return "cargo test", "Cargo.toml"
    if "pom.xml" in names:
        return ("./mvnw test" if "mvnw" in names else "mvn test"), "pom.xml"
    if {"build.gradle", "build.gradle.kts"} & names:
        return ("./gradlew test" if "gradlew" in names else "gradle test"), "a Gradle build file"
    if any(name.endswith((".sln", ".csproj")) for name in names):
        return "dotnet test", "a .NET solution or project file"
    return None


# The files that make a folder a project of its own; a tests folder alone is not one.
MANIFESTS = ("package.json", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", "go.mod", "Cargo.toml", "pom.xml",
             "build.gradle", "build.gradle.kts")


def _is_project(names: set[str]) -> bool:
    return any(name in names for name in MANIFESTS) or any(name.endswith((".csproj", ".sln")) for name in names)


def _covered_by_solution(path: str, paths: list[str], listings: dict[str, set[str]]) -> bool:
    """A .NET project inside a folder whose solution dotnet test already runs."""
    def has(folder: str, suffix: str) -> bool:
        return any(name.endswith(suffix) for name in listings.get(folder, ()))

    if not has(path, ".csproj") or has(path, ".sln"):
        return False
    parts = path.split("/")
    ancestors = ["/".join(parts[:index]) or "." for index in range(len(parts))] if path != "." else []
    return any(ancestor in paths and has(ancestor, ".sln") for ancestor in ancestors)


def propose_checks(root: Path, detected: dict, listings: dict[str, set[str]] | None = None) -> list[dict]:
    """The test command each component shows, and its lint script when package.json has one, run from that
    component's folder. A .NET project that a solution above it covers gets no command of its own.

    The folders whose manifests name a test runner count too, though detection found no technology there, such
    as a package.json that holds only a test script. listings, the files of each folder that detect_stack
    walked, saves a second walk of the tree; each folder's manifests are read once.
    """
    if listings is None:
        listings = {"/".join(parts) or ".": set(files) for _, parts, files, _ in walk(root, MAX_DEPTH)}
    listings, checks = dict(listings), {}

    def folder_checks(path: str) -> list[tuple[str, str]]:
        if path not in checks:
            names = listings[path] if path in listings else listings.setdefault(path, _file_names(root / path))
            scripts = _npm_scripts(root / path, names)
            found = [_command(root / path, names, scripts)]
            if _npm_script(scripts, "lint"):
                found.append(("npm run lint", "a lint script in package.json"))
            checks[path] = found
        return checks[path]

    test_folders = [relative for relative, names in listings.items()
                    if _is_project(names) and folder_checks(relative)[0] is not None]
    paths = [component["path"] for component in detected.get("components", [])] or ["."]
    paths = list(dict.fromkeys(["." if path in ("", ".") else path for path in paths] + test_folders))
    proposals = []
    for path in paths:
        found = folder_checks(path)  # Lists the folder first if the walk did not reach it.
        if _covered_by_solution(path, paths, listings):
            continue
        where = ""
        if path != ".":
            # Stored checks may run under either cmd.exe or a POSIX shell.
            # Double quotes protect spaces and separators, but both shells still expand some characters.
            if re.search(r'["\\$\x60%!\x00-\x1f]', path):
                continue
            operand = f"./{path}" if path.startswith("-") else path
            if not re.fullmatch(r"[\w./-]+", operand):
                operand = f'"{operand}"'
            where = f"cd {operand} && "
        proposals += [{"command": where + command, "evidence": f"{path}: {evidence}"}
                      for command, evidence in filter(None, found)]
    return proposals


NOT_FOUND = lazy_re.compile(r"command not found|is not recognized as an internal or external command", re.I)
MISSING_DEPENDENCY = lazy_re.compile(
    r"ModuleNotFoundError|No module named|Cannot find module|ERR_MODULE_NOT_FOUND|could not resolve dependencies"
    r"|Could not resolve host|getaddrinfo|ENOTFOUND|EAI_AGAIN|Network is unreachable",
    re.I,
)
TAIL_LINES = 3


# A line that names the error, as test runners and interpreters print it.
ERROR_LINE = lazy_re.compile(r"error|cannot find|can't find|not found|no module|exception|failed|traceback", re.IGNORECASE)


def _telling_lines(output: str) -> list[str]:
    """The lines that say why a command failed: the first that names the error and the last line, within the
    same number of lines as the plain tail; the tail when no line names an error."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    tail = lines[-TAIL_LINES:]
    named = next((line for line in lines if ERROR_LINE.search(line) and not line.lower().startswith("traceback")), None)
    if named is None or named in tail:
        return tail
    return [named, *lines[-(TAIL_LINES - 1):]]


def failure_message(code: int | None, output: str, log: str) -> str:
    """Why a check command failed and what to do, in one line: its cause, its last output lines and its log."""
    tail = " | ".join(_telling_lines(output)) or "no output"
    if code is None:
        cause, step = "timed out", "run it by hand to see where it waits"
    elif code in (127, 9009) or NOT_FOUND.search(output):
        cause = f"exit code {code}, command not found"
        step = "install the project's dependencies or the tool (npm ci, pip install -e ., ...), or fix the command"
    elif MISSING_DEPENDENCY.search(output):
        cause = f"exit code {code}, a dependency or the network is missing"
        step = "install the dependencies where the network is available, then run task verify again"
    else:
        cause, step = f"exit code {code}", "fix the code or the test, then run task verify again"
    return f"{cause}: {tail}. Next: {step}. Log: {log}"
