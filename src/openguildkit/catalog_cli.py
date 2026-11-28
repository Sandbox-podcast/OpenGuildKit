"""The commands that read the catalog in force: catalog, references, patterns, brains, detect and update.

Entry: print_catalog, print_references, print_patterns, print_brains, new_brain, print_detection, update_catalog,
pending_catalog_changes, undated_project_sources.
Tests: tests/test_upgrades.py, tests/test_references.py, tests/test_brain_knowledge.py.
"""

from pathlib import Path

from .brains import brain_knowledge, knowledge_gaps, reading_list_note, write_brain_skeleton
from .catalog import undated_sources
from .deliverables import load_deliverables
from .errors import unknown
from .lock import (
    apply_lock,
    build_lock,
    catalog_changes,
    installed_catalog,
    installed_catalog_date,
    project_catalog,
    read_lock,
    update_target,
    write_lock,
)
from .patterns import role_choices
from .profile_cli import print_touched
from .project import load_profile, rule_conflicts, sync_instructions
from .references import english_title, find_references, load_references, with_pattern_references
from .storage import print_json, project_lock
from .tasks import tasks_touched
from .tools import load_tools
from .wording import plural


def pending_catalog_changes(lock: dict | None, live: dict, profile: dict, bundled: dict) -> list[str]:
    """Locked records whose rules the installed catalog changes; a source checked again changes no rule."""
    if lock is None:
        return []
    changes = catalog_changes(lock, live, update_target(live, lock), profile, bundled)
    return [
        f"{change['collection']}/{change['id']}" for change in changes
        if change["status"] != "changed" or set(change["fields"]) != {"sources"}
        or change["sources"]["added"] or change["sources"]["removed"]
    ]


def undated_project_sources(state: Path, live: dict) -> list[str]:
    """Project records that cite a source without a checked date; bundled sources always carry one. The project's
    references are read with the catalog it uses, so a pack or a brain they name that does not exist stops check."""
    project = state / "catalog"
    in_use = apply_lock(live, read_lock(state))
    references = {
        "references": {record["id"]: record for family in load_references(project / "references", in_use).values()
                       for record in family["references"]},
        "deliverables": load_deliverables(live, project / "deliverables"),
    }
    return undated_sources({**live, **references})


def update_catalog(args, root: Path, state: Path) -> None:
    with project_lock(state):
        load_tools(state / "catalog" / "tools")
        live, bundled = installed_catalog(args, state)
        lock = read_lock(state)
        if lock is None:
            catalog = live
            profile = load_profile(state, catalog)
            if args.apply:
                sync_instructions(root, profile, catalog)
                write_lock(state, build_lock(profile, catalog, bundled))
            result = {"changes": [], "conflicts": [], "applied": args.apply, "stale_tasks": [],
                      "note": "The project had no catalog lock. It now pins the installed catalog." if args.apply
                      else "The project has no catalog lock yet. Run openguildkit update --apply or sync to create one."}
        else:
            current = apply_lock(live, lock)
            profile = load_profile(state, current)
            target = update_target(live, lock)
            changes = catalog_changes(lock, live, target, profile, bundled)
            conflicts = [conflict for conflict in rule_conflicts(profile, target) if conflict["resolution"] is None]
            # The tasks are named before --apply, and sync names the same ones afterwards.
            touched = tasks_touched(state, profile, target) if changes else []
            result = {"changes": changes, "conflicts": conflicts, "applied": False, "stale_tasks": touched}
            if args.apply and changes:
                sync_instructions(root, profile, target)
                write_lock(state, build_lock(profile, target, bundled, lock))
                result["applied"] = True
        result["catalog_date"] = installed_catalog_date()
    _print_update(result, args.json)


