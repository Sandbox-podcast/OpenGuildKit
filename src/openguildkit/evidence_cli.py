"""The `evidence` commands: `export` gathers the decisions with the state of their seal and signature, the profile
changes, the history of the signers file, the alerts and the controls of a period into a dossier with a manifest of
SHA-256, `verify` recomputes it. Reads the project and states no conformity.

`export` gathers, for a period, what the tool already knows: the exported decisions with the state of their seal and of
their signature, the profile changes, the history of the allowed signers file in Git, the alerts, the registry of
controls and a manifest with the SHA-256 of each file. It reads the project, writes only a new folder inside it and
states no conformity to any framework. `verify` recomputes the manifest of a dossier.
Entry: add_parser, run.
Tests: tests/test_evidence.py, tests/test_command_output_budget.py.
"""

import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from . import clock, git
from .alerts import load_register
from .catalog import package_file
from .command import Command
from .decisions import approval_policy, export_digest, exported_records, git_revision, seal, verify_recorded_signature
from .errors import OgkError
from .guard_records import exported_decisions
from .lock import LOCK_FILE, package_version, project_catalog
from .project import STATE_DIR, load_profile
from .project_rules import Fingerprints
from .records import Catalog, Profile
from .storage import file_sha256, json_text, read_json, write_text

DOSSIER_FILES = ("alerts.jsonl", "controls.json", "decisions.jsonl", "profile-changes.jsonl", "signers-history.jsonl")
MANIFEST = "MANIFEST.json"
STATEMENT = ("These files hold facts that OpenGuildKit read from the project. They do not state that the project, the "
             "organization or OpenGuildKit complies with any framework.")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def add_parser(commands) -> None:
    evidence = commands.add_parser(
        "evidence", help="Gather the decisions, signatures and settings of a period into a dossier for an auditor, and "
                         "check that it was not changed. States no conformity.")
    actions = evidence.add_subparsers(dest="evidence_action", required=True)
    export = actions.add_parser("export", help="Write the dossier into a new folder of the project. Reads the project.")
    export.add_argument("--output", type=Path, required=True, metavar="DOSSIER",
                        help="New or empty folder inside the project, outside .openguildkit/.")
    export.add_argument("--since", help="First day of the period, YYYY-MM-DD (UTC).")
    export.add_argument("--until", help="Last day of the period, YYYY-MM-DD (UTC).")
    verify = actions.add_parser("verify", help="Recompute the manifest of a dossier: exit 1 when a file changed.")
    verify.add_argument("dossier", type=Path, help="The folder `evidence export` wrote, from the project root unless absolute.")


def run(command: Command) -> int:
    args, root, state = command.args, command.root, command.state
    if args.evidence_action == "verify":
        return _verify(args.dossier if args.dossier.is_absolute() else root / args.dossier)
    since, until = _day(args.since, "--since"), _day(args.until, "--until")
    if since and until and since > until:
        raise ValueError("--since is after --until: the period holds no day.")
    from .deliverables import project_path  # Only this command writes a folder the team may share.

    target = project_path(root, state, args.output, "--output")
    shown = target.relative_to(root.resolve()).as_posix()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise OgkError("OGK-EVIDENCE-001", f"--output {shown} already holds files: give a new folder, or an empty one. Nothing was written.")
    catalog = project_catalog(args, state)
    profile = load_profile(state, catalog)
    notes = []
    lists = {"decisions.jsonl": _decisions(root, state, profile, catalog, since, until),
             "profile-changes.jsonl": [dict(entry) for entry in profile.get("changes", [])
                                       if _within(entry.get("on"), since, until)],
             "alerts.jsonl": _alerts(state, since, until)}
    lists["signers-history.jsonl"], note = _signers(root, profile, since, until)
    notes += [note] if note else []
    files = {name: "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
             for name, rows in lists.items()}
    files["controls.json"] = package_file("registry", "controls.json").read_bytes()
    files = {name: files[name] for name in DOSSIER_FILES}  # The files written are the files declared, in their order.
    manifest = _manifest(root, state, profile, catalog, files, (since, until), notes)
    target.mkdir(parents=True, exist_ok=True)
    for name, data in {**files, MANIFEST: json_text(manifest).encode("utf-8")}.items():
        write_text(target / name, data.decode("utf-8"))
    counts = ", ".join(f"{len(rows)} {word}{'' if len(rows) == 1 else 's'}" for rows, word in (
        (lists["decisions.jsonl"], "decision"), (lists["profile-changes.jsonl"], "profile change"),
        (lists["alerts.jsonl"], "alert line"), (lists["signers-history.jsonl"], "signers commit")))
    print(f"Dossier written to {shown}: {counts}. Check it later with openguildkit evidence verify {shown}.")
    for note in notes:
        print(f"Note: {note}")
    return 0


