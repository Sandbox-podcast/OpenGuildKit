"""Checks the review entry a board returns: its findings, its evidence, its challenge and its warnings."""

import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import clock, lazy_re
from .board_brief import CONTEST_ITEM
from .consultation import CHOICES, EVIDENCE_SOURCES, market_references, one_based, storybook_references, tool_references
from .questionnaire import ASSUMPTIONS
from .sensitive import credential_problems, public_evidence_url, redact_credentials


def required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain text.")
    return value.strip()


def _text_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings.")
    return [required_text(item, field) for item in value]


DATED_SOURCES = ("public", "measurement", "interview")


_DATE = lazy_re.compile(r"\d{4}-\d{2}-\d{2}")


_REVISION = lazy_re.compile(r"[0-9a-f]{7,64}")


_LOCATION = lazy_re.compile(r"(?:::.*|#.*|:\d+(?:-\d+)?)$")


def _evidence_day(value: object, field: str) -> str:
    """A real YYYY-MM-DD date that is not in the future on the real clock (one day of margin for time zones)."""
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError(f"{field}: got {received_value(value)}; write the date YYYY-MM-DD.")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field}: {value} is not a real date. Write it YYYY-MM-DD.") from None
    if day > clock.real_today() + timedelta(days=1):
        raise ValueError(f"{field}: {value} is in the future. Write the day the evidence was observed.")
    return value


def _project_path(ref: str, field: str, root: Path) -> None:
    """A project file or test cited as evidence exists in the project, with an optional :LINE, #anchor or ::test."""
    if ref.startswith(("https://", "market:", "storybook:")):
        return
    project = root.resolve()
    path = (project / _LOCATION.sub("", ref)).resolve()
    if not path.exists() or (path != project and project not in path.parents):
        raise ValueError(
            f"{field}: {ref} is not a file or folder of the project. Cite a path relative to the project root, "
            "optionally followed by :LINE."
        )


def _evidence_item(
    item: object, field: str, market_refs: frozenset = frozenset(), storybook_refs: frozenset = frozenset(),
    tool_ids: frozenset = frozenset(), root: Path | None = None, problems: list[str] | None = None,
) -> dict | None:
    """An evidence item says where it comes from, what it supports and how to find it again.

    With problems, each problem of the item is added there with its key path, so that one submission reports them
    all, and None is returned; without, the first problem is raised."""
    found: list[str] = []
    if not isinstance(item, dict) or not {"source", "ref", "supports"} <= item.keys() \
            or not item.keys() <= {"source", "ref", "supports", "date", "revision"}:
        found.append(
            f"{field}: each item is an object with source, ref and supports, and can add date or revision, "
            f"as in the template's evidence_item."
        )
        return _evidence_outcome(None, found, problems)
    source = item["source"]
    if source not in EVIDENCE_SOURCES:
        found.append(f"{field}.source: got {received_value(source)}; accepted: {', '.join(EVIDENCE_SOURCES)}.")
        source = None
    result = {"source": source, "ref": _checked(found, required_text, item["ref"], f"{field}.ref"),
              "supports": _checked(found, required_text, item["supports"], f"{field}.supports")}
    if source == "tool" and result["ref"] is not None:
        result["ref"] = _tool_reference(result["ref"], tool_ids)
    ref = result["ref"]
    if ref is not None:
        _checked(found, _check_reference, ref, source, f"{field}.ref", market_refs, storybook_refs, tool_ids, root)
    if "date" in item:
        result["date"] = _checked(found, _evidence_day, item["date"], f"{field}.date")
    if "revision" in item:
        if not isinstance(item["revision"], str) or not _REVISION.fullmatch(item["revision"]):
            found.append(f"{field}.revision: got {received_value(item['revision'])}; write a commit SHA.")
        result["revision"] = item["revision"]
    if source in DATED_SOURCES and "date" not in item and ref is not None and not ref.startswith("market:"):
        found.append(f"{field}.date: a {source} source needs the date it was observed.")
    return _evidence_outcome(result, found, problems)


