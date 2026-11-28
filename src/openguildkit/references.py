"""Searches the reference library, separately from the active rule packs.

Entry: load_references, check_reference_links, with_pattern_references, english_title, find_references
Tests: tests/test_references.py
"""

import re
import unicodedata
from pathlib import Path

from .catalog import (
    ID_PATTERN,
    CatalogError,
    package_file,
    record_files,
    validate_fields,
    validate_id,
    validate_list,
    validate_sources,
    validate_text,
)
from .errors import OgkError
from .patterns import role_choices
from .records import Catalog

# IDs used before the hyphen convention, such as pd_iac, stay resolvable as aliases.
LEGACY_ID = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
TEXT_FIELDS = ("title", "category", "kind", "summary", "applies_when")
LINK_FIELDS = ("aliases", "brains", "pattern", "packs")
# The edition or version the entry describes, when the source has several: "2022", "Rev. 5", "5.0.0".
# The English title, when the title is in another language: the CLI and the briefs are in English.
OPTIONAL_TEXT_FIELDS = ("edition", "title_en")
KINDS = {
    "norme": "standard published by a standards body (ISO, IEC, ETSI, NIST FIPS, Ecma, HL7, NEMA)",
    "spécification": "technical specification from a consortium, a community or the IETF",
    "protocole": "exchange, messaging or authentication protocol",
    "format": "data, file or encoding format",
    "réglementation": "law or regulation",
    "référentiel": "set of requirements, controls or criteria, a design system or reference data",
    "méthode": "structured method with steps or artifacts",
    "pratique": "engineering, operations or organization practice",
    "principe": "design principle or heuristic",
    "concept": "theoretical notion or property",
    "convention": "naming, style or collaboration convention",
    "guide": "writing, design or usage guide",
    "outil": "software or service",
    "indicateur": "metric or numeric objective",
    "taxonomie": "classification of risks, weaknesses or attacks",
}
PATTERN_FAMILY = "work-patterns"


def _validate_links(record: dict, record_id: str) -> None:
    if "aliases" in record:
        aliases = record["aliases"]
        validate_list(aliases, f"{record_id}.aliases")
        for alias in aliases:
            if not isinstance(alias, str) or not LEGACY_ID.fullmatch(alias) or alias == record_id:
                raise CatalogError("OGK-DOCS-006", f"{record_id}.aliases must list former IDs other than the current one")
        if len(set(aliases)) != len(aliases):
            raise CatalogError("OGK-DOCS-007", f"{record_id}.aliases contains duplicates")
    if "brains" in record:
        validate_list(record["brains"], f"{record_id}.brains")
        for board_id in record["brains"]:
            validate_id(board_id, f"{record_id}.brains entry")
        if len(set(record["brains"])) != len(record["brains"]):
            raise CatalogError("OGK-DOCS-008", f"{record_id}.brains contains duplicates")
    if "pattern" in record:
        validate_id(record["pattern"], f"{record_id}.pattern")
    if "packs" in record:
        validate_list(record["packs"], f"{record_id}.packs")
        for pack_id in record["packs"]:
            validate_id(pack_id, f"{record_id}.packs entry")
        if len(set(record["packs"])) != len(record["packs"]):
            raise CatalogError("OGK-DOCS-009", f"{record_id}.packs contains duplicates")


def _validate_family(family, filename: str, bundled: bool = False) -> None:
    validate_fields(family, "family", {"id", "title", "references"})
    validate_id(family["id"], "family ID")
    if filename != f"{family['id']}.json":
        raise CatalogError("OGK-DOCS-010", f"Expected the family file to be named {family['id']}.json")
    validate_text(family["title"], "family title")
    validate_list(family["references"], "references")
    for record in family["references"]:
        validate_fields(record, "reference", {"id", "sources", *TEXT_FIELDS}, {*LINK_FIELDS, *OPTIONAL_TEXT_FIELDS})
        record_id = record["id"]
        if not isinstance(record_id, str) or not ID_PATTERN.fullmatch(record_id):
            raise CatalogError("OGK-DOCS-011",
                f"Invalid reference ID: {record_id!r}. Use lowercase letters, digits and hyphens, "
                "and keep a former ID in aliases."
            )
        for field in (*TEXT_FIELDS, *(name for name in OPTIONAL_TEXT_FIELDS if name in record)):
            validate_text(record[field], f"{record_id}.{field}")
        if record["kind"] not in KINDS:
            raise CatalogError("OGK-DOCS-012", f"{record_id}.kind must be one of: {', '.join(KINDS)}")
        _validate_links(record, record_id)
        validate_list(record["sources"], f"{record_id}.sources")
        validate_sources(record["sources"], require_checked=bundled)


