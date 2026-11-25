"""Check what the boards return and carry the task to the person's decision: the review entries and their evidence,
the deliberation between boards, the decision brief, the blockers and the implementation handoff.

The questionnaire (questionnaire.py), the routing (routing.py) and the consultation (consultation.py) come first.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import clock
from .consultation import (
    CHOICES, EVIDENCE_SOURCES, answer_lines, json_section, market_references, one_based, scope_lines,
    storybook_references, tool_references,
)
from .routing import normalize_text, trigger_matches
from .sensitive import credential_problems, public_evidence_url, redact_credentials


class TaskStateError(ValueError):
    """An action refused because of the task's status. The message says what is refused; the command line adds the
    status and the next command that runs in it (tasks.state_refusal)."""


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain text.")
    return value.strip()


def _text_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings.")
    return [_text(item, field) for item in value]


DATED_SOURCES = ("public", "measurement", "interview")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_REVISION = re.compile(r"[0-9a-f]{7,64}")


_LOCATION = re.compile(r"(?:::.*|#.*|:\d+(?:-\d+)?)$")


def _evidence_day(value: object, field: str) -> str:
    """A real YYYY-MM-DD date that is not in the future on the real clock (one day of margin for time zones)."""
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError(f"{field}: got {_received(value)}; write the date YYYY-MM-DD.")
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
        found.append(f"{field}.source: got {_received(source)}; accepted: {', '.join(EVIDENCE_SOURCES)}.")
        source = None
    result = {"source": source, "ref": _checked(found, _text, item["ref"], f"{field}.ref"),
              "supports": _checked(found, _text, item["supports"], f"{field}.supports")}
    if source == "tool" and result["ref"] is not None:
        result["ref"] = _tool_reference(result["ref"], tool_ids)
    ref = result["ref"]
    if ref is not None:
        _checked(found, _check_reference, ref, source, f"{field}.ref", market_refs, storybook_refs, tool_ids, root)
    if "date" in item:
        result["date"] = _checked(found, _evidence_day, item["date"], f"{field}.date")
    if "revision" in item:
        if not isinstance(item["revision"], str) or not _REVISION.fullmatch(item["revision"]):
            found.append(f"{field}.revision: got {_received(item['revision'])}; write a commit SHA.")
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


def mock_evidence(task: dict) -> list[str]:
    """Review evidence cited from a mock tool ("finance #1 stripe:in_test_001"): synthetic data, never the real system."""
    scope = task.get("consultation", {}).get("scope", {})
    mocks = {item["id"] for item in scope.get("tools", []) if item.get("mode") == "mock"}
    return [
        f"{entry['id']} #{index} {item['ref']}"
        for entry in task.get("review", {}).get("boards", [])
        for index, item in enumerate(entry.get("evidence", []), start=1)
        if isinstance(item, dict) and item.get("source") == "tool" and item["ref"].partition(":")[0] in mocks
    ]


def _received(value: object) -> str:
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
    problems.append(f"{path}: got {_received(value)}; accepted: {', '.join(CHOICES[field])}.")
    return None


def _keys(value: object, expected: set, optional: set, path: str, problems: list[str]) -> bool:
    """An object with the expected keys; missing and unknown keys are both reported."""
    if not isinstance(value, dict):
        problems.append(f"{path}: got {_received(value)}; expected an object with {', '.join(sorted(expected))}.")
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
        problems.append(f"{path}: got {_received(item)}; each blocker is an object with finding, owner and "
                        "clears_when, as in blocker_item.")
        return None
    _keys(item, {"finding", "owner", "clears_when"}, {"phase"}, path, problems)
    blocker = {key: _checked(problems, _text, item.get(key, _ABSENT), f"{path}.{key}")
               for key in ("finding", "owner", "clears_when")}
    if "phase" in item:
        blocker["phase"] = _choice(item["phase"], "phase", f"{path}.phase", problems)
    return blocker


def _evidence_refs(references: object, count: int, path: str, problems: list[str]) -> list[int]:
    """Positions in the entry's own evidence list, counted from one."""
    if not isinstance(references, list):
        problems.append(f"{path}: got {_received(references)}; write a list of positions such as [1, 3].")
        return []
    wrong = [index for index in references if type(index) is not int or not 1 <= index <= count]
    if wrong:
        valid = f"1 to {count}" if count else "none: the entry's evidence list is empty, add the evidence first"
        problems.append(
            f"{path}: {_received(wrong)} must point to the board's evidence list: evidence_refs are positions in "
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
        problems.append(f"{path}.specialists: got {_received(specialists)}; expected a list of lens findings.")
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
            problems.append(f"{lens_path}.id: unexpected or repeated {board_id} specialist {_received(specialist_id)}; "
                            f"expected each of {', '.join(expected)} once.")
            continue
        lens_path = f"{board_id}/{specialist_id}"
        basis = _choice(specialist["basis"], "basis", f"{lens_path} basis", problems)
        references = _evidence_refs(specialist["evidence_refs"], len(evidence), f"{lens_path} evidence_refs", problems)
        if basis == "observed" and not references:
            problems.append(f"{lens_path} needs an evidence reference for an observed finding.")
        findings[specialist_id] = {
            "id": specialist_id, "finding": _checked(problems, _text, specialist["finding"], f"{lens_path} finding"),
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
        problems.append(f"{path}.blockers: got {_received(blockers)}; expected a list, empty unless the board blocks.")
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
        **{field: _checked(problems, _text, challenge[field], f"{path}.{field}")
           for field in ("alternative", "failure_mode", "verification")},
        "blockers": blockers,
    }


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
        raise ValueError(f"id: got {_received(board_id)}; write the board's ID, one of {', '.join(selected)}.")
    board_id = board_id.strip()
    if board_id not in selected:
        raise ValueError(f"id: board {board_id!r} was not selected for this consultation. Selected: {', '.join(selected)}.")
    templates = {item["id"]: item for item in consultation.get("review_template", {}).get("boards", [])}
    template = templates.get(board_id, {})
    fields = {"id", "recommendation", "evidence", "open_questions"} | ({"challenge", "reviewer"} & template.keys())
    problems = []
    _keys(entry, fields, set(), board_id, problems)
    credentials = []
    if root is not None:
        credentials = [one_based(problem) for problem in
                       credential_problems({key: entry[key] for key in fields - {"id"} if key in entry}, board_id)]
    entry = {key: entry.get(key, _ABSENT) for key in fields}
    scope = consultation.get("scope", {})
    structured = consultation.get("evidence_format") == "structured"
    evidence = [] if entry["evidence"] is _ABSENT else entry["evidence"]
    if not isinstance(evidence, list):
        problems.append(f"{board_id}.evidence: got {_received(evidence)}; expected a list of evidence items.")
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
        "recommendation": _checked(problems, _text, entry["recommendation"], f"{board_id}.recommendation"),
        "evidence": checked,
        "open_questions": _checked(problems, _text_list, entry["open_questions"], f"{board_id}.open_questions"),
    }
    if "reviewer" in template:
        result["reviewer"] = _checked(problems, _text, entry["reviewer"], f"{board_id}.reviewer")
    if "challenge" in template and entry["challenge"] is not _ABSENT:
        stored = consultation.get("board_briefs", {}).get(board_id, {})
        listed = stored.get("lenses_not_concerned") if isinstance(stored, dict) else None
        not_concerned = {lens["id"] for lens in listed if isinstance(lens, dict) and isinstance(lens.get("id"), str)} \
            if isinstance(listed, list) else set()
        result["challenge"] = _validate_challenge(
            board_id, entry["challenge"], template["challenge"], [item or {} for item in checked], structured, problems,
            not_concerned,
        )
    # A field another check already refuses is reported once, by that check.
    reported = {problem.split(": ", 1)[0] for problem in problems}
    problems.extend(problem for problem in credentials if problem.split(": ", 1)[0] not in reported)
    if problems:
        raise EntryProblems(board_id, problems)
    return result


