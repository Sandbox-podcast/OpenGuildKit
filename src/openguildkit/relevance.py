"""Decides which active packs concern a task, from its answers, boards and brief.

Each bundled pack has a subject (SUBJECTS): the task answers that call for it, and for a few packs the boards
the task consults or the words its brief uses. A pack concerns a task when its subject meets the task's kind,
surface, data and concerns, and the way it reached the project still holds: a method pack needs a board of the
role that brought it, a pack brought for some components needs a changed file in them (the subject decides when
nothing can be compared). The presence of a board or of personal data does not bring a pack by itself. A pack
of the project's own catalog has no subject and follows its origin: a regulation pack concerns tasks on
personal or regulated data, the others concern every task. Every pack left out is recorded as not concerned,
with the reason, and needs no answer. LEGAL_BASIS (legal_basis.py) gives, for each regulatory pack, the subject
retained and its legal reason. judge_rules then decides rule by rule, for the board passes, the handoff and the closing alike.

Entry: rule_not_concerned, judge_rules, sensitive_area, evidence_owner, changed_files, condition_met
Tests: tests/test_pass_relevance.py, tests/test_relevance.py
"""

from pathlib import Path, PurePosixPath

from . import git
from .decisions import changed_paths_since
from .patterns import is_stack_pattern, pattern_selection
from .questionnaire import FOLLOW_UPS
from .records import Catalog, Profile, Task
from .routing import trigger_matches

