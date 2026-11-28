"""Validate and evaluate the machine checks that pack rules declare.

A declarative check reads project files with the standard library and executes nothing:
a path exists, a text file contains or lacks a literal text, a field of a JSON or TOML
file compares to a value, or a file stays within a number of bytes. Literal text instead of
regular expressions keeps every match linear, so no pattern can make a check hang. Only a pack
of the project's own catalog may declare a `command` check, which task verify runs like the
project's check commands.
"""

import json
import math
import re
import tomllib
from itertools import islice
from pathlib import Path

from .storage import parse_json
from .wording import plural

CHECK_KINDS = ("file-exists", "text", "field", "size", "command")
FIELD_OPERATORS = ("equals", "one_of", "min", "max", "integer")
FIELD_FORMATS = {".json": "JSON", ".toml": "TOML"}
MAX_PATHS = 20
MAX_FILES = 200
MAX_FILE_BYTES = 1_000_000
MAX_SIZE_BYTES = 1_000_000_000
MAX_LITERALS = 20
MAX_LITERAL_LENGTH = 200
MAX_SAFE_INTEGER = (1 << 53) - 1
# Path segments: letters, digits and . _ - plus the * and ? wildcards; ** matches any depth.
SEGMENT = re.compile(r"[\w.*?@+=-]+")
SKIPPED_DIRECTORIES = {".git", ".openguildkit"}


def _fields(check: dict, label: str, required: set[str], optional: set[str]) -> None:
    missing = required - check.keys()
    extra = check.keys() - required - optional - {"kind"}
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(extra))}")


def validate_path(path: object, label: str, *, pattern: bool = True) -> None:
    """A check path is relative to the project, written with /, and cannot leave it."""
    if not isinstance(path, str) or not path or len(path) > 300:
        raise ValueError(f"{label} must be a relative path of at most 300 characters")
    parts = path.split("/")
    if path.startswith("/") or any(part in ("", ".", "..") or not SEGMENT.fullmatch(part) for part in parts):
        raise ValueError(f"{label} {path!r} must stay inside the project: relative, with / and without . or ..")
    if not pattern and any(character in path for character in "*?"):
        raise ValueError(f"{label} {path!r} names one file: wildcards are not allowed")


def _validate_check_path(path: object, label: str, *, pattern: bool = True) -> None:
    """A check path also stays out of the folders no search reads: a check never looks inside .git or .openguildkit."""
    validate_path(path, label, pattern=pattern)
    if SKIPPED_DIRECTORIES & {part.casefold() for part in path.split("/")}:
        raise ValueError(f"{label} {path!r} is not searched: a check does not read inside .git or .openguildkit")


def _is_number(value: object) -> bool:
    return type(value) in (int, float) and not (isinstance(value, float) and math.isnan(value))


def _is_scalar(value: object) -> bool:
    return value is None or type(value) in (str, bool) or (_is_number(value) and math.isfinite(value))


def _validate_paths(check: dict, label: str) -> None:
    paths = check["paths"]
    if not isinstance(paths, list) or not paths or len(paths) > MAX_PATHS:
        raise ValueError(f"{label}.paths must list 1 to {MAX_PATHS} paths")
    for index, path in enumerate(paths):
        _validate_check_path(path, f"{label}.paths[{index}]")


def _validate_text(check: dict, label: str) -> None:
    _fields(check, label, {"paths", "contains", "expect"}, {"ignore_case", "each"})
    _validate_paths(check, label)
    literals = check["contains"]
    if not isinstance(literals, list) or not literals or len(literals) > MAX_LITERALS:
        raise ValueError(f"{label}.contains must list 1 to {MAX_LITERALS} literal texts")
    for literal in literals:
        if not isinstance(literal, str) or not literal.strip() or len(literal) > MAX_LITERAL_LENGTH:
            raise ValueError(f"{label}.contains holds literal texts of 1 to {MAX_LITERAL_LENGTH} characters")
    if check["expect"] not in ("present", "absent"):
        raise ValueError(f"{label}.expect must be present or absent")
    if "ignore_case" in check and type(check["ignore_case"]) is not bool:
        raise ValueError(f"{label}.ignore_case must be true or false")
    if "each" in check and (check["each"] is not True or check["expect"] != "present"):
        raise ValueError(f"{label}.each must be true, with expect present; omit it otherwise")