def validate_review(consultation: dict, review: dict, root: Path | None = None) -> dict:
    """Require a recommendation for every board in the recorded consultation; report every board's problems at once."""
    # kept: the passes a reopened approval kept (tasks.kept_passes); only task review --summary records it.
    allowed = {"consultation_id", "summary", "boards", "execution", "warnings", "evidence_item", "blocker_item", "kept"}
    if not isinstance(review, dict) or not {"consultation_id", "summary", "boards"} <= review.keys() \
            or not review.keys() <= allowed:
        raise ValueError("A review must contain consultation_id, summary and boards. Run task template.")
    execution = review.get("execution", "unspecified")
    if execution not in EXECUTION_MODES:
        raise ValueError(f"Review execution must be one of {', '.join(EXECUTION_MODES)}.")
    if review["consultation_id"] != consultation["id"]:
        raise ValueError("This review belongs to another consultation. Run task template again.")
    summary = _text(review["summary"], "Review summary")
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


OBJECTING_VERDICTS = ("revise", "block", "insufficient-evidence")
POSITIONS = ("maintain", "concede", "amend")


# Which verdicts each objecting verdict challenges: every objection challenges a board that would proceed,
# and a board that blocks also challenges a board that only asks to revise, on the point of its blockers.
CHALLENGED = {"revise": ("proceed",), "insufficient-evidence": ("proceed",), "block": ("proceed", "revise")}
# Why two different verdicts meet in no objection, for the decision brief.
UNCONFRONTED = {
    frozenset({"revise", "insufficient-evidence"}): "both hold the work back and neither has a position to defend "
                                                    "against the other",
    frozenset({"block", "insufficient-evidence"}): "a board without enough evidence has no position to defend "
                                                   "against a blocker",
}