def _tool_reference(ref: str, tool_ids: frozenset) -> str:
    """A tool's name is read in any case, as everywhere else, and recorded as the registry writes it."""
    tool_id, separator, record = ref.partition(":")
    known = {item.casefold(): item for item in tool_ids}
    return f"{known[tool_id.casefold()]}{separator}{record}" if separator and tool_id.casefold() in known else ref


def _evidence_outcome(result: dict | None, found: list[str], problems: list[str] | None) -> dict | None:
    if not found:
        return result
    if problems is None:
        raise ValueError(found[0])
    problems.extend(found)
    return None


def _check_reference(
    ref: str, source: str | None, field: str, market_refs: frozenset, storybook_refs: frozenset, tool_ids: frozenset,
    root: Path | None,
) -> None:
    """A reference names a recorded market observation or story, a connected tool's record, an https page or a
    project file, as its source requires."""
    if ref.startswith("market:") and ref not in market_refs:
        raise ValueError(f"{field}: {ref} is not an observation or change of the attached market dossier.")
    if ref.startswith("storybook:") and ref not in storybook_refs:
        raise ValueError(f"{field}: {ref} is not a story of the Storybook indexes the project recorded.")
    if source == "tool":
        tool_id, separator, record = ref.partition(":")
        if not separator or not record.strip() or tool_id not in tool_ids:
            connected = ", ".join(sorted(tool_ids)) or "none"
            raise ValueError(
                f"{field}: a tool source is written TOOL:RECORD (for example jira:SUP-142) for a tool connected to the "
                f"project. Connected: {connected}."
            )
    if source == "public" and not ref.startswith("market:"):
        if not ref.startswith("https://"):
            raise ValueError(f"{field}: a public source needs an https link in ref.")
        if root is not None:
            public_evidence_url(ref, field)
    if root is not None and source in ("project-file", "test"):
        _project_path(ref, field, root)


def received_value(value: object) -> str:
    """The value a person sent, short enough for one line of an error."""
    text = redact_credentials(json.dumps(value, ensure_ascii=False)[:2000])
    return text if len(text) <= 60 else text[:57] + "..."


class EntryProblems(ValueError):
    """Every problem of one board's entry, each with its key path, the value received and the accepted values."""

    def __init__(self, board_id: str, problems: list[str]):
        self.problems = problems
        heading = f"{board_id} entry has {len(problems)} problem{'s' if len(problems) > 1 else ''}"
        super().__init__(heading + ":\n- " + "\n- ".join(problems))


# A key the entry lacks: its absence is reported once by _keys, and its own check is skipped.
_ABSENT = object()


def _checked(problems: list[str], function, *args):
    """Run one field's check; record its problem and go on with the other fields."""
    if args and args[0] is _ABSENT:
        return None
    try:
        return function(*args)
    except ValueError as error:
        problems.append(str(error))
        return None


def _choice(value: object, field: str, path: str, problems: list[str]) -> str | None:
    if isinstance(value, str) and value in CHOICES[field]:
        return value
    problems.append(f"{path}: got {received_value(value)}; accepted: {', '.join(CHOICES[field])}.")
    return None


def _keys(value: object, expected: set, optional: set, path: str, problems: list[str]) -> bool:
    """An object with the expected keys; missing and unknown keys are both reported."""
    if not isinstance(value, dict):
        problems.append(f"{path}: got {received_value(value)}; expected an object with {', '.join(sorted(expected))}.")
        return False
    missing, unknown = expected - value.keys(), value.keys() - expected - optional
    if missing:
        problems.append(f"{path}: missing {', '.join(sorted(missing))}.")
    if unknown:
        problems.append(f"{path}: unknown {', '.join(sorted(unknown))}; accepted keys: "
                        f"{', '.join(sorted(expected | optional))}.")
    return not missing


def _blocker(item: object, path: str, problems: list[str]) -> dict | None:
    """A blocking finding names who can resolve it and what would clear it."""
    if not isinstance(item, dict):
        problems.append(f"{path}: got {received_value(item)}; each blocker is an object with finding, owner and "
                        "clears_when, as in blocker_item.")
        return None
    _keys(item, {"finding", "owner", "clears_when"}, {"phase"}, path, problems)
    blocker = {key: _checked(problems, required_text, item.get(key, _ABSENT), f"{path}.{key}")
               for key in ("finding", "owner", "clears_when")}
    if "phase" in item:
        blocker["phase"] = _choice(item["phase"], "phase", f"{path}.phase", problems)
    return blocker


