"""Business deliverable templates: inputs, tool actions that need approval, reviewer checks; the architecture decision
record filled from a decision task.

Templates live in registry/deliverables/ (and .openguildkit/catalog/deliverables/ for a
project). `deliverable new` turns an approved task into a draft; `deliverable check` says what
is still missing before the brain and the owner review it.

Entry: project_path, load_deliverables, launch_notice, utm_link, new_draft, draft_problems
Tests: tests/test_deliverables.py
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import clock
from .catalog import (
    CatalogError,
    package_file,
    record_files,
    validate_fields,
    validate_id,
    validate_list,
    validate_sources,
    validate_text,
)
from .errors import OgkError
from .records import Catalog, Task
from .storage import write_text
from .wording import plural
from .workflow import blocker_list, is_decision_task, objections

DATA_CLASSES = ("none", "internal", "personal", "regulated")
ACTIONS = ("public-research", "external-api", "send-message", "publish", "install-dependency", "other")
_CHECKED = re.compile(r"^- \[x\] (?P<id>[a-z0-9-]+): .+? Evidence: (?P<evidence>\S.*)$", re.MULTILINE)
_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_FIELD = re.compile(r'^(?P<key>[a-z_]+): (?P<value>".*")$')
# The approval stays in the task record: a draft may go to a client, so it carries no internal field.
FRONT_MATTER = ("deliverable", "task")
# The campaign-measurement pack asks for the agreed values in the same case on every link;
# lowercase letters, digits, dots, hyphens and underscores keep one spelling per value.
_UTM_VALUE = re.compile(r"[a-z0-9][a-z0-9._-]*")
UTM_ORDER = ("source", "medium", "campaign", "content", "term")


def _same_or_inside(path: Path, folder: Path) -> bool:
    """True when path is folder or lies in it, also on a file system that ignores case."""
    if path == folder or folder in path.parents:
        return True
    if not folder.exists():
        return False
    return any(ancestor.exists() and os.path.samefile(ancestor, folder) for ancestor in (path, *path.parents))


def project_path(root: Path, state: Path, value: Path | str, option: str) -> Path:
    """A path the team may share: inside the project once symbolic links are resolved, and outside .openguildkit/.

    The refusal shows the path as the person wrote it.
    """
    shown = Path(value).as_posix()
    project = root.resolve()
    target = (project / Path(value)).resolve()
    if not _same_or_inside(target, project):
        raise OgkError("OGK-RESULT-001", f"{option} {shown} is outside the project, once links are followed. "
                         "Give a path inside the project folder.")
    if _same_or_inside(target, state.resolve()):
        raise OgkError("OGK-RESULT-002", f"{option} {shown} is in .openguildkit/, OpenGuildKit's own state, such as the task records "
                         "the team does not share. Give a path outside .openguildkit/.")
    return target


def _validate(record: dict, catalog: Catalog, bundled: bool = False) -> None:
    validate_fields(record, "deliverable", {"id", "title", "description", "brains", "inputs", "tool_actions", "sections", "checks", "sources"}, {"method", "market", "requires_tool", "decision"})
    for flag in ("market", "requires_tool", "decision"):
        if flag in record and not isinstance(record[flag], bool):
            raise CatalogError(f"{flag} must be true or false")
    validate_id(record["id"], "id")
    for field in ("title", "description"):
        validate_text(record[field], field)
    validate_sources(record["sources"], require_checked=bundled)
    if "method" in record and record["method"] not in catalog["patterns"]:
        raise CatalogError(f"Unknown method pattern {record['method']!r}")
    validate_list(record["brains"], "brains")
    unknown = sorted(set(record["brains"]) - catalog["boards"].keys())
    if unknown:
        raise CatalogError(f"Unknown brains: {', '.join(unknown)}")
    validate_list(record["inputs"], "inputs")
    for item in record["inputs"]:
        validate_fields(item, "input", {"id", "label", "data"})
        validate_id(item["id"], "input id")
        validate_text(item["label"], "input label")
        if item["data"] not in DATA_CLASSES:
            raise CatalogError(f"input data must be one of {', '.join(DATA_CLASSES)}")
    validate_list(record["tool_actions"], "tool_actions", allow_empty=True)
    for item in record["tool_actions"]:
        validate_fields(item, "tool action", {"action", "description"})
        if item["action"] not in ACTIONS:
            raise CatalogError(f"tool action must be one of {', '.join(ACTIONS)}")
        validate_text(item["description"], "tool action description")
    for field in ("sections", "checks"):
        validate_list(record[field], field)
        for item in record[field]:
            validate_fields(item, field[:-1], {"id", "title" if field == "sections" else "verification", "prompt"} if field == "sections" else {"id", "verification"})
            validate_id(item["id"], f"{field[:-1]} id")
            for key in item:
                if key != "id":
                    validate_text(item[key], f"{field[:-1]} {key}")


def load_deliverables(catalog: Catalog, extra_dir: Path | None = None) -> dict[str, dict]:
    roots = [package_file("registry", "deliverables")]
    if extra_dir is not None and extra_dir.is_dir():
        roots.append(extra_dir)
    found = {}
    for root in roots:
        for path, record in record_files(root):
            try:
                _validate(record, catalog, root == roots[0])
                if path.name != f"{record['id']}.json" or record["id"] in found:
                    raise CatalogError(f"name the file {record['id']}.json and keep IDs unique")
            except (OSError, ValueError) as error:
                raise CatalogError(f"{path}: {error}") from error
            found[record["id"]] = record
    return dict(sorted(found.items()))


def launch_notice(deliverable: dict) -> list[str]:
    """What the requester must know before the tool runs: data needed and actions needing approval."""
    lines = [f"{item['label']} ({'no sensitive data' if item['data'] == 'none' else item['data'] + ' data'})"
             for item in deliverable["inputs"]]
    lines += [f"Needs your approval (task authorize --action {item['action']}): {item['description']}" for item in deliverable["tool_actions"]]
    return lines


def utm_link(url: str, values: dict[str, str | None]) -> str:
    """A landing URL tagged with UTM parameters, following the campaign-measurement pack.

    Values are trimmed and must be lowercase without spaces, so each one has a single spelling;
    an email address is refused, since personal data stays out of tags. Nothing is fetched.
    """
    address = urlsplit(url.strip())
    if address.scheme != "https" or not address.hostname or address.username is not None:
        raise OgkError("OGK-RESULT-003", "Give the landing page as an https address with a host and no credentials.")
    if any(key.lower().startswith("utm_") for key, _ in parse_qsl(address.query, keep_blank_values=True)):
        raise OgkError("OGK-RESULT-004", "The landing URL already carries utm_ parameters. Give the page address without them.")
    tags = []
    for name in UTM_ORDER:
        value = values.get(name)
        if value is None:
            continue
        value = value.strip()
        if "@" in value:
            raise OgkError("OGK-RESULT-005", f"utm_{name} looks like an email address: keep personal data out of UTM values.")
        if not _UTM_VALUE.fullmatch(value):
            raise OgkError("OGK-RESULT-006", f"Write utm_{name} in lowercase letters, digits, '.', '-' or '_', without spaces, "
                             f"as agreed with the analytics owner: {value!r}.")
        tags.append((f"utm_{name}", value))
    query = "&".join(part for part in (address.query, urlencode(tags)) if part)
    return urlunsplit((address.scheme, address.netloc, address.path, query, address.fragment))


def _market_lines(deliverable: dict, task: Task) -> tuple[list[str], list[str]]:
    """Front matter and input lines linking a market template to the dossier the task was consulted with."""
    if not deliverable.get("market"):
        return [], []
    dossier = task.get("consultation", {}).get("scope", {}).get("market")
    if not dossier:
        return [], ["- Market dossier: none attached. Create one in .openguildkit/market/ and consult the task with --market ID."]
    gaps = f", {plural(len(dossier.get('gaps', [])), 'gap')}" if dossier.get("gaps") else ""
    return [f"market: {json.dumps(dossier['id'])}"], [
        f"- Market dossier: .openguildkit/market/{dossier['id']}.json ({plural(len(dossier.get('observations', [])), 'observation')}{gaps}); "
        f"cite observations as market:{dossier['id']}/ID"]


def _quoted(text: object) -> list[str]:
    """What a person typed, as a Markdown quote: a heading of theirs cannot open a section of the draft."""
    if not isinstance(text, str) or not text.strip():
        return []
    return [f"> {line}".rstrip() for line in text.strip().splitlines()]


def _one_line(text: object) -> str:
    return " ".join(text.split()) if isinstance(text, str) else ""


def _day(stamp: object) -> str:
    return stamp[:10] if isinstance(stamp, str) else ""


def _status_lines(task: Task) -> list[str]:
    task_id, approved = task["id"], _day(task.get("decision", {}).get("at"))
    accepted = f"Accepted: decision task `{task_id}` approved on {approved}"
    closed = _day(task.get("completed_at"))
    if task["status"] == "done":
        lines = [f"{accepted} and closed on {closed}."]
    elif task["status"] == "done-with-reservations":
        # The closing names who closed the task in its lines: the draft points to it rather than copy it.
        lines = [f"{accepted} and closed with reservations on {closed}: openguildkit task show {task_id} --closing "
                 "lists them."]
    else:
        lines = [f"{accepted}. It is not closed yet: openguildkit task complete {task_id} closes it."]
    follows = task.get("follows")
    if isinstance(follows, dict) and follows.get("task"):
        lines.append(f"It follows the decision of task `{follows['task']}`.")
    return lines


def _advice_lines(task: Task) -> list[str]:
    """Each board's verdict and recommendation, then what the deliberation left open, or the objections that
    no deliberation answered and the person decided when approving."""
    review = task.get("review", {})
    lines = [f"- {entry['id']} ({entry.get('challenge', {}).get('verdict', 'no verdict')}): "
             f"{_one_line(entry.get('recommendation'))}" for entry in review.get("boards", [])]
    if not lines:
        lines = ["No board review is recorded."]
    deliberation = task.get("deliberation")
    if deliberation:
        points = {item["id"]: _one_line(item.get("point")) for item in deliberation.get("objections", [])}
        left = deliberation.get("open", [])
        lines += ["", f"Deliberation: {len(deliberation.get('agreed', []))} resolved, {len(left)} left open."]
        lines += [f"- Disagreement left open, {item_id}: {points.get(item_id, '')}" for item_id in left]
        if left and deliberation.get("decision_needed"):
            lines.append(f"- Decision needed: {_one_line(deliberation['decision_needed'])}")
        if not left:
            lines.append("No disagreement was left open between the boards.")
        return lines
    try:
        pending = objections(review, task.get("consultation", {}).get("domains"))
    except (KeyError, TypeError, AttributeError, ValueError):
        return [*lines, "", "The objections between boards cannot be read from this task record."]
    if not pending:
        return [*lines, "", "No disagreement was left open between the boards."]
    lines += ["", f"{len(pending)} objection{'' if len(pending) == 1 else 's'} not deliberated, "
                  f"{', '.join(item['id'] for item in pending)}: the person decided them when approving."]
    return [*lines, *(f"- {item['id']}: {_one_line(item.get('point'))}" for item in pending)]


def _condition_lines(task: Task) -> list[str]:
    """Each blocker a board set, without who owns, cleared or waived it: only the decision's own name is kept."""
    lines = []
    for item in blocker_list(task):
        when = "after the decision" if item.get("phase") == "verification" else "before the decision"
        line = f"- {item['id']}, {when}: {_one_line(item.get('finding'))}"
        if item.get("clears_when"):
            line += f" Clears when: {_one_line(item['clears_when'])}"
        resolution = item["resolution"]
        if not resolution:
            line += (" Open: it is cleared after the decision and before the task closes."
                     if item.get("phase") == "verification" else " Open.")
        elif resolution.get("kind") == "cleared":
            line += f" Cleared: {resolution.get('evidence', '')} supports that {_one_line(resolution.get('supports'))}"
        else:
            line += (f" Waived until {resolution.get('until', '')}: {_one_line(resolution.get('reason'))} "
                     f"(scope: {_one_line(resolution.get('scope'))})")
        lines.append(line)
    return lines or ["No condition: no board set a blocker."]