def _domain_words(domains: dict | None, board_id: str, text: str) -> list[str]:
    """The words of a board's domain (its title and routing triggers) that a text uses. Every board's words
    compete for the text, so that "contract test" belongs to QA and does not reach Legal through "contract"."""
    domains = {key: value for key, value in (domains or {}).items() if value}
    domains.setdefault(board_id, [board_id])
    found = trigger_matches({key: {"triggers": value} for key, value in domains.items()}, text)
    return found.get(board_id, [])


def _meets(words: list[str], domains: dict | None) -> bool:
    """Domains meet on two distinct words, on a phrase of several words, or on a word that only one board's
    domain holds: a single word shared by several domains says too little about the subject of a point."""
    words = list(dict.fromkeys(normalize_text(word) for word in words))
    if len(words) > 1 or any(" " in word for word in words):
        return True
    owners = [board for board, domain in (domains or {}).items()
              if any(normalize_text(item) == word for item in domain for word in words)]
    return len(owners) == 1


def _position_text(entry: dict) -> str:
    return f"{entry['recommendation']} {entry['challenge'].get('verification', '')}"


def objections(review: dict, domains: dict | None = None) -> list[dict]:
    """An objecting board's point (its blockers, or else its failure mode) goes to a board whose position it
    contradicts: one that would proceed, or that only asks to revise when the objector blocks, and whose domain
    the point meets. The domains meet when the point uses the other board's words, or the other board's
    recommendation uses the objector's. A point that meets no board stands as its board's own advice."""
    entries = [entry for entry in review["boards"] if "challenge" in entry]
    result = []
    for objector in entries:
        challenge = objector["challenge"]
        if challenge["verdict"] not in OBJECTING_VERDICTS:
            continue
        findings = [item["finding"] if isinstance(item, dict) else item for item in challenge["blockers"]]
        point = "; ".join(findings) or challenge["failure_mode"]
        for responder in entries:
            verdict = responder["challenge"]["verdict"]
            if verdict not in CHALLENGED[challenge["verdict"]]:
                continue
            meets = _domain_words(domains, responder["id"], point) + [
                word for word in _domain_words(domains, objector["id"], _position_text(responder))
            ]
            if not _meets(meets, domains):
                continue
            result.append({
                "id": f"{objector['id']}-to-{responder['id']}",
                "from": objector["id"],
                "to": responder["id"],
                "point": point,
                "meets": list(dict.fromkeys(meets)),
                "from_position": f"{challenge['verdict']}: {objector['recommendation']}",
                "to_position": f"{verdict}: {responder['recommendation']}",
            })
    return result


def unconfronted_verdicts(review: dict, domains: dict | None = None) -> list[str]:
    """Different verdicts that no objection confronts, each with the reason."""
    boards = {}
    for entry in review["boards"]:
        if "challenge" in entry:
            boards.setdefault(entry["challenge"]["verdict"], []).append(entry["id"])
    lines = []
    for pair, reason in UNCONFRONTED.items():
        first, second = sorted(pair, key=("revise", "block", "insufficient-evidence").index)
        if first in boards and second in boards:
            lines.append(
                f"Verdicts differ without a confrontation: {first} ({', '.join(boards[first])}) and {second} "
                f"({', '.join(boards[second])}). No objection asks them to answer each other, because {reason}."
            )
    raised = {item["from"] for item in objections(review, domains)}
    challenged = {verdict for objector in OBJECTING_VERDICTS for verdict in CHALLENGED[objector]}
    if any(verdict in boards for verdict in challenged):
        alone = [board for verdict in OBJECTING_VERDICTS for board in boards.get(verdict, []) if board not in raised]
        if alone:
            lines.append(
                f"Advice addressed to no other board: {', '.join(alone)}. Their point meets the domain of no board "
                "whose position it contradicts, so no board answers it; it stands as their advice in this brief."
            )
    return lines


RESOLUTION_RULE = (
    "An objection is resolved when one of the two boards concedes, or when both amend their position. Otherwise "
    "it stays open and the person approving decides it. A concession closes it alone: the other board need not "
    "answer it."
)
DELIBERATION_RULES = {
    "positions": {
        "maintain": "the board keeps its position; cite its evidence",
        "amend": "the board changes its position to meet the other's point; say how, and cite its evidence",
        "concede": "the board accepts the other's point; no evidence needed",
    },
    "evidence_refs": "positions in the board's own evidence list from its review entry, counted from 1",
    "objections": "the objection IDs this response answers: one response can answer several objections",
    "one_response": "a board that raised and received objections has two responses in the template; merge them "
                    "into one when it takes the same position on all, or split any response to take different "
                    "positions",
    "decision_needed": "required when an objection stays open: the decision the person approving must take",
    "resolution": RESOLUTION_RULE,
}


def _resolved(positions: set[str]) -> bool:
    return "concede" in positions or positions == {"amend"}


