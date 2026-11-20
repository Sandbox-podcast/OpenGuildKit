"""What a brain knows: its specialists' methods, rule packs and reference material.

A brain's knowledge is assembled from the catalog instead of being copied into each board:
the patterns whose roles name the brain, the packs those patterns apply, and the references
tagged with the brain. The consultation carries this knowledge to each selected brain.
"""

MAX_REFERENCES_IN_BRIEF = 12


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


def knowledge_gaps(catalog: dict, families: dict) -> list[str]:
    """Brains that have no method or no reference attached."""
    gaps = []
    for board_id in catalog["boards"]:
        knowledge = brain_knowledge(board_id, catalog, families)
        if not knowledge["methods"]:
            gaps.append(f"{board_id} has no method: tag a pattern with this role.")
        if not knowledge["references"]:
            gaps.append(f"{board_id} has no reference: tag references with this brain.")
    return gaps


def brief_knowledge(board_id: str, catalog: dict, families: dict, active_packs: set[str]) -> dict:
    """The part of the knowledge a consultation carries: active packs first, a bounded reading list."""
    knowledge = brain_knowledge(board_id, catalog, families, active_packs)
    knowledge["packs"].sort(key=lambda pack: not pack["active"])
    knowledge["references"] = knowledge["references"][:MAX_REFERENCES_IN_BRIEF]
    return knowledge
