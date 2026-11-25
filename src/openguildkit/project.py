"""Collect a project profile and render its repository instructions."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from .agent_workflow import AGENT_WORKFLOW, RULE_PACKS_NOTE
from .catalog import rule_check
from .clock import today
from .patterns import (
    check_pattern_choices,
    condition_reasons,
    core_roles,
    is_stack_pattern,
    pattern_selection,
    recommend_patterns,
    role_choices,
    technology_key,
)
from .rule_checks import describe_check
from .storage import read_json, write_json, write_text

STATE_DIR = ".openguildkit"
SCHEMA_VERSION = 1
BEGIN = "<!-- BEGIN OPENGUILDKIT -->"
END = "<!-- END OPENGUILDKIT -->"
# The layout of the managed block, written in its stamp. Raise it when a release changes the block without changing
# the profile: the stamp then differs, and check calls the block out of date instead of calling its lines hand edits.
INSTRUCTIONS_LAYOUT = 2
ALREADY_INITIALIZED = (
    "Project is already initialized. Change its profile with openguildkit profile (adopt, decline, add, remove, "
    "set); openguildkit profile --help lists them."
)
# The agent's working files (answers, board entries, deliberation, result) go in work/: Git ignores it, and the guard
# lets the agent write there before any approval, as it is state the CLI reads rather than project work.
WORK_DIR = f"{STATE_DIR}/work"
PROJECT_IGNORE = "tasks/\nshares/\nwork/\n.lock\n.*.tmp\n"


def project_root(path: Path | None) -> Path:
    if path is not None:
        root = path.resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"Project path must be a directory: {root}")
        return root
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / STATE_DIR / "project.json").is_file():
            return candidate
    return current


def state_path(root: Path) -> Path:
    state = root / STATE_DIR
    if state.resolve() != state:
        raise ValueError(f"Project state must stay inside its project: {state}")
    return state


def _select(question_id, prompt, choices, default=None, multiple=False):
    question = {
        "id": question_id,
        "prompt": prompt,
        "type": "multi-select" if multiple else "select",
        "choices": [{"id": entry["id"], "label": entry["title"]} for entry in choices],
    }
    if default is not None:
        question["default"] = default
    return question


SECTOR_PROMPT = (
    "Which sector describes the project? Its regulation patterns are preselected for you to confirm. "
    "A project catalog can add its own sector in .openguildkit/catalog/sectors/."
)


def _personal_data_question() -> dict:
    """Personal data preselects the GDPR pattern; the answer is stored as personal_data."""
    question = _select(
        "personal_data",
        "Does the project process personal data, such as names, emails, health or payment data?",
        [{"id": "yes", "title": "Yes"}, {"id": "no", "title": "No"}],
    )
    return {**question, "required": True}


def _people_decisions_question() -> dict:
    """Software that ranks or decides about people proposes the EU AI Act; stored as people_decisions."""
    question = _select(
        "people_decisions",
        "Does the project score, rank, select or decide about individual people, for example hiring, credit, "
        "insurance, school places or a price per person? Asked when the project processes personal data.",
        [{"id": "yes", "title": "Yes"}, {"id": "no", "title": "No"}],
        "no",
    )
    return {**question, "when": {"personal_data": True}}


DEFAULT_GUARD = "observe"
GUARD_MODES = {
    "off": "Off: nothing reminds the agent to consult the board and no edit is checked; it depends on the agent "
           "following AGENTS.md.",
    "observe": "Observe: each request reminds the agent to open a task and consult the board; an edit without an "
               "approved task is flagged to the agent, not blocked.",
    "enforce": "Enforce: each request reminds the agent, and edits through its edit tools are refused until a person "
               "approves a task. Use signed approvals with it: a local approval can be forged by an agent that writes files.",
}
HOST_CHOICES = (
    ("claude-code", "Claude Code"),
    ("codex", "Codex"),
    ("other", "Another agent, or none: the rules stay in AGENTS.md and no host setting is written"),
)


def is_norm(pattern: dict) -> bool:
    """A regulation that the sector, personal data, decisions about people or the stack (a card payment
    provider) proposes, confirmed one by one at setup: it is active only once a person accepts it."""
    match = pattern.get("match", {})
    return pattern.get("kind") == "regulation" and bool(
        match.get("sectors") or match.get("personal_data") or match.get("people_decisions") or match.get("stack")
    )


NORM_CONDITIONS = ("sectors", "personal_data", "people_decisions", "stack")


def norm_reason(pattern: dict) -> str:
    """Why a norm is proposed, in the words of its condition."""
    match = pattern["match"]
    reasons = [f"the sector is {' or '.join(match['sectors'])}"] if match.get("sectors") else []
    if match.get("personal_data"):
        reasons.append("the project processes personal data")
    if match.get("people_decisions"):
        reasons.append("the project scores, ranks or decides about people")
    if match.get("stack"):
        reasons.append(f"the stack names {' or '.join(match['stack'][0])}")
    return " or ".join(reasons)


def _norms_question(catalog: dict) -> dict:
    """One sub-question per norm, asked only when its condition holds; a no is recorded in declined.

    The help is the pattern's description, which says when the norm does not apply, with the sources behind it,
    so that a person who declines it does so knowingly.
    """
    norms = [
        {
            "id": pattern["id"],
            "title": pattern["title"],
            "when": {key: pattern["match"][key] for key in NORM_CONDITIONS if key in pattern["match"]},
            "prompt": f"{pattern['title']} ({pattern['id']}) is proposed because {norm_reason(pattern)}. Does it apply?",
            "help": pattern["description"],
            "sources": [{"title": source["title"], "url": source["url"]} for source in pattern["sources"]],
        }
        for pattern in catalog["patterns"].values() if is_norm(pattern)
    ]
    return {
        "id": "norms",
        "type": "norms",
        "prompt": (
            "Ask each norm below whose condition the project meets (its sector, personal data, decisions about "
            "people, or a technology of its stack), one at a time. Record each answer under norms: \"yes\" makes "
            'the norm active; a no needs who and why, {"answer": "no", "by": "NAME", "reason": "WHY"}, and is '
            "recorded in declined so that it is not proposed again. A norm whose condition holds and that is "
            "not answered stops init: nothing is active that a person did not accept."
        ),
        "norms": norms,
        "default": "yes",
    }


def _tools_question(detected: list[dict]) -> dict:
    question = {
        "id": "tools",
        "type": "list",
        "prompt": (
            "Which tools does the company work with: tracker, documentation, CI, chat, time tracking, HR, security "
            "scanner? Use the names the team uses. openguildkit tools list shows the tools the registry knows; a name "
            "it does not know is kept as written."
        ),
        "examples": ["Jira", "Confluence", "GitHub Actions", "Slack"],
        "default": [item["tool"] for item in detected],
    }
    if detected:
        question["detected"] = detected
    return question


def _host_question(detected: str | None) -> dict:
    """The default stays other: choosing a host makes check require its settings, so the person names it."""
    prompt = "Which agent host does the team use?"
    if detected:
        prompt += f" The repository has {dict(HOST_CHOICES)[detected]} files."
    question = _select("host", prompt, [{"id": key, "title": title} for key, title in HOST_CHOICES], "other")
    return {**question, "detected": detected} if detected else question


def _checks_question(proposed: list[dict]) -> dict:
    """The project checks, with the test commands the repository shows proposed for the person to confirm."""
    question = {
        "id": "checks",
        "type": "list",
        "prompt": (
            "Which project checks should the agent or CI run? task verify runs each one in the project root, and the "
            "task cannot be done while one fails: keep commands that pass once the project's dependencies are "
            "installed, and leave to CI a check that needs the network or a service (docs/workflow.md#project-checks)."
        ),
        "default": [],
    }
    if proposed:
        question["proposed"] = proposed
        question["prompt"] += " The repository shows the commands under proposed: confirm or remove each one."
    return question


def init_questions(
    catalog: dict, project_name: str, detected: list[dict] | None = None, tools: list[dict] | None = None,
    host: str | None = None, proposed_checks: list[dict] | None = None,
) -> list[dict]:
    """The setup questionnaire, in the order it is asked. Every question has a default or is marked required.

    detected: components found in the repository; tools: registry tools it shows signs of; host: the agent
    host its files point to; proposed_checks: test commands the repository shows, for the person to confirm.
    """
    components = {
        "id": "components",
        "type": "components",
        "prompt": (
            "Which components does the repository contain? Confirm or correct each component's "
            "path and stack, with versions where you know them."
        ),
        "examples": [{"id": "web", "path": "apps/web", "stack": ["Next.js 14.2", "React 18.3", "TypeScript"]}],
    }
    components["default"] = detected or []
    patterns = _select(
        "patterns",
        "Which other patterns should apply? Enter keeps those preselected by the stack, the sector and the core "
        "method of each role; the other methods of the roles are suggestions. openguildkit recommend --answers "
        "FILE shows why each one is preselected or suggested and how many rules it adds.",
        catalog["patterns"].values(),
        multiple=True,
    )
    patterns["default_label"] = "the preselected patterns (leave patterns out of an answers file)"
    packs = _select(
        "packs",
        "Which packs should apply in addition to the recommended baseline and language packs and the packs of "
        'the selected patterns? Enter adds none. In an answers file, "replace_default_packs": true makes this '
        "list replace the recommended packs.",
        catalog["packs"].values(),
        [],
        multiple=True,
    )
    packs["default_label"] = "none beyond the recommended packs"
    boards = _select(
        "boards",
        "Which boards can advise? An empty list lets every board advise, including boards added later.",
        catalog["boards"].values(),
        [],
        multiple=True,
    )
    boards["default_label"] = "all boards (saved as an empty list)"
    questions = [
        {"id": "name", "type": "text", "prompt": "Project name", "default": project_name},
        _select("sector", SECTOR_PROMPT, catalog["sectors"].values(), "general"),
        {
            "id": "stack",
            "type": "list",
            "prompt": "Which languages, frameworks and services are in the stack? Add a version where it matters.",
            "examples": ["Python 3.12", "FastAPI", "PostgreSQL 16"],
            "default": [],
        },
        components,
        _select(
            "roles",
            "Which roles should this project support?",
            role_choices(catalog["patterns"]).values(),
            [],
            multiple=True,
        ),
        _personal_data_question(),
        _people_decisions_question(),
        _norms_question(catalog),
        patterns,
        packs,
        boards,
        _tools_question(tools or []),
        _host_question(host),
        _select("guard", "Should the board be brought to the agent before each change?",
                [{"id": key, "title": text} for key, text in GUARD_MODES.items()], DEFAULT_GUARD),
        _select(
            "research",
            "Can the host agent consult public sources when you approve it for a task?",
            [
                {"id": "local-only", "title": "Use project sources"},
                {"id": "public-sources", "title": "Allow public research when requested for a task"},
            ],
            "local-only",
        ),
        {"id": "conventions", "type": "list", "prompt": "Which team conventions should the agent follow?", "default": []},
        _checks_question(proposed_checks or []),
    ]
    return [{**question, "help": QUESTION_HELP[question["id"]], "unsure": _unsure_text(question)}
            for question in questions]


# One line per question in plain words, for a person who does not know the product's vocabulary.
QUESTION_HELP = {
    "name": "The name the rules and the task records show; the folder name is fine.",
    "sector": "The field the project works in; it decides which laws are proposed, such as DORA for finance.",
    "stack": "The programming languages, frameworks and databases the code uses, such as Python or React.",
    "components": "The separate parts of the repository, each in its own folder, such as a website and an API.",
    "roles": "The jobs whose methods the agent should follow, such as back-end development or marketing.",
    "personal_data": "Whether the software stores or reads information about people: names, emails, health, payments.",
    "people_decisions": "Whether the software sorts, scores or picks people, which the EU AI Act regulates.",
    "norms": "Laws and standards that may apply because of your sector, your data or your tools; each is a yes or a no.",
    "patterns": "Ready-made sets of rules for a technology or a way of working; keep the ones that fit your team.",
    "packs": "Extra lists of rules for the agent; most teams keep only those already chosen for them.",
    "boards": "The panels of specialists (security, legal, design...) that review a task before work starts.",
    "tools": "The software the team uses every day, such as Jira, Slack or GitHub, so the agent can read from it.",
    "host": "The AI coding assistant the team uses in the project, such as Claude Code or Codex.",
    "guard": "How strictly the agent is held to asking the specialists before it changes files.",
    "research": "Whether the agent may look things up on the internet when a person allows it for a task.",
    "conventions": "House rules the agent should follow, in one sentence each, such as how branches are named.",
    "checks": "Commands that test the code, such as npm test, run before a task can be closed.",
}
UNSURE = ("unsure", "?")
# The answer an "I don't know" takes when it is not the question's default: the one that keeps a protection.
UNSURE_ANSWERS = {"personal_data": "yes"}


def _unsure_text(question: dict) -> str:
    """What an "I don't know" answer applies, said to the person."""
    if question["id"] in UNSURE_ANSWERS:
        return (f"{UNSURE_ANSWERS[question['id']]}: the protective answer, so the laws on personal data are proposed "
                "for a person to accept or decline")
    if question["id"] == "norms":
        return "yes: the norm is active until the person responsible declines it with openguildkit profile decline"
    if "default_label" in question:
        return f"the default: {question['default_label']}"
    default = question.get("default")
    shown = ", ".join(map(_default_item, default)) if isinstance(default, list) else default
    return f"the default: {shown or 'none'}"


def _default_item(item) -> str:
    """One item of a default answer in words: a detected component by its ID and folder, anything else as is."""
    if isinstance(item, dict) and "id" in item:
        return f"{item['id']} ({item['path']})" if item.get("path") else str(item["id"])
    return str(item)


def unsure_answers(answers: dict, questions: list[dict]) -> tuple[dict, list[str]]:
    """Replace each "unsure" answer by what its question applies, and say so, one line per question."""
    by_id = {question["id"]: question for question in questions}
    answers, notes = dict(answers), []
    for question_id, value in list(answers.items()):
        if question_id not in by_id or not isinstance(value, str) or value.strip().casefold() not in UNSURE:
            continue
        question = by_id[question_id]
        if question_id in UNSURE_ANSWERS:
            answers[question_id] = UNSURE_ANSWERS[question_id]
        elif "default" in question:
            answers[question_id] = question["default"]
        else:
            del answers[question_id]
        notes.append(f"{question_id}: unsure, so {question['unsure']}.")
    norms = answers.get("norms")
    if isinstance(norms, dict):
        unsure = [norm for norm, value in norms.items() if isinstance(value, str) and value.casefold() in UNSURE]
        answers["norms"] = {**norms, **dict.fromkeys(unsure, "yes")}
        notes += [f"norm {norm}: unsure, so {by_id['norms']['unsure']}." for norm in unsure]
    return answers, notes


def _single_line(value: str) -> bool:
    """True when the text holds no line break of any kind, including a lone carriage return."""
    return len(value.strip().splitlines()) == 1


def _texts(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    if any(not _single_line(item) for item in value):
        raise ValueError(f"Each entry of {field} must be a single line")
    return list(dict.fromkeys(item.strip() for item in value))


def _ids(value, field: str, available: dict) -> list[str]:
    chosen = _texts(value, field)
    unknown = sorted(set(chosen) - available.keys())
    if unknown:
        hint = (
            " It comes from a central policy: pass --policy-repo and --policy-commit."
            if "export-link-expiry" in unknown else " Run openguildkit catalog."
        )
        raise ValueError(f"Unknown {field}: {', '.join(unknown)}.{hint}")
    return chosen


def _recommended_packs(stack: list[str], catalog: dict) -> list[str]:
    aliases = {"react.js": "react", "openapi": "api-design"}
    tokens = {re.split(r"[\s@]+", item.lower(), maxsplit=1)[0] for item in stack}
    legacy_stack_packs = {"api-design", "python", "react", "typescript"}
    names = {aliases.get(token, token) for token in tokens}
    candidates = {"secure-sdlc", *(names & legacy_stack_packs)}
    return sorted(candidates & catalog["packs"].keys())


def _default_packs(stack: list[str], components: list[dict], patterns: list, catalog: dict) -> list[str]:
    """Recommended packs. In a monorepo a language pack that a selected pattern brings keeps that pattern's scope."""
    packs = _recommended_packs(stack, catalog)
    if not components:
        return packs
    brought = {pack_id for entry in patterns for pack_id in catalog["patterns"][pattern_selection(entry)[0]]["packs"]}
    return [pack_id for pack_id in packs if pack_id not in brought]


