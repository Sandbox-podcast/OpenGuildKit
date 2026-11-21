"""Storybook for a project: reference the company's Storybook, compare it with the project's own,
and extract a design system from an existing React application.

The CLI never runs npm and never opens the network. It writes the refs file that the project's
.storybook/main imports, reads Storybook index.json files the team built or downloaded, and records
the known stories in .openguildkit/storybook.json so boards can cite a story and its state. From the
application's sources it writes an inventory, proposals the team decides on, and for validated items
only, Design Tokens, CSF3 stories and an index that the team edits.
"""

import hashlib
import json
import os
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from . import clock
from .storage import json_text, project_lock, read_json, write_json, write_text

STORYBOOK_VERSION = "10.6.6"
RECORD = "storybook.json"
REFS_FILE = "openguildkit-refs.json"
PROJECT_REF = "project"
INDEX_VERSIONS = (4, 5)
MAIN_FILES = ("main.ts", "main.mts", "main.cts", "main.js", "main.mjs", "main.cjs")
_REF_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
STYLING_PACKAGES = (
    "tailwindcss", "styled-components", "@emotion/", "sass", "less", "@mui/", "bootstrap", "@vanilla-extract/",
    "@chakra-ui/", "@stitches/", "@pandacss/", "@mantine/", "@radix-ui/themes", "postcss",
)
_THEME_WORDS = ("theme", "token", "color", "colour", "couleur", "typograph", "spacing", "palette", "css", "style")


OUTSIDE = "outside:"
MINIMAL_MAIN = """import type { StorybookConfig } from '@storybook/react-vite';
import refs from './openguildkit-refs.json' with { type: 'json' };

const config: StorybookConfig = {
  framework: '@storybook/react-vite',
  stories: ['../src/**/*.mdx', '../src/**/*.stories.@(js|jsx|mjs|ts|tsx)'],
  addons: ['@storybook/addon-docs'],
  refs,
};
export default config;
"""


def _home() -> Path | None:
    """The user's home folder, kept apart so a test can stand in for it."""
    try:
        return Path.home().resolve()
    except (RuntimeError, OSError):
        return None


def _outside_relative(root: Path, path: Path) -> str | None:
    """A path outside the project written relative to it, unless that would spell the drive or the home folder.

    Both are resolved. Files written here are committed, so they must not carry a user name.
    """
    try:
        relative = os.path.relpath(path, root)
        common = Path(os.path.commonpath([path, root]))
    except ValueError:
        return None
    if common.parent == common:
        return None
    home = _home()
    if home and (home == path or home in path.parents) and not (home == root or home in root.parents):
        return None
    return Path(relative).as_posix()


def _relative(root: Path, path: Path) -> str:
    """A path as the project's committed files write it: never absolute, outside:NAME when it cannot be relative."""
    resolved, base = path.resolve(), root.resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError:
        return _outside_relative(base, resolved) or OUTSIDE + resolved.name


def ref_id(value: str) -> str:
    if not isinstance(value, str) or not _REF_ID.fullmatch(value) or len(value) > 40:
        raise ValueError("Use a Storybook ref ID of lowercase letters, digits and hyphens.")
    return value


def citation(ref: str, story_id: str) -> str:
    """The project's stories are cited by ID; a composed Storybook's as REF_ID, the ID Storybook shows in its URL."""
    return f"storybook:{story_id}" if ref == PROJECT_REF else f"storybook:{ref}_{story_id}"


# Storybook index.json


def index_file(path: Path) -> Path:
    return path / "index.json" if path.is_dir() else path


def read_index(path: Path) -> list[dict]:
    """Entries of a Storybook 7+ index.json (format 4 or 5), from a static build or a downloaded file."""
    path = index_file(path)
    data = read_json(path)
    if "entries" not in data and "stories" in data:
        raise ValueError(f"{path} is a Storybook 6 stories.json. Build the Storybook with version 7 or later.")
    if data.get("v") not in INDEX_VERSIONS or not isinstance(data.get("entries"), dict):
        raise ValueError(f"{path} is not a Storybook index.json (format version 4 or 5).")
    entries = []
    for key, entry in data["entries"].items():
        if not isinstance(entry, dict) or entry.get("id") != key or not key or any(
                character.isspace() or character in "/_:" for character in key):
            raise ValueError(f"{path}: unexpected Storybook entry {key!r}.")
        if not all(isinstance(entry.get(field), str) and entry[field].strip() for field in ("title", "name")):
            raise ValueError(f"{path}: entry {key} needs a title and a name.")
        kind = entry.get("type", "story")
        if kind not in ("story", "docs"):
            raise ValueError(f"{path}: entry {key} has an unknown type {kind!r}.")
        tags = entry.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"{path}: entry {key} has invalid tags.")
        item = {"id": key, "title": entry["title"].strip(), "name": entry["name"].strip(), "type": kind, "tags": tags}
        if isinstance(entry.get("importPath"), str):
            item["importPath"] = entry["importPath"]
        entries.append(item)
    return entries


def components(entries: list[dict]) -> list[dict]:
    """Stories grouped by title. A title with only docs pages is not a component."""
    grouped: dict[str, dict] = {}
    for entry in entries:
        item = grouped.setdefault(entry["title"], {
            "title": entry["title"], "name": entry["title"].split("/")[-1].strip(), "stories": [], "docs": []})
        item["stories" if entry["type"] == "story" else "docs"].append(entry["id"])
    return list(grouped.values())


def _name_key(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).casefold()
    return "".join(character for character in folded if character.isalnum())


def compare(project: list[dict], company: list[dict]) -> dict:
    """Project components matched by name in the company Storybook, those left to map, and duplicates."""
    company_components = [item for item in components(company) if item["stories"]]
    by_name = {}
    for item in company_components:
        by_name.setdefault(_name_key(item["name"]), item)
    matched, to_map = [], []
    for item in components(project):
        if not item["stories"]:
            continue
        counterpart = by_name.get(_name_key(item["name"]))
        if counterpart:
            matched.append({"project": item["title"], "company": counterpart["title"]})
        else:
            to_map.append({"title": item["title"], "stories": item["stories"]})
    company_ids = {entry["id"] for entry in company}
    company_titles = {entry["title"] for entry in company}
    return {
        "matched": matched,
        "to_map": to_map,
        "conflicts": {
            "story_ids": sorted({entry["id"] for entry in project} & company_ids),
            "titles": sorted({entry["title"] for entry in project} & company_titles),
        },
    }


# Versions and ranges, as npm writes them in package.json.

_PARTIAL = re.compile(r"v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")
_COMPARATOR = re.compile(r"(\^|~>?|>=|<=|>|<|=)?(.+)")
_OPERATORS = ("^", "~", "~>", ">=", "<=", ">", "<", "=")


def _partial(text: str):
    match = _PARTIAL.fullmatch(text.strip())
    if not match:
        return None
    parts = [None if part is None or part in "xX*" else int(part) for part in match.groups()[:3]]
    for index in range(1, 3):
        if parts[index - 1] is None:
            parts[index] = None
    return parts, match.group(4)


def _version(parts, prerelease=None) -> tuple:
    major, minor, patch = (part or 0 for part in parts)
    # A release sorts after its prereleases.
    return (major, minor, patch, 0 if prerelease else 1, prerelease or "")


def parse_version(text: str) -> tuple | None:
    parsed = _partial(text)
    if not parsed or None in parsed[0]:
        return None
    return _version(*parsed)


def _bump(parts, position: int) -> tuple:
    bumped = [part or 0 for part in parts]
    bumped[position] += 1
    for index in range(position + 1, 3):
        bumped[index] = 0
    return _version(bumped, "0")


def _comparators(operator: str, parts: list, prerelease) -> list[tuple]:
    known = len([part for part in parts if part is not None])
    if known == 0:
        return [] if operator in ("", "=", "^", "~", "~>", ">=", "<=") else [("<", (0, 0, 0, 0, "0"))]
    low = _version(parts, prerelease)
    if operator == "^":
        # Bump the first non-zero part: ^1.2.3 is below 2.0.0, ^0.2.3 below 0.3.0, ^0.0.3 below 0.0.4.
        position = next((index for index, part in enumerate(parts[:known]) if part), known - 1)
        return [(">=", low), ("<", _bump(parts, position))]
    if operator in ("~", "~>"):
        return [(">=", low), ("<", _bump(parts, 1 if known > 1 else 0))]
    if operator in ("", "="):
        return [("=", low)] if known == 3 else [(">=", low), ("<", _bump(parts, known - 1))]
    if operator == ">":
        return [(">", low)] if known == 3 else [(">=", _bump(parts, known - 1))]
    if operator == "<=":
        return [("<=", low)] if known == 3 else [("<", _bump(parts, known - 1))]
    return [(operator, low)]