def _day(value: str | None, option: str) -> str | None:
    if value is None:
        return None
    try:
        if DAY.fullmatch(value):
            date.fromisoformat(value)
            return value
    except ValueError:
        pass
    raise OgkError("OGK-EVIDENCE-002", f"{option} must be a day written YYYY-MM-DD.")


def _within(day: object, since: str | None, until: str | None) -> bool:
    """Whether a day (or the start of a timestamp) is in the period; a record with no day is in none, unless the period is open."""
    if since is None and until is None:
        return True
    if not isinstance(day, str) or not DAY.fullmatch(day[:10]):
        return False
    return (since is None or day[:10] >= since) and (until is None or day[:10] <= until)


def _sha256(path: Path) -> str | None:
    try:
        return file_sha256(path)
    except OSError:
        return None


def _decisions(root: Path, state: Path, profile: Profile, catalog: Catalog, since: str | None, until: str | None) -> list[dict]:
    """One line for each exported decision record dated in the period, and one for each file of the folder that cannot be
    read, oldest first."""
    judged = {row["path"]: row for row in exported_decisions(root, state, profile, Fingerprints(profile, catalog))}
    policy, rows = approval_policy(profile), []
    for path, record in exported_records(state):
        relative = path.relative_to(root).as_posix()
        found = judged.get(relative, {})
        base = {"record": relative, "record_file_sha256": _sha256(path), "task": path.stem}
        if record is None or found.get("status") == "unreadable" or not isinstance(record.get("decision"), dict):
            rows.append({**base, "state": "unreadable", "decided_at": None, "holds": False, "problem": found.get("problem")})
            continue
        decision = record["decision"]
        if not _within(decision.get("at"), since, until):
            continue
        rows.append({
            **base, "task": record["task"], "state": "readable", "status": found.get("status", record.get("status")),
            "completed": found.get("completed"), "decided_at": decision.get("at"), "decided_by": decision.get("by"),
            "reason": decision.get("reason"), "requested_by": record.get("requested_by"), "seal": _seal(decision),
            "record_digest": _digest_state(record), "signature": _signature(root, policy, decision),
            "withdrawn": record.get("withdrawn") if isinstance(record.get("withdrawn"), dict) else None,
            "holds": found.get("problem") is None, "problem": found.get("problem")})
    return sorted(rows, key=lambda row: (row["decided_at"] is None, row["decided_at"] or "", row["record"]))


def _seal(decision: dict) -> dict:
    """The seal an approval carries, and whether it still covers the payload it was given over."""
    payload, value = decision.get("payload"), decision.get("seal")
    if not isinstance(payload, dict) or not isinstance(value, str):
        return {"value": value if isinstance(value, str) else None, "state": "missing"}
    return {"value": value, "state": "holds" if seal(payload) == value else "broken"}


def _digest_state(record: dict) -> str:
    recorded = record.get("record_sha256")
    return "absent" if recorded is None else "holds" if recorded == export_digest(record) else "broken"


def _signature(root: Path, policy: dict, decision: dict) -> dict:
    """Whether the approval is signed, whether the project requires it, and what the signers file says of the signature."""
    signature, signer, payload = decision.get("signature"), decision.get("signer"), decision.get("payload")
    required = policy["mode"] == "signed"
    if not isinstance(signature, str) or not isinstance(signer, str):
        return {"required": required, "state": "unsigned", "signer": None, "detail": None}
    if not required:
        return {"required": False, "state": "not-checked", "signer": signer,
                "detail": "the project does not require signed approvals now, so no signers file is read"}
    try:
        if not isinstance(payload, dict):
            raise ValueError("the record carries no approval payload")
        earlier = verify_recorded_signature(root, policy, payload, signature, signer)
    except ValueError as error:
        return {"required": True, "state": "not-verified", "signer": signer, "detail": str(error)}
    return {"required": True, "state": "verified" if earlier is None else "verified-earlier-signers", "signer": signer,
            "detail": None if earlier is None else f"verified against the signers of revision {earlier}"}