def decision_sections(task: Task) -> dict[str, list[str]]:
    """The sections of an architecture decision record, filled from a decision task. The only person named is the
    one the decision names; a section the task cannot fill says TODO with what to write."""
    task_id, answers, decision = task["id"], task.get("answers", {}), task.get("decision", {})
    context = _quoted(task.get("brief"))
    for label, key in (("Context given at consultation", "context"), ("Who it affects", "affected")):
        if _quoted(answers.get(key)):
            context += ["", f"{label}:", "", *_quoted(answers[key])]
    options = _quoted(answers.get("options")) or [
        "TODO: the task records no answer to the options question; list the options considered."]
    chosen = [*_quoted(decision.get("reason")), "",
              f"Approved by {decision.get('by', '')} on {_day(decision.get('at'))}."]
    summary = _quoted(task.get("review", {}).get("summary"))
    if summary:
        chosen += ["", "The boards' review in short:", "", *summary]
    record = [f"- Exported decision record: `.openguildkit/decisions/{task_id}.json`, written by "
              f"`openguildkit task export {task_id}` (again after the task closes)."]
    if decision.get("seal"):
        record.append(f"- Decision seal: `{decision['seal']}`")
    return {"status": _status_lines(task), "context": context, "options": options, "decision": chosen,
            "advice": _advice_lines(task), "conditions": _condition_lines(task), "record": record,
            "_inputs": [f"`{task_id}` ({task['status']})"],
            "_sources": [f"- Decision task `{task_id}`, approved on {_day(decision.get('at'))}: "
                         f"`.openguildkit/decisions/{task_id}.json`"]}


