"""Route a task to the boards: read the brief and the answers (triggers, negations, concepts, audience and stack),
then apply the project's required boards and the requester's changes.

Routing changes with each edition of the catalog's triggers; the consultation (consultation.py) and the rest of
the workflow read its result.

Entry: normalize_text, normalize_with_offsets, trigger_pattern, scan_triggers, trigger_matches, task_concepts
Tests: tests/test_short_lane.py
"""

import re
import unicodedata
from functools import lru_cache

from . import lazy_re
from .questionnaire import FOLLOW_UPS, SURFACE_MEANINGS, as_list

_STRUCTURED_ROUTES = {
    "kind": {
        "feature": {
            "product": "Feature scope and outcome",
            "engineering": "Implementation and integration",
            "qa": "Acceptance and regression checks",
        },
        "bug": {
            "engineering": "Defect diagnosis and implementation",
            "qa": "Reproduction and regression checks",
        },
        "maintenance": {
            "engineering": "Maintainability and compatibility",
            "qa": "Regression checks",
        },
        "decision": {"product": "Options and decision criteria"},
        "unsure": {"project-management": "Task scope is open"},
    },
    "surface": {
        "customer": {
            "product": "Customer outcome",
            "design": "Customer experience",
            "marketing": "Customer expectations and market evidence",
        },
        "service": {
            "engineering": "Service boundaries",
            "performance": "Service performance and capacity",
        },
        "infrastructure": {
            "devops": "Infrastructure and deployment",
            "performance": "Capacity and runtime performance",
        },
        "business": {"project-management": "Owners and business dependencies"},
    },
    "data": {
        "internal": {"security": "Internal data access"},
        "personal": {
            "security": "Personal data access",
            "legal": "Lawful basis, notice and records for personal data",
        },
        "regulated": {
            "security": "Regulated or restricted data access",
            "legal": "Obligations attached to regulated data",
        },
        "unsure": {"security": "Data sensitivity is open"},
    },
}


# Data answers whose boards only the person approving can drop: they confirm it at the approval prompt.
PROTECTED_DATA = ("personal", "regulated", "unsure")


# What a task is about, recognised from an answer to the concerns question or from the brief: "terms"
# lists groups of phrases, and the concept applies when the text matches a phrase of every group.
_CONCEPTS = (
    {
        "id": "people-decisions",
        "reason": "Software scores, ranks or decides about individual people",
        "terms": (
            ("ai", "ia", "machine learning", "apprentissage automatique", "model", "modèle", "algorithm",
             "algorithme", "llm"),
            ("applicant", "candidate", "candidat", "candidature", "cv", "resume screening", "employee", "salarié",
             "worker", "loan", "prêt", "credit score", "credit scoring", "creditworthiness", "solvabilité",
             "personalised price", "personalized price", "personalized pricing", "prix personnalisé"),
        ),
        "boards": {
            "legal": "Automated decision about people: GDPR Art. 22 and AI Act Annex III classification",
            "data": "Model that scores people: evaluation, bias and monitoring",
            "security": "Model that scores people: access to the inputs and the scores",
        },
        "patterns": ("eu-ai-act-system",),
    },
    {
        "id": "ai",
        "reason": "The task builds or changes an AI system",
        "terms": (
            ("llm", "large language model", "chatbot", "generative ai", "genai", "ia générative", "ai assistant",
             "assistant ia", "ai agent", "agent ia", "gpt"),
        ),
        "boards": {
            "data": "AI system: evaluation before release and monitoring after",
            "security": "AI system: prompt injection, data leakage and misuse",
            "legal": "AI system: AI Act classification and transparency (Art. 50)",
        },
        "patterns": ("eu-ai-act-system",),
    },
    {
        "id": "money",
        "reason": "The task touches prices, payments, invoices, payroll or spending",
        "terms": (
            ("aws", "gcp", "azure", "cloud", "snowflake", "bigquery", "databricks", "datadog", "saas", "vendor",
             "fournisseur", "licence", "license"),
            ("spend", "spending", "bill", "invoice", "facture", "dépense"),
        ),
        "boards": {"finance": "Money: prices, payments, invoices, payroll or spending"},
        "patterns": (),
    },
    {
        "id": "credentials",
        "reason": "The task handles secrets, keys, tokens or passwords",
        "terms": (),
        "boards": {
            "security": "Secrets and credentials: storage, exposure and revocation",
            "devops": "Secrets and credentials: rotation without downtime",
        },
        "patterns": (),
    },
)


