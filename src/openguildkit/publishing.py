"""Exports verified work as documentation pages for Documentalist and keeps the share register.

The export writes a Markdown tree that Documentalist imports from a Git repository:
`reference/` for the Reference tab, `learn/` for Learn, `blog/` for dated release notes, each
page ordered by its `sidebar_position`, plus `project/overview.md` and a root `SUMMARY.md` for
readers of the repository. Paths stay stable, so a sync after a new export updates the same pages.
Only tasks completed with recorded checks can be exported, and only the fields listed here
leave the project: no review, evidence or internal note.

The share register records what was shared, with whom, through which portal space and until when.
Documentalist gives a reader a whole space. The local register follows the real clock; a separate
observation may compare it with a compatible portal's invitation settings. A share can mark its space as
dedicated to its deliverable: the register then refuses another deliverable in that space, so that
one space per deliverable gives each deliverable its own reader list.

Entry: project_overview, export_docs, load_shares, portal_space, share_space, add_share
Tests: tests/test_publishing.py
"""

import ipaddress
import json
import posixpath
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import clock
from .deliverables import project_path
from .errors import OgkError, unknown
from .project_instructions import rule_text
from .project_rules import pack_scopes, rule_plan
from .records import Catalog, Profile
from .sensitive import WHERE, personal_data_kinds, redact_data, refuse_link_credentials
from .storage import project_lock, read_json, write_json, write_text
from .task_files import read_task
from .wording import plural
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
_DEFAULT_PORTS = {"https": 443, "http": 80}


def _title(task: Mapping[str, Any]) -> str:
    return task["brief"].strip().splitlines()[0].rstrip(".")[:120]


def _frontmatter(fields: dict) -> str:
    return "---\n" + "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n" for key, value in fields.items()) + "---\n\n"


def _criteria(task: Mapping[str, Any]) -> list[str]:
    return [item["criterion"] for item in task.get("result", {}).get("criteria", []) if item["status"] == "met"]


def _body(task: Mapping[str, Any], title: str) -> list[str]:
    """Keep any brief text that does not fit in the title."""
    lines = task["brief"].strip().splitlines()
    if lines[0].rstrip(".") == title:
        lines = lines[1:]
    rest = "\n".join(lines).strip()
    return [rest, ""] if rest else []


def _behaviour(task: Mapping[str, Any]) -> list[str]:
    """The expected outcome and the criteria met, each said once."""
    seen, lines = set(), []
    for text in [task.get("answers", {}).get("outcome") or "", *_criteria(task)]:
        key = " ".join(text.casefold().split()).rstrip(".")
        if key and key not in seen:
            seen.add(key)
            lines.append(f"- {text}")
    return lines


def _verification(task: Mapping[str, Any]) -> str:
    """What was verified, what did not apply and what stayed open, so the page does not overstate the checks."""
    checks = task.get("result", {}).get("checks", [])
    passed = sum(item["status"] == "passed" for item in checks)
    skipped = sum(item["status"] == "not-applicable" for item in checks)
    line = f"Checks before release: {passed} passed, {skipped} not applicable, {len(checks) - passed - skipped} open."
    if "deliberation" in task:
        disagreements = len(task["deliberation"]["open"])
        if disagreements:
            line += f" {plural(disagreements, 'disagreement')} between the boards {'was' if disagreements == 1 else 'were'} left open."
    elif task.get("review"):
        pending = len(objections(task["review"], task["consultation"].get("domains")))
        if pending:
            line += f" {plural(pending, 'objection')} between the boards {'was' if pending == 1 else 'were'} not deliberated before the approval."
    return line


def _pages(task: Mapping[str, Any], position: int, version: str, sections: tuple[str, ...]) -> dict[str, str]:
    title = _title(task)
    result = task.get("result", {})
    delivered = result.get("pull_request") or result.get("revision") or "not recorded"
    outcome = task.get("answers", {}).get("outcome")
    common = {"title": title, "source_task": task["id"], "project_version": version}
    pages = {}
    if "reference" in sections:
        lines = [f"# {title}", "", *_body(task, title)]
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
        lines = [f"# {title}", "", *_body(task, title), f"Available in version {version}.", ""]
        pages[f"blog/{day}-{task['id']}.md"] = _frontmatter({**common, "date": day}) + "\n".join(lines)
    return pages


def project_overview(profile: Profile, catalog: Catalog) -> dict:
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