def parse_range(text: str) -> list[list[tuple]] | None:
    """npm's range grammar: alternatives with ||, hyphen ranges, ^, ~, x-ranges and comparators."""
    if not isinstance(text, str) or re.search(r"[:/#]|^\s*(latest|next|workspace)", text):
        return None
    alternatives = []
    for alternative in text.split("||"):
        alternative = alternative.strip()
        hyphen = re.fullmatch(r"(\S+)\s+-\s+(\S+)", alternative)
        if hyphen:
            low, high = _partial(hyphen.group(1)), _partial(hyphen.group(2))
            if not low or not high:
                return None
            alternatives.append(_comparators(">=", *low) + _comparators("<=", *high))
            continue
        tokens: list[str] = []
        for token in alternative.split():
            if tokens and tokens[-1] in _OPERATORS:
                tokens[-1] += token
            else:
                tokens.append(token)
        comparators = []
        for token in tokens or ["*"]:
            operator, value = _COMPARATOR.fullmatch(token).groups()
            parsed = _partial(value)
            if not parsed:
                return None
            comparators.extend(_comparators(operator or "", *parsed))
        alternatives.append(comparators)
    return alternatives


def satisfies(version: tuple, ranges: list[list[tuple]]) -> bool:
    checks = {"=": lambda a, b: a == b, ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
              "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}
    return any(all(checks[operator](version, bound) for operator, bound in alternative) for alternative in ranges)


def lowest(ranges: list[list[tuple]]) -> list[tuple]:
    """The lowest version each alternative accepts. An alternative without a lower bound tells nothing."""
    result = []
    for alternative in ranges:
        bounds = [bound for operator, bound in alternative if operator in (">=", "=")]
        if bounds:
            result.append(max(bounds))
    return result


def _version_text(version: tuple) -> str:
    return ".".join(str(part) for part in version[:3]) + (f"-{version[4]}" if version[3] == 0 else "")


def _project_dependencies(package: dict) -> dict:
    merged = {}
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        for name, spec in (package.get(field) or {}).items():
            merged.setdefault(name, spec)
    return merged


def _installed_version(root: Path, name: str) -> str | None:
    manifest = root / "node_modules" / name / "package.json"
    try:
        version = read_json(manifest).get("version")
    except (OSError, ValueError):
        return None
    return version if isinstance(version, str) and parse_version(version) else None


def dependency_conflicts(library: dict, package: dict, root: Path) -> list[dict]:
    """The company library's peer dependencies and shared dependencies against the project's versions."""
    project = _project_dependencies(package)
    optional = {name for name, meta in (library.get("peerDependenciesMeta") or {}).items()
                if isinstance(meta, dict) and meta.get("optional")}
    rows = []
    sources = [("peer", library.get("peerDependencies") or {}), ("dependency", library.get("dependencies") or {})]
    for kind, requirements in sources:
        for name, wanted in sorted(requirements.items()):
            if kind == "dependency" and name not in project:
                continue
            row = {"name": name, "kind": kind, "library": wanted, "project": project.get(name),
                   "styling": name.startswith(STYLING_PACKAGES)}
            installed = _installed_version(root, name)
            if installed:
                row["installed"] = installed
            ranges = parse_range(wanted) if isinstance(wanted, str) else None
            if name not in project:
                row["status"] = "optional" if name in optional else "missing"
            elif ranges is None:
                row["status"] = "unknown"
            else:
                versions = [parse_version(installed)] if installed else lowest(parse_range(project[name]) or [])
                if not versions:
                    row["status"] = "unknown"
                else:
                    results = [satisfies(version, ranges) for version in versions]
                    compatible = "ok" if all(results) else "partial" if any(results) else None
                    row["status"] = compatible or ("conflict" if kind == "peer" else "duplicate")
                    row["checked"] = [_version_text(version) for version in versions]
            rows.append(row)
    return rows


def theme_sources(library: dict | None, company: list[dict]) -> list[dict]:
    """Theme candidates: library exports and Storybook pages that name colors, tokens or styles."""
    found = []
    if library:
        exports = library.get("exports")
        targets = []
        if isinstance(exports, str):
            targets.append((".", exports))
        elif isinstance(exports, dict):
            for key, value in exports.items():
                targets.append((key, value if isinstance(value, str) else json.dumps(value, sort_keys=True)))
        for field in ("style", "sass"):
            if isinstance(library.get(field), str):
                targets.append((field, library[field]))
        for key, value in targets:
            if any(word in f"{key} {value}".casefold() for word in _THEME_WORDS):
                found.append({"source": "library", "export": key, "path": value})
    for entry in company:
        if any(word in entry["title"].casefold() for word in _THEME_WORDS):
            found.append({"source": "storybook", "title": entry["title"], "id": entry["id"], "type": entry["type"]})
    return found


# The managed refs file and the record of known stories.


def _check_ref_url(url: object) -> None:
    """The refs file is committed: an https URL, or localhost while testing, and never credentials."""
    try:
        netloc = urlsplit(url).netloc if isinstance(url, str) else ""
    except ValueError:
        netloc = ""
    if "@" in netloc:
        raise ValueError("Remove the user name and password from the URL: the refs file is committed. "
                         "Let the Storybook host handle authentication, with its own sign-in.")
    if not netloc or not re.fullmatch(r"(https://[^\s]+|http://(localhost|127\.0\.0\.1)(:\d+)?(/[^\s]*)?)", url):
        raise ValueError("The composed Storybook needs an https URL, or http://localhost while testing.")


def compose(root: Path, ref: str, url: str | None, title: str | None = None, remove: bool = False,
            config_dir: str = ".storybook") -> dict:
    """Add, update or remove one composed Storybook in the refs file that .storybook/main imports."""
    ref = ref_id(ref)
    if ref == PROJECT_REF:
        raise ValueError(f"{PROJECT_REF} is reserved for the project's own Storybook.")
    directory = (root / config_dir).resolve()
    if root.resolve() not in (directory, *directory.parents):
        raise ValueError("The Storybook configuration folder must be inside the project.")
    if not directory.is_dir():
        raise ValueError(f"No Storybook configuration in {config_dir}. Create the project Storybook first, "
                         f"with npm create storybook@{STORYBOOK_VERSION}, or create the {config_dir} folder and run "
                         "this command again: it prints a minimal main.ts.")
    path = directory / REFS_FILE
    refs = read_json(path) if path.exists() else {}
    if any(not isinstance(item, dict) or not isinstance(item.get("url"), str) for item in refs.values()):
        raise ValueError(f"{path.name} is managed by openguildkit storybook compose and holds refs only.")
    if remove:
        if ref not in refs:
            raise ValueError(f"No composed Storybook named {ref} in {path.name}.")
        del refs[ref]
    else:
        _check_ref_url(url)
        current = refs.get(ref, {})
        title = (title or current.get("title") or ref).strip()
        if not title or len(title.splitlines()) != 1:
            raise ValueError("The title is a single line of text.")
        refs[ref] = {**current, "title": title, "url": url.rstrip("/")}
    write_json(path, dict(sorted(refs.items())))
    main = next((directory / name for name in MAIN_FILES if (directory / name).is_file()), None)
    imported = bool(main) and REFS_FILE in main.read_text(encoding="utf-8", errors="replace")
    result = {"file": _relative(root, path), "refs": refs, "main": _relative(root, main) if main else None,
              "imported": imported}
    if main is None:
        result["minimal_main"] = MINIMAL_MAIN
        result["minimal_main_file"] = _relative(root, directory / "main.ts")
    if not imported:
        result["add_to_main"] = [
            f"import refs from './{REFS_FILE}' with {{ type: 'json' }};",
            "refs,  // inside the exported configuration object",
        ]
    return result


def _validate_story(item: object) -> dict:
    if not isinstance(item, dict) or item.keys() != {"id", "title", "name"} or not all(
            isinstance(item[key], str) and item[key].strip() for key in item):
        raise ValueError("Each recorded story needs id, title and name.")
    return dict(item)


def validate_record(record: dict) -> dict:
    if not isinstance(record, dict) or record.get("schema_version") != 1 or not isinstance(record.get("indexes"), list):
        raise ValueError(f"{RECORD} needs schema_version 1 and a list of indexes.")
    refs = set()
    indexes = []
    for index in record["indexes"]:
        if not isinstance(index, dict) or index.keys() != {"ref", "source", "sha256", "recorded", "stories"}:
            raise ValueError("Each recorded index needs ref, source, sha256, recorded and stories.")
        ref = index["ref"] if index["ref"] == PROJECT_REF else ref_id(index["ref"])
        if ref in refs:
            raise ValueError(f"The Storybook index {ref} is recorded twice.")
        refs.add(ref)
        if not isinstance(index["recorded"], str) or not _DAY.fullmatch(index["recorded"]):
            raise ValueError("recorded must be a date written YYYY-MM-DD.")
        date.fromisoformat(index["recorded"])
        if not isinstance(index["stories"], list):
            raise ValueError("stories must be a list.")
        indexes.append({**index, "stories": [_validate_story(item) for item in index["stories"]]})
    return {"schema_version": 1, "indexes": indexes}


def load_record(state: Path) -> dict | None:
    path = state / RECORD
    return validate_record(read_json(path)) if path.is_file() else None


def _index_entry(root: Path, ref: str, path: Path, entries: list[dict], today: date) -> dict:
    return {
        "ref": ref,
        "source": _relative(root, path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "recorded": today.isoformat(),
        "stories": [{"id": item["id"], "title": item["title"], "name": item["name"]}
                    for item in entries if item["type"] == "story"],
    }


def _newer_story_source(root: Path, index: Path, entries: list[dict]) -> Path | None:
    root = root.resolve()
    built_at = index.stat().st_mtime_ns
    folders = {root / name for name in ("src", "app", "components", "stories", ".storybook")}
    files = {path for path in root.glob("*.stories.*") if path.is_file()}
    for entry in entries:
        if "importPath" in entry:
            source = (root / entry["importPath"]).resolve()
            if root in source.parents:
                folders.add(source.parent)
                if source.is_file():
                    files.add(source)
    project_folders = [folder for folder in sorted(folders) if folder.is_dir() and root in folder.resolve().parents]
    files.update(path for _, path in _source_files(project_folders))
    for path in sorted(files):
        if path.suffix in (*_MODULE_SUFFIXES, ".mdx", ".css", ".scss") and root in path.resolve().parents \
                and path.stat().st_mtime_ns > built_at:
            return path
    return None


def import_indexes(root: Path, state: Path, project_index: Path | None = None, company_index: Path | None = None,
                   ref: str = "company", library: Path | None = None, package: Path | None = None,
                   today: date | None = None) -> dict:
    """Compare the company Storybook with the project's, report what to map, and record the known stories.

    Only .openguildkit/storybook.json is written: the project's stories and configuration stay as they are.
    """
    today = today or clock.today()
    ref = ref_id(ref)
    if ref == PROJECT_REF:
        raise ValueError(f"{PROJECT_REF} is reserved for the project's own Storybook.")
    if project_index is None and (root / "storybook-static" / "index.json").is_file():
        project_index = root / "storybook-static"
    if project_index is None and company_index is None:
        raise ValueError("Give --project-index, --company-index or both. Build the project Storybook with "
                         "npm run build-storybook to get storybook-static/index.json.")
    indexes = {}
    report: dict = {}
    for name, given in ((PROJECT_REF, project_index), (ref, company_index)):
        if given is not None:
            path = index_file(given)
            entries = read_index(path)
            indexes[name] = (path, entries)
            report[PROJECT_REF if name == PROJECT_REF else "company"] = {
                "ref": name, "source": _relative(root, path),
                "components": [{key: item[key] for key in ("title", "stories", "docs")} for item in components(entries)],
                "stories": sum(item["type"] == "story" for item in entries),
            }
    if PROJECT_REF in indexes:
        path, entries = indexes[PROJECT_REF]
        newer = _newer_story_source(root, path, entries)
        if newer is not None:
            report["warnings"] = [
                f"{_relative(root, newer)} is newer than {_relative(root, path)}. "
                "Run npm run build-storybook, then import the project index again."
            ]
    if PROJECT_REF in indexes and ref in indexes:
        report.update(compare(indexes[PROJECT_REF][1], indexes[ref][1]))
    library_data = None
    if library is not None:
        library_data = read_json(library)
        package = package or root / "package.json"
        report["dependencies"] = dependency_conflicts(library_data, read_json(package), root)
    if ref in indexes or library_data:
        report["themes"] = theme_sources(library_data, indexes.get(ref, (None, []))[1])
    with project_lock(state):
        record = load_record(state) or {"schema_version": 1, "indexes": []}
        kept = [item for item in record["indexes"] if item["ref"] not in indexes]
        fresh = [_index_entry(root, name, path, entries, today) for name, (path, entries) in indexes.items()]
        record["indexes"] = sorted(kept + fresh, key=lambda item: (item["ref"] != PROJECT_REF, item["ref"]))
        write_json(state / RECORD, validate_record(record))
    report["record"] = _relative(root, state / RECORD)
    return report


def scope_entry(state: Path, today: date | None = None) -> dict | None:
    """What a consultation carries when the project has recorded a Storybook index: the story IDs boards can cite."""
    record = load_record(state)
    if not record:
        return None
    today = today or clock.today()
    return {
        "record": f"{state.name}/{RECORD}",
        "cite": "storybook:STORY_ID for the project's stories, storybook:REF_STORY_ID for a composed Storybook. "
                "The ID names one story, so one state, as in the Storybook URL ?path=/story/ID.",
        "indexes": [
            {"ref": item["ref"], "source": item["source"], "recorded": item["recorded"],
             "age_days": (today - date.fromisoformat(item["recorded"])).days,
             "stories": [story["id"] for story in item["stories"]]}
            for item in record["indexes"]
        ],
    }


# Extraction from an existing React application, with the standard library only.

INVENTORY = "storybook/inventory.json"
PROPOSALS = "storybook/proposals.json"
MANIFEST = "storybook/generated.json"
STATUSES = ("proposed", "validated", "rejected")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "out", "coverage", "storybook-static", ".next", ".openguildkit"}
MAX_FILE_BYTES = 1_000_000
_NAME = r"[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*"
_FUNCTION = re.compile(rf"^[ \t]*(export\s+(?:default\s+)?)?(?:async\s+)?function\s+({_NAME})\s*(?:<[^>()]*>)?\s*\(", re.M)
_CONST = re.compile(
    rf"^[ \t]*(export\s+)?const\s+({_NAME})\b[^=\n]*=\s*(?:React\.)?(?:(?:forwardRef|memo)\s*(?:<[^>()]*>)?\s*\(\s*)?"
    r"(?:async\s+)?(?:function\b[^(]*)?\(", re.M)
_EXPORT_LIST = re.compile(r"\bexport\s*\{([^}]*)\}(?:\s*from\s*(['\"])([^'\"\n]+)\2)?")
_EXPORT_ITEM = re.compile(r"\s*(?:type\s+)?([A-Za-z_$][\w$]*)(?:\s+as\s+([A-Za-z_$][\w$]*))?\s*")
_MODULE_SUFFIXES = (".tsx", ".jsx", ".ts", ".js")
_EXPORT_DEFAULT = re.compile(rf"\bexport\s+default\s+({_NAME})\s*;?\s*$", re.M)
_TAG = re.compile(r"<([A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*)?)(?=[\s/>])")
_ATTRIBUTE = re.compile(r"[A-Za-z_][\w:.-]*")
_VARIANT_VALUE = re.compile(r"[a-z][a-z0-9-]{0,30}")
_TYPED_VARIANT = re.compile(_VARIANT_VALUE.pattern, re.I | re.ASCII)
# Props that carry content or wiring rather than a visual variant.
_CONTENT_PROPS = {
    "children", "label", "title", "text", "placeholder", "alt", "href", "src", "id", "name", "key", "classname",
    "style", "value", "defaultvalue", "to", "description", "heading", "message", "caption", "tooltip", "role",
    "htmlfor", "type", "as", "ref", "onclick", "onchange", "testid",
}
_SYNTHETIC_TEXT = {"label", "title", "text", "heading", "placeholder", "description", "name", "caption", "message"}
_COLOR = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z])|(?:rgba?|hsla?)\([^()]*\)")
_LENGTH = re.compile(r"(?<![\w.-])(\d*\.?\d+)(px|rem)(?![\w-])")
_DECLARATION = re.compile(r"(--[\w-]+|\$[\w-]+|[a-zA-Z-]+)\s*:\s*([^;{}]+?)\s*(?=;|})")
_VAR = re.compile(r"var\(\s*(--[\w-]+)")
_SCSS_VAR = re.compile(r"\$([\w-]+)")
TOKEN_GROUPS = {"color": "color", "spacing": "spacing", "radius": "radius", "font-size": "font-size",
                "font-family": "font-family", "dimension": "dimension"}