def _decision_refusal(deliverable: dict, task: Task) -> ValueError:
    kind = task.get("answers", {}).get("kind") or "unanswered"
    return ValueError(f"{deliverable['id']} is written from a decision task, and {task['id']} is a {kind} task. "
                      "Open a decision task (answer kind decision at task consult) for the choice to record, or pick "
                      "another template: openguildkit deliverable list.")


def new_draft(deliverable: dict, task: Task, tool: str | None, approved_tools: list[str], output: Path) -> dict:
    """Write the draft. The tool is optional unless the template requires one: its actions are authorized one by
    one with task authorize. The draft may go to a client, so the approval stays in the task record.
    """
    if task["status"] not in ("approved", "done", "done-with-reservations"):
        raise OgkError("OGK-RESULT-007", "Start a deliverable from an approved or completed task.")
    if deliverable.get("requires_tool") and not tool:
        raise ValueError("This template needs --tool, one of the project's approved tools.")
    if tool is not None and approved_tools and tool not in approved_tools:
        raise OgkError("OGK-RESULT-008", f"{tool} is not an approved tool for this project. Approved: {', '.join(approved_tools)}.")
    if deliverable.get("decision") and not is_decision_task(task):
        raise _decision_refusal(deliverable, task)
    if output.exists():
        raise ValueError(f"{output.as_posix()} already exists.")
    market_fields, market_inputs = _market_lines(deliverable, task)
    filled = decision_sections(task) if deliverable.get("decision") else {}
    inputs = filled.get("_inputs")
    lines = [
        "---",
        f"deliverable: {json.dumps(deliverable['id'])}",
        f"task: {json.dumps(task['id'])}",
        *([f"tool: {json.dumps(tool)}"] if tool is not None else []),
        *market_fields,
        "---",
        "",
        f"# {deliverable['title']}" + (f": {task['id']}" if filled else ""),
        "",
        "## Inputs",
        "",
        *[f"- {item['label']}: {inputs[0] if inputs else 'TODO'}" for item in deliverable["inputs"]],
        *market_inputs,
        "",
    ]
    for section in deliverable["sections"]:
        lines += [f"## {section['title']}", "", f"<!-- {section['prompt']} -->", *filled.get(section["id"], ["TODO"]),
                  ""]
    lines += ["## Sources", "", *filled.get("_sources", ["- TODO: each source with its date or link"]), "",
              "## Checks", ""]
    lines += [f"- [ ] {check['id']}: {check['verification']} Evidence: " for check in deliverable["checks"]]
    write_text(output, "\n".join(lines) + "\n")
    entry = {"deliverable": deliverable["id"], "path": output.as_posix(), "created_at": clock.timestamp()}
    if tool is not None:
        entry["tool"] = tool
    return entry