def _merge_family(incoming: dict, families: dict, seen: set, project: set | None) -> None:
    """Add the references of one family file to its family, refusing an ID or alias already seen; with project, a
    set that receives the IDs of a project file."""
    family = families.setdefault(
        incoming["id"], {"id": incoming["id"], "title": incoming["title"], "references": []}
    )
    if incoming["title"] != family["title"]:
        raise CatalogError("OGK-DOCS-013", f"Expected family title {family['title']!r}")
    for reference in incoming["references"]:
        for name in (reference["id"], *reference.get("aliases", ())):
            if name in seen:
                raise CatalogError("OGK-DOCS-014", f"Duplicate reference ID: {name}")
            seen.add(name)
        family["references"].append(reference)
        if project is not None:
            project.add(reference["id"])


def load_references(extra_dir: Path | None = None, catalog: Catalog | None = None) -> dict[str, dict]:
    """Load the reference index and merge new project entries by stable ID. With the catalog the project uses, also
    check the project's entries with check_reference_links; the tests check the bundled ones."""
    bundled = package_file("registry", "references")
    directories = [bundled]
    if extra_dir is not None and extra_dir.exists():
        directories.append(extra_dir)
    families = {}
    seen: set[str] = set()
    project: set[str] = set()
    for directory in directories:
        if not directory.is_dir():
            raise CatalogError("OGK-DOCS-015", f"{directory} must be a directory")
        for path, incoming in record_files(directory):
            try:
                _validate_family(incoming, path.name, directory == bundled)
                _merge_family(incoming, families, seen, project if directory != bundled else None)
            except (OSError, ValueError) as error:
                raise CatalogError("OGK-DOCS-016", f"{path}: {error}") from error
        if directory == bundled and not families:
            raise CatalogError("OGK-DOCS-017", f"{bundled} has no bundled reference families")
    families = dict(sorted(families.items()))
    if catalog is not None:
        check_reference_links(families, catalog, only=project)
    return families


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    unaccented = "".join(character for character in folded if not unicodedata.combining(character))
    return re.findall(r"[^\W_]+", unaccented)


def _active_packs(pack_ids: list[str], packs: dict) -> set[str]:
    active, pending = set(), list(pack_ids)
    while pending:
        pack_id = pending.pop()
        if pack_id not in active and pack_id in packs:
            active.add(pack_id)
            pending.extend(packs[pack_id].get("depends_on", []))
    return active


def check_reference_links(families: dict, catalog: Catalog, only: set[str] | None = None) -> None:
    """Check that references, packs and patterns on one subject name each other.

    A reference names the brains whose work it supports, the pattern it presents and the
    packs built on it. A pattern names the references behind the packs it activates,
    dependencies included. With only, check those references alone: a project's own, against
    the catalog it uses, where a pack a release no longer ships stays while the lock keeps it.
    """
    records = {record["id"]: record for family in families.values() for record in family["references"]}
    for record_id, record in records.items():
        if only is not None and record_id not in only:
            continue
        unknown = [f"unknown {kind}: {', '.join(names)}" for kind, names in (
            ("brains", sorted(set(record.get("brains", [])) - catalog["boards"].keys())),
            ("packs", sorted(set(record.get("packs", [])) - catalog["packs"].keys()))) if names]
        if unknown:
            raise CatalogError("OGK-DOCS-018", f"Reference {record_id!r} names {' and '.join(unknown)}")
        pattern_id = record.get("pattern")
        if pattern_id is not None and record_id not in catalog["patterns"].get(pattern_id, {}).get("references", []):
            raise CatalogError("OGK-DOCS-019", f"Pattern {pattern_id!r} must list reference {record_id!r} in references")
    if only is not None:
        return
    for pattern_id, pattern in catalog["patterns"].items():
        for reference_id in pattern.get("references", []):
            record = records.get(reference_id)
            if record is None:
                raise CatalogError("OGK-DOCS-020", f"Pattern {pattern_id!r} names unknown reference {reference_id!r}")
            if record.get("pattern") != pattern_id and not set(record.get("packs", [])) & _active_packs(pattern["packs"], catalog["packs"]):
                raise CatalogError("OGK-DOCS-021", f"Reference {reference_id!r} names neither pattern {pattern_id!r} nor one of its packs")