def _strip_js_comments(text: str) -> str:
    """Blank out comments and keep every line in place, so positions still give line numbers."""
    out, index, quote = [], 0, None
    while index < len(text):
        character = text[index]
        if quote:
            out.append(character)
            if character == "\\" and index + 1 < len(text):
                out.append(text[index + 1])
                index += 2
                continue
            if character == quote or (character == "\n" and quote != "`"):
                quote = None
        elif character in "'\"`":
            quote = character
            out.append(character)
        elif text.startswith("//", index) and (index == 0 or text[index - 1] != ":"):
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            out.append(" " * (end - index))
            index = end
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end < 0 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[index:end]))
            index = end
            continue
        else:
            out.append(character)
        index += 1
    return "".join(out)


def _closing(text: str, start: int, opening: str = "{", closing: str = "}") -> int:
    """Index of the bracket that closes the one at start, skipping quoted text; -1 if none."""
    depth, quote, index = 0, None, start
    while index < len(text):
        character = text[index]
        if quote:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
        elif character in "'\"`":
            quote = character
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _split_top_level(text: str, separators: str = ",") -> list[str]:
    parts, depth, quote, current = [], 0, None, []
    for index, character in enumerate(text):
        if quote:
            if character == quote and text[index - 1] != "\\":
                quote = None
        elif character in "'\"`":
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character in separators and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _literal(expression: str):
    """(True, value) for a string, number or boolean literal; (False, None) otherwise."""
    expression = expression.strip()
    if len(expression) >= 2 and expression[0] == expression[-1] and expression[0] in "'\"`" \
            and not (expression[0] == "`" and "${" in expression):
        return True, expression[1:-1]
    if expression in ("true", "false"):
        return True, expression == "true"
    if re.fullmatch(r"-?\d+(\.\d+)?", expression):
        return True, float(expression) if "." in expression else int(expression)
    return False, None