def _print_update(result: dict, as_json: bool) -> None:
    if as_json:
        print_json(result)
        return
    date = result.get("catalog_date") or "unknown"
    if result.get("note"):
        print(f"Installed catalog: sources checked up to {date}.")
        print(result["note"])
        return
    count = len(result["changes"])
    print(f"Installed catalog: sources checked up to {date}. "
          f"{count} {'record' if count == 1 else 'records'} changed since the project's lock.")
    if not result["changes"]:
        print("The project's rules match the installed catalog.")
        return
    for change in result["changes"]:
        label = f"{change['collection']}/{change['id']}"
        if change["status"] == "added":
            print(f"+ {label} {change.get('version') or ''}".rstrip())
            continue
        if change["status"] != "changed":
            print(f"- {label}: {change['status']}, kept from the lock until you remove it from .openguildkit/project.json")
            continue
        version = f" {change['version'][0]} -> {change['version'][1]}" if "version" in change else ""
        print(f"~ {label}{version} ({', '.join(change['fields'])})")
        for rule in change.get("rules", {}).get("added", []):
            print(f"    + rule {rule['id']}: {rule['text']}")
        for rule_id in change.get("rules", {}).get("removed", []):
            print(f"    - rule {rule_id}")
        for rule in change.get("rules", {}).get("changed", []):
            print(f"    ~ rule {rule['id']}")
            print(f"        before: {rule['before']}")
            print(f"        after:  {rule['after']}")
        for url in change["sources"]["added"]:
            print(f"    + source {url}")
        for url in change["sources"]["removed"]:
            print(f"    - source {url}")
        redated = change["sources"].get("redated", [])
        if redated:
            latest = max((item["checked"][1] or "" for item in redated), default="")
            print(f"    ~ {len(redated)} {'source' if len(redated) == 1 else 'sources'} checked again, latest {latest}")
    for conflict in result["conflicts"]:
        print(f"! {' and '.join(conflict['packs'])} conflict: record a resolution before applying.")
    if not result["applied"]:
        print_touched(result["stale_tasks"], before=True)
        print("Nothing changed. Run openguildkit update --apply to adopt these rules.")
        return
    print("Applied. The next consultations use these rules.")
    print_touched(result["stale_tasks"])


def print_catalog(catalog: dict, as_json: bool) -> None:
    groups = ("packs", "boards", "sectors")
    if as_json:
        print_json({group: catalog[group] for group in groups})
        return
    width = max(len(entry["id"]) for group in groups for entry in catalog[group].values())
    for group in groups:
        print(group.capitalize())
        for entry in catalog[group].values():
            preselected = _sector_packs(catalog, entry["id"]) if group == "sectors" else []
            suffix = f" (preselects {', '.join(preselected)})" if preselected else ""
            print(f"  {entry['id']:<{width}} {entry['title']}{suffix}")


def _sector_packs(catalog: dict, sector_id: str) -> list[str]:
    """The packs of the patterns that a sector preselects without a stack."""
    return [
        pack_id
        for pattern in catalog["patterns"].values()
        if sector_id in pattern.get("match", {}).get("sectors", []) and not pattern["match"].get("stack")
        for pack_id in pattern["packs"]
    ]


def print_references(args, state: Path, catalog: dict) -> None:
    families = with_pattern_references(load_references(state / "catalog" / "references", catalog), catalog["patterns"])
    if not args.json and all(value is None for value in (args.query, args.family, args.id)):
        print(f"{sum(len(family['references']) for family in families.values())} references")
        for family in families.values():
            print(f"  {family['id']:<14} {family['title']} ({len(family['references'])})")
        return
    matches = find_references(families, family_id=args.family, query=args.query, record_id=args.id)
    if args.json:
        print_json(matches)
    elif args.id:
        reference = matches[0]
        print(f"{english_title(reference)} [{reference['id']}]")
        if english_title(reference) != reference["title"]:
            print(f"Original title: {reference['title']}")
        print(f"{reference['family_title']} / {reference['category']} / {reference['kind']}")
        if reference.get("edition"):
            print(f"Edition: {reference['edition']}")
        print(f"\n{reference['summary']}\n{reference['applies_when']}\n")
        if reference.get("pattern"):
            print(f"Pattern: openguildkit patterns --id {reference['pattern']}")
        packs = [catalog["packs"][pack_id] for pack_id in reference.get("packs", []) if pack_id in catalog["packs"]]
        for pack in packs:
            print(f"Pack {pack['id']}@{pack['version']}: {', '.join(rule['id'] for rule in pack['rules'])}")
        if not packs:
            print("Status: documentary reference. No pack turns it into rules yet.")
        print()
        for source in reference["sources"]:
            print(_source_line(source))
    elif matches:
        for reference in matches:
            print(f"  {reference['id']:<34} {english_title(reference)} [{reference['family']}]")
    else:
        print("No references matched.")


def _source_line(source: dict) -> str:
    """A source as printed for a person, with the day its page was last checked."""
    checked = f" (checked {source['checked']})" if "checked" in source else ""
    return f"- {source['title']}: {source['url']}{checked}"


