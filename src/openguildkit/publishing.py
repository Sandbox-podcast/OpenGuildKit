"""Turn verified work into documentation pages and keep track of who it is shared with.

The export writes a Markdown tree that Documentalist imports from a Git repository:
`project/overview.md` for what the project is and the rules in force, `reference/` for the
Reference tab, `learn/` for Learn, `blog/` for dated release notes, and `SUMMARY.md` for the order. Paths stay stable, so re-exporting updates the same pages.
Only tasks completed with recorded checks can be exported, and only the fields listed here
leave the project: no review, evidence or internal note.
"""

import json
import re
import sys
import uuid
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from . import clock
from .project import STATE_DIR, pack_scopes, rule_plan, rule_text
from .storage import project_lock, read_json, write_json, write_text
from .tasks import read_task
from .workflow import open_objection_count

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


def _unique_points(values: list[str]) -> list[str]:
    points = {}
    for value in values:
        text = value.strip()
        if text:
            points.setdefault(" ".join(text.rstrip(".").lower().split()), text)
    return list(points.values())


def _criteria(task: dict) -> list[str]:
    return _unique_points([item["criterion"] for item in task.get("result", {}).get("criteria", [])
                           if item["status"] == "met"])


def _verification(task: dict) -> str:
    checks = Counter(item["status"] for item in task.get("result", {}).get("checks", []))
    return (f"{checks['passed']} check(s) passed, {checks['not-applicable']} not applicable, "
            f"{checks['failed']} failed, {checks['skipped']} skipped. "
            f"{open_objection_count(task)} disagreement(s) remained open.")


def _pages(task: dict, position: int, version: str, sections: tuple[str, ...], export_day: str | None = None) -> dict[str, str]:
    title = _title(task)
    result = task.get("result", {})
    delivered = result.get("pull_request") or result.get("revision") or "not recorded"
    outcome = task.get("answers", {}).get("outcome")
    brief = task["brief"].strip()
    first, _, details = brief.partition("\n")
    body = details.strip() if first.rstrip(".") == title else brief
    behaviour = _unique_points(([outcome] if outcome else []) + _criteria(task))
    common = {"title": title, "source_task": task["id"], "project_version": version}
    pages = {}
    if "reference" in sections:
        lines = [f"# {title}", ""]
        if body:
            lines += [body, ""]
        if behaviour:
            lines += ["## Behaviour", "", *[f"- {point}" for point in behaviour], ""]
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
        day = export_day or (task.get("completed_at") or task["created_at"])[:10]
        lines = [f"# {title}", ""]
        if body:
            lines += [body, ""]
        lines += [f"Available in version {version}.", ""]
        pages[f"blog/{day}-{task['id']}.md"] = _frontmatter({**common, "date": day}) + "\n".join(lines)
    return pages


def project_overview(profile: dict, catalog: dict) -> dict:
    """What the Project page shows: profile fields, active packs with their rules, and boards.

    Component paths, check commands and anything outside the profile and catalog stay out.
    """
    plan, scopes = rule_plan(profile, catalog), pack_scopes(profile, catalog)
    packs = [{"id": item["id"], "title": item["title"], "version": item["version"], "components": scopes.get(item["id"]),
              "rules": [rule_text(rule)[0] for rule in catalog["packs"][item["id"]]["rules"]]} for item in plan["packs"]]
    boards = sorted(catalog["boards"])
    return {"name": profile["name"], "sector": profile.get("sector"), "stack": profile.get("stack", []),
            "components": [{"id": item["id"], "stack": item["stack"]} for item in profile.get("components", [])],
            "conventions": profile.get("conventions", []), "packs": packs,
            "boards": [{"id": board_id, "title": catalog["boards"][board_id]["title"]} for board_id in boards]}


def _project_page(overview: dict, version: str, consulted: set[str]) -> str:
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
    labels = {item["id"]: item["title"] for item in overview["boards"]}
    boards = [f"- {labels.get(board_id, board_id)} ({board_id})" for board_id in sorted(consulted)]
    lines += ["## Boards consulted", "", *(boards or ["No board reviews are recorded for the selected tasks."]), ""]
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
    not_done = [task["id"] for task in tasks if task["status"] != "done"]
    if not_done:
        raise ValueError(f"Only completed tasks with recorded checks can be documented: {', '.join(not_done)}.")
    manifest_path = output / MANIFEST
    previous = read_json(manifest_path)["files"] if manifest_path.is_file() else []
    if output.exists() and not manifest_path.is_file() and any(output.iterdir()):
        raise ValueError(f"{output} is not empty and was not created by openguildkit docs export.")
    fixed = clock.source_date_epoch() if "blog" in sections and tasks else None
    if fixed:
        print(f"OpenGuildKit: SOURCE_DATE_EPOCH sets the exported blog date to {fixed.date().isoformat()}.", file=sys.stderr)
    pages = {}
    for position, task in enumerate(tasks, start=1):
        pages.update(_pages(task, position, version, sections, fixed.date().isoformat() if fixed else None))
    summary = [f"# {project}", ""]
    if "project" in sections and overview is not None:
        consulted = {entry["id"] for task in tasks for entry in task.get("review", {}).get("boards", [])}
        pages[PROJECT_PAGE] = _project_page(overview, version, consulted)
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