BASELINE_PACKS = ("agent-workflow", "secure-sdlc")
OPEN_ANSWERS = ("unsure", "other")
SELECTING_ANSWERS = ("data", "concerns")
# Conditions on what the task consults or says, not on its answers.
FACTS = ("boards", "mentions")
VERBS = {"surface": "includes", "concerns": "include"}
_CODE = [{"surface": ["service", "customer", "infrastructure"]}]
_UI = [{"surface": ["customer"]}]
_PRODUCT = [{"surface": ["customer"], "kind": ["feature"]}]
_SERVICE = [{"surface": ["service"]}]
_INFRASTRUCTURE = [{"surface": ["infrastructure"]}]
_AI = [{"concerns": ["ai", "people-decisions"]}]
_AI_AGENT = [{"concerns": ["ai"]}, {"mentions": ["agents and MCP"]}]
_MONEY = [{"concerns": ["money"]}]
_PERSONAL = [{"data": ["personal", "regulated"]}]
# Personal data on a surface that users or services reach: the information these controls protect.
_PERSONAL_SURFACE = {"surface": ["customer", "service"], "data": ["personal"]}
_SECURITY = [{"data": ["regulated"]}, {"concerns": ["credentials"]}, {"surface": ["infrastructure"]}, _PERSONAL_SURFACE]
# A change that adds or changes an ICT system on personal data; a bug fix restores the system as it was.
_ICT = [{"data": ["regulated"]}, {"surface": ["infrastructure"]}, {**_PERSONAL_SURFACE, "kind": ["feature", "maintenance"]}]
_BUSINESS = [{"surface": ["business"]}]
_HIRING = {"boards": ["hr"], "mentions": ["hiring"]}
# Words that name a subject no answer names, read in the brief and the free-text answers as the routing reads
# a board's triggers: whole words, a regular plural, and a negated mention ("no card payments") names nothing.
MENTIONS = {
    "card payments": ("card", "credit card", "debit card", "carte bancaire", "carte de paiement", "cardholder",
                      "payment", "paiement", "checkout", "payment page", "payment provider", "psp", "stripe",
                      "adyen", "paypal", "braintree"),
    "hiring": ("hire", "hiring", "recruit", "recruiting", "recruitment", "recruter", "recrutement", "embauche",
               "embaucher", "candidate", "candidat", "candidature", "applicant", "interview", "entretien d'embauche",
               "job posting", "job offer", "offre d'emploi", "job description", "fiche de poste"),
    # A support agent or a sales agent is a person: only the AI agent and the protocols and frameworks that build one.
    "agents and MCP": ("mcp", "model context protocol", "ai agent", "llm agent", "agentic", "agent ia", "agentique",
                       "tool calling", "function calling", "langgraph", "crewai", "autogen", "openai agents",
                       "pydantic ai", "claude agent sdk"),
}
# The subject of each bundled pack: a list of alternatives, each a set of conditions that must all match. The
# task answers kind, surface, data and concerns match when one of their values is listed; "boards" matches when
# the task consults one of the boards listed; "mentions" when its text names one of the MENTIONS listed. A pack
# concerns a task only through its subject: the presence of a board or of personal data does not bring it alone.
# An answer left open (unsure, other, or missing) matches. None marks the packs of every change.
SUBJECTS = {
    "agent-workflow": ("the change process", None),
    "secure-sdlc": ("secure development of every change", None),
    # The core methods of QA and data follow the board of their role, which reviews the task.
    **{pack: ("the work its board reviews", None) for pack in ("test-strategy", "data-definitions")},
    **{pack: ("the project's code", _CODE) for pack in (
        "python", "typescript", "api-design", "django", "fastapi", "express", "spring-boot", "aspnet-core", "rails",
        "laravel", "symfony", "symfony-security", "kotlin-service", "ktor-server", "rust-cargo", "rust-dependencies",
        "dbt", "apache-airflow", "elixir-mix", "phoenix", "go-database", "postgresql", "pytest", "licence-policy")},
    **{pack: ("the user interface", _UI) for pack in (
        "react", "vue", "angular", "nextjs", "svelte", "sveltekit", "react-native", "expo", "flutter",
        "frontend-delivery", "web-accessibility", "web-performance",
        "mobile-accessibility", "ios-app", "android-app", "mobile-store-release", "i18n-readiness", "playwright",
        "chaosfolk-e2e", "public-sector-accessibility", "european-accessibility-act", "france-rgaa-accessibility",
        "france-cookies-and-trackers")},
    **{pack: ("a new customer feature", _PRODUCT) for pack in (
        "design-process", "user-research-practice", "controlled-experiments", "product-discovery",
        "opportunity-solution-tree", "jobs-to-be-done", "web-search-optimization", "release-communication",
        "support-readiness")},
    # No task answer names content that users publish: the trust and safety board, which the brief's words about
    # reports, moderation or illegal content route, does.
    "notice-and-action": ("content that users publish", [{"boards": ["trust-and-safety"]}]),
    **{pack: ("a backend service", _SERVICE) for pack in ("backend-data-safety", "public-api-docs")},
    "service-reliability": ("a running service", [{"surface": ["service"]}, {"surface": ["infrastructure"]}]),
    **{pack: ("infrastructure and delivery", _INFRASTRUCTURE) for pack in (
        "container-images", "kubernetes-gitops", "terraform-kubernetes", "aws-iam", "github-actions-security",
        "gitlab-ci-security", "incident-response", "release-management", "supply-chain")},
    # The tools, instructions and checks agents work with: the repository's delivery tooling.
    "agent-native-engineering": ("the tools and instructions agents work with", _INFRASTRUCTURE),
    "finops-cost-management": ("cloud and vendor spending", [
        {"surface": ["infrastructure"]}, {"surface": ["business"], "concerns": ["money"], "boards": ["finance", "devops"]}]),
    **{pack: ("AI", _AI) for pack in ("llm-evaluations", "nist-ai-risk", "eu-ai-act")},
    # Concern ai names it; so does a brief that speaks of an MCP server or an AI agent, which no answer does.
    "agentic-application-security": ("an AI agent or an MCP server", [*_AI_AGENT]),
    **{pack: ("money", _MONEY) for pack in (
        "revenue-recognition", "saas-metrics", "vat-and-e-invoicing", "france-e-invoicing", "financial-planning",
        "deal-approval")},
    "pci-dss": ("payment card data", [{"data": ["regulated"]}, {"concerns": ["money"], "mentions": ["card payments"]}]),
    **{pack: ("personal data", _PERSONAL) for pack in (
        "gdpr", "minors-data-protection", "health-data-protection", "france-health-data-hosting")},
    **{pack: ("security-sensitive changes", _SECURITY) for pack in (
        "threat-modeling", "owasp-asvs", "iso-27001", "france-public-sector-security")},
    **{pack: ("the ICT systems of a regulated entity", _ICT) for pack in ("dora", "nis2")},
    # An aviation organisation's systems, data and interfaces, and the software and systems of an aircraft product.
    "aviation-information-security": ("the systems of an aviation organisation", [
        {"surface": ["service", "customer", "infrastructure"]}, {"data": ["regulated"]}]),
    **{pack: ("airborne software and systems", _CODE) for pack in ("airborne-software-assurance",
                                                                    "airworthiness-security")},
    **{pack: ("security incidents and vulnerabilities", [{"surface": ["infrastructure"]}, {"concerns": ["credentials"]}])
       for pack in ("cyber-resilience-act", "incident-notification")},
    "pay-transparency": ("pay and recruitment", [
        {"concerns": ["people-decisions"]}, {"boards": ["hr"], "concerns": ["money"]}, _HIRING]),
    "structured-hiring": ("hiring decisions", [{"concerns": ["people-decisions"]}, _HIRING]),
    "device-and-access-lifecycle": ("staff devices and access", [{"surface": ["business"]}, {"concerns": ["credentials"]}]),
    **{pack: ("a business process", _BUSINESS) for pack in (
        "campaign-measurement", "workforce-capacity", "onboarding-practice", "employee-offboarding", "partner-program",
        "meddpicc-qualification", "spin-discovery", "sales-pipeline-review", "account-health-review",
        "channel-selection", "campaign-planning", "market-evidence", "vendor-due-diligence", "enterprise-risk-review",
        "strategy-map", "leadership-planning", "project-governance", "project-planning", "responsibility-matrix",
        "scrum-delivery", "kanban-delivery", "business-case-review")},
    "online-consumer-sales": ("selling to consumers", [{"surface": ["customer"], "concerns": ["money"]}]),
    "insurance-distribution": ("selling insurance", [{"surface": ["customer"], "concerns": ["money"]},
                                                     {"surface": ["customer"], "concerns": ["people-decisions"]}]),
    "unece-r155": ("the software of a road vehicle", _CODE),
    "unece-r156": ("the software updates of a road vehicle", _CODE),
}
# Data protection rules about creating or changing a processing: its record, its lawful basis, its
# retention, its impact assessment, rights over new data, the consent and notices of a new flow. A fix
# or maintenance of a processing the project already runs (kind bug or maintenance) does not create one;
# a feature, or any other kind, keeps them. The rules about the security of the processing, minimisation
# in what the change touches and documentation of a changed component stay asked.
FIX_KINDS = ("bug", "maintenance")
NEW_PROCESSING_RULES = {
    "gdpr": ("update-processing-record", "confirm-lawful-basis", "apply-retention-period", "assess-dpia-need",
             "keep-data-subject-rights-working", "inform-data-subjects", "gate-trackers-on-consent"),
    "minors-data-protection": ("confirm-age-of-consent", "obtain-parental-consent", "assess-dpia-for-pupils",
                               "protect-minors-by-default"),
    "health-data-protection": ("confirm-health-data-condition", "assess-health-data-dpia",
                               "qualify-medical-device-software", "classify-medical-device-software",
                               "plan-ehr-harmonised-components"),
}
# A new processor or a transfer outside the EEA: a maintenance (a migration to a hosted service) often adds
# one, a bug fix almost never. Only a bug leaves them out.
NEW_RECIPIENT_RULES = {"gdpr": ("review-processor-terms", "check-transfer-mechanism")}
# The rows of a pack that several regulations share, each with the pack of its regulation: a row is asked when
# that pack concerns the task, and the shared pack concerns the task when one of its rows does.
REGULATION_ROWS = {
    "incident-notification": {
        "gdpr-personal-data-breach": "gdpr", "nis2-significant-incident": "nis2", "dora-major-ict-incident": "dora",
        "cra-actively-exploited-vulnerability": "cyber-resilience-act", "ai-act-serious-incident": "eu-ai-act",
    },
}
# Subjects of single rules, inside a pack that concerns the task: automated-decision is the subject of a rule on
# decisions based solely on automated processing (GDPR Art. 22), asked when software decides about people.
RULE_SUBJECTS = {
    "automated-decision": ("automated decisions about people", [{"concerns": ["people-decisions"]}]),
}
# The rules that follow one of RULE_SUBJECTS on top of their pack's subject, by PACK/RULE.
RULES_WITH_A_SUBJECT = {"gdpr/automated-decision": "automated-decision"}