def _destructured_props(text: str, start: int) -> list[dict] | None:
    """Props of a component whose first parameter is destructured: names and literal defaults."""
    position = start
    while position < len(text) and text[position] in " \t\r\n":
        position += 1
    if position >= len(text) or text[position] != "{":
        return None
    end = _closing(text, position)
    if end < 0:
        return None
    props = []
    for part in _split_top_level(text[position + 1:end]):
        if part.startswith("..."):
            continue
        match = re.match(r"([A-Za-z_$][\w$]*)\s*(?::\s*[A-Za-z_$][\w$]*)?\s*(?:=\s*(.+))?$", part, re.S)
        if not match:
            continue
        prop = {"name": match.group(1)}
        if match.group(2) is not None:
            known, value = _literal(match.group(2))
            if known:
                prop["default"] = value
        props.append(prop)
    return props


def _line_of(starts: list[int], position: int) -> int:
    low, high = 0, len(starts)
    while low < high:
        middle = (low + high) // 2
        if starts[middle] <= position:
            low = middle + 1
        else:
            high = middle
    return low


def _line_starts(text: str) -> list[int]:
    return [0] + [match.end() for match in re.finditer("\n", text)]


def _tag_attributes(text: str, start: int):
    """Attributes of a JSX opening tag from start, its end and whether it closes itself."""
    attributes, index = [], start
    while index < len(text):
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if index >= len(text):
            break
        if text.startswith("/>", index):
            return attributes, index + 2, True
        if text[index] == ">":
            return attributes, index + 1, False
        if text[index] == "{":
            end = _closing(text, index)
            if end < 0:
                break
            attributes.append(("...", False, None))
            index = end + 1
            continue
        match = _ATTRIBUTE.match(text, index)
        if not match:
            break
        name, index = match.group(0), match.end()
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if text[index:index + 1] != "=":
            attributes.append((name, True, True))
            continue
        index += 1
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if text[index:index + 1] in ("'", '"'):
            end = text.find(text[index], index + 1)
            if end < 0:
                break
            attributes.append((name, True, text[index + 1:end]))
            index = end + 1
        elif text[index:index + 1] == "{":
            end = _closing(text, index)
            if end < 0:
                break
            known, value = _literal(text[index + 1:end])
            attributes.append((name, known, value))
            index = end + 1
        else:
            break
    return None, index, False


def _source_files(sources: list[Path]):
    """Each source file with the folder given for it, in POSIX path order on every system."""
    for base in sources:
        base = base.resolve()
        if base.is_file():
            yield base.parent, base
        elif base.is_dir():
            files = []
            for folder, dirs, names in os.walk(base):
                dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
                files.extend(Path(folder) / name for name in names)
            for path in sorted(files, key=lambda item: item.as_posix()):
                if path.is_file():
                    yield base, path
        else:
            raise ValueError(f"No such file or folder: {base.name}. Give a --src path that exists.")


def _file_label(root: Path, base: Path, path: Path) -> str:
    """A source file as the inventory names it: relative to the project, or outside:FOLDER/... by the given folder."""
    label = _relative(root, path)
    if label.startswith(OUTSIDE):
        return f"{OUTSIDE}{base.name}/{path.relative_to(base).as_posix()}"
    return label


def _origin(label: str, line: int) -> str:
    return f"{label}:{line}"


def _type_body(code: str, name: str) -> str | None:
    """The members of an interface or object type alias declared in the same file."""
    match = re.search(rf"\binterface\s+{re.escape(name)}\b[^{{;]*\{{", code) or re.search(
        rf"\btype\s+{re.escape(name)}\s*(?:<[^>]*>)?\s*=\s*\{{", code)
    if not match:
        return None
    end = _closing(code, match.end() - 1)
    return code[match.end():end] if end > 0 else None


def _type_alias(code: str, name: str) -> str | None:
    """The right-hand side of type NAME = ..., up to its semicolon or the last line that continues the union."""
    match = re.search(rf"\btype\s+{re.escape(name)}\s*=", code)
    if not match:
        return None
    lines, rest = [], code[match.end():].split("\n")
    for index, line in enumerate(rest):
        if index and not line.strip().startswith("|"):
            break
        lines.append(line.split(";")[0])
        if ";" in line:
            break
    return " ".join(lines)


def _string_union(code: str, type_text: str, depth: int = 0) -> list[str] | None:
    """The values of a union of string literals, following type aliases of the same file; None for other types."""
    values = []
    for part in type_text.strip().lstrip("|").split("|"):
        part = part.strip()
        known, value = _literal(part)
        if known and isinstance(value, str) and part[0] != "`":
            values.append(value)
        elif part in ("undefined", "null"):
            continue
        elif _JS_IDENTIFIER.fullmatch(part) and depth < 3 and _type_alias(code, part) is not None:
            nested = _string_union(code, _type_alias(code, part), depth + 1)
            if nested is None:
                return None
            values.extend(nested)
        else:
            return None
    values = list(dict.fromkeys(values))
    return values if len(values) >= 2 else None


def _member_types(body: str) -> dict:
    """Prop name to (type text, required) for the top-level members of an object type."""
    starts = re.compile(r"^(?:readonly\s+)?([A-Za-z_$][\w$]*)\s*(\?)?\s*:\s*(.*)$", re.S)
    members = {}
    current = None
    for part in _split_top_level(body, ",;\n"):
        match = starts.fullmatch(part)
        if match:
            current, optional, annotation = match.groups()
            members[current] = (annotation, optional is None)
        elif current:
            annotation, required = members[current]
            members[current] = (f"{annotation} {part}".strip(), required)
    return members


def _props_type(code: str, after_props: int, declaration: str) -> dict:
    """Member types of the props: the annotation after the destructured parameter, or FC<Props> on a constant."""
    position = after_props
    while position < len(code) and code[position] in " \t\r\n":
        position += 1
    name = None
    if code[position:position + 1] == ":":
        annotation = code[position + 1:].lstrip()
        if annotation.startswith("{"):
            end = _closing(annotation, 0)
            return _member_types(annotation[1:end]) if end > 0 else {}
        match = _JS_IDENTIFIER.match(annotation)
        name = match.group(0) if match else None
    if name is None:
        generics = re.findall(r"<([^<>()]*)>", declaration)
        if generics:
            name = generics[-1].split(",")[-1].strip()
    body = _type_body(code, name) if name and _JS_IDENTIFIER.fullmatch(name) else None
    return _member_types(body) if body is not None else {}


def _sample_arg(code: str, name: str, annotation: str, depth: int = 0):
    """Find a JSON sample for a locally declared type, without reading prop values from app usages."""
    if depth >= 4:
        return False, None
    if annotation in ("string", "ReactNode", "React.ReactNode"):
        return True, f"Sample {name}"
    if annotation == "number":
        return True, 1
    if annotation == "boolean":
        return True, False
    if (annotation.endswith("[]") and "=>" not in annotation) or re.fullmatch(r"(?:Readonly)?Array<.+>", annotation):
        return True, []
    if annotation == "null":
        return True, None
    options = _string_union(code, annotation)
    if options and all(_TYPED_VARIANT.fullmatch(option) for option in options):
        return True, options[0]
    known, value = _literal(annotation)
    if known and (not isinstance(value, str) or _TYPED_VARIANT.fullmatch(value)):
        return True, value
    body = annotation[1:-1] if annotation.startswith("{") and annotation.endswith("}") else None
    if body is None and _JS_IDENTIFIER.fullmatch(annotation):
        body = _type_body(code, annotation)
        if body is None:
            alias = _type_alias(code, annotation)
            if alias:
                return _sample_arg(code, name, alias.strip(), depth + 1)
    if body is not None:
        fields = {}
        for field, (field_type, required) in _member_types(body).items():
            if required:
                known, value = _sample_arg(code, field, field_type, depth + 1)
                if not known:
                    return False, None
                fields[field] = value
        return True, fields
    return False, None