COMPONENT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _components(value) -> list[dict]:
    """Validate the project's components: an ID, an optional relative path and a stack each."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("components must be a list of objects with id, path and stack")
    components, seen = [], set()
    for component in value:
        if not isinstance(component, dict) or not {"id", "stack"} <= component.keys() <= {"id", "path", "stack"}:
            raise ValueError("Each component needs an id and a stack, and can have a path")
        component_id = component["id"]
        if not isinstance(component_id, str) or len(component_id) > 64 or not COMPONENT_ID.fullmatch(component_id):
            raise ValueError("Component IDs use up to 64 lowercase letters, digits and separating hyphens")
        if component_id in seen:
            raise ValueError(f"Duplicate component: {component_id}")
        seen.add(component_id)
        entry = {"id": component_id}
        if "path" in component:
            path = component["path"]
            parts = path.replace("\\", "/").split("/") if isinstance(path, str) else []
            if not isinstance(path, str) or not path.strip() or path.startswith(("/", "\\")) or ":" in path or ".." in parts:
                raise ValueError(f"Component {component_id} needs a path relative to the project root")
            entry["path"] = path.strip()
        entry["stack"] = _texts(component["stack"], f"components.{component_id}.stack")
        components.append(entry)
    return components


def _project_context(answers: dict, catalog: dict) -> tuple[str, list[str], list[str], list[dict]]:
    sector = answers.get("sector", "general")
    if not isinstance(sector, str) or sector not in catalog["sectors"]:
        raise ValueError(f"Unknown sector: {sector}. Run openguildkit catalog.")
    components = _components(answers.get("components"))
    stack = _texts(answers.get("stack", []), "stack")
    if components:
        # With components, the project stack is the union of what each component uses.
        stack = list(dict.fromkeys([*stack, *(item for component in components for item in component["stack"])]))
    roles = _ids(answers.get("roles", []), "roles", role_choices(catalog["patterns"]))
    return sector, stack, roles, components


def _yes_no(value, field: str) -> bool | None:
    """A yes or no answer: true, false, or None when it was not asked."""
    if value is None or isinstance(value, bool):
        return value
    if value in ("yes", "no"):
        return value == "yes"
    raise ValueError(f"{field} must be yes, no, true or false")


def _personal_data(value) -> bool | None:
    """The answer to the personal data question: true, false, or None when it was not asked."""
    return _yes_no(value, "personal_data")


DECISION_FIELDS = ("by", "on", "reason")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _decision_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or not _single_line(value):
        raise ValueError(f"{field} must be a non-empty single line")
    return value.strip()


def _decision(entry: dict, label: str) -> dict:
    """Who decided, on which day and why: each a single line, the day as YYYY-MM-DD."""
    record = {key: _decision_text(entry[key], f"{label} {key}") for key in DECISION_FIELDS}
    if not DATE.fullmatch(record["on"]):
        raise ValueError(f"{label} on must be a date written YYYY-MM-DD")
    return record


def _declined(value, catalog: dict) -> list:
    """Declined patterns: plain IDs (written before declines were recorded), or objects with who, when and why."""
    if not isinstance(value, list):
        raise ValueError("declined must be a list")
    entries, seen = [], set()
    for entry in value:
        if isinstance(entry, dict):
            if set(entry) != {"id", *DECISION_FIELDS}:
                raise ValueError('A declined entry is an ID or {"id", "by", "on", "reason"}')
            pattern_id = entry["id"]
        else:
            pattern_id = entry
        if not isinstance(pattern_id, str) or pattern_id not in catalog["patterns"]:
            raise ValueError(f"Unknown declined: {pattern_id}. Run openguildkit catalog.")
        if pattern_id in seen:
            continue
        seen.add(pattern_id)
        decided = isinstance(entry, dict)
        entries.append({"id": pattern_id, **_decision(entry, f"declined {pattern_id}")} if decided else pattern_id)
    return entries


def declined_ids(profile: dict) -> list[str]:
    return [entry["id"] if isinstance(entry, dict) else entry for entry in profile.get("declined", [])]


def _changes(value) -> list[dict]:
    """The history of profile commands: who changed what, on which day and why."""
    if not isinstance(value, list):
        raise ValueError("changes must be a list")
    result = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"change", *DECISION_FIELDS}:
            raise ValueError('Each change needs change, by, on and reason')
        result.append({"change": _decision_text(entry["change"], "change"), **_decision(entry, "change")})
    return result


def _recommendation_inputs(answers: dict, catalog: dict) -> dict:
    """Everything that preselects patterns besides the stack: personal data, decisions about people and
    declined patterns."""
    return {
        "personal_data": _personal_data(answers.get("personal_data")),
        "people_decisions": _yes_no(answers.get("people_decisions"), "people_decisions"),
        "declined": [entry["id"] if isinstance(entry, dict) else entry
                     for entry in _declined(answers.get("declined", []), catalog)],
    }


def profile_recommendations(answers: dict, catalog: dict) -> dict:
    """Preselected and suggested patterns for setup answers or a saved profile, and the packs they bring."""
    sector, stack, roles, components = _project_context(answers, catalog)
    inputs = _recommendation_inputs(answers, catalog)
    result = recommend_patterns(catalog, stack, sector, roles, components, **inputs)
    result["declined"] = _declined(answers.get("declined", []), catalog)
    base_packs = ["agent-workflow", *_recommended_packs(stack, catalog)]
    for entry in [*result["matched"], *result["suggested"]]:
        entry["rules"] = pattern_rules(entry, catalog)
    result["recommended_packs"] = list(
        dict.fromkeys([*base_packs, *(pack for pattern in result["matched"] for pack in pattern["packs"])])
    )
    result["rule_count"] = sum(pack_rule_counts(result["recommended_packs"], catalog).values())
    return result


# One meaning for the rule count of a pattern, in recommend, preview and init.
RULES_NOTE = ("Each pattern's count is the rules of its own packs and their dependencies, even when another "
              "pattern or the baseline brings the same pack.")


def pattern_rules(pattern: dict, catalog: dict) -> int:
    """The rules of a pattern's packs and their dependencies: the same number wherever it is shown."""
    return sum(pack_rule_counts(pattern["packs"], catalog).values())


