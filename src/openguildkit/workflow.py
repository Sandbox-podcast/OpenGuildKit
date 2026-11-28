"""Check what the boards return and carry the task to the person's decision: the review entries and their evidence,
the deliberation between boards, the decision brief, the blockers and the implementation handoff.

The questionnaire (questionnaire.py), the routing (routing.py) and the consultation (consultation.py) come first.

Entry: TaskStateError, mock_evidence
Tests: tests/test_assumptions.py, tests/test_board_entries.py, tests/test_brain_selection.py, tests/test_clock.py,
tests/test_decision_brief.py, tests/test_evidence_fingerprints.py, tests/test_output_size.py, tests/test_owners.py,
tests/test_sensitive.py, tests/test_short_lane.py
"""

from pathlib import Path

from . import owners
from .board_entries import evidence_positions, received_value, validate_review
from .consultation import json_section
from .questionnaire import ASSUMPTIONS
from .routing import normalize_text, trigger_matches
from .tasks_record import RESOLUTION_FIELDS
from .wording import plural


class TaskStateError(ValueError):
    """An action refused because of the task's status. The message says what is refused; the command line adds the
    status and the next command that runs in it (tasks_status.state_refusal)."""


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


def _domain_words(domains: dict | None):
    """The words of a board's domain (its title and routing triggers) that a text uses, as a function of the board
    and the text. Every board's words compete for the text, so that "contract test" belongs to QA and does not reach
    Legal through "contract". Each text is scanned once for every board: a review asks for the same texts again."""
    domains = {key: value for key, value in (domains or {}).items() if value}
    scanned: dict[tuple[str | None, str], dict[str, list[str]]] = {}

    def words(board_id: str, text: str) -> list[str]:
        added = None if board_id in domains else board_id  # A board without a domain competes with its ID.
        if (added, text) not in scanned:
            competing = {**domains, **({added: [added]} if added else {})}
            scanned[added, text] = trigger_matches({key: {"triggers": value} for key, value in competing.items()},
                                                   text)
        return scanned[added, text].get(board_id, [])

    return words


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
    domain_words = _domain_words(domains)
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
            meets = domain_words(responder["id"], point) + domain_words(objector["id"], _position_text(responder))
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
        return [], [f"got {received_value(response)}; each response is an object as in the template of task deliberate."]
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
        problems.append(f"{board}: position got {received_value(response['position'])}; accepted: {', '.join(POSITIONS)}.")
    count = len(evidence.get(board, []))
    evidence_positions(response["evidence_refs"], count, f"{board} evidence_refs", problems)
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
        lines.append(f"Mock data: {plural(len(synthetic), 'evidence item')} {'comes' if len(synthetic) == 1 else 'come'} from mock "
                     "tools, synthetic sample data and not "
                     f"the real systems: {', '.join(synthetic)}.")
    lines += _board_change_lines(task)
    lines += [f"Open point: {point}" for point in task["consultation"]["scope"].get("open_points", [])]
    lines += _assumption_lines(task, review)
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


def assumptions_read(task: dict, review: dict) -> list[dict]:
    """The task's working assumptions with the boards that contest each, the contested first, then in their order."""
    assumed = task["consultation"]["scope"].get("answers", {}).get(ASSUMPTIONS, [])
    items = [{"number": number, "text": text, "contested": []} for number, text in enumerate(assumed, start=1)]
    for entry in review["boards"]:
        for item in entry.get("contested_assumptions", []):
            items[item["assumption"] - 1]["contested"].append({"board": entry["id"], "reason": item["reason"]})
    return sorted(items, key=lambda item: not item["contested"])


def _assumption_lines(task: dict, review: dict) -> list[str]:
    """The assumptions apart, before the person types the task ID: approving accepts what is still assumed."""
    items = assumptions_read(task, review)
    if not items:
        return []
    lines = [f"Assumptions not confirmed ({len(items)}): approving accepts them as they are."]
    for item in items:
        boards = ", ".join(contest["board"] for contest in item["contested"])
        reasons = " ".join(f"{contest['board']}: {contest['reason']}" for contest in item["contested"])
        lines.append(f"Assumption {item['number']}, contested by {boards}: {item['text']} ({reasons})" if boards
                     else f"Assumption {item['number']}: {item['text']}")
    return lines


def challenge_report(task: dict, lines: list[str] | None = None, root: Path | None = None) -> str:
    """The decision brief: the lines the person reads before deciding (tasks_review.decision_text, the same as the
    approval prompt), then each board's challenge as JSON. With the project root, the code owners of what the task
    touches, read from CODEOWNERS and never recorded."""
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
    assumed = assumptions_read(task, review)
    if assumed:
        report["assumptions"] = assumed
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
    shown = decision_summary(task) if lines is None else lines
    owner = owners.owner_line(root, task) if root is not None else None
    summary = "\n".join(f"- {line}" for line in [*shown, *([owner] if owner else [])])
    return "# Decision brief\n\n" + summary + "\n\n" + json_section(report) + "\n"


def is_decision_task(task: dict) -> bool:
    """A decision task asks for a recommendation, not for a change to the project."""
    return task.get("answers", {}).get("kind") == "decision"


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


_SHARED_RESOLUTION = ("kind", "by", "at", "recorded_from", "evidence", "supports", "fingerprint", "reason", "scope",
                      "until", "signer")


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