def shareable_path(root: Path, deliverable: str) -> None:
    """A share names a page or a folder of a docs export: inside the project, never under .openguildkit
    (task records, shares and decisions stay local) and never through a link that leaves the folder."""
    named = Path(deliverable.strip())
    candidate = named if named.is_absolute() else root / named
    resolved, project = candidate.resolve(), root.resolve()
    try:
        relative = resolved.relative_to(project)
    except ValueError:
        raise ValueError(f"{deliverable} is outside the project: share a page of a docs export.") from None
    if STATE_DIR in relative.parts or STATE_DIR in named.parts:
        raise ValueError(f"{deliverable} is under {STATE_DIR}, which holds the local task records and reviews: "
                         "they are never shared. Share a page that docs export wrote.")
    folder = resolved if resolved.is_dir() else resolved.parent
    for ancestor in (folder, *folder.parents):
        if (ancestor / MANIFEST).is_file():
            return
        if ancestor == project:
            break
    raise ValueError(f"{deliverable} is not inside a docs export folder: run openguildkit docs export, "
                     "then share one of its pages or folders.")


def add_share(state: Path, deliverable: str, recipients: list[str], until: str, portal: str, by: str) -> dict:
    """Record a share before creating it in Documentalist: what, for whom, until when."""
    if not deliverable.strip() or not by.strip():
        raise ValueError("Name the deliverable and the owner of the share.")
    shareable_path(state.parent, deliverable)
    bad = [item for item in recipients if not _EMAIL.fullmatch(item)]
    if not recipients or bad:
        raise ValueError(f"List the recipients' email addresses{': ' + ', '.join(bad) if bad else ''}.")
    end = _share_end(until)
    address = urlsplit(portal)
    if address.scheme != "https" or not address.hostname:
        raise ValueError("Give the https address of the Documentalist portal.")
    share = {"id": uuid.uuid4().hex[:8], "deliverable": deliverable.strip(), "recipients": sorted(set(recipients)),
             "until": until, "portal": portal, "by": by.strip(),
             "created_at": clock.timestamp(), "revoked_at": None}
    with project_lock(state):
        write_json(_shares_path(state), {"shares": [*_load_shares(state), share]})
    return share


def _share_end(until: str) -> date:
    """The last day of access: a real YYYY-MM-DD date, after today and within a year."""
    try:
        end = date.fromisoformat(until) if _DAY.fullmatch(until) else None
    except ValueError:
        end = None
    if end is None:
        raise ValueError(f"Give the last day of access as YYYY-MM-DD, not {until!r}.")
    if end <= clock.today():
        raise ValueError("A share ends after today.")
    if end > clock.today() + timedelta(days=MAX_SHARE_DAYS):
        raise ValueError(f"A share lasts at most {MAX_SHARE_DAYS} days. Record a new share when it ends to extend it.")
    return end


def revoke_share(state: Path, share_id: str, by: str) -> dict:
    """Record that the access was removed in Documentalist; the first revocation stays."""
    if not by.strip():
        raise ValueError("Name the person who removed the access with --by.")
    with project_lock(state):
        shares = _load_shares(state)
        share = next((item for item in shares if item["id"] == share_id), None)
        if share is None:
            raise ValueError(f"Unknown share {share_id}. Run openguildkit docs share list.")
        if share["revoked_at"]:
            raise ValueError(f"Share {share_id} was already revoked by {share.get('revoked_by') or 'someone'} on {share['revoked_at'][:10]}.")
        share["revoked_at"] = clock.timestamp()
        share["revoked_by"] = by.strip()
        write_json(_shares_path(state), {"shares": shares})
    return share


def share_status(state: Path, today: date | None = None) -> list[dict]:
    """Each share with its state: active, expired (to revoke in Documentalist) or revoked."""
    today = today or clock.today()
    rows = []
    for share in _load_shares(state):
        if share["revoked_at"]:
            state_name = "revoked"
        elif date.fromisoformat(share["until"]) < today:
            state_name = "expired: remove the access in Documentalist"
        else:
            state_name = "active"
        rows.append({**share, "state": state_name})
    return rows
