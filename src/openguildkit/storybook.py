"""Storybook for a project: reference the company's Storybook and compare it with the project's own.

The CLI never runs npm and never opens the network. It writes the refs file that the project's
.storybook/main imports, reads Storybook index.json files the team built or downloaded, and records
the known stories in .openguildkit/storybook.json so boards can cite a story and its state.
"""

import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from .storage import json_text, project_lock, read_json, write_json

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


def _relative(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


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
                         f"with npm create storybook@{STORYBOOK_VERSION}.")
    path = directory / REFS_FILE
    refs = read_json(path) if path.exists() else {}
    if any(not isinstance(item, dict) or not isinstance(item.get("url"), str) for item in refs.values()):
        raise ValueError(f"{path.name} is managed by openguildkit storybook compose and holds refs only.")
    if remove:
        if ref not in refs:
            raise ValueError(f"No composed Storybook named {ref} in {path.name}.")
        del refs[ref]
    else:
        if not isinstance(url, str) or not re.fullmatch(r"(https://[^\s]+|http://(localhost|127\.0\.0\.1)(:\d+)?(/[^\s]*)?)", url):
            raise ValueError("The composed Storybook needs an https URL, or http://localhost while testing.")
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


def import_indexes(root: Path, state: Path, project_index: Path | None = None, company_index: Path | None = None,
                   ref: str = "company", library: Path | None = None, package: Path | None = None,
                   today: date | None = None) -> dict:
    """Compare the company Storybook with the project's, report what to map, and record the known stories.

    Only .openguildkit/storybook.json is written: the project's stories and configuration stay as they are.
    """
    today = today or date.today()
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
    today = today or date.today()
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


# Command line


def _print_compose(result: dict) -> list[str]:
    lines = [f"{result['file']}: " + (", ".join(f"{key} ({value['url']})" for key, value in result["refs"].items())
                                       or "no composed Storybook")]
    if result["main"] is None:
        lines.append("No .storybook/main file was found. Create the project Storybook first.")
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
    return lines


def run(args, root: Path, state: Path) -> int | None:
    """The storybook subcommands."""
    if args.action == "compose":
        result = compose(root, args.ref, args.url, args.title, args.remove, args.config_dir)
        lines = _print_compose(result)
    elif args.action == "import":
        result = import_indexes(root, state, args.project_index, args.company_index, args.ref, args.library, args.package)
        lines = _print_import(result)
    else:
        raise ValueError(f"Unknown storybook action {args.action}.")
    if args.json:
        print(json_text(result), end="")
    else:
        print("\n".join(lines))
    return None