def _validate_size(check: dict, label: str) -> None:
    _fields(check, label, {"paths", "max_bytes"}, set())
    _validate_paths(check, label)
    limit = check["max_bytes"]
    if type(limit) is not int or not 1 <= limit <= MAX_SIZE_BYTES:
        raise ValueError(f"{label}.max_bytes must be a whole number of bytes from 1 to {MAX_SIZE_BYTES}")


def _validate_field(check: dict, label: str) -> None:
    _fields(check, label, {"path", "field"}, set(FIELD_OPERATORS))
    _validate_check_path(check["path"], f"{label}.path", pattern=False)
    if Path(check["path"]).suffix not in FIELD_FORMATS:
        raise ValueError(f"{label}.path must name a .json or .toml file")
    field = check["field"]
    if not isinstance(field, str) or not all(part.strip() for part in field.split(".")):
        raise ValueError(f"{label}.field must be a dotted path such as tool.package.name")
    operators = check.keys() & set(FIELD_OPERATORS)
    if not operators:
        raise ValueError(f"{label} needs one of {', '.join(FIELD_OPERATORS)}")
    if "integer" in check and check["integer"] is not True:
        raise ValueError(f"{label}.integer must be true; omit it otherwise")
    for bound in ("min", "max"):
        if bound in check and not (_is_number(check[bound]) and math.isfinite(check[bound])):
            raise ValueError(f"{label}.{bound} must be a number")
    if "min" in check and "max" in check and check["min"] > check["max"]:
        raise ValueError(f"{label}.min is above {label}.max")
    if "equals" in check and not _is_scalar(check["equals"]):
        raise ValueError(f"{label}.equals must be a text, a number, true, false or null")
    if "one_of" in check:
        values = check["one_of"]
        if not isinstance(values, list) or not values or not all(_is_scalar(value) for value in values):
            raise ValueError(f"{label}.one_of must list texts, numbers, true, false or null")


def validate_check(check: object, label: str, *, allow_command: bool) -> None:
    """Refuse a malformed check, and a command check outside the project's own catalog."""
    if not isinstance(check, dict):
        raise ValueError(f"{label} must be a JSON object")
    kind = check.get("kind")
    if kind not in CHECK_KINDS:
        raise ValueError(f"{label}.kind must be one of {', '.join(CHECK_KINDS)}")
    if kind == "file-exists":
        _fields(check, label, {"paths"}, set())
        _validate_paths(check, label)
    elif kind == "text":
        _validate_text(check, label)
    elif kind == "field":
        _validate_field(check, label)
    elif kind == "size":
        _validate_size(check, label)
    else:
        if not allow_command:
            raise ValueError(
                f"{label} runs a command: only a pack in .openguildkit/catalog/packs/ may declare one"
            )
        _fields(check, label, {"command"}, set())
        if not isinstance(check["command"], str) or not check["command"].strip():
            raise ValueError(f"{label}.command must be a non-empty string")