# Phrases that claim their words without selecting a board, so that a shorter trigger inside them does
# not fire: a "backend engineer" is a job title, not backend work, "en vue de" is not Vue and a worker that
# "reacts to" events is not React.
NEUTRAL_PHRASES = (
    "backend engineer", "back-end engineer", "backend developer", "back-end developer", "frontend engineer",
    "front-end engineer", "frontend developer", "front-end developer", "full-stack engineer",
    "full-stack developer", "développeur backend", "développeur frontend", "security engineer", "qa engineer",
    "en vue de", "point de vue", "vue sql", "react to", "react when",
)


NO_DISCIPLINE = (
    "No discipline recognised in the brief or the answers: initial scope review only. "
    "Add the boards that apply with --add BOARD --reason TEXT."
)


_APOSTROPHES = lazy_re.compile("[\u2019\u2018\u02bc\u00b4`]")


_SEPARATORS = lazy_re.compile(r"[/_|]")


_PLURAL = "(?:s|es|x)?"


_POSSESSIVE = "(?:'s)?"


def normalize_text(value: str) -> str:
    """Fold case, accents, apostrophes and spacing so that triggers match how people write."""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    folded = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(_SEPARATORS.sub(" ", _APOSTROPHES.sub("'", folded)).split())


# What normalize_text does to an ASCII character: the one apostrophe and the separators it folds.
_ASCII_FOLD = str.maketrans({"`": "'", "/": " ", "_": " ", "|": " "})


def normalize_with_offsets(value: str) -> tuple[str, list[int]]:
    """normalize_text, with the index in value of each character it returns, to quote the words as written."""
    pieces: list[tuple[str, int]] = []
    if value.isascii():  # No accent to drop and one character for one: fold the whole text at once.
        pieces = list(zip(value.lower().translate(_ASCII_FOLD), range(len(value)), strict=True))
    else:
        for index, character in enumerate(value):
            for piece in unicodedata.normalize("NFKD", character).casefold():
                if not unicodedata.combining(piece):
                    pieces.append((_SEPARATORS.sub(" ", _APOSTROPHES.sub("'", piece)), index))
    characters, offsets = [], []
    for piece, index in pieces:
        if piece.isspace():
            if characters and characters[-1] != " ":
                characters.append(" ")
                offsets.append(index)
            continue
        characters.append(piece)
        offsets.append(index)
    if characters and characters[-1] == " ":
        characters.pop()
        offsets.pop()
    return "".join(characters), offsets


@lru_cache(maxsize=None)
def _trigger_words(trigger: str) -> tuple[str, ...]:
    return tuple(normalize_text(trigger).split(" "))


@lru_cache(maxsize=None)
def trigger_pattern(trigger: str) -> re.Pattern:
    """Match a trigger as whole words, allowing a regular plural or a possessive on each word.

    Compiled once per process: the catalog holds more triggers than the re module caches, so reading each
    brief would otherwise compile them all again."""
    parts = [re.escape(word) + (_PLURAL if word[-1:].isalpha() else "") + _POSSESSIVE
             for word in _trigger_words(trigger)]
    return re.compile(r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])")


def _trigger_matches(trigger: str, normalized: str):
    """The matches of a trigger in a normalized text. A trigger matches only where each of its words is
    written, so a trigger with a word absent from the text is not compiled at all."""
    if not all(word in normalized for word in _trigger_words(trigger)):
        return ()
    return trigger_pattern(trigger).finditer(normalized)


# A trigger preceded in its clause, within NEGATION_WINDOW words, by one of these words is mentioned as
# excluded: "no payments", "without personal data", "sans paiement", "does not touch the API".
NEGATIONS = frozenset((
    "no", "not", "without", "never", "nor", "neither", "none", "nothing", "cannot",
    "sans", "pas", "aucun", "aucune", "aucuns", "aucunes", "ni", "jamais", "non", "rien",
))


NEGATION_WINDOW = 5


# A negation followed by one of these words does not exclude: "not only", "no more than", "sans doute".
_NOT_NEGATING_NEXT = frozenset((
    "only", "just", "merely", "longer", "more", "less", "matter", "doubt",
    "seulement", "uniquement", "simplement", "moins", "doute",
))


# "not without payments" and "pas sans paiement" say the opposite of "without payments".
_DOUBLE_NEGATION = (frozenset(("without", "sans")), frozenset(("not", "never", "pas", "jamais")))


