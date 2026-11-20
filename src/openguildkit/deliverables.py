"""Business deliverables: a method's template, the inputs it needs, the tool actions that need
approval and the checks a reviewer runs on the result.

Templates live in registry/deliverables/ (and .openguildkit/catalog/deliverables/ for a
project). `deliverable new` turns an approved task into a draft; `deliverable check` says what
is still missing before the brain and the owner review it.
"""

import json
import re
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from .catalog import CatalogError, _unique_fields, _validate_fields, _validate_id, _validate_list, _validate_sources, _validate_text
from .storage import write_text

DATA_CLASSES = ("none", "internal", "personal", "regulated")
ACTIONS = ("public-research", "external-api", "send-message", "publish", "install-dependency", "other")
_CHECKED = re.compile(r"^- \[x\] (?P<id>[a-z0-9-]+): .+? Evidence: (?P<evidence>\S.*)$", re.MULTILINE)


def _validate(record: dict, catalog: dict) -> None:
    _validate_fields(record, "deliverable", {"id", "title", "description", "brains", "inputs", "tool_actions", "sections", "checks", "sources"}, {"method"})
    _validate_id(record["id"], "id")
    for field in ("title", "description"):
        _validate_text(record[field], field)
    _validate_sources(record["sources"])
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
    roots = [files("openguildkit").joinpath("registry", "deliverables")]
    if extra_dir is not None and extra_dir.is_dir():
        roots.append(extra_dir)
    found = {}
    for root in roots:
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if not path.name.endswith(".json"):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_fields)
                _validate(record, catalog)
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


def new_draft(deliverable: dict, task: dict, tool: str, approved_tools: list[str], output: Path) -> dict:
    if task["status"] not in ("approved", "done"):
        raise ValueError("Start a deliverable from an approved task.")
    if approved_tools and tool not in approved_tools:
        raise ValueError(f"{tool} is not an approved tool for this project. Approved: {', '.join(approved_tools)}.")
    if output.exists():
        raise ValueError(f"{output} already exists.")
    decision = task["decision"]
    lines = [
        "---",
        f"deliverable: {json.dumps(deliverable['id'])}",
        f"task: {json.dumps(task['id'])}",
        f"tool: {json.dumps(tool)}",
        f"approved_by: {json.dumps(decision['by'])}",
        f"decision_reason: {json.dumps(decision['reason'])}",
        "---",
        "",
        f"# {deliverable['title']}",
        "",
        "## Inputs",
        "",
        *[f"- {item['label']}: TODO" for item in deliverable["inputs"]],
        "",
    ]
    for section in deliverable["sections"]:
        lines += [f"## {section['title']}", "", f"<!-- {section['prompt']} -->", "TODO", ""]
    lines += ["## Sources", "", "- TODO: each source with its date or link", "", "## Checks", ""]
    lines += [f"- [ ] {check['id']}: {check['verification']} Evidence: " for check in deliverable["checks"]]
    write_text(output, "\n".join(lines) + "\n")
    return {"deliverable": deliverable["id"], "path": output.as_posix(), "tool": tool,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def draft_problems(deliverable: dict, text: str) -> list[str]:
    """What keeps a draft from review: placeholders, missing sources, unchecked controls."""
    problems = []
    if "TODO" in text:
        problems.append(f"{text.count('TODO')} placeholder(s) still say TODO.")
    sources = text.split("## Sources", 1)[-1].split("## Checks", 1)[0]
    if not any(line.strip().startswith("- ") and "TODO" not in line for line in sources.splitlines()):
        problems.append("List at least one source.")
    checked = {match["id"] for match in _CHECKED.finditer(text)}
    for check in deliverable["checks"]:
        if check["id"] not in checked:
            problems.append(f"Check {check['id']} is not ticked with its evidence.")
    return problems