def _show(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def describe_check(check: dict) -> str:
    """One sentence that says what the check accepts, used as the derived rule instruction."""
    kind = check["kind"]
    if kind == "command":
        return f"`{check['command']}` exits with 0."
    if kind == "file-exists":
        return f"One of {', '.join(f'`{path}`' for path in check['paths'])} exists."
    if kind == "text":
        verb = "contains" if check["expect"] == "present" else "does not contain"
        texts = " or ".join(_show(literal) for literal in check["contains"])
        subject = "Each file of " if check.get("each") else ""
        return f"{subject}{', '.join(f'`{path}`' for path in check['paths'])} {verb} {texts}."
    if kind == "size":
        paths = ", ".join(f"`{path}`" for path in check["paths"])
        return f"Each file matching {paths} is at most {check['max_bytes']} bytes."
    conditions = []
    if check.get("integer"):
        conditions.append("an integer")
    if "min" in check and "max" in check:
        conditions.append(f"from {_show(check['min'])} to {_show(check['max'])}")
    elif "min" in check:
        conditions.append(f"at least {_show(check['min'])}")
    elif "max" in check:
        conditions.append(f"at most {_show(check['max'])}")
    if "equals" in check:
        conditions.append(f"equal to {_show(check['equals'])}")
    if "one_of" in check:
        conditions.append(f"one of {', '.join(_show(value) for value in check['one_of'])}")
    return f"`{check['field']}` in `{check['path']}` is {' '.join(conditions)}."


def parse_fields(content: bytes, path: str) -> dict:
    """Read a JSON or TOML file into a table; an unreadable file raises ValueError."""
    if Path(path).suffix == ".json":
        return parse_json(content, path)
    try:
        return tomllib.loads(content.decode("utf-8-sig"))
    except (UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"Invalid TOML in {path}: {error}") from error


def _lookup(data: dict, field: str) -> tuple[bool, object]:
    value: object = data
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def _same(value: object, expected: object) -> bool:
    """Equality that keeps true apart from 1 and false apart from 0."""
    return (type(value) is bool) == (type(expected) is bool) and value == expected


def compare_field(check: dict, data: dict) -> dict:
    """Judge one field: the outcome, the value found when it is a plain value, and why."""
    found, value = _lookup(data, check["field"])
    where = f"{check['path']}: {check['field']}"
    if not found:
        return {"passed": False, "actual": None, "evidence": f"{where} is missing."}
    plain = value if _is_scalar(value) else None
    integer = _is_number(value) and math.isfinite(value) and value == int(value) and abs(value) <= MAX_SAFE_INTEGER
    if integer:
        plain = int(value)
    failures = []
    if check.get("integer") and not integer:
        failures.append("not an integer")
    numeric = _is_number(value) and math.isfinite(value)
    if "min" in check and not (numeric and value >= check["min"]):
        failures.append(f"below {_show(check['min'])}" if numeric else "not a number")
    if "max" in check and not (numeric and value <= check["max"]):
        failures.append(f"above {_show(check['max'])}" if numeric else "not a number")
    if "equals" in check and not _same(value, check["equals"]):
        failures.append(f"not {_show(check['equals'])}")
    if "one_of" in check and not any(_same(value, option) for option in check["one_of"]):
        failures.append("not one of the accepted values")
    shown = _show(plain) if plain is not None or value is None else "a value of another type"
    reasons = "; ".join(dict.fromkeys(failures))
    evidence = f"{where} = {shown}" + (f" ({reasons})." if failures else ".")
    return {"passed": not failures, "actual": plain, "evidence": evidence}


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def matching_paths(root: Path, patterns: list[str]) -> tuple[list[Path], bool]:
    """Existing paths inside the project that the patterns name, and whether there were too many."""
    root = root.resolve()
    found: dict[str, Path] = {}
    for pattern in patterns:
        if any(character in pattern for character in "*?"):
            candidates = islice(
                (path for path in root.glob(pattern)
                 if not SKIPPED_DIRECTORIES & set(path.relative_to(root).parts)),
                MAX_FILES + 1,
            )
        else:
            candidates = [root / pattern] if (root / pattern).exists() else []
        for path in candidates:
            if _inside(root, path):
                found.setdefault(path.relative_to(root).as_posix(), path)
            if len(found) > MAX_FILES:
                return [], True
    return [found[name] for name in sorted(found)], False


def _read_bounded(path: Path) -> bytes | None:
    if path.stat().st_size > MAX_FILE_BYTES:
        return None
    return path.read_bytes()


def _text_outcome(root: Path, check: dict) -> tuple[bool, str]:
    paths, too_many = matching_paths(root, check["paths"])
    if too_many:
        return False, f"More than {MAX_FILES} files match: narrow the paths of the check."
    files = [path for path in paths if path.is_file()]
    fold = (lambda text: text.casefold()) if check.get("ignore_case") else (lambda text: text)
    literals = [fold(literal) for literal in check["contains"]]
    hits, skipped, lacking = [], [], []
    for path in files:
        content = _read_bounded(path)
        name = path.relative_to(root.resolve()).as_posix()
        if content is None:
            skipped.append(name)
            continue
        text = fold(content.decode("utf-8", errors="replace"))
        found = [f"{name} contains {_show(literal)}" for literal in literals if literal in text]
        hits.extend(found)
        if not found:
            lacking.append(name)
    if skipped:
        return False, f"Larger than {MAX_FILE_BYTES} bytes, not read: {', '.join(skipped)}."
    if check.get("each") and files:
        if lacking:
            return False, f"No text of the check in {', '.join(lacking[:5])}."
        return True, f"{plural(len(files), 'file')} read, each contains the text."
    if check["expect"] == "present":
        if hits:
            return True, f"{'; '.join(hits[:5])}."
        return False, f"No file matching {', '.join(check['paths'])} contains the text." if files else (
            f"No file matches {', '.join(check['paths'])}."
        )
    if hits:
        return False, f"{'; '.join(hits[:5])}."
    return True, f"{plural(len(files), 'file')} read, none contains the text."


def _size_outcome(root: Path, check: dict) -> tuple[bool, str]:
    """Measure the files the paths name, without reading them: the largest is the evidence."""
    paths, too_many = matching_paths(root, check["paths"])
    if too_many:
        return False, f"More than {MAX_FILES} files match: narrow the paths of the check."
    limit = check["max_bytes"]
    sizes = sorted(((path.stat().st_size, path.relative_to(root.resolve()).as_posix())
                    for path in paths if path.is_file()), key=lambda item: (-item[0], item[1]))
    if not sizes:
        return True, f"No file matches {', '.join(check['paths'])}: nothing is above {limit} bytes."
    above = [f"{name} is {size} bytes, above {limit}" for size, name in sizes if size > limit]
    if above:
        return False, f"{'; '.join(above[:5])}."
    size, name = sizes[0]
    return True, f"{name} is {size} bytes (the largest of {plural(len(sizes), 'file')}; at most {limit})."


def evaluate_check(root: Path, check: dict) -> dict:
    """Evaluate a declarative check on the working tree: passed or failed, with what was found."""
    if check["kind"] == "file-exists":
        paths, too_many = matching_paths(root, check["paths"])
        if too_many:
            return {"status": "failed", "evidence": f"More than {MAX_FILES} paths match: narrow the check."}
        if paths:
            names = [path.relative_to(root.resolve()).as_posix() for path in paths]
            return {"status": "passed", "evidence": f"Found {', '.join(names[:5])}."}
        return {"status": "failed", "evidence": f"Not found: none of {', '.join(check['paths'])} exists."}
    if check["kind"] == "text":
        passed, evidence = _text_outcome(root, check)
        return {"status": "passed" if passed else "failed", "evidence": evidence}
    if check["kind"] == "size":
        passed, evidence = _size_outcome(root, check)
        return {"status": "passed" if passed else "failed", "evidence": evidence}
    paths, _ = matching_paths(root, [check["path"]])
    if not paths or not paths[0].is_file():
        return {"status": "failed", "evidence": f"{check['path']} does not exist."}
    content = _read_bounded(paths[0])
    if content is None:
        return {"status": "failed", "evidence": f"{check['path']} is larger than {MAX_FILE_BYTES} bytes."}
    try:
        outcome = compare_field(check, parse_fields(content, check["path"]))
    except ValueError as error:
        return {"status": "failed", "evidence": str(error)}
    return {"status": "passed" if outcome["passed"] else "failed", "evidence": outcome["evidence"]}
