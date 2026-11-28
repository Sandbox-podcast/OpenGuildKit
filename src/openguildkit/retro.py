"""The retrospective of a closed task and of the project: what the records already say, counted and never kept, with the
profile command a person could type.

`task retro ID` says what one closed task set aside, which boards brought nothing, what it left open and which
blockers it waived. `task retro --all` counts what comes back in several closed tasks and, for some findings, names the
profile command a person could type. Everything is a count taken from a task record (`.openguildkit/tasks/`) or from an
exported decision record (`.openguildkit/decisions/`): no model, no estimate, no field that holds a person, and no file
written unless the person asks for a draft rule pack with --draft-rules (draft_pack, write_draft). The functions take and
return dicts; reading the records is the command's part (tasks_cli.py).

Entry: facts_of_task, facts_of_record, task_retro, recurrences, proposals, project_summary, render_task, render_project
Tests: tests/test_rule_decline.py
"""

import re
from pathlib import Path

from . import lazy_re
from .patterns import pattern_selection
from .profile_changes import check_proposal
from .project import DRAFT_MARK
from .project_rules import resolved_profile
from .records import Catalog, Profile, Task
from .shell import shell_command
from .storage import write_json
from .tasks_closing import NOT_RUN_GROUP, OTHER_RULES_GROUP, SENSITIVE_GROUP, VERDICTS_GROUP
from .wording import plural
from .workflow import exported_blockers, objections

DEFAULT_MINIMUM = 3
DONE = ("done", "done-with-reservations")
SET_ASIDE = ("skipped", "not-applicable")
RULE_PREFIXES = ("rule:", "evidence:")
# The fields that hold a person, wherever a record has them: their values are taken out of the closing's lines.
PERSON_KEYS = frozenset({"by", "owner", "confirmed_by", "signer", "reviewer"})
# The closing groups that restate what the rules already count, or are only a record: not counted again as reservations.
RULE_GROUPS = (SENSITIVE_GROUP, OTHER_RULES_GROUP)
NOT_COUNTED_GROUPS = frozenset({*RULE_GROUPS, VERDICTS_GROUP})
KIND_ORDER = {"rule": 0, "committee": 1, "reservation": 2}
# What the text shows: a section is cut after MAX_LINES lines, a sentence after MAX_TEXT characters.
MAX_LINES, MAX_TEXT, MAX_IDS, MAX_EXAMPLES = 8, 160, 5, 3
# The reason written into a proposed command, which the profile history keeps: one line, at most this many characters.
MAX_REASON = 240
REASON_PREFIX = "task retro: "
_DATE = lazy_re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_BLOCKER = lazy_re.compile(r"\bblocker ([a-z0-9-]+):\d+")
_HANDED = lazy_re.compile(r"\bis handed to task [a-z0-9-]+")
_COMMAND_POINT = lazy_re.compile(r"^command:(\d+) could not run: (.*)$", re.DOTALL)


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _collapse(text: object) -> str:
    return " ".join(text.split()) if isinstance(text, str) else ""


def _key(text: str) -> str:
    """A reason or a wording compared without its case, its spacing or its final stop."""
    return _collapse(text).rstrip(".;: ").casefold()


def _wording(text: str) -> str:
    """A reservation said the same way in every task: no date, no number of a blocker, no name of a follow-up task."""
    text = _DATE.sub("<date>", text)
    text = _BLOCKER.sub(r"blocker \1", text)
    text = _HANDED.sub("is handed to a follow-up task", text)
    return _collapse(text).rstrip(".;: ")


def _sort_person_fields(value: dict, found: set[str], pending: list) -> None:
    """Add to found the person a field of value names, and to pending the other fields to look into."""
    for key, item in value.items():
        if key in PERSON_KEYS and isinstance(item, str):
            if item.strip():
                found.add(item.strip())
        else:
            pending.append(item)


def _people(record: object) -> set[str]:
    """Every text under a field that names a person, anywhere in a record."""
    found: set[str] = set()
    pending = [record]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            _sort_person_fields(value, found, pending)
        elif isinstance(value, list):
            pending.extend(value)
    return found


def _scrub(text: str, people: set[str]) -> str:
    """The text without the name a closing line puts in parentheses: `(NAME)` and `(recorded by NAME)`."""
    for name in sorted(people, key=lambda person: (-len(person), person)):
        text = re.sub(rf" ?\((?:recorded by )?{re.escape(name)}\)", "", text)
    return text