def evidence_positions(references: object, count: int, path: str, problems: list[str]) -> list[int]:
    """Positions in the entry's own evidence list, counted from one."""
    if not isinstance(references, list):
        problems.append(f"{path}: got {received_value(references)}; write a list of positions such as [1, 3].")
        return []
    wrong = [index for index in references if type(index) is not int or not 1 <= index <= count]
    if wrong:
        valid = f"1 to {count}" if count else "none: the entry's evidence list is empty, add the evidence first"
        problems.append(
            f"{path}: {received_value(wrong)} must point to the board's evidence list: evidence_refs are positions in "
            f"this entry's own evidence list, counted from 1 ([1, 3] cites its first and third items); valid here: "
            f"{valid}."
        )
    return [index for index in references if index not in wrong]


def _validate_challenge(
    board_id: str, challenge: object, template: dict, evidence: list, structured: bool, problems: list[str],
    not_concerned: set[str] | frozenset = frozenset(),
) -> dict:
    path = f"{board_id}.challenge"
    if not isinstance(challenge, dict):
        _keys(challenge, set(template), set(), path, problems)
        return {}
    _keys(challenge, set(template), set(), path, problems)
    challenge = {key: challenge.get(key, _ABSENT) for key in template}
    verdict = confidence = None
    if challenge["verdict"] is not _ABSENT:
        verdict = _choice(challenge["verdict"], "verdict", f"{path}.verdict", problems)
    if challenge["confidence"] is not _ABSENT:
        confidence = _choice(challenge["confidence"], "confidence", f"{path}.confidence", problems)
    if verdict == "insufficient-evidence" and confidence not in (None, "low"):
        problems.append(f"{path}.confidence: {board_id} must use low confidence when evidence is insufficient.")
    expected = [specialist["id"] for specialist in template["specialists"]]
    specialists = challenge["specialists"]
    findings = {}
    if specialists is _ABSENT:
        specialists = []
    elif not isinstance(specialists, list):
        problems.append(f"{path}.specialists: got {received_value(specialists)}; expected a list of lens findings.")
        specialists = []
    for position, specialist in enumerate(specialists):
        lens_path = f"{path}.specialists[{position}]"
        if not _keys(specialist, {"id", "finding", "basis", "evidence_refs"}, set(), lens_path, problems):
            continue
        specialist_id = specialist["id"]
        if isinstance(specialist_id, str) and specialist_id in not_concerned:
            problems.append(f"{lens_path}.id: {specialist_id} is not concerned by this task's surfaces: remove it "
                            "from the entry.")
            continue
        if not isinstance(specialist_id, str) or specialist_id not in expected or specialist_id in findings:
            problems.append(f"{lens_path}.id: unexpected or repeated {board_id} specialist {received_value(specialist_id)}; "
                            f"expected each of {', '.join(expected)} once.")
            continue
        lens_path = f"{board_id}/{specialist_id}"
        basis = _choice(specialist["basis"], "basis", f"{lens_path} basis", problems)
        references = evidence_positions(specialist["evidence_refs"], len(evidence), f"{lens_path} evidence_refs", problems)
        if basis == "observed" and not references:
            problems.append(f"{lens_path} needs an evidence reference for an observed finding.")
        findings[specialist_id] = {
            "id": specialist_id, "finding": _checked(problems, required_text, specialist["finding"], f"{lens_path} finding"),
            "basis": basis, "evidence_refs": list(dict.fromkeys(references)),
        }
    # A lens whose finding is malformed is already reported; only the lenses never written are missing.
    written = {item.get("id") for item in specialists if isinstance(item, dict) and isinstance(item.get("id"), str)}
    missing = [specialist_id for specialist_id in expected if specialist_id not in written]
    if missing and challenge["specialists"] is not _ABSENT and isinstance(challenge["specialists"], list):
        problems.append(f"{path}.specialists: {board_id} specialist findings are missing for {', '.join(missing)}.")
    observed = any(finding["basis"] == "observed" for finding in findings.values())
    if (verdict == "proceed" or confidence == "high") and findings and not observed:
        problems.append(f"{path}: {board_id} needs an observed finding and cited evidence for this review.")
    if (verdict == "proceed" or confidence == "high") and observed and evidence and isinstance(evidence[0], dict):
        cited = {
            index for finding in findings.values() if finding["basis"] == "observed" for index in finding["evidence_refs"]
        }
        if all(evidence[index - 1].get("source") == "requester" for index in cited):
            problems.append(
                f"{path}: {board_id}: the requester's own words cannot be the only evidence for this verdict. "
                "Cite a project file, test, measurement or other inspected source."
            )
    blockers = [] if challenge["blockers"] is _ABSENT else challenge["blockers"]
    if not isinstance(blockers, list):
        problems.append(f"{path}.blockers: got {received_value(blockers)}; expected a list, empty unless the board blocks.")
        blockers = []
    elif structured:
        blockers = [_blocker(item, f"{path}.blockers[{index}]", problems) for index, item in enumerate(blockers)]
    else:
        blockers = _checked(problems, _text_list, blockers, f"{path}.blockers") or []
    if verdict == "block" and not blockers:
        problems.append(f"{path}.blockers: {board_id} must name the blocking findings.")
    if verdict == "proceed" and any(
        not isinstance(blocker, dict) or blocker.get("phase") != "verification" for blocker in blockers
    ):
        problems.append(f"{path}.blockers: {board_id} cannot recommend proceeding with unresolved blockers; only "
                        "blockers of phase verification can go with proceed.")
    return {
        "specialists": [findings[specialist_id] for specialist_id in expected if specialist_id in findings],
        "verdict": verdict,
        "confidence": confidence,
        **{field: _checked(problems, required_text, challenge[field], f"{path}.{field}")
           for field in ("alternative", "failure_mode", "verification")},
        "blockers": blockers,
    }


