"""The `org-catalog` commands: follow an organization catalog pinned at a commit of a local Git copy (RFC #446).

`show` says what the project follows; `set` shows what a commit brings and, with --by and --reason at a terminal,
pins it in the catalog lock (with --name, under a name that carries no path); `accept` records that a person accepts a
project record that replaces an organization record; `off` stops following it. The lock keeps each pin and each stop
with who, when and why. Nothing here runs for a project that never calls them.
"""

import os
import sys
from pathlib import Path

from .catalog import load_catalog
from .cli_surface import add_by
from .clock import today
from .lock import (
    COLLECTIONS,
    apply_lock,
    build_lock,
    central_policy,
    installed_catalog,
    package_version,
    project_catalog,
    read_lock,
    used_ids,
    write_lock,
)
from .org_catalog import (
    MIGRATE_COMMAND,
    NAME,
    changes,
    copies_read_from,
    organization_in,
    read_files,
    records_of,
    replacements,
    unaccepted_replacements,
    variable_name,
)
from .profile_cli import print_touched
from .project import load_profile, sync_instructions
from .shell import shell_word
from .storage import print_json, project_lock
from .tasks import tasks_touched
from .terminal import interactive

__all__ = ["add_parser", "run", "unaccepted_replacements"]

PERSON = "--by INITIALS --reason WHY"


def add_parser(commands) -> None:
    org = commands.add_parser(
        "org-catalog", help="Follow an organization catalog: packs, patterns and brains pinned at a commit of a local "
                            "Git copy (off unless a person sets it).")
    actions = org.add_subparsers(dest="org_action", required=True)
    show = actions.add_parser("show", help="Say which organization catalog the project follows and what it replaces.")
    show.add_argument("--json", action="store_true", help="Print it as JSON.")
    setter = actions.add_parser(
        "set", help="Show what a commit of the organization catalog adds, removes and changes; with --by and "
                    "--reason, a person pins it at a terminal.")
    setter.add_argument("--repo", type=Path, required=True, help="The local Git copy of the organization catalog.")
    setter.add_argument("--commit", required=True, help="The full SHA of the commit to follow.")
    setter.add_argument("--name", help="Pin it under this name, which carries no path: each machine points "
                                       "OPENGUILDKIT_ORG_CATALOG_NAME at its copy, and guard --ci takes "
                                       "--org-catalog NAME=PATH.")
    add_by(setter)
    setter.add_argument("--reason", help="Why, in one line.")
    setter.add_argument("--json", action="store_true", help="Print the changes as JSON.")
    accept = actions.add_parser(
        "accept", help="Accept, at a terminal, a project record that replaces a record of the organization catalog.")
    accept.add_argument("record", metavar="COLLECTION/ID", help="The replaced record, such as packs/review.")
    off = actions.add_parser("off", help="Stop following the organization catalog, at a terminal.")
    for command in (accept, off):
        add_by(command, required=True)
        command.add_argument("--reason", required=True, help="Why, in one line.")


def _confirm(target: str, what: str) -> None:
    """A person types the target at an interactive terminal."""
    if not interactive():
        raise ValueError(f"To {what}, a person runs the command at an interactive terminal.")
    print(f"Type {target} to {what}: ", end="", file=sys.stderr, flush=True)
    if input().strip() != target:
        raise ValueError("Cancelled. Nothing was written.")


def _person(args) -> dict:
    for name in ("by", "reason"):
        value = getattr(args, name)
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError(f"--{name} must be a non-empty single line.")
    return {"by": args.by.strip(), "reason": args.reason.strip(), "on": today().isoformat()}


def _stored_repo(repo: Path, root: Path) -> str:
    """The copy's path as the lock keeps it: relative to the project root when it can be, so teammates share it."""
    absolute = repo.resolve()
    try:
        return Path(os.path.relpath(absolute, root.resolve())).as_posix()
    except ValueError:  # Another drive on Windows.
        return absolute.as_posix()


