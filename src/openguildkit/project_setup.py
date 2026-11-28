"""The setup questionnaire of init and the completion of its answers into a profile."""

import json

from .clock import today
from .doc_links import doc_link
from .patterns import pattern_selection, recommend_patterns, role_choices, technology_key
from .project import (
    catalog_ids,
    decision_record,
    declined_entries,
    default_packs,
    pattern_entries,
    project_context,
    recommendation_inputs,
    validate_profile,
)


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
    ("gemini-cli", "Gemini CLI"),
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
            "installed, and leave to CI a check that needs the network or a service "
            f"({doc_link('docs/workflow.md', 'project-checks')})."
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
    "host": "The AI coding assistant the team uses in the project, such as Claude Code, Codex or Gemini CLI.",
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
            answers[pattern_id] = {"id": pattern_id, **decision_record({**answer, "on": today().isoformat()},
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
    sector, stack, roles, components = project_context(answers, catalog)
    inputs = recommendation_inputs(answers, catalog)
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
        earlier = declined_entries(completed.get("declined", []), catalog)
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
            'Add this line to the answers file, "yes" for a norm that applies, or {"answer": "no", "by": "NAME", '
            f'"reason": "WHY"}} to decline it: "norms": {json.dumps({entry["id"]: "yes" for entry in missing})}. '
            "Nothing was written."
        )
    replace = completed.pop("replace_default_packs", False)
    if not isinstance(replace, bool):
        raise ValueError("replace_default_packs must be true or false")
    sector, stack, roles, components = project_context(completed, catalog)
    if "patterns" not in completed:
        inputs = recommendation_inputs(completed, catalog)
        completed["patterns"] = [
            {"id": record["id"], "components": record["components"]} if record.get("components") else record["id"]
            for record in recommend_patterns(catalog, stack, sector, roles, components, **inputs)["matched"]
        ]
    patterns = pattern_entries(completed["patterns"], catalog, components)
    selected = {pattern_selection(entry)[0] for entry in patterns}
    completed["patterns"] = [*(pattern_id for pattern_id in kept_norms if pattern_id not in selected), *patterns]
    chosen = catalog_ids(completed.get("packs", []), "packs", catalog["packs"])
    if not replace:
        chosen = [*default_packs(stack, components, completed["patterns"], catalog), *chosen]
    completed["packs"] = list(dict.fromkeys(chosen))
    return validate_profile(completed, catalog), left_aside