def _export_lists(path: Path, code: str, reexports: list) -> dict:
    """Local name to the public names an export list gives it; re-exports from another module are set aside."""
    exported: dict[str, list[str]] = {}
    for match in _EXPORT_LIST.finditer(code):
        for item in match.group(1).split(","):
            names = _EXPORT_ITEM.fullmatch(item)
            if not names:
                continue
            local, public = names.group(1), names.group(2) or names.group(1)
            if match.group(3):
                reexports.append((path, match.group(3), local, public))
            else:
                exported.setdefault(local, []).append(public)
    for match in _EXPORT_DEFAULT.finditer(code):
        exported.setdefault(match.group(1), []).append("default")
    return exported


def _export_of(name: str, prefix: str, publics: list[str]) -> tuple[str | None, str]:
    """How the component is exported and the name to import: its own name first, then default, then an alias."""
    if "default" in prefix:
        return "default", "default"
    if prefix or name in publics:
        return "named", name
    if "default" in publics:
        return "default", "default"
    return ("named", publics[0]) if publics else (None, "")


def _scan_reexports(path: Path, text: str, reexports: list) -> None:
    """An index module that re-exports components, possibly under another name."""
    _export_lists(path, _strip_js_comments(text), reexports)


def _scan_components(label: str, path: Path, text: str, definitions: dict, usages: dict, modules: dict,
                     reexports: list) -> None:
    code = _strip_js_comments(text)
    starts = _line_starts(code)
    exported = _export_lists(path, code, reexports)
    public_names = modules.setdefault(path, {})
    has_jsx = bool(_TAG.search(code)) or bool(re.search(r"<[a-z][a-z0-9]*[\s/>]", code))
    for pattern in (_FUNCTION, _CONST):
        for match in pattern.finditer(code):
            prefix, name = match.group(1) or "", match.group(2)
            export, public = _export_of(name, prefix, exported.get(name, []))
            if not export or not has_jsx or name in definitions:
                continue
            props = _destructured_props(code, match.end())
            if props is not None:
                members = _props_type(code, _closing(code, code.index("{", match.end())) + 1, match.group(0))
                destructured = {prop["name"] for prop in props}
                props.extend({"name": member} for member, (_, required) in members.items()
                             if required and member not in destructured)
                for prop in props:
                    annotation, required = members.get(prop["name"], ("", False))
                    options = _string_union(code, annotation)
                    if options:
                        prop["options"] = options
                    if required:
                        prop["required"] = True
                        known, value = _sample_arg(code, prop["name"], annotation)
                        if known:
                            prop["sample"] = value
            definitions[name] = {
                "name": name, "file": label, "line": _line_of(starts, match.start(2)),
                "export": export, "props": props if props is not None else [],
                "children": any(prop["name"] == "children" for prop in props or []),
            }
            if export == "named" and public != name:
                definitions[name]["public"] = public
            for alias in {public, *exported.get(name, [])}:
                public_names[alias] = name
    for match in _TAG.finditer(code):
        if match.start() > 0 and (code[match.start() - 1].isalnum() or code[match.start() - 1] in "_$).]"):
            continue
        attributes, _, closes = _tag_attributes(code, match.end())
        if attributes is None:
            continue
        name = match.group(1)
        usage = usages.setdefault(name, {"count": 0, "origins": [], "with_children": 0, "props": {}, "calls": []})
        usage["count"] += 1
        origin = _origin(label, _line_of(starts, match.start()))
        usage["origins"].append(origin)
        usage["with_children"] += not closes
        literals = {}
        for prop, known, value in attributes:
            entry = usage["props"].setdefault(prop, {"literal": 0, "dynamic": 0})
            entry["literal" if known else "dynamic"] += 1
            if known:
                literals[prop] = value
        usage["calls"].append((origin, literals, [prop for prop, _, _ in attributes]))


def _variant_prop(prop: str, options: list[str] | None = None) -> bool:
    """A prop that can carry a visual state, not content or wiring."""
    if prop == "type" and options:
        return True
    return prop.casefold() not in _CONTENT_PROPS and not prop.startswith(("aria-", "data-", "on"))


def _module_file(path: Path, specifier: str) -> Path | None:
    """The scanned module a relative import specifier names, as a bundler resolves it."""
    if not specifier.startswith("."):
        return None
    target = path.parent / specifier
    candidates = [target, *(target.with_name(target.name + suffix) for suffix in _MODULE_SUFFIXES),
                  *(target / f"index{suffix}" for suffix in _MODULE_SUFFIXES)]
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)


def _aliases(definitions: dict, modules: dict, reexports: list) -> dict:
    """Component name to the other names the application uses it under: export aliases and re-exports."""
    aliases: dict[str, list[str]] = {}

    def add(name: str | None, alias: str) -> None:
        if name in definitions and alias not in (name, "default") and alias not in definitions:
            aliases.setdefault(name, [])
            if alias not in aliases[name]:
                aliases[name].append(alias)

    for public_names in modules.values():
        for alias, name in public_names.items():
            add(name, alias)
    for path, specifier, local, public in reexports:
        target = _module_file(path, specifier)
        add(modules.get(target, {}).get(local), public)
    return aliases


def _merged_usage(found: list[dict]) -> dict:
    """The uses of one component under each of its names, counted together."""
    merged = {"count": 0, "origins": [], "with_children": 0, "calls": [], "props": {}}
    for usage in found:
        for field in ("count", "with_children"):
            merged[field] += usage[field]
        for field in ("origins", "calls"):
            merged[field].extend(usage[field])
    return merged


def _hex(red: float, green: float, blue: float, alpha: float = 1.0) -> str:
    channels = [max(0, min(255, round(value))) for value in (red, green, blue)]
    text = "#" + "".join(f"{value:02x}" for value in channels)
    return text if alpha >= 1 else text + f"{max(0, min(255, round(alpha * 255))):02x}"


def normalize_color(text: str) -> str | None:
    """A CSS hex, rgb() or hsl() color as #rrggbb, or #rrggbbaa below full opacity."""
    text = text.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(character * 2 for character in digits)
        if len(digits) == 8 and digits.endswith("ff"):
            digits = digits[:6]
        return "#" + digits if len(digits) in (6, 8) else None
    match = re.fullmatch(r"(rgba?|hsla?)\(([^()]*)\)", text)
    if not match:
        return None
    values = [item for item in re.split(r"[\s,/]+", match.group(2).strip()) if item]
    if len(values) not in (3, 4):
        return None
    try:
        alpha = 1.0
        if len(values) == 4:
            alpha = float(values[3][:-1]) / 100 if values[3].endswith("%") else float(values[3])
        if match.group(1).startswith("rgb"):
            channels = [float(item[:-1]) * 2.55 if item.endswith("%") else float(item) for item in values[:3]]
            return _hex(*channels, alpha)
        hue = float(values[0].removesuffix("deg")) % 360 / 360
        saturation, lightness = (float(item.rstrip("%")) / 100 for item in values[1:3])
    except ValueError:
        return None
    import colorsys

    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return _hex(red * 255, green * 255, blue * 255, alpha)


def _length(number: str, unit: str) -> str | None:
    value = float(number)
    if value == 0:
        return None
    return f"{value:g}{unit}"


def _dimension_kind(name: str) -> str:
    lowered = name.casefold()
    if "radius" in lowered or "rounded" in lowered:
        return "radius"
    if "font" in lowered or "text" in lowered:
        return "font-size"
    if any(word in lowered for word in ("space", "spacing", "gap", "padding", "margin", "inset")):
        return "spacing"
    return "dimension"


