"""Turn verified work into documentation pages and keep track of who it is shared with.

The export writes a Markdown tree that Documentalist imports from a Git repository:
`reference/` for the Reference tab, `learn/` for Learn, `blog/` for dated release notes, each
page ordered by its `sidebar_position`, plus `project/overview.md` and a root `SUMMARY.md` for
readers of the repository. Paths stay stable, so a sync after a new export updates the same pages.
Only tasks completed with recorded checks can be exported, and only the fields listed here
leave the project: no review, evidence or internal note.

The share register records what was shared, with whom, through which portal space and until when.
Documentalist gives a reader a whole space and keeps no end date, so the register is a reminder
the owner acts on in the portal, and its dates follow the real clock.
"""

import ipaddress
import json
import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from . import clock
from .deliverables import project_path
from .project import pack_scopes, rule_plan, rule_text
from .storage import project_lock, read_json, write_json, write_text
from .tasks import read_task
from .workflow import objections

MANIFEST = ".openguildkit-export.json"
SECTIONS = ("project", "reference", "learn", "blog")
PROJECT_PAGE = "project/overview.md"
SHARES_DIR = "shares"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# The only paths an export writes; a manifest entry of another shape is never removed.
_EXPORTED = re.compile(r"(?:(?:reference|learn|blog)/[^/]+\.md|openapi/[^/]+|project/overview\.md|SUMMARY\.md|README\.md)")
MAX_SHARE_DAYS = 366


def _title(task: dict) -> str:
    return task["brief"].strip().splitlines()[0].rstrip(".")[:120]


def _frontmatter(fields: dict) -> str:
    return "---\n" + "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n" for key, value in fields.items()) + "---\n\n"


def _criteria(task: dict) -> list[str]:
    return [item["criterion"] for item in task.get("result", {}).get("criteria", []) if item["status"] == "met"]


def _body(task: dict) -> list[str]:
    """The brief after its first line, which is already the title; nothing when the brief is one line."""
    rest = "\n".join(task["brief"].strip().splitlines()[1:]).strip()
    return [rest, ""] if rest else []


def _behaviour(task: dict) -> list[str]:
    """The expected outcome and the criteria met, each said once."""
    seen, lines = set(), []
    for text in [task.get("answers", {}).get("outcome") or "", *_criteria(task)]:
        key = " ".join(text.casefold().split()).rstrip(".")
        if key and key not in seen:
            seen.add(key)
            lines.append(f"- {text}")
    return lines


def _verification(task: dict) -> str:
    """What was verified, what did not apply and what stayed open, so the page does not overstate the checks."""
    checks = task.get("result", {}).get("checks", [])
    passed = sum(item["status"] == "passed" for item in checks)
    skipped = sum(item["status"] == "not-applicable" for item in checks)
    line = f"Checks before release: {passed} passed, {skipped} not applicable, {len(checks) - passed - skipped} open."
    if "deliberation" in task:
        disagreements = len(task["deliberation"]["open"])
        if disagreements:
            line += f" {disagreements} disagreement(s) between the boards were left open."
    elif task.get("review"):
        pending = len(objections(task["review"], task["consultation"].get("domains")))
        if pending:
            line += f" {pending} objection(s) between the boards were not deliberated before the approval."
    return line


def _pages(task: dict, position: int, version: str, sections: tuple[str, ...]) -> dict[str, str]:
    title = _title(task)
    result = task.get("result", {})
    delivered = result.get("pull_request") or result.get("revision") or "not recorded"
    outcome = task.get("answers", {}).get("outcome")
    common = {"title": title, "source_task": task["id"], "project_version": version}
    pages = {}
    if "reference" in sections:
        lines = [f"# {title}", "", *_body(task)]
        if _behaviour(task):
            lines += ["## Behaviour", "", *_behaviour(task), ""]
        lines += ["## Verification", "", _verification(task), "",
                  "## Source", "", f"Delivered in {delivered}, project version {version}.", ""]
        pages[f"reference/{task['id']}.md"] = _frontmatter({**common, "sidebar_position": position}) + "\n".join(lines)
    if "learn" in sections:
        affected = task.get("answers", {}).get("affected")
        lines = [f"# {title}", "", "<!-- Generated from an approved OpenGuildKit task. Review before publishing. -->", ""]
        lines += [f"Who it is for: {affected}", ""] if affected else []
        lines += ["## What you can do", "", outcome or task["brief"].strip(), ""]
        if _criteria(task):
            lines += ["## What to expect", "", *[f"- {criterion}" for criterion in _criteria(task)], ""]
        pages[f"learn/{task['id']}.md"] = _frontmatter({**common, "sidebar_position": position}) + "\n".join(lines)
    if "blog" in sections:
        day = (task.get("completed_at") or task["created_at"])[:10]
        lines = [f"# {title}", "", *_body(task), f"Available in version {version}.", ""]
        pages[f"blog/{day}-{task['id']}.md"] = _frontmatter({**common, "date": day}) + "\n".join(lines)
    return pages


