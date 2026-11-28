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
from .detect import walk
from .sensitive import refuse_link_credentials
from .stack_versions import STORYBOOK_VERSION, lower_bounds, parse_range, parse_version, satisfies, version_text
from .storage import file_sha256, json_text, project_lock, read_json, write_json, write_text
from .wording import plural

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


def committed_path(root: Path, path: Path) -> str:
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


# Dependencies of the company library against the project's.


def project_dependencies(package: dict) -> dict:
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
    project = project_dependencies(package)
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
                declared = parse_range(project[name])
                versions = [parse_version(installed)] if installed else (lower_bounds(declared) if declared else None)
                if not versions:
                    row["status"] = "unknown"
                else:
                    results = [satisfies(version, ranges) for version in versions]
                    compatible = "ok" if all(results) else "partial" if any(results) else None
                    row["status"] = compatible or ("conflict" if kind == "peer" else "duplicate")
                    row["checked"] = [version_text(version) for version in versions]
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
    refuse_link_credentials(url, "The composed Storybook URL")


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
    result = {"file": committed_path(root, path), "refs": refs, "main": committed_path(root, main) if main else None,
              "imported": imported}
    if main is None:
        result["minimal_main"] = MINIMAL_MAIN
        result["minimal_main_file"] = committed_path(root, directory / "main.ts")
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
        "source": committed_path(root, path),
        "sha256": file_sha256(path),
        "recorded": today.isoformat(),
        "stories": [{"id": item["id"], "title": item["title"], "name": item["name"]}
                    for item in entries if item["type"] == "story"],
    }


def source_files(sources: list[Path]):
    """Each source file with the folder given for it, in POSIX path order on every system.

    A folder is walked as every walk of the project is: dependencies, builds and caches are skipped.
    """
    for base in sources:
        base = base.resolve()
        if base.is_file():
            yield base.parent, base
        elif base.is_dir():
            files = [folder / name for folder, _, names, _ in walk(base) for name in names]
            for path in sorted(files, key=lambda item: item.as_posix()):
                yield base, path
        else:
            raise ValueError(f"No such file or folder: {base.name}. Give a --src path that exists.")


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
    files.update(path for _, path in source_files(project_folders))
    for path in sorted(files):
        if path.suffix in (*MODULE_SUFFIXES, ".mdx", ".css", ".scss") and root in path.resolve().parents \
                and path.stat().st_mtime_ns > built_at:
            return path
    return None


