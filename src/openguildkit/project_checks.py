"""Propose the project's test commands at setup, and say why a check command failed.

Nothing is run here: the person confirms each proposed command before it becomes a project check.
"""

import json
import re
from pathlib import Path

from .detect import MAX_DEPTH, SKIPPED_DIRECTORIES


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def _npm_script(directory: Path, name: str) -> str | None:
    """A script of package.json, or None when it is missing or is the npm init placeholder."""
    try:
        scripts = json.loads(_read(directory / "package.json") or "{}").get("scripts", {})
    except (ValueError, AttributeError):
        return None
    script = scripts.get(name) if isinstance(scripts, dict) else None
    if not isinstance(script, str) or not script.strip() or "no test specified" in script:
        return None
    return script


def _npm_test(directory: Path) -> str | None:
    """npm test when package.json has a test script other than the npm init placeholder."""
    return "npm test" if _npm_script(directory, "test") else None


def _python_test(directory: Path) -> tuple[str, str] | None:
    """pytest when the project names it, python -m unittest when it has a tests folder of test_*.py files."""
    manifests = "\n".join(_read(directory / name) for name in (
        "pyproject.toml", "setup.cfg", "tox.ini", "requirements.txt", "requirements-dev.txt", "pytest.ini"))
    if (directory / "pytest.ini").is_file() or re.search(r"\bpytest\b", manifests):
        return "python -m pytest", "pytest named in the project's Python manifests"
    tests = directory / "tests"
    if manifests.strip() and tests.is_dir() and any(tests.glob("test_*.py")):
        return "python -m unittest discover -s tests", "tests/test_*.py without pytest"
    if any(path.is_file() for path in directory.glob("test_*.py")):
        return "python -m unittest discover", "test_*.py files in the folder itself, without pytest"
    return None


def _command(directory: Path) -> tuple[str, str] | None:
    """The test command a component's manifests show, with the evidence for it."""
    npm = _npm_test(directory)
    if npm:
        return npm, "a test script in package.json"
    python = _python_test(directory)
    if python:
        return python
    if (directory / "go.mod").is_file():
        return "go test ./...", "go.mod"
    if (directory / "Cargo.toml").is_file():
        return "cargo test", "Cargo.toml"
    if (directory / "pom.xml").is_file():
        return ("./mvnw test" if (directory / "mvnw").is_file() else "mvn test"), "pom.xml"
    if any((directory / name).is_file() for name in ("build.gradle", "build.gradle.kts")):
        return ("./gradlew test" if (directory / "gradlew").is_file() else "gradle test"), "a Gradle build file"
    if any(directory.glob("*.sln")) or any(directory.glob("*.csproj")):
        return "dotnet test", "a .NET solution or project file"
    return None


# The files that make a folder a project of its own; a tests folder alone is not one.
MANIFESTS = ("package.json", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", "go.mod", "Cargo.toml", "pom.xml",
             "build.gradle", "build.gradle.kts")


def _test_folders(root: Path) -> list[str]:
    """Folders under root whose manifests name a test runner, though detection found no technology there,
    such as a package.json that holds only a test script."""
    folders = []

    def visit(directory: Path, depth: int) -> None:
        manifest = any((directory / name).is_file() for name in MANIFESTS) or any(directory.glob("*.csproj")) \
            or any(directory.glob("*.sln"))
        if manifest and _command(directory) is not None:
            folders.append(directory.relative_to(root).as_posix() or ".")
        if depth >= MAX_DEPTH:
            return
        try:
            children = sorted(entry for entry in directory.iterdir() if entry.is_dir() and not entry.is_symlink())
        except OSError:
            return
        for child in children:
            if child.name not in SKIPPED_DIRECTORIES:
                visit(child, depth + 1)

    visit(root, 0)
    return folders


def _covered_by_solution(path: str, paths: list[str], root: Path) -> bool:
    """A .NET project inside a folder whose solution dotnet test already runs."""
    if not any((root / path).glob("*.csproj")) or any((root / path).glob("*.sln")):
        return False
    parts = path.split("/")
    ancestors = ["/".join(parts[:index]) or "." for index in range(len(parts))] if path != "." else []
    return any(ancestor in paths and any((root / ancestor).glob("*.sln")) for ancestor in ancestors)


def propose_checks(root: Path, detected: dict) -> list[dict]:
    """The test command each component shows, and its lint script when package.json has one, run from that
    component's folder. A .NET project that a solution above it covers gets no command of its own."""
    paths = [component["path"] for component in detected.get("components", [])] or ["."]
    paths = list(dict.fromkeys(["." if path in ("", ".") else path for path in paths] + _test_folders(root)))
    proposals = []
    for path in paths:
        if _covered_by_solution(path, paths, root):
            continue
        found = [_command(root / path)]
        if _npm_script(root / path, "lint"):
            found.append(("npm run lint", "a lint script in package.json"))
        where = "" if path == "." else f"cd {path} && "
        proposals += [{"command": where + command, "evidence": f"{path}: {evidence}"}
                      for command, evidence in filter(None, found)]
    return proposals


NOT_FOUND = re.compile(r"command not found|is not recognized as an internal or external command", re.I)
MISSING_DEPENDENCY = re.compile(
    r"ModuleNotFoundError|No module named|Cannot find module|ERR_MODULE_NOT_FOUND|could not resolve dependencies"
    r"|Could not resolve host|getaddrinfo|ENOTFOUND|EAI_AGAIN|Network is unreachable",
    re.I,
)
TAIL_LINES = 3


# A line that names the error, as test runners and interpreters print it.
ERROR_LINE = re.compile(r"error|cannot find|can't find|not found|no module|exception|failed|traceback", re.IGNORECASE)


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