def _with_status(record: dict) -> dict:
    """An entry is applied when packs turn it into rules, documentary otherwise."""
    linked = {**record, "status": "applied" if record.get("packs") else "documentary"}
    if "pattern" in record:
        linked["aliases"] = [*record.get("aliases", []), f"pattern-{record['pattern']}"]
    return linked


def with_pattern_references(families: dict, patterns: dict) -> dict:
    """Expose actionable patterns in the same index as their source material.

    A pattern that a reference presents appears once, as that reference, which also
    answers to the generated ID pattern-<id>. Other patterns get a generated entry.
    Every entry gets a status: applied when packs turn it into rules, documentary otherwise.
    """
    if PATTERN_FAMILY in families:
        raise CatalogError("OGK-DOCS-022", "The work-patterns family is generated from the pattern catalog")
    roles = role_choices(patterns)
    names = {
        name
        for family in families.values()
        for reference in family["references"]
        for name in (reference["id"], *reference.get("aliases", ()))
    }
    presented = {}
    for family in families.values():
        for reference in family["references"]:
            pattern_id = reference.get("pattern")
            if pattern_id is None:
                continue
            if pattern_id not in patterns:
                raise CatalogError("OGK-DOCS-023", f"Reference {reference['id']!r} presents unknown pattern {pattern_id!r}")
            if pattern_id in presented:
                raise CatalogError("OGK-DOCS-024", f"Pattern {pattern_id!r} is presented by {presented[pattern_id]!r} and {reference['id']!r}")
            presented[pattern_id] = reference["id"]
    records = []
    for pattern in patterns.values():
        pattern_id = pattern["id"]
        reference_id = f"pattern-{pattern_id}"
        if reference_id in names:
            raise CatalogError("OGK-DOCS-025", f"Reference ID {reference_id!r} is already used by a pattern")
        if pattern_id in presented:
            continue
        records.append(
            {
                "id": reference_id,
                "title": pattern["title"],
                "category": ", ".join(roles[role]["title"] for role in pattern["roles"]),
                "kind": "Stack pattern" if pattern.get("match", {}).get("stack") else "Work method",
                "summary": pattern["description"],
                "applies_when": f"Inspect the match and rule packs with openguildkit patterns --id {pattern_id}.",
                "sources": pattern["sources"],
                "pattern": pattern_id,
                "packs": pattern["packs"],
                "status": "applied",
            }
        )
    linked = {
        family_id: {**family, "references": [_with_status(reference) for reference in family["references"]]}
        for family_id, family in families.items()
    }
    return {**linked, PATTERN_FAMILY: {"id": PATTERN_FAMILY, "title": "Work and stack patterns", "references": records}}


def english_title(record: dict) -> str:
    """The title to show in English output: the English title when the entry has one."""
    return record.get("title_en", record["title"])


def find_references(
    families: dict, *, family_id: str | None = None, query: str | None = None, record_id: str | None = None
) -> list[dict]:
    if family_id is not None and family_id not in families:
        raise OgkError("OGK-DOCS-003", f"Unknown reference family: {family_id}. Run openguildkit references.")
    if record_id is not None and query is not None:
        raise ValueError("Choose either a search query or --id.")
    selected = [families[family_id]] if family_id is not None else families.values()
    records = [
        {**record, "family": family["id"], "family_title": family["title"]}
        for family in selected
        for record in family["references"]
    ]
    if record_id is not None:
        found = [record for record in records if record_id == record["id"] or record_id in record.get("aliases", ())]
        if not found:
            raise OgkError("OGK-DOCS-004", f"Unknown reference ID: {record_id}. Run openguildkit references QUERY.")
        return found
    if query is None:
        return records
    terms = set(_words(query))
    if not terms:
        raise ValueError("Supply at least one word to search the references.")
    ranked = []
    for record in records:
        names = set(_words(" ".join([record["id"], record["title"], record.get("title_en", ""), *record.get("aliases", ())])))
        labels = set(_words(f"{record['kind']} {record['category']} {record['family_title']}"))
        context = set(_words(f"{record['summary']} {record['applies_when']}"))
        if terms.issubset(names | labels | context):
            ranked.append((-len(terms & names), -len(terms & labels), record["id"], record))
    return [record for _, _, _, record in sorted(ranked)]
