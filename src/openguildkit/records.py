"""The types of the records read from disk: a task, a project profile and the catalog in force, each field named, so
that the type checker sees a key nothing writes.

The shapes stay checked at run time where they were (`tasks_record._RECORD`, `project.validate_profile`, `catalog.py`);
these types only name the top-level fields for the type checker; a nested part is a `dict` whose fields are not typed.

Entry: Task, Profile, Catalog, as_dict
Tests: tests/test_records.py
"""

from typing import Any, NotRequired, TypedDict, cast

# A nested part of a record: its shape is checked when the record is read (tasks_record._RECORD), not typed here.
Part = dict[str, Any]


class Task(TypedDict):
    """A task record, `.openguildkit/tasks/ID.json` (tasks_record._RECORD gives the shape of each part)."""

    schema_version: int
    id: str
    brief: str
    created_at: str
    status: str
    rounds: list[Part]
    lane: NotRequired[str]
    waiting_for: NotRequired[list[Any]]
    paths: NotRequired[list[str]]
    requested_by: NotRequired[str]
    completed_at: NotRequired[str]
    profile_fingerprint: NotRequired[str]
    answers: NotRequired[dict[str, Any]]
    consultation: NotRequired[Part]
    review: NotRequired[Part]
    decision: NotRequired[Part]
    passes: NotRequired[Part]
    deliberation: NotRequired[Part]
    blocker_resolutions: NotRequired[dict[str, Part]]
    verification_blocker_resolutions: NotRequired[dict[str, Part]]
    result: NotRequired[Part]
    follows: NotRequired[Part]
    after: NotRequired[list[str]]
    authorizations: NotRequired[list[Part]]
    dependency_alerts: NotRequired[Part]
    delivered_review: NotRequired[Part]
    deliverables: NotRequired[list[Part]]
    # Set in memory by the commands for the one that called them, never written: the records written leave them out.
    _held: NotRequired[Any]
    _submitted: NotRequired[bool]
    _warnings: NotRequired[list[str]]
    _error: NotRequired[str]


class Profile(TypedDict):
    """A project profile as project.validate_profile returns it from `.openguildkit/project.json`."""

    schema_version: int
    name: str
    sector: str
    stack: list[str]
    packs: list[str]
    boards: list[str]
    research: str
    conventions: list[str]
    checks: list[str]
    components: NotRequired[list[Any]]
    roles: NotRequired[list[str]]
    patterns: NotRequired[list[Any]]
    resolutions: NotRequired[list[Part]]
    required_boards: NotRequired[list[str]]
    required_rules: NotRequired[list[str]]
    host: NotRequired[str]
    guard: NotRequired[str]
    waivers: NotRequired[Any]
    approval: NotRequired[Part]
    tools: NotRequired[list[Any]]
    personal_data: NotRequired[bool]
    people_decisions: NotRequired[bool]
    declined: NotRequired[list[Any]]
    changes: NotRequired[list[Part]]
    ask_every_rule: NotRequired[bool]
    light_paths: NotRequired[list[str]]
    declined_rules: NotRequired[list[Any]]
    separate_requester: NotRequired[bool]
    frozen: NotRequired[Any]
    restricted_paths: NotRequired[list[str]]


# The catalog in force for a project (lock.project_catalog): each collection's records by ID, under "packs", "boards",
# "sectors" and "patterns", with "overlays" and "organization" when they apply. Not a TypedDict: forty places read a
# collection by a name held in a variable (`catalog[collection]`), which a TypedDict refuses.
Catalog = dict[str, dict[str, Any]]


def as_dict(record: Task | Profile) -> dict[str, Any]:
    """The same record as a plain dict, for a field named by a variable (`for key in FIELDS: record.pop(key)`), which
    the type of a record refuses."""
    return cast(dict, record)
