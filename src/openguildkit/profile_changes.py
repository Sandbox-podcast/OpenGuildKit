"""How a profile changes: what weakens a protection, and the one path every change takes, from a command at a terminal
or from the web page; `profile_edits.py` holds what each change writes.

Entry: weakening_changes, write_change, save_edited, check_proposal, report_change, print_touched, Weakening,
InvalidProfile.
Tests: tests/test_profile_commands.py, tests/test_rule_decline.py, tests/test_short_lane.py, tests/test_requester.py,
tests/test_profile_reference.py.
"""

from argparse import Namespace
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import audit_log, incident, org_policy, requester
from .clock import today
from .lock import apply_lock, build_lock, installed_catalog, read_lock, write_lock
from .patterns import pattern_selection
from .profile_edits import RULE_WORD, changed_profile, lifted_paths
from .project import declined_ids, declined_rule_ids, load_profile, restricted_paths, validate_profile
from .project_instructions import sync_instructions
from .project_setup import DEFAULT_GUARD, is_norm, norm_reason, unanswered_norms
from .records import Catalog, Profile
from .sensitive import redact_credentials
from .storage import project_lock, write_json
from .tasks import tasks_touched
from .wording import plural

# Lists whose entries a person adds for protection: removing one weakens it.
REQUIRED_LISTS = (("required_rules", "required-rule", "required rule"),
                  ("required_boards", "required-board", "required board"), ("checks", "check", "check command"))


GUARD_LEVEL = {"off": 0, "observe": 1, "enforce": 2}


# How much each host enforces by itself: Claude Code also denies edits to the profile and the task records,
# Codex runs the hooks and forbids the approval commands, Gemini CLI runs the hooks and nothing else, another agent
# only reads the instructions.
HOST_LEVEL = {"other": 0, "gemini-cli": 1, "codex": 2, "claude-code": 3}


PROTECTIVE_BOARDS = ("security", "legal")


AI_PACKS = ("llm-evaluations", "nist-ai-risk", "eu-ai-act")


def protective_packs(catalog: Catalog) -> set[str]:
    """Packs whose removal weakens a protection: those of a regulation, of a security method, or about AI."""
    packs = set(AI_PACKS) | {"secure-sdlc"}
    for pattern in catalog["patterns"].values():
        security_method = "security" in pattern["roles"] and not pattern.get("match", {}).get("stack")
        if pattern.get("kind") == "regulation" or security_method:
            packs.update(pattern["packs"])
    return packs & set(catalog["packs"])


def _packs_in_force(profile: Profile, catalog: Catalog) -> set[str]:
    """The packs a profile lists or brings through its patterns, without resolving it: the page passes drafts."""
    packs = set(profile.get("packs", []))
    for entry in profile.get("patterns", []):
        if isinstance(entry, (str, dict)):
            packs.update(catalog["patterns"].get(pattern_selection(entry)[0], {}).get("packs", []))
    return packs


def _boards_in_force(profile: Profile, catalog: Catalog) -> set[str]:
    """An empty board list lets every board advise."""
    return set(profile.get("boards") or catalog["boards"])