def _rule(check: str, status: str, reason: object) -> dict:
    return {"check": check, "status": status, "reason": _collapse(reason)}


def _pack_rules(result: dict) -> list[dict]:
    """A pack declared not applicable, skipped or failed as a whole stands for its rules."""
    found = []
    for item in _list(result.get("packs")):
        item = _dict(item)
        status, pack = item.get("status"), item.get("pack")
        if isinstance(pack, str) and status in (*SET_ASIDE, "failed"):
            found.append(_rule(f"pack:{pack}", status, item.get("reason" if status in SET_ASIDE else "evidence")))
    return found


def _rules_of_task(result: dict) -> list[dict]:
    found = []
    for item in _list(result.get("checks")):
        item = _dict(item)
        check, status = item.get("check"), item.get("status")
        if not isinstance(check, str) or not check.startswith(RULE_PREFIXES):
            continue
        if status in SET_ASIDE:
            found.append(_rule(check, status, item.get("reason")))
        elif status == "failed":
            found.append(_rule(check, status, item.get("evidence")))
    return sorted([*found, *_pack_rules(result)], key=lambda rule: (rule["check"], rule["status"]))


def _rules_of_record(result: dict) -> list[dict]:
    """An exported record keeps the reason of a rule set aside, and only the status of a rule that failed."""
    found = []
    for item in _list(result.get("check_exceptions")):
        item = _dict(item)
        check = item.get("check")
        if isinstance(check, str) and check.startswith(RULE_PREFIXES) and item.get("status") in SET_ASIDE:
            found.append(_rule(check, item["status"], item.get("reason")))
    for check, status in _dict(result.get("checks")).items():
        if status == "failed" and isinstance(check, str) and check.startswith(RULE_PREFIXES):
            found.append(_rule(check, "failed", ""))
    return sorted([*found, *_pack_rules(result)], key=lambda rule: (rule["check"], rule["status"]))


def _not_concerned(closing: dict) -> list[dict]:
    return [{key: item[key] for key in ("pack", "check", "reason", "checks") if key in item}
            for item in map(_dict, _list(closing.get("not_concerned"))) if isinstance(item.get("reason"), str)]


def _committees(task: Task) -> dict | None:
    """The boards convened, and those whose verdict was proceed with no blocker and no objection raised or received.

    The objections are those the deliberation recorded or, when it never ran, those the review gives (as task challenge
    shows them). None when the review cannot be read.
    """
    consultation, review = _dict(task.get("consultation")), _dict(task.get("review"))
    convened = [board for board in _list(consultation.get("boards")) if isinstance(board, str)]
    entries = {_dict(entry).get("id"): _dict(entry) for entry in _list(review.get("boards"))}
    deliberation = _dict(task.get("deliberation"))
    try:
        items = (deliberation["objections"] if isinstance(deliberation.get("objections"), list)
                 else objections(review, consultation.get("domains")))
    except (KeyError, TypeError, AttributeError, ValueError):
        return None
    involved = {board for item in items for board in (_dict(item).get("from"), _dict(item).get("to"))}
    without = []
    for board in convened:
        challenge = _dict(entries.get(board, {}).get("challenge"))
        if challenge.get("verdict") == "proceed" and challenge.get("blockers") == [] and board not in involved:
            without.append(board)
    return {"convened": convened, "without": without}


def _reservations(closing: dict, people: set[str]) -> list[dict]:
    groups = []
    for item in map(_dict, _list(closing.get("open_points"))):
        points = [_scrub(point, people) for point in _list(item.get("points")) if isinstance(point, str)]
        if isinstance(item.get("group"), str) and points:
            groups.append({"group": item["group"], "points": points})
    return groups


def _waivers(blockers: list) -> list[dict]:
    found = []
    for item in map(_dict, blockers):
        resolution = _dict(item.get("resolution"))
        if resolution.get("kind") == "waived":
            found.append({"blocker": str(item.get("id")), "board": item.get("board"),
                          "phase": item.get("phase") or "approval", "finding": item.get("finding") or "",
                          "until": resolution.get("until") or "", "reason": resolution.get("reason") or "",
                          "scope": resolution.get("scope") or ""})
    return sorted(found, key=lambda waiver: (waiver["until"], waiver["blocker"]))


def _refusal(task_id: object, status: object) -> ValueError:
    return ValueError(f"Task {task_id} is not closed (status {status}): only a task that is done or done with "
                      "reservations has a retrospective.")


