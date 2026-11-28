"""What a brain knows: its specialists' methods, rule packs and reference material.

A brain's knowledge is assembled from the catalog instead of being copied into each board:
the patterns whose roles name the brain, the packs those patterns apply, and the references
tagged with the brain. The consultation carries this knowledge to each selected brain.
"""

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path

from .catalog import ID_PATTERN

MAX_REFERENCES_IN_BRIEF = 12
# Text the skeleton of a project brain leaves to replace. brains --check reports it until it is gone.
TODO = "TODO:"

# Words too common to tell one reference from another, in English and French.
_STOPWORDS = frozenset("""
a an and are as at be by for from in into is it its of on or our the their this to with we you your
add build change make new use using update need needs want let over per via all any each
au aux avec ce ces dans de des du en est et la le les leur nos notre ou par pour sur un une
data donnees system systeme service project projet team equipe user users utilisateur application app task
""".split())
# Catalogue summaries are in French and often name a standard by its acronym: these bridges let an
# English brief reach them. Keys and values are folded words.
_RELATED_WORDS = {
    "sso": ("saml", "openid", "oauth", "federation", "authentification", "asvs"),
    "login": ("authentification", "connexion", "asvs"),
    "authentication": ("authentification", "asvs"),
    "identity": ("identite", "identification"),
    "okta": ("saml", "openid", "oauth"),
    "payment": ("paiement", "carte", "pci"),
    "card": ("carte", "paiement", "pci"),
    "cardholder": ("carte", "pci"),
    "privacy": ("rgpd", "gdpr", "personnelles"),
    "personal": ("personnelles", "rgpd"),
    "health": ("sante",),
    "patient": ("sante", "patient"),
    "accessibility": ("accessibilite",),
    "accessible": ("accessibilite",),
    "a11y": ("accessibilite", "wcag"),
    "translation": ("traduction", "internationalisation", "localisation"),
    "invoice": ("facture", "facturation"),
    "billing": ("facturation",),
    "tax": ("taxe", "tva"),
    "vat": ("tva",),
    "hiring": ("recrutement", "embauche"),
    "recruiting": ("recrutement",),
    "candidate": ("candidat", "recrutement"),
    "applicant": ("candidat", "recrutement"),
    "employee": ("salarie", "travail"),
    "salary": ("salaire", "remuneration"),
    "ai": ("ia",),
    "llm": ("ia", "langage"),
    "security": ("securite",),
    "vulnerability": ("vulnerabilite",),
    "contract": ("contrat",),
    "cost": ("cout",),
    "revenue": ("revenu",),
    "log": ("journal", "journalisation"),
    "regulated": ("reglementation",),
}


def brain_knowledge(board_id: str, catalog: dict, families: dict, active_packs: set[str] | None = None) -> dict:
    methods = [pattern for pattern in catalog["patterns"].values() if board_id in pattern["roles"]]
    pack_ids = list(dict.fromkeys(pack_id for pattern in methods for pack_id in pattern["packs"]))
    active_packs = active_packs or set()
    references = [
        reference
        for family in families.values()
        for reference in family["references"]
        if board_id in reference.get("brains", [])
    ]
    return {
        "methods": [{"id": pattern["id"], "title": pattern["title"]} for pattern in methods],
        "packs": [
            {"id": pack_id, "title": catalog["packs"][pack_id]["title"], "version": catalog["packs"][pack_id]["version"],
             "active": pack_id in active_packs}
            for pack_id in pack_ids if pack_id in catalog["packs"]
        ],
        "references": [
            {key: reference[key] for key in ("id", "title", "kind", "edition") if key in reference}
            | {"title": reference.get("title_en", reference["title"]), "url": reference["sources"][0]["url"]}
            for reference in references
        ],
    }


def _brain_records(board_id: str, catalog: dict, families: dict) -> list[dict]:
    """The board and the records its knowledge comes from."""
    methods = [pattern for pattern in catalog["patterns"].values() if board_id in pattern["roles"]]
    packs = [catalog["packs"][pack_id] for pattern in methods for pack_id in pattern["packs"] if pack_id in catalog["packs"]]
    references = [record for family in families.values() for record in family["references"]
                  if board_id in record.get("brains", [])]
    return [catalog["boards"][board_id], *methods, *packs, *references]