def _contested(items: object, count: int, path: str, problems: list[str]) -> list[dict]:
    """The task's assumptions a board contests: each names one by its number, counted from 1, and says why."""
    if not isinstance(items, list):
        problems.append(f"{path}: got {received_value(items)}; expected a list of {json.dumps(CONTEST_ITEM)}, empty when "
                        "the board contests no assumption.")
        return []
    contested = []
    for position, item in enumerate(items, start=1):
        item_path = f"{path}[{position}]"
        if not _keys(item, set(CONTEST_ITEM), set(), item_path, problems):
            continue
        number = item["assumption"]
        if type(number) is not int or not 1 <= number <= count:
            problems.append(f"{item_path}.assumption: got {received_value(number)}; the number of a listed assumption, "
                            f"1 to {count}.")
            continue
        reason = _checked(problems, required_text, item["reason"], f"{item_path}.reason")
        if reason:
            contested.append({"assumption": number, "reason": reason})
    return contested


EXECUTION_MODES = ("subagents", "sequential", "mixed", "unspecified")


def validate_board_entry(consultation: dict, entry: object, root: Path | None = None) -> dict:
    """Validate one board's review entry against the consultation's template, reporting every problem at once.

    With the project root, at recording time, a cited project file or test must exist.
    """
    selected = consultation["boards"]
    if not isinstance(entry, dict):
        raise ValueError("A board review must be a JSON object, as printed under Entry to return.")
    board_id = entry.get("id")
    if not isinstance(board_id, str) or not board_id.strip():
        raise ValueError(f"id: got {received_value(board_id)}; write the board's ID, one of {', '.join(selected)}.")
    board_id = board_id.strip()
    if board_id not in selected:
        raise ValueError(f"id: board {board_id!r} was not selected for this consultation. Selected: {', '.join(selected)}.")
    templates = {item["id"]: item for item in consultation.get("review_template", {}).get("boards", [])}
    template = templates.get(board_id, {})
    fields = {"id", "recommendation", "evidence", "open_questions"} | ({"challenge", "reviewer"} & template.keys())
    assumed = consultation.get("scope", {}).get("answers", {}).get(ASSUMPTIONS, [])
    problems = []
    _keys(entry, fields, {"contested_assumptions"} if assumed else set(), board_id, problems)
    contested = entry.get("contested_assumptions", []) if assumed and isinstance(entry, dict) else []
    credentials = []
    if root is not None:
        credentials = [one_based(problem) for problem in
                       credential_problems({key: entry[key] for key in fields - {"id"} if key in entry}, board_id)]
    entry = {key: entry.get(key, _ABSENT) for key in fields}
    scope = consultation.get("scope", {})
    structured = consultation.get("evidence_format") == "structured"
    evidence = [] if entry["evidence"] is _ABSENT else entry["evidence"]
    if not isinstance(evidence, list):
        problems.append(f"{board_id}.evidence: got {received_value(evidence)}; expected a list of evidence items.")
        evidence = []
    if structured:
        checked = [
            _evidence_item(item, f"{board_id}.evidence[{index}]", market_references(scope), storybook_references(scope),
                           tool_references(scope), root, problems)
            for index, item in enumerate(evidence, start=1)
        ]
    else:
        checked = _checked(problems, _text_list, evidence, f"{board_id} evidence") or []
    result = {
        "id": board_id,
        "recommendation": _checked(problems, required_text, entry["recommendation"], f"{board_id}.recommendation"),
        "evidence": checked,
        "open_questions": _checked(problems, _text_list, entry["open_questions"], f"{board_id}.open_questions"),
    }
    if "reviewer" in template:
        result["reviewer"] = _checked(problems, required_text, entry["reviewer"], f"{board_id}.reviewer")
    if "challenge" in template and entry["challenge"] is not _ABSENT:
        stored = consultation.get("board_briefs", {}).get(board_id, {})
        listed = stored.get("lenses_not_concerned") if isinstance(stored, dict) else None
        not_concerned = {lens["id"] for lens in listed if isinstance(lens, dict) and isinstance(lens.get("id"), str)} \
            if isinstance(listed, list) else set()
        result["challenge"] = _validate_challenge(
            board_id, entry["challenge"], template["challenge"], [item or {} for item in checked], structured, problems,
            not_concerned,
        )
    contested = _contested(contested, len(assumed), f"{board_id}.contested_assumptions", problems)
    if contested:
        result["contested_assumptions"] = contested
    # A field another check already refuses is reported once, by that check.
    reported = {problem.split(": ", 1)[0] for problem in problems}
    problems.extend(problem for problem in credentials if problem.split(": ", 1)[0] not in reported)
    if problems:
        raise EntryProblems(board_id, problems)
    return result