def rule_not_concerned(task: Task, pack_id: str, rule_id: str, packs: dict | None = None) -> str:
    """Why a rule of a pack that concerns the task does not concern it, or an empty text.

    packs is the pack relevance of the task (pack_relevance): a row of a shared pack follows its regulation's pack.
    """
    kind = task.get("answers", {}).get("kind")
    if kind in FIX_KINDS and rule_id in NEW_PROCESSING_RULES.get(pack_id, ()):
        return (f"the rule applies when a change creates or changes a processing of personal data, and the task is of "
                f"kind {kind}: it fixes or maintains a processing the project already runs (a feature keeps the rule)")
    if kind == "bug" and rule_id in NEW_RECIPIENT_RULES.get(pack_id, ()):
        return ("the rule applies when a new service provider processes the data or the data leaves the EEA, and the "
                "task is of kind bug: a fix keeps the recipients the project already has (a maintenance or a feature "
                "keeps the rule)")
    regulation = REGULATION_ROWS.get(pack_id, {}).get(rule_id)
    if regulation and packs is not None and not packs.get(regulation, {}).get("concerned"):
        # One reason for every row in the same case, so that a pass names them on one line.
        state = "does not concern the task" if regulation in packs else "is not in force"
        return f"the pack of the row's regulation {state}, and a row is asked when that pack concerns the task"
    subject = RULES_WITH_A_SUBJECT.get(f"{pack_id}/{rule_id}")
    if subject:
        label, alternatives = RULE_SUBJECTS[subject]
        if not condition_met(task, alternatives)[0]:
            return (f"its subject is {label}, which applies when the task's {_condition_text(alternatives)}; the task's "
                    f"answers ({_answers_text(task, alternatives)}) do not call for it")
    return ""