def facts_of_task(task: Task) -> dict:
    """What a closed task's own record says, with no field that holds a person."""
    if task.get("status") not in DONE:
        raise _refusal(task.get("id"), task.get("status"))
    result = _dict(task.get("result"))
    closing = _dict(result.get("closing"))
    checks = _dict(_dict(task.get("consultation")).get("scope")).get("checks")
    return {
        "id": task["id"], "created": task.get("created_at") or "", "status": task["status"], "source": "task",
        "rules": _rules_of_task(result), "not_concerned": _not_concerned(closing), "committees": _committees(task),
        "reservations": _reservations(closing, _people(task)), "waivers": _waivers(exported_blockers(task)),
        "commands": {f"command:{number}": command for number, command in enumerate(_list(checks), start=1)
                     if isinstance(command, str)},
    }


def facts_of_record(record: dict) -> dict:
    """What an exported decision record says of a task it holds as completed. It carries no objections between
    boards, so it cannot say which board brought nothing."""
    if not isinstance(record.get("task"), str):
        raise ValueError("An exported record names its task: this one does not.")
    if record.get("completed") is not True or record.get("status") not in DONE:
        raise _refusal(record["task"], record.get("status"))
    result = _dict(record.get("result"))
    closing = _dict(result.get("closing"))
    return {
        "id": record["task"], "created": record.get("task_created_at") or "", "status": record["status"],
        "source": "record", "rules": _rules_of_record(result), "not_concerned": _not_concerned(closing),
        "committees": None, "reservations": _reservations(closing, _people(record)),
        "waivers": _waivers(_list(record.get("blockers"))), "commands": {},
    }


def task_retro(facts: dict) -> dict:
    """The retrospective of one task, as `task retro ID --json` prints it."""
    not_recorded = []
    if facts["committees"] is None and facts["source"] == "record":
        not_recorded.append("boards: an exported record keeps each board's verdict but not the objections between "
                            "boards, so it cannot say which board brought nothing; read the task record where the "
                            "task was closed")
    elif facts["committees"] is None:
        not_recorded.append("boards: the review of this task record cannot be read, so it cannot say which "
                            "board brought nothing")
    return {"task": facts["id"], "status": facts["status"],
            "source": "task record" if facts["source"] == "task" else "exported record",
            **{key: facts[key] for key in ("rules", "not_concerned", "committees", "reservations", "waivers")},
            "not_recorded": not_recorded}


def _findings(facts: dict) -> dict:
    """What one task says that another can say too, each once: (kind, key) -> the finding without its tasks."""
    found = {}
    for rule in facts["rules"]:
        reason = "" if rule["status"] == "failed" else rule["reason"]
        found.setdefault(("rule", rule["check"], rule["status"], _key(reason)),
                         {"check": rule["check"], "status": rule["status"], "reason": reason,
                          "label": f"{rule['check']} {rule['status']}"})
    for board in (facts["committees"] or {}).get("without", []):
        found.setdefault(("committee", board), {"board": board, "label": board})
    for group in facts["reservations"]:
        if group["group"] in NOT_COUNTED_GROUPS:
            continue
        for point in group["points"]:
            match = _COMMAND_POINT.match(point) if group["group"] == NOT_RUN_GROUP else None
            command = facts["commands"].get(f"command:{match.group(1)}") if match else None
            wording = _wording(f"`{command}` could not run: {match.group(2)}" if command else point)
            found.setdefault(("reservation", group["group"], wording.casefold()),
                             {"group": group["group"], "point": wording, "label": wording,
                              **({"check_command": command} if command else {})})
    return found


def recurrences(all_facts: list[dict], minimum: int) -> list[dict]:
    """The findings that come back in at least `minimum` tasks, each task counted once, whatever the order of the facts.

    A rule is counted with its status and its reason (a rule that failed, by rule alone); a committee in the tasks where
    it brought nothing, with the tasks where it was convened; a reservation by its wording.
    """
    if minimum < 1:
        raise ValueError("--min counts tasks: give a number of 1 or more.")
    ordered = sorted(all_facts, key=lambda facts: (facts["id"], facts["created"]))
    slots, convened = {}, {}
    for facts in ordered:
        for board in set((facts["committees"] or {}).get("convened", [])):
            convened[board] = convened.get(board, 0) + 1
        for key, finding in _findings(facts).items():
            slots.setdefault(key, {"kind": key[0], **finding, "tasks": []})["tasks"].append(facts["id"])
    found = []
    for slot in slots.values():
        if len(slot["tasks"]) >= minimum:
            if slot["kind"] == "committee":
                slot["convened_in"] = convened[slot["board"]]
            found.append({**slot, "count": len(slot["tasks"])})
    found.sort(key=lambda item: (KIND_ORDER[item["kind"]], -item["count"], item["label"], item.get("status", ""),
                                 item.get("reason", ""), item.get("group", "")))
    return found