def pack_rule_counts(pack_ids: list[str], catalog: dict) -> dict[str, int]:
    """The rules of these packs and of their dependencies, each pack counted once."""
    counts: dict[str, int] = {}

    def add(pack_id: str) -> None:
        if pack_id in counts:
            return
        counts[pack_id] = 0
        for dependency in catalog["packs"][pack_id].get("depends_on", []):
            add(dependency)
        counts[pack_id] = len(catalog["packs"][pack_id]["rules"])

    for pack_id in pack_ids:
        add(pack_id)
    return counts


def _pattern_entries(value, catalog: dict, components: list[dict]) -> list:
    """Validate selected patterns: plain IDs, or objects limiting a pattern to components."""
    if not isinstance(value, list):
        raise ValueError("patterns must be a list")
    known_components = {component["id"] for component in components}
    entries, seen = [], set()
    for entry in value:
        if isinstance(entry, dict):
            if set(entry) != {"id", "components"}:
                raise ValueError("A scoped pattern needs exactly id and components")
            scope = _texts(entry["components"], "pattern components")
            unknown = sorted(set(scope) - known_components)
            if unknown:
                raise ValueError(f"Pattern {entry['id']} names unknown components: {', '.join(unknown)}")
            pattern_id = entry["id"]
        else:
            pattern_id, scope = entry, None
        if not isinstance(pattern_id, str) or pattern_id not in catalog["patterns"]:
            raise ValueError(f"Unknown patterns: {pattern_id}. Run openguildkit catalog.")
        if pattern_id in seen:
            continue
        seen.add(pattern_id)
        entries.append({"id": pattern_id, "components": scope} if scope else pattern_id)
    return entries


def _resolutions(value, catalog: dict) -> list[dict]:
    """Validate the team's choices between conflicting packs."""
    if not isinstance(value, list):
        raise ValueError("resolutions must be a list")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"packs", "keep", "reason"}:
            raise ValueError("Each resolution needs packs, keep and reason")
        packs = _ids(item["packs"], "resolution packs", catalog["packs"])
        keep = _ids(item["keep"], "resolution keep", catalog["packs"])
        if len(packs) < 2:
            raise ValueError("A resolution names at least two conflicting packs")
        if not keep or not set(keep) <= set(packs):
            raise ValueError("keep must list one or more of the resolution's packs")
        reason = item["reason"]
        if not isinstance(reason, str) or not reason.strip() or not _single_line(reason):
            raise ValueError("A resolution needs a single-line reason")
        key = tuple(sorted(packs))
        if key in seen:
            raise ValueError(f"Duplicate resolution for {', '.join(key)}")
        seen.add(key)
        result.append({"packs": sorted(packs), "keep": sorted(keep), "reason": reason.strip()})
    return result


def pattern_ids(profile: dict) -> list[str]:
    return [pattern_selection(entry)[0] for entry in profile.get("patterns", [])]


