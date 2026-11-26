"""The task questionnaire: its questions and follow-ups, what each answer means, and the check of the answers a
consultation records."""


_QUESTIONS = (
    (
        "kind",
        "What are you asking the team to do?",
        (
            ("feature", "Build a feature"),
            ("bug", "Fix a defect"),
            ("maintenance", "Maintain or refactor existing work"),
            ("decision", "Make a recommendation"),
            ("other", "Other (describe in context)"),
            ("unsure", "Unsure"),
        ),
    ),
    (
        "surface",
        "Which areas will this task affect? Select every area that applies.",
        (
            ("customer", "Customer-facing experience"),
            ("service", "Backend service or data flow"),
            ("infrastructure", "Infrastructure or deployment"),
            ("business", "Business process or deliverable"),
            ("other", "Other (describe in context)"),
            ("unsure", "Unsure"),
        ),
    ),
    (
        "data",
        "What is the most sensitive data this task may access or change?",
        (
            ("none", "No data or public data only"),
            ("internal", "Internal company data"),
            ("personal", "Personal data"),
            ("regulated", "Regulated or restricted data"),
            ("unsure", "Unsure"),
        ),
    ),
    (
        "research",
        "What evidence can the boards consult?",
        (
            ("local", "Project files and sources already provided"),
            ("public", "Project files and public sources, if the project permits"),
            ("unsure", "Unsure"),
        ),
    ),
)


# Required for a new consultation (task consult and task route refuse answers without it, see
# require_concerns); a task consulted before it existed keeps its recorded answers. Each concern routes by
# itself, even when the brief has none of the boards' trigger words; unsure routes every topic's boards.
_OPTIONAL_QUESTIONS = (
    (
        "concerns",
        "Does the task involve any of these (select every one that applies, none, or unsure)?",
        (
            ("money", "Prices, payments, invoices, payroll or spending"),
            ("ai", "An AI model or LLM that produces answers or content"),
            ("people-decisions", "Software that scores, ranks or decides about individual people "
                                 "(hiring, credit, price per person)"),
            ("credentials", "Secrets, keys, tokens or passwords"),
            ("none", "None of these"),
            ("unsure", "Unsure"),
        ),
    ),
)


EXCLUSIVE_CONCERNS = ("none", "unsure")


MULTIPLE = {"surface", "concerns"}


FOLLOW_UPS = ("outcome", "affected", "options")


# The working assumptions made while scoping, kept apart from the confirmed answers: a list of sentences, optional.
ASSUMPTIONS = "assumptions"


SHORT_BRIEF_WORDS = 8


def _choice_question(question_id: str, prompt: str, choices) -> dict:
    question = {
        "id": question_id,
        "prompt": prompt,
        "choices": [{"id": choice_id, "label": label} for choice_id, label in choices],
    }
    if question_id in MULTIPLE:
        question["type"] = "multi-select"
    return question


def _follow_up_questions(answers: dict) -> list[dict]:
    """Questions that depend on the kind and impact of the change."""
    kind = answers.get("kind") if isinstance(answers.get("kind"), str) else None
    surfaces = [item for item in as_list(answers.get("surface")) if isinstance(item, str)]
    questions = []
    outcome_prompts = {
        "feature": "What observable result shows that the feature works?",
        "bug": "What should happen instead, and how can someone reproduce the defect?",
        "maintenance": "What must keep working, and how will you check it after the change?",
        "other": "What observable result shows that the task is done?",
        "unsure": "What would you like to be different once this task is done?",
    }
    if kind in outcome_prompts:
        questions.append({"id": "outcome", "type": "text", "prompt": outcome_prompts[kind],
                          "essential": kind in ("feature", "bug", "unsure")})
    customer_facing = bool({"customer", "business"} & set(surfaces))
    sensitive = answers.get("data") in ("personal", "regulated")
    if kind in ("feature", "decision", "unsure", "other") or customer_facing or sensitive:
        questions.append({"id": "affected", "type": "text",
                          "prompt": "Who is affected: which users, customers, teams or partners?",
                          "essential": customer_facing or kind == "unsure"})
    if kind == "decision":
        questions.append({"id": "options", "type": "text",
                          "prompt": "Which options are on the table, and what would make you choose one?",
                          "essential": True})
    # While the outcome or who is affected stays empty, what is assumed instead is worth writing down.
    if any(question["id"] in ("outcome", "affected") and not answers.get(question["id"]) for question in questions):
        questions.append({"id": ASSUMPTIONS, "type": "list", "essential": False,
                          "prompt": "What are you assuming that nobody has confirmed yet, one sentence each?"})
    return questions