def _active_patterns(profile: Profile) -> list[str]:
    return sorted({pattern_selection(entry)[0] for entry in _list(profile.get("patterns"))
                   if isinstance(entry, (str, dict))})


def _candidates(item: dict, profile: Profile, catalog: Catalog):
    """The profile commands that could answer a finding, as (action, field, value, pack it must stop), most direct
    first. One rule set aside in at least DEFAULT_MINIMUM tasks can be declined alone (profile decline rule, RFC #447),
    whatever --min says; no command settles a reservation or adds a committee's silence to the profile."""
    if item["kind"] == "rule" and item["status"] == "failed":
        if item["check"].startswith(("rule:", "pack:")):
            yield "add", "required-rule", item["check"].split(":", 1)[1], None
    elif item["kind"] == "rule" and item["check"].startswith("pack:"):
        pack = item["check"].removeprefix("pack:")
        yield "remove", "pack", pack, pack
        bringing = [pattern for pattern in _active_patterns(profile)
                    if pack in _dict(catalog["patterns"].get(pattern)).get("packs", [])]
        if len(bringing) == 1:
            yield "decline", None, bringing[0], pack
    elif item["kind"] == "rule" and item["check"].startswith("rule:") and item["count"] >= DEFAULT_MINIMUM:
        yield "decline", "rule", item["check"].removeprefix("rule:"), None
    elif item["kind"] == "committee" and item["convened_in"] == item["count"]:
        yield "remove", "board", item["board"], None
    elif item["kind"] == "reservation" and item.get("check_command"):
        yield "remove", "check", item["check_command"], None


def _finding_words(item: dict) -> str:
    """What a finding says, in the words of the text output, for the reason of its command."""
    if item["kind"] == "rule":
        return _collapse(f"{item['check']} {item['status']}")
    if item["kind"] == "committee":
        return f"{item['board']} brought no blocker or objection"
    return _collapse(item["point"])


def proposed_reason(item: dict) -> str:
    """The reason a proposed command carries, so that the profile history keeps the link to the retrospective: what
    comes back, in how many tasks and which, then the reason the tasks recorded. One line, at most MAX_REASON
    characters: the recorded reason is cut first, then what the finding says; the tasks stay."""
    tasks = f" in {item['count']} tasks ({_ids(item['tasks'])})"
    words = _finding_words(item)
    recorded = _collapse(item.get("reason")) if item["kind"] == "rule" else ""
    room = MAX_REASON - len(REASON_PREFIX) - len(tasks)
    if len(words) > room:
        words = words[:max(room - 3, 0)] + "..."
    reason = f"{REASON_PREFIX}{words}{tasks}"
    if recorded:
        tail = f": {recorded}"
        free = MAX_REASON - len(reason)
        if len(tail) > free:
            tail = tail[:free - 3] + "..." if free > 5 else ""
        reason += tail
    return reason[:MAX_REASON]


def _proposal(item: dict, profile: Profile, catalog: Catalog, before: set[str], powershell: bool | None) -> dict:
    """The first command the profile accepts whose effect is the one wanted, or none; before is the packs in force.
    The command carries a prefilled reason that names the tasks; --by INITIALS stays the person's to fill in."""
    for action, field, value, pack in _candidates(item, profile, catalog):
        try:
            updated, weakens = check_proposal(profile, catalog, action, field, value)
            after = resolved_profile(updated, catalog)
        except ValueError:
            continue
        dropped = before - set(after["packs"])
        if pack is not None and pack not in dropped:
            continue  # the pack stays: another pattern or the list still brings it
        if item["kind"] == "committee" and item["board"] in after["boards"]:
            continue  # the last board removed leaves every board advising
        reason = proposed_reason(item)
        words = ["openguildkit", "profile", action, *([field] if field else []), value, "--by", "INITIALS", "--reason",
                 reason]
        return {"command": shell_command(words, powershell), "needs_terminal": bool(weakens),
                "also_drops": sorted(dropped - {pack}) if pack is not None else [], "proposed_reason": reason}
    return {"command": None, "needs_terminal": False, "also_drops": [], "proposed_reason": None}