def _show(args, root: Path, state: Path) -> int:
    lock = read_lock(state)
    pin = (lock or {}).get("organization")
    history = (lock or {}).get("organization_history", [])
    if pin is None:
        if args.json:
            print_json({"organization": None, **({"history": history} if history else {})})
        else:
            print("No organization catalog: the project uses the bundled catalog and its own records.")
            if history and history[-1]["action"] == "stopped":
                last = history[-1]
                print(f"Stopped by {last['by']} on {last['on']} at {last['commit'][:12]}: {last['reason']}")
            print("To follow one: openguildkit org-catalog set --repo PATH --commit SHA shows what it brings.")
        return 0
    catalog = project_catalog(args, state)
    provided = catalog["organization"]["records"]
    used = []
    if (state / "project.json").is_file():
        in_use = used_ids(load_profile(state, catalog), catalog)
        used = [f"{collection}/{record_id}" for collection in COLLECTIONS for record_id in in_use[collection]
                if record_id in provided[collection]]
    rows = replacements(catalog, lock)
    if args.json:
        print_json({"organization": {key: pin[key] for key in ("name", "repo", "commit", "fingerprint", "pinned")
                                     if key in pin},
                    "records": provided, "used": used, "replaced": rows,
                    **({"migrate": MIGRATE_COMMAND} if "repo" in pin else {}), **({"history": history} if history else {})})
        return 0
    pinned = pin["pinned"]
    print(f"Organization catalog: {pin.get('name') or pin['repo']} at {pin['commit'][:12]}, pinned by {pinned['by']} on "
          f"{pinned['on']}: {pinned['reason']}")
    if "repo" in pin:
        print(f"The lock keeps the path of one machine's copy, which another machine and CI cannot resolve: {MIGRATE_COMMAND}.")
    counts = ", ".join(f"{len(ids)} {collection if len(ids) > 1 else collection[:-1]}"
                       for collection, ids in provided.items() if ids) or "no records"
    print(f"It provides {counts}; the profile uses {', '.join(used) or 'none of them'}.")
    for row in rows:
        accepted = row["accepted"]
        print(f"  {row['record']} (accepted by {accepted['by']} on {accepted['on']}: {accepted['reason']})" if accepted
              else f"  {row['record']}: replaced by the project, not accepted: openguildkit org-catalog accept "
                   f"{row['record']} {PERSON} at a terminal.")
    print("A new commit: git -C REPO fetch, then openguildkit org-catalog set --repo REPO --commit SHA.")
    return 0


def _current_records(lock: dict | None, state: Path) -> tuple[dict, str | None]:
    """The organization records of the commit pinned now, or none with the reason they cannot be read."""
    if not (lock or {}).get("organization"):
        return {}, None
    try:
        organization = organization_in(lock, state)
        return records_of(load_catalog(state / "catalog", organization=organization)), None
    except ValueError as error:
        return {}, str(error)


def _print_changes(found: dict, commit: str) -> None:
    lines = [f"+ {name}" + (f" {found['versions'][name]}" if name in found["versions"] else "")
             for name in found["added"]]
    lines += [f"- {name}" for name in found["removed"]]
    lines += [f"~ {change['record']}" + (f" {change['version'][0]} -> {change['version'][1]}" if "version" in change
                                          else "") for change in found["changed"]]
    print(f"Organization catalog at {commit[:12]}: {len(found['added'])} added, {len(found['removed'])} removed, "
          f"{len(found['changed'])} changed.")
    for line in lines:
        print(f"  {line}")


def _set(args, root: Path, state: Path) -> int:
    if (args.by is None) != (args.reason is None):
        raise ValueError("Supply --by and --reason together to pin the commit, or neither to see what it brings.")
    if args.name is not None and not NAME.fullmatch(args.name):
        raise ValueError("--name is lowercase letters, digits, - and _, such as acme. Nothing was written.")
    folder = args.repo.resolve()
    stored = args.name or _stored_repo(args.repo, root)
    read = read_files(stored, args.commit, root, folder if args.name else None)
    target = load_catalog(state / "catalog", central_policy=central_policy(args), organization=read)
    after = records_of(target)
    with copies_read_from(root, {args.name: str(folder)} if args.name else None):
        before, unreadable = _current_records(read_lock(state), state)
    found = changes(before, after)
    found["versions"] = {name: record["version"] for name, record in after.items() if "version" in record}
    if args.by is None:
        if args.json:
            print_json({"repo": stored, "commit": args.commit, "applied": False, "changes": _public(found)})
            return 0
        _print_changes(found, args.commit)
        if unreadable:
            print(f"The commit pinned now cannot be read, so every record shows as added: {unreadable}")
        print(f"To pin it, a person runs at a terminal: openguildkit org-catalog set --repo "
              f"{shell_word(str(args.repo))} --commit {args.commit} {PERSON}")
        return 0
    person = _person(args)
    _confirm(args.commit[:12], "pin this commit of the organization catalog")
    with project_lock(state):
        lock = read_lock(state)
        earlier = (lock or {}).get("organization") or {}
        pin = {"name" if args.name else "repo": stored, "commit": args.commit, "fingerprint": read["fingerprint"],
               "pinned": person, "exceptions": earlier.get("exceptions", [])}
        touched = _write_pinned(root, state, args, lock, read, pin, {"action": "pinned", "commit": args.commit, **person})
    if args.json:
        print_json({"repo": stored, "commit": args.commit, "applied": True, "changes": _public(found)})
    else:
        _print_changes(found, args.commit)
        print(f"Pinned the organization catalog at {args.commit[:12]} ({stored}), by {person['by']}.")
        if args.name:
            print(f"Each machine points at its copy: {variable_name(args.name)}=PATH (guard --ci: --org-catalog "
                  f"{args.name}=PATH).")
        print_touched(touched)
        print("Next: openguildkit check; openguildkit profile add pack ID adds one of its packs.")
    return 0