def validate_profile(answers: dict, catalog: dict) -> dict:
    fields = {
        "schema_version", "name", "sector", "stack", "components", "roles", "patterns", "packs",
        "resolutions", "boards", "required_boards", "required_rules", "research", "host", "guard", "waivers", "approval", "tools",
        "conventions", "checks", "personal_data", "people_decisions", "declined", "changes", "ask_every_rule",
    }
    unknown = sorted(answers.keys() - fields)
    if unknown:
        raise ValueError(f"Unknown profile fields: {', '.join(unknown)}")
    version = answers.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported project schema version: {version}")
    name = answers.get("name")
    if not isinstance(name, str) or not name.strip() or not _single_line(name):
        raise ValueError("name must be a non-empty single line")
    sector, stack, roles, components = _project_context(answers, catalog)
    research = answers.get("research", "local-only")
    if research not in ("local-only", "public-sources"):
        raise ValueError("research must be local-only or public-sources")
    inputs = _recommendation_inputs(answers, catalog)
    patterns = _pattern_entries(answers.get("patterns", []), catalog, components)
    if "patterns" not in answers and "packs" not in answers:
        patterns = [
            {"id": record["id"], "components": record["components"]} if record.get("components") else record["id"]
            for record in recommend_patterns(catalog, stack, sector, roles, components, **inputs)["matched"]
        ]
    declined = _declined(answers.get("declined", []), catalog)
    both = sorted(set(inputs["declined"]) & {pattern_selection(entry)[0] for entry in patterns})
    if both:
        raise ValueError(f"Pattern {', '.join(both)} is both selected and declined: remove it from one of the lists.")
    check_pattern_choices([pattern_selection(entry)[0] for entry in patterns], catalog["patterns"])
    packs = _ids(answers.get("packs", _default_packs(stack, components, patterns, catalog)), "packs", catalog["packs"])
    profile = {
        "schema_version": SCHEMA_VERSION,
        "name": name.strip(),
        "sector": sector,
        "stack": stack,
        **({"components": components} if components else {}),
        "packs": list(dict.fromkeys(["agent-workflow", *packs])),
        "boards": _ids(answers.get("boards", []), "boards", catalog["boards"]),
        "research": research,
        "conventions": _texts(answers.get("conventions", []), "conventions"),
        "checks": _texts(answers.get("checks", []), "checks"),
    }
    if roles:
        profile["roles"] = roles
    if inputs["personal_data"] is not None:
        profile["personal_data"] = inputs["personal_data"]
    if inputs["people_decisions"] is not None:
        profile["people_decisions"] = inputs["people_decisions"]
    if patterns:
        profile["patterns"] = patterns
    if declined:
        profile["declined"] = declined
    host = answers.get("host")
    if host is not None:
        from .hosts import HOSTS
        if host not in HOSTS:
            raise ValueError(f"host must be one of {', '.join(HOSTS)}")
        profile["host"] = host
    tools = _texts(answers.get("tools", []), "tools")
    if tools:
        profile["tools"] = tools
    guard = answers.get("guard")
    if guard is not None:
        if guard not in ("off", "observe", "enforce"):
            raise ValueError("guard must be off, observe or enforce")
        profile["guard"] = guard
    required_rules = _texts(answers.get("required_rules", []), "required_rules")
    for item in required_rules:
        pack_id, _, rule_id = item.partition("/")
        pack = catalog["packs"].get(pack_id)
        if pack is None or (rule_id and rule_id not in {rule["id"] for rule in pack["rules"]}):
            raise ValueError(f"Unknown required rule {item}: use PACK or PACK/RULE from openguildkit catalog")
    if required_rules:
        profile["required_rules"] = required_rules
    approval = answers.get("approval")
    if approval is not None:
        if not isinstance(approval, dict) or approval.get("mode") not in ("local", "signed"):
            raise ValueError("approval.mode must be local or signed")
        if approval["mode"] == "signed":
            if set(approval) != {"mode", "allowed_signers", "approvers"}:
                raise ValueError("A signed approval needs allowed_signers (a project path) and approvers")
            path = approval["allowed_signers"]
            if not isinstance(path, str) or not path.strip() or path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
                raise ValueError("approval.allowed_signers must be a path inside the project")
            profile["approval"] = {"mode": "signed", "allowed_signers": path.strip(),
                                   "approvers": _texts(approval["approvers"], "approval.approvers")}
        elif set(approval) != {"mode"}:
            raise ValueError("A local approval takes no other setting")
    waivers = answers.get("waivers")
    if waivers is not None:
        if not isinstance(waivers, dict) or set(waivers) != {"allowed_by", "max_days"}:
            raise ValueError("waivers needs allowed_by (names) and max_days")
        max_days = waivers["max_days"]
        if type(max_days) is not int or not 1 <= max_days <= 366:
            raise ValueError("waivers.max_days must be a whole number of days between 1 and 366")
        profile["waivers"] = {"allowed_by": _texts(waivers["allowed_by"], "waivers.allowed_by"), "max_days": max_days}
    ask_every_rule = answers.get("ask_every_rule", False)
    if type(ask_every_rule) is not bool:
        raise ValueError("ask_every_rule must be true or false")
    if ask_every_rule:
        profile["ask_every_rule"] = True
    required = _ids(answers.get("required_boards", []), "required_boards", catalog["boards"])
    if required:
        profile["required_boards"] = required
    resolutions = _resolutions(answers.get("resolutions", []), catalog)
    if resolutions:
        profile["resolutions"] = resolutions
    changes = _changes(answers.get("changes", []))
    if changes:
        profile["changes"] = changes
    return profile


def _norm_answers(value, catalog: dict) -> dict[str, dict | None]:
    """The answers to the norms question: "yes" (or true) accepts a norm; a no names who and why,
    {"answer": "no", "by": NAME, "reason": WHY}. Returns None for an accepted norm, the decline otherwise."""
    if not isinstance(value, dict):
        raise ValueError('norms must be an object such as {"gdpr-personal-data": "yes"}')
    answers = {}
    for pattern_id, answer in value.items():
        if pattern_id not in catalog["patterns"] or not is_norm(catalog["patterns"][pattern_id]):
            raise ValueError(f"Unknown norm: {pattern_id}. Use the IDs listed in the norms question of init --questions.")
        if answer in ("yes", True):
            answers[pattern_id] = None
        elif isinstance(answer, dict) and answer.get("answer") == "no" and set(answer) == {"answer", "by", "reason"}:
            answers[pattern_id] = {"id": pattern_id, **_decision({**answer, "on": today().isoformat()},
                                                                 f"norm {pattern_id}")}
        elif answer in ("no", False) or isinstance(answer, dict):
            raise ValueError(
                f'Declining norm {pattern_id} records who and why: write {{"answer": "no", "by": "NAME", '
                '"reason": "WHY"}, with the name of the person who decided.'
            )
        else:
            raise ValueError(f"The answer for norm {pattern_id} must be yes or no")
    return answers


def _merged_stack(detected: list[str], written: list) -> list[str]:
    """The detected stack with what the person wrote: their entry wins for a technology both name."""
    written = [item for item in written if isinstance(item, str) and item.strip()]
    by_key = {technology_key(item): item for item in written}
    merged = [by_key.pop(technology_key(item), item) for item in detected]
    return merged + [item for item in written if technology_key(item) in by_key]


def unanswered_norms(answers: dict, catalog: dict, norms: dict) -> list[dict]:
    """The norms whose condition the answers meet and that no answer accepts, lists or declines."""
    sector, stack, roles, components = _project_context(answers, catalog)
    inputs = _recommendation_inputs(answers, catalog)
    chosen = {pattern_selection(entry)[0] for entry in answers.get("patterns", []) if isinstance(entry, (str, dict))}
    plan = recommend_patterns(catalog, stack, sector, roles, components, **inputs)["matched"]
    return [entry for entry in plan if is_norm(catalog["patterns"][entry["id"]])
            and entry["id"] not in norms and entry["id"] not in chosen]


