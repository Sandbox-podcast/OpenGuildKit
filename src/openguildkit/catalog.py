"""Load and validate OpenGuildKit's declarative knowledge catalog."""

import json
import re
import unicodedata
from graphlib import CycleError, TopologicalSorter
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit


COLLECTION_FIELDS = {
    "packs": {"version", "rules"},
    "boards": {"expertises", "triggers", "questions"},
    "sectors": {"context"},
    "patterns": {"roles", "packs"},
}
ENTRY_FIELDS = {"id", "title", "description", "sources"}
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
MIN_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){0,3}")
EXPORT_EXPIRY_ID = "export-link-expiry"
MAX_SAFE_INTEGER = (1 << 53) - 1
# Query parameters that record how a visitor reached a page, never which page it is.
TRACKING_PARAMETERS = frozenset({
    "_hsenc", "_hsmi", "_src_ref", "dclid", "fbclid", "gbraid", "gclid", "igshid", "mc_cid",
    "mc_eid", "msclkid", "sitelocation", "trk", "visit_id", "wbraid", "yclid",
})


def is_positive_integer(value: Any) -> bool:
    return type(value) in (int, float) and 0 < value <= MAX_SAFE_INTEGER and int(value) == value


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
    if any(unicodedata.category(character) in ("Cc", "Cs", "Zl", "Zp") for character in value):
        raise CatalogError(f"{label} must be a single line of text without control characters")


def _validate_id(value: Any, label: str) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise CatalogError(f"{label} must use lowercase letters, digits, and hyphens")


