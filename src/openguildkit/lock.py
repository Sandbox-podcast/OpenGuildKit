"""Pin the catalog records a project uses so a new OpenGuildKit release cannot change its rules silently.

The lock holds a copy of every bundled pack, board, sector and pattern the profile
uses. Commands read the locked copy instead of the bundled one. `openguildkit update`
shows what a newer catalog would change and applies it only when asked.

Entry: lock_path, read_lock, central_policy, installed_catalog, project_catalog
Tests: tests/test_org_catalog.py, tests/test_performance.py
"""

import json
from pathlib import Path

from .catalog import (
    CatalogError,
    bundled_ids,
    json_copy,
    latest_checked,
    load_catalog,
    overlaid_boards,
    validate_dependencies,
    validate_entry,
)
from .org_catalog import organization_in, validate_history, validate_pin
from .patterns import pattern_selection
from .project import selected_packs
from .startup import package_version
from .storage import file_signature, read_json, write_json

LOCK_FILE = "catalog.lock.json"
COLLECTIONS = ("packs", "boards", "sectors", "patterns")


def lock_path(state: Path) -> Path:
    return state / LOCK_FILE


# Locks already validated in this process, by the signature of their file: task consult reads the lock again under
# the project lock, and the web server runs one command after another.
_READ: dict[tuple, dict] = {}
_READ_KEPT = 8


def read_lock(state: Path) -> dict | None:
    """The project's catalog lock, validated; each call gets its own copy."""
    path = lock_path(state)
    if not path.is_file():
        return None
    key = (str(path), file_signature(path, content=True))
    if key not in _READ:
        lock = _validated_lock(path)
        if len(_READ) >= _READ_KEPT:
            _READ.clear()
        _READ[key] = lock
    return json_copy(_READ[key])


def _validated_lock(path: Path) -> dict:
    lock = read_json(path)
    if lock.get("schema_version") != 1 or not isinstance(lock.get("records"), dict):
        raise ValueError(f"Unsupported catalog lock: {path}. Run openguildkit update --apply.")
    records = lock["records"]
    for collection, entries in records.items():
        if collection not in COLLECTIONS or not isinstance(entries, dict):
            raise ValueError(f"Unknown collection {collection!r} in {path}.")
        for record_id, record in entries.items():
            if not isinstance(record, dict):
                raise ValueError(f"{path}: {collection}/{record_id} is not an object. Restore the file from Git, or delete it and "
                                 "run openguildkit update --apply, which locks the catalog installed on this machine.")
            try:
                validate_entry(collection, {key: value for key, value in record.items() if key != "policy_commit"})
            except CatalogError as error:
                raise ValueError(f"{path}: {collection}/{record_id}: {error}") from error
            if record.get("id") != record_id:
                raise ValueError(f"{path}: {collection}/{record_id} has a different id.")
    if "organization" in lock:
        validate_pin(lock["organization"], str(path))
    if "organization_history" in lock:
        validate_history(lock["organization_history"], str(path))
    return lock


def central_policy(args) -> tuple[str, dict] | None:
    """The central export rule that --policy-repo and --policy-commit name, read at that commit; None without them,
    and for a caller without command-line arguments (args None), such as the web page."""
    repo, commit = (args.policy_repo, args.policy_commit) if args is not None else (None, None)
    if (repo is None) != (commit is None):
        raise ValueError("Supply --policy-repo and --policy-commit together.")
    from .ci import read_policy_pack  # Not for the edit hook, which reads the lock (#539).

    return None if repo is None else (commit, read_policy_pack(repo, commit))


def _live_catalog(args, state: Path, lock: dict | None) -> dict:
    """The installed catalog with the organization's records, if the lock pins an organization catalog, and the
    project's additions."""
    organization = organization_in(lock, state)
    return load_catalog(state / "catalog", central_policy=central_policy(args), organization=organization)


def installed_catalog(args, state: Path) -> tuple[dict, dict[str, set[str]]]:
    """The installed catalog (_live_catalog) and the IDs that ship with OpenGuildKit."""
    return _live_catalog(args, state, read_lock(state)), bundled_ids()


