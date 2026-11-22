"""Load and validate OpenGuildKit's declarative knowledge catalog."""

import copy
import json
import re
import unicodedata
from datetime import date
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .rule_checks import validate_check


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
LEGACY_EXPORT_CHECK = {"kind": "field", "path": "export.json", "field": "downloadLinkMinutes", "integer": True, "min": 1}
MAX_EVIDENCE = 5
# The answers to a task's data question, which a named evidence can apply to.
DATA_ANSWERS = ("none", "internal", "personal", "regulated", "unsure")
# A method is preselected for its roles; a regulation only for its sectors or personal data.
PATTERN_KINDS = ("method", "regulation")
MAX_SAFE_INTEGER = (1 << 53) - 1
CHECKED_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
UNDATED_SOURCE = (
    "{label}.checked is missing: open the page, check what the record says against it, "
    'then add "checked": "YYYY-MM-DD" with that day\'s date after its url'
)
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
    # Printable text has no control, surrogate or line separator: only other text needs the slow check.
    forbidden = ("Cc", "Cs", "Zl", "Zp")
    if not value.isprintable() and any(unicodedata.category(character) in forbidden for character in value):
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


def _validate_checked(value: Any, label: str) -> None:
    """A source's verification day: an ISO date such as 2026-11-21."""
    try:
        if not isinstance(value, str) or not CHECKED_PATTERN.fullmatch(value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise CatalogError(f"{label} must be a date written YYYY-MM-DD, such as 2026-11-21") from None


def _validate_sources(sources: Any, *, require_checked: bool = False) -> None:
    """Bundled sources must carry the day they were last checked; a project's own sources may not yet."""
    _validate_list(sources, "sources", allow_empty=True)
    seen_urls = set()
    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        _validate_fields(source, label, {"title", "url"}, {"checked"})
        if "checked" in source:
            _validate_checked(source["checked"], f"{label}.checked")
        elif require_checked:
            raise CatalogError(UNDATED_SOURCE.format(label=label))
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


def _validate_pack(pack: dict[str, Any], allow_command: bool = False) -> None:
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
        _validate_rule(rule, label, allow_command)
        if rule["id"] in seen_ids:
            raise CatalogError(f"duplicate rule ID {rule['id']!r}")
        seen_ids.add(rule["id"])


def rule_check(rule: dict) -> dict | None:
    """The machine check a rule declares, with the former central export form written out."""
    check = rule.get("check")
    if check is None or "kind" in check:
        return check
    # Central policy packs written before generic checks: {"max_minutes": N} on the export rule.
    return {**LEGACY_EXPORT_CHECK, "max": check["max_minutes"]}


def recorded_value(task: dict, check_id: str, item: dict | None = None) -> dict:
    """The value a rule's `records` asks a task to write in its result, such as an agreed threshold.

    Without item, the fields the result template shows for the check. With item, a reported outcome:
    a passed or failed check of such a rule carries the value with its unit, which is returned to keep.
    """
    name = check_id[len("rule:"):] if check_id.startswith("rule:") else ""
    pack_id, _, rule_id = name.partition("/")
    packs = task.get("consultation", {}).get("scope", {}).get("packs", [])
    rules = [rule for pack in packs if pack["id"] == pack_id for rule in pack["rules"] if rule["id"] == rule_id]
    records = rules[0].get("records") if rules else None
    if records is None:
        return {}
    if item is None:
        bounds = bounds_text(records)
        accepted = f" Write a number {bounds}, with its unit." if bounds else " Write a number with its unit."
        return {"records": f"{records['name']}: {records['description']}{accepted}", "value": ""}
    if item.get("status") not in ("passed", "failed"):
        return {}
    value = item.get("value")
    if not isinstance(value, str) or not re.search(r"[0-9]", value) or not re.search(r"[^0-9\s.,+-]", value):
        raise ValueError(
            f"{check_id} records the {records['name']}: write it in value, a number with its unit "
            f"such as \"90 % of cases\" ({records['description']})."
        )
    problem = _out_of_bounds(records, value)
    if problem:
        raise ValueError(f"{check_id} records the {records['name']}: {problem} ({records['description']}).")
    return {"value": " ".join(value.split())}


_NUMBER = re.compile(r"(?<![\w.])[-+]?[0-9]+(?:[.,][0-9]+)?")
BOUND_FIELDS = ("min", "above", "max")


def bounds_text(records: dict) -> str:
    """The range a recorded value accepts, in words: 'above 0 and at most 100'."""
    parts = []
    if "min" in records:
        parts.append(f"at least {records['min']}")
    if "above" in records:
        parts.append(f"above {records['above']}")
    if "max" in records:
        parts.append(f"at most {records['max']}")
    return " and ".join(parts)


def _out_of_bounds(records: dict, value: str) -> str | None:
    """Why the number of a recorded value falls outside the bounds its rule declares, or None."""
    if not any(field in records for field in BOUND_FIELDS):
        return None
    match = _NUMBER.search(value)
    number = float(match.group(0).replace(",", ".")) if match else None
    if number is None or ("min" in records and number < records["min"]) or (
            "above" in records and number <= records["above"]) or ("max" in records and number > records["max"]):
        return f"{value.strip()!r} is out of range: write a number {bounds_text(records)}, with its unit"
    return None


def _validate_records(records: Any, label: str) -> None:
    """The value a task records: a name, a description and optional bounds on its number."""
    _validate_fields(records, label, {"name", "description"}, set(BOUND_FIELDS))
    _validate_id(records["name"], f"{label} name")
    _validate_text(records["description"], f"{label} description")
    for field in BOUND_FIELDS:
        if field in records and (type(records[field]) not in (int, float) or abs(records[field]) > MAX_SAFE_INTEGER):
            raise CatalogError(f"{label}.{field} must be a number")
    if "min" in records and "above" in records:
        raise CatalogError(f"{label} sets min or above, not both")
    low = records.get("min", records.get("above"))
    if low is not None and "max" in records and low >= records["max"]:
        raise CatalogError(f"{label}.max must be greater than its lower bound")


def _validate_evidence(evidence: Any, label: str) -> None:
    _validate_list(evidence, f"{label}.evidence")
    if len(evidence) > MAX_EVIDENCE:
        raise CatalogError(f"{label}.evidence names at most {MAX_EVIDENCE} pieces of evidence")
    seen = set()
    for item in evidence:
        _validate_fields(item, f"{label}.evidence entry", {"id", "title"}, {"when"})
        _validate_id(item["id"], f"{label}.evidence id")
        _validate_text(item["title"], f"{label}.evidence title")
        if "when" in item:
            _validate_fields(item["when"], f"{label}.evidence when", {"data"})
            values = item["when"]["data"]
            _validate_list(values, f"{label}.evidence when.data")
            known = [value for value in values if isinstance(value, str) and value in DATA_ANSWERS]
            if len(known) != len(values) or len(set(known)) != len(known):
                raise CatalogError(f"{label}.evidence when.data lists distinct answers among {', '.join(DATA_ANSWERS)}")
        if item["id"] in seen:
            raise CatalogError(f"{label}.evidence names {item['id']!r} twice")
        seen.add(item["id"])


def _validate_rule(rule: Any, label: str, allow_command: bool) -> None:
    """A rule states an instruction and its verification; a machine check can stand in for both.

    A rule without a check may say in `manual` why only a person can verify it, such as a record kept outside
    the repository or a behaviour that shows only in a running system.
    """
    _validate_fields(rule, label, {"id"}, {"instruction", "verification", "check", "evidence", "records", "manual"})
    if "manual" in rule:
        _validate_text(rule["manual"], f"{label}.manual")
        if "check" in rule:
            raise CatalogError(f"{label} carries a check, which task verify evaluates: remove its manual reason")
    _validate_id(rule["id"], f"{label}.id")
    if "check" in rule and isinstance(rule["check"], dict) and rule["check"].keys() == {"max_minutes"}:
        if rule["id"] != EXPORT_EXPIRY_ID or not is_positive_integer(rule["check"]["max_minutes"]):
            raise CatalogError(f"{label}: expected an {EXPORT_EXPIRY_ID} check with positive integer max_minutes")
    elif "check" in rule:
        try:
            validate_check(rule["check"], f"{label}.check", allow_command=allow_command)
        except ValueError as error:
            raise CatalogError(str(error)) from error
    for field in ("instruction", "verification"):
        if field in rule:
            _validate_text(rule[field], f"{label}.{field}")
        elif "check" not in rule:
            raise CatalogError(f"{label} is missing fields: {field}")
    if "evidence" in rule:
        _validate_evidence(rule["evidence"], label)
    if "records" in rule:
        _validate_records(rule["records"], f"{label}.records")


def _validate_core_roles(pattern: dict[str, Any]) -> None:
    """core_for names roles of the pattern for which a method without a match is preselected."""
    _validate_list(pattern["core_for"], "core_for")
    roles = pattern["core_for"]
    if not set(roles) <= set(pattern["roles"]) or len(set(roles)) != len(roles):
        raise CatalogError("core_for must list distinct roles of the pattern")
    if pattern.get("kind", "method") != "method" or "match" in pattern:
        raise CatalogError("core_for applies to a method without a match; a regulation is never preselected by a role")


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
    if "core_for" in pattern:
        _validate_core_roles(pattern)
    if "references" in pattern:
        _validate_list(pattern["references"], "references")
        for reference_id in pattern["references"]:
            _validate_id(reference_id, "references entry")
        if len(set(pattern["references"])) != len(pattern["references"]):
            raise CatalogError("references contains duplicate IDs")
    if pattern.get("kind", "method") not in PATTERN_KINDS:
        raise CatalogError(f"kind must be one of {', '.join(PATTERN_KINDS)}")
    if "match" not in pattern:
        return
    match = pattern["match"]
    _validate_fields(match, "match", set(), {"stack", "sectors", "min_versions", "personal_data", "people_decisions"})
    if not match.keys() & {"stack", "sectors", "personal_data", "people_decisions"}:
        raise CatalogError("match needs a stack, sectors, personal_data or people_decisions")
    for flag in ("personal_data", "people_decisions"):
        if flag in match and match[flag] is not True:
            raise CatalogError(f"match.{flag} must be true; omit it otherwise")
    if "min_versions" in match and "stack" not in match:
        raise CatalogError("match.min_versions needs a match.stack")
    _validate_list(match.get("stack", []), "match.stack", allow_empty="stack" not in match)
    for group in match.get("stack", []):
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


# The task surfaces a lens can name; unsure and other are answers that keep every lens, never a lens's scope.
LENS_SURFACES = ("customer", "service", "infrastructure", "business")
# The task concerns a lens can name; none, unsure and other are answers, never a lens's scope.
LENS_CONCERNS = ("money", "ai", "people-decisions", "credentials")


def _validate_lens_surfaces(specialist: dict[str, Any]) -> None:
    """applies_to names the task surfaces a lens can concern; the task's other surfaces leave it out."""
    surfaces = specialist["applies_to"]
    _validate_list(surfaces, f"specialist {specialist['id']} applies_to")
    unknown = [surface for surface in surfaces if surface not in LENS_SURFACES]
    if unknown or len(set(surfaces)) != len(surfaces):
        raise CatalogError(f"specialist {specialist['id']} applies_to lists distinct surfaces among "
                           f"{', '.join(LENS_SURFACES)}")


def _validate_lens_concerns(specialist: dict[str, Any]) -> None:
    """applies_to_concerns names the task concerns a lens needs; a task that answers none of them leaves it out."""
    concerns = specialist["applies_to_concerns"]
    label = f"specialist {specialist['id']} applies_to_concerns"
    if not isinstance(concerns, list) or not concerns:
        raise CatalogError(f"{label} must be a non-empty list")
    if any(item not in LENS_CONCERNS for item in concerns) or len(set(concerns)) != len(concerns):
        raise CatalogError(f"{label} lists distinct concerns among {', '.join(LENS_CONCERNS)}")


def _validate_board_review(review: Any) -> None:
    _validate_fields(review, "review", {"specialists", "evidence", "challenge", "decision_criteria"})
    _validate_list(review["specialists"], "review.specialists")
    seen = set()
    for specialist in review["specialists"]:
        _validate_fields(specialist, "specialist", {"id", "title", "focus"}, {"checks", "applies_to", "applies_to_concerns"})
        specialist_id = specialist["id"]
        _validate_id(specialist_id, "specialist ID")
        if specialist_id in seen:
            raise CatalogError(f"Duplicate specialist: {specialist_id}")
        seen.add(specialist_id)
        _validate_text(specialist["title"], "specialist title")
        _validate_text(specialist["focus"], "specialist focus")
        # What an expert of this lens verifies: the discipline's knowledge carried into each consultation.
        if "applies_to" in specialist:
            _validate_lens_surfaces(specialist)
        if "applies_to_concerns" in specialist:
            _validate_lens_concerns(specialist)
        if "checks" in specialist:
            _validate_list(specialist["checks"], f"specialist {specialist_id} checks")
            for check in specialist["checks"]:
                _validate_text(check, f"specialist {specialist_id} check")
    for key in ("evidence", "challenge", "decision_criteria"):
        _validate_list(review[key], f"review.{key}")
        for prompt in review[key]:
            _validate_text(prompt, f"review.{key} entry")


def _validate_entry(collection: str, entry: Any, *, bundled: bool = False, allow_command: bool = False) -> None:
    required = ENTRY_FIELDS | COLLECTION_FIELDS[collection]
    optional = {
        "packs": {"depends_on", "conflicts_with"},
        "patterns": {"match", "exclusive_group", "references", "kind", "core_for"},
        "boards": {"review"},
    }.get(collection)
    _validate_fields(entry, "record", required, optional)
    _validate_id(entry["id"], "id")
    _validate_text(entry["title"], "title")
    _validate_text(entry["description"], "description")
    _validate_sources(entry["sources"], require_checked=bundled)
    if collection == "packs":
        _validate_pack(entry, allow_command)
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


BOARD_LIST_FIELDS = ("expertises", "triggers", "questions", "sources")
REVIEW_LIST_FIELDS = ("evidence", "challenge", "decision_criteria")
MISSING_REVIEW = (
    "a project brain needs a review block with specialists, evidence, challenge and decision_criteria. "
    "Run openguildkit brains --new ID to start from a complete skeleton"
)


def _append_new(items: list, additions: list) -> list:
    return items + [item for item in additions if item not in items]


def merge_board(bundled: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Complete a bundled brain with a project file: lists grow, a specialist with the same ID is replaced."""
    merged = json.loads(json.dumps(bundled))
    for key in ("title", "description"):
        if key in overlay:
            merged[key] = overlay[key]
    for key in BOARD_LIST_FIELDS:
        merged[key] = _append_new(merged[key], overlay.get(key, []))
    review = overlay.get("review", {})
    if review:
        base = merged.setdefault("review", {"specialists": [], "evidence": [], "challenge": [], "decision_criteria": []})
        specialists = {specialist["id"]: specialist for specialist in base["specialists"]}
        for specialist in review.get("specialists", []):
            specialists[specialist["id"]] = specialist
        base["specialists"] = list(specialists.values())
        for key in REVIEW_LIST_FIELDS:
            base[key] = _append_new(base[key], review.get(key, []))
    return merged


def _validate_overlay(overlay: Any) -> None:
    """A project file that completes a bundled brain may carry any board field; the merged board is validated."""
    fields = ENTRY_FIELDS | COLLECTION_FIELDS["boards"] | {"review"}
    _validate_fields(overlay, "record", {"id"}, fields - {"id"})
    review = overlay.get("review", {})
    _validate_fields(review, "review", set(), {"specialists", *REVIEW_LIST_FIELDS})
    for key in (*BOARD_LIST_FIELDS, "specialists"):
        source = review if key == "specialists" else overlay
        if key in source:
            _validate_list(source[key], key)


def _load_entry(collection: str, path: Path, entry: Any, entries: dict, bundled: bool) -> tuple[dict, bool]:
    """Validate one record file. A project board with the ID of a bundled one completes it."""
    record_id = entry.get("id") if isinstance(entry, dict) else None
    overlay = collection == "boards" and not bundled and record_id in entries
    if overlay:
        _validate_overlay(entry)
        merged = merge_board(entries[record_id], entry)
        _validate_entry(collection, merged)
    else:
        # Only the project's own catalog may run commands: it already controls its check commands.
        _validate_entry(collection, entry, bundled=bundled, allow_command=not bundled)
        merged = entry
        if record_id in entries:
            raise CatalogError(f"duplicate {collection} ID {record_id!r}")
        if collection == "boards" and not bundled and "review" not in entry:
            raise CatalogError(MISSING_REVIEW)
    if path.name != f"{record_id}.json":
        raise CatalogError(f"name the file {record_id}.json after its id")
    return merged, overlay


def overlaid_boards(catalog: dict) -> set[str]:
    """Bundled brains that a project file completes. The project owns them, so the lock does not pin them."""
    return set(catalog.get("overlays", {}).get("boards", []))


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


def package_file(*parts: str):
    """A file or folder shipped in the package: a plain path, unless the package is installed inside an archive.

    importlib.resources takes longer to import than most commands need, so it serves only that rare case.
    """
    package = Path(__file__).parent
    if package.joinpath("registry").is_dir():
        return package.joinpath(*parts)
    from importlib.resources import files

    return files("openguildkit").joinpath(*parts)


def _registry():
    return package_file("registry")


def _read_records(collection: str, directory, entries: dict, bundled: bool, overlays: list) -> None:
    """Validate the record files of one folder and add them to entries."""
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if not path.name.endswith(".json"):
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_fields)
            entry, overlay = _load_entry(collection, path, entry, entries, bundled)
        except RecursionError as exc:
            raise CatalogError(f"{path}: JSON nested too deeply") from exc
        except (OSError, ValueError) as exc:
            raise CatalogError(f"{path}: {exc}") from exc
        entries[entry["id"]] = entry
        if overlay:
            overlays.append(entry["id"])


def _read_bundled(builtin) -> dict[str, dict[str, dict[str, Any]]]:
    """Read and validate the records that ship with OpenGuildKit, by collection."""
    bundled = {}
    for collection in COLLECTION_FIELDS:
        directory = builtin.joinpath(collection)
        if not directory.is_dir():
            raise CatalogError(f"{directory} must be a directory")
        entries: dict[str, dict[str, Any]] = {}
        _read_records(collection, directory, entries, True, [])
        if not entries:
            raise CatalogError(f"{directory} has no bundled records")
        bundled[collection] = entries
    return bundled


# Bundled records already validated in this process, by registry folder. They ship with the code that is
# running, so they cannot change during a command; project records are read again on every load.
_BUNDLED: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}


def _bundled_records(builtin) -> dict[str, dict[str, dict[str, Any]]]:
    """A copy of the validated bundled records, read and validated once per process."""
    key = str(builtin)
    if key not in _BUNDLED:
        _BUNDLED[key] = _read_bundled(builtin)
    return copy.deepcopy(_BUNDLED[key])


def load_catalog(
    extra_dir: Path | None = None, *, central_policy: tuple[str, dict] | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    """Load bundled records and optional project additions, ordered by ID."""
    bundled = _bundled_records(_registry())
    if extra_dir is not None and extra_dir.exists() and not extra_dir.is_dir():
        raise CatalogError(f"{extra_dir} must be a directory")
    project = extra_dir if extra_dir is not None and extra_dir.is_dir() else None

    catalog: dict[str, dict[str, dict[str, Any]]] = {}
    overlays: list[str] = []
    for collection in COLLECTION_FIELDS:
        entries = bundled[collection]
        directory = project.joinpath(collection) if project is not None else None
        if directory is not None and directory.is_dir():
            _read_records(collection, directory, entries, False, overlays)
        elif directory is not None and directory.is_file():
            raise CatalogError(f"{directory} must be a directory")
        catalog[collection] = dict(sorted(entries.items()))

    if central_policy is not None:
        commit, pack = central_policy
        _validate_entry("packs", pack)
        rules = pack["rules"]
        check = rule_check(rules[0]) if len(rules) == 1 else None
        if pack["id"] != EXPORT_EXPIRY_ID or check is None or check["kind"] != "field":
            raise CatalogError(f"The central policy must contain one {EXPORT_EXPIRY_ID} rule with a field check")
        if EXPORT_EXPIRY_ID in catalog["packs"]:
            raise CatalogError(f"duplicate packs ID {EXPORT_EXPIRY_ID!r}")
        catalog["packs"][EXPORT_EXPIRY_ID] = {**pack, "policy_commit": commit}
        catalog["packs"] = dict(sorted(catalog["packs"].items()))

    if overlays:
        catalog["overlays"] = {"boards": sorted(overlays)}
    _validate_dependencies(catalog["packs"])
    for pattern_id, pattern in catalog["patterns"].items():
        unknown_packs = set(pattern["packs"]) - catalog["packs"].keys()
        if unknown_packs:
            raise CatalogError(f"Pattern {pattern_id!r} links unknown packs: {', '.join(sorted(unknown_packs))}")
        unknown_sectors = set(pattern.get("match", {}).get("sectors", [])) - catalog["sectors"].keys()
        if unknown_sectors:
            raise CatalogError(f"Pattern {pattern_id!r} links unknown sectors: {', '.join(sorted(unknown_sectors))}")
    return catalog


def undated_sources(records: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
    """The records, as collection/id, that cite a source without a checked date."""
    return [
        f"{collection}/{record_id}"
        for collection, entries in records.items()
        if collection != "overlays"
        for record_id, record in entries.items()
        if any("checked" not in source for source in record.get("sources", []))
    ]


def latest_checked(*record_lists) -> str | None:
    """The most recent checked date among the sources of the given records."""
    dates = [
        source["checked"] for records in record_lists for record in records
        for source in record.get("sources", []) if "checked" in source
    ]
    return max(dates, default=None)