def task_questions(brief: str, answers: dict | None = None) -> list[dict]:
    """Return the questionnaire. With partial answers, add the follow-up questions they call for."""
    if not brief.strip():
        raise ValueError("A task brief is required.")
    questions = [
        _choice_question(question_id, prompt, choices)
        for question_id, prompt, choices in (*_QUESTIONS, *_OPTIONAL_QUESTIONS)
    ]
    if answers:
        questions.extend(_follow_up_questions(answers))
    questions.append(
        {
            "id": "context",
            "type": "text",
            "prompt": "What acceptance criteria, constraints or other context should the boards know?",
            "default": "",
        }
    )
    return [{**question, **TASK_QUESTION_HELP.get(question["id"], {})} for question in questions]


# One line per task question in plain words, and what an "I don't know" answer does, as init --questions has.
TASK_QUESTION_HELP = {
    "kind": {"help": "Whether you want something new, a repair, upkeep of what exists, or advice before deciding.",
             "unsure": "unsure: the project-management board joins to help frame the task"},
    "surface": {"help": "Which part of the product the change touches: what customers see, the server side, the "
                        "hosting, or a business process.",
                "unsure": "unsure: every specialist lens of the boards stays in the review"},
    "data": {"help": "The most private information the change may read or change, such as emails or health data.",
             "unsure": "unsure: treated like personal data, so the security board joins and the GDPR evidence is asked"},
    "research": {"help": "Whether the boards may cite public web pages, or only the project's files and what you gave.",
                 "unsure": "unsure: counts as local, so only the project's files and the sources you gave"},
    "concerns": {"help": "Topics that bring their own specialists: money, AI, decisions about people, secrets.",
                 "unsure": "unsure: the boards of every topic join, and the rules of every topic stay open"},
    "outcome": {"help": "What someone can see or measure once the work is done.",
                "unsure": "leave it empty: the consultation lists the missing outcome as an open point"},
    "affected": {"help": "The people or teams who will notice the change.",
                 "unsure": "leave it empty: the consultation lists it as an open point"},
    "options": {"help": "The choices being compared, and what would tip the decision.",
                "unsure": "leave it empty: the consultation lists it as an open point"},
    "assumptions": {"help": "What scoping takes for granted unconfirmed: shown apart before deciding, and any board "
                            "can contest one.",
                    "unsure": "leave it empty: nothing is recorded as assumed"},
    "context": {"help": "Anything the boards should know: deadlines, limits, acceptance criteria, links.",
                "unsure": "the default: empty"},
}


def as_list(value) -> list:
    """An answer as a list: a multi-select answer is one already, a single answer becomes one item, none is empty."""
    return value if isinstance(value, list) else [value] if value is not None else []


def _optional_answers(answers: dict) -> dict:
    """Check the optional multi-select answers that are present; an absent one stays absent."""
    validated = {}
    for question_id, _, choices in _OPTIONAL_QUESTIONS:
        if question_id not in answers:
            continue
        allowed = [choice_id for choice_id, _ in choices]
        selected = as_list(answers[question_id])
        if any(item not in allowed for item in selected) or len(set(selected)) != len(selected):
            raise ValueError(f"Choose {question_id} values from {', '.join(allowed)}.")
        for alone in EXCLUSIVE_CONCERNS:
            if alone in selected and len(selected) > 1:
                raise ValueError(f"Choose {question_id} values or {alone}, not both.")
        validated[question_id] = selected
    return validated


def concerns_question() -> dict:
    """The concerns question as a follow-up to ask: its prompt, its choices and what unsure does."""
    question_id, prompt, choices = _OPTIONAL_QUESTIONS[0]
    return {**_choice_question(question_id, prompt, choices), **TASK_QUESTION_HELP[question_id]}