def deliberation_request(task: dict) -> dict:
    """What each board must answer, on the same point, before the person decides: one response per board and
    side, covering every objection it raised or received."""
    if task.get("status") != "reviewed":
        raise TaskStateError("Deliberate after the review is recorded and before the decision.")
    review = validate_review(task["consultation"], task["review"])
    items = objections(review, task["consultation"].get("domains"))
    groups = {}
    for item in items:
        groups.setdefault((item["from"], "from"), []).append(item["id"])
        groups.setdefault((item["to"], "to"), []).append(item["id"])
    template = {
        "consultation_id": review["consultation_id"],
        "responses": [
            {"objections": ids, "board": board, "position": "", "response": "", "evidence_refs": []}
            for (board, _), ids in groups.items()
        ],
        "decision_needed": "",
    }
    request = {"objections": items, "rules": DELIBERATION_RULES, "template": template}
    if template["responses"]:
        first = template["responses"][0]
        request["example"] = {**first, "position": "amend",
                              "response": "We add the access test the other board asks for before release.",
                              "evidence_refs": [1]}
    return request


def _response_problems(response: object, items: dict, evidence: dict) -> tuple[list[tuple], list[str]]:
    """The (objection, board) pairs a response answers, and its problems."""
    if not isinstance(response, dict):
        return [], [f"got {_received(response)}; each response is an object as in the template of task deliberate."]
    keys = {"board", "position", "response", "evidence_refs"}
    target = "objections" if "objections" in response else "objection"
    if response.keys() != keys | {target}:
        return [], [f"needs objections, board, position, response and evidence_refs; got {', '.join(sorted(response))}."]
    ids = response[target] if target == "objections" else [response[target]]
    board = response["board"]
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids) or not isinstance(board, str):
        return [], ["objections is a list of objection IDs and board is text, as in the template of task deliberate."]
    problems = [f"{item_id}/{board}: unknown objection or board in response." for item_id in ids
                if item_id not in items or board not in (items[item_id]["from"], items[item_id]["to"])]
    if not isinstance(response["position"], str) or response["position"] not in POSITIONS:
        problems.append(f"{board}: position got {_received(response['position'])}; accepted: {', '.join(POSITIONS)}.")
    count = len(evidence.get(board, []))
    _evidence_refs(response["evidence_refs"], count, f"{board} evidence_refs", problems)
    if response["position"] in ("maintain", "amend") and not response["evidence_refs"]:
        problems.append(f"{board} must cite its evidence to maintain or amend a position.")
    if not isinstance(response["response"], str) or not response["response"].strip():
        problems.append(f"{board}: response must contain text.")
    return [(item_id, board) for item_id in ids], problems


def nothing_to_deliberate(task_id: str) -> str:
    """What task deliberate and task respond say when no board objects to another: respond has nothing to record."""
    return ("The boards do not disagree on this task: there is nothing to deliberate, so skip task respond. Next: "
            f"openguildkit task challenge {task_id} prints the decision brief.")


def validate_deliberation(task: dict, payload: dict) -> dict:
    """Both boards answer each objection with a position and evidence from their first review."""
    request = deliberation_request(task)
    items = {item["id"]: item for item in request["objections"]}
    if not items:
        raise ValueError(nothing_to_deliberate(task["id"]))
    if not isinstance(payload, dict) or payload.keys() != {"consultation_id", "responses", "decision_needed"}:
        raise ValueError("A deliberation contains consultation_id, responses and decision_needed. Run task deliberate.")
    if payload["consultation_id"] != task["consultation"]["id"]:
        raise ValueError("This deliberation belongs to another consultation.")
    if not isinstance(payload["responses"], list):
        raise ValueError("responses must be a list.")
    evidence = {entry["id"]: entry["evidence"] for entry in task["review"]["boards"]}
    responses, problems = {}, []
    for position, response in enumerate(payload["responses"]):
        pairs, found = _response_problems(response, items, evidence)
        problems.extend(f"responses[{position}]: {problem}" for problem in found)
        for key in pairs:
            if key in responses:
                problems.append(f"responses[{position}]: repeated response for {key[0]} by {key[1]}.")
            elif not found:
                responses[key] = {"objection": key[0], "board": key[1], "position": response["position"],
                                  "response": response["response"].strip(), "evidence_refs": response["evidence_refs"]}
    conceded = {item_id for (item_id, _), response in responses.items() if response["position"] == "concede"}
    missing = [f"{item_id} by {board}" for item_id, item in items.items() for board in (item["from"], item["to"])
               if (item_id, board) not in responses and item_id not in conceded]
    if missing and not problems:
        problems.append(f"Responses are missing: {', '.join(missing)}.")
    if problems:
        raise ValueError(f"The deliberation has {len(problems)} problem{'s' if len(problems) > 1 else ''}:\n- "
                         + "\n- ".join(problems))
    agreed, open_items = [], []
    for item_id, item in items.items():
        positions = {responses[(item_id, board)]["position"] for board in (item["from"], item["to"])
                     if (item_id, board) in responses}
        (agreed if _resolved(positions) else open_items).append(item_id)
    decision = payload["decision_needed"].strip() if isinstance(payload["decision_needed"], str) else ""
    if open_items and not decision:
        raise ValueError(f"Some disagreements remain ({', '.join(open_items)}): say in decision_needed which "
                         f"decision the responsible person must take. {RESOLUTION_RULE}")
    return {
        "consultation_id": payload["consultation_id"],
        "objections": list(items.values()),
        "responses": [responses[(item_id, board)] for item_id, item in items.items() for board in (item["from"], item["to"])
                      if (item_id, board) in responses],
        "agreed": agreed,
        "open": open_items,
        "decision_needed": decision,
    }