DECISION_REASON = "a decision task: its approval records the process and it delivers no implementation"


def judge_rules(task: Task, profile: Profile, relevance: dict | None = None) -> dict[str, dict]:
    """Each rule of the task's scope by PACK/RULE: whether it concerns the task, is mandatory or selected, and why not.

    The one judgement the board passes, the handoff and the closing share. Without a relevance judgement every
    rule concerns the task. A rule of a pack that concerns the task can still be outside it, such as the GDPR
    rules about a new processing for a bug fix; required_rules, --all and ask_every_rule keep it. A decision task
    delivers no implementation, so no rule concerns it.
    """
    required = set(profile.get("required_rules", []))
    packs = (relevance or {}).get("packs")
    every = bool((relevance or {}).get("every") or profile.get("ask_every_rule"))
    decision = task.get("answers", {}).get("kind") == "decision"
    judged = {}
    for pack in task["consultation"]["scope"].get("packs", []):
        entry = (packs or {}).get(pack["id"], {"concerned": True, "selected": False, "reason": ""})
        for rule in pack["rules"]:
            name = f"{pack['id']}/{rule['id']}"
            mandatory = pack["id"] in required or name in required
            concerned = entry["concerned"] or name in required
            narrowed = "" if mandatory or every or not concerned else rule_not_concerned(task, pack["id"], rule["id"],
                                                                                          packs)
            concerned = concerned and not narrowed
            reason = "" if concerned else narrowed or entry["reason"]
            if decision and concerned:
                concerned, reason = False, DECISION_REASON
            judged[name] = {"mandatory": mandatory, "selected": entry["selected"] or mandatory,
                            "concerned": concerned, "reason": reason}
    return judged


# A regulation pack of the project's own catalog concerns a task that touches personal or regulated data.
REGULATION_DEFAULT = [{"data": ["personal", "regulated"]}]
# Rules a person must confirm by name before a task closes with them skipped or failed.
SENSITIVE = {
    "data protection": ("gdpr", "minors-data-protection", "health-data-protection", "france-health-data-hosting",
                        "france-cookies-and-trackers", "backend-data-safety", "pci-dss"),
    "security": ("secure-sdlc", "owasp-asvs", "threat-modeling", "supply-chain", "iso-27001", "aws-iam",
                 "container-images", "github-actions-security", "gitlab-ci-security", "nis2", "dora",
                 "cyber-resilience-act", "incident-notification", "france-public-sector-security",
                 "agentic-application-security"),
    "AI": ("llm-evaluations", "nist-ai-risk", "eu-ai-act"),
}
# Who provides the named evidence of a pack: the document belongs to them, never to the agent.
EVIDENCE_OWNERS = {
    "gdpr": "the data protection officer or the person accountable for the processing (data controller)",
    "dora": "the ICT risk management function",
    "iso-27001": "the information security management system owner",
    "eu-ai-act": "the person accountable for the AI system's compliance",
    "pci-dss": "the PCI DSS compliance owner",
}