def project_overview(profile: dict, catalog: dict) -> dict:
    """What the Project page shows: profile fields, active packs with their rules, and boards.

    Component paths, check commands and anything outside the profile and catalog stay out.
    """
    plan, scopes = rule_plan(profile, catalog), pack_scopes(profile, catalog)
    packs = [{"id": item["id"], "title": item["title"], "version": item["version"], "components": scopes.get(item["id"]),
              "rules": [rule_text(rule)[0] for rule in catalog["packs"][item["id"]]["rules"]]} for item in plan["packs"]]
    # Every board's title: the export lists only those its tasks consulted.
    boards = sorted(catalog["boards"])
    return {"name": profile["name"], "sector": profile.get("sector"), "stack": profile.get("stack", []),
            "components": [{"id": item["id"], "stack": item["stack"]} for item in profile.get("components", [])],
            "conventions": profile.get("conventions", []), "packs": packs,
            "boards": [{"id": board_id, "title": catalog["boards"][board_id]["title"]} for board_id in boards]}


def _project_page(overview: dict, version: str) -> str:
    lines = [f"# {overview['name']}", "", "<!-- Generated from the OpenGuildKit project profile. Review before publishing. -->", ""]
    lines += [f"Sector: {overview['sector']}", ""] if overview["sector"] else []
    lines += [f"Stack: {', '.join(overview['stack'])}", ""] if overview["stack"] else []
    if overview["components"]:
        lines += ["## Components", "", *[f"- {item['id']}: {', '.join(item['stack'])}" for item in overview["components"]], ""]
    if overview["conventions"]:
        lines += ["## Conventions", "", *[f"- {item}" for item in overview["conventions"]], ""]
    lines += ["## Rules in force", ""]
    for pack in overview["packs"]:
        lines += [f"### {pack['title']} ({pack['id']}, version {pack['version']})", ""]
        lines += [f"Applies to: {', '.join(pack['components'])}", ""] if pack["components"] else []
        lines += [*[f"- {rule}" for rule in pack["rules"]], ""]
    lines += ["## Boards consulted", "", "The boards that reviewed the documented changes before a person approved them.", "",
              *[f"- {item['title']} ({item['id']})" for item in overview["boards"]], ""]
    front = {"title": overview["name"], "project_version": version, "sidebar_position": 0}
    return _frontmatter(front) + "\n".join(lines)


def _inside(output: Path, relative: str) -> bool:
    """True when the path stays in the output folder once links and `..` are resolved."""
    if Path(relative).is_absolute() or Path(relative).anchor:
        return False
    try:
        (output / relative).resolve().relative_to(output.resolve())
    except ValueError:
        return False
    return True