def import_indexes(root: Path, state: Path, project_index: Path | None = None, company_index: Path | None = None,
                   ref: str = "company", library: Path | None = None, package: Path | None = None,
                   today: date | None = None) -> dict:
    """Compare the company Storybook with the project's, report what to map, and record the known stories.

    Only .openguildkit/storybook.json is written: the project's stories and configuration stay as they are. The day
    an index is recorded is the real one, from which its age is counted.
    """
    today = today or clock.real_today()
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
                "ref": name, "source": committed_path(root, path),
                "components": [{key: item[key] for key in ("title", "stories", "docs")} for item in components(entries)],
                "stories": sum(item["type"] == "story" for item in entries),
            }
    if PROJECT_REF in indexes:
        path, entries = indexes[PROJECT_REF]
        newer = _newer_story_source(root, path, entries)
        if newer is not None:
            report["warnings"] = [
                f"{committed_path(root, newer)} is newer than {committed_path(root, path)}. "
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
    report["record"] = committed_path(root, state / RECORD)
    return report


def scope_entry(state: Path, today: date | None = None) -> dict | None:
    """What a consultation carries when the project has recorded a Storybook index: the story IDs boards can cite."""
    record = load_record(state)
    if not record:
        return None
    today = today or clock.real_today()
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


# The design system drawn from an existing application: storybook_extract writes the inventory, propose the
# proposals a person validates, and generate the files.

INVENTORY = "storybook/inventory.json"
PROPOSALS = "storybook/proposals.json"
MANIFEST = "storybook/generated.json"
STATUSES = ("proposed", "validated", "rejected")
MODULE_SUFFIXES = (".tsx", ".jsx", ".ts", ".js")
_SYNTHETIC_TEXT = {"label", "title", "text", "heading", "placeholder", "description", "name", "caption", "message"}
TOKEN_GROUPS = {"color": "color", "spacing": "spacing", "radius": "radius", "font-size": "font-size",
                "font-family": "font-family", "dimension": "dimension"}
# How a CSS variable usually starts when it names a token of that kind: the group already says it.
TOKEN_PREFIXES = {
    "color": ("color-", "colour-", "clr-"), "spacing": ("spacing-", "space-", "sp-"),
    "radius": ("radius-", "radii-", "rounded-"), "font-size": ("font-size-", "fs-", "font-"),
    "font-family": ("font-family-", "ff-", "font-"), "dimension": ("dimension-", "size-"),
}


def _screen(component: dict) -> bool:
    folders = set(component["file"].casefold().split("/")[:-1])
    return component["name"] == "App" or bool(folders & {"pages", "screens", "views", "routes"}) \
        or component["name"].endswith(("Page", "Screen", "View"))


def story_name(name: str, component: str, props: dict, basis: str | None) -> str:
    """A story is named for the state it shows; one named like its component is its default state."""
    if name.casefold() != component.casefold():
        return name
    if basis == "default" or not props:
        return "Default"
    return " ".join(word[:1].upper() + word[1:] for word in [*props][:1] + [name])


def _variant_name(props: dict) -> str:
    words = []
    for prop, value in props.items():
        if value is False:
            words.append("not " + re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", prop))
        else:
            words.append(prop if value is True else str(value))
    return " ".join(word[:1].upper() + word[1:] for word in " ".join(words).replace("-", " ").split()) or "Default"


def _token_name(token: dict, short: bool = True) -> str:
    """The token's path: its group, then its CSS variable's name without the group it repeats, or its value."""
    group = TOKEN_GROUPS.get(token["kind"], "other")
    hint = token.get("name_hint")
    if hint:
        prefix = next((item for item in TOKEN_PREFIXES.get(token["kind"], ()) if hint.startswith(item)), "")
        if short and prefix and len(hint) > len(prefix):
            hint = hint[len(prefix):]
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
                "public" not in item or (isinstance(item["public"], str) and JS_IDENTIFIER.fullmatch(item["public"])
                                         and item["public"] != "default")):
            raise ValueError(f"{item['key']}: export is named or default, and public is the JavaScript name "
                             "the component is exported under.")
        if any(field in item and not isinstance(item[field], dict) for field in ("args", "sample_args")):
            raise ValueError(f"{item['key']}: args and sample_args must be objects.")
        callbacks = item.get("callback_props", [])
        if not isinstance(callbacks, list) or not all(isinstance(prop, str) and prop for prop in callbacks):
            raise ValueError(f"{item['key']}: callback_props lists prop names.")
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
    short = [_token_name(item) for item in inventory["tokens"]]
    # Two variables that shorten to the same name keep their whole names, so each token keeps its own.
    token_names = {item["key"]: name if short.count(name) == 1 else _token_name(item, short=False)
                   for item, name in zip(inventory["tokens"], short)}
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
            "callback_props": [prop["name"] for prop in item["props"] if prop.get("callback")],
        } for item in inventory["components"]],
        "variants": [{
            "key": f"variant:{item['key']}", "component": f"component:{item['component']}",
            "name": story_name(_variant_name(item["props"]), item["component"], item["props"], item["basis"]),
            "props": item["props"], "status": "proposed",
            "confidence": item["confidence"], "basis": item["basis"], "occurrences": item["occurrences"],
            "origins": item["origins"],
        } for item in inventory["variants"]],
        "tokens": [{
            "key": f"token:{item['key']}", "kind": item["kind"], "value": item["value"], "name": token_names[item["key"]],
            "status": "proposed", "confidence": item["confidence"], "occurrences": item["occurrences"],
            "origins": item["origins"],
        } for item in inventory["tokens"]],
    }
    decided = ("status", "name", "props", "args", "note")
    result = {"schema_version": 1, "inventory": {
        "path": committed_path(root, inventory_path), "sha256": file_sha256(inventory_path)}}
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
    return {"proposals": committed_path(root, proposals_path), **counts,
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
    token["$description"] = f"Extracted from {plural(item['occurrences'], 'occurrence')} in the application."
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


JS_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class _Code(str):
    """A fixed piece of TypeScript written as is in a story, such as a callback that does nothing."""


NO_OP = _Code("() => {}")


def _js_object(values: dict, indent: str) -> str:
    if not values:
        return "{}"
    lines = [f"{indent}  {key if JS_IDENTIFIER.fullmatch(key) else _js(key)}: "
             f"{value if isinstance(value, _Code) else _js(value)}," for key, value in values.items()]
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
    callbacks = {prop: NO_OP for prop in component.get("callback_props", [])}
    return {**samples, **callbacks, **component.get("sample_args", {}), **component.get("args", {})}


def _story_file(component: dict, variants: list[dict], args: dict, out: Path, root: Path, framework: str) -> str:
    name = component["key"].split(":", 1)[1]
    source = _js(_import_path(out, root, component["file"]))
    binding = name if component["export"] == "default" else _imported_as(component)
    types = _js(framework)
    lines = [
        "// Generated by openguildkit storybook generate from the validated proposals.",
        "// Edit freely: once this file changes, generate leaves it as it is.",
        f"import type {{ Meta, StoryObj }} from {types};",
        f"import {binding} from {source};",
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
        story = story_name(variant["name"], name, variant["props"], variant.get("basis"))
        lines.extend([
            "",
            f"export const {_identifier(story, taken)}: Story = {{",
            f"  name: {_js(story)},",
            f"  args: {_js_object(variant['props'], '  ')},",
            f"  parameters: {{ openguildkit: {_js(parameters)} }},",
            "};",
        ])
    return "\n".join(lines) + "\n"


# Storybook framework packages for React, in the order a project that lists several is read.
REACT_FRAMEWORKS = ("@storybook/nextjs-vite", "@storybook/nextjs", "@storybook/react-vite", "@storybook/react-webpack5")


def detect_framework(root: Path) -> str:
    """The Storybook framework package the stories import: the one package.json lists, else one for its stack."""
    package = root / "package.json"
    dependencies = project_dependencies(read_json(package)) if package.is_file() else {}
    listed = [name for name in REACT_FRAMEWORKS if name in dependencies]
    if listed:
        return listed[0]
    return "@storybook/nextjs-vite" if "next" in dependencies else "@storybook/react-vite"


def _setup_warnings(root: Path, framework: str) -> list[str]:
    warnings = []
    package = root / "package.json"
    dependencies = project_dependencies(read_json(package)) if package.is_file() else {}
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
             framework: str | None = None) -> dict:
    """Write DTCG tokens, CSF3 stories and an index for the validated proposals only.

    A file the team changed since it was generated is never overwritten: its hash is kept in the manifest.
    """
    proposals = validate_proposals(read_json(proposals_path or state / PROPOSALS))
    root = root.resolve()
    framework = framework or detect_framework(root)
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
        result = {"framework": framework, "written": [], "unchanged": [], "kept": [], "skipped": skipped}
        for path, content in sorted(files.items(), key=lambda item: item[0].as_posix()):
            relative = committed_path(root, path)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if path.exists():
                current = file_sha256(path)
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
                                if path not in {committed_path(root, item) for item in files} and (root / path).exists())
        write_json(manifest_path, manifest)
    if warnings:
        result["warnings"] = warnings
    return result