def _exported_files(manifest_path: Path) -> list[str]:
    """The files the last export wrote, as its manifest lists them; a manifest without that list is refused by name."""
    if not manifest_path.is_file():
        return []
    files = read_json(manifest_path).get("files")
    if not isinstance(files, list) or not all(isinstance(path, str) for path in files):
        raise OgkError("OGK-PUBLISH-001", f"{manifest_path.name} is not an export manifest: its \"files\" must be a list of paths. "
                         f"Restore {manifest_path.as_posix()} from git, or export to an empty folder.")
    return files


def _task_pages(tasks: Sequence[Mapping[str, Any]], version: str, sections: tuple[str, ...]) -> tuple[dict, list[str], dict]:
    """The pages of each task, with what may hold a credential replaced; the warnings on what they replaced and on
    the personal data they show; and each task as published."""
    pages, warnings, published = {}, [], {}
    for position, task in enumerate(tasks, start=1):
        # What leaves the project is checked again: a record written before, or by hand, may hold what the CLI now refuses.
        shown = {**task, **{key: redact_data(task[key]) for key in ("brief", "answers", "result") if key in task}}
        written = _pages(shown, position, version, sections)
        if shown != task:
            warnings.append(f"{task['id']}: replaced a possible credential with a placeholder before publishing it: {WHERE}.")
        kinds = list(dict.fromkeys(kind for text in written.values() for kind in personal_data_kinds(text)))
        if kinds:
            warnings.append(f"{task['id']}: the pages contain {' and '.join(kinds)}, and Documentalist shows them to every "
                            "reader: keep personal data out unless it is a role address.")
        pages.update(written)
        published[task["id"]] = shown
    return pages, warnings, published


def _summary_page(tasks: Sequence[Mapping[str, Any]], pages: dict, published: dict, project: str, version: str,
                  sections: tuple[str, ...], overview: dict | None) -> str:
    """The SUMMARY.md of the export, adding the project page to pages when the project section is asked."""
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
                f"- [{_title(published[Path(path).stem])}]({path})" for path in entries] + [""]
    return "\n".join(summary)


def export_docs(state: Path, task_ids: list[str], output: Path, version: str,
                sections: tuple[str, ...] = SECTIONS, openapi: Path | None = None, project: str = "Project",
                overview: dict | None = None) -> dict:
    """Write the selected completed tasks, and the project page when given, as documentation pages."""
    unknown = sorted(set(sections) - set(SECTIONS))
    if unknown or not sections:
        raise OgkError("OGK-PUBLISH-016", f"Choose sections among {', '.join(SECTIONS)}.")
    tasks = [read_task(state, task_id) for task_id in task_ids]
    not_done = [task["id"] for task in tasks if task["status"] not in ("done", "done-with-reservations")]
    if not_done:
        raise OgkError("OGK-PUBLISH-002", f"Only completed tasks with recorded checks can be documented: {', '.join(not_done)}.")
    manifest_path = output / MANIFEST
    previous = _exported_files(manifest_path)
    if output.exists() and not manifest_path.is_file() and any(output.iterdir()):
        raise OgkError("OGK-PUBLISH-003", f"{output} is not empty and was not created by openguildkit docs export.")
    pages, warnings, published = _task_pages(tasks, version, sections)
    pages["SUMMARY.md"] = _summary_page(tasks, pages, published, project, version, sections, overview)
    pages["README.md"] = f"# {project}\n\nDocumentation for version {version}, generated from completed OpenGuildKit tasks.\n"
    if openapi is not None:
        try:
            pages[f"openapi/{openapi.name}"] = openapi.read_text(encoding="utf-8")
        except UnicodeError as error:
            raise OgkError("OGK-PUBLISH-004", f"--openapi {openapi.name} is not UTF-8 text: {error}") from error
    escaping = sorted(path for path in pages if not _inside(output, path))
    if escaping:
        raise OgkError("OGK-PUBLISH-005", f"{', '.join(escaping)} would be written outside {output}: remove the symbolic link and export again.")
    for relative, content in pages.items():
        write_text(output / relative, content)
    stale = [path for path in previous if isinstance(path, str) and path not in pages]
    # The manifest is committed with the pages: anyone can edit it, so only remove what an export wrote.
    removed = [path for path in stale if _EXPORTED.fullmatch(path) and _inside(output, path)]
    kept = [path for path in previous if path not in pages and path not in removed]
    for relative in removed:
        (output / relative).unlink(missing_ok=True)
    write_json(manifest_path, {"version": version, "tasks": task_ids, "files": sorted(pages)})
    return {"written": sorted(pages), "removed": removed, "kept": kept, "warnings": warnings}