# "Do not forget payments", "don't skip the payment step", "n'oubliez pas les paiements": a negated verb
# of omission asks for the subject, so the negation does not exclude it.
_OMISSIONS = frozenset((
    "forget", "forgets", "forgetting", "forgot", "skip", "skips", "skipping", "omit", "omits", "omitting",
    "miss", "misses", "missing", "ignore", "ignores", "ignoring", "neglect", "neglects", "neglecting",
    "overlook", "overlooks", "overlooking", "drop", "drops", "dropping", "lose", "loses", "losing",
    "oublier", "oubliez", "oublie", "oublies", "oublions", "omettre", "omettez", "omet", "omets", "omis",
    "negliger", "negligez", "neglige", "ignorer", "ignorez", "sauter", "sautez", "rater", "ratez",
    "manquer", "manquez", "perdre", "perdez",
))


# "Users must not exceed the budget", "ne pas dépasser le budget": a negated verb of limit keeps the subject in the
# task, as a constraint on it.
_LIMITS = frozenset((
    "exceed", "exceeds", "exceeding", "surpass", "surpasses", "overrun", "overruns", "overspend", "overspends",
    "breach", "breaches", "depasser", "depassez", "depasse", "depassent", "depassons",
))


# "Avoid" excludes only a change to the subject ("avoid any changes to the pricing page"), not the subject
# itself ("avoid double payments" is about payments).
_AVOID = frozenset(("avoid", "avoiding", "eviter", "evitez", "evite", "evitons"))


_CHANGE_WORDS = frozenset((
    "any", "change", "changes", "changing", "touch", "touching", "modify", "modifying", "modification",
    "modifications", "tout", "toute", "toucher", "modifier", "changer", "changement", "changements",
))


# "payments are out of scope", "paiements hors périmètre": a negation written after the subject.
_AFTER_NEGATION = lazy_re.compile(
    r"^(?:\S+\s+){0,2}?(?:out of scope|not in scope|outside the scope|hors (?:du )?(?:perimetre|scope|sujet)|"
    r"not (?:concerned|affected)|pas concernee?s?)(?![\w-])"
)


# Words that join the items of a list, so that "without touching personal data or secrets" excludes both.
_LIST_WORDS = frozenset((
    "or", "and", "nor", "the", "any", "a", "an", "ou", "et", "ni", "le", "la", "les", "l'", "de", "des", "du",
    "d'", "aux", "au",
))


# A clause ends at punctuation, a line break or a contrasting conjunction.
_CLAUSE_END = lazy_re.compile(r"[.,;:!?()\[\]{}\n\r\u2022\u2013\u2014]")


_CLAUSE_WORDS = frozenset(("but", "however", "yet", "although", "though", "whereas", "mais", "cependant"))


_QUOTE_WORDS = 3


# A quote does not end on one of these words: "payments are out of" becomes "payments are out of scope".
_TRAILING_WORDS = frozenset((
    "of", "the", "to", "a", "an", "and", "or", "for", "in", "on", "with", "at", "by", "from", "is", "are",
    "de", "la", "le", "les", "des", "du", "a", "et", "ou", "pour", "en", "dans", "sur", "avec", "un", "une",
    "au", "aux", "par", "est", "sont",
))


KEPT_AFTER_NEGATION = "kept: a clause that opens with \"without\" may name what is needed"


def _is_negation(word: str) -> bool:
    return word in NEGATIONS or word.endswith("n't")


def _bare(word: str) -> str:
    """A word without a leading elided article or pronoun: "n'omettez" reads as "omettez"."""
    return re.sub(r"^(?:n|d|l|qu|j|s|c|m|t)'", "", word)


def _clause_words(text: str, normalized: str, offsets: list[int], start: int) -> list[tuple[int, str]]:
    """The normalized words before start in its clause, with their position in normalized."""
    clause_start = max((match.end() for match in _CLAUSE_END.finditer(text, 0, offsets[start])), default=0)
    words = [(match.start(), match.group().strip("'\"\u00ab\u00bb\u201c\u201d"))
             for match in re.finditer(r"\S+", normalized[:start]) if offsets[match.start()] >= clause_start]
    cut = max((index + 1 for index, (_, word) in enumerate(words) if word in _CLAUSE_WORDS), default=0)
    return words[cut:]


# "Also ignore the competitors": an imperative "ignore" at the start of its clause sets its object aside.
_SET_ASIDE = frozenset(("ignore", "ignorer", "ignorez", "ignorons"))


_LEADING_WORDS = frozenset(("also", "just", "please", "simply", "then", "and", "now",
                            "aussi", "simplement", "puis", "et", "merci", "de", "svp"))