def require_concerns(answers: dict) -> None:
    """A new consultation needs the concerns answer, so that routing and the rules asked read the same topics.

    A task consulted before the question was required keeps its recorded answers: only new answers go through this.
    """
    if "concerns" in answers:
        return
    choices = ", ".join(choice["id"] for choice in concerns_question()["choices"])
    raise ValueError(f"Answer concerns, a list of the topics the task involves: choose from {choices}, for "
                     "example \"concerns\": [\"none\"]; unsure keeps every topic's rules open and consults its boards.")


def _assumptions(value: object) -> list[str]:
    """The working assumptions as sentences, in order and once each; an empty list records none."""
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError('Task assumptions must be a list of sentences, such as ["Requests are linked to accounts by '
                         'the customer ID."], or left out.')
    return list(dict.fromkeys(item.strip() for item in value))


def validate_answers(answers: dict) -> dict:
    """Normalize the scope answers from interactive or JSON input."""
    if not isinstance(answers, dict):
        raise ValueError("Task answers must be a JSON object.")

    validated = {}
    for question_id, _, choices in _QUESTIONS:
        allowed = [choice_id for choice_id, _ in choices]
        answer = answers.get(question_id)
        if question_id in MULTIPLE:
            selected = as_list(answer)
            if not selected or any(item not in allowed for item in selected) or len(set(selected)) != len(selected):
                raise ValueError(f"Choose one or more {question_id} values from {', '.join(allowed)}.")
            if "unsure" in selected and len(selected) > 1:
                raise ValueError(f"Choose {question_id} values or unsure, not both.")
            validated[question_id] = selected
            continue
        if answer not in allowed:
            raise ValueError(f"Choose {question_id} from {', '.join(allowed)}.")
        validated[question_id] = answer
    validated.update(_optional_answers(answers))
    if "components" in answers:
        selected = answers["components"]
        if not isinstance(selected, list) or not all(isinstance(item, str) and item.strip() for item in selected):
            raise ValueError("Task components must be a list of project component IDs.")
        validated["components"] = list(dict.fromkeys(item.strip() for item in selected))

    assumptions = _assumptions(answers.get(ASSUMPTIONS, []))
    if assumptions:
        validated[ASSUMPTIONS] = assumptions
    unknown = answers.keys() - validated.keys() - {"context", ASSUMPTIONS, *FOLLOW_UPS}
    if unknown:
        raise ValueError(f"Unknown task answer fields: {', '.join(sorted(unknown))}.")
    for field in ("context", *FOLLOW_UPS):
        value = answers.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"Task {field} must be text.")
        if value.strip():
            validated[field] = value.strip()
    chosen = [validated[key] for key in ("kind", "data", "research")] + validated["surface"]
    if "other" in chosen and not validated.get("context"):
        raise ValueError("Describe the answer marked 'other' in context.")
    return validated


def open_points(brief: str, answers: dict) -> list[str]:
    """Essential points still open before the boards review the task."""
    points = []
    words = len(brief.split()) + len(answers.get("context", "").split())
    if words < SHORT_BRIEF_WORDS:
        points.append("The brief is short. Describe the change, who needs it and why.")
    labels = {"kind": "the kind of work", "surface": "the affected areas", "data": "the most sensitive data",
              "research": "the evidence the boards can use"}
    for key, label in labels.items():
        if "unsure" in as_list(answers.get(key)):
            points.append(f"The requester is unsure about {label}.")
    for question in _follow_up_questions(answers):
        if question["essential"] and not answers.get(question["id"]):
            points.append(f"Unanswered: {question['prompt']}")
    return points


# What each surface answer means, for a sentence: "applies to tasks that touch the customer-facing experience".
SURFACE_MEANINGS = {
    "customer": "customer-facing experience", "service": "backend services or data flows",
    "infrastructure": "infrastructure or deployment", "business": "business processes or deliverables",
    # The concerns a lens can need, said the same way.
    "money": "prices, payments, invoices, payroll or spending", "ai": "AI models or LLMs",
    "people-decisions": "software that decides about individual people", "credentials": "secrets, keys or tokens",
}