def pending_removals(task: dict) -> list[str]:
    """Boards routed for sensitive data that the agent removed and the person has not confirmed yet."""
    return [
        item["board"] for item in task.get("consultation", {}).get("adjustments", [])
        if item.get("confirmation") == "pending"
    ]


def _satisfied(deliberation: dict | None) -> set[str]:
    """Objecting boards whose every objection was resolved in deliberation: their advice is taken into account."""
    if not deliberation:
        return set()
    raised = {}
    for item in deliberation["objections"]:
        raised.setdefault(item["from"], []).append(item["id"])
    return {board for board, ids in raised.items() if all(item_id in deliberation["agreed"] for item_id in ids)}


def verdict_lines(review: dict, deliberation: dict | None = None, decision_task: bool = False) -> list[str]:
    """The count of verdicts, and a warning when boards still object after the deliberation."""
    entries = [entry for entry in review["boards"] if "challenge" in entry]
    if not entries:
        return ["Verdicts: none recorded."]
    counts = {}
    for entry in entries:
        counts.setdefault(entry["challenge"]["verdict"], []).append(entry["id"])
    lines = ["Verdicts: " + ", ".join(f"{len(boards)} {verdict}" for verdict, boards in counts.items()) + "."]
    satisfied = _satisfied(deliberation)
    objecting = [board for verdict in OBJECTING_VERDICTS for board in counts.get(verdict, []) if board not in satisfied]
    if satisfied:
        lines.append(f"Objections of {', '.join(sorted(satisfied))} were all resolved in deliberation.")
    if objecting:
        consequence = ("The decision record carries their reservations." if decision_task
                       else "Approving goes against their advice.")
        lines.append(
            f"Warning: {len(objecting)} of {len(entries)} boards {'says' if len(objecting) == 1 else 'say'} revise, "
            f"block or insufficient-evidence "
            f"({', '.join(objecting)}). {consequence}"
        )
    return lines


def _board_change_lines(task: dict) -> list[str]:
    confirmed = task.get("decision", {}).get("confirmed_removals", [])
    lines = []
    for item in task["consultation"].get("adjustments", []):
        if item["action"] == "add":
            lines.append(f"Board added: {item['board']}. Reason: {item['reason']}; requested by the agent at consultation.")
            continue
        line = f"Board removed: {item['board']}"
        if item.get("routed_for"):
            line += f", routed for {item['routed_for']!r}"
        line += f". Reason: {item['reason']}; requested by the agent at consultation"
        if item["board"] in confirmed:
            line += f"; removal confirmed by {task['decision']['by']} at approval."
        elif item.get("confirmation") == "pending":
            line += "; the person approving must confirm it by typing the board's name."
        else:
            line += "."
        lines.append(line)
    return lines


def _blocker_lines(task: dict) -> list[str]:
    lines = []
    for item in blocker_list(task):
        resolution = item["resolution"]
        if not resolution and item.get("phase") == "verification":
            lines.append(f"Condition of approval {item['id']}, cleared after implementation and before the task "
                         f"completes: {item['finding']} Clears when: {item['clears_when']}")
            continue
        if not resolution:
            lines.append(f"Blocker {item['id']} open: {item['finding']}")
            continue
        line = f"Blocker {item['id']} {resolution['kind']} by {resolution['by']}"
        if resolution.get("recorded_from") == "no terminal":
            line += " (recorded without a terminal)"
        line += f": {item['finding']}"
        if resolution["kind"] == "cleared":
            line += f" Evidence: {resolution['evidence']}. Supports: {resolution['supports']}"
        else:
            line += f" Reason: {resolution['reason']}. Scope: {resolution['scope']}. Until: {resolution['until']}"
        lines.append(line)
    return lines