def sensitive_area(pack_id: str) -> str | None:
    """The sensitive area a pack belongs to: data protection, security or AI, or None."""
    return next((area for area, packs in SENSITIVE.items() if pack_id in packs), None)


def evidence_owner(pack_id: str) -> str:
    return EVIDENCE_OWNERS.get(pack_id, f"the person accountable for the {pack_id} obligations")


def changed_files(root: Path, task: Task) -> list[str] | None:
    """Project files changed since the approved revision, committed or not; None when Git cannot tell.

    The tool's own state folder is left out: its records are not part of the delivered change.
    """
    base = (task.get("decision") or {}).get("base_revision")
    if not base:
        return None
    try:
        tracked = changed_paths_since(root, base["commit"])
    except ValueError:
        return None
    untracked = git.names(root, "ls-files", "--others", "--exclude-standard")
    if untracked is None:
        return None
    return sorted({name for name in [*tracked, *untracked] if not name.startswith(".openguildkit/")})


def _answer_list(answers: dict, key: str) -> list[str]:
    value = answers.get(key)
    return [value] if isinstance(value, str) else list(value or [])


def _mentioned(task: Task, subject: str) -> bool:
    """Whether the brief or a free-text answer names a subject of MENTIONS, as the routing reads a trigger."""
    answers = task.get("answers", {})
    texts = [task.get("brief", ""), *(answers.get(field, "") for field in ("context", *FOLLOW_UPS))]
    return any(trigger_matches({"subject": {"triggers": list(MENTIONS[subject])}}, text) for text in texts if text)


def _fact_met(task: Task, key: str, values: list[str]) -> bool:
    """A condition on what the task consults or says rather than on an answer: never left open."""
    if key == "boards":
        return bool(set(values) & set(task.get("consultation", {}).get("boards", [])))
    return any(_mentioned(task, subject) for subject in values)


def _alternative_met(task: Task, condition: dict) -> tuple[bool, bool]:
    """Every condition of one alternative matches (an answer may be left open), and whether the data or concerns
    name it.

    Only the data and concerns answers select a pack in the sense of the warnings: they say what the
    task handles, where the kind and surface say only where it happens.
    """
    named = False
    answers = task.get("answers", {})
    for key, values in condition.items():
        if key in FACTS:
            if not _fact_met(task, key, values):
                return False, False
            continue
        given = _answer_list(answers, key)
        if any(item in values for item in given):
            named = named or key in SELECTING_ANSWERS
        elif given and not any(item in OPEN_ANSWERS for item in given):
            return False, False
    return True, named


def condition_met(task: Task, alternatives: list[dict]) -> tuple[bool, bool]:
    """Whether the task meets one of the alternatives, and whether its answers name it rather than leave it open."""
    results = [_alternative_met(task, condition) for condition in alternatives]
    met = [named for ok, named in results if ok]
    return bool(met), any(met)


def _condition_text(alternatives: list[dict]) -> str:
    def part(key: str, values: list[str]) -> str:
        if key == "boards":
            return f"consultation includes the {'/'.join(values)} board"
        if key == "mentions":
            return f"text names {'/'.join(values)}"
        return f"{key} {VERBS.get(key, 'is')} {'/'.join(values)}"

    return " or ".join(" and ".join(part(key, values) for key, values in condition.items()) for condition in alternatives)


def _answers_text(task: Task, alternatives: list[dict] | None = None) -> str:
    """The task's answers a subject reads, and the boards it consults when the subject depends on them."""
    answers = task.get("answers", {})
    shown = [f"{key} {'/'.join(_answer_list(answers, key)) or 'not answered'}"
             for key in ("kind", "surface", "data", "concerns")]
    if any("boards" in condition for condition in alternatives or []):
        shown.append(f"boards {'/'.join(task.get('consultation', {}).get('boards', [])) or 'none'}")
    return ", ".join(shown)