def weakening_changes(before: Profile, after: Profile, catalog: Catalog) -> list[tuple[str, list[str]]]:
    """What a new profile weakens, each with the profile command a person types for it at a terminal: a lower
    guard, public research, a regulation that stops being active, a regulation, security or AI pack removed, the
    security or legal board removed, personal data set to no, a host whose settings enforce less, signed
    approvals turned off or on, an approver added or the signers file moved, waivers allowed or widened, a
    required rule, required board or check command removed, every rule no longer asked, a path added to the short
    lane, the separation of the requester and the approver turned on or off, a freeze lifted, the limit on the age of an
    approval raised or removed, a role of a board removed or widened, a restricted path lifted. The profile commands and
    the web page ask this."""
    person = ["--by", "INITIALS", "--reason", "WHY"]
    changes = [*_approval_changes(before, after, person), *_waiver_changes(before, after, person),
               *_light_changes(before, after, person), *_requester_changes(before, after, person),
               *_incident_changes(before, after, person), *_role_changes(before, after, person),
               *_restricted_changes(before, after, person)]
    old_guard, new_guard = before.get("guard", "off"), after.get("guard", "off")
    if GUARD_LEVEL.get(new_guard, 0) < GUARD_LEVEL.get(old_guard, 0):
        changes.append((f"guard {old_guard} -> {new_guard}", ["profile", "set", "guard", str(new_guard), *person]))
    if after.get("research") == "public-sources" and before.get("research") != "public-sources":
        changes.append(("research public-sources", ["profile", "set", "research", "public-sources", *person]))

    def active(profile: Mapping[str, Any]) -> set:
        return {pattern_selection(entry)[0] for entry in profile.get("patterns", []) if isinstance(entry, (str, dict))}

    dropped = (active(before) - active(after)) | (set(declined_ids(after)) - set(declined_ids(before)))
    for pattern_id in sorted(item for item in dropped if isinstance(item, str)):
        if catalog["patterns"].get(pattern_id, {}).get("kind") == "regulation":
            changes.append((f"regulation {pattern_id} no longer active", ["profile", "decline", pattern_id, *person]))
    removed = (_packs_in_force(before, catalog) - _packs_in_force(after, catalog)) & protective_packs(catalog)
    # A pack that leaves with a regulation reported above is part of that change.
    removed -= {pack for pattern_id in dropped if isinstance(pattern_id, str)
                for pack in catalog["patterns"].get(pattern_id, {}).get("packs", [])}
    for pack_id in sorted(removed):
        changes.append((f"protective pack {pack_id} removed", ["profile", "remove", "pack", pack_id, *person]))
    if "boards" in after:
        for board in PROTECTIVE_BOARDS:
            if board in _boards_in_force(before, catalog) - _boards_in_force(after, catalog):
                changes.append((f"board {board} no longer advises", ["profile", "remove", "board", board, *person]))
    if before.get("personal_data") is not False and after.get("personal_data") is False:
        changes.append(("personal data set to no", ["profile", "set", "personal-data", "no", *person]))
    old_host, new_host = before.get("host", "other"), after.get("host", "other")
    if HOST_LEVEL.get(new_host, 0) < HOST_LEVEL.get(old_host, 0):
        changes.append((f"host {old_host} -> {new_host}, whose settings enforce less",
                        ["profile", "set", "host", str(new_host), *person]))
    already = set(declined_rule_ids(before))
    for rule in declined_rule_ids(after):
        if rule not in already:
            changes.append((f"rule {rule} declined", ["profile", "decline", RULE_WORD, rule, *person]))
    for key, field, label in REQUIRED_LISTS:
        kept = _texts(after.get(key))
        for value in _texts(before.get(key)):
            if value not in kept:
                changes.append((f"{label} {value} removed", ["profile", "remove", field, value, *person]))
    if before.get("ask_every_rule") is True and after.get("ask_every_rule") is not True:
        changes.append(("every rule no longer asked", ["profile", "set", "ask-every-rule", "no", *person]))
    return changes


def _texts(value) -> list[str]:
    """The entries of a list of a profile, or a draft's, keeping only text."""
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _signed(profile: Profile) -> dict | None:
    """Who approves in a profile with signed approvals, or None when approvals are local."""
    approval = profile.get("approval")
    if not isinstance(approval, dict) or approval.get("mode") != "signed":
        return None
    return {"allowed_signers": str(approval.get("allowed_signers")), "approvers": _texts(approval.get("approvers"))}


def _approval_changes(before: Profile, after: Profile, person: list[str]) -> list[tuple[str, list[str]]]:
    """Signed approvals turned off, or a change of who signs: an approver added, the signers file moved, or
    signing turned on, since whoever writes that file then approves without a terminal."""
    old, new = _signed(before), _signed(after)
    if old == new:
        return []
    if new is None:
        return [("signed approvals turned off", ["profile", "set", "approval", "local", *person])]
    command = ["profile", "set", "approval", "signed", "--signers", new["allowed_signers"],
               *[word for name in new["approvers"] for word in ("--approver", name)], *person]
    if old is None:
        return [(f"signed approvals turned on: {', '.join(new['approvers'])} approve with a key listed in "
                 f"{new['allowed_signers']}", command)]
    changes = []
    added = [name for name in new["approvers"] if name not in old["approvers"]]
    if added:
        changes.append((f"approver {', '.join(added)} added", command))
    if new["allowed_signers"] != old["allowed_signers"]:
        changes.append((f"allowed signers moved from {old['allowed_signers']} to {new['allowed_signers']}", command))
    return changes