def decision_summary(task: dict) -> list[str]:
    """What the person approving must see before deciding, as plain lines. Each objection appears once."""
    review = validate_review(task["consultation"], task["review"])
    domains = task["consultation"].get("domains")
    deliberation = task.get("deliberation")
    lines = verdict_lines(review, deliberation, is_decision_task(task)) + unconfronted_verdicts(review, domains)
    if review.get("kept"):
        lines.append(f"Passes kept from the approved round, their board, rules and questions unchanged: "
                     f"{', '.join(review['kept'])}.")
    lines += [f"Review warning: {warning}" for warning in review.get("warnings", [])]
    synthetic = mock_evidence(task)
    if synthetic:
        lines.append(f"Mock data: {len(synthetic)} evidence item(s) come from mock tools, synthetic sample data and not "
                     f"the real systems: {', '.join(synthetic)}.")
    lines += _board_change_lines(task)
    lines += [f"Open point: {point}" for point in task["consultation"]["scope"].get("open_points", [])]
    if deliberation:
        lines.append(f"Deliberation: {len(deliberation['agreed'])} resolved, {len(deliberation['open'])} open. "
                     f"{RESOLUTION_RULE}")
        points = {item["id"]: item["point"] for item in deliberation["objections"]}
        lines += [f"Resolved: {item_id}: {points[item_id]}" for item_id in deliberation["agreed"]]
        lines += [f"Disagreement left open: {item_id}: {points[item_id]}" for item_id in deliberation["open"]]
        if deliberation["open"]:
            lines.append(f"Decision needed: {deliberation['decision_needed']}")
    else:
        pending = objections(review, domains)
        if pending:
            lines.append(f"{len(pending)} objection{'' if len(pending) == 1 else 's'} not deliberated yet: approving "
                         f"is still possible, and you then "
                         f"decide them yourself; task deliberate has the boards answer first. {RESOLUTION_RULE}")
        lines += [f"Objection not deliberated: {item['id']}: {item['point']}" for item in pending]
    lines += _blocker_lines(task)
    return lines


def challenge_report(task: dict, lines: list[str] | None = None) -> str:
    """The decision brief: the lines the person reads before deciding (tasks.decision_text, the same as the
    approval prompt), then each board's challenge as JSON."""
    if "review" not in task:
        raise TaskStateError("Record the board reviews before opening the decision brief.")
    review = validate_review(task["consultation"], task["review"])
    findings = []
    verdicts = {}
    for entry in review["boards"]:
        challenge = entry.get("challenge", {})
        finding = {"board": entry["id"], "recommendation": entry["recommendation"]}
        for field in ("verdict", "confidence", "alternative", "failure_mode", "verification", "blockers"):
            if field in challenge:
                finding[field] = challenge[field]
        cited = sorted({
            index for lens in challenge.get("specialists", []) if lens["basis"] == "observed" for index in lens["evidence_refs"]
        })
        if cited:
            finding["decisive_evidence"] = [entry["evidence"][index - 1] for index in cited]
        finding["open_questions"] = entry["open_questions"]
        if "verdict" in challenge:
            verdicts.setdefault(challenge["verdict"], []).append(entry["id"])
        findings.append(finding)
    report = {"summary": review["summary"], "verdicts": verdicts, "findings": findings}
    if review.get("warnings"):
        report["review_warnings"] = review["warnings"]
    if task["consultation"].get("adjustments"):
        report["board_changes"] = task["consultation"]["adjustments"]
    points = task["consultation"]["scope"].get("open_points")
    if points:
        report["open_points"] = points
    deliberation = task.get("deliberation")
    if deliberation:
        # Each objection once, with its status and both boards' answers; the lines above only name it.
        report["deliberation"] = {
            "rule": RESOLUTION_RULE,
            "objections": [
                {**item, "status": "resolved" if item["id"] in deliberation["agreed"] else "open",
                 "responses": [r for r in deliberation["responses"] if r["objection"] == item["id"]]}
                for item in deliberation["objections"]
            ],
            "decision_needed": deliberation["decision_needed"],
        }
    else:
        pending = objections(review, task["consultation"].get("domains"))
        if pending:
            report["objections_not_deliberated"] = [item["id"] for item in pending]
    resolved = [item for item in blocker_list(task) if item["resolution"]]
    if resolved:
        report["resolved_blockers"] = resolved
    summary = "\n".join(f"- {line}" for line in (decision_summary(task) if lines is None else lines))
    return "# Decision brief\n\n" + summary + "\n\n" + json_section(report) + "\n"


def is_decision_task(task: dict) -> bool:
    """A decision task asks for a recommendation, not for a change to the project."""
    return task.get("answers", {}).get("kind") == "decision"


# Clearances and waivers are stored apart by phase, because the approval's seal covers only those given before it.
# blocker_resolutions(task) reads both: every reader goes through it.
RESOLUTION_FIELDS = ("blocker_resolutions", "verification_blocker_resolutions")


def resolution_field(phase: str | None) -> str:
    """Where a clearance or waiver of a blocker of this phase is stored."""
    return RESOLUTION_FIELDS[1] if phase == "verification" else RESOLUTION_FIELDS[0]