def validate_review(consultation: dict, review: dict, root: Path | None = None) -> dict:
    """Require a recommendation for every board in the recorded consultation; report every board's problems at once."""
    # kept: the passes a reopened approval kept (tasks_review.kept_passes); only task review --summary records it.
    allowed = {"consultation_id", "summary", "boards", "execution", "warnings", "evidence_item", "blocker_item", "kept"}
    if not isinstance(review, dict) or not {"consultation_id", "summary", "boards"} <= review.keys() \
            or not review.keys() <= allowed:
        raise ValueError("A review must contain consultation_id, summary and boards. Run task template.")
    execution = review.get("execution", "unspecified")
    if execution not in EXECUTION_MODES:
        raise ValueError(f"Review execution must be one of {', '.join(EXECUTION_MODES)}.")
    if review["consultation_id"] != consultation["id"]:
        raise ValueError("This review belongs to another consultation. Run task template again.")
    summary = required_text(review["summary"], "Review summary")
    if not isinstance(review["boards"], list):
        raise ValueError("Review boards must be a list.")

    selected = consultation["boards"]
    found, problems = {}, []
    for entry in review["boards"]:
        try:
            result = validate_board_entry(consultation, entry, root)
        except EntryProblems as error:
            problems.extend(error.problems)
            continue
        except ValueError as error:
            problems.append(str(error))
            continue
        if result["id"] in found:
            problems.append(f"Provide one review for board {result['id']!r}.")
        found[result["id"]] = result

    missing = [board_id for board_id in selected if board_id not in found]
    if missing and not problems:
        problems.append(f"Board reviews are missing for {', '.join(missing)}.")
    if len(problems) == 1:
        raise ValueError(problems[0])
    if problems:
        raise ValueError(f"The review has {len(problems)} problems:\n- " + "\n- ".join(problems))
    validated = {
        "consultation_id": consultation["id"],
        "summary": summary,
        "boards": [found[board_id] for board_id in selected],
    }
    if execution != "unspecified":
        validated["execution"] = execution
    if isinstance(review.get("kept"), list):
        validated["kept"] = [board_id for board_id in selected if board_id in review["kept"]]
    warnings = review_warnings(validated["boards"])
    if warnings:
        validated["warnings"] = warnings
    return validated