def _waiver_policy(profile: Profile) -> tuple[list[str], int] | None:
    waivers = profile.get("waivers")
    if not isinstance(waivers, dict):
        return None
    days = waivers.get("max_days")
    return _texts(waivers.get("allowed_by")), days if type(days) is int else 0


def _waiver_changes(before: Profile, after: Profile, person: list[str]) -> list[tuple[str, list[str]]]:
    """Waivers allowed where none were, or allowed to more people or for longer."""
    old, new = _waiver_policy(before), _waiver_policy(after)
    if new is None or new == old:
        return []
    names, days = new
    command = ["profile", "set", "waivers", "allowed", *[word for name in names for word in ("--allowed-by", name)],
               "--max-days", str(days), *person]
    if old is None:
        return [(f"waivers allowed, by {', '.join(names)}, for up to {days} days", command)]
    wider = [f"{name} may waive" for name in names if name not in old[0]]
    if days > old[1]:
        wider.append(f"a waiver lasts up to {days} days instead of {old[1]}")
    return [(f"waivers widened: {'; '.join(wider)}", command)] if wider else []


def _light_changes(before: Profile, after: Profile, person: list[str]) -> list[tuple[str, list[str]]]:
    """A path added to the short lane: a task there is reviewed by one board and without questions, so adding a path
    lowers the rigor of that part of the project. Fewer paths, or none, is stricter and asks nothing."""
    old, new = _texts(before.get("light_paths")), _texts(after.get("light_paths"))
    added = [path for path in new if path not in old]
    if not added:
        return []
    what = f"short lane widened: {', '.join(added)} added" if old else f"short lane turned on for {', '.join(added)}"
    return [(what, ["profile", "set", "light-paths", *new, *person])]


def _requester_changes(before: Profile, after: Profile, person: list[str]) -> list[tuple[str, list[str]]]:
    """The separation of the requester and the approver turned on or off. Either way it changes who may approve, so
    only a person turns it, at a terminal, as for signed approvals."""
    old, new = requester.active(before), requester.active(after)
    if old == new:
        return []
    if new:
        return [("requester separation turned on: task new needs --requested-by and the requester cannot approve",
                 ["profile", "set", "separate-requester", "on", *person])]
    return [("requester separation turned off: the requester of a task may approve it",
             ["profile", "set", "separate-requester", "off", *person])]


def _incident_changes(before: Profile, after: Profile, person: list[str]) -> list[tuple[str, list[str]]]:
    """A freeze lifted, or the limit on the age of an approval raised or removed (incident.py). Freezing and a shorter
    limit only restrict, so they ask nothing."""
    changes = []
    if incident.frozen(before) and not incident.frozen(after):
        changes.append(("freeze lifted: agents may edit again", ["profile", "set", "freeze", "off", *person]))
    old, new = incident.max_age_days(before), incident.max_age_days(after)
    if old is not None and (new is None or new > old):
        what = "removed" if new is None else f"raised from {old} to {new} days"
        changes.append((f"approval age limit {what}: approvals cover work for longer",
                        ["profile", "set", "max-approval-age", "none" if new is None else str(new), *person]))
    return changes


def _role_changes(before: Profile, after: Profile, person: list[str]) -> list[tuple[str, list[str]]]:
    """A role of a board (roles.py) removed, or given more people: anyone may then clear that board's blockers, or more
    people may. A new role, or fewer people in one, only restricts and asks nothing."""
    old = (before.get("approval") or {}).get("roles") or {}
    new = (after.get("approval") or {}).get("roles") or {}
    changes = []
    for board, names in old.items():
        added = [name for name in new.get(board, names) if name not in names]
        if board not in new:
            changes.append((f"role {board} removed: any approver may clear its blockers and approve",
                            ["profile", "set", "approver-roles", board, "none", *person]))
        elif added:
            changes.append((f"role {board} widened: {', '.join(added)} added",
                            ["profile", "set", "approver-roles", board, *new[board], *person]))
    return changes