def proposals(found: list[dict], profile: Profile, catalog: Catalog, powershell: bool | None = None) -> list[dict]:
    """Each finding with the profile command that answers it, written and never run, or without one when the profile
    accepts none: a command is given only if the profile takes it and it does what the finding asks. The command is
    quoted for PowerShell on Windows and a POSIX shell elsewhere, unless powershell says which."""
    before = set(resolved_profile(profile, catalog)["packs"])
    return [{**item, **_proposal(item, profile, catalog, before, powershell)} for item in found]


def project_summary(all_facts: list[dict], minimum: int, profile: Profile, catalog: Catalog, ignored: dict) -> dict:
    """The retrospective of the project, as `task retro --all --json` prints it."""
    records = sum(1 for facts in all_facts if facts["source"] == "record")
    return {
        "minimum": minimum,
        "tasks": {"read": len(all_facts), "from_task_records": len(all_facts) - records, "from_exported_records": records},
        "ignored": {"unreadable_task_records": ignored.get("unreadable_task_records", 0),
                    "exported_records_not_holding": ignored.get("exported_records_not_holding", 0)},
        "recurrences": proposals(recurrences(all_facts, minimum), profile, catalog),
    }


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 3] + "..."


def _examples(names: list[str], limit: int = MAX_EXAMPLES) -> str:
    return ", ".join(names[:limit]) + (f", {len(names) - limit} more" if len(names) > limit else "")


def _capped(lines: list[str], more: str) -> list[str]:
    return lines if len(lines) <= MAX_LINES else [*lines[:MAX_LINES], f"  ... {len(lines) - MAX_LINES} more: {more}"]


def _grouped(items: list[dict], status: str, noun: str) -> list[str]:
    """One line for each reason shared by several items of one status."""
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(_key(item["reason"]), []).append(item)
    lines = []
    for members in sorted(groups.values(), key=lambda group: (-len(group), group[0]["reason"])):
        names = [member.get("check") or member.get("pack") for member in members]
        reason = f": {_clip(members[0]['reason'])}" if members[0]["reason"] else ""
        lines.append(f"  {plural(len(members), noun)} {status}{reason} ({_examples(names)})")
    return lines


def _reservation_lines(group: dict) -> list[str]:
    """The lines of one closing group: its short points on one line, the others one each; the groups that restate the
    rules set aside only say how many."""
    title, points = group["group"], group["points"]
    if title in RULE_GROUPS:
        return [f"  {title}: {len(points)} (listed under rules not applied)"]
    joined = "; ".join(points)
    if len(points) > 1 and len(joined) <= MAX_TEXT:
        return [f"  {title}: {joined}"]
    return [f"  {title}: {_clip(point)}" for point in points]


def render_task(retro: dict) -> list[str]:
    """The retrospective of one task in a few lines, with the command for the detail."""
    task_id, more = retro["task"], f"openguildkit task retro {retro['task']} --json"
    lines = [f"Retrospective of {task_id}, closed as {retro['status']}: read from the {retro['source']}. "
             "It writes nothing."]
    rules, concerned = retro["rules"], retro["not_concerned"]
    if rules or concerned:
        lines.append(f"Rules not applied: {len(rules)} set aside or failed, {len(concerned)} not concerned.")
        entries = []
        for status in ("failed", "skipped", "not-applicable"):
            entries += _grouped([rule for rule in rules if rule["status"] == status], status, "rule")
        for noun, key in (("pack", "pack"), ("check", "check")):
            entries += _grouped([item for item in concerned if key in item], "not concerned", noun)
        lines += _capped(entries, more)
    committees = retro["committees"]
    if committees is None:
        lines.append("Boards: not in the exported record (it carries no objections between boards)."
                     if retro["source"] == "exported record" else
                     "Boards: not read (the review of this task record cannot be read).")
    elif committees["without"]:
        lines.append(f"Boards: {len(committees['convened'])} convened; without a blocker or an objection, and "
                     f"proceeding: {', '.join(committees['without'])}.")
    else:
        lines.append(f"Boards: {len(committees['convened'])} convened; none without a blocker or an objection.")
    groups = retro["reservations"]
    if groups:
        points = sum(len(group["points"]) for group in groups)
        lines.append(f"Open reservations ({points}), most serious first:")
        lines += _capped([line for group in groups for line in _reservation_lines(group)], more)
    if retro["waivers"]:
        lines.append(f"Blockers waived ({len(retro['waivers'])}):")
        lines += _capped([f"  {item['blocker']} until {item['until']}: {_clip(item['reason'])} (scope: "
                          f"{_clip(item['scope'])})" for item in retro["waivers"]], more)
    if not (rules or concerned or groups or retro["waivers"]):
        lines.append("Nothing left open: no rule set aside, no waived blocker, no reservation.")
    return [*lines, f"Detail for a program: {more}", "Across the closed tasks: openguildkit task retro --all"]


