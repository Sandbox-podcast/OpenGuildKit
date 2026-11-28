"""Reads the organization policy (`policy.json` of the organization catalog) at the pinned commit, or at the commit
`guard --ci --org-policy` is given, and lists where a profile is under its minimum or frozen.

The security or platform team writes `policy.json` at the root of the organization catalog (org_catalog.py). A
project reads it at the commit a person pinned at a terminal with `org-catalog set`, and `guard --ci` reads it at the
commit the organization's required workflow gives as `--org-policy PATH --org-commit SHA`, which no pull request
carries. It may require a guard mode, signed approvals, the separation of requester and approver, and packs; and it
may freeze every repository (#481), which only a commit of the policy lifts. A repository may be stricter, never less
strict: `profile` refuses a change that goes under the minimum, `check` and `guard --ci` fail a project under it.

    {"schema_version": 1, "minimum": {"guard": "enforce", "approval": "signed", "separate_requester": true},
     "required": {"packs": ["secure-sdlc"]}, "frozen": {"by": "SEC", "reason": "WHY", "since": "2026-11-28"}}

A project that follows no organization catalog, or one whose commit has no policy.json, reads nothing more.

Entry: parse, pinned, gaps, findings, refuse_lowering, ci_problems
Tests: tests/test_org_policy.py
"""

import json
from pathlib import Path
from typing import NoReturn

from . import requester
from .lock import read_lock
from .org_catalog import POLICY_FILE, copies_read_from, organization_in, read_files
from .project import STATE_DIR
from .project_rules import resolved_profile
from .storage import read_json

GUARD_ORDER = ("off", "observe", "enforce")
FIELDS = {"schema_version", "minimum", "required", "frozen"}
MINIMUM = {"guard": ("observe", "enforce"), "approval": ("signed",), "separate_requester": (True,)}
FROZEN_FIELDS = {"by", "reason", "since"}
PERSON = "--by INITIALS --reason WHY"


def parse(data: bytes, commit: str) -> dict:
    """The policy file read at a commit, validated, with the commit it was read at."""
    where = f"{commit[:12]}:{POLICY_FILE}"
    try:
        policy = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError(f"{where} is not valid JSON. Fix it in the organization catalog.") from None

    def refuse(problem: str) -> NoReturn:
        raise ValueError(f"{where}: {problem}. Fix it in the organization catalog, then pin the new commit.")

    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        refuse('it must be an object with "schema_version": 1')
    unknown = sorted(policy.keys() - FIELDS)
    if unknown:
        refuse(f"unknown field {', '.join(unknown)}; a policy holds {', '.join(sorted(FIELDS))}")
    minimum = policy.get("minimum", {})
    if not isinstance(minimum, dict) or any(key not in MINIMUM or value not in MINIMUM[key]
                                            for key, value in minimum.items()):
        refuse('minimum may hold guard ("observe" or "enforce"), approval ("signed") and separate_requester (true)')
    required = policy.get("required", {})
    packs = required.get("packs", []) if isinstance(required, dict) else None
    if packs is None or required.keys() - {"packs"} or not isinstance(packs, list) \
            or not all(isinstance(item, str) and item for item in packs):
        refuse("required may hold packs, a list of pack IDs")
    frozen = policy.get("frozen")
    if frozen is not None and (not isinstance(frozen, dict) or frozen.keys() != FROZEN_FIELDS
                               or not all(isinstance(value, str) and value.strip() for value in frozen.values())):
        refuse("frozen must name by, reason and since")
    return {"commit": commit, "minimum": minimum, "packs": packs, "frozen": frozen}


def from_read(read: dict | None) -> dict | None:
    """The policy among the files org_catalog.read_files read, or None when the commit has none."""
    files = read["files"].get(POLICY_FILE) if read else None
    return parse(files[0][1], read["commit"]) if read and files else None


def pinned(lock: dict | None, state: Path) -> dict | None:
    """The policy at the commit the catalog lock pins; None, without running Git, for a project that pins none."""
    return from_read(organization_in(lock, state)) if (lock or {}).get("organization") else None


def given(path: str, commit: str, root: Path) -> dict:
    """The policy of the copy and commit `guard --ci --org-policy PATH --org-commit SHA` names."""
    folder = Path(path).resolve()
    policy = from_read(read_files(path, commit, root, folder))
    if policy is None:
        raise ValueError(f"Commit {commit[:12]} of {path} has no {POLICY_FILE}: give the commit of the organization "
                         "policy to --org-commit.")
    return policy


