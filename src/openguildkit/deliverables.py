"""Business deliverables: a method's template, the inputs it needs, the tool actions that need
approval and the checks a reviewer runs on the result.

Templates live in registry/deliverables/ (and .openguildkit/catalog/deliverables/ for a
project). `deliverable new` turns an approved task into a draft; `deliverable check` says what
is still missing before the brain and the owner review it.
"""

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import clock
from .catalog import (
    CatalogError, _unique_fields, _validate_fields, _validate_id, _validate_list, _validate_sources, _validate_text, package_file,
)
from .storage import write_text

DATA_CLASSES = ("none", "internal", "personal", "regulated")
ACTIONS = ("public-research", "external-api", "send-message", "publish", "install-dependency", "other")
_CHECKED = re.compile(r"^- \[x\] (?P<id>[a-z0-9-]+): .+? Evidence: (?P<evidence>\S.*)$", re.MULTILINE)
_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_FIELD = re.compile(r'^(?P<key>[a-z_]+): (?P<value>".*")$')
FRONT_MATTER = ("deliverable", "task")
# The campaign-measurement pack asks for the agreed values in the same case on every link;
# lowercase letters, digits, dots, hyphens and underscores keep one spelling per value.
_UTM_VALUE = re.compile(r"[a-z0-9][a-z0-9._-]*")
UTM_ORDER = ("source", "medium", "campaign", "content", "term")


def _validate(record: dict, catalog: dict, bundled: bool = False) -> None:
    _validate_fields(record, "deliverable", {"id", "title", "description", "brains", "inputs", "tool_actions", "sections", "checks", "sources"}, {"method", "market", "requires_tool"})
    for flag in ("market", "requires_tool"):
        if flag in record and not isinstance(record[flag], bool):
            raise CatalogError(f"{flag} must be true or false")
    _validate_id(record["id"], "id")
    for field in ("title", "description"):
        _validate_text(record[field], field)
    _validate_sources(record["sources"], require_checked=bundled)
    if "method" in record and record["method"] not in catalog["patterns"]:
        raise CatalogError(f"Unknown method pattern {record['method']!r}")
    _validate_list(record["brains"], "brains")
    unknown = sorted(set(record["brains"]) - catalog["boards"].keys())
    if unknown:
        raise CatalogError(f"Unknown brains: {', '.join(unknown)}")
    _validate_list(record["inputs"], "inputs")
    for item in record["inputs"]:
        _validate_fields(item, "input", {"id", "label", "data"})
        _validate_id(item["id"], "input id")
        _validate_text(item["label"], "input label")
        if item["data"] not in DATA_CLASSES:
            raise CatalogError(f"input data must be one of {', '.join(DATA_CLASSES)}")
    _validate_list(record["tool_actions"], "tool_actions", allow_empty=True)
    for item in record["tool_actions"]:
        _validate_fields(item, "tool action", {"action", "description"})
        if item["action"] not in ACTIONS:
            raise CatalogError(f"tool action must be one of {', '.join(ACTIONS)}")
        _validate_text(item["description"], "tool action description")
    for field in ("sections", "checks"):
        _validate_list(record[field], field)
        for item in record[field]:
            _validate_fields(item, field[:-1], {"id", "title" if field == "sections" else "verification", "prompt"} if field == "sections" else {"id", "verification"})
            _validate_id(item["id"], f"{field[:-1]} id")
            for key in item:
                if key != "id":
                    _validate_text(item[key], f"{field[:-1]} {key}")


def load_deliverables(catalog: dict, extra_dir: Path | None = None) -> dict[str, dict]:
    roots = [package_file("registry", "deliverables")]
    if extra_dir is not None and extra_dir.is_dir():
        roots.append(extra_dir)
    found = {}
    for root in roots:
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if not path.name.endswith(".json"):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_fields)
                _validate(record, catalog, root == roots[0])
                if path.name != f"{record['id']}.json" or record["id"] in found:
                    raise CatalogError(f"name the file {record['id']}.json and keep IDs unique")
            except (OSError, ValueError) as error:
                raise CatalogError(f"{path}: {error}") from error
            found[record["id"]] = record
    return dict(sorted(found.items()))


def launch_notice(deliverable: dict) -> list[str]:
    """What the requester must know before the tool runs: data needed and actions needing approval."""
    lines = [f"{item['label']} ({item['data']} data)" for item in deliverable["inputs"]]
    lines += [f"Needs your approval (task authorize --action {item['action']}): {item['description']}" for item in deliverable["tool_actions"]]
    return lines