def export_docs(state: Path, task_ids: list[str], output: Path, version: str,
                sections: tuple[str, ...] = SECTIONS, openapi: Path | None = None, project: str = "Project",
                overview: dict | None = None) -> dict:
    """Write the selected completed tasks, and the project page when given, as documentation pages."""
    unknown = sorted(set(sections) - set(SECTIONS))
    if unknown or not sections:
        raise ValueError(f"Choose sections among {', '.join(SECTIONS)}.")
    tasks = [read_task(state, task_id) for task_id in task_ids]
    not_done = [task["id"] for task in tasks if task["status"] not in ("done", "done-with-reservations")]
    if not_done:
        raise ValueError(f"Only completed tasks with recorded checks can be documented: {', '.join(not_done)}.")
    manifest_path = output / MANIFEST
    previous = read_json(manifest_path)["files"] if manifest_path.is_file() else []
    if output.exists() and not manifest_path.is_file() and any(output.iterdir()):
        raise ValueError(f"{output} is not empty and was not created by openguildkit docs export.")
    pages = {}
    for position, task in enumerate(tasks, start=1):
        pages.update(_pages(task, position, version, sections))
    summary = [f"# {project}", ""]
    if "project" in sections and overview is not None:
        consulted = list(dict.fromkeys(board for task in tasks for board in task["consultation"]["boards"]))
        titles = {item["id"]: item["title"] for item in overview["boards"]}
        boards = [{"id": board, "title": titles.get(board, board)} for board in consulted]
        pages[PROJECT_PAGE] = _project_page({**overview, "boards": boards}, version)
        summary += ["## Project", "", f"- [Overview]({PROJECT_PAGE})", ""]
    for section in ("reference", "learn"):
        entries = [path for path in pages if path.startswith(f"{section}/")]
        if entries:
            summary += [f"## {section.capitalize()}", ""] + [
                f"- [{_title(read_task(state, Path(path).stem))}]({path})" for path in entries] + [""]
    pages["SUMMARY.md"] = "\n".join(summary)
    pages["README.md"] = f"# {project}\n\nDocumentation for version {version}, generated from completed OpenGuildKit tasks.\n"
    if openapi is not None:
        pages[f"openapi/{openapi.name}"] = openapi.read_text(encoding="utf-8")
    escaping = sorted(path for path in pages if not _inside(output, path))
    if escaping:
        raise ValueError(f"{', '.join(escaping)} would be written outside {output}: remove the symbolic link and export again.")
    for relative, content in pages.items():
        write_text(output / relative, content)
    stale = [path for path in previous if isinstance(path, str) and path not in pages]
    # The manifest is committed with the pages: anyone can edit it, so only remove what an export wrote.
    removed = [path for path in stale if _EXPORTED.fullmatch(path) and _inside(output, path)]
    kept = [path for path in previous if path not in pages and path not in removed]
    for relative in removed:
        (output / relative).unlink(missing_ok=True)
    write_json(manifest_path, {"version": version, "tasks": task_ids, "files": sorted(pages)})
    return {"written": sorted(pages), "removed": removed, "kept": kept}


def _shares_path(state: Path) -> Path:
    return state / SHARES_DIR / "shares.json"


def _load_shares(state: Path) -> list[dict]:
    path = _shares_path(state)
    return read_json(path)["shares"] if path.is_file() else []


def _shared_item(state: Path, deliverable: str) -> None:
    """What a recipient receives: an existing file of the project, or the folder of a documentation export."""
    target = project_path(state.parent, state, deliverable, "--deliverable")
    shown = Path(deliverable).as_posix()
    if not target.exists():
        raise ValueError(f"--deliverable {shown} does not exist. Name the file you share, or the folder that "
                         "openguildkit docs export wrote.")
    if target.is_dir() and not (target / MANIFEST).is_file():
        raise ValueError(f"--deliverable {shown} is a folder that holds no documentation export. Name the file you "
                         "share, or the folder that openguildkit docs export wrote.")


def _loopback(host: str) -> bool:
    """True for an address of this machine, where a local Documentalist runs without TLS."""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def portal_space(portal: str) -> str:
    """The space a portal address opens, written HOST/p/SPACE: Documentalist shows a reader every page of it.

    The address is https, or http for an instance on this machine (localhost, 127.0.0.1, ::1).
    """
    address = urlsplit(portal.strip())
    try:
        host, port = address.hostname, address.port
    except ValueError:
        host = port = None
    secure = address.scheme == "https" or (address.scheme == "http" and bool(host) and _loopback(host))
    if not host or not secure:
        raise ValueError("Give the https address of the Documentalist portal, such as https://docs.example.org/p/support-portal "
                         "(http only for an instance on this machine: localhost, 127.0.0.1 or ::1).")
    parts = address.path.split("/")
    if len(parts) < 3 or parts[1] != "p" or not parts[2]:
        raise ValueError(f"--portal {portal} names no space. Give the portal of the space you share, https://HOST/p/SPACE: "
                         "the recipients see every published page of that space.")
    shown = f"[{host}]" if ":" in host else host
    return f"{shown}{f':{port}' if port else ''}/p/{parts[2]}"


def _space(share: dict) -> str | None:
    """The space a share opens; a share recorded before the space was kept gets it from its portal."""
    if share.get("space"):
        return share["space"]
    try:
        return portal_space(share["portal"])
    except ValueError:
        return None