def complete_answers(answers: object, questions: list[dict], catalog: dict) -> tuple[dict, list[dict], list[str]]:
    """Give each omitted question its default and record the norms answered no in declined.

    Returns the answers, the detected components left aside and the norms answered yes.
    """
    if not isinstance(answers, dict):
        raise ValueError("Setup answers must be a JSON object, such as {} or {\"name\": \"Portal\"}.")
    completed = unsure_answers(answers, questions)[0]
    defaults = {question["id"]: question["default"] for question in questions if "default" in question}
    detected = defaults.pop("components", [])
    for field in ("name", "sector", "boards", "tools", "host", "guard", "research"):
        if field in defaults:
            completed.setdefault(field, defaults[field])
    root_only = len(detected) == 1 and detected[0].get("path") == "."
    if "components" not in completed and detected and ("stack" not in completed or root_only):
        completed["components"] = detected
        if root_only and isinstance(completed.get("stack"), list):
            completed["components"] = [{**detected[0], "stack": _merged_stack(detected[0]["stack"], completed["stack"])}]
    left_aside = detected if detected and not completed.get("components") else []
    norms = _norm_answers(completed.pop("norms", {}), catalog)
    declined = [decline for decline in norms.values() if decline is not None]
    if declined:
        earlier = _declined(completed.get("declined", []), catalog)
        named = {decline["id"] for decline in declined}
        completed["declined"] = [*(entry for entry in earlier if (entry["id"] if isinstance(entry, dict) else entry)
                                   not in named), *declined]
    return completed, left_aside, [pattern_id for pattern_id, decline in norms.items() if decline is None]


def setup_profile(answers: object, catalog: dict, questions: list[dict]) -> tuple[dict, list[dict]]:
    """The profile that init writes from setup answers, and the detected components the answers leave aside.

    Unlike a saved profile, setup answers add their packs to the recommended ones unless
    "replace_default_packs" is true, and omitted patterns are preselected even when packs are given.
    """
    completed, left_aside, kept_norms = complete_answers(answers, questions, catalog)
    missing = unanswered_norms(completed, catalog, {pattern_id: True for pattern_id in kept_norms})
    if missing:
        listed = "; ".join(f"{entry['id']} ({', '.join(entry['reasons'])})" for entry in missing)
        raise ValueError(
            f"Ask the person about each norm the project meets, then record the answers under norms: {listed}. "
            'Write "yes", or {"answer": "no", "by": "NAME", "reason": "WHY"}. Nothing was written.'
        )
    replace = completed.pop("replace_default_packs", False)
    if not isinstance(replace, bool):
        raise ValueError("replace_default_packs must be true or false")
    sector, stack, roles, components = _project_context(completed, catalog)
    if "patterns" not in completed:
        inputs = _recommendation_inputs(completed, catalog)
        completed["patterns"] = [
            {"id": record["id"], "components": record["components"]} if record.get("components") else record["id"]
            for record in recommend_patterns(catalog, stack, sector, roles, components, **inputs)["matched"]
        ]
    patterns = _pattern_entries(completed["patterns"], catalog, components)
    selected = {pattern_selection(entry)[0] for entry in patterns}
    completed["patterns"] = [*(pattern_id for pattern_id in kept_norms if pattern_id not in selected), *patterns]
    chosen = _ids(completed.get("packs", []), "packs", catalog["packs"])
    if not replace:
        chosen = [*_default_packs(stack, components, completed["patterns"], catalog), *chosen]
    completed["packs"] = list(dict.fromkeys(chosen))
    return validate_profile(completed, catalog), left_aside


def load_profile(state: Path, catalog: dict) -> dict:
    path = state / "project.json"
    if not path.is_file():
        # Run from the wrong folder, a bare "run init" would start a second project there.
        raise ValueError(f"No OpenGuildKit project found for {state.parent.as_posix()}: {STATE_DIR}/project.json "
                         "does not exist. cd into the project folder or pass --project PATH; run openguildkit init "
                         "only to set up a new project here.")
    answers = read_json(path)
    sector = answers.get("sector", "general")
    if isinstance(sector, str) and sector not in catalog["sectors"]:
        raise ValueError(
            f".openguildkit/project.json names the sector {sector!r}, which neither this release nor the catalog "
            "lock provides: choose one listed by openguildkit catalog, set it in .openguildkit/project.json, "
            "then run openguildkit sync."
        )
    missing = _missing_records(answers, catalog)
    if missing:
        entries = ", ".join(f'"{record_id}" from "{field}"' for field, record_id in missing)
        raise ValueError(
            f".openguildkit/project.json uses records that neither this release nor the catalog lock provides: "
            f"remove {entries}, then run openguildkit sync."
        )
    return validate_profile(answers, catalog)


def _missing_records(answers: dict, catalog: dict) -> list[tuple[str, str]]:
    """Profile entries that name a pack, pattern or board no catalog in force provides."""
    fields = (
        ("packs", "packs"), ("patterns", "patterns"), ("declined", "patterns"), ("boards", "boards"),
        ("required_boards", "boards"),
    )
    missing = []
    for field, collection in fields:
        entries = answers.get(field)
        for entry in entries if isinstance(entries, list) else []:
            record_id = entry.get("id") if isinstance(entry, dict) else entry
            if isinstance(record_id, str) and record_id not in catalog[collection]:
                missing.append((field, record_id))
    return missing


def selected_packs(profile: dict, catalog: dict) -> list[str]:
    """Packs from the profile and its patterns, each after its dependencies, before any resolution."""
    ordered = {}

    def add_pack(pack_id):
        if pack_id not in ordered:
            for dependency in catalog["packs"][pack_id].get("depends_on", []):
                add_pack(dependency)
            ordered[pack_id] = None

    pattern_packs = [
        pack_id
        for pattern_id in pattern_ids(profile)
        for pack_id in catalog["patterns"][pattern_id]["packs"]
    ]
    for pack_id in [*profile["packs"], *pattern_packs]:
        add_pack(pack_id)
    return list(ordered)


def rule_conflicts(profile: dict, catalog: dict) -> list[dict]:
    """Declared incompatibilities between selected packs that apply to a common scope."""
    selected = selected_packs(profile, catalog)
    scopes = pack_scopes(profile, catalog)
    # A declaration on either pack is enough: conflicts are symmetric.
    declared = {
        tuple(sorted((pack_id, other)))
        for pack_id in selected
        for other in catalog["packs"][pack_id].get("conflicts_with", [])
        if other in selected
    }
    # A choice the team recorded stays in force when the catalog stops declaring the conflict.
    recorded = {
        tuple(sorted((first, second)))
        for item in profile.get("resolutions", [])
        for first in item["packs"]
        for second in item["packs"]
        if first != second and {first, second} <= set(selected)
    }
    pairs = sorted(declared | recorded)
    conflicts = []
    for first, second in pairs:
        left, right = scopes.get(first), scopes.get(second)
        if left is None or right is None:
            shared = right if left is None else left
        else:
            shared = sorted(set(left) & set(right))
            if not shared:
                continue
        resolution = next(
            (item for item in profile.get("resolutions", []) if {first, second} <= set(item["packs"])), None
        )
        conflicts.append({"packs": [first, second], "scope": shared, "resolution": resolution})
    return conflicts


def _excluded_packs(profile: dict, catalog: dict) -> set[str]:
    excluded = set()
    for conflict in rule_conflicts(profile, catalog):
        resolution = conflict["resolution"]
        if resolution:
            excluded |= set(conflict["packs"]) - set(resolution["keep"])
    return excluded


def resolved_profile(profile: dict, catalog: dict) -> dict:
    excluded = _excluded_packs(profile, catalog) if profile.get("resolutions") else set()
    packs = [pack_id for pack_id in selected_packs(profile, catalog) if pack_id not in excluded]
    return {**profile, "packs": packs, "boards": profile["boards"] or sorted(catalog["boards"])}


def pack_provenance(profile: dict, catalog: dict) -> dict[str, list[str]]:
    """Explain why each pack is active: required, selected, from a pattern or as a dependency."""
    reasons: dict[str, list[str]] = {}

    def add(pack_id: str, reason: str) -> None:
        known = reasons.setdefault(pack_id, [])
        if reason in known:
            return
        known.append(reason)
        for dependency in catalog["packs"][pack_id].get("depends_on", []):
            add(dependency, f"dependency of {pack_id}")

    for pack_id in profile["packs"]:
        add(pack_id, "required by OpenGuildKit" if pack_id == "agent-workflow" else "selected")
    for pattern_id in pattern_ids(profile):
        origin = pattern_origin(catalog["patterns"][pattern_id], profile)
        for pack_id in catalog["patterns"][pattern_id]["packs"]:
            add(pack_id, f"pattern {pattern_id}" + (f" ({origin})" if origin else ""))
    return reasons


def pattern_origin(pattern: dict, profile: dict) -> str:
    """Why a selected pattern without a stack concerns the project: its sector, personal data or roles."""
    if is_stack_pattern(pattern):
        return ""
    reasons = condition_reasons(
        pattern, profile["sector"], profile.get("personal_data"), profile.get("people_decisions"))
    roles = [role for role in pattern["roles"] if role in profile.get("roles", [])]
    if roles:
        reasons.append(f"role {', '.join(roles)}")
    return "; ".join(reasons)