# A clause that opens with one of these, or with a French infinitive or imperative, is an instruction:
# "Sans les concurrents, ajouter le calcul des prix" sets the competitors aside.
_INSTRUCTIONS = frozenset((
    "add", "fix", "update", "change", "create", "remove", "delete", "build", "write", "implement", "show",
    "display", "move", "rename", "make", "set", "use", "keep", "compute", "calculate", "send", "store",
    "refactor", "migrate", "test", "check", "list", "export", "import", "document", "replace", "compare",
    "prepare", "plan",
))


_NOT_FRENCH_VERBS = frozenset((
    "notre", "votre", "entre", "autre", "contre", "outre", "premier", "dernier", "lettre", "titre", "ordre",
    "nombre", "membre", "offre", "centre", "filtre", "hier", "cher", "super", "user", "leur", "chez", "assez",
))


def _is_instruction(word: str, french: bool) -> bool:
    """An English imperative from a short list, or, after "sans", a French infinitive (-er, -ir, -re) or
    imperative (-ez)."""
    word = _bare(word)
    if not french:
        return word in _INSTRUCTIONS
    return len(word) >= 4 and word not in _NOT_FRENCH_VERBS and word.endswith(("er", "ir", "re", "ez")) \
        and word.isalpha()


def _opens_a_condition(text: str, offsets: list[int], clause_start: int, words_before: int, end: int,
                       french: bool = False) -> bool:
    """ "Without a payment, the order fails": a short clause that opens with without and goes on after a
    comma. In a list of exclusions ("no AI, without payments, no UI") the clauses around it are negated too."""
    following = text[offsets[end - 1] + 1:].lstrip()
    if words_before > 3 or not following.startswith(",") or not following[1:].strip():
        return False
    next_words = normalize_text(following[1:]).split()
    if next_words and _is_instruction(next_words[0], french):
        return False
    head = text[:offsets[clause_start]].rstrip()
    previous = re.split(r"[.,;:!?()\[\]{}\n\r]", head[:-1])[-1] if head.endswith(",") else ""
    previous_words = normalize_text(previous).split()
    return not (next_words and _is_negation(next_words[0])) and not (previous_words and _is_negation(previous_words[0]))


def _negation(text: str, normalized: str, offsets: list[int], start: int, end: int) -> tuple[str, int] | None:
    """How a negation reads the words at start: ("excluded", where it begins), ("kept", where it begins)
    when it may name what is needed, or None when nothing negates them."""
    clause = _clause_words(text, normalized, offsets, start)
    window = clause[-NEGATION_WINDOW:]
    for index, (position, word) in enumerate(clause):
        if _bare(word) in _SET_ASIDE and all(other in _LEADING_WORDS for _, other in clause[:index]):
            return "excluded", position
    if any(_bare(word) in _OMISSIONS or _bare(word) in _LIMITS for _, word in window):
        return None
    for index in range(len(window) - 1, -1, -1):
        position, word = window[index]
        following = [other for _, other in window[index + 1:]]
        if word in _AVOID and _CHANGE_WORDS.intersection(following[:2]):
            return "excluded", position
        if not _is_negation(word):
            continue
        if following and following[0] in _NOT_NEGATING_NEXT:
            continue
        before = window[index - 1][1] if index else ""
        if word in _DOUBLE_NEGATION[0] and (before in _DOUBLE_NEGATION[1] or before.endswith("n't")):
            return None
        opens_clause = len(clause) - len(window) + index == 0
        if word in _DOUBLE_NEGATION[0] and opens_clause and _opens_a_condition(
                text, offsets, position, len(window) - index, end, french=word == "sans"):
            return "kept", position
        return "excluded", position
    rest = normalized[end:]
    after = _AFTER_NEGATION.match(rest.lstrip())
    if after:
        stop = end + len(rest) - len(rest.lstrip()) + after.end()
        if not _CLAUSE_END.search(text, offsets[end - 1] + 1, offsets[stop - 1] + 1):
            return "excluded-after", stop
    return None


def _passage(text: str, offsets: list[int], first: int, last: int) -> str:
    """The words of text between two positions of its normalized form, as written."""
    return " ".join(text[offsets[first]:offsets[last - 1] + 1].split())