def project_catalog(args, state: Path) -> dict:
    """The catalog in force for the project: locked records take precedence over installed ones."""
    lock = read_lock(state)
    return apply_lock(_live_catalog(args, state, lock), lock)


LOCK_OLDER = (
    "The instructions follow a newer catalog than the project's lock. Run openguildkit update to review the changes "
    "and the tasks they touch, then openguildkit update --apply. openguildkit sync would rewrite the instructions from "
    "the lock's earlier rules and leave the lock as it is."
)


def require_instructions(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    """Refuse out-of-date instructions, naming update rather than sync when they follow a newer installed catalog."""
    from .project_instructions import RuleError, check_instructions  # Not for the edit hook (#539).

    try:
        check_instructions(root, profile, catalog)
    except ValueError as error:
        lock = read_lock(state)
        if lock is not None and _instructions_match(root, profile, update_target(installed_catalog(args, state)[0], lock)):
            raise RuleError(LOCK_OLDER, "instructions-ahead-of-lock", getattr(error, "files", ())) from None
        raise


def _instructions_match(root: Path, profile: dict, catalog: dict) -> bool:
    from .project_instructions import check_instructions

    try:
        check_instructions(root, profile, catalog)
    except ValueError:
        return False
    return True


def apply_lock(catalog: dict, lock: dict | None) -> dict:
    """Return the catalog with the project's locked records in place of the bundled ones. It holds the lock's records,
    not copies: pass a lock read for this call (read_lock gives each call its own copy)."""
    if not lock:
        return catalog
    effective = {collection: dict(entries) for collection, entries in catalog.items()}
    overlaid = overlaid_boards(catalog)
    for collection, entries in lock["records"].items():
        for record_id, record in entries.items():
            if collection == "boards" and record_id in overlaid:
                continue
            effective[collection][record_id] = record
        effective[collection] = dict(sorted(effective[collection].items()))
    try:
        validate_dependencies(effective["packs"])
    except CatalogError as error:
        raise ValueError(f"The catalog lock is inconsistent: {error}. Run openguildkit update.") from error
    return effective


def used_ids(profile: dict, catalog: dict) -> dict[str, list[str]]:
    patterns = [pattern_selection(entry)[0] for entry in profile.get("patterns", [])]
    return {
        "packs": selected_packs(profile, catalog),
        "boards": list(profile.get("boards") or catalog["boards"]),
        "sectors": [profile["sector"]],
        "patterns": patterns,
    }


def _lockable(bundled: dict[str, set[str]], lock: dict | None) -> dict[str, set[str]]:
    """Bundled IDs plus those already pinned: a release that drops a record must not break the project."""
    pinned = lock["records"] if lock else {}
    return {collection: bundled[collection] | set(pinned.get(collection, {})) for collection in COLLECTIONS}


def locked_records(profile: dict, catalog: dict, bundled: dict[str, set[str]], lock: dict | None = None) -> dict:
    """The bundled or already locked records the profile uses, taken from the given catalog."""
    used = used_ids(profile, catalog)
    lockable = _lockable(bundled, lock)
    overlaid = overlaid_boards(catalog)
    return {
        collection: {
            record_id: json_copy(catalog[collection][record_id])
            for record_id in sorted(used[collection])
            if record_id in lockable[collection] and record_id in catalog[collection]
            and not (collection == "boards" and record_id in overlaid)
        }
        for collection in COLLECTIONS
    }


def build_lock(profile: dict, catalog: dict, bundled: dict[str, set[str]], lock: dict | None = None) -> dict:
    """The lock of the records the profile uses; the organization catalog it pins, if any, stays pinned."""
    built = {
        "schema_version": 1,
        "generated_by": f"openguildkit {package_version()}",
        "records": locked_records(profile, catalog, bundled, lock),
    }
    for key in ("organization", "organization_history"):
        if lock and key in lock:
            built[key] = json_copy(lock[key])
    return built


def unshipped_records(lock: dict, bundled: dict[str, set[str]]) -> list[str]:
    """Locked records that the installed release no longer ships, as collection/id."""
    return [
        f"{collection}/{record_id}"
        for collection in COLLECTIONS
        for record_id in lock["records"].get(collection, {})
        if record_id not in bundled[collection]
    ]


def write_lock(state: Path, lock: dict) -> None:
    write_json(lock_path(state), lock)


def lock_is_current(lock: dict | None, profile: dict, catalog: dict, bundled: dict[str, set[str]]) -> bool:
    """A project without a lock predates it; a lock must cover exactly what the profile uses."""
    return lock is None or lock["records"] == locked_records(profile, catalog, bundled, lock)


def _rule_text(rule: dict) -> str:
    text = f"{rule.get('instruction', '')} Verify: {rule.get('verification', '')}".strip()
    if "check" in rule:
        text = f"{text} Check: {json.dumps(rule['check'], sort_keys=True)}"
    if "evidence" in rule:
        text = f"{text} Evidence: {', '.join(item['id'] for item in rule['evidence'])}"
    return text


def _source_urls(record: dict) -> list[str]:
    return [source["url"] for source in record.get("sources", [])]


def _redated(old: dict, new: dict) -> list[dict]:
    """Sources kept by the new record whose checked date differs from the locked one."""
    before = {source["url"]: source.get("checked") for source in old.get("sources", [])}
    return [
        {"url": source["url"], "checked": [before[source["url"]], source.get("checked")]}
        for source in new.get("sources", [])
        if source["url"] in before and before[source["url"]] != source.get("checked")
    ]


def installed_catalog_date() -> str | None:
    """The date of the installed catalog: the most recent checked date among its bundled sources."""
    from .deliverables import load_deliverables  # Only update needs them; keep other commands fast.
    from .references import load_references

    catalog = load_catalog()
    references = [record for family in load_references().values() for record in family["references"]]
    return latest_checked(
        *(catalog[collection].values() for collection in COLLECTIONS), references,
        load_deliverables(catalog).values(),
    )


def record_changes(collection: str, old: dict, new: dict | None) -> dict | None:
    """Describe what changes between the locked record and the catalog's current one."""
    if new is None:
        return {"collection": collection, "id": old["id"], "status": "removed from the catalog"}
    if old == new:
        return None
    change = {"collection": collection, "id": old["id"], "status": "changed"}
    if collection == "packs":
        change["version"] = [old["version"], new["version"]]
        old_rules = {rule["id"]: rule for rule in old["rules"]}
        new_rules = {rule["id"]: rule for rule in new["rules"]}
        change["rules"] = {
            "added": [{"id": rule_id, "text": _rule_text(new_rules[rule_id])} for rule_id in new_rules if rule_id not in old_rules],
            "removed": [rule_id for rule_id in old_rules if rule_id not in new_rules],
            "changed": [
                {"id": rule_id, "before": _rule_text(old_rules[rule_id]), "after": _rule_text(new_rules[rule_id])}
                for rule_id in new_rules
                if rule_id in old_rules and old_rules[rule_id] != new_rules[rule_id]
            ],
        }
    old_urls, new_urls = _source_urls(old), _source_urls(new)
    change["sources"] = {
        "added": [url for url in new_urls if url not in old_urls],
        "removed": [url for url in old_urls if url not in new_urls],
        "redated": _redated(old, new),
    }
    change["fields"] = sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))
    return change


def update_target(live: dict, lock: dict) -> dict:
    """The installed catalog, keeping locked records that it no longer ships so the profile stays valid."""
    target = {collection: dict(entries) for collection, entries in live.items()}
    for collection, entries in lock["records"].items():
        for record_id, record in entries.items():
            target[collection].setdefault(record_id, json_copy(record))
        target[collection] = dict(sorted(target[collection].items()))
    return target


def catalog_changes(lock: dict, live: dict, target: dict, profile: dict, bundled: dict[str, set[str]]) -> list[dict]:
    """Compare the locked records with what the installed catalog would now write."""
    changes = []
    current = locked_records(profile, target, bundled, lock)
    for collection in COLLECTIONS:
        locked = lock["records"].get(collection, {})
        for record_id, record in locked.items():
            change = record_changes(collection, record, live[collection].get(record_id))
            if change:
                changes.append(change)
        for record_id, record in current[collection].items():
            if record_id not in locked:
                changes.append({"collection": collection, "id": record_id, "status": "added", "version": record.get("version")})
    return changes