def _front_matter(text: str) -> tuple[dict, str]:
    """The draft's front matter fields and the body after it."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---" or "---" not in [line.strip() for line in lines[1:]]:
        return {}, text
    end = [line.strip() for line in lines].index("---", 1)
    fields = {}
    for line in lines[1:end]:
        match = _FIELD.match(line.strip())
        if match:
            try:
                fields[match["key"]] = json.loads(match["value"])
            except ValueError:
                continue
    return fields, "\n".join(lines[end + 1:])


def _visible(text: str) -> str:
    """The text a reader sees: HTML comments and fenced code blocks do not count."""
    kept, fenced = [], False
    for line in _COMMENT.sub("", text).splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            kept.append(line)
    return "\n".join(kept)


def _sections(body: str) -> dict[str, list[str]]:
    """The non-blank lines under each level-two heading, by heading title."""
    found, current = {}, None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            found.setdefault(current, [])
        elif line.startswith("# "):
            current = None
        elif current is not None and line.strip():
            found[current].append(line.strip())
    return found


def draft_problems(deliverable: dict, text: str) -> list[str]:
    """What keeps a draft from review: front matter, sections, placeholders, sources and checks.

    Only what a reader sees counts: a section, source or ticked check inside an HTML comment
    or a code block is ignored, so an empty draft cannot pass.
    """
    fields, body = _front_matter(text)
    required = (*FRONT_MATTER, "tool") if deliverable.get("requires_tool") else FRONT_MATTER
    problems = [f"The front matter has no {field}: start the draft with openguildkit deliverable new."
                for field in required if not str(fields.get(field, "")).strip()]
    for field in ("approved_by", "decision_reason"):
        if field in fields:
            problems.append(f"Remove the internal {field} field before sharing this draft.")
    visible = _visible(body)
    sections = _sections(visible)
    for title in ["Inputs", *[section["title"] for section in deliverable["sections"]], "Sources", "Checks"]:
        if title not in sections:
            problems.append(f'Section "{title}" is missing.')
        elif not sections[title]:
            problems.append(f'Section "{title}" is empty.')
    if "TODO" in visible:
        problems.append(f"{plural(visible.count('TODO'), 'placeholder')} still {'says' if visible.count('TODO') == 1 else 'say'} TODO.")
    if "Sources" in sections and not any(line.startswith("- ") and "TODO" not in line for line in sections["Sources"]):
        problems.append("List at least one source.")
    checked = {match["id"] for match in _CHECKED.finditer("\n".join(sections.get("Checks", [])))}
    for check in deliverable["checks"]:
        if check["id"] not in checked:
            problems.append(f"Check {check['id']} is not ticked with its evidence.")
    return problems