def _restricted_changes(before: Profile, after: Profile, person: list[str]) -> list[tuple[str, list[str]]]:
    """A path of restricted_paths that the new profile no longer closes to the agents. Closing a path asks nothing."""
    lifted = lifted_paths(before, after)
    if not lifted:
        return []
    kept = restricted_paths(after) or ["none"]
    what = (f"{plural(len(lifted), 'restricted path')} lifted ({', '.join(lifted)}): agents may read and edit "
            f"{'it' if len(lifted) == 1 else 'them'}")
    return [(what, ["profile", "set", "restricted-paths", *kept, *person])]


def check_proposal(profile: Profile, catalog: Catalog, action: str, field: str | None, value: str) -> tuple[Profile, list[str]]:
    """The profile a command would write and what it weakens, or the ValueError the command would raise.

    action is add, remove or decline: field names the list for add and remove and is None for decline, whose value is a
    pattern, or "rule" for decline rule, whose value is PACK/RULE. Nothing is written and the profile given is left as it is: the retrospective proposes only a command that
    this accepts, and the confirmation at a terminal that a weakening needs (write_change) is still the person's.
    """
    rule = field == RULE_WORD
    args = Namespace(profile_action=action, pattern=RULE_WORD if rule else value, rule=value if rule else None,
                     field=field, values=[value], by="NAME", reason="WHY")
    edited, _ = changed_profile(profile, args, catalog)
    updated = validate_profile(edited, catalog)
    return updated, [text for text, _ in weakening_changes(profile, updated, catalog)]


class Weakening(ValueError):
    """A change that weakens a protection, refused without a person at a terminal. `changes` holds each
    protection with the profile command a person types for it."""

    def __init__(self, message: str, changes: list[tuple[str, list[str]]]):
        super().__init__(message)
        self.changes = changes


class InvalidProfile(ValueError):
    """A profile edited in the page that cannot be used, or that rewrites the history of profile changes."""


def voided_note(voided: list[str]) -> str:
    return f" It also voids the approval of {', '.join(voided)}." if voided else ""


def voided_approvals(state: Path, profile: Profile, catalog: Catalog) -> list[str]:
    """The approved tasks whose approval this profile voids, by the rule that decides whether an approval holds."""
    return [task["id"] for task in tasks_touched(state, profile, catalog) if task["status"] == "approved"]


def write_change(root: Path, state: Path, args, edit, by: str, reason: str, confirm) -> tuple[Profile, dict, Catalog]:
    """Under the project lock: apply edit to the profile, name the approvals it voids, have the person confirm what
    it weakens, record who, when and why, then write the instructions, the profile and the catalog lock. args carries
    the central policy options of the command, or is None for the web page."""
    with project_lock(state):
        live, bundled = installed_catalog(args, state)
        lock = read_lock(state)
        catalog = apply_lock(live, lock)
        profile = load_profile(state, catalog)
        edited, change = edit(profile, catalog)
        updated = validate_profile(edited, catalog)
        org_policy.refuse_lowering(profile, updated, catalog, lock, state)  # Even at a terminal (RFC #452).
        weakened = weakening_changes(profile, updated, catalog)
        voided = voided_approvals(state, updated, catalog)
        if weakened:
            confirm(change, weakened, voided)
        elif voided:
            print(f"This change voids the approval of {', '.join(voided)}: each is consulted again before its work "
                  "goes on.", flush=True)
        record = {"change": change, "by": by, "on": today().isoformat(), "reason": reason}
        updated = validate_profile({**updated, "changes": [*profile.get("changes", []), record]}, catalog)
        sync_instructions(root, updated, catalog)
        write_json(state / "project.json", updated)
        write_lock(state, build_lock(updated, catalog, bundled, lock))
    audit_log.record(root, "profile.changed", by=by, change=updated["changes"][-1]["change"])
    return updated, updated["changes"][-1], catalog


