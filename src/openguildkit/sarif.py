"""Write findings as SARIF 2.1.0, the OASIS standard that code scanning dashboards read (#420).

A finding is the same dict for every command that reports in SARIF: `finding(code, level, message, path, line)`.
`code` names a rule, `level` is `error`, `warning` or `note`, `path` is a file relative to the project root with `/`
separators (None when no file is precise, which points at the project profile) and `line` is a line number or None.
`to_sarif` turns a list of findings and the descriptions of the rules they use into the document; `sarif_text` writes
it the same way every time, so two runs on the same project give the same bytes.

The document holds no folder of the machine: a path is relative, and the project folder and the home folder are
taken out of every message.
"""

import hashlib
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .storage import json_text

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
TOOL_NAME = "OpenGuildKit"
TOOL_URI = "https://github.com/Sandbox-podcast/OpenGuildKit"
# The page of a rule, as its `help` says it (PAGE.md#anchor), read on the main branch of the repository.
DOCS_URI = f"{TOOL_URI}/blob/main/docs/"
# Where a finding without a precise file is reported: the profile every project has.
DEFAULT_PATH = ".openguildkit/project.json"
# The key under which a result carries its fingerprint, so that a dashboard does not open an alert again at each run.
FINGERPRINT_KEY = "openguildkit/v1"
LEVELS = ("error", "warning", "note")
_DRIVE = re.compile(r"^[A-Za-z]:")


def finding(code: str, level: str, message: str, path: str | None = None, line: int | None = None) -> dict:
    """The form of a finding that `to_sarif` reads."""
    return {"code": code, "level": level, "message": message, "path": path, "line": line}


def _clean_path(path) -> str:
    """The path as a POSIX path relative to the project root, or the profile's path when there is none."""
    if path is None:
        return DEFAULT_PATH
    posix = path.replace("\\", "/") if isinstance(path, str) else ""
    if not posix.strip() or posix.startswith("/") or _DRIVE.match(posix) or ".." in posix.split("/"):
        raise ValueError(f"A finding's path must be relative to the project root, without '..': {path!r}.")
    clean = PurePosixPath(posix).as_posix()
    if clean == ".":
        raise ValueError(f"A finding's path must be relative to the project root and name a file: {path!r}.")
    return clean


def _folders(root: Path | None) -> list[str]:
    """The ways the project folder can be written, the longest first."""
    forms = set()
    if root is not None:
        paths = [root]
        try:
            paths.append(root.resolve())
        except OSError:
            pass
        forms = {form for path in paths for form in (str(path), path.as_posix())}
    return sorted((form for form in forms if len(form) > 1), key=len, reverse=True)


def _home() -> list[str]:
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        return []
    return [form for form in sorted({str(home), home.as_posix()}, key=len, reverse=True) if len(form) > 1]


def _relative(found) -> str:
    """The path that follows the project folder, written with / on every platform."""
    return found.group(1).replace("\\", "/")


def _without_machine(text: str, root: Path | None) -> str:
    """Take the project folder and the home folder out of a message: a file inside the project is named relative to
    it, the folder itself is "the project folder", and the home folder is `~`."""
    for form in _folders(root):
        text = re.sub(re.escape(form) + r"[/\\]([\w.@+=\-/\\]*)", _relative, text)
        text = re.sub(re.escape(form) + r"(?![\w\-/\\]|\.\w)", "the project folder", text)
    for form in _home():
        text = re.sub(re.escape(form) + r"(?![\w\-]|\.\w)", "~", text)
    return text


def _normalized(message: str) -> str:
    return " ".join(message.split())


def fingerprint(item: dict) -> str:
    """The SHA-256 of `code|path|message`, the message with its spaces and line breaks collapsed.

    The line is not part of it, so that code added above a finding does not make it a new one, and neither is the
    level. The same finding keeps the same fingerprint from one run to the next and from one machine to another.
    """
    text = f"{item['code']}|{_clean_path(item.get('path'))}|{_normalized(item['message'])}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prepared(item: dict, rules: dict, root: Path | None) -> dict:
    code, level, message, line = item.get("code"), item.get("level"), item.get("message"), item.get("line")
    if code not in rules:
        raise ValueError(f"No rule describes the finding code {code!r}: add it to the rules the command passes.")
    if level not in LEVELS:
        raise ValueError(f"The level of a finding must be error, warning or note, not {level!r} ({code}).")
    if not isinstance(message, str) or not message.strip():
        raise ValueError(f"A finding needs a message ({code}).")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
        raise ValueError(f"The line of a finding must be a positive whole number, not {line!r} ({code}).")
    return {"code": code, "level": level, "message": _without_machine(message, root),
            "path": _clean_path(item.get("path")), "line": line}


def _rule(code: str, rule: dict) -> dict:
    for key in ("name", "description", "help"):
        if not isinstance(rule.get(key), str) or not rule[key].strip():
            raise ValueError(f"The rule {code} lacks its {key}.")
    if "#" not in rule["help"]:
        raise ValueError(f"The help of the rule {code} must name a page and an anchor, as PAGE.md#anchor.")
    return {"id": code, "name": rule["name"], "shortDescription": {"text": rule["description"]},
            "helpUri": DOCS_URI + rule["help"]}


def to_sarif(findings: list[dict], *, rules: dict[str, dict], tool_version: str, root: Path | None = None) -> dict:
    """The SARIF document of a list of findings.

    `rules` maps each code to `{"name", "description", "help"}`; the document lists only the rules a finding uses.
    The results come in a fixed order (path, line, code, message), so the order a command found them in changes
    nothing, and a finding written twice is written once. Two findings that differ only by their line keep distinct
    fingerprints: the first, in line order, has the plain one and the next ones add `:2`, `:3`. `root` is the project
    folder, taken out of the messages.
    """
    if not isinstance(tool_version, str) or not tool_version.strip():
        raise ValueError("The SARIF document needs the version of the tool.")
    prepared = [_prepared(item, rules, root) for item in findings]
    unique = {(item["code"], item["path"], item["line"], item["message"], item["level"]): item for item in prepared}
    ordered = sorted(unique.values(), key=lambda item: (item["path"], item["line"] or 0, item["code"], item["message"],
                                                         item["level"]))
    used = sorted({item["code"] for item in ordered})
    position = {code: number for number, code in enumerate(used)}
    seen: Counter = Counter()
    results = []
    for item in ordered:
        digest = fingerprint(item)
        seen[digest] += 1
        physical = {"artifactLocation": {"uri": quote(item["path"], safe="/"), "uriBaseId": "%SRCROOT%"}}
        if item["line"] is not None:
            physical["region"] = {"startLine": item["line"]}
        results.append({
            "ruleId": item["code"],
            "ruleIndex": position[item["code"]],
            "level": item["level"],
            "message": {"text": item["message"]},
            "locations": [{"physicalLocation": physical}],
            "partialFingerprints": {FINGERPRINT_KEY: digest if seen[digest] == 1 else f"{digest}:{seen[digest]}"},
        })
    driver = {"name": TOOL_NAME, "version": tool_version, "informationUri": TOOL_URI,
              "rules": [_rule(code, rules[code]) for code in used]}
    return {"$schema": SARIF_SCHEMA, "version": SARIF_VERSION, "runs": [{"tool": {"driver": driver}, "results": results}]}


def sarif_text(document: dict) -> str:
    """The document as text: two-space indentation, keys in the order they were built, characters as they are
    (UTF-8 when written) and one final line break."""
    return json_text(document)
