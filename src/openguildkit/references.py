"""Discover bibliographic references separately from active rule packs."""

import json
import re
import unicodedata
from importlib.resources import files
from pathlib import Path

from .catalog import (
    CatalogError,
    _unique_fields,
    _validate_fields,
    _validate_id,
    _validate_list,
    _validate_sources,
    _validate_text,
)

REFERENCE_ID = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
TEXT_FIELDS = ("title", "category", "kind", "summary", "applies_when")


def _validate_family(family, filename: str) -> None:
    _validate_fields(family, "family", {"id", "title", "references"})
    _validate_id(family["id"], "family ID")
    if filename != f"{family['id']}.json":
        raise CatalogError(f"Expected the family file to be named {family['id']}.json")
    _validate_text(family["title"], "family title")
    _validate_list(family["references"], "references")
    for record in family["references"]:
        _validate_fields(record, "reference", {"id", "sources", *TEXT_FIELDS})
        record_id = record["id"]
        if not isinstance(record_id, str) or not REFERENCE_ID.fullmatch(record_id):
            raise CatalogError(f"Invalid reference ID: {record_id!r}")
        for field in TEXT_FIELDS:
            _validate_text(record[field], f"{record_id}.{field}")
        _validate_list(record["sources"], f"{record_id}.sources")
        _validate_sources(record["sources"])


def load_references(extra_dir: Path | None = None) -> dict[str, dict]:
    """Load the reference index and merge new project entries by stable ID."""
    bundled = files("openguildkit").joinpath("registry", "references")
    directories = [bundled]
    if extra_dir is not None and extra_dir.exists():
        directories.append(extra_dir)
    families = {}
    seen = set()
    for directory in directories:
        if not directory.is_dir():
            raise CatalogError(f"{directory} must be a directory")
        for path in sorted(directory.iterdir(), key=lambda entry: entry.name):
            if not path.name.endswith(".json"):
                continue
            try:
                incoming = json.loads(
                    path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_fields
                )
                _validate_family(incoming, path.name)
                family = families.setdefault(
                    incoming["id"], {"id": incoming["id"], "title": incoming["title"], "references": []}
                )
                if incoming["title"] != family["title"]:
                    raise CatalogError(f"Expected family title {family['title']!r}")
                for reference in incoming["references"]:
                    record_id = reference["id"]
                    if record_id in seen:
                        raise CatalogError(f"Duplicate reference ID: {record_id}")
                    seen.add(record_id)
                    family["references"].append(reference)
            except (OSError, ValueError) as error:
                raise CatalogError(f"{path}: {error}") from error
        if directory == bundled and not families:
            raise CatalogError(f"{bundled} has no bundled reference families")
    return dict(sorted(families.items()))


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    unaccented = "".join(character for character in folded if not unicodedata.combining(character))
    return re.findall(r"[^\W_]+", unaccented)


def find_references(
    families: dict, *, family_id: str | None = None, query: str | None = None, record_id: str | None = None
) -> list[dict]:
    if family_id is not None and family_id not in families:
        raise ValueError(f"Unknown reference family: {family_id}. Run openguildkit references.")
    if record_id is not None and query is not None:
        raise ValueError("Choose either a search query or --id.")
    selected = [families[family_id]] if family_id is not None else families.values()
    records = [
        {**record, "family": family["id"], "family_title": family["title"]}
        for family in selected
        for record in family["references"]
    ]
    if record_id is not None:
        found = [record for record in records if record["id"] == record_id]
        if not found:
            raise ValueError(f"Unknown reference ID: {record_id}. Run openguildkit references QUERY.")
        return found
    if query is None:
        return records
    terms = set(_words(query))
    if not terms:
        raise ValueError("Supply at least one word to search the references.")
    ranked = []
    for record in records:
        names = set(_words(f"{record['id']} {record['title']}"))
        labels = set(_words(f"{record['kind']} {record['category']} {record['family_title']}"))
        context = set(_words(f"{record['summary']} {record['applies_when']}"))
        if terms.issubset(names | labels | context):
            ranked.append((-len(terms & names), -len(terms & labels), record["id"], record))
    return [record for _, _, _, record in sorted(ranked)]