def _alerts(state: Path, since: str | None, until: str | None) -> list[dict]:
    """The alerts of the register as they stand, those with a dated event in the period (the register keeps the latest
    decision on an alert, not each step), then the scanner imports of the period."""
    register = load_register(state)
    imports = [{"kind": "import", **entry} for entry in register.get("imports", [])
               if _within(entry.get("date"), since, until)]
    alerts = []
    for alert in register["alerts"]:
        nested = [alert.get(key, {}).get("at") if isinstance(alert.get(key), dict) else None
                  for key in ("accepted", "severity_set")]
        days = [alert.get("first_seen"), alert.get("last_seen"), alert.get("decided_at"), alert.get("resolved_on"), *nested]
        if any(_within(day, since, until) for day in days):
            alerts.append({"kind": "alert", **alert})
    return [*sorted(alerts, key=lambda alert: alert["id"]), *imports]


def _signers(root: Path, profile: Profile, since: str | None, until: str | None) -> tuple[list[dict], str | None]:
    """The commits of the period that changed the allowed signers file, oldest first: the principals the file listed
    and its object ID, never a key. The reason it is empty when it cannot be filled."""
    policy = approval_policy(profile)
    if policy["mode"] != "signed":
        return [], "signers-history.jsonl is empty: the project does not require signed approvals."
    relative = Path(policy["allowed_signers"]).as_posix()
    listing = git.text(root, "log", "--reverse", "--format=%H %ct", "--", relative)
    if listing is None:
        return [], "signers-history.jsonl is empty: the project is not in a Git repository, or git is missing."
    rows = []
    for line in listing.splitlines():
        commit, seconds = line.split()
        moment = datetime.fromtimestamp(int(seconds), UTC)
        if not _within(moment.date().isoformat(), since, until):
            continue
        text, blob = git.text(root, "show", f"{commit}:./{relative}"), git.text(root, "rev-parse", f"{commit}:./{relative}")
        words = [text_line.split()[0] for text_line in (text or "").splitlines()
                 if text_line.strip() and not text_line.lstrip().startswith("#")]
        rows.append({"commit": commit, "committed_at": moment.isoformat(timespec="seconds"),
                     "principals": sorted({name for word in words for name in word.split(",")}),
                     "blob": blob.strip() if blob else None})
    return rows, None


def _manifest(root: Path, state: Path, profile: Profile, catalog: Catalog, files: dict, period: tuple, notes: list) -> dict:
    policy = approval_policy(profile)
    return {
        "schema_version": 1, "openguildkit": package_version(), "generated": clock.today().isoformat(),
        "project": git_revision(root) or {"commit": None, "dirty": None},
        "period": {"since": period[0], "until": period[1]},
        "profile": {"name": profile.get("name"), "guard": profile.get("guard", "off"), "host": profile.get("host", "other"),
                    "approvals": policy["mode"], "separate_requester": profile.get("separate_requester") is True,
                    "rules_fingerprint": Fingerprints(profile, catalog).current},
        "state_files": {f"{STATE_DIR}/{name}": digest for name in ("project.json", LOCK_FILE)
                        if (digest := _sha256(state / name))},
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in sorted(files.items())},
        "notes": notes, "statement": STATEMENT,
    }


def _verify(dossier: Path) -> int:
    """Recompute the SHA-256 of each file the manifest lists, and name the files that differ, are missing, are not plain
    files of the folder, or are in the folder without being in the manifest."""
    path = dossier / MANIFEST
    if not path.is_file():
        raise OgkError("OGK-EVIDENCE-003", f"{path.as_posix()} is not there: name the folder that `evidence export` wrote.")
    manifest = read_json(path)
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict):
        raise ValueError(f"{path.as_posix()} is not the manifest of a dossier: it lists no files.")
    problems = []
    for name, entry in sorted(files.items()):
        target = dossier / name
        if Path(name).name != name or name in ("", ".", "..", MANIFEST) or target.is_symlink():
            problems.append(f"{name}: not a file of the dossier")
        elif not target.is_file():
            problems.append(f"{name}: missing")
        elif not isinstance(entry, dict) or entry.get("sha256") != _sha256(target):
            problems.append(f"{name}: changed")
    problems += [f"{child.name}: not in the manifest" for child in sorted(dossier.iterdir())
                 if child.name != MANIFEST and child.name not in files]
    for problem in problems:
        print(problem)
    if problems:
        print(f"OpenGuildKit: the dossier differs from its manifest in {len(problems)} place"
              f"{'' if len(problems) == 1 else 's'}.", file=sys.stderr)
        return 1
    print(f"{len(files)} files match the manifest. {MANIFEST} sha256: {_sha256(path)}")
    return 0
