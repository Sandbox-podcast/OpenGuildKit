"""The commands that take a task's work to readers: deliverable, and docs export and share.

Entry: run.
Tests: tests/test_deliverables.py, tests/test_publishing.py.
"""

import re
import sys
from pathlib import Path

from .command import Command
from .deliverables import draft_problems, launch_notice, load_deliverables, new_draft, project_path, utm_link
from .errors import unknown
from .publishing import (
    add_share,
    export_docs,
    project_overview,
    revoke_share,
    same_access,
    share_status,
    shared_addresses,
    space_neighbours,
)
from .storage import print_json, project_lock, write_json
from .tasks import read_task, task_path
from .wording import plural


def deliverable(args, root: Path, state: Path, profile: dict, catalog: dict) -> int:
    templates = load_deliverables(catalog, state / "catalog" / "deliverables")
    action = args.deliverable_action
    if action == "list":
        width = max((len(key) for key in templates), default=0)
        for template in templates.values():
            method = f" (method {template['method']})" if template.get("method") else ""
            print(f"{template['id']:<{width}} {template['title']}{method} [{', '.join(template['brains'])}]")
        return 0
    if action == "utm":
        names = ("source", "medium", "campaign", "content", "term")
        print(utm_link(args.url, {name: getattr(args, name) for name in names}))
        return 0
    if action == "check":
        path = project_path(root, state, args.path, "deliverable check")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeError as error:
            raise ValueError(f"{args.path} is not UTF-8 text ({error}): save the draft as UTF-8.") from error
        match = re.search(r'^deliverable: "([a-z0-9-]+)"$', text, re.MULTILINE)
        if not match or match.group(1) not in templates:
            raise ValueError(f"{args.path} is not a draft written by openguildkit deliverable new.")
        problems = draft_problems(templates[match.group(1)], text)
        for problem in problems:
            print(f"- {problem}")
        if not problems:
            print("Ready for review by " + ", ".join(templates[match.group(1)]["brains"]))
        return 1 if problems else 0
    if args.id not in templates:
        raise ValueError(unknown("deliverable", args.id, "deliverable list"))
    template = templates[args.id]
    if action == "show":
        print(f"{template['title']} [{template['id']}]\n{template['description']}\nBefore starting the tool:")
        for line in launch_notice(template):
            print(f"  - {line}")
        print("Checks:")
        for check in template["checks"]:
            print(f"  - {check['id']}: {check['verification']}")
        return 0
    task = read_task(state, args.task)
    output = project_path(root, state, args.output, "--output")
    entry = new_draft(template, task, args.tool, profile.get("tools", []), output)
    with project_lock(state):
        current = read_task(state, args.task)
        write_json(task_path(state, args.task), {**current, "deliverables": [*current.get("deliverables", []), entry]})
    print("Before starting the tool:")
    for line in launch_notice(template):
        print(f"  - {line}")
    print(f"Draft written to {args.output.as_posix()}")
    return 0


def docs(args, root: Path, state: Path, profile: dict, catalog: dict) -> int:
    if args.docs_action == "export":
        tasks = [item.strip() for item in args.tasks.split(",") if item.strip()]
        sections = tuple(item.strip() for item in args.sections.split(",") if item.strip())
        output = project_path(root, state, args.output, "--output")
        openapi = project_path(root, state, args.openapi, "--openapi") if args.openapi else None
        result = export_docs(state, tasks, output, args.doc_version, sections, openapi, profile["name"],
                             project_overview(profile, catalog))
        for path in result["written"]:
            print(f"wrote {path}")
        for path in result["removed"]:
            print(f"removed {path}")
        for path in result["kept"]:
            print(f"kept {path}: not a page this export wrote inside {args.output.as_posix()}, left in place")
        for warning in result["warnings"]:
            print(f"OpenGuildKit: {warning}", file=sys.stderr)
        return 0
    if args.share_action == "add":
        if not (args.deliverable and args.until and args.portal and args.by):
            raise ValueError("docs share add needs --deliverable, --recipient, --until, --portal and --by.")
        share = add_share(state, args.deliverable, args.recipient, args.until, args.portal, args.by, args.dedicated_space)
        _print_share_added(share)
        for given in dict.fromkeys(args.recipient):
            if given not in share["recipients"]:
                kept = shared_addresses(share, {"recipients": [given]})[0]
                print(f"OpenGuildKit: {given} and {kept} differ only in case, so they are one reader: the share records "
                      f"{kept}.", file=sys.stderr)
        for other in space_neighbours(state, share):
            print(f"OpenGuildKit: space {share['space']} also carries {other['deliverable']} (share {other['id']}): the "
                  f"recipients of each share can read both deliverables. To share {share['deliverable']} on its own, "
                  "publish it in a space of its own and record it with --dedicated-space.", file=sys.stderr)
        for other in same_access(state, share, running=True):
            for recipient in shared_addresses(share, other):
                print(f"OpenGuildKit: {recipient} already has access to space {share['space']} through share {other['id']} "
                      f"(until {other['until']}). Documentalist keeps one access per address and space: give it the later "
                      f"last day, {max(share['until'], other['until'])}, in the portal; removing it there ends both shares, "
                      "so revoke them together.", file=sys.stderr)
        return 0
    if args.share_action == "revoke":
        if not args.share_id or not args.by:
            raise ValueError("docs share revoke needs --id and --by.")
        share = revoke_share(state, args.share_id, args.by)
        print("revoked")
        space = share["space"] or f"of the portal {share['portal']}"
        print(f"\"Retirer l'accès\" in Documentalist removes an address from the whole space {space}, not only from "
              f"{share['deliverable']}.")
        others = same_access(state, share)
        if others:
            shared = sorted({recipient for other in others for recipient in shared_addresses(share, other)})
            print(f"Other shares give {', '.join(shared)} the same space: if you removed that access there, they lost it "
                  "too. Record each one:")
            for other in others:
                print(f"  openguildkit docs share revoke --id {other['id']} --by INITIALS   "
                      f"# {', '.join(other['recipients'])}, {other['deliverable']}, until {other['until']}")
        return 0
    if args.share_action == "verify":
        if not args.portal or not args.user:
            raise ValueError("docs share verify needs --portal and --user; the password is requested at the terminal.")
        from .portal_verification import verify_portal
        report = verify_portal(state, args.portal, args.user)
        if args.json:
            print_json(report)
        else:
            print(f"{report['space']}: {report['source']} at {report['checked_at']}")
            print(report["scope"])
            if report["problem"]:
                print(report["problem"])
            for item in report["rows"]:
                print(f"  {item['recipient']}: register until {item['register_until'] or 'no running share'}; "
                      f"portal {_portal_state(item)}; {item['status']}")
                if item.get("action"):
                    print(f"    {item['action']}")
        return 0 if report["source"] == "documentalist-api" and all(row["status"] == "matches" for row in report["rows"]) else 1
    rows = share_status(state)
    if args.json:
        print_json(rows)
    elif not rows:
        print("No share recorded.")
    else:
        for row in rows:
            _print_share_row(row)
    expired = [row for row in rows if row["state"].startswith("expired")]
    # A dedicated space that carries another deliverable no longer isolates it: the register was edited by hand.
    breached = [row for row in rows if row["dedicated"] and row["also_in_space"]]
    return 1 if args.share_action == "check" and (expired or breached) else 0