def _validate_list(value: Any, label: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        requirement = "a JSON array" if allow_empty else "a non-empty JSON array"
        raise CatalogError(f"{label} must be {requirement}")


def tracking_parameters(url: str) -> list[str]:
    """Names of campaign, click or session parameters in a URL, and a copied text fragment."""
    parts = urlsplit(url)
    names = [name for name, _ in parse_qsl(parts.query, keep_blank_values=True)]
    found = [name for name in names if name.lower() in TRACKING_PARAMETERS or name.lower().startswith("utm_")]
    if parts.fragment.startswith(":~:"):
        found.append("#:~:text")
    return found


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
        tracking = tracking_parameters(url)
        if tracking:
            raise CatalogError(f"{label}.url carries the tracking parameter {tracking[0]!r}; link the page without it")
        if url in seen_urls:
            raise CatalogError(f"duplicate source URL {url!r}")
        seen_urls.add(url)


def _validate_pack(pack: dict[str, Any]) -> None:
    version = pack["version"]
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise CatalogError("version must use major.minor.patch")

    for field in ("depends_on", "conflicts_with"):
        identifiers = pack.get(field, [])
        _validate_list(identifiers, field, allow_empty=True)
        for identifier in identifiers:
            _validate_id(identifier, f"{field} entry")
        if len(set(identifiers)) != len(identifiers):
            raise CatalogError(f"{field} contains duplicate IDs")
        if pack["id"] in identifiers:
            raise CatalogError(f"{field} cannot name the pack itself")
    if set(pack.get("depends_on", [])) & set(pack.get("conflicts_with", [])):
        raise CatalogError("A pack cannot depend on a pack it conflicts with")

    _validate_list(pack["rules"], "rules")
    seen_ids = set()
    for index, rule in enumerate(pack["rules"]):
        label = f"rules[{index}]"
        if isinstance(rule, dict) and "check" in rule:
            _validate_fields(rule, label, {"id", "check"})
            check = rule["check"]
            _validate_fields(check, f"{label}.check", {"max_minutes"})
            if rule["id"] != EXPORT_EXPIRY_ID or not is_positive_integer(check["max_minutes"]):
                raise CatalogError(f"{label}: expected an {EXPORT_EXPIRY_ID} check with positive integer max_minutes")
        else:
            _validate_fields(rule, label, {"id", "instruction", "verification"})
            _validate_text(rule["instruction"], f"{label}.instruction")
            _validate_text(rule["verification"], f"{label}.verification")
        _validate_id(rule["id"], f"{label}.id")
        if rule["id"] in seen_ids:
            raise CatalogError(f"duplicate rule ID {rule['id']!r}")
        seen_ids.add(rule["id"])


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
    _validate_fields(match, "match", {"stack"}, {"sectors", "min_versions"})
    _validate_list(match["stack"], "match.stack")
    for group in match["stack"]:
        _validate_list(group, "technology aliases")
        for alias in group:
            _validate_text(alias, "technology alias")
            if not any(character.isalnum() for character in alias):
                raise CatalogError("Technology aliases must contain letters or digits")
    if "min_versions" in match:
        minimums = match["min_versions"]
        if not isinstance(minimums, dict) or not minimums:
            raise CatalogError("match.min_versions must be a non-empty JSON object")
        aliases = {alias for group in match["stack"] for alias in group}
        for alias, version in minimums.items():
            if alias not in aliases:
                raise CatalogError(f"match.min_versions names {alias!r}, which is not a stack alias")
            if not isinstance(version, str) or not MIN_VERSION_PATTERN.fullmatch(version):
                raise CatalogError(f"match.min_versions[{alias!r}] must be a version such as 13.4")
    if "sectors" in match:
        _validate_list(match["sectors"], "match.sectors")
        for sector in match["sectors"]:
            _validate_id(sector, "sector ID")


def _validate_board_review(review: Any) -> None:
    _validate_fields(review, "review", {"specialists", "evidence", "challenge", "decision_criteria"})
    _validate_list(review["specialists"], "review.specialists")
    seen = set()
    for specialist in review["specialists"]:
        _validate_fields(specialist, "specialist", {"id", "title", "focus"})
        specialist_id = specialist["id"]
        _validate_id(specialist_id, "specialist ID")
        if specialist_id in seen:
            raise CatalogError(f"Duplicate specialist: {specialist_id}")
        seen.add(specialist_id)
        _validate_text(specialist["title"], "specialist title")
        _validate_text(specialist["focus"], "specialist focus")
    for key in ("evidence", "challenge", "decision_criteria"):
        _validate_list(review[key], f"review.{key}")
        for prompt in review[key]:
            _validate_text(prompt, f"review.{key} entry")


def _validate_entry(collection: str, entry: Any) -> None:
    required = ENTRY_FIELDS | COLLECTION_FIELDS[collection]
    optional = {
        "packs": {"depends_on", "conflicts_with"},
        "patterns": {"match", "exclusive_group"},
        "boards": {"review"},
    }.get(collection)
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
    if collection == "boards" and "review" in entry:
        _validate_board_review(entry["review"])
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
        unknown = sorted(set(packs[pack_id].get("conflicts_with", [])) - packs.keys())
        if unknown:
            raise CatalogError(f"pack {pack_id!r} conflicts with unknown packs: {', '.join(unknown)}")
    try:
        TopologicalSorter(graph).prepare()
    except CycleError as exc:
        raise CatalogError(f"pack dependency cycle: {' -> '.join(exc.args[1])}") from exc


def load_catalog(
    extra_dir: Path | None = None, *, central_policy: tuple[str, dict] | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
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
                    if path.name != f"{record_id}.json":
                        raise CatalogError(f"name the file {record_id}.json after its id")
                except RecursionError as exc:
                    raise CatalogError(f"{path}: JSON nested too deeply") from exc
                except (OSError, ValueError) as exc:
                    raise CatalogError(f"{path}: {exc}") from exc
                entries[record_id] = entry
            if root == builtin and not entries:
                raise CatalogError(f"{directory} has no bundled records")
        catalog[collection] = dict(sorted(entries.items()))

    if central_policy is not None:
        commit, pack = central_policy
        _validate_entry("packs", pack)
        rules = pack["rules"]
        if pack["id"] != EXPORT_EXPIRY_ID or len(rules) != 1 or "check" not in rules[0]:
            raise CatalogError(f"The central policy must contain one executable {EXPORT_EXPIRY_ID} rule")
        if EXPORT_EXPIRY_ID in catalog["packs"]:
            raise CatalogError(f"duplicate packs ID {EXPORT_EXPIRY_ID!r}")
        catalog["packs"][EXPORT_EXPIRY_ID] = {**pack, "policy_commit": commit}
        catalog["packs"] = dict(sorted(catalog["packs"].items()))

    _validate_dependencies(catalog["packs"])
    for pattern_id, pattern in catalog["patterns"].items():
        unknown_packs = set(pattern["packs"]) - catalog["packs"].keys()
        if unknown_packs:
            raise CatalogError(f"Pattern {pattern_id!r} links unknown packs: {', '.join(sorted(unknown_packs))}")
        unknown_sectors = set(pattern.get("match", {}).get("sectors", [])) - catalog["sectors"].keys()
        if unknown_sectors:
            raise CatalogError(f"Pattern {pattern_id!r} links unknown sectors: {', '.join(sorted(unknown_sectors))}")
    return catalog