def _shares_path(state: Path) -> Path:
    return state / SHARES_DIR / "shares.json"


def load_shares(state: Path) -> list[dict]:
    path = _shares_path(state)
    return read_json(path)["shares"] if path.is_file() else []


def _shared_item(state: Path, deliverable: str) -> str:
    """What a recipient receives: an existing file of the project, or the folder of a documentation export. Returns its
    path from the project root, written with `/`, once links are resolved: the register keeps no local path."""
    target = project_path(state.parent, state, deliverable, "--deliverable")
    shown = Path(deliverable).as_posix()
    if not target.exists():
        raise OgkError("OGK-PUBLISH-006", f"--deliverable {shown} does not exist. Name the file you share, or the folder that "
                         "openguildkit docs export wrote.")
    if target.is_dir() and not (target / MANIFEST).is_file():
        raise OgkError("OGK-PUBLISH-007", f"--deliverable {shown} is a folder that holds no documentation export. Name the file you "
                         "share, or the folder that openguildkit docs export wrote.")
    return target.relative_to(state.parent.resolve()).as_posix()


def is_loopback(host: str) -> bool:
    """True for an address of this machine, where a local Documentalist runs without TLS."""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def portal_space(portal: str) -> str:
    """The space a portal address opens, written HOST/p/SPACE: Documentalist shows a reader every page of it.

    The address is https, or http for an instance on this machine (localhost, 127.0.0.1, ::1). The default port of
    the scheme is left out, so HOST:443 and HOST name the same space.
    """
    address = urlsplit(portal.strip())
    try:
        host, port = address.hostname, address.port
    except ValueError:
        host = port = None
    secure = address.scheme == "https" or (address.scheme == "http" and bool(host) and is_loopback(host))
    if not host or not secure:
        raise OgkError("OGK-PUBLISH-008", "Give the https address of the Documentalist portal, such as https://docs.example.org/p/support-portal "
                         "(http only for an instance on this machine: localhost, 127.0.0.1 or ::1).")
    parts = address.path.split("/")
    if len(parts) < 3 or parts[1] != "p" or not parts[2]:
        raise OgkError("OGK-PUBLISH-009", f"--portal {portal} names no space. Give the portal of the space you share, https://HOST/p/SPACE: "
                         "the recipients see every published page of that space.")
    shown = f"[{host}]" if ":" in host else host
    return f"{shown}{f':{port}' if port and port != _DEFAULT_PORTS[address.scheme] else ''}/p/{parts[2]}"


def _default_port(share: dict) -> int | None:
    """The default port of the scheme of the share's portal: 443 for https, 80 for http."""
    return _DEFAULT_PORTS.get(urlsplit(str(share.get("portal", "")).strip()).scheme)


def share_space(share: dict) -> str | None:
    """The space a share opens; a share recorded before the space was kept gets it from its portal.

    A space recorded with the default port of its portal's scheme, as earlier versions kept it, is read without it.
    """
    if share.get("space"):
        host, separator, rest = share["space"].partition("/p/")
        default = _default_port(share)
        if default and separator and host.endswith(f":{default}"):
            return f"{host.removesuffix(f':{default}')}/p/{rest}"
        return share["space"]
    try:
        return portal_space(share["portal"])
    except ValueError:
        return None


def _address(address: str) -> str:
    """An email address as docs share verify compares it: without surrounding spaces or case."""
    return address.strip().lower()


def shared_addresses(share: dict, other: dict) -> list[str]:
    """The share's recipients that the other share names too, whatever the case, written as the share writes them."""
    theirs = {_address(address) for address in other["recipients"]}
    return sorted(address for address in share["recipients"] if _address(address) in theirs)


