"""The code owners of the paths a task touches, read from the project's CODEOWNERS with GitHub's syntax.

Shown in the decision brief and the handoff, never written into a task or a decision record: the owners are often
people's names or emails (docs/personal-data.md), and whether a record may keep them is still an open decision.

GitHub's rules, as its page "About code owners" states them (read on 2026-11-26,
https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners):
the file is .github/CODEOWNERS, CODEOWNERS or docs/CODEOWNERS, searched in that order, and the first one found is
used; patterns follow most gitignore rules, but `!` negation and `[ ]` ranges do not work; the last matching pattern
takes precedence; a pattern without owners leaves its paths without one; paths are case sensitive; a file of 3 MB or
more is not loaded.

Entry: parse, owners_of, read_codeowners, touched_paths, owner_line
Tests: tests/test_owners.py
"""

import re
from pathlib import Path, PurePosixPath

LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
MAX_BYTES = 3 * 1024 * 1024
# The touched paths named in one line; the others are counted.
MAX_SHOWN = 8
# A file name no name pattern such as *.js or ?.py targets: a folder's owners are those of its files in general.
_PROBE = "\0probe\0"
_BRIEF_PATH = re.compile(r"(?<![\w.:/-])[\w.-]+/(?:[\w.-]+/?)*")


def _segment(text: str) -> str:
    return "".join("[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char) for char in text)


def _regex(pattern: str) -> re.Pattern:
    """A gitignore pattern as GitHub reads it: anchored when it starts with or holds a slash, a trailing slash for a
    folder's contents, ** across folders, and a last segment with a wildcard that matches files only in its folder."""
    directory = pattern.endswith("/")
    body = pattern.rstrip("/")
    anchored = body.startswith("/") or "/" in body
    parts = body.lstrip("/").split("/")
    out, last = [], len(parts) - 1
    for index, part in enumerate(parts):
        if part == "**":
            out.append(".*" if index == last else "(?:[^/]+/)*")
            continue
        out.append(_segment(part) + ("" if index == last else "/"))
    wildcard = any(char in parts[-1] for char in "*?") and parts[-1] != "**"
    tail = "/.+" if directory else "" if wildcard else "(?:/.+)?"
    return re.compile(("" if anchored else "(?:.*/)?") + "".join(out) + tail)


def parse(text: str) -> tuple[list[dict], list[int]]:
    """The rules of a CODEOWNERS file in order, and the numbers of the lines skipped: a negation or a character range,
    which GitHub does not support."""
    rules, skipped = [], []
    for number, line in enumerate(text.splitlines(), start=1):
        tokens = line.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        pattern = tokens[0]
        if pattern.startswith("!") or "[" in pattern or "]" in pattern:
            skipped.append(number)
            continue
        found = []
        for token in tokens[1:]:
            if token.startswith("#"):
                break
            found.append(token)
        rules.append({"line": number, "pattern": pattern, "regex": _regex(pattern), "owners": found})
    return rules, skipped


def owners_of(rules: list[dict], path: str, directory: bool = False) -> list[str] | None:
    """The owners of a project path, from the last rule that matches it: [] when that rule names none, None when no
    rule matches. A folder reads the rule that covers its files in general, not one for some files inside it."""
    path = PurePosixPath(path.replace("\\", "/")).as_posix().strip("/")
    if path in ("", "."):
        path = ""
    probe = f"{path}/{_PROBE}" if directory and path else _PROBE if directory else path
    found = None
    for rule in rules:
        if rule["regex"].fullmatch(probe):
            found = rule["owners"]
    return found


def read_codeowners(root: Path) -> dict | None:
    """The project's CODEOWNERS: the first of LOCATIONS that exists inside the project, its rules and skipped lines.
    None when there is none."""
    resolved = root.resolve()
    for location in LOCATIONS:
        path = root / location
        if not path.is_file() or not path.resolve().is_relative_to(resolved):
            continue
        if path.stat().st_size >= MAX_BYTES:
            return {"file": location, "too_large": True, "rules": [], "skipped": []}
        rules, skipped = parse(path.read_text(encoding="utf-8", errors="replace"))
        return {"file": location, "too_large": False, "rules": rules, "skipped": skipped}
    return None


def _lane_path(entry: str) -> tuple[str, bool]:
    """A short-lane glob as the folder before its first wildcard, or the path itself when it has none."""
    parts = entry.replace("\\", "/").strip("/").split("/")
    fixed = []
    for part in parts:
        if any(char in part for char in "*?["):
            return "/".join(fixed), True
        fixed.append(part)
    return "/".join(fixed), entry.endswith("/")


def touched_paths(root: Path, task: dict) -> list[tuple[str, str, bool]]:
    """What the task touches, as (label, path, is folder): its short-lane paths, the folders of the components it
    names, and the project paths its brief and answers name. None of them: the whole project."""
    touched: dict[str, tuple[str, bool]] = {}
    for entry in task.get("paths", []) if isinstance(task.get("paths"), list) else []:
        if isinstance(entry, str) and entry.strip():
            touched[entry] = _lane_path(entry)
    scope = task.get("consultation", {}).get("scope", {})
    answers = task.get("answers") if isinstance(task.get("answers"), dict) else scope.get("answers", {})
    named = set(answers.get("components", [])) if isinstance(answers.get("components"), list) else set()
    for component in scope.get("components", []):
        folder = (component.get("path") or "").strip("/") if isinstance(component, dict) else ""
        if folder and component.get("id") in named:
            touched[folder + "/"] = (folder, True)
    text = " ".join([task.get("brief", ""), *(value for value in answers.values() if isinstance(value, str))])
    for match in _BRIEF_PATH.finditer(text):
        found = match.group(0).rstrip(".")
        path = root / found
        if ".." in found.split("/") or not path.exists() or not path.resolve().is_relative_to(root.resolve()):
            continue
        folder = path.is_dir()
        relative = found.rstrip("/")
        touched.setdefault(relative + ("/" if folder else ""), (relative, folder))
    return [(label, path, folder) for label, (path, folder) in touched.items()] or [("whole project", "", True)]


def owner_line(root: Path, task: dict) -> str | None:
    """One line naming the owners of each touched path, or None when the project has no CODEOWNERS."""
    found = read_codeowners(root)
    if found is None:
        return None
    if found["too_large"]:
        return f"Code owners: {found['file']} is over 3 MB, which GitHub does not load; no owner is shown."
    paths = touched_paths(root, task)
    items = []
    for label, path, folder in paths[:MAX_SHOWN]:
        names = owners_of(found["rules"], path, folder)
        items.append(f"{label} {' '.join(names) if names else 'no owner declared'}")
    more = f"; and {len(paths) - MAX_SHOWN} more paths" if len(paths) > MAX_SHOWN else ""
    skipped = (f" Lines {', '.join(map(str, found['skipped']))} skipped: GitHub does not support ! or [ ] in "
               "CODEOWNERS." if found["skipped"] else "")
    return (f"Code owners, read from {found['file']} (shown here, never recorded): {'; '.join(items)}{more}."
            f"{skipped}")