def _packs(profile: dict, catalog: dict) -> set[str]:
    try:
        return set(resolved_profile(profile, catalog)["packs"])
    except (KeyError, TypeError, ValueError, AttributeError):  # A head profile CI cannot resolve: its own list.
        return {item for item in profile.get("packs", []) if isinstance(item, str)}


def gaps(profile: dict, catalog: dict, policy: dict) -> dict[str, str]:
    """Each setting of the profile under the policy's minimum, with what it requires and the command that meets it."""
    at = f"the organization policy at {policy['commit'][:12]} requires"
    minimum, found = policy["minimum"], {}
    need, have = minimum.get("guard"), profile.get("guard", "off")
    if need and GUARD_ORDER.index(need) > GUARD_ORDER.index(have if have in GUARD_ORDER else "off"):
        found["guard"] = (f"{at} guard {need}; the profile has {have}. A person raises it: openguildkit profile set "
                          f"guard {need} {PERSON}.")
    if minimum.get("approval") == "signed" and (profile.get("approval") or {}).get("mode") != "signed":
        found["approval"] = (f"{at} signed approvals; the profile's approvals are local: openguildkit profile set "
                             f"approval signed --signers PATH --approver NAME {PERSON}.")
    if minimum.get("separate_requester") and not requester.active(profile):
        found["separate_requester"] = (f"{at} separate-requester on: openguildkit profile set separate-requester on "
                                       f"{PERSON}.")
    used = _packs(profile, catalog)
    for pack in policy["packs"]:
        if pack not in used:
            fix = (f"openguildkit profile add pack {pack} {PERSON}" if pack in catalog["packs"] else
                   "the catalog has no such pack: pin the organization catalog that provides it, openguildkit "
                   "org-catalog set --repo PATH --commit SHA")
            found[f"packs/{pack}"] = f"{at} pack {pack}, which the profile does not use: {fix}."
    return found


def frozen_text(policy: dict) -> str | None:
    frozen = policy["frozen"]
    return None if frozen is None else (
        f"the organization policy at {policy['commit'][:12]} freezes every repository, by {frozen['by']} since "
        f"{frozen['since']}: {frozen['reason']}. Only a commit of the organization policy lifts it")


def findings(profile: dict, catalog: dict, policy: dict | None) -> list[tuple[str, str]]:
    """(code of docs/sarif.md, message) for the freeze and each gap; none without a policy."""
    if policy is None:
        return []
    freeze = frozen_text(policy)
    return [*([("policy-frozen", freeze + ".")] if freeze else []),
            *[("policy-below-floor", message) for message in gaps(profile, catalog, policy).values()]]


def refuse_lowering(before: dict, after: dict, catalog: dict, lock: dict | None, state: Path) -> None:
    """Refuse a profile change that leaves the policy's minimum, even from a person at a terminal. A change that keeps
    a gap the profile already had, or closes one, goes on: the floor is never a reason to refuse raising a setting."""
    policy = pinned(lock, state)
    if policy is None:
        return
    new = {key: message for key, message in gaps(after, catalog, policy).items()
           if key not in gaps(before, catalog, policy)}
    if new:
        raise ValueError(f"Refused: {' '.join(new.values())} A repository may be stricter than the organization "
                         "policy, never less strict. Nothing was written.")


def ci_problems(copy: tuple[str, str] | None, root: Path, base_state: Path, profile: dict, catalog: dict,
                copies: dict[str, str], changed: bool) -> list[tuple[str, str]]:
    """What guard --ci fails on: the policy the option names (else the one the base revision pins) unmet by the base
    profile or by the profile the change brings, and a freeze, which fails every change."""
    with copies_read_from(root, copies):
        policy = given(*copy, root) if copy else pinned(read_lock(base_state), base_state)
    if policy is None:
        return []
    problems = [item for item in findings(profile, catalog, policy) if changed or item[0] != "policy-frozen"]
    try:
        head = read_json(root / STATE_DIR / "project.json")
    except (OSError, ValueError):
        head = None
    if isinstance(head, dict) and head != profile:
        problems += [("policy-below-floor", f"The change brings a profile under the minimum: {message}")
                     for key, message in gaps(head, catalog, policy).items()
                     if key not in gaps(profile, catalog, policy)]
    return problems