def knowledge_gaps(catalog: dict, families: dict) -> list[str]:
    """Brains that have no method or no reference attached."""
    gaps = []
    for board_id in catalog["boards"]:
        knowledge = brain_knowledge(board_id, catalog, families)
        if not knowledge["methods"]:
            gaps.append(f"{board_id} has no method: tag a pattern with this role.")
        if not knowledge["references"]:
            gaps.append(f"{board_id} has no reference: tag references with this brain.")
        if TODO in json.dumps(_brain_records(board_id, catalog, families), ensure_ascii=False):
            gaps.append(f"{board_id} still has skeleton text: replace each {TODO} in its catalog files.")
    return gaps


@lru_cache(maxsize=4096)
def _words(text: str) -> frozenset[str]:
    """Folded words without accents or a regular plural, so "Customers" and "customer" compare equal. Kept per text:
    a consultation ranks the same references for several boards."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(character for character in folded if not unicodedata.combining(character))
    words = set()
    for word in re.findall(r"[^\W\d_]+", plain):
        if len(word) > 1:
            words.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return frozenset(words - _STOPWORDS)


def consultation_context(task: dict, answers: dict, profile: dict, catalog: dict) -> str:
    """The words that describe a task for ranking references: brief, answers, sector and stack.
    The general sector names no domain, and active packs rank their references first on their own."""
    parts = [task.get("brief", "")]
    for key, value in answers.items():
        if key not in ("kind", "research"):
            parts.extend(value if isinstance(value, list) else [value])
    if profile.get("sector") != "general":
        sector = catalog["sectors"].get(profile.get("sector", ""), {})
        parts += [sector.get("title", ""), sector.get("description", "")]
    parts += profile.get("stack", [])
    return " ".join(part for part in parts if isinstance(part, str))


def _task_words(context: str) -> set[str]:
    words = set(_words(context))
    for word in list(words):
        words.update(_words(" ".join(_RELATED_WORDS.get(word, ()))))
    return words


def _rank(reference: dict, words: set[str], active_packs: set[str]) -> tuple:
    """Active packs first, then the overlap with the task (names count double), then applied references."""
    names = _words(" ".join([reference["id"].replace("-", " "), reference.get("title", ""),
                             reference.get("title_en", ""), *reference.get("aliases", [])]))
    labels = _words(f"{reference.get('category', '')} {reference.get('summary', '')}")
    overlap = 2 * len(words & names) + len(words & labels)
    applied = reference.get("status") == "applied" or bool(reference.get("packs"))
    return (not set(reference.get("packs", [])) & active_packs, -overlap, not applied, reference["id"])


def brief_knowledge(board_id: str, catalog: dict, families: dict, active_packs: set[str], context: str = "",
                    words: set[str] | None = None) -> dict:
    """The part of the knowledge a consultation carries: active packs first, and a reading list
    of the brain's references that best fit the task, bounded so the brief stays readable. words are the task's
    words of the context (_task_words), when the caller has them already."""
    knowledge = brain_knowledge(board_id, catalog, families, active_packs)
    knowledge["packs"].sort(key=lambda pack: not pack["active"])
    words = _task_words(context) if words is None else words
    records = {
        reference["id"]: reference
        for family in families.values()
        for reference in family["references"]
        if board_id in reference.get("brains", [])
    }
    ranked = sorted(knowledge["references"], key=lambda item: _rank(records[item["id"]], words, active_packs))
    knowledge["references"] = ranked[:MAX_REFERENCES_IN_BRIEF]
    return knowledge


class BriefKnowledge(Mapping):
    """Each board's brief_knowledge, worked out the first time the consultation asks for that board: it reads only the
    boards routing selects, not every board of the catalog. tools are the connected tools by board, added to its
    knowledge."""

    def __init__(self, catalog: dict, families: dict, active_packs: set[str], context: str,
                 tools: Callable[[str], list[dict]]):
        self._catalog, self._families, self._active, self._tools = catalog, families, active_packs, tools
        self._words = _task_words(context)
        self._known: dict[str, dict] = {}

    def __getitem__(self, board_id: str) -> dict:
        if board_id not in self._catalog["boards"]:
            raise KeyError(board_id)
        if board_id not in self._known:
            knowledge = brief_knowledge(board_id, self._catalog, self._families, self._active, words=self._words)
            usable = self._tools(board_id)
            if usable:
                knowledge["tools"] = usable
            self._known[board_id] = knowledge
        return self._known[board_id]

    def __iter__(self):
        return iter(self._catalog["boards"])

    def __len__(self) -> int:
        return len(self._catalog["boards"])


def _todo(text: str) -> str:
    return f"{TODO} {text}"


def brain_skeleton(board_id: str) -> dict[str, dict]:
    """Every file a project brain needs, keyed by its path in the project catalog, with text to replace."""
    pack_id, family_id = f"{board_id}-rules", f"project-{board_id}"
    specialists = [
        {"id": f"{board_id}-lens-{index}", "title": _todo(f"title of specialist {index}"),
         "focus": _todo("what this specialist examines in a task, in one or two sentences"),
         "checks": [_todo("one thing an expert of this lens verifies"), _todo("a frequent mistake this expert catches")]}
        for index in (1, 2, 3, 4)
    ]
    source = {"title": _todo("primary source: the standard, regulation or method publisher"),
              "url": "https://example.org/replace-with-the-primary-source"}
    board = {
        "id": board_id,
        "title": _todo("name of the discipline"),
        "description": _todo("what this brain reviews in a task, in one sentence"),
        "expertises": [_todo("area of expertise")],
        "triggers": [_todo("a phrase that appears in a task brief, in each language the team writes")],
        "questions": [_todo("a question this brain asks about every task")],
        "sources": [source],
        "review": {
            "specialists": specialists,
            "evidence": [_todo("a document, record or measurement this brain inspects")],
            "challenge": [_todo("a question that tests the proposal against an alternative or a failure")],
            "decision_criteria": [_todo("a condition that makes this brain proceed, revise or block")],
        },
    }
    pattern = {
        "id": f"{board_id}-method", "title": _todo("name of the method this brain applies"),
        "description": _todo("what the method does, in one sentence"), "sources": [source],
        "roles": [board_id], "packs": [pack_id],
    }
    pack = {
        "id": pack_id, "title": _todo("name of the rule pack"), "version": "0.1.0",
        "description": _todo("when these rules apply"), "sources": [source],
        "rules": [{"id": "first-rule", "instruction": _todo("an action an agent can take"),
                   "verification": _todo("how a person checks it in a record")}],
    }
    family = {
        "id": family_id, "title": _todo(f"references of {board_id}"),
        "references": [{
            "id": f"{board_id}-primary-source", "title": _todo("title of the reference"), "category": _todo("category"),
            "kind": "référentiel", "brains": [board_id], "summary": _todo("what the reference says, in one sentence"),
            "applies_when": _todo("when the brain should read it"), "packs": [pack_id], "sources": [source],
        }],
    }
    return {
        f"boards/{board_id}.json": board,
        f"patterns/{board_id}-method.json": pattern,
        f"packs/{pack_id}.json": pack,
        f"references/{family_id}.json": family,
    }


def write_brain_skeleton(catalog_dir: Path, board_id: str, catalog: dict) -> list[Path]:
    """Write the skeleton of a new project brain; refuse an existing ID or file instead of overwriting."""
    if not isinstance(board_id, str) or not ID_PATTERN.fullmatch(board_id):
        raise ValueError("Name the brain with lowercase letters, digits and hyphens, such as risk-office.")
    if board_id in catalog["boards"]:
        raise ValueError(
            f"Brain {board_id} already exists. To complete it, write .openguildkit/catalog/boards/{board_id}.json "
            "with only the lenses, evidence or criteria to add."
        )
    skeleton = brain_skeleton(board_id)
    for relative, record in skeleton.items():
        collection = relative.split("/")[0]
        if collection in ("patterns", "packs") and record["id"] in catalog[collection]:
            raise ValueError(f"The {collection[:-1]} {record['id']} already exists. Choose another brain ID.")
    files = {catalog_dir / relative: record for relative, record in skeleton.items()}
    existing = [path.as_posix() for path in files if path.exists()]
    if existing:
        raise ValueError(f"{existing[0]} already exists. Remove it or choose another brain ID.")
    for path, record in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return list(files)


def reading_list_note(count: int) -> str:
    """Says that brains --id shows the whole list while a consultation filters it."""
    return (f"All {count} references of this brain. A consultation keeps the {MAX_REFERENCES_IN_BRIEF} that best "
            "fit the task: those of the project's active packs, then those that share words with the brief, "
            "the answers, the sector and the stack.")