def _quote(text: str, normalized: str, offsets: list[int], start: int, end: int) -> str:
    """The words of text from normalized[start:end], with a few words of their clause around them, ending
    on a word that carries meaning."""
    words = _clause_words(text, normalized, offsets, start)[-_QUOTE_WORDS:]
    first = offsets[words[0][0]] if words else offsets[start]
    last = offsets[end - 1] + 1
    clause_end = _CLAUSE_END.search(text, last)
    limit = clause_end.start() if clause_end else len(text)
    after = list(re.finditer(r"\S+", text[last:limit]))
    taken = after[:_QUOTE_WORDS]
    while taken and normalize_text(taken[-1].group()) in _TRAILING_WORDS and len(taken) < min(len(after), 2 * _QUOTE_WORDS):
        taken = after[:len(taken) + 1]
    while taken and normalize_text(taken[-1].group()) in _TRAILING_WORDS:
        taken.pop()
    if taken:
        last += taken[-1].end()
    return " ".join(text[first:last].split())


def _joined_to(text: str, offsets: list[int], normalized: str, previous_end: int, start: int) -> bool:
    """True when only list words, and no clause boundary, separate a previous match from this one."""
    if _CLAUSE_END.search(text, offsets[previous_end - 1] + 1, offsets[start]):
        return False
    return all(_bare(word) in _LIST_WORDS or word in _LIST_WORDS for word in normalized[previous_end:start].split())


def scan_triggers(boards: dict, text: str, enabled: set[str] | None = None) -> tuple[dict, dict]:
    """The boards a text selects and those it mentions as excluded, each with the passages that say so.

    Returns ({board: [(trigger, passage, note)]}, {board: [passage]}); note is empty unless a negation was
    read and the board kept. The longest phrase claims the words it covers, so "performance budget" selects
    Performance and not Finance through "budget". A neutral phrase claims its words for no board, and a
    board's own shorter phrases never cancel its longer one."""
    normalized, offsets = normalize_with_offsets(text)
    candidates = []
    sources = [(None, phrase) for phrase in NEUTRAL_PHRASES]
    sources += [(board_id, trigger) for board_id in sorted(enabled if enabled is not None else boards)
                for trigger in boards[board_id]["triggers"]]
    for board_id, trigger in sources:
        for match in _trigger_matches(trigger, normalized):
            candidates.append((match.end() - match.start(), match.start(), match.end(), board_id or "", trigger))
    claimed: set[tuple[int, int, str]] = set()
    kept = []
    for _, start, end, board_id, trigger in sorted(candidates, key=lambda item: (-item[0], item[1], item[3])):
        overlaps = [owner for other_start, other_end, owner in claimed
                    if start < other_end and other_start < end and (start, end) != (other_start, other_end)]
        # Boards that share the exact same phrase are all selected; a longer phrase wins otherwise.
        if overlaps:
            if board_id and all(owner == board_id for owner in overlaps):
                claimed.add((start, end, board_id))
            continue
        claimed.add((start, end, board_id))
        if board_id:
            kept.append((start, end, board_id, trigger))
    selected: dict[str, list[tuple[str, str, str]]] = {}
    excluded: dict[str, list[str]] = {}
    previous = None  # (end, how, where) of the last match, for the items of a negated list
    for start, end, board_id, trigger in sorted(kept):
        reading = _negation(text, normalized, offsets, start, end)
        if reading is None and previous and previous[1] == "excluded" and previous[0] <= start \
                and _joined_to(text, offsets, normalized, previous[0], start):
            reading = ("excluded", previous[2])
        previous = (end, reading[0] if reading else None, reading[1] if reading else None)
        if reading and reading[0] in ("excluded", "excluded-after"):
            first, last = (reading[1], end) if reading[0] == "excluded" else (start, reading[1])
            passage = _passage(text, offsets, first, last)
            # "without touching personal data or secrets" replaces its own beginning.
            passages = [item for item in excluded.setdefault(board_id, []) if not passage.startswith(item)]
            excluded[board_id] = passages + [passage] if passage not in passages else passages
            continue
        found = selected.setdefault(board_id, [])
        # "regression" and "régression" are one word once folded: report it once.
        if all(normalize_text(trigger) != normalize_text(other) for other, _, _ in found):
            note = KEPT_AFTER_NEGATION if reading else ""
            found.append((trigger, _quote(text, normalized, offsets, start, end), note))
    # A board both selected and excluded by the same text is selected: "no X" does not cancel another mention.
    return selected, {board_id: passages for board_id, passages in excluded.items() if board_id not in selected}


def trigger_matches(boards: dict, text: str) -> dict[str, list[str]]:
    """Return the triggers that select each board; a negated trigger selects nothing (see scan_triggers)."""
    selected, _ = scan_triggers(boards, text)
    return {board_id: [trigger for trigger, _, _ in found] for board_id, found in selected.items()}