def add_share(state: Path, deliverable: str, recipients: list[str], until: str, portal: str, by: str) -> dict:
    """Record a share before creating it in Documentalist: what, for whom, through which space, until when."""
    if not deliverable.strip() or not by.strip():
        raise ValueError("Name the deliverable and the owner of the share.")
    _shared_item(state, deliverable.strip())
    bad = [item for item in recipients if not _EMAIL.fullmatch(item)]
    if not recipients or bad:
        raise ValueError(f"List the recipients' email addresses{': ' + ', '.join(bad) if bad else ''}.")
    _share_end(until)
    space = portal_space(portal)
    share = {"id": uuid.uuid4().hex[:8], "deliverable": deliverable.strip(), "recipients": sorted(set(recipients)),
             "until": until, "portal": portal, "space": space, "by": by.strip(),
             "created_at": clock.real_timestamp(), "revoked_at": None}
    with project_lock(state):
        write_json(_shares_path(state), {"shares": [*_load_shares(state), share]})
    return share


def _share_end(until: str) -> date:
    """The last day of access: a real YYYY-MM-DD date, after today and within a year, on the real clock."""
    try:
        end = date.fromisoformat(until) if _DAY.fullmatch(until) else None
    except ValueError:
        end = None
    if end is None:
        raise ValueError(f"Give the last day of access as YYYY-MM-DD, not {until!r}.")
    today = clock.real_today()
    if end <= today:
        raise ValueError("A share ends after today.")
    if end > today + timedelta(days=MAX_SHARE_DAYS):
        raise ValueError(f"A share lasts at most {MAX_SHARE_DAYS} days. Record a new share when it ends to extend it.")
    return end


def _same_access(shares: list[dict], share: dict, today: date | None) -> list[dict]:
    space, recipients = _space(share), set(share["recipients"])
    return [item for item in shares
            if item["id"] != share["id"] and not item["revoked_at"] and space and _space(item) == space
            and recipients & set(item["recipients"]) and (today is None or date.fromisoformat(item["until"]) >= today)]


def same_access(state: Path, share: dict, running: bool = False) -> list[dict]:
    """The other shares not revoked that give one of the share's recipients the same space.

    Documentalist keeps one access per address and space, so these shares grant and lose that access together.
    With `running`, only those whose last day is not past on the real clock.
    """
    return _same_access(_load_shares(state), share, clock.real_today() if running else None)


def revoke_share(state: Path, share_id: str, by: str) -> dict:
    """Record that the access was removed in Documentalist; the first revocation stays. Returns it with its space."""
    if not by.strip():
        raise ValueError("Name the person who removed the access with --by.")
    with project_lock(state):
        shares = _load_shares(state)
        share = next((item for item in shares if item["id"] == share_id), None)
        if share is None:
            raise ValueError(f"Unknown share {share_id}. Run openguildkit docs share list.")
        if share["revoked_at"]:
            raise ValueError(f"Share {share_id} was already revoked by {share.get('revoked_by') or 'someone'} on {share['revoked_at'][:10]}.")
        share["revoked_at"] = clock.real_timestamp()
        share["revoked_by"] = by.strip()
        write_json(_shares_path(state), {"shares": shares})
    return {**share, "space": _space(share)}


def share_status(state: Path, today: date | None = None) -> list[dict]:
    """Each share with its space and state, on the real clock: active, expired, covered or revoked.

    A share past its last day is expired when some of its addresses must be removed from the space (listed in
    `remove`), and covered when other running shares of the same space still give every address access (listed in
    `kept`, with the share that ends last): there is nothing to remove until those shares end.
    """
    today = today or clock.real_today()
    shares, rows = _load_shares(state), []
    for share in shares:
        row = {**share, "space": _space(share), "remove": [], "kept": {}}
        if share["revoked_at"]:
            row["state"] = "revoked"
        elif date.fromisoformat(share["until"]) >= today:
            row["state"] = "active"
        else:
            running = _same_access(shares, share, today)
            for recipient in share["recipients"]:
                covering = [item for item in running if recipient in item["recipients"]]
                if covering:
                    last = max(covering, key=lambda item: item["until"])
                    row["kept"][recipient] = {"share": last["id"], "until": last["until"]}
                else:
                    row["remove"].append(recipient)
            row["state"] = ("expired: remove the access in Documentalist" if row["remove"]
                            else "covered: other shares keep the same access, nothing to remove yet")
        rows.append(row)
    return rows