def _scan_styles(label: str, path: Path, text: str, tokens: dict, variables: dict) -> None:
    code = re.sub(r"/\*.*?\*/", lambda match: re.sub(r"[^\n]", " ", match.group(0)), text, flags=re.S)
    if path.suffix == ".scss":
        code = re.sub(r"(^|[^:])//[^\n]*", lambda match: match.group(1), code)
    starts = _line_starts(code)

    def add(kind: str, value: str, origin: str, variable: str | None = None) -> None:
        key = f"{kind}:{value}"
        # Keep the original key for the first candidate so existing proposals still match.
        primary = tokens.get(key)
        if variable and primary and primary.get("variable") not in (None, variable):
            key = f"{key}:{variable}"
        token = tokens.setdefault(key, {
            "key": key, "kind": kind, "value": value, "occurrences": 0, "origins": []})
        token["occurrences"] += 1
        token["origins"].append(origin)
        if variable:
            token["name_hint"] = variable.removeprefix("--").removeprefix("$")
            token["variable"] = variable

    for match in _DECLARATION.finditer(code):
        prop, value = match.group(1), match.group(2).strip()
        origin = _origin(label, _line_of(starts, match.start()))
        for variable in _VAR.findall(value):
            variables.setdefault(variable, []).append(origin)
        if path.suffix == ".scss":
            for variable in _SCSS_VAR.findall(value):
                variables.setdefault(f"${variable}", []).append(origin)
        if prop.startswith(("--", "$")):
            hint = prop.lstrip("-$")
            colors = _COLOR.findall(value)
            lengths = _LENGTH.findall(value)
            if len(colors) == 1 and _COLOR.fullmatch(value) and normalize_color(colors[0]):
                add("color", normalize_color(colors[0]), origin, prop)
            elif len(lengths) == 1 and _LENGTH.fullmatch(value) and _length(*lengths[0]):
                add(_dimension_kind(hint), _length(*lengths[0]), origin, prop)
            elif "family" in hint.casefold() or ("," in value and not colors and "(" not in value):
                add("font-family", ", ".join(part.strip() for part in value.split(",")), origin, prop)
            else:
                add("other", f"{prop}: {value}", origin, prop)
            continue
        name = prop.casefold()
        if "var(" in value and not _COLOR.search(value) and not _LENGTH.search(value):
            continue
        for color in _COLOR.findall(value):
            normalized = normalize_color(color)
            if normalized:
                add("color", normalized, origin)
        if name == "font-size":
            for number, unit in _LENGTH.findall(value):
                if _length(number, unit):
                    add("font-size", _length(number, unit), origin)
        elif name == "font-family" and "var(" not in value:
            add("font-family", ", ".join(part.strip() for part in value.split(",")), origin)
        elif name.startswith(("margin", "padding")) or name in ("gap", "row-gap", "column-gap"):
            for number, unit in _LENGTH.findall(value):
                if _length(number, unit):
                    add("spacing", _length(number, unit), origin)
        elif name.endswith("radius"):
            for number, unit in _LENGTH.findall(value):
                if _length(number, unit):
                    add("radius", _length(number, unit), origin)


def _confidence(count: int, basis: str = "code") -> str:
    return "observed" if count >= 2 and basis != "preview" else "hypothesis"


def _capped(origins: list[str], limit: int = 20) -> list[str]:
    return list(dict.fromkeys(origins))[:limit]


def extract(root: Path, sources: list[Path], previews: list[Path] | None = None, today: date | None = None) -> dict:
    """Inventory React components, their variants and style token candidates, each tied to its origin."""
    today = today or clock.today()
    definitions, usages, tokens, variables = {}, {}, {}, {}
    modules, reexports = {}, []
    scanned = {"components": 0, "styles": 0}
    for base, path in _source_files(sources):
        name = path.name
        if any(marker in name for marker in (".stories.", ".test.", ".spec.")) or name.endswith(".d.ts"):
            continue
        if path.suffix not in (*_MODULE_SUFFIXES, ".css", ".scss") or path.stat().st_size > MAX_FILE_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        label = _file_label(root, base, path)
        if path.suffix in (".tsx", ".jsx"):
            scanned["components"] += 1
            _scan_components(label, path, text, definitions, usages, modules, reexports)
        elif path.suffix in (".ts", ".js"):
            _scan_reexports(path, text, reexports)
        else:
            scanned["styles"] += 1
            _scan_styles(label, path, text, tokens, variables)
    aliases = _aliases(definitions, modules, reexports)
    # A custom property counts once where it is defined and once per var() that uses it.
    for token in tokens.values():
        uses = variables.get(token.pop("variable", None), [])
        token["occurrences"] += len(uses)
        token["origins"].extend(uses)
    components, variants = [], {}
    for name, definition in sorted(definitions.items()):
        usage = _merged_usage([usages[tag] for tag in [name, *aliases.get(name, [])] if tag in usages])
        components.append({
            **definition, "children": definition["children"] or usage["with_children"] > 0,
            "usages": usage["count"], "origins": _capped(usage["origins"]),
            "confidence": _confidence(usage["count"]),
        })
        defaults = {prop["name"]: prop["default"] for prop in definition["props"] if "default" in prop}
        options = {prop["name"]: prop["options"] for prop in definition["props"] if "options" in prop}
        for origin, literals, given in usage["calls"]:
            found = []
            for prop, value in literals.items():
                if not _variant_prop(prop, options.get(prop)):
                    continue
                if value is True or (isinstance(value, str) and (
                        _VARIANT_VALUE.fullmatch(value) or
                        (value in options.get(prop, []) and _TYPED_VARIANT.fullmatch(value)))):
                    found.append((prop, value, "usage"))
            for prop, value in defaults.items():
                if prop not in given and _variant_prop(prop, options.get(prop)) and isinstance(value, str) \
                        and _VARIANT_VALUE.fullmatch(value):
                    found.append((prop, value, "default"))
            for prop, value, basis in found:
                key = f"{name}:{prop}={json.dumps(value)}"
                item = variants.setdefault(key, {
                    "key": key, "component": name, "props": {prop: value}, "occurrences": 0, "origins": [],
                    "basis": basis})
                item["occurrences"] += 1
                item["origins"].append(origin)
                if basis == "usage":
                    item["basis"] = "usage"
        # Values a typed string union allows, unseen in the scanned uses: states to confirm on the screens.
        for prop in definition["props"]:
            if not _variant_prop(prop["name"], prop.get("options")):
                continue
            for value in prop.get("options", []):
                key = f"{name}:{prop['name']}={json.dumps(value)}"
                if _TYPED_VARIANT.fullmatch(value) and key not in variants:
                    variants[key] = {
                        "key": key, "component": name, "props": {prop["name"]: value}, "occurrences": 0,
                        "origins": [_origin(definition["file"], definition["line"])],
                        "basis": "default" if prop.get("default") == value else "type"}
    for item in variants.values():
        item["origins"] = _capped(item["origins"])
        item["confidence"] = _confidence(item["occurrences"])
    aliased = {alias for names in aliases.values() for alias in names}
    external = [{"name": name, "usages": usage["count"]} for name, usage in sorted(usages.items())
                if name not in definitions and name not in aliased and len(name) > 1]
    token_list = []
    for token in sorted(tokens.values(), key=lambda item: (item["kind"], -item["occurrences"], item["key"])):
        token["origins"] = _capped(token["origins"])
        token["confidence"] = _confidence(token["occurrences"])
        token_list.append(token)
    inventory = {
        "schema_version": 1,
        "extracted": today.isoformat(),
        "sources": [_relative(root, path) for path in sources],
        "previews": [{"path": _relative(root, path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                     for path in previews or []],
        "scanned": scanned,
        "components": components,
        "variants": sorted(variants.values(), key=lambda item: item["key"]),
        "external_components": external,
        "tokens": token_list,
    }
    if any(item.startswith(OUTSIDE) for item in inventory["sources"]) or any(
            item["file"].startswith(OUTSIDE) for item in components):
        inventory["notes"] = [
            "A source outside the project is named outside:FOLDER/... by its folder name, because a path relative "
            "to the project would spell the home folder or the drive. generate writes no story for a component "
            "defined there: copy it into the project, or extract from a folder next to the project."]
    return inventory


def _screen(component: dict) -> bool:
    folders = set(component["file"].casefold().split("/")[:-1])
    return component["name"] == "App" or bool(folders & {"pages", "screens", "views", "routes"}) \
        or component["name"].endswith(("Page", "Screen", "View"))


def _variant_name(props: dict) -> str:
    words = []
    for prop, value in props.items():
        words.append(prop if value is True else str(value))
    return " ".join(word[:1].upper() + word[1:] for word in " ".join(words).replace("-", " ").split()) or "Default"


def _token_name(token: dict) -> str:
    group = TOKEN_GROUPS.get(token["kind"], "other")
    hint = token.get("name_hint")
    if hint:
        return f"{group}.{hint}"
    slug = re.sub(r"[^0-9a-z]+", "-", token["value"].casefold()).strip("-") or "value"
    return f"{group}.{slug[:40]}"


def _check_name(name: object, field: str) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip().splitlines()) != 1:
        raise ValueError(f"{field} needs a name on one line.")
    return name.strip()


def validate_proposals(data: dict) -> dict:
    """Check the proposals file the team edits: one status and one name per item."""
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not all(
            isinstance(data.get(field), list) for field in ("components", "variants", "tokens")):
        raise ValueError("Proposals need schema_version 1 and lists of components, variants and tokens.")
    keys = set()
    for field in ("components", "variants", "tokens"):
        for item in data[field]:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str) or item["key"] in keys:
                raise ValueError(f"Each item of {field} needs a unique key.")
            keys.add(item["key"])
            if item.get("status") not in STATUSES:
                raise ValueError(f"{item['key']}: status must be proposed, validated or rejected.")
            item["name"] = _check_name(item.get("name"), item["key"])
            if item.get("basis") == "preview":
                item["confidence"] = "hypothesis"
    for item in data["components"]:
        if item.get("export", "named") not in ("named", "default") or not (
                "public" not in item or (isinstance(item["public"], str) and _JS_IDENTIFIER.fullmatch(item["public"])
                                         and item["public"] != "default")):
            raise ValueError(f"{item['key']}: export is named or default, and public is the JavaScript name "
                             "the component is exported under.")
        if any(field in item and not isinstance(item[field], dict) for field in ("args", "sample_args")):
            raise ValueError(f"{item['key']}: args and sample_args must be objects.")
    components = {item["key"] for item in data["components"]}
    for item in data["variants"]:
        if item.get("component") not in components or not isinstance(item.get("props"), dict) or not all(
                isinstance(prop, str) and (value is None or isinstance(value, (str, int, float, bool)))
                for prop, value in item["props"].items()):
            raise ValueError(f"{item['key']}: a variant names one of the components and gives props with literal values.")
    for item in data["tokens"]:
        segments = item["name"].split(".")
        if any(not segment or segment.startswith("$") or "{" in segment or "}" in segment for segment in segments):
            raise ValueError(f"{item['key']}: a token name is a dotted path whose parts do not start with $ "
                             "and contain no braces.")
    validated = [item["name"] for item in data["tokens"] if item["status"] == "validated"]
    for name in validated:
        if validated.count(name) > 1 or any(other.startswith(name + ".") for other in validated):
            raise ValueError(f"Validated token {name} is used twice or is also a group.")
    return data