def _concepts_in_text(text: str) -> list[dict]:
    """Concepts the text describes: each of their groups of terms has a match."""
    return [
        concept for concept in _CONCEPTS
        if concept["terms"] and all(trigger_matches({"group": {"triggers": group}}, text) for group in concept["terms"])
    ]


def task_concepts(text: str, answers: dict) -> list[dict]:
    """Concepts recognised from the concerns answer or from the brief and context."""
    chosen = set(as_list(answers.get("concerns")))
    in_text = _concepts_in_text(text)
    return [concept for concept in _CONCEPTS if concept["id"] in chosen or concept in in_text]


def _trigger_reasons(found: list[tuple[str, str, str]]) -> list[str]:
    return [f"Brief mentions {trigger!r}: \"{passage}\"" + (f" ({note})" if note else "") for trigger, passage, note in found]


# Words that say who a task serves when they come shortly before a declared role: "for our support agents",
# "Audience: support agents", "pour l'équipe support".
_AUDIENCE_WORDS = frozenset((
    "for", "audience", "used", "read", "serves", "serving", "intended", "pour", "public", "destine", "destinee",
    "destines", "destinees", "utilise", "utilisee", "lu", "lue",
))


def _audience_routes(profile: dict, task: dict, answers: dict, enabled: set[str]) -> dict[str, str]:
    """Boards of the project's declared roles that the task's audience names, with the passage. The affected
    answer names the audience; the brief and the context name it after "for", "audience" or "pour"."""
    roles = [role for role in profile.get("roles", []) if role in enabled]
    phrases = {role: {"triggers": sorted({role, role.replace("-", " ")})} for role in roles}
    found: dict[str, str] = {}
    for field, text in (("affected", answers.get("affected") or ""), ("brief", task["brief"]),
                        ("context", answers.get("context") or "")):
        normalized, offsets = normalize_with_offsets(text)
        selected, _ = scan_triggers(phrases, text)
        for role, matches in selected.items():
            if role in found:
                continue
            if field == "affected":
                found[role] = matches[0][1]
                continue
            pattern = re.compile("|".join(trigger_pattern(phrase).pattern for phrase in phrases[role]["triggers"]))
            for match in pattern.finditer(normalized):
                # "Audience: support agents" labels the clause, so the window crosses a colon but not a sentence.
                # The marker may head a list: "read by the support team and customer-success managers".
                sentence = re.split(r"[.;!?\n]", normalized[:match.start()])[-1]
                before = {_bare(word) for word in re.findall(r"[\w']+", sentence)[-8:]}
                if before & _AUDIENCE_WORDS:
                    found[role] = _quote(text, normalized, offsets, match.start(), match.end())
                    break
    return {role: f"Declared role of the project, and the task is for \"{passage}\"" for role, passage in found.items()}


# The surface each stack role's board serves: a React page is frontend work, a Django endpoint backend work, even
# when the brief names neither.
_STACK_SURFACES = {"frontend": "customer", "backend": "service"}


def _stack_words(boards: dict, role: str, stack: list[str]) -> list[str]:
    """The triggers of a role's board that the stack names, such as react for "React 18.3"."""
    return trigger_matches({role: boards[role]}, ", ".join(stack)).get(role, [])


def _stack_routes(profile: dict, boards: dict, task: dict, answers: dict, enabled: set[str]) -> dict[str, str]:
    """Boards of the project's declared roles that the task's stack calls for, with the reason: the role whose board
    the stack of a touched component names (named in the answers, or a path of the brief), and the frontend or
    backend role when the task touches the surface it serves and the project's stack names its frameworks."""
    roles = [role for role in profile.get("roles", []) if role in enabled and role in boards]
    found: dict[str, str] = {}
    touched = touched_components({"brief": task["brief"], "answers": answers}, profile)
    for component in profile.get("components", []):
        if component["id"] not in touched:
            continue
        for role in roles:
            words = _stack_words(boards, role, component.get("stack", []))
            if words and role not in found:
                found[role] = (f"Declared role of the project, and the task touches component {component['id']}, "
                               f"whose stack names {', '.join(words)}")
    for role, surface in _STACK_SURFACES.items():
        words = _stack_words(boards, role, profile.get("stack", [])) if role in roles else []
        if words and surface in as_list(answers.get("surface")) and role not in found:
            found[role] = (f"Declared role of the project, and the task touches the {SURFACE_MEANINGS[surface]} of "
                           f"a stack that names {', '.join(words)}")
    return found