def _ids(tasks: list[str]) -> str:
    return _examples(tasks, MAX_IDS)


def _rule_findings(items: list[dict]) -> list[list[str]]:
    """The rules that come back, one entry each; those set aside the same way in the same tasks with no command to
    propose share one line."""
    shared = {}
    for item in items:
        if item["command"] is None:
            shared.setdefault((item["status"], _key(item["reason"]), tuple(item["tasks"])), []).append(item)
    out, done = [], set()
    for item in items:
        reason = f": {_clip(item['reason'])}" if item["reason"] else ""
        line = f"{item['check']} {item['status']} in {item['count']} tasks ({_ids(item['tasks'])}){reason}"
        if item["command"] is not None:
            out.append([f"  {line}", *_command_lines(item)])
            continue
        key = (item["status"], _key(item["reason"]), tuple(item["tasks"]))
        if key in done:
            continue
        done.add(key)
        members = shared[key]
        if len(members) == 1:
            out.append([f"  {line}"])
        else:
            out.append([f"  {len(members)} rules {item['status']} in {item['count']} tasks ({_ids(item['tasks'])})"
                        f"{reason} ({_examples([member['check'] for member in members])})"])
    return out


def _command_lines(item: dict) -> list[str]:
    if not item.get("command"):
        return []
    notes = []
    if item["also_drops"]:
        notes.append(f"also drops {', '.join(item['also_drops'])}")
    if item["needs_terminal"]:
        notes.append("it lowers a protection: type it at an interactive terminal")
    return [f"      profile: {item['command']}" + (f" ({'; '.join(notes)})" if notes else "")]


def _point_line(item: dict) -> str:
    """A reservation that comes back, its command cut when it is long so that the reason stays."""
    point, command = item["point"], item.get("check_command")
    if command and len(command) > 60:
        point = point.replace(command, command[:57] + "...", 1)
    return f"  {_clip(point)} in {item['count']} tasks ({_ids(item['tasks'])})"


def _section(title: str, entries: list[list[str]]) -> list[str]:
    if not entries:
        return []
    shown = entries[:MAX_LINES]
    lines = [title, *(line for entry in shown for line in entry)]
    if len(entries) > MAX_LINES:
        lines.append(f"  ... {len(entries) - MAX_LINES} more: openguildkit task retro --all --json")
    return lines