def _same_text(value: str, board_id: str = "") -> str:
    """A text compared across boards: the board's own name taken out, case, punctuation and spacing folded, so
    "legal: proceed" and "security: proceed" read as the same advice."""
    if board_id:
        for name in {board_id, board_id.replace("-", " ")}:
            value = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", " ", value, flags=re.IGNORECASE)
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())


def _shown(items: list[str]) -> str:
    return ", ".join(items[:6]) + (f" and {len(items) - 6} more" if len(items) > 6 else "")


def _single_evidence(entry: dict) -> int | None:
    """The number of the one evidence item every finding of a board cites, when all of them cite that one alone.

    The number, not the reference: a reference no tool or file confirms is never echoed (tools.tool_evidence_warnings).
    """
    lenses = entry.get("challenge", {}).get("specialists", [])
    cited = {tuple(lens["evidence_refs"]) for lens in lenses}
    if len(lenses) < 2 or len(cited) != 1 or len(next(iter(cited))) != 1:
        return None
    return next(iter(cited))[0]


def review_warnings(boards: list[dict], focus: str | None = None) -> list[str]:
    """Signs that the boards did not review the task independently. Computed, never taken from the review.

    Advice is compared with each board's own name taken out, so a text copied from board to board with the name
    swapped is found; a board whose every finding rests on one and the same evidence item is named too. With focus,
    only the signs that concern that board are given: task submit says what the pass it records adds, once.
    """
    warnings = []

    def concerns(names: list[str]) -> bool:
        """A board, or a board/lens, list that names the focused board, or any list without a focus."""
        return focus is None or any(name.split("/")[0] == focus for name in names)

    recommendations = {}
    for entry in boards:
        recommendations.setdefault(_same_text(entry["recommendation"], entry["id"]), []).append(entry["id"])
    for board_ids in recommendations.values():
        if len(board_ids) > 1 and concerns(board_ids):
            warnings.append(f"Boards {_shown(board_ids)} give the same recommendation word for word, once each "
                            "board's name is taken out.")
    findings, originals = {}, {}
    for entry in boards:
        for lens in entry.get("challenge", {}).get("specialists", []):
            text = _same_text(lens["finding"], entry["id"])
            findings.setdefault(text, []).append(f"{entry['id']}/{lens['id']}")
            originals.setdefault(text, lens["finding"])
    for text, lenses in findings.items():
        if len(lenses) > 1 and concerns(lenses):
            warnings.append(f"The same finding appears in {_shown(lenses)}, once each board's name is taken out: "
                            f"{' '.join(originals[text].split())[:120]}")
    singles = [(entry["id"], _single_evidence(entry)) for entry in boards if concerns([entry["id"]])]
    singles = [f"{board_id} (its evidence #{index})" for board_id, index in singles if index is not None]
    if singles:
        warnings.append(f"Every finding of a board cites one and the same evidence item: {_shown(singles)}.")
    unobserved = [
        entry["id"] for entry in boards
        if concerns([entry["id"]]) and entry.get("challenge", {}).get("specialists")
        and all(lens["basis"] != "observed" for lens in entry["challenge"]["specialists"])
    ]
    if unobserved:
        warnings.append(f"No observed finding from {', '.join(unobserved)}: every lens is an assumption or missing.")
    return warnings