def print_touched(tasks: list[dict], before: bool = False) -> None:
    """The tasks a change of rules touches, in the same words for update, update --apply, sync and profile changes."""
    if not tasks:
        return
    print("Tasks this change touches:" if before else "Tasks consulted under the previous rules:")
    for task in tasks:
        print(f"  {task['id']} ({task['status']}): {task['step']}.")


def report_change(state: Path, updated: Profile, record: dict, catalog: Catalog, host_settings: bool) -> None:
    """What follows a change: the norms it brings, the host settings to apply, the tasks it touches."""
    print(f"Profile changed: {record['change']}, by {record['by']} on {record['on']}. AGENTS.md is up to date.")
    for norm in unanswered_norms(updated, catalog, {}):
        pattern = catalog["patterns"][norm["id"]]
        print(f"  Norm {norm['id']} now concerns the project ({norm_reason(pattern)}) and is not active: ask the "
              f"person, then openguildkit profile adopt {norm['id']} or decline {norm['id']}, with --by and --reason.")
    if host_settings:
        print("  Run openguildkit host apply, then openguildkit host check, so the host settings follow.")
    touched = tasks_touched(state, updated, catalog)
    print_touched(touched)
    if not touched:
        print("No open task was consulted under the previous profile.")


PERSON = "--by INITIALS --reason WHY"


def _yes_no(value: object) -> str:
    """A saved yes or no as init --answers reads it; unsure when the profile never answered."""
    return "unsure" if value is None else "yes" if value else "no"


def export_answers(profile: Profile, catalog: Catalog) -> tuple[dict, list[str]]:
    """The init --answers file that sets up another repository with this profile's rules, and what the person types
    there for each setting that is left out because it names someone or lowers a protection.

    Carried: sector, stack, roles, the answers on personal data, the patterns and packs as they are, the boards,
    required boards and rules, the host and guard when they do not lower the default, the research policy when it is
    local, the conventions and the pack resolutions, without credentials. A declined norm comes back as yes: declining
    it again is the person's decision, recorded with their name.
    """
    answers: dict = {"sector": profile["sector"], "stack": profile["stack"]}
    if profile.get("roles"):
        answers["roles"] = profile["roles"]
    answers["personal_data"] = _yes_no(profile.get("personal_data"))
    if "people_decisions" in profile:
        answers["people_decisions"] = _yes_no(profile["people_decisions"])
    declined_norms = [pattern_id for pattern_id in declined_ids(profile)
                      if is_norm(catalog["patterns"].get(pattern_id, {}))]
    if declined_norms:
        answers["norms"] = dict.fromkeys(declined_norms, "yes")
    # Component scopes name this repository's folders: each pattern applies to the whole new project.
    answers["patterns"] = list(dict.fromkeys(pattern_selection(entry)[0] for entry in profile.get("patterns", [])))
    answers.update(packs=profile["packs"], replace_default_packs=True, boards=profile["boards"])
    for key in ("required_boards", "required_rules"):
        if profile.get(key):
            answers[key] = profile[key]
    if profile.get("ask_every_rule"):
        answers["ask_every_rule"] = True
    if profile.get("tools"):
        answers["tools"] = profile["tools"]
    commands = "; ".join(f"openguildkit profile decline {norm} {PERSON}" for norm in declined_norms)
    steps = [f"Declined norms come back active: {', '.join(declined_norms)}. The person declines each again at a "
             f"terminal there: {commands}."] if declined_norms else []
    declined_rules = declined_rule_ids(profile)
    if declined_rules:
        commands = "; ".join(f"openguildkit profile decline rule {rule} {PERSON}" for rule in declined_rules)
        steps.append(f"Declined rules come back in force: {', '.join(declined_rules)}. The person declines each again "
                     f"at a terminal there: {commands}.")
    if profile.get("host", "other") != "other":
        answers["host"] = profile["host"]
    guard = profile.get("guard", "off")
    if GUARD_LEVEL.get(guard, 0) >= GUARD_LEVEL[DEFAULT_GUARD]:
        answers["guard"] = guard
    else:
        steps.append(f"guard {guard} is not carried: the new project starts at {DEFAULT_GUARD}. To lower it, the "
                     f"person runs openguildkit profile set guard {guard} {PERSON} at a terminal there.")
    if profile.get("research") == "public-sources":
        steps.append("Public research is not carried: the person runs openguildkit profile set research "
                     f"public-sources {PERSON} at a terminal there.")
    else:
        answers["research"] = "local-only"
    answers["conventions"] = [redact_credentials(text) for text in profile.get("conventions", [])]
    if profile.get("resolutions"):
        answers["resolutions"] = [{**item, "reason": redact_credentials(item["reason"])}
                                  for item in profile["resolutions"]]
    if _signed(profile):
        steps.append("Signed approvals are not carried: the person runs openguildkit profile set approval signed "
                     f"--signers PATH --approver NAME {PERSON} at a terminal there.")
    if _waiver_policy(profile):
        steps.append("Waivers are not carried: the person runs openguildkit profile set waivers allowed --allowed-by "
                     f"NAME --max-days DAYS {PERSON} at a terminal there.")
    if (profile.get("approval") or {}).get("roles"):
        steps.append("The roles of the boards are not carried: the person runs openguildkit profile set approver-roles "
                     f"BOARD NAME... {PERSON} at a terminal there.")
    if incident.max_age_days(profile):
        steps.append("The limit on the age of an approval is not carried: the person runs openguildkit profile set "
                     f"max-approval-age DAYS {PERSON} at a terminal there.")
    if requester.active(profile):
        steps.append("Requester separation is not carried: the person runs openguildkit profile set separate-requester "
                     f"on {PERSON} at a terminal there.")
    if profile.get("light_paths"):
        steps.append("The short lane is not carried: the person runs openguildkit profile set light-paths GLOB "
                     f"{PERSON} at a terminal there.")
    return answers, _organization_steps(catalog) + steps