# Above this many rules, the preview warns. A rule is read by the agent and answered by every task it
# concerns, so the count is what a profile brings, whatever a given task is asked. The default selection
# of each of the thirty field-test teams, recomputed with the core methods of its roles and every norm it
# meets accepted, stays at or under 74 rules (a payments API with DORA, GDPR and PCI DSS: 62; a seven-role
# monorepo: 74), and the field called 77 rules and more too heavy: 80 flags what optional methods add on
# top of a regulated project's own baseline.
RULE_WARNING = 80


def _pattern_reason(pattern: dict, profile: dict) -> str:
    """Why a selected pattern applies, in one line: its stack, sector, personal data, core role, or a decision."""
    adopted = [change for change in profile.get("changes", []) if change["change"] == f"adopt {pattern['id']}"]
    if adopted:
        last = adopted[-1]
        return f"adopted by {last['by']} on {last['on']}: {last['reason']}"
    if is_stack_pattern(pattern):
        return "stack " + ", ".join(" / ".join(group) for group in pattern["match"]["stack"])
    conditions = condition_reasons(pattern, profile["sector"], profile.get("personal_data"),
                                   profile.get("people_decisions"))
    if conditions:
        return "; ".join(conditions)
    core = core_roles(pattern, profile.get("roles", []))
    return f"role {', '.join(core)} (core method)" if core else "chosen by the team"


def regulation_demands(pattern: dict, catalog: dict) -> str:
    """One sentence saying what a regulation asks of each task: rules to answer, evidence to supply, checks run."""
    packs = pack_rule_counts(pattern["packs"], catalog)
    rules = [rule for pack_id in packs for rule in catalog["packs"][pack_id]["rules"]]
    evidence = [item["title"] for rule in rules for item in rule.get("evidence", [])]
    machine = sum(1 for rule in rules if rule_check(rule) is not None)
    text = f"{len(rules)} rules, asked of a task whose data or concerns it touches"
    if evidence:
        text += f"; such a task supplies or declares not applicable: {'; '.join(evidence)}"
    if machine:
        text += f"; task verify runs {machine} automatic check{'s' if machine > 1 else ''}"
    return text + "."


def rule_plan(profile: dict, catalog: dict) -> dict:
    """Everything init or sync would write, with the origin and scope of each pack, the patterns with their
    reason and rule count, what each regulation asks of a task, and the recorded profile decisions."""
    resolved = resolved_profile(profile, catalog)
    scopes = pack_scopes(profile, catalog)
    provenance = pack_provenance(profile, catalog)
    selected = selected_packs(profile, catalog)
    patterns = [catalog["patterns"][pattern_id] for pattern_id in pattern_ids(profile)]
    count = sum(len(catalog["packs"][pack_id]["rules"]) for pack_id in resolved["packs"])
    return {
        "rule_count": count,
        "rule_warning": (
            f"{count} rules in force. A task is asked only the rules that concern it, but each pattern adds rules "
            f"to read and to answer: above {RULE_WARNING}, check that each pattern below concerns the project and "
            "decline the others (openguildkit profile decline PATTERN --by NAME --reason WHY)."
            if count > RULE_WARNING else None
        ),
        "patterns": [
            {"id": pattern["id"], "title": pattern["title"], "reason": _pattern_reason(pattern, profile),
             "rules": pattern_rules(pattern, catalog)}
            for pattern in patterns
        ],
        "regulations": [
            {"id": pattern["id"], "title": pattern["title"], "asks": regulation_demands(pattern, catalog)}
            for pattern in patterns if pattern.get("kind") == "regulation"
        ],
        "declined": [entry if isinstance(entry, dict) else {"id": entry} for entry in profile.get("declined", [])],
        "changes": profile.get("changes", []),
        "packs": [
            {
                "id": pack_id,
                "title": catalog["packs"][pack_id]["title"],
                "version": catalog["packs"][pack_id]["version"],
                "provenance": provenance.get(pack_id, []),
                "scope": scopes.get(pack_id),
                "rules": [rule["id"] for rule in catalog["packs"][pack_id]["rules"]],
            }
            for pack_id in resolved["packs"]
        ],
        "excluded": [pack_id for pack_id in selected if pack_id not in resolved["packs"]],
        "conflicts": rule_conflicts(profile, catalog),
        "conventions": profile.get("conventions", []),
        "checks": profile.get("checks", []),
    }


def require_resolved_conflicts(profile: dict, catalog: dict) -> None:
    open_conflicts = [conflict for conflict in rule_conflicts(profile, catalog) if conflict["resolution"] is None]
    if open_conflicts:
        names = "; ".join(" and ".join(conflict["packs"]) for conflict in open_conflicts)
        # During init the profile is still the answers file: .openguildkit/project.json does not exist yet.
        raise ValueError(
            f"Conflicting rule packs: {names}. Keep only one of them, or record which apply in \"resolutions\" of "
            "the profile (the file passed to init --answers, or .openguildkit/project.json once the project is set "
            'up), for example {"packs": ["first", "second"], "keep": ["second"], "reason": "Why"}. '
            "Run openguildkit preview --answers FILE to check it."
        )


def pack_scopes(profile: dict, catalog: dict) -> dict[str, list[str] | None]:
    """Map each resolved pack to the components it applies to, or None for the whole project."""
    scopes: dict[str, set[str] | None] = {}

    def apply(pack_id: str, scope: set[str] | None) -> None:
        current = scopes.get(pack_id, set())
        merged = None if current is None or scope is None else current | scope
        if pack_id in scopes and merged == current:
            return
        scopes[pack_id] = merged
        for dependency in catalog["packs"][pack_id].get("depends_on", []):
            apply(dependency, merged)

    for pack_id in profile["packs"]:
        apply(pack_id, None)
    for entry in profile.get("patterns", []):
        pattern_id, components = pattern_selection(entry)
        for pack_id in catalog["patterns"][pattern_id]["packs"]:
            apply(pack_id, set(components) if components else None)
    return {pack_id: (sorted(scope) if scope is not None else None) for pack_id, scope in scopes.items()}


def _without_dates(record: dict) -> dict:
    """The record without its sources' checked dates: a page read again does not change the advice."""
    sources = [{key: value for key, value in source.items() if key != "checked"} for source in record.get("sources", [])]
    return {**record, "sources": sources} if "sources" in record else record


def task_scope_profile(profile: dict, catalog: dict, component_ids: list[str]) -> dict:
    """Resolve the project rules for all components or the ones named in the task answers."""
    resolved = resolved_profile(profile, catalog)
    if not component_ids:
        return resolved
    selected = set(component_ids)
    components = [component for component in resolved.get("components", []) if component["id"] in selected]
    available = {component["id"] for component in resolved.get("components", [])}
    if unknown := selected - available:
        raise ValueError(f"Unknown task components: {', '.join(sorted(unknown))}. "
                         f"Use project component IDs: {', '.join(sorted(available)) or 'none'}.")
    scopes = pack_scopes(profile, catalog)
    resolved["packs"] = [
        pack for pack in resolved["packs"] if scopes.get(pack) is None or selected.intersection(scopes[pack])
    ]
    patterns = []
    for entry in resolved.get("patterns", []):
        pattern, scope = pattern_selection(entry)
        if not scope:
            patterns.append(entry)
        elif scoped := [name for name in scope if name in selected]:
            patterns.append({"id": pattern, "components": scoped})
    resolved["checks"] = [command for command in resolved.get("checks", [])
                          if check_component(command, resolved.get("components", [])) in (None, *selected)]
    resolved["components"] = components
    resolved["stack"] = list(dict.fromkeys(technology for component in components for technology in component["stack"]))
    resolved["patterns"] = patterns
    return resolved


_CHECK_FOLDER = re.compile(r"""\s*cd\s+("[^"]+"|'[^']+'|[^\s;&|]+)\s*&&""")


def check_component(command: str, components: list[dict]) -> str | None:
    """The component a check command runs in, from its leading `cd FOLDER &&` as init proposes it, or None when it
    runs for the whole project. A folder inside a component belongs to it; the deepest component wins."""
    match = _CHECK_FOLDER.match(command)
    if not match:
        return None
    folder = PurePosixPath(match.group(1).strip("\"'").replace("\\", "/")).as_posix().strip("/")
    owners = [(len(path), component["id"]) for component in components
              for path in [PurePosixPath((component.get("path") or "").strip()).as_posix().strip("/")]
              if path not in ("", ".") and (folder == path or folder.startswith(path + "/"))]
    return max(owners)[1] if owners else None