def utm_link(url: str, values: dict[str, str | None]) -> str:
    """A landing URL tagged with UTM parameters, following the campaign-measurement pack.

    Values are trimmed and must be lowercase without spaces, so each one has a single spelling;
    an email address is refused, since personal data stays out of tags. Nothing is fetched.
    """
    address = urlsplit(url.strip())
    if address.scheme != "https" or not address.hostname or address.username is not None:
        raise ValueError("Give the landing page as an https address with a host and no credentials.")
    if any(key.lower().startswith("utm_") for key, _ in parse_qsl(address.query, keep_blank_values=True)):
        raise ValueError("The landing URL already carries utm_ parameters. Give the page address without them.")
    tags = []
    for name in UTM_ORDER:
        value = values.get(name)
        if value is None:
            continue
        value = value.strip()
        if "@" in value:
            raise ValueError(f"utm_{name} looks like an email address: keep personal data out of UTM values.")
        if not _UTM_VALUE.fullmatch(value):
            raise ValueError(f"Write utm_{name} in lowercase letters, digits, '.', '-' or '_', without spaces, "
                             f"as agreed with the analytics owner: {value!r}.")
        tags.append((f"utm_{name}", value))
    query = "&".join(part for part in (address.query, urlencode(tags)) if part)
    return urlunsplit((address.scheme, address.netloc, address.path, query, address.fragment))


def _market_lines(deliverable: dict, task: dict) -> tuple[list[str], list[str]]:
    """Front matter and input lines linking a market template to the dossier the task was consulted with."""
    if not deliverable.get("market"):
        return [], []
    dossier = task.get("consultation", {}).get("scope", {}).get("market")
    if not dossier:
        return [], ["- Market dossier: none attached. Create one in .openguildkit/market/ and consult the task with --market ID."]
    gaps = f", {len(dossier.get('gaps', []))} gap(s)" if dossier.get("gaps") else ""
    return [f"market: {json.dumps(dossier['id'])}"], [
        f"- Market dossier: .openguildkit/market/{dossier['id']}.json ({len(dossier.get('observations', []))} observation(s){gaps}); "
        f"cite observations as market:{dossier['id']}/ID"]


def new_draft(deliverable: dict, task: dict, tool: str | None, approved_tools: list[str], output: Path) -> dict:
    if task["status"] not in ("approved", "done"):
        raise ValueError("Start a deliverable from an approved or completed task.")
    if deliverable.get("requires_tool") and not tool:
        raise ValueError("This template needs --tool.")
    if tool and approved_tools and tool not in approved_tools:
        raise ValueError(f"{tool} is not an approved tool for this project. Approved: {', '.join(approved_tools)}.")
    if output.exists():
        raise ValueError(f"{output} already exists.")
    tool_fields = [f"tool: {json.dumps(tool)}"] if tool else []
    market_fields, market_inputs = _market_lines(deliverable, task)
    lines = [
        "---",
        f"deliverable: {json.dumps(deliverable['id'])}",
        f"task: {json.dumps(task['id'])}",
        *tool_fields,
        *market_fields,
        "---",
        "",
        f"# {deliverable['title']}",
        "",
        "## Inputs",
        "",
        *[f"- {item['label']}: TODO" for item in deliverable["inputs"]],
        *market_inputs,
        "",
    ]
    for section in deliverable["sections"]:
        lines += [f"## {section['title']}", "", f"<!-- {section['prompt']} -->", "TODO", ""]
    lines += ["## Sources", "", "- TODO: each source with its date or link", "", "## Checks", ""]
    lines += [f"- [ ] {check['id']}: {check['verification']} Evidence: " for check in deliverable["checks"]]
    write_text(output, "\n".join(lines) + "\n")
    return {"deliverable": deliverable["id"], "path": output.as_posix(), "tool": tool,
            "created_at": clock.timestamp()}


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
        problems.append(f"{visible.count('TODO')} placeholder(s) still say TODO.")
    if "Sources" in sections and not any(line.startswith("- ") and "TODO" not in line for line in sections["Sources"]):
        problems.append("List at least one source.")
    checked = {match["id"] for match in _CHECKED.finditer("\n".join(sections.get("Checks", [])))}
    for check in deliverable["checks"]:
        if check["id"] not in checked:
            problems.append(f"Check {check['id']} is not ticked with its evidence.")
    return problems
