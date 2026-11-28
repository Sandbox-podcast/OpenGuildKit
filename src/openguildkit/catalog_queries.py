"""What the commands ask of the catalog besides loading it: a recorded value against its rule's bounds, the boards an
organization replaced and the sources without a date."""

import re
from typing import Any

from . import lazy_re
from .catalog import BOUND_FIELDS, overlaid_boards, registry_folder, validated_bundle


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


_NUMBER = lazy_re.compile(r"(?<![\w.])[-+]?[0-9]+(?:[.,][0-9]+)?")


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


def _changed_fields(before: dict, after: dict) -> list[str]:
    return sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))


def board_replacements(catalog: dict) -> list[str]:
    """One line per bundled brain whose title, description or specialists the project catalog replaces.

    A project may replace them (docs/catalog-format.md), and a weaker security brain reads like the bundled one:
    check and task consult print these lines so that the person sees what the project changed.
    """
    return list(replaced_boards(catalog).values())


def replaced_boards(catalog: dict) -> dict[str, str]:
    """The line board_replacements prints, by the ID of the brain it is about."""
    from .wording import plural

    bundled = validated_bundle(registry_folder())["boards"]
    lines = {}
    for board_id in sorted(overlaid_boards(catalog)):
        before, after = bundled.get(board_id), catalog["boards"].get(board_id)
        if before is None or after is None:
            continue
        changes = [f"{key} {after[key]!r} in place of {before[key]!r}" for key in ("title", "description")
                   if after[key] != before[key]]
        earlier = {item["id"]: item for item in before.get("review", {}).get("specialists", [])}
        replaced = [f"{item['id']} ({', '.join(_changed_fields(earlier[item['id']], item))})"
                    for item in after.get("review", {}).get("specialists", [])
                    if item["id"] in earlier and item != earlier[item["id"]]]
        if replaced:
            changes.append(f"{plural(len(replaced), 'specialist')} replaced: {', '.join(replaced)}")
        if changes:
            lines[board_id] = (f"the project catalog replaces parts of the bundled brain {board_id} "
                               f"(.openguildkit/catalog/boards/{board_id}.json): {'; '.join(changes)}. Check that the "
                               "person accepted this change to the brain's review.")
    return lines


def undated_sources(records: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
    """The records, as collection/id, that cite a source without a checked date."""
    return [
        f"{collection}/{record_id}"
        for collection, entries in records.items()
        if collection not in ("overlays", "organization")
        for record_id, record in entries.items()
        if any("checked" not in source for source in record.get("sources", []))
    ]