# Profile fields that change neither the rules, nor the checks, nor the boards of a task: changing one leaves every
# approval standing. A convention or a tool reaches the next consultations; the guard, host, research, approval and
# waiver settings are read when they act (the signature, for one, is verified again by every reader of an approval).
APPROVAL_NEUTRAL_FIELDS = ("name", "conventions", "tools", "host", "guard", "research", "approval", "waivers")


def _advice_profile(profile: dict, neutral: tuple = ()) -> dict:
    """The profile without its decision history, and without the neutral fields given: who declined or changed
    what does not change the advice."""
    advice = {key: value for key, value in profile.items() if key != "changes" and key not in neutral}
    if "declined" in advice:
        advice["declined"] = declined_ids(profile)
    return advice


def profile_fingerprint(profile: dict, catalog: dict, *, legacy: bool = False) -> str:
    """The digest of what an approval rests on: the rules, the checks and the boards of the profile.

    legacy gives the digest of releases before 0.17, which covered every field; approvals recorded under it hold
    while the profile has not changed since (fingerprint_holds).
    """
    neutral = () if legacy else APPROVAL_NEUTRAL_FIELDS
    resolved = resolved_profile(_advice_profile(profile, neutral), catalog)
    snapshot = {
        "profile": resolved,
        "packs": [_without_dates(catalog["packs"][pack_id]) for pack_id in resolved["packs"]],
        "boards": [_without_dates(catalog["boards"][board_id]) for board_id in resolved["boards"]],
        "sector": _without_dates(catalog["sectors"][resolved["sector"]]),
    }
    if profile.get("patterns"):
        snapshot["patterns"] = [
            {key: value for key, value in _without_dates(catalog["patterns"][pattern_id]).items() if key != "core_for"}
            for pattern_id in pattern_ids(profile)
        ]
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Fingerprints:
    """The current fingerprint of a profile, and the earlier releases' one computed only when a record needs it."""

    def __init__(self, profile: dict, catalog: dict):
        self.profile, self.catalog = profile, catalog
        self.current = profile_fingerprint(profile, catalog)
        self._legacy = None

    def holds(self, recorded: str | None) -> bool:
        """Whether rules recorded under this fingerprint are still the rules, checks and boards of the profile."""
        if recorded == self.current:
            return True
        if self._legacy is None:
            self._legacy = profile_fingerprint(self.profile, self.catalog, legacy=True)
        return recorded == self._legacy


def fingerprint_holds(recorded: str | None, profile: dict, catalog: dict) -> bool:
    """Whether a fingerprint recorded with an approval still matches the rules, checks and boards of the profile."""
    return Fingerprints(profile, catalog).holds(recorded)


def _bullets(values: list[str]) -> list[str]:
    return ["- " + value.replace("\n", "\n  ") for value in values]


CHECK_VERIFICATION = "OpenGuildKit evaluates the check: task verify in the project, ci-check on a commit."


def rule_text(rule: dict) -> tuple[str, str]:
    """The rule's instruction and verification; a machine check fills in the text a rule leaves out."""
    check = rule_check(rule)
    if check is None:
        return rule["instruction"], rule["verification"]
    return (
        rule.get("instruction", describe_check(check)),
        rule.get("verification", CHECK_VERIFICATION),
    )


def profile_decision_lines(profile: dict, catalog: dict) -> list[str]:
    """The declined patterns and the patterns adopted by a command, with who, when and why when recorded."""
    lines = []
    for entry in profile.get("declined", []):
        if isinstance(entry, dict):
            lines.append(f"Declined `{entry['id']}` by {entry['by']} on {entry['on']}: {entry['reason']}. "
                         "It is not active; the person can adopt it again with openguildkit profile adopt.")
        else:
            lines.append(f"Declined `{entry}` before declines recorded who and why. It is not active.")
    for change in profile.get("changes", []):
        verb, _, target = change["change"].partition(" ")
        if verb == "adopt" and target in pattern_ids(profile):
            lines.append(f"Adopted `{target}` by {change['by']} on {change['on']}: {change['reason']}.")
    return lines


def render_instructions(profile: dict, catalog: dict) -> str:
    require_resolved_conflicts(profile, catalog)
    resolved = resolved_profile(profile, catalog)
    sector = catalog["sectors"][profile["sector"]]
    lines = [
        "## OpenGuildKit",
        "",
        f"Project: {profile['name']}",
        f"Sector: {sector['title']}",
        f"Stack: {', '.join(profile['stack']) or 'See the project files.'}",
        f"Research policy: `{profile['research']}`",
        *([f"Host agent: `{profile['host']}`"] if profile.get("host") else []),
        "",
        *_bullets(sector["context"]),
        "",
        *AGENT_WORKFLOW.strip().splitlines(),
    ]
    components = {component["id"]: component for component in profile.get("components", [])}

    def scope_text(scope: list[str] | None) -> str:
        names = [
            f"`{component_id}` ({components[component_id]['path']})" if components[component_id].get("path")
            else f"`{component_id}`"
            for component_id in scope or []
        ]
        return ", ".join(names)

    if components:
        lines.extend(["", "### Components", ""])
        for component in components.values():
            location = f" in `{component['path']}`" if component.get("path") else ""
            lines.append(f"- `{component['id']}`{location}: {', '.join(component['stack'])}")
    if profile.get("patterns"):
        lines.extend(["", "### Selected patterns", ""])
        for entry in profile["patterns"]:
            pattern_id, scope = pattern_selection(entry)
            pattern = catalog["patterns"][pattern_id]
            packs = ", ".join(f"`{pack_id}`" for pack_id in pattern["packs"])
            where = f" Applies to {scope_text(scope)}." if scope else ""
            lines.append(f"- {pattern['title']} (`{pattern_id}`) uses {packs}.{where}")
    decisions = profile_decision_lines(profile, catalog)
    if decisions:
        lines.extend(["", "### Profile decisions", "", *_bullets(decisions)])
    applied = [conflict for conflict in rule_conflicts(profile, catalog) if conflict["resolution"]]
    if applied:
        lines.extend(["", "### Rule decisions", ""])
        for conflict in applied:
            resolution = conflict["resolution"]
            kept = ", ".join(f"`{pack_id}`" for pack_id in resolution["keep"])
            dropped = [pack_id for pack_id in conflict["packs"] if pack_id not in resolution["keep"]]
            verb = "applies" if len(resolution["keep"]) == 1 else "apply"
            outcome = (
                f"{kept} {verb} instead of {', '.join(f'`{pack_id}`' for pack_id in dropped)}" if dropped
                else f"{kept} both apply"
            )
            lines.append(f"- {outcome}. Reason: {resolution['reason']}")
    if profile.get("approval", {}).get("mode") == "signed":
        lines.extend(["", "### Signed approvals", ""])
        lines.append(
            f"Approvals must be signed by {', '.join(profile['approval']['approvers'])} with a key listed in "
            f"`{profile['approval']['allowed_signers']}`."
        )
    if profile.get("waivers"):
        lines.extend(["", "### Waivers", ""])
        lines.append(
            f"Only {', '.join(profile['waivers']['allowed_by'])} can waive a blocker, "
            f"for up to {profile['waivers']['max_days']} days."
        )
    if profile.get("guard", "off") != "off":
        lines.extend(["", "### Board guard", ""])
        lines.append(
            "Every change goes through an approved task. "
            + ("Edits without one are refused." if profile["guard"] == "enforce" else "Edits without one are flagged.")
        )
    if profile.get("required_boards"):
        lines.extend(["", "### Required reviews", ""])
        lines.append(
            "Every consultation includes these boards: "
            + ", ".join(f"`{board_id}`" for board_id in profile["required_boards"]) + "."
        )
    for title, field in (("Team conventions", "conventions"), ("Project checks", "checks")):
        if profile[field]:
            lines.extend(["", f"### {title}", "", *_bullets(profile[field])])
    scopes = pack_scopes(profile, catalog) if components else {}
    lines.extend(["", "### Rule packs", "", *RULE_PACKS_NOTE.splitlines()])
    for pack_id in resolved["packs"]:
        pack = catalog["packs"][pack_id]
        lines.extend(["", f"#### {pack['title']} (`{pack_id}@{pack['version']}`)", ""])
        if scopes.get(pack_id):
            lines.append(f"Applies to {scope_text(scopes[pack_id])}.")
        if "policy_commit" in pack:
            lines.append(f"Policy commit: `{pack['policy_commit']}`")
        lines.append(", ".join(f"`{rule['id']}`" for rule in pack["rules"]))
    stamp = f"{profile_fingerprint(profile, catalog)} layout {INSTRUCTIONS_LAYOUT}"
    lines.extend(["", f"<!-- openguildkit profile {stamp} -->"])
    return "\n".join(lines)