def _component_prefixes(components: list[str], profile: Profile) -> list[str] | None:
    """Each component's path relative to the project, without slashes around it; None when one has no path."""
    paths = {item["id"]: item.get("path") for item in profile.get("components", [])}
    if any(not paths.get(component) for component in components):
        return None
    return [PurePosixPath(paths[component].strip()).as_posix().strip("/") for component in components]


def _at_root(components: list[str], profile: Profile) -> bool:
    prefixes = _component_prefixes(components, profile)
    return bool(prefixes) and any(prefix in ("", ".") for prefix in prefixes)


def _in_components(changed: list[str], components: list[str], profile: Profile) -> bool | None:
    """Whether a changed file lies in one of the components; None when a component has no path.

    A component at the project root (path "." or "") holds every file.
    """
    prefixes = _component_prefixes(components, profile)
    if prefixes is None:
        return None
    if any(prefix in ("", ".") for prefix in prefixes):
        return bool(changed)
    return any(name.startswith(prefix + "/") for name in changed for prefix in prefixes)


def _origins(pack_id: str, profile: Profile, catalog: Catalog) -> list[dict]:
    """The ways a pack reached the project: the profile's packs, and each selected pattern that brings it."""
    origins = []
    if pack_id in profile.get("packs", []):
        regulation = next((pattern["id"] for pattern in catalog.get("patterns", {}).values()
                           if pattern.get("kind") == "regulation" and pack_id in pattern["packs"]), None)
        if regulation:
            origins.append({"kind": "regulation", "pattern": regulation})
        else:
            origins.append({"kind": "baseline" if pack_id in BASELINE_PACKS else "selected"})
    for entry in profile.get("patterns", []):
        pattern_id, components = pattern_selection(entry)
        pattern = catalog.get("patterns", {}).get(pattern_id)
        if pattern is None:
            origins.append({"kind": "unknown", "pattern": pattern_id})
            continue
        if pack_id not in pattern["packs"]:
            continue
        if pattern.get("kind") == "regulation":
            origins.append({"kind": "regulation", "pattern": pattern_id})
        elif is_stack_pattern(pattern):
            origins.append({"kind": "stack", "pattern": pattern_id, "components": components})
        else:
            roles = [role for role in pattern["roles"] if role in profile.get("roles", [])] or pattern["roles"]
            origins.append({"kind": "method", "pattern": pattern_id, "roles": roles})
    return origins


def _structure(origin: dict, task: Task, profile: Profile, changed: list[str] | None) -> tuple[bool, bool, str]:
    """Whether the way a pack came still holds for this task: the role's board, the component's files."""
    answers = task.get("answers", {})
    kind = origin["kind"]
    if kind == "method":
        boards = task.get("consultation", {}).get("boards", [])
        if not [role for role in origin["roles"] if role in boards]:
            return False, False, (f"method {origin['pattern']} came for the {', '.join(origin['roles'])} "
                                  f"{'role' if len(origin['roles']) == 1 else 'roles'}, "
                                  "and no board of those roles reviewed the task")
    if kind == "stack" and origin.get("components"):
        # The task's answers can name its components: the consultation scope then holds only theirs.
        if set(origin["components"]) & set(_answer_list(answers, "components")):
            return True, True, ""
        inside = _in_components(changed or [], origin["components"], profile) if changed else None
        if inside is False:
            return False, False, (f"pattern {origin['pattern']} applies to {', '.join(origin['components'])}, "
                                  "where no file changed since the approved revision")
        if inside:
            return True, True, ""
    if kind == "unknown":
        return True, False, f"pattern {origin['pattern']} is no longer in the catalog"
    return True, False, ""


def _judge_with_subject(pack_id: str, origins: list[dict], task: Task, profile: Profile,
                        changed: list[str] | None) -> dict:
    """A bundled pack concerns the task when its subject meets the answers and the way it came still holds."""
    label, alternatives = SUBJECTS[pack_id]
    # Files changed in the component a pack was brought for are a stronger fact than the answers, unless
    # that component is the whole project: then every change lies in it and the subject decides.
    if changed and any(origin["kind"] == "stack" and origin.get("components")
                       and not _at_root(origin["components"], profile)
                       and _in_components(changed, origin["components"], profile) for origin in origins):
        return {"concerned": True, "selected": False, "reason": ""}
    named = False
    if alternatives is not None:
        met, named = condition_met(task, alternatives)
        if not met:
            return {"concerned": False, "selected": False, "reason": (
                f"its subject is {label}, which applies when the task's {_condition_text(alternatives)}; the task's "
                f"answers ({_answers_text(task, alternatives)}) do not call for it")}
    outcomes = [_structure(origin, task, profile, changed) for origin in origins] or [(True, False, "")]
    held = [item for item in outcomes if item[0]]
    if not held:
        return {"concerned": False, "selected": False, "reason": "; ".join(dict.fromkeys(item[2] for item in outcomes))}
    return {"concerned": True, "selected": named, "reason": ""}


