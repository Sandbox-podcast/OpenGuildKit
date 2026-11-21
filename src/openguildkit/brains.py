"""What a brain knows: its specialists' methods, rule packs and reference material.

A brain's knowledge is assembled from the catalog instead of being copied into each board:
the patterns whose roles name the brain, the packs those patterns apply, and the references
tagged with the brain. The consultation carries this knowledge to each selected brain.
"""

import json
from pathlib import Path

from .catalog import ID_PATTERN

MAX_REFERENCES_IN_BRIEF = 12
# Text the skeleton of a project brain leaves to replace. brains --check reports it until it is gone.
TODO = "TODO:"


def brain_knowledge(board_id: str, catalog: dict, families: dict, active_packs: set[str] | None = None) -> dict:
    methods = [pattern for pattern in catalog["patterns"].values() if board_id in pattern["roles"]]
    pack_ids = list(dict.fromkeys(pack_id for pattern in methods for pack_id in pattern["packs"]))
    active_packs = active_packs or set()
    references = [
        reference
        for family in families.values()
        for reference in family["references"]
        if board_id in reference.get("brains", [])
    ]
    return {
        "methods": [{"id": pattern["id"], "title": pattern["title"]} for pattern in methods],
        "packs": [
            {"id": pack_id, "title": catalog["packs"][pack_id]["title"], "version": catalog["packs"][pack_id]["version"],
             "active": pack_id in active_packs}
            for pack_id in pack_ids if pack_id in catalog["packs"]
        ],
        "references": [
            {key: reference[key] for key in ("id", "title", "kind", "edition") if key in reference}
            | {"url": reference["sources"][0]["url"]}
            for reference in references
        ],
    }


def _brain_records(board_id: str, catalog: dict, families: dict) -> list[dict]:
    """The board and the records its knowledge comes from."""
    methods = [pattern for pattern in catalog["patterns"].values() if board_id in pattern["roles"]]
    packs = [catalog["packs"][pack_id] for pattern in methods for pack_id in pattern["packs"] if pack_id in catalog["packs"]]
    references = [record for family in families.values() for record in family["references"]
                  if board_id in record.get("brains", [])]
    return [catalog["boards"][board_id], *methods, *packs, *references]


def knowledge_gaps(catalog: dict, families: dict) -> list[str]:
    """Brains that have no method or no reference attached."""
    gaps = []
    for board_id in catalog["boards"]:
        knowledge = brain_knowledge(board_id, catalog, families)
        if not knowledge["methods"]:
            gaps.append(f"{board_id} has no method: tag a pattern with this role.")
        if not knowledge["references"]:
            gaps.append(f"{board_id} has no reference: tag references with this brain.")
        if TODO in json.dumps(_brain_records(board_id, catalog, families), ensure_ascii=False):
            gaps.append(f"{board_id} still has skeleton text: replace each {TODO} in its catalog files.")
    return gaps


def brief_knowledge(board_id: str, catalog: dict, families: dict, active_packs: set[str]) -> dict:
    """The part of the knowledge a consultation carries: active packs first, a bounded reading list."""
    knowledge = brain_knowledge(board_id, catalog, families, active_packs)
    knowledge["packs"].sort(key=lambda pack: not pack["active"])
    knowledge["references"] = knowledge["references"][:MAX_REFERENCES_IN_BRIEF]
    return knowledge


def _todo(text: str) -> str:
    return f"{TODO} {text}"


def brain_skeleton(board_id: str) -> dict[str, dict]:
    """Every file a project brain needs, keyed by its path in the project catalog, with text to replace."""
    pack_id, family_id = f"{board_id}-rules", f"project-{board_id}"
    specialists = [
        {"id": f"{board_id}-lens-{index}", "title": _todo(f"title of specialist {index}"),
         "focus": _todo("what this specialist examines in a task, in one or two sentences"),
         "checks": [_todo("one thing an expert of this lens verifies"), _todo("a frequent mistake this expert catches")]}
        for index in (1, 2, 3, 4)
    ]
    source = {"title": _todo("primary source: the standard, regulation or method publisher"),
              "url": "https://example.org/replace-with-the-primary-source"}
    board = {
        "id": board_id,
        "title": _todo("name of the discipline"),
        "description": _todo("what this brain reviews in a task, in one sentence"),
        "expertises": [_todo("area of expertise")],
        "triggers": [_todo("a phrase that appears in a task brief, in each language the team writes")],
        "questions": [_todo("a question this brain asks about every task")],
        "sources": [source],
        "review": {
            "specialists": specialists,
            "evidence": [_todo("a document, record or measurement this brain inspects")],
            "challenge": [_todo("a question that tests the proposal against an alternative or a failure")],
            "decision_criteria": [_todo("a condition that makes this brain proceed, revise or block")],
        },
    }
    pattern = {
        "id": f"{board_id}-method", "title": _todo("name of the method this brain applies"),
        "description": _todo("what the method does, in one sentence"), "sources": [source],
        "roles": [board_id], "packs": [pack_id],
    }
    pack = {
        "id": pack_id, "title": _todo("name of the rule pack"), "version": "0.1.0",
        "description": _todo("when these rules apply"), "sources": [source],
        "rules": [{"id": "first-rule", "instruction": _todo("an action an agent can take"),
                   "verification": _todo("how a person checks it in a record")}],
    }
    family = {
        "id": family_id, "title": _todo(f"references of {board_id}"),
        "references": [{
            "id": f"{board_id}-primary-source", "title": _todo("title of the reference"), "category": _todo("category"),
            "kind": "référentiel", "brains": [board_id], "summary": _todo("what the reference says, in one sentence"),
            "applies_when": _todo("when the brain should read it"), "packs": [pack_id], "sources": [source],
        }],
    }
    return {
        f"boards/{board_id}.json": board,
        f"patterns/{board_id}-method.json": pattern,
        f"packs/{pack_id}.json": pack,
        f"references/{family_id}.json": family,
    }


def write_brain_skeleton(catalog_dir: Path, board_id: str, catalog: dict) -> list[Path]:
    """Write the skeleton of a new project brain; refuse an existing ID or file instead of overwriting."""
    if not isinstance(board_id, str) or not ID_PATTERN.fullmatch(board_id):
        raise ValueError("Name the brain with lowercase letters, digits and hyphens, such as risk-office.")
    if board_id in catalog["boards"]:
        raise ValueError(
            f"Brain {board_id} already exists. To complete it, write .openguildkit/catalog/boards/{board_id}.json "
            "with only the lenses, evidence or criteria to add."
        )
    skeleton = brain_skeleton(board_id)
    for relative, record in skeleton.items():
        collection = relative.split("/")[0]
        if collection in ("patterns", "packs") and record["id"] in catalog[collection]:
            raise ValueError(f"The {collection[:-1]} {record['id']} already exists. Choose another brain ID.")
    files = {catalog_dir / relative: record for relative, record in skeleton.items()}
    existing = [path.as_posix() for path in files if path.exists()]
    if existing:
        raise ValueError(f"{existing[0]} already exists. Remove it or choose another brain ID.")
    for path, record in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return list(files)