def add_share(state: Path, deliverable: str, recipients: list[str], until: str, portal: str, by: str,
              dedicated: bool = False) -> dict:
    """Record a share before creating it in Documentalist: what, for whom, through which space, until when.

    With `dedicated`, the space is recorded as holding this deliverable only: refused when another deliverable is
    already shared through it, and any later share of another deliverable through it is refused too. A new share of
    the same deliverable through a dedicated space is dedicated as well.
    """
    if not deliverable.strip() or not by.strip():
        raise OgkError("OGK-PUBLISH-017", "Name the deliverable and the owner of the share.")
    shared = _shared_item(state, deliverable.strip())
    bad = [item for item in recipients if not _EMAIL.fullmatch(item)]
    if not recipients or bad:
        raise OgkError("OGK-PUBLISH-010", f"List the recipients' email addresses{': ' + ', '.join(bad) if bad else ''}.")
    _share_end(until)
    refuse_link_credentials(portal, "--portal")
    space = portal_space(portal)
    spellings: dict[str, str] = {}
    for address in recipients:  # One spelling per address, the first given: the register compares them without case.
        spellings.setdefault(_address(address), address)
    share = {"id": uuid.uuid4().hex[:8], "deliverable": shared, "recipients": sorted(spellings.values()),
             "until": until, "portal": portal, "space": space, "by": by.strip(),
             "created_at": clock.real_timestamp(), "revoked_at": None}
    with project_lock(state):
        shares = load_shares(state)
        # Another share of the same deliverable keeps a dedicated space dedicated after the first one is revoked.
        if dedicated or any(item.get("dedicated") for item in _same_deliverable(state, shares, share)):
            share["dedicated"] = True
        _check_dedication(_space_neighbours(state, shares, share), share)
        write_json(_shares_path(state), {"shares": [*shares, share]})
    return share


def _deliverable_key(project: Path, deliverable: str) -> str:
    """The same deliverable written `d.md`, `./d.md` or by its absolute path, as an earlier register may hold it, is one
    deliverable. `project` is the resolved project folder."""
    try:
        return (project / deliverable).resolve().relative_to(project).as_posix()
    except ValueError:
        return posixpath.normpath(Path(deliverable).as_posix())


def _space_neighbours(state: Path, shares: list[dict], share: dict) -> list[dict]:
    """The shares not revoked of another deliverable through the same space: Documentalist shows a reader every
    published page of a space, so the recipients of each of them can read the other deliverables too."""
    project = state.parent.resolve()
    space, key = share_space(share), _deliverable_key(project, share["deliverable"])
    return [item for item in shares
            if item["id"] != share["id"] and not item["revoked_at"] and space and share_space(item) == space
            and _deliverable_key(project, item["deliverable"]) != key]


def _same_deliverable(state: Path, shares: list[dict], share: dict) -> list[dict]:
    project = state.parent.resolve()
    space, key = share_space(share), _deliverable_key(project, share["deliverable"])
    return [item for item in shares
            if not item["revoked_at"] and space and share_space(item) == space
            and _deliverable_key(project, item["deliverable"]) == key]


def _check_dedication(neighbours: list[dict], share: dict) -> None:
    claimed = [item for item in neighbours if item.get("dedicated")]
    if claimed:
        owner = claimed[0]
        raise OgkError("OGK-PUBLISH-011", f"Space {share['space']} is dedicated to {owner['deliverable']} (share {owner['id']}): its "
                         f"readers would see {share['deliverable']} too. Publish {share['deliverable']} in a space of its "
                         "own and give its portal address.")
    if share.get("dedicated") and neighbours:
        listed = ", ".join(f"{item['deliverable']} (share {item['id']})" for item in neighbours)
        raise OgkError("OGK-PUBLISH-012", f"Space {share['space']} already carries {listed}: its readers would see "
                         f"{share['deliverable']} too, so it cannot be dedicated to it. Use a new space, or revoke those "
                         "shares and remove their pages from the space first.")


def space_neighbours(state: Path, share: dict) -> list[dict]:
    """The shares not revoked of other deliverables through the share's space."""
    return _space_neighbours(state, load_shares(state), share)


def _share_end(until: str) -> date:
    """The last day of access: a real YYYY-MM-DD date, after today and within a year, on the real clock."""
    try:
        end = date.fromisoformat(until) if _DAY.fullmatch(until) else None
    except ValueError:
        end = None
    if end is None:
        raise OgkError("OGK-PUBLISH-013", f"Give the last day of access as YYYY-MM-DD, not {until!r}.")
    today = clock.real_today()
    if end <= today:
        raise OgkError("OGK-PUBLISH-014", "A share ends after today.")
    if end > today + timedelta(days=MAX_SHARE_DAYS):
        raise OgkError("OGK-PUBLISH-015", f"A share lasts at most {MAX_SHARE_DAYS} days. Record a new share when it ends to extend it.")
    return end