def _task_parts(task: dict, answers: dict) -> list[str]:
    """The brief and each free-text answer, read one at a time so that a quote never spans two of them."""
    return [text for text in (task["brief"], *(answers.get(field, "") for field in ("context", *FOLLOW_UPS))) if text]


def _task_text(task: dict, answers: dict) -> str:
    return " ".join([task["brief"], *(answers.get(field, "") for field in ("context", *FOLLOW_UPS))])


def text_routes(boards: dict, brief: str, answers: dict | None = None,
                enabled: set[str] | None = None) -> dict[str, list[str]]:
    """Boards that the words of a task select, with the reason: the triggers and the passage that names them, the
    brief and each free-text answer read apart, then the concepts the whole text describes. Every consultation
    routes its texts here."""
    return _text_reasons(boards, {"brief": brief}, answers or {}, set(boards if enabled is None else enabled))[0]


def _text_reasons(boards: dict, task: dict, answers: dict, enabled: set[str]) -> tuple[dict, dict]:
    """The reasons the brief and answers give each board, and the passages that exclude boards."""
    reasons: dict[str, list[str]] = {}
    excluded: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for text in _task_parts(task, answers):
        selected, negated = scan_triggers(boards, text, enabled)
        for board_id, found in selected.items():
            for item in found:
                if normalize_text(item[0]) not in seen.setdefault(board_id, set()):
                    seen[board_id].add(normalize_text(item[0]))
                    reasons.setdefault(board_id, []).extend(_trigger_reasons([item]))
        for board_id, passages in negated.items():
            excluded.setdefault(board_id, []).extend(item for item in passages if item not in excluded[board_id])
    for concept in _concepts_in_text(_task_text(task, answers)):
        for board_id, reason in concept["boards"].items():
            if board_id in enabled:
                reasons.setdefault(board_id, []).append(reason)
    return reasons, {board_id: passages for board_id, passages in excluded.items() if board_id not in reasons}


def _route_boards(profile: dict, catalog: dict, task: dict, answers: dict) -> dict:
    boards = catalog["boards"]
    enabled = set(profile.get("boards") or boards)
    reasons = {}

    def add(board_id: str, reason: str) -> None:
        if board_id in enabled and reason not in reasons.get(board_id, []):
            reasons.setdefault(board_id, []).append(reason)

    for question_id, routes in _STRUCTURED_ROUTES.items():
        for answer in as_list(answers[question_id]):
            for board_id, reason in routes.get(answer, {}).items():
                add(board_id, reason)
    # An unsure concerns answer keeps every topic's rules open (relevance.py): every topic's boards review them.
    unsure = "unsure" in as_list(answers.get("concerns"))
    for concept in _CONCEPTS if unsure else task_concepts("", answers):
        for board_id, reason in concept["boards"].items():
            add(board_id, f"Concerns unsure, so this topic stays open: {reason}" if unsure else reason)

    matches = text_routes(boards, task["brief"], answers, enabled)
    for board_id in sorted(matches):
        for reason in matches[board_id]:
            add(board_id, reason)
    for board_id, reason in _audience_routes(profile, task, answers, enabled).items():
        add(board_id, reason)
    for board_id, reason in _stack_routes(profile, boards, task, answers, enabled).items():
        add(board_id, reason)

    if not reasons:
        board_id = "product" if "product" in enabled else min(enabled)
        reasons[board_id] = [NO_DISCIPLINE]
    return reasons


def _left_out_reason(board: dict, declared: bool, answers: dict) -> str:
    """Why a board the team expects was not selected, and the words that would have selected it."""
    distinct = {}
    for trigger in board["triggers"]:
        distinct.setdefault(re.sub(r"[\W_]", "", normalize_text(trigger)), trigger)
    examples = ", ".join(list(distinct.values())[:3])
    why = "declared role of the project" if declared else "enabled in the profile"
    return (f"{why}; the answers (kind {answers['kind']}, surface {', '.join(as_list(answers['surface']))}, "
            f"data {answers['data']}) do not call for it and the brief names none of its subjects, such as {examples}")


def suggested_patterns(profile: dict, catalog: dict, task: dict, answers: dict) -> list[dict]:
    """Patterns that the task's concepts call for and the project has not selected yet."""
    # A pattern scoped to components is recorded as {"id": ..., "components": [...]}.
    active = {entry["id"] if isinstance(entry, dict) else entry for entry in profile.get("patterns", [])}
    suggestions = {}
    for concept in task_concepts(_task_text(task, answers), answers):
        for pattern_id in concept["patterns"]:
            if pattern_id in catalog["patterns"] and pattern_id not in active:
                suggestions.setdefault(pattern_id, concept["reason"])
    return [{"id": pattern_id, "reason": reason} for pattern_id, reason in suggestions.items()]