def blocker_resolutions(task: dict) -> dict:
    """Every clearance and waiver of the task's blockers, both phases, by blocker ID: the one way to read them."""
    resolutions = {}
    for field in RESOLUTION_FIELDS:
        resolutions.update(task.get(field, {}))
    return resolutions


def blocker_list(task: dict) -> list[dict]:
    """Every blocker of the recorded review, with how it was resolved so far."""
    if "review" not in task:
        return []
    resolutions = blocker_resolutions(task)
    items = []
    for entry in task["review"]["boards"]:
        for index, blocker in enumerate(entry.get("challenge", {}).get("blockers", []), start=1):
            key = f"{entry['id']}:{index}"
            details = blocker if isinstance(blocker, dict) else {"finding": blocker}
            items.append({"id": key, "board": entry["id"], **details, "resolution": resolutions.get(key)})
    return items


_SHARED_RESOLUTION = ("kind", "by", "at", "recorded_from", "evidence", "supports", "reason", "scope", "until", "signer")


def exported_blockers(task: dict) -> list[dict]:
    """Each blocker as a shared decision record shows it: its board, phase, finding and condition, and who cleared or
    waived it, with the evidence and what it establishes, or the waiver's reason, scope and end date."""
    shown = []
    for item in blocker_list(task):
        entry = {"id": item["id"], "board": item["board"], "phase": item.get("phase", "approval"),
                 **{key: item[key] for key in ("finding", "owner", "clears_when") if key in item}}
        entry["resolution"] = ({key: item["resolution"][key] for key in _SHARED_RESOLUTION if key in item["resolution"]}
                               if item["resolution"] else None)
        shown.append(entry)
    return shown


def _evidence_section(evidence: list[dict]) -> list[str]:
    """The named evidence the closing will ask for, and who provides each: never the agent."""
    if not evidence:
        return []
    lines = ["## Evidence the closing will ask for", "",
             "These documents belong to the people named here. Ask them for each one (a project path or an https "
             "link) early; do not write them yourself to satisfy the check.", ""]
    for check in evidence:
        need = (f"required because {check['must_supply']}" if check["must_supply"]
                else "may be declared not applicable with a reason and an owner")
        lines.append(f"- `{check['id']}`: {check['title']}, provided by {check['owner_role']} ({need}).")
    return [*lines, ""]


def _checks_section(task: dict) -> list[str]:
    """The check commands task verify will run, and what they need, so nothing surprises the agent at the end."""
    if is_decision_task(task):
        return []
    commands = task["consultation"]["scope"].get("checks", [])
    if not commands:
        return ["## Checks task verify will run", "",
                "None: the profile lists no check command, so no test runs before the task closes. The person can "
                "add one for the next tasks: openguildkit profile add check \"COMMAND\" --by NAME --reason WHY.", ""]
    if task.get("status") in ("done", "done-with-reservations"):
        lines = ["## Checks task verify ran", "",
                 "Each one had to pass, or be recorded by a person as unable to run here, before the task was closed. "
                 "Their outcomes are in task show (result.checks).", ""]
    else:
        lines = ["## Checks task verify will run", "",
                 "Each one must pass before the task is done. Install the project's dependencies and the tools these "
                 "commands call first: a command that cannot run fails with its cause and its log. When one cannot "
                 f"run in this environment, the person records it with `openguildkit task verify {task['id']} "
                 "--cannot-run command:N --by NAME --reason TEXT`, and the task closes with that reservation.", ""]
    lines += [f"- `command:{index}`: `{command}`" for index, command in enumerate(commands, start=1)]
    return [*lines, ""]


def _rules_section(task: dict, checks: list[dict] | None) -> list[str]:
    """The rules task checks asks, pack by pack, then one line for the packs and rules it does not ask. checks
    are those of results.expected_checks; without them every rule is listed. A decision task asks none."""
    if is_decision_task(task):
        return []
    task_id = task["id"]
    judged = {check["id"][len("rule:"):]: check for check in checks or [] if check["kind"] in ("rule", "machine")}
    asked, skipped = [], {}
    for pack in task["consultation"]["scope"].get("packs", []):
        ids = [rule["id"] for rule in pack.get("rules", [])
               if judged.get(f"{pack['id']}/{rule['id']}", {"concerned": True})["concerned"]]
        if ids:
            asked.append(f"- {pack['id']}@{pack.get('version', '')}: {', '.join(ids)}")
        if len(ids) < len(pack.get("rules", [])):
            skipped[pack["id"]] = (len(pack["rules"]) - len(ids), len(pack["rules"]))
    lines = ["## Rules to apply and their checks", "",
             "The rule texts are in the project's agent instructions (AGENTS.md); the whole scope with every rule "
             f"text: openguildkit task brief {task_id} --scope. What to report for each rule: openguildkit task "
             f"checks {task_id}.", "", *(asked or ["No rule of the packs in force concerns this task."])]
    if skipped:
        counts = ", ".join(f"{pack} ({count} of {total} rules)" if count < total else f"{pack} ({total} rules)"
                           for pack, (count, total) in skipped.items())
        lines.append(f"Not concerned by this task, so not asked (each reason: openguildkit task checks {task_id}): "
                     f"{counts}.")
    return [*lines, ""]