def _organization_steps(catalog: Catalog) -> list[str]:
    """What profile export says of the organization catalog (RFC #446): it is pinned in the lock, not the answers."""
    organization = catalog.get("organization")
    if organization is None:
        return []
    steps = [f"The organization catalog is not carried: before init there, the person runs openguildkit org-catalog "
             f"set --repo PATH --commit {organization['commit']} {PERSON} at a terminal, PATH being their copy."]
    if organization["replaced"]:
        steps.append(f"This project's own records that replace organization records stay here: "
                     f"{', '.join(organization['replaced'])}.")
    return steps


def save_edited(root: Path, state: Path, edited: dict, by: str, reason: str) -> None:
    """Save a whole profile edited in the web page by the same path as the commands. The page sends the history of
    changes as it is and the change is recorded after it; a change that weakens a protection is refused, with the
    profile command a person types for it."""
    changed: list[str] = []

    def edit(profile: Profile, catalog: Catalog) -> tuple[Profile, str]:
        try:
            candidate = validate_profile(edited, catalog)
        except ValueError as error:
            raise InvalidProfile(str(error)) from None
        # The history sent must be the saved one: the server adds the entry of this change itself. A page that
        # read the profile before another command changed it sends an older history and would undo that change.
        if candidate.get("changes", []) != profile.get("changes", []):
            raise InvalidProfile("The history of profile changes (changes) differs from the saved one: the profile "
                                 "changed since the page read it, or the page edited its history. Reload the profile "
                                 "and make the change again. Nothing was written.")
        fields = sorted(key for key in {*profile, *candidate} - {"changes"} if profile.get(key) != candidate.get(key))
        if not fields:
            raise ValueError("The profile is unchanged. Nothing was written.")
        changed.extend(fields)
        return candidate, f"edit {', '.join(fields)} from the web page"

    def refuse(change: str, weakened: list[tuple[str, list[str]]], voided: list[str]) -> None:
        what = "; ".join(text for text, _ in weakened)
        raise Weakening(f"{what}: this weakens a protection, which is the person's decision at an interactive "
                        f"terminal.{voided_note(voided)} Nothing was written.", weakened)

    updated, record, catalog = write_change(root, state, None, edit, by, reason, refuse)
    report_change(state, updated, record, catalog,
                  bool({"host", "guard", "research", "approval", "restricted_paths"} & set(changed)))
