"""Decide which active rule packs concern a task, from facts the tool already holds.

Each bundled pack has a subject (SUBJECTS): the task answers that call for it, and for a few packs the boards
the task consults or the words its brief uses. A pack concerns a task when its subject meets the task's kind,
surface, data and concerns, and the way it reached the project still holds: a method pack needs a board of the
role that brought it, a pack brought for some components needs a changed file in them (the subject decides when
nothing can be compared). The presence of a board or of personal data does not bring a pack by itself. A pack
of the project's own catalog has no subject and follows its origin: a regulation pack concerns tasks on
personal or regulated data, the others concern every task. Every pack left out is recorded as not concerned,
with the reason, and needs no answer. LEGAL_BASIS gives, for each regulatory pack, the subject retained and its
legal reason. judge_rules then decides rule by rule, for the board passes, the handoff and the closing alike.
"""

import subprocess
from pathlib import Path, PurePosixPath

from .decisions import changed_paths_since
from .patterns import is_stack_pattern, pattern_selection
from .questionnaire import FOLLOW_UPS
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
        "go-database", "postgresql", "pytest", "licence-policy")},
    **{pack: ("the user interface", _UI) for pack in (
        "react", "vue", "angular", "nextjs", "frontend-delivery", "web-accessibility", "web-performance",
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
# The subject retained for each regulatory pack and its legal reason. A regulation pattern is selected by a person
# who confirmed that the regulation applies to the organization; the subject then says which changes it reaches.
LEGAL_BASIS = {
    "gdpr": "personal or regulated data: the GDPR applies to the processing of personal data (Art. 2(1)). Within "
            "it, the rules about a new processing (record Art. 30, lawful basis Art. 6, retention Art. 5(1)(e), "
            "DPIA Art. 35, rights Art. 15 to 17, information Art. 13 and 14, consent to trackers ePrivacy Art. 5(3)) "
            "are left out of a bug or a maintenance, and those about a new "
            "processor (Art. 28) or a transfer outside the EEA (Chapter V) out of a bug only: a migration often "
            "changes where the data goes, a fix almost never.",
    "minors-data-protection": "personal or regulated data: GDPR Art. 8 and 35 and DSA Art. 28 apply to the "
                              "processing of children's data; the rules about a new flow are left out of a bug or a "
                              "maintenance.",
    "health-data-protection": "personal or regulated data: health data is a special category (GDPR Art. 9), and "
                              "software that processes it may be a medical device (Regulation (EU) 2017/745) or an "
                              "EHR system (Regulation (EU) 2025/327); the rules about a new processing are left out "
                              "of a bug or a maintenance.",
    "dora": "regulated data, infrastructure, or a feature or maintenance on a customer or service surface with "
            "personal data: for a financial entity, a change to an ICT system that serves clients or holds their "
            "data is a change of Art. 9(4)(e), its assets belong to the inventory of Art. 8, and a new ICT provider "
            "enters the register of Art. 28(3). A bug fix restores a system as it was and adds no asset or provider.",
    "nis2": "regulated data, infrastructure, or a feature or maintenance on a customer or service surface with "
            "personal data: the measures of Art. 21(2) cover the network and information systems an essential or "
            "important entity uses for its services, their suppliers (point d) included.",
    "aviation-information-security": "regulated data, or code, services and infrastructure: for an organisation listed "
                                     "in Art. 2 of Delegated Regulation (EU) 2022/1645 or Art. 2(1) of Implementing "
                                     "Regulation (EU) 2023/203, the systems, data and interfaces that support its "
                                     "activities belong to the risk assessment of IS.D.OR.205 or IS.I.OR.205.",
    "airborne-software-assurance": "code, services and infrastructure: AMC 20-115D applies to applicants, design "
                                   "approval holders and developers of airborne software (section 2), and the "
                                   "objectives of each software level are in the Annex A tables of ED-12C/DO-178C "
                                   "(section 6.a).",
    "airworthiness-security": "code, services and infrastructure: AMC 20-42 section 2 applies to manufacturers and "
                              "design approval holders, and its product information security risk assessment is an "
                              "acceptable means under Annex I (Part 21) to Regulation (EU) No 748/2012.",
    "european-accessibility-act": "a customer surface: Directive (EU) 2019/882 sets accessibility requirements for "
                                  "services provided to consumers (Art. 2(2), Annex I), applied since 28 June 2025.",
    "cyber-resilience-act": "infrastructure or credentials: its rules act on how releases are built, shipped and "
                            "updated and how vulnerabilities are handled (Annex I Part II, Art. 13(8)).",
    "incident-notification": "each row follows the pack of its regulation (GDPR Art. 33 and 34, NIS 2 Art. 23, DORA "
                             "Art. 19, CRA Art. 14, AI Act Art. 73) and is asked when that pack concerns the task; the "
                             "matrix itself also when the change touches infrastructure or credentials.",
    "eu-ai-act": "AI or decisions about people: the AI Act applies to AI systems (Art. 2), with the Art. 50 "
                 "transparency duties for systems that interact with people or generate content and Annex III for "
                 "systems that decide about people, such as in employment or credit.",
    "pci-dss": "regulated data, or money in a brief that names cards or payments: PCI DSS v4.0.1 applies to the "
               "system components that store, process or transmit cardholder data or can affect their security; "
               "prices, payroll or spending without a card are not in its scope.",
    "iso-27001": "regulated data, credentials, infrastructure, or personal data on a customer or service surface: "
                 "the Annex A controls protect the information in the scope of the management system, personal data "
                 "first (control 5.34).",
    "notice-and-action": "a task the trust and safety board reviews: DSA Art. 16, 17 and 20 apply to a hosting "
                         "service's notices, statements of reasons and complaints, and Regulation (EU) 2021/784 Art. 3 "
                         "to removal orders; the brief's words about reports, moderation or illegal content route "
                         "that board.",
    "pay-transparency": "pay or recruitment reviewed by the HR board, or software that decides about people: "
                        "Directive (EU) 2023/970 Art. 5 governs job postings and hiring forms, Art. 6 the pay "
                        "criteria and Art. 9 the pay gap report.",
    "insurance-distribution": "a customer surface with money or decisions about people: IDD Art. 20 and 25 govern "
                              "the sale and the approval of an insurance product, and AI Act Annex III point 5(c) "
                              "pricing for natural persons.",
    "online-consumer-sales": "a customer surface with money: Directive 2011/83/EU Art. 6 and 8 govern the "
                             "information and the order button of a distance sale to consumers.",
    "unece-r155": "the code of a service, a customer surface or infrastructure: UN Regulation No 155 asks the vehicle "
                  "manufacturer for a risk assessment, mitigations and tests of each vehicle type (paragraphs 7.3.3 "
                  "to 7.3.6, Annex 5) and for the monitoring of vehicles in use, and Regulation (EU) 2019/2144 Annex II "
                  "row D4 makes it a condition of EU type-approval.",
    "unece-r156": "the code of a service, a customer surface or infrastructure: UN Regulation No 156 asks the vehicle "
                  "manufacturer to identify software versions, assess the effect of each update on the type approval "
                  "and protect its delivery (paragraphs 7.1 and 7.2), where an approval authority applies it; "
                  "Regulation (EU) 2019/2144 does not list it in Annex I or Annex II.",
    "public-sector-accessibility": "the user interface: Directive (EU) 2016/2102 Art. 4 applies to the websites "
                                   "and mobile applications of public sector bodies.",
    "france-health-data-hosting": "personal or regulated data: Art. L1111-8 of the Code de la santé publique "
                                  "requires the host of personal health data to hold a certificate of conformity, "
                                  "and Art. R1111-9-1 and R1111-11 set the storage in the EU or EEA and the contract.",
    "france-rgaa-accessibility": "the user interface: Art. 47 of loi n° 2005-102 binds certain public and private "
                                 "entities to make their online public communication services accessible, tested "
                                 "with the RGAA.",
    "france-cookies-and-trackers": "the user interface: Art. 82 of loi n° 78-17 requires information and consent "
                                   "before trackers are written to or read from a user's device, unless exempt.",
    "france-public-sector-security": "regulated data, infrastructure, credentials, or personal data on a customer or "
                                     "service surface: Art. 3 and 4 of décret n° 2010-112 and Art. 4-3 of décret "
                                     "n° 2019-1088 hold a public authority to a risk analysis and a homologation.",
    "france-e-invoicing": "money: the DGFiP e-invoicing and e-reporting reform of impots.gouv.fr covers the invoices "
                          "and the transaction and payment data of businesses liable to French VAT.",
    "web-accessibility": "the user interface: WCAG 2.2, through EN 301 549, is the test of Directive (EU) 2016/2102 "
                         "and of the accessibility requirements a customer-facing screen meets.",
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


def rule_not_concerned(task: dict, pack_id: str, rule_id: str, packs: dict | None = None) -> str:
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


def judge_rules(task: dict, profile: dict, relevance: dict | None = None) -> dict[str, dict]:
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
                 "cyber-resilience-act", "incident-notification", "france-public-sector-security"),
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


def _git_lines(root: Path, *args: str) -> list[str] | None:
    try:
        completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False,
                                   encoding="utf-8", errors="replace")
    except OSError:
        return None
    if completed.returncode:
        return None
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def changed_files(root: Path, task: dict) -> list[str] | None:
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
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard")
    if untracked is None:
        return None
    return sorted({name for name in [*tracked, *untracked] if not name.startswith(".openguildkit/")})


def _answer_list(answers: dict, key: str) -> list[str]:
    value = answers.get(key)
    return [value] if isinstance(value, str) else list(value or [])


def _mentioned(task: dict, subject: str) -> bool:
    """Whether the brief or a free-text answer names a subject of MENTIONS, as the routing reads a trigger."""
    answers = task.get("answers", {})
    texts = [task.get("brief", ""), *(answers.get(field, "") for field in ("context", *FOLLOW_UPS))]
    return any(trigger_matches({"subject": {"triggers": list(MENTIONS[subject])}}, text) for text in texts if text)


def _fact_met(task: dict, key: str, values: list[str]) -> bool:
    """A condition on what the task consults or says rather than on an answer: never left open."""
    if key == "boards":
        return bool(set(values) & set(task.get("consultation", {}).get("boards", [])))
    return any(_mentioned(task, subject) for subject in values)


def _alternative_met(task: dict, condition: dict) -> tuple[bool, bool]:
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


def condition_met(task: dict, alternatives: list[dict]) -> tuple[bool, bool]:
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


def _answers_text(task: dict, alternatives: list[dict] | None = None) -> str:
    """The task's answers a subject reads, and the boards it consults when the subject depends on them."""
    answers = task.get("answers", {})
    shown = [f"{key} {'/'.join(_answer_list(answers, key)) or 'not answered'}"
             for key in ("kind", "surface", "data", "concerns")]
    if any("boards" in condition for condition in alternatives or []):
        shown.append(f"boards {'/'.join(task.get('consultation', {}).get('boards', [])) or 'none'}")
    return ", ".join(shown)


def _component_prefixes(components: list[str], profile: dict) -> list[str] | None:
    """Each component's path relative to the project, without slashes around it; None when one has no path."""
    paths = {item["id"]: item.get("path") for item in profile.get("components", [])}
    if any(not paths.get(component) for component in components):
        return None
    return [PurePosixPath(paths[component].strip()).as_posix().strip("/") for component in components]


def _at_root(components: list[str], profile: dict) -> bool:
    prefixes = _component_prefixes(components, profile)
    return bool(prefixes) and any(prefix in ("", ".") for prefix in prefixes)


def _in_components(changed: list[str], components: list[str], profile: dict) -> bool | None:
    """Whether a changed file lies in one of the components; None when a component has no path.

    A component at the project root (path "." or "") holds every file.
    """
    prefixes = _component_prefixes(components, profile)
    if prefixes is None:
        return None
    if any(prefix in ("", ".") for prefix in prefixes):
        return bool(changed)
    return any(name.startswith(prefix + "/") for name in changed for prefix in prefixes)


def _origins(pack_id: str, profile: dict, catalog: dict) -> list[dict]:
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


def _structure(origin: dict, task: dict, profile: dict, changed: list[str] | None) -> tuple[bool, bool, str]:
    """Whether the way a pack came still holds for this task: the role's board, the component's files."""
    answers = task.get("answers", {})
    kind = origin["kind"]
    if kind == "method":
        boards = task.get("consultation", {}).get("boards", [])
        if not [role for role in origin["roles"] if role in boards]:
            return False, False, (f"method {origin['pattern']} came for the {', '.join(origin['roles'])} role(s), "
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


def _judge_with_subject(pack_id: str, origins: list[dict], task: dict, profile: dict,
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


def _judge(origin: dict, pack_id: str, task: dict, profile: dict, changed: list[str] | None) -> tuple[bool, bool, str]:
    """For a pack of the project's own catalog: whether one origin makes it concern the task, and why not."""
    if origin["kind"] == "regulation":
        met, named = condition_met(task, REGULATION_DEFAULT)
        why = (f"regulation pattern {origin['pattern']}, which applies when the task's "
               f"{_condition_text(REGULATION_DEFAULT)}")
        return met, named, why if met else f"{why}; the task's answers say otherwise"
    return _structure(origin, task, profile, changed)


def pack_relevance(task: dict, profile: dict, catalog: dict, changed: list[str] | None, every: bool = False) -> dict:
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