def _same_access(shares: list[dict], share: dict, today: date | None) -> list[dict]:
    space = share_space(share)
    return [item for item in shares
            if item["id"] != share["id"] and not item["revoked_at"] and space and share_space(item) == space
            and shared_addresses(share, item) and (today is None or date.fromisoformat(item["until"]) >= today)]


def same_access(state: Path, share: dict, running: bool = False) -> list[dict]:
    """The other shares not revoked that give one of the share's recipients the same space, whatever the case.

    Documentalist keeps one access per address and space, so these shares grant and lose that access together.
    With `running`, only those whose last day is not past on the real clock.
    """
    return _same_access(load_shares(state), share, clock.real_today() if running else None)


def revoke_share(state: Path, share_id: str, by: str) -> dict:
    """Record that the access was removed in Documentalist; the first revocation stays. Returns it with its space."""
    if not by.strip():
        raise OgkError("OGK-PUBLISH-018", "Name the person who removed the access with --by.")
    with project_lock(state):
        shares = load_shares(state)
        share = next((item for item in shares if item["id"] == share_id), None)
        if share is None:
            raise OgkError("OGK-PUBLISH-019", unknown("share", share_id, "docs share list"))
        if share["revoked_at"]:
            raise OgkError("OGK-PUBLISH-020", f"Share {share_id} was already revoked by {share.get('revoked_by') or 'someone'} on {share['revoked_at'][:10]}.")
        share["revoked_at"] = clock.real_timestamp()
        share["revoked_by"] = by.strip()
        write_json(_shares_path(state), {"shares": shares})
    return {**share, "space": share_space(share)}


def _observation(observations: dict, share: dict, space: str | None) -> dict:
    """The last observation of the share's space, one an earlier version kept under HOST:443/p/SPACE included."""
    host, separator, rest = (space or "").partition("/p/")
    default = _default_port(share)
    keys = [space, *([f"{host}:{default}/p/{rest}"] if default and separator else [])]
    found = [observations[key] for key in keys
             if isinstance(observations.get(key), dict) and observations[key].get("checked_at")]
    return max(found, key=lambda item: str(item["checked_at"]), default={})


def share_status(state: Path, today: date | None = None) -> list[dict]:
    """Each share with its space and state, on the real clock: active, expired, covered or revoked.

    A share past its last day is expired when some of its addresses must be removed from the space (listed in
    `remove`), and covered when other running shares of the same space still give every address access (listed in
    `kept`, with the share that ends last): there is nothing to remove until those shares end.
    """
    today = today or clock.real_today()
    shares, rows = load_shares(state), []
    observation_path = state / SHARES_DIR / "portal-observations.json"
    try:
        observations = read_json(observation_path).get("observations", {}) if observation_path.is_file() else {}
    except ValueError:
        observations = {}
    observations = observations if isinstance(observations, dict) else {}
    for share in shares:
        row = {**share, "space": share_space(share), "remove": [], "kept": {}, "dedicated": bool(share.get("dedicated")),
               "also_in_space": [] if share["revoked_at"] else
               sorted({item["deliverable"] for item in _space_neighbours(state, shares, share)})}
        observed = _observation(observations, share, row["space"])
        if observed:
            recipients = {_address(address) for address in share["recipients"]}
            observed_rows = observed.get("rows") if isinstance(observed.get("rows"), list) else []
            row["portal_observation"] = {"source": observed.get("source"), "checked_at": observed["checked_at"],
                                         "rows": [item for item in observed_rows
                                                  if isinstance(item, dict) and item.get("recipient") in recipients]}
        if share["revoked_at"]:
            row["state"] = "revoked"
        elif date.fromisoformat(share["until"]) >= today:
            row["state"] = "active"
        else:
            running = _same_access(shares, share, today)
            for recipient in share["recipients"]:
                covering = [item for item in running
                            if _address(recipient) in {_address(address) for address in item["recipients"]}]
                if covering:
                    last = max(covering, key=lambda item: item["until"])
                    row["kept"][recipient] = {"share": last["id"], "until": last["until"]}
                else:
                    row["remove"].append(recipient)
            row["state"] = ("expired: remove the access in Documentalist" if row["remove"]
                            else "covered: other shares keep the same access, nothing to remove yet")
        rows.append(row)
    return rows