def _print_share_added(share: dict) -> None:
    """Say what the recipients really get and that the end date is the owner's to keep."""
    print(f"Share {share['id']} recorded. Its perimeter is the whole space {share['space']}: Documentalist shows the "
          f"recipients every published page of that space, not only {share['deliverable']}. Publish the deliverable in a "
          "space that holds only it, or hide the other pages.")
    if share.get("dedicated"):
        print(f"Space {share['space']} is recorded as dedicated to {share['deliverable']}: the register refuses another "
              "deliverable in it. OpenGuildKit cannot see what the space publishes: check from a reader session that "
              "its navigation and search show only this deliverable.")
    print("Invite the recipients now in that space's reader settings (magic link mode).")
    print(f"Set the last day {share['until']} in Documentalist if supported. On older versions remove access there "
          f"after that day, then run openguildkit docs share revoke --id {share['id']} --by INITIALS. "
          "The local check is a reminder; it does not contact the portal.")


def _portal_state(item: dict) -> str:
    """What the portal's invitation settings said for one recipient of docs share verify."""
    if item.get("source") != "documentalist-api":
        return "not verified"
    if not item.get("invited"):
        return "not invited"
    state = "open" if item.get("policy_active") else "ended"
    return f"until {item['portal_until']} ({state})" if item.get("portal_until") else "invited with no end date (open)"


def _print_share_row(row: dict) -> None:
    """One share with its perimeter and state; one past its last day says which access to remove and which to keep."""
    space = row["space"] or "unknown: the portal address names no /p/SPACE"
    print(f"{row['id']} {row['deliverable']} (whole space {space}) until {row['until']} "
          f"({plural(len(row['recipients']), 'recipient')}): {row['state']}")
    if row["also_in_space"]:
        dedicated = " although the space is recorded as dedicated to this deliverable" if row["dedicated"] else ""
        print(f"  its recipients can also read {', '.join(row['also_in_space'])}, shared through the same space{dedicated}")
    if row.get("portal_observation"):
        observed = row["portal_observation"]
        print(f"  last portal observation: {observed['source']} at {observed['checked_at']} (may be outdated)")
        for item in observed["rows"]:
            print(f"    {item.get('recipient')}: {item.get('status')}, portal {_portal_state(item)}")
    for recipient in row["remove"]:
        print(f"  remove {recipient} from space {space} in Documentalist (\"Retirer l'accès\")")
    for recipient, other in sorted(row["kept"].items()):
        print(f"  keep {recipient}: share {other['share']} gives the same space until {other['until']}")
    if row["remove"]:
        print(f"  then record it: openguildkit docs share revoke --id {row['id']} --by INITIALS")


HANDLERS = {
    "deliverable": lambda command: deliverable(command.args, command.root, command.state, command.profile, command.catalog),
    "docs": lambda command: docs(command.args, command.root, command.state, command.profile, command.catalog),
}


def run(command: Command) -> int:
    return HANDLERS[command.args.command](command)