def render_project(summary: dict) -> list[str]:
    """The retrospective of the project in a few lines: one per finding that comes back, with its command."""
    tasks, ignored, minimum = summary["tasks"], summary["ignored"], summary["minimum"]
    notes = []
    if ignored["unreadable_task_records"]:
        count = ignored["unreadable_task_records"]
        notes.append(f"{plural(count, 'task record')} unreadable and left out: openguildkit task list names "
                     f"{'it' if count == 1 else 'them'}.")
    if ignored["exported_records_not_holding"]:
        count = ignored["exported_records_not_holding"]
        notes.append(f"{plural(count, 'exported record')} {'does' if count == 1 else 'do'} not match "
                     f"{'its' if count == 1 else 'their'} digest and {'is' if count == 1 else 'are'} left out: "
                     "openguildkit check names the file.")
    if not tasks["read"]:
        return ["No closed task to count: a retrospective reads the tasks that are done or done with reservations. "
                "List the tasks with openguildkit task list.", *notes]
    lines = [f"Retrospective of the project: {plural(tasks['read'], 'closed task')} read "
             f"({plural(tasks['from_task_records'], 'task record')}, "
             f"{plural(tasks['from_exported_records'], 'exported record')}). A finding counts once per task and is "
             f"shown when it comes back in at least {minimum} (--min N changes that). "
             f"{'It writes only the draft named below.' if summary.get('draft') else 'It writes nothing.'}", *notes]
    found = summary["recurrences"]
    if not found and minimum == 1:
        return [*lines, "Nothing to count: no closed task set a rule aside, left a reservation open or had a board "
                        "that brought nothing."]
    if not found:
        return [*lines, f"Nothing comes back in {minimum} tasks or more. Try a lower minimum: openguildkit task retro "
                        f"--all --min {minimum - 1}."]
    rules = _rule_findings([item for item in found if item["kind"] == "rule"])
    committees = [[f"  {item['board']}: no blocker or objection in {item['count']} of the {item['convened_in']} "
                   f"task{'' if item['convened_in'] == 1 else 's'} where it was convened ({_ids(item['tasks'])})",
                   *_command_lines(item)] for item in found if item["kind"] == "committee"]
    reservations = [[_point_line(item), *_command_lines(item)] for item in found if item["kind"] == "reservation"]
    lines += _section("Rules set aside or failed again:", rules)
    lines += _section("Boards without a blocker or an objection (task records only):", committees)
    lines += _section("Reservations that come back:", reservations)
    lines.append("None of these commands was run. A command that lowers a protection is the person's decision, typed "
                 "at an interactive terminal; --by is theirs to fill in, and --reason, which names the tasks, theirs "
                 "to edit."
                 if any(item["command"] for item in found) else
                 "No profile command answers these findings as the profile stands.")
    return lines


def _rule_id(point: str, taken: set[str]) -> str:
    """A rule ID in the catalog format from the first words of a reservation, unique in the draft."""
    words = re.findall(r"[a-z0-9]+", point.casefold())[:6]
    base = "-".join(words)[:48].strip("-") or "rule"
    rule_id, number = base, 2
    while rule_id in taken:
        rule_id, number = f"{base}-{number}", number + 1
    taken.add(rule_id)
    return rule_id


def draft_pack(found: list[dict], day: str) -> dict | None:
    """A project pack in the catalog format, marked as a draft, with one rule to write for each reservation that comes
    back, or None when none does. Rules set aside or failed have their profile command; a reservation has none, and a
    project rule is what would keep it from coming back. Every rule is a TODO for a person to write: the draft says what
    came back and in which tasks, never what to do about it, and no profile uses it while its description is the draft's
    (project.validate_profile)."""
    points = [item for item in found if item["kind"] == "reservation"]
    if not points:
        return None
    taken: set[str] = set()
    rules = [{"id": _rule_id(item["point"], taken),
              "instruction": f"TODO: an action an agent can take so that this stops coming back: {_clip(item['point'])} "
                             f"in {item['count']} tasks ({_ids(item['tasks'])}).",
              "verification": "TODO: how a person checks it in a task record or a pull request."} for item in points]
    return {"id": f"retro-draft-{day}", "title": "TODO: name of the project rule pack", "version": "0.1.0",
            "description": f"{DRAFT_MARK} on {day}, not active: write each rule, replace each TODO and this description, "
                           "then copy the file to .openguildkit/catalog/packs/ and add the pack with openguildkit "
                           "profile add pack.",
            "sources": [], "rules": rules}


def write_draft(root: Path, state: Path, folder: Path, pack: dict) -> str:
    """Write the draft in a folder of the project outside .openguildkit/, where no catalog reads it, never over a file;
    the path as the project names it."""
    from .deliverables import project_path  # only --draft-rules needs it: the CLI starts without deliverables

    path = project_path(root, state, folder, "--draft-rules") / f"{pack['id']}.json"
    shown = path.relative_to(root.resolve()).as_posix()
    if path.exists():
        raise ValueError(f"{shown} already exists: review it, rename it or remove it before writing another draft "
                         "today. Nothing was written.")
    write_json(path, pack)
    return shown


def render_draft(draft: dict | None, minimum: int) -> list[str]:
    """What --draft-rules wrote, and what the person does next."""
    if draft is None:
        return [f"No draft written: no reservation comes back in {minimum} tasks or more, and a rule set aside or "
                "failed has its profile command above."]
    return [f"Draft rule pack written: {draft['path']} ({plural(draft['rules'], 'rule')} to write, not active). Next: "
            "write each rule and replace each TODO and the description, copy the file to .openguildkit/catalog/packs/, "
            f"then openguildkit profile add pack {draft['pack']} --by INITIALS --reason WHY."]