def _judge(origin: dict, pack_id: str, task: Task, profile: Profile, changed: list[str] | None) -> tuple[bool, bool, str]:
    """For a pack of the project's own catalog: whether one origin makes it concern the task, and why not."""
    if origin["kind"] == "regulation":
        met, named = condition_met(task, REGULATION_DEFAULT)
        why = (f"regulation pattern {origin['pattern']}, which applies when the task's "
               f"{_condition_text(REGULATION_DEFAULT)}")
        return met, named, why if met else f"{why}; the task's answers say otherwise"
    return _structure(origin, task, profile, changed)


def pack_relevance(task: Task, profile: Profile, catalog: Catalog, changed: list[str] | None, every: bool = False) -> dict:
    """Each pack of the approved scope: whether it concerns the task, whether the answers select it, and why not.

    changed is the list of files changed since the approved revision, or None when it cannot be known.
    """
    packs = task["consultation"]["scope"].get("packs", [])
    required = {item.partition("/")[0] for item in profile.get("required_rules", []) if "/" not in item}
    judged = {}
    for pack in packs:
        pack_id = pack["id"]
        origins = _origins(pack_id, profile, catalog)
        if every or profile.get("ask_every_rule"):
            judged[pack_id] = {"concerned": True, "selected": False, "reason": ""}
        elif pack_id in required:
            judged[pack_id] = {"concerned": True, "selected": True, "reason": ""}
        elif pack_id in SUBJECTS:
            judged[pack_id] = _judge_with_subject(pack_id, origins, task, profile, changed)
        else:
            outcomes = [_judge(origin, pack_id, task, profile, changed) for origin in origins]
            concerned = [item for item in outcomes if item[0]]
            judged[pack_id] = {
                "concerned": bool(concerned), "selected": any(item[1] for item in concerned),
                "reason": "" if concerned else "; ".join(dict.fromkeys(item[2] for item in outcomes)),
            }
    _inherit(packs, judged)
    _follow_rows(judged)
    return judged


def _follow_rows(judged: dict) -> None:
    """A pack of regulation rows (REGULATION_ROWS) concerns the task when the pack of one of its rows does, even
    when its own subject does not; judge_rules then asks only those rows."""
    for pack_id, rows in REGULATION_ROWS.items():
        entry = judged.get(pack_id)
        if entry is None or entry["concerned"]:
            continue
        regulations = [regulation for regulation in dict.fromkeys(rows.values()) if regulation in judged]
        concerned = [regulation for regulation in regulations if judged[regulation]["concerned"]]
        if concerned:
            judged[pack_id] = {"concerned": True, "selected": any(judged[item]["selected"] for item in concerned),
                               "reason": ""}
        elif regulations:
            entry["reason"] += f"; its rows follow {', '.join(regulations)}, which do not concern the task either"


def _inherit(packs: list[dict], judged: dict) -> None:
    """A dependency without a subject of its own concerns the task when a pack that needs it does.

    A bundled dependency with a subject (incident notification, for example) is judged on that subject, then on
    the packs of its rows (_follow_rows).
    """
    needed: dict[str, list[str]] = {}
    for pack in packs:
        for dependency in pack.get("depends_on", []):
            needed.setdefault(dependency, []).append(pack["id"])
    changed = True
    while changed:
        changed = False
        for pack_id, users in needed.items():
            entry = judged.get(pack_id)
            if entry is None or entry["concerned"] or pack_id in SUBJECTS:
                continue
            concerned = [user for user in users if judged.get(user, {}).get("concerned")]
            if concerned:
                judged[pack_id] = {"concerned": True, "selected": any(judged[user]["selected"] for user in concerned),
                                   "reason": ""}
                changed = True
            elif not entry["reason"]:
                entry["reason"] = f"needed only by {', '.join(users)}, which do not concern the task"
