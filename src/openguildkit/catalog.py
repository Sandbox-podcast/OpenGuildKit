"""Load and validate OpenGuildKit's declarative knowledge catalog."""

import json
import re
from graphlib import CycleError, TopologicalSorter
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


COLLECTION_FIELDS = {
    "packs": {"version", "rules"},
    "boards": {"expertises", "triggers", "questions"},
    "sectors": {"context"},
    "patterns": {"roles", "packs"},
}
ENTRY_FIELDS = {"id", "title", "description", "sources"}
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


class CatalogError(ValueError):
    """A catalog record or dependency is invalid."""


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _validate_fields(
    value: Any, label: str, required: set[str], optional: set[str] | None = None
) -> None:
    if not isinstance(value, dict):
        raise CatalogError(f"{label} must be a JSON object")
    missing = required - value.keys()
    extra = value.keys() - required - (optional or set())
    if missing:
        raise CatalogError(f"{label} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise CatalogError(f"{label} has unknown fields: {', '.join(sorted(extra))}")


def _validate_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{label} must be a non-empty string")
    if any(ord(character) < 32 or 0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CatalogError(f"{label} must be a single line of text")


def _validate_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise CatalogError(f"{label} must use lowercase letters, digits, and hyphens")


def _validate_list(value: Any, label: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        requirement = "a JSON array" if allow_empty else "a non-empty JSON array"
        raise CatalogError(f"{label} must be {requirement}")


def _validate_sources(sources: Any) -> None:
    _validate_list(sources, "sources", allow_empty=True)
    seen_urls = set()
    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        _validate_fields(source, label, {"title", "url"})
        _validate_text(source["title"], f"{label}.title")
        url = source["url"]
        _validate_text(url, f"{label}.url")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
            raise CatalogError(f"{label}.url must be an HTTPS URL without credentials")
        if any(character.isspace() or character in "<>\\" for character in url):
            raise CatalogError(f"{label}.url contains invalid characters")
        if url in seen_urls:
            raise CatalogError(f"duplicate source URL {url!r}")
        seen_urls.add(url)


def _validate_pack(pack: dict[str, Any]) -> None:
    version = pack["version"]
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise CatalogError("version must use major.minor.patch")

    dependencies = pack.get("depends_on", [])
    _validate_list(dependencies, "depends_on", allow_empty=True)
    for dependency in dependencies:
        _validate_id(dependency, "depends_on entry")
    if len(set(dependencies)) != len(dependencies):
        raise CatalogError("depends_on contains duplicate IDs")

    _validate_list(pack["rules"], "rules")
    seen_ids = set()
    for index, rule in enumerate(pack["rules"]):
        label = f"rules[{index}]"
        _validate_fields(rule, label, {"id", "instruction", "verification"})
        _validate_id(rule["id"], f"{label}.id")
        if rule["id"] in seen_ids:
            raise CatalogError(f"duplicate rule ID {rule['id']!r}")
        seen_ids.add(rule["id"])
        _validate_text(rule["instruction"], f"{label}.instruction")
        _validate_text(rule["verification"], f"{label}.verification")


def _validate_pattern(pattern: dict[str, Any]) -> None:
    for key in ("roles", "packs"):
        identifiers = pattern[key]
        _validate_list(identifiers, key)
        for item in identifiers:
            _validate_id(item, f"{key} entry")
        if len(identifiers) != len(set(identifiers)):
            raise CatalogError(f"{key} contains duplicate IDs")
    if "exclusive_group" in pattern:
        _validate_id(pattern["exclusive_group"], "exclusive_group")
    if "match" not in pattern:
        return
    match = pattern["match"]
    _validate_fields(match, "match", {"stack"}, {"sectors"})
    _validate_list(match["stack"], "match.stack")
    for group in match["stack"]:
        _validate_list(group, "technology aliases")
        for alias in group:
            _validate_text(alias, "technology alias")
            if not any(character.isalnum() for character in alias):
                raise CatalogError("Technology aliases must contain letters or digits")
    if "sectors" in match:
        _validate_list(match["sectors"], "match.sectors")
        for sector in match["sectors"]:
            _validate_id(sector, "sector ID")


def _validate_entry(collection: str, entry: Any) -> None:
    required = ENTRY_FIELDS | COLLECTION_FIELDS[collection]
    optional = {"packs": {"depends_on"}, "patterns": {"match", "exclusive_group"}}.get(collection)
    _validate_fields(entry, "record", required, optional)
    _validate_id(entry["id"], "id")
    _validate_text(entry["title"], "title")
    _validate_text(entry["description"], "description")
    _validate_sources(entry["sources"])
    if collection == "packs":
        _validate_pack(entry)
        return
    if collection == "patterns":
        _validate_pattern(entry)
        return
    for field in sorted(COLLECTION_FIELDS[collection]):
        _validate_list(entry[field], field)
        for index, item in enumerate(entry[field]):
            _validate_text(item, f"{field}[{index}]")


def _validate_dependencies(packs: dict[str, dict[str, Any]]) -> None:
    graph = {pack_id: pack.get("depends_on", []) for pack_id, pack in packs.items()}
    for pack_id, dependencies in graph.items():
        missing = sorted(set(dependencies) - packs.keys())
        if missing:
            raise CatalogError(f"pack {pack_id!r} requires unknown packs: {', '.join(missing)}")
    try:
        TopologicalSorter(graph).prepare()
    except CycleError as exc:
        raise CatalogError(f"pack dependency cycle: {' -> '.join(exc.args[1])}") from exc


def load_catalog(extra_dir: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    """Load bundled records and optional project additions, ordered by ID."""
    builtin = files("openguildkit").joinpath("registry")
    roots = [builtin]
    if extra_dir is not None and extra_dir.exists():
        if not extra_dir.is_dir():
            raise CatalogError(f"{extra_dir} must be a directory")
        roots.append(extra_dir)

    catalog: dict[str, dict[str, dict[str, Any]]] = {}
    for collection in COLLECTION_FIELDS:
        entries = {}
        for root in roots:
            directory = root.joinpath(collection)
            if not directory.is_dir():
                if root == builtin or directory.is_file():
                    raise CatalogError(f"{directory} must be a directory")
                continue
            for path in sorted(directory.iterdir(), key=lambda item: item.name):
                if not path.name.endswith(".json"):
                    continue
                try:
                    entry = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_fields)
                    _validate_entry(collection, entry)
                    record_id = entry["id"]
                    if record_id in entries:
                        raise CatalogError(f"duplicate {collection} ID {record_id!r}")
                except (OSError, ValueError) as exc:
                    raise CatalogError(f"{path}: {exc}") from exc
                entries[record_id] = entry
            if root == builtin and not entries:
                raise CatalogError(f"{directory} has no bundled records")
        catalog[collection] = dict(sorted(entries.items()))

    _validate_dependencies(catalog["packs"])
    for pattern_id, pattern in catalog["patterns"].items():
        unknown_packs = set(pattern["packs"]) - catalog["packs"].keys()
        if unknown_packs:
            raise CatalogError(f"Pattern {pattern_id!r} links unknown packs: {', '.join(sorted(unknown_packs))}")
        unknown_sectors = set(pattern.get("match", {}).get("sectors", [])) - catalog["sectors"].keys()
        if unknown_sectors:
            raise CatalogError(f"Pattern {pattern_id!r} links unknown sectors: {', '.join(sorted(unknown_sectors))}")
    return catalog