def select_boards(profile: dict, catalog: dict, task: dict, answers: dict, selection: dict | None = None,
                  proposed: dict | None = None) -> dict:
    """Apply the project's required boards and the requester's changes to the proposed routing.

    selection: {"add": [ids], "remove": [ids], "reason": text, "delegate": {board: person}}
    proposed: the routing a short-lane task is given (short_lane.proposed_routing) in place of the words of the brief.
    Returns {"routing": {...}, "adjustments": [...], "delegations": {...}}.
    """
    selection = selection or {}
    boards = catalog["boards"]
    enabled = set(profile.get("boards") or boards)
    routing = {board_id: list(reasons) for board_id, reasons in proposed.items()} if proposed is not None \
        else _route_boards(profile, catalog, task, answers)
    required = list(profile.get("required_boards", []))
    delegations = dict(selection.get("delegate") or {})
    unknown = sorted(set(delegations) - set(required))
    if unknown:
        raise ValueError(f"Only a required board can be delegated: {', '.join(unknown)}.")
    missing = []
    for board_id in required:
        if board_id in enabled:
            if "Required by the project" not in routing.get(board_id, []):
                routing.setdefault(board_id, []).append("Required by the project")
        elif board_id in delegations:
            routing.setdefault(board_id, []).append(f"Required by the project, reviewed by {delegations[board_id]}")
        else:
            missing.append(board_id)
    if missing:
        raise ValueError(
            f"Required reviews are unavailable: {', '.join(missing)} not enabled in the profile. Enable them, "
            "or name the person who will review with --delegate BOARD=NAME."
        )
    adjustments = []
    reason = (selection.get("reason") or "").strip()
    if (selection.get("add") or selection.get("remove")) and not reason:
        raise ValueError("Give a --reason for adding or removing a board.")
    for board_id in selection.get("add") or []:
        if board_id not in enabled:
            raise ValueError(f"Board {board_id!r} is not enabled for this project.")
        if board_id not in routing:
            routing[board_id] = [f"Added by the requester: {reason}"]
            adjustments.append({"action": "add", "board": board_id, "reason": reason})
    for board_id in selection.get("remove") or []:
        if board_id not in routing:
            raise ValueError(f"Board {board_id!r} was not proposed for this task.")
        if board_id in required:
            raise ValueError(f"The project requires the {board_id} review; it cannot be removed.")
        adjustment = {"action": "remove", "board": board_id, "reason": reason}
        protected = _STRUCTURED_ROUTES["data"].get(answers["data"], {}).get(board_id)
        if answers["data"] in PROTECTED_DATA and protected in routing[board_id]:
            adjustment.update(routed_for=protected, confirmation="pending")
        del routing[board_id]
        adjustments.append(adjustment)
    if not routing:
        raise ValueError("Keep at least one board for the consultation.")
    _, negated = _text_reasons(boards, task, answers, enabled)
    excluded = {board_id: passages for board_id, passages in sorted(negated.items()) if board_id not in routing}
    removed = {item["board"] for item in adjustments if item["action"] == "remove"}
    not_selected = sorted(enabled - set(routing) - set(excluded) - removed)
    declared = set(profile.get("roles", []))
    # A profile that lists only some boards says the team expects those; the full list says nothing.
    listed = set(profile.get("boards") or []) if set(profile.get("boards") or []) < set(boards) else set()
    expected = {board_id: _left_out_reason(boards[board_id], board_id in declared, answers)
                for board_id in not_selected if board_id in declared or board_id in listed}
    return {"routing": routing, "adjustments": adjustments, "delegations": delegations,
            "patterns": suggested_patterns(profile, catalog, task, answers),
            "excluded": excluded,
            "not_selected": not_selected, "expected_not_selected": expected}


def touched_components(scope: dict, profile: dict) -> set[str]:
    """Components the task names in its answers, or whose folder a path of the brief falls in."""
    named = set(as_list(scope["answers"].get("components")))
    text = " ".join([scope["brief"], *(scope["answers"].get(key, "") for key in ("context", *FOLLOW_UPS))])
    paths = [match.group(0) for match in re.finditer(r"(?<![\w.-])[\w.-]+(?:/[\w.-]+)+", text)]
    for component in profile.get("components", []):
        folder = (component.get("path") or "").strip("/")
        if folder and any(path == folder or path.startswith(folder + "/") for path in paths):
            named.add(component["id"])
    return named