def handoff(task: dict, evidence: list[dict] | None = None, checks: list[dict] | None = None) -> str:
    """Render the authorized scope, decision and advisory findings, with the named evidence first.

    checks are the expected checks of the approved task (results.expected_checks): the rules to apply are those
    they ask."""
    status = task.get("status")
    if status == "changes-requested":
        raise ValueError(f"Task {task['id']} has changes requested by {task['decision']['by']}: there is nothing to "
                         f"implement. Next: openguildkit task consult {task['id']} --reuse-answers")
    if status not in ("approved", "done", "done-with-reservations"):
        raise TaskStateError("A human approval is required before implementation.")
    pending_verification = [item for item in blocker_list(task) if item.get("phase") == "verification"
                            and not item["resolution"]]
    consultation = task["consultation"]
    review = validate_review(consultation, task["review"])
    decision = task["decision"]
    approval = {
        "by": _text(decision.get("by"), "Approver"),
        "reason": _text(decision.get("reason"), "Approval reason"),
    }
    if is_decision_task(task):
        heading = "# Approved decision record"
        instruction = (
            "Report this decision and its review to the user. Leave the project files "
            f"unchanged. Close the task with `openguildkit task complete {task['id']}`, then export its record with "
            f"`openguildkit task export {task['id']}`. To act on the decision, open a follow-up task with "
            f"`openguildkit task new \"BRIEF\" --follows {task['id']}`, which records the link and carries this "
            "decision into its consultation, and get that task's scope approved before implementing it."
        )
    else:
        heading = "# Approved task handoff"
        instruction = (
            "Implement the approved scope. Apply the recorded rules and conventions, "
            "run the relevant project checks and report the results. Bring scope "
            "changes and unresolved decisions back to the user."
        )
    if status != "approved":
        heading += f" (task {status})"
        instruction = (
            f"Task {task['id']} is {status}: nothing is left to implement. This handoff is shown for reference. To "
            f"change the work, open a follow-up with `openguildkit task new \"BRIEF\" --follows {task['id']}`."
        )
    task_id = task["id"]
    return "\n".join(
        [
            heading,
            "",
            instruction,
            "",
            *(
                ["## Conditions of the approval, to meet before the task completes", "",
                 "The person approved with these blockers open: only the finished work can clear them. Build the "
                 "evidence each one names, show it to the person, and let them clear it in their terminal with "
                 f"openguildkit task clear {task['id']} BLOCKER --evidence PATH --supports TEXT --by NAME. "
                 "task complete refuses the task while one is open.", "",
                 *(f"- {item['id']} ({item['owner']}): {item['finding']} Clears when: {item['clears_when']}"
                   for item in pending_verification), ""]
                if pending_verification else []
            ),
            *_evidence_section(evidence or []),
            *_checks_section(task),
            "## Human approval",
            "",
            json_section(approval),
            "",
            "## Reviewed scope" if is_decision_task(task) else "## Approved project scope",
            "",
            f"{task_id}: {consultation['scope']['brief'].strip()}",
            "",
            *answer_lines(consultation["scope"]),
            *scope_lines(consultation["scope"]),
            "",
            *_rules_section(task, checks),
            "## Advisory review",
            "",
            review["summary"],
            "",
            *review_lines(review),
            "",
            f"Each board's evidence and lens findings: openguildkit task challenge {task_id}.",
            "",
            *(
                ["## External actions decided by a person", "", json_section(task["authorizations"]), ""]
                if task.get("authorizations") else []
            ),
            *(
                [
                    "## Conditions from resolved blockers",
                    "",
                    "Respect each waiver's scope and expiry. A waiver that expires before the work ships needs a "
                    "new decision.",
                    "",
                    json_section([item for item in blocker_list(task) if item["resolution"]]),
                    "",
                ]
                if any(item["resolution"] for item in blocker_list(task)) else []
            ),
        ]
    )


def review_lines(review: dict) -> list[str]:
    """Each board's advice in a few lines: verdict, recommendation, verification, blockers and open questions."""
    lines = []
    for entry in review["boards"]:
        challenge = entry.get("challenge", {})
        verdict = f" {challenge['verdict']} ({challenge['confidence']} confidence)." if challenge else ""
        lines.append(f"- {entry['id']}:{verdict} {entry['recommendation']}")
        if challenge.get("verification"):
            lines.append(f"  - Verification: {challenge['verification']}")
        for blocker in challenge.get("blockers", []):
            lines.append(f"  - Blocker: {blocker['finding'] if isinstance(blocker, dict) else blocker}")
        lines.extend(f"  - Open question: {question}" for question in entry["open_questions"])
    return lines