def print_patterns(args, patterns: dict) -> None:
    roles = role_choices(patterns)
    if args.role and args.role not in roles:
        raise ValueError(f"Unknown role: {args.role}. Available roles: {', '.join(roles)}.")
    matches = [
        pattern for pattern in patterns.values()
        if (not args.role or args.role in pattern["roles"]) and (not args.id or args.id == pattern["id"])
    ]
    if args.id and not matches:
        raise ValueError(unknown("pattern", args.id, "patterns"))
    if args.json:
        print_json(matches)
        return
    if args.id:
        pattern = matches[0]
        print(f"{pattern['title']} [{pattern['id']}]")
        print(pattern["description"])
        print(f"Roles: {', '.join(pattern['roles'])}")
        print(f"Packs: {', '.join(pattern['packs'])}")
        match = pattern.get("match", {})
        if match.get("stack"):
            requirements = [" / ".join(group) for group in match["stack"]]
            print(f"Stack requirements: {' + '.join(requirements)}")
        if match.get("sectors"):
            print(f"Sectors: {', '.join(match['sectors'])}")
        if match.get("personal_data"):
            print("Preselected when the project processes personal data")
        for source in pattern["sources"]:
            print(_source_line(source))
        return
    print(f"{len(matches)} patterns")
    for pattern in matches:
        print(f"  {pattern['id']:<33} {pattern['title']} [{', '.join(pattern['roles'])}]")


def print_detection(detected: dict, as_json: bool) -> None:
    if as_json:
        print_json(detected)
        return
    if not detected["components"]:
        print("No known manifest found. Describe the stack during init.")
        return
    for component in detected["components"]:
        print(f"{component['id']} ({component['path']})")
        for item in component["evidence"]:
            version = item["version"] or item.get("note") or "version unknown"
            note = ", inferred from a client library" if item["inferred"] else ""
            print(f"  {item['name']}: {version} [{item['evidence']}{note}]")


def print_brains(args, catalog: dict, families: dict) -> int:
    boards = catalog["boards"]
    if args.id and args.id not in boards:
        raise ValueError(f"Unknown brain: {args.id}. Run openguildkit brains.")
    if args.check:
        gaps = knowledge_gaps(catalog, families)
        for gap in gaps:
            print(f"- {gap}")
        print(f"{len(boards)} brains, {plural(len(gaps), 'gap')}.")
        return 1 if gaps else 0
    if args.json:
        if args.id:
            print_json({**boards[args.id], "knowledge": brain_knowledge(args.id, catalog, families)})
        else:
            print_json(boards)
    elif args.id:
        board = boards[args.id]
        print(f"{board['title']} [{board['id']}]")
        print(board["description"])
        if "review" in board:
            plan = board["review"]
            for specialist in plan["specialists"]:
                print(f"  {specialist['title']}: {specialist['focus']}")
                for check in specialist.get("checks", []):
                    print(f"    - {check}")
            for heading, key in (
                ("Evidence to inspect", "evidence"),
                ("Challenge questions", "challenge"),
                ("Decision criteria", "decision_criteria"),
            ):
                print(f"\n{heading}")
                for question in plan[key]:
                    print(f"  - {question}")
        knowledge = brain_knowledge(args.id, catalog, families)
        print("\nMethods")
        for item in knowledge["methods"]:
            print(f"  - {item['title']} [{item['id']}]")
        print("\nRule packs")
        for item in knowledge["packs"]:
            print(f"  - {item['title']} [{item['id']}@{item['version']}]")
        print("\nReferences and standards")
        print(f"  {reading_list_note(len(knowledge['references']))}")
        for item in knowledge["references"]:
            edition = f" ({item['edition']})" if item.get("edition") else ""
            print(f"  - {item['title']}{edition}: {item['url']}")
        used = [tool["title"] for tool in load_tools().values() if args.id in tool["brains"]]
        print(f"\nTools this brain can use ({len(used)}): {', '.join(used)}")
        print(f"  Details: openguildkit tools list --brain {args.id}")
    else:
        width = max(len(board_id) for board_id in boards)
        for board in boards.values():
            reviewers = board.get("review", {}).get("specialists", [])
            count = f" ({len(reviewers)} specialists)" if reviewers else ""
            print(f"  {board['id']:<{width}} {board['title']}{count}")
    return 0


def new_brain(args, state: Path, catalog: dict) -> int:
    """Write a project brain's skeleton and say which tasks the new brain makes stale."""
    with project_lock(state):
        written = write_brain_skeleton(state / "catalog", args.new, catalog)
        updated = project_catalog(args, state)
    for path in written:
        print(f"Wrote {path.as_posix()}")
    print("Replace each TODO, then run openguildkit brains --check and openguildkit sync.")
    if not (state / "project.json").is_file():
        return 0
    profile = load_profile(state, catalog)
    if profile["boards"]:
        print(f"The profile lists its boards: openguildkit profile add board {args.new} --by INITIALS --reason WHY "
              "lets it review tasks.")
        return 0
    already = {task["id"] for task in tasks_touched(state, profile, catalog)}
    stale = [task for task in tasks_touched(state, profile, updated) if task["id"] not in already]
    for task in stale:
        print(f"Task {task['id']} ({task['status']}) was consulted without {args.new}: once you sync, "
              "it needs a new review before work continues.")
    if not stale:
        print(f"No task was reviewed under the previous board. New tasks will be routed to {args.new} by its triggers.")
    return 0