def propose(root: Path, state: Path, inventory_path: Path | None = None, proposals_path: Path | None = None) -> dict:
    """Write the proposals from the inventory. Decisions and names already in the file are kept."""
    inventory_path = inventory_path or state / INVENTORY
    proposals_path = proposals_path or state / PROPOSALS
    inventory = read_json(inventory_path)
    if inventory.get("schema_version") != 1:
        raise ValueError(f"{inventory_path} is not an OpenGuildKit Storybook inventory. Run storybook extract.")
    previous = validate_proposals(read_json(proposals_path)) if proposals_path.exists() else {
        "components": [], "variants": [], "tokens": []}
    fresh = {
        "components": [{
            "key": f"component:{item['name']}", "name": item["name"], "status": "proposed",
            "kind": "screen" if _screen(item) else "component", "confidence": item["confidence"],
            "file": item["file"], "line": item["line"], "export": item["export"], "usages": item["usages"],
            "children": item["children"], **({"public": item["public"]} if "public" in item else {}),
            "text_props": [prop["name"] for prop in item["props"]
                           if "default" not in prop and "sample" not in prop
                           and not prop.get("required") and prop["name"].casefold() in _SYNTHETIC_TEXT],
            "required_props": [prop["name"] for prop in item["props"] if prop.get("required")],
            "sample_args": {prop["name"]: prop["sample"] for prop in item["props"] if "sample" in prop},
        } for item in inventory["components"]],
        "variants": [{
            "key": f"variant:{item['key']}", "component": f"component:{item['component']}",
            "name": _variant_name(item["props"]), "props": item["props"], "status": "proposed",
            "confidence": item["confidence"], "basis": item["basis"], "occurrences": item["occurrences"],
            "origins": item["origins"],
        } for item in inventory["variants"]],
        "tokens": [{
            "key": f"token:{item['key']}", "kind": item["kind"], "value": item["value"], "name": _token_name(item),
            "status": "proposed", "confidence": item["confidence"], "occurrences": item["occurrences"],
            "origins": item["origins"],
        } for item in inventory["tokens"]],
    }
    decided = ("status", "name", "props", "args", "note")
    result = {"schema_version": 1, "inventory": {
        "path": _relative(root, inventory_path), "sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest()}}
    counts = {"new": 0, "kept": 0, "not_observed": 0}
    for field in ("components", "variants", "tokens"):
        earlier = {item["key"]: item for item in previous[field]}
        items = []
        for item in fresh[field]:
            if item["key"] in earlier:
                counts["kept"] += 1
                item.update({key: earlier[item["key"]][key] for key in decided if key in earlier[item["key"]]})
            else:
                counts["new"] += 1
            items.append(item)
        seen = {item["key"] for item in items}
        for key, item in earlier.items():
            if key not in seen:
                counts["not_observed"] += 1
                items.append({**item, "observed": False})
        result[field] = items
    validate_proposals(result)
    with project_lock(state):
        write_json(proposals_path, result)
    return {"proposals": _relative(root, proposals_path), **counts,
            "hypotheses": sum(item.get("confidence") == "hypothesis" for field in ("components", "variants", "tokens")
                              for item in result[field])}


def _color_value(value: str) -> dict:
    digits = value[1:]
    channels = [int(digits[index:index + 2], 16) for index in range(0, len(digits), 2)]
    color = {"colorSpace": "srgb", "components": [round(channel / 255, 4) for channel in channels[:3]],
             "hex": "#" + digits[:6]}
    if len(channels) == 4:
        color["alpha"] = round(channels[3] / 255, 4)
    return color


def _dtcg_token(item: dict) -> dict | None:
    """A validated token in the Design Tokens Format Module 2025.10."""
    kind, value = item["kind"], item["value"]
    if kind == "color" and re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", value):
        token = {"$type": "color", "$value": _color_value(value)}
    elif kind in ("spacing", "radius", "font-size", "dimension") and re.fullmatch(r"\d*\.?\d+(px|rem)", value):
        number = float(value[:-3] if value.endswith("rem") else value[:-2])
        token = {"$type": "dimension", "$value": {"value": int(number) if number.is_integer() else number,
                                                   "unit": "rem" if value.endswith("rem") else "px"}}
    elif kind == "font-family":
        token = {"$type": "fontFamily",
                 "$value": [part.strip().strip("'\"") for part in value.split(",") if part.strip()]}
    else:
        return None
    token["$description"] = f"Extracted from {item['occurrences']} occurrence(s) in the application."
    token["$extensions"] = {"org.openguildkit": {"origins": item["origins"], "confidence": item["confidence"]}}
    return token


def _identifier(name: str, taken: set) -> str:
    words = re.findall(r"[A-Za-z0-9]+", unicodedata.normalize("NFKD", name))
    identifier = "".join(word[:1].upper() + word[1:] for word in words) or "Story"
    if identifier[0].isdigit():
        identifier = "Story" + identifier
    candidate, number = identifier, 2
    while candidate in taken:
        candidate, number = f"{identifier}{number}", number + 1
    taken.add(candidate)
    return candidate


_JS_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _js_object(values: dict, indent: str) -> str:
    if not values:
        return "{}"
    lines = [f"{indent}  {key if _JS_IDENTIFIER.fullmatch(key) else _js(key)}: {_js(value)}," for key, value in values.items()]
    return "{\n" + "\n".join(lines) + f"\n{indent}}}"


def _import_path(out: Path, root: Path, file: str) -> str:
    target = (root / file).with_suffix("")
    relative = Path(os.path.relpath(target, out)).as_posix()
    return relative if relative.startswith(".") else f"./{relative}"


def _imported_as(component: dict) -> str:
    """The import clause that binds the component's name to what its module really exports."""
    name = component["key"].split(":", 1)[1]
    if component["export"] == "default":
        return f"{{ default as {name} }}"
    public = component.get("public", name)
    return f"{{ {public} }}" if public == name else f"{{ {public} as {name} }}"


def _story_args(component: dict) -> dict:
    samples = {prop: f"Sample {prop}" for prop in component.get("text_props", [])}
    if component.get("children") and "children" not in component.get("required_props", []):
        samples["children"] = component["name"]
    return {**samples, **component.get("sample_args", {}), **component.get("args", {})}


def _story_file(component: dict, variants: list[dict], args: dict, out: Path, root: Path, framework: str) -> str:
    name = component["key"].split(":", 1)[1]
    source = _js(_import_path(out, root, component["file"]))
    imported = f"import {name} from {source};" if component["export"] == "default" else \
        f"import {_imported_as(component)} from {source};"
    lines = [
        "// Generated by openguildkit storybook generate from the validated proposals.",
        "// Edit freely: once this file changes, generate leaves it as it is.",
        f"import type {{ Meta, StoryObj }} from {_js(framework)};",
        imported,
        "",
        "const meta = {",
        f"  title: {_js('Design system/' + component['name'])},",
        f"  component: {name},",
        f"  args: {_js_object(args, '  ')},",
        f"  parameters: {{ openguildkit: {{ definition: {_js(component['file'] + ':' + str(component['line']))} }} }},",
        f"}} satisfies Meta<typeof {name}>;",
        "export default meta;",
        "",
        "type Story = StoryObj<typeof meta>;",
    ]
    taken = {name}
    # Observed states first, then the hypotheses to confirm against the original screens.
    stories = sorted(variants, key=lambda item: (item["confidence"] != "observed", item["name"].casefold())) or [
        {"name": "Default", "props": {}, "origins": [], "confidence": component["confidence"], "basis": "usage"}]
    for variant in stories:
        parameters = {"origins": variant["origins"], "confidence": variant["confidence"], "basis": variant.get("basis")}
        lines.extend([
            "",
            f"export const {_identifier(variant['name'], taken)}: Story = {{",
            f"  name: {_js(variant['name'])},",
            f"  args: {_js_object(variant['props'], '  ')},",
            f"  parameters: {{ openguildkit: {_js(parameters)} }},",
            "};",
        ])
    return "\n".join(lines) + "\n"


def _setup_warnings(root: Path, framework: str) -> list[str]:
    warnings = []
    package = root / "package.json"
    dependencies = _project_dependencies(read_json(package)) if package.is_file() else {}
    missing = sorted({"storybook", framework} - dependencies.keys())
    if missing:
        warnings.append(f"Missing Storybook dependencies in package.json: {', '.join(missing)}.")
    if not any((root / ".storybook" / name).is_file() for name in MAIN_FILES):
        warnings.append("Missing Storybook configuration (.storybook/main.ts or .storybook/main.js).")
    if warnings:
        warnings.append(f"Set up the project first with npm create storybook@{STORYBOOK_VERSION}, "
                        "or add the missing settings to your existing Storybook.")
    return warnings


def generate(root: Path, state: Path, proposals_path: Path | None = None, out: Path | None = None,
             framework: str = "@storybook/react-vite") -> dict:
    """Write DTCG tokens, CSF3 stories and an index for the validated proposals only.

    A file the team changed since it was generated is never overwritten: its hash is kept in the manifest.
    """
    proposals = validate_proposals(read_json(proposals_path or state / PROPOSALS))
    root = root.resolve()
    out = (out or root / "src" / "design-system").resolve()
    if root not in (out, *out.parents):
        raise ValueError("Generate the design system inside the project.")
    components = {item["key"]: item for item in proposals["components"] if item["status"] == "validated"}
    files: dict[Path, str] = {}
    skipped = []
    warnings = []
    by_component: dict[str, list] = {key: [] for key in components}
    for variant in proposals["variants"]:
        if variant["status"] != "validated":
            continue
        if variant["component"] in by_component:
            by_component[variant["component"]].append(variant)
        else:
            skipped.append({"key": variant["key"], "reason": "its component is not validated"})
    names = [item["key"].split(":", 1)[1] for item in components.values()]
    if len(set(name.casefold() for name in names)) != len(names):
        raise ValueError("Two validated components share a name.")
    for key, component in components.items():
        if "file" not in component or "export" not in component:
            skipped.append({"key": key, "reason": "no definition in the application"})
            continue
        if component["file"].startswith(OUTSIDE):
            skipped.append({"key": key, "reason": f"defined outside the project ({component['file']}); copy it into "
                                                  "the project or extract from a folder next to it"})
            continue
        name = key.split(":", 1)[1]
        args = _story_args(component)
        variants = by_component[key]
        missing = [prop for prop in component.get("required_props", []) if prop not in args
                   and (not variants or any(prop not in variant["props"] for variant in variants))]
        if missing:
            warnings.append(f"{name}: add sample args for {', '.join(missing)} in the proposals or the story.")
        files[out / f"{name}.stories.tsx"] = _story_file(component, variants, args, out, root, framework)
    if files:
        warnings.extend(_setup_warnings(root, framework))
    tokens: dict = {}
    for item in proposals["tokens"]:
        if item["status"] != "validated":
            continue
        token = _dtcg_token(item)
        if token is None:
            skipped.append({"key": item["key"], "reason": "no Design Tokens type for this value"})
            continue
        group = tokens
        *parents, last = item["name"].split(".")
        for part in parents:
            group = group.setdefault(part, {})
        group[last] = token
    if tokens:
        files[out / "design.tokens.json"] = json_text(tokens)
    exported = [component for component in components.values()
                if "file" in component and not component["file"].startswith(OUTSIDE)]
    if exported:
        files[out / "index.ts"] = "// Generated by openguildkit storybook generate: the validated components.\n" + "".join(
            f"export {_imported_as(item)} from {_js(_import_path(out, root, item['file']))};\n" for item in exported)
    manifest_path = state / MANIFEST
    with project_lock(state):
        manifest = read_json(manifest_path) if manifest_path.exists() else {"schema_version": 1, "files": {}}
        result = {"written": [], "unchanged": [], "kept": [], "skipped": skipped}
        for path, content in sorted(files.items(), key=lambda item: item[0].as_posix()):
            relative = _relative(root, path)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if path.exists():
                current = hashlib.sha256(path.read_bytes()).hexdigest()
                if current == digest:
                    result["unchanged"].append(relative)
                    manifest["files"][relative] = digest
                    continue
                if manifest["files"].get(relative) != current:
                    result["kept"].append(relative)
                    continue
            write_text(path, content)
            manifest["files"][relative] = digest
            result["written"].append(relative)
        result["left"] = sorted(path for path in manifest["files"]
                                if path not in {_relative(root, item) for item in files} and (root / path).exists())
        write_json(manifest_path, manifest)
    if warnings:
        result["warnings"] = warnings
    return result


# Command line


def _print_compose(result: dict) -> list[str]:
    lines = [f"{result['file']}: " + (", ".join(f"{key} ({value['url']})" for key, value in result["refs"].items())
                                       or "no composed Storybook")]
    if result["main"] is None:
        lines.append(f"No Storybook main file was found. Create the project Storybook first, or start from this "
                     f"{result['minimal_main_file']}:")
        lines.extend(f"  {line}" if line else "" for line in result["minimal_main"].splitlines())
    elif not result["imported"]:
        lines.append(f"Add these lines to {result['main']}, then rebuild Storybook:")
        lines.extend(f"  {line}" for line in result["add_to_main"])
    return lines


def _print_import(report: dict) -> list[str]:
    lines = []
    for key in ("company", PROJECT_REF):
        if key in report:
            item = report[key]
            lines.append(f"{key.capitalize()} Storybook ({item['source']}): {len(item['components'])} titles, "
                         f"{item['stories']} stories.")
    if "matched" in report:
        lines.append(f"Matched components: {len(report['matched'])}.")
        lines.extend(f"- To map: {item['title']}" for item in report["to_map"])
        for kind, label in (("story_ids", "story ID"), ("titles", "title")):
            lines.extend(f"- Conflict, same {label} in both: {value}" for value in report["conflicts"][kind])
    for row in report.get("dependencies", []):
        if row["status"] != "ok":
            lines.append(f"- Dependency {row['status']}: {row['name']} {row['library']} in the library, "
                         f"{row.get('installed') or row['project'] or 'absent'} in the project"
                         + (" (styling)" if row["styling"] else ""))
    lines.extend(f"- Theme source: {item.get('title') or item.get('path')}" for item in report.get("themes", []))
    lines.append(f"Recorded the known stories in {report['record']}.")
    lines.extend(f"Warning: {warning}" for warning in report.get("warnings", []))
    return lines


def _print_extract(result: dict, output: str) -> list[str]:
    hypotheses = sum(item["confidence"] == "hypothesis" for field in ("components", "variants", "tokens")
                     for item in result[field])
    return [
        f"Scanned {result['scanned']['components']} component files and {result['scanned']['styles']} style files.",
        f"{len(result['components'])} components, {len(result['variants'])} variants, {len(result['tokens'])} "
        f"token candidates; {hypotheses} seen once are hypotheses.",
        f"Inventory written to {output}. Run openguildkit storybook propose next.",
    ]


def run(args, root: Path, state: Path) -> int | None:
    """The storybook subcommands."""
    if args.action == "compose":
        result = compose(root, args.ref, args.url, args.title, args.remove, args.config_dir)
        lines = _print_compose(result)
    elif args.action == "import":
        result = import_indexes(root, state, args.project_index, args.company_index, args.ref, args.library, args.package)
        lines = _print_import(result)
    elif args.action == "extract":
        result = extract(root, args.src, args.preview)
        output = args.output or state / INVENTORY
        with project_lock(state):
            write_json(output, result)
        lines = _print_extract(result, _relative(root, output))
    elif args.action == "propose":
        result = propose(root, state, args.inventory, args.proposals)
        lines = [f"{result['proposals']}: {result['new']} new, {result['kept']} kept with their decision, "
                 f"{result['not_observed']} no longer observed, {result['hypotheses']} hypotheses.",
                 "Set each status to validated or rejected and adjust the names, then run storybook generate."]
    elif args.action == "generate":
        result = generate(root, state, args.proposals, args.out, args.framework)
        lines = [f"Written: {path}" for path in result["written"]]
        lines += [f"Unchanged: {path}" for path in result["unchanged"]]
        lines += [f"Kept, changed by the team: {path}" for path in result["kept"]]
        lines += [f"No longer generated, left in place: {path}" for path in result["left"]]
        lines += [f"Skipped {item['key']}: {item['reason']}" for item in result["skipped"]]
        lines = lines or ["Nothing is validated yet."]
        lines.extend(f"Warning: {warning}" for warning in result.get("warnings", []))
    else:
        raise ValueError(f"Unknown storybook action {args.action}.")
    if args.json:
        print(json_text(result), end="")
    else:
        print("\n".join(lines))
    return None
