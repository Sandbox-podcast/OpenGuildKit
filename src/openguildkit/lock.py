"""Pin the catalog records a project uses so a new OpenGuildKit release cannot change its rules silently.

The lock holds a copy of every bundled pack, board, sector and pattern the profile
uses. Commands read the locked copy instead of the bundled one. `openguildkit update`
shows what a newer catalog would change and applies it only when asked.
"""

from copy import deepcopy
from importlib import metadata
from pathlib import Path

from .catalog import CatalogError, _validate_dependencies, _validate_entry
from .patterns import pattern_selection
from .storage import read_json, write_json

LOCK_FILE = "catalog.lock.json"
COLLECTIONS = ("packs", "boards", "sectors", "patterns")


def package_version() -> str:
    """The installed version, or the version of the source checkout the CLI runs from."""
    try:
        return metadata.version("openguildkit")
    except metadata.PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        try:
            import tomllib

            return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"] + "+source"
        except (OSError, KeyError, ValueError):
            return "unknown"


def lock_path(state: Path) -> Path:
    return state / LOCK_FILE


def read_lock(state: Path) -> dict | None:
    path = lock_path(state)
    if not path.is_file():
        return None
    lock = read_json(path)
    if lock.get("schema_version") != 1 or not isinstance(lock.get("records"), dict):
        raise ValueError(f"Unsupported catalog lock: {path}. Run openguildkit update --apply.")
    records = lock["records"]
    for collection, entries in records.items():
        if collection not in COLLECTIONS or not isinstance(entries, dict):
            raise ValueError(f"Unknown collection {collection!r} in {path}.")
        for record_id, record in entries.items():
            try:
                _validate_entry(collection, {key: value for key, value in record.items() if key != "policy_commit"})
            except CatalogError as error:
                raise ValueError(f"{path}: {collection}/{record_id}: {error}") from error
            if record.get("id") != record_id:
                raise ValueError(f"{path}: {collection}/{record_id} has a different id.")
    return lock


def apply_lock(catalog: dict, lock: dict | None) -> dict:
    """Return the catalog with the project's locked records in place of the bundled ones."""
    if not lock:
        return catalog
    effective = {collection: dict(entries) for collection, entries in catalog.items()}
    for collection, entries in lock["records"].items():
        for record_id, record in entries.items():
            effective[collection][record_id] = deepcopy(record)
        effective[collection] = dict(sorted(effective[collection].items()))
    try:
        _validate_dependencies(effective["packs"])
    except CatalogError as error:
        raise ValueError(f"The catalog lock is inconsistent: {error}. Run openguildkit update.") from error
    return effective


def _used_ids(profile: dict, catalog: dict) -> dict[str, list[str]]:
    from .project import _selected_packs  # avoid a circular import at module load

    patterns = [pattern_selection(entry)[0] for entry in profile.get("patterns", [])]
    return {
        "packs": _selected_packs(profile, catalog),
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
    used = _used_ids(profile, catalog)
    lockable = _lockable(bundled, lock)
    return {
        collection: {
            record_id: deepcopy(catalog[collection][record_id])
            for record_id in sorted(used[collection])
            if record_id in lockable[collection] and record_id in catalog[collection]
        }
        for collection in COLLECTIONS
    }


def build_lock(profile: dict, catalog: dict, bundled: dict[str, set[str]], lock: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "generated_by": f"openguildkit {package_version()}",
        "records": locked_records(profile, catalog, bundled, lock),
    }


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
    if "check" in rule:
        return f"check {rule['check']}"
    return f"{rule['instruction']} Verify: {rule['verification']}"


def _source_urls(record: dict) -> list[str]:
    return [source["url"] for source in record.get("sources", [])]


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
    }
    change["fields"] = sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))
    return change


def update_target(live: dict, lock: dict) -> dict:
    """The installed catalog, keeping locked records that it no longer ships so the profile stays valid."""
    target = {collection: dict(entries) for collection, entries in live.items()}
    for collection, entries in lock["records"].items():
        for record_id, record in entries.items():
            target[collection].setdefault(record_id, deepcopy(record))
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