def _public(found: dict) -> dict:
    return {key: found[key] for key in ("added", "removed", "changed")}


def _write_pinned(root: Path, state: Path, args, lock: dict | None, read: dict | None, pin: dict | None,
                  entry: dict) -> list:
    """Under the project lock: rewrite the instructions and the catalog lock for the organization catalog pinned
    (pin) or for none (None), add entry (who, when, why and the commit) to the history the lock keeps, and return the
    tasks the change touches. A profile that uses a record the new catalog lacks stops it, and nothing is written."""
    live = load_catalog(state / "catalog", central_policy=central_policy(args), organization=read)
    bundled = {collection: set(entries) for collection, entries in load_catalog().items()}
    catalog = apply_lock(live, lock)
    if not (state / "project.json").is_file():
        # Before init: the lock holds the pin alone, and init --answers reads the organization's records from it.
        built = {"schema_version": 1, "generated_by": f"openguildkit {package_version()}",
                 "records": {collection: {} for collection in COLLECTIONS}}
        touched = []
    else:
        try:
            profile = load_profile(state, catalog)
        except ValueError as error:
            remedy = "" if pin is None else ", or pin another commit"
            raise ValueError(f"{error} Without it, the profile uses a record the catalog no longer provides: remove it "
                             f"from the profile first (openguildkit profile remove pack ID {PERSON}){remedy}. Nothing "
                             "was written.") from None
        touched = tasks_touched(state, profile, catalog)
        sync_instructions(root, profile, catalog)
        built = build_lock(profile, catalog, bundled, lock)
    built.pop("organization", None)
    if pin is not None:
        built["organization"] = pin
    built["organization_history"] = [*(lock or {}).get("organization_history", []), entry]
    write_lock(state, built)
    return touched


def _accept(args, state: Path) -> int:
    person = _person(args)
    lock = read_lock(state)
    if not (lock or {}).get("organization"):
        raise ValueError("The project follows no organization catalog: openguildkit org-catalog show.")
    catalog = installed_catalog(args, state)[0]
    replaced = catalog["organization"]["replaced"]
    if args.record not in replaced:
        listed = ", ".join(replaced) or "none"
        raise ValueError(f"{args.record} is not a project record that replaces an organization record (replaced now: "
                         f"{listed}). openguildkit org-catalog show lists them.")
    _confirm(args.record, "accept this replacement")
    with project_lock(state):
        lock = read_lock(state)
        pin = lock["organization"]
        kept = [item for item in pin.get("exceptions", []) if item["record"] != args.record]
        pin["exceptions"] = [*kept, {"record": args.record, "digest": replaced[args.record], **person}]
        write_lock(state, lock)
    print(f"Accepted: the project replaces {args.record} of the organization catalog, by {person['by']}. A new "
          "edition of that record needs a new acceptance.")
    return 0


def _off(args, root: Path, state: Path) -> int:
    person = _person(args)
    lock = read_lock(state)
    if not (lock or {}).get("organization"):
        print("The project follows no organization catalog. Nothing was written.")
        return 0
    _confirm("off", "stop following the organization catalog")
    with project_lock(state):
        lock = read_lock(state)
        left = (lock or {}).get("organization", {}).get("commit")
        touched = _write_pinned(root, state, args, lock, None, None, {"action": "stopped", "commit": left, **person})
    print(f"The project no longer follows the organization catalog, by {person['by']}: {person['reason']}")
    print_touched(touched)
    return 0


def run(args, root: Path, state: Path) -> int:
    if args.org_action == "show":
        return _show(args, root, state)
    if args.org_action == "set":
        return _set(args, root, state)
    if args.org_action == "accept":
        return _accept(args, state)
    return _off(args, root, state)