_MARKER_LINE = re.compile("(" + re.escape(BEGIN) + "|" + re.escape(END) + r")[ \t]*")
_IMPORT_LINE = re.compile(r"[ \t]*(@AGENTS\.md|@\./AGENTS\.md)[ \t]*")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
BOM = "\ufeff"


def _scan_markers(text: str, line_pattern: re.Pattern = _MARKER_LINE) -> tuple[list[tuple[str, int, int]], int | None]:
    """Find the lines the pattern matches (the markers) outside fenced code blocks, and the line of a fence the
    text leaves open."""
    found, fence, opened, offset = [], None, None, 0
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        content = line.rstrip("\r\n")
        opening = _FENCE.match(content)
        if fence is None and opening:
            fence, opened = opening.group(1), number
        elif fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence) \
                    and not content[opening.end():].strip():
                fence = None
        else:
            match = line_pattern.fullmatch(content)
            if match:
                found.append((match.group(1), offset, offset + len(content)))
        offset += len(line)
    return found, opened if fence is not None else None


def _marker_positions(text: str) -> list[tuple[str, int, int]]:
    """Find the OpenGuildKit markers that stand on their own line outside fenced code blocks."""
    return _scan_markers(text)[0]


def managed_block_lines(text: str) -> tuple[int, int] | None:
    """The first and last line (counted from 1, markers included) of the block OpenGuildKit manages, or None when the
    text has no block or malformed markers."""
    matches = _marker_positions(text)
    if [kind for kind, _, _ in matches] != [BEGIN, END]:
        return None
    return text.count("\n", 0, matches[0][1]) + 1, text.count("\n", 0, matches[1][2]) + 1


def merged_instructions(current: str, generated: str, label: str = "AGENTS.md") -> str:
    """Replace the managed block in an instructions file, or append it, keeping the rest unchanged."""
    newline = "\r\n" if "\r\n" in current else "\n"
    if any(_MARKER_LINE.fullmatch(line.strip()) for line in generated.splitlines()):
        raise ValueError("Project instructions contain a reserved OpenGuildKit marker.")
    matches, open_fence = _scan_markers(current)
    block = newline.join([BEGIN, generated.replace("\n", newline), END])
    if not matches:
        if open_fence is not None:
            # Appending would put the rules inside the code block, and each sync would add another copy.
            raise ValueError(f"{label} ends inside an unclosed code block at line {open_fence}. Close it and retry.")
        separator = newline if current.endswith(newline) else newline * 2
        return current + (separator if current else "") + block + newline
    if [kind for kind, _, _ in matches] != [BEGIN, END]:
        raise ValueError(f"{label} has malformed OpenGuildKit markers. Repair the marked block and retry.")
    return current[:matches[0][1]] + block + current[matches[1][2]:]


_FINGERPRINT_LINE = re.compile(r"<!-- openguildkit profile [0-9a-f]{64}(?: layout \d+)? -->")


def hand_edits(current: str, generated: str) -> list[str]:
    """The lines a person changed in the managed block: lines it holds that the generated block lacks, when the
    block still carries the same profile fingerprint (otherwise the profile or catalog changed, not a person)."""
    matches = _marker_positions(current)
    if [kind for kind, _, _ in matches] != [BEGIN, END]:
        return []
    block = current[matches[0][2]:matches[1][1]].replace("\r\n", "\n")
    stamp = _FINGERPRINT_LINE.search(block)
    if stamp is None or stamp.group(0) not in generated:
        return []
    expected = set(generated.splitlines())
    return [line.strip() for line in block.splitlines() if line.strip() and line not in expected]


def _read_instructions(path: Path) -> tuple[str, bool]:
    """Read an instructions file and report whether it starts with a UTF-8 byte order mark."""
    if path.is_symlink():
        raise ValueError(f"Refusing a symbolic link as project instructions: {path}")
    if not path.exists():
        return "", False
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{path.name} is not UTF-8 (byte {error.start + 1}): convert it to UTF-8 and retry.") from error
    return (text[1:], True) if text.startswith(BOM) else (text, False)


def _instruction_text(path: Path) -> str:
    return _read_instructions(path)[0]


def _claude_links_to_agents(root: Path) -> bool:
    """A CLAUDE.md that is a symbolic link to the project's AGENTS.md already carries the rules."""
    claude, agents = root / "CLAUDE.md", root / "AGENTS.md"
    if not claude.is_symlink():
        return False
    try:
        return claude.resolve(strict=True) == agents.resolve(strict=True) and not agents.is_symlink()
    except OSError:
        return False


def _claude_instructions(current: str) -> str:
    standalone_import = bool(_scan_markers(current, _IMPORT_LINE)[0])
    if not _marker_positions(current) and standalone_import:
        return current
    return merged_instructions(current, "@AGENTS.md", "CLAUDE.md")


def sync_instructions(root: Path, profile: dict, catalog: dict) -> list[str]:
    """Write the managed instructions; returns the lines a person had edited in the block, which it replaces."""
    state = state_path(root)
    instructions = root / "AGENTS.md"
    current, bom = _read_instructions(instructions)
    generated = render_instructions(profile, catalog)
    replaced = hand_edits(current, generated)
    updated = merged_instructions(current, generated)
    claude = root / "CLAUDE.md"
    linked = _claude_links_to_agents(root)
    if not linked:
        current_claude, claude_bom = _read_instructions(claude)
        updated_claude = _claude_instructions(current_claude)
    ignore = state / ".gitignore"
    previous_ignore = _instruction_text(ignore)
    missing = [entry for entry in PROJECT_IGNORE.splitlines() if entry not in previous_ignore.splitlines()]
    if missing:
        separator = "\n" if previous_ignore and not previous_ignore.endswith("\n") else ""
        write_text(ignore, previous_ignore + separator + "\n".join(missing) + "\n")
    write_text(instructions, (BOM if bom else "") + updated)
    if not linked:
        write_text(claude, (BOM if claude_bom else "") + updated_claude)
    return replaced


def initialize(root: Path, state: Path, profile: dict, catalog: dict) -> None:
    path = state / "project.json"
    if path.exists():
        raise ValueError(ALREADY_INITIALIZED)
    sync_instructions(root, profile, catalog)
    write_json(path, profile)


class RuleError(ValueError):
    """A problem `check` reports under a rule of docs/sarif.md.

    `code` is the rule's stable code, None when the findings were already reported one by one; `files` are the files
    the problem concerns, relative to the project root. The message is the one the command prints.
    """

    def __init__(self, message: str, code: str | None, files: tuple[str, ...] | list[str] = ()):
        super().__init__(message)
        self.code = code
        self.files = tuple(files)


def _outdated(test) -> bool:
    try:
        return bool(test())
    except ValueError:
        return False  # A file that cannot be merged is reported by its own message, not listed here.


def _outdated_files(generated: str, current: str, claude: str, linked: bool, ignore: str) -> list[str]:
    """The instructions files that no longer match the profile, for the finding that names them."""
    checks = (
        ("AGENTS.md", lambda: current != merged_instructions(current, generated)),
        ("CLAUDE.md", lambda: not linked and claude != _claude_instructions(claude)),
        (f"{STATE_DIR}/.gitignore", lambda: not set(PROJECT_IGNORE.splitlines()).issubset(ignore.splitlines())),
    )
    return [name for name, test in checks if _outdated(test)]


def check_instructions(root: Path, profile: dict, catalog: dict) -> None:
    current = _instruction_text(root / "AGENTS.md")
    linked = _claude_links_to_agents(root)
    claude = "" if linked else _instruction_text(root / "CLAUDE.md")
    ignore = _instruction_text(state_path(root) / ".gitignore")
    generated = render_instructions(profile, catalog)
    edited = hand_edits(current, generated)
    if edited:
        raise RuleError(
            f"The OpenGuildKit block of AGENTS.md was edited by hand ({len(edited)} line(s), first: {edited[0][:80]}). "
            "openguildkit sync replaces the block: move your own text outside the markers first.",
            "instructions-edited", ["AGENTS.md"],
        )
    if (
        current != merged_instructions(current, generated)
        or (not linked and claude != _claude_instructions(claude))
        or not set(PROJECT_IGNORE.splitlines()).issubset(ignore.splitlines())
    ):
        raise RuleError("OpenGuildKit instructions are out of date. Run openguildkit sync.", "instructions-drift",
                        _outdated_files(generated, current, claude, linked, ignore))
