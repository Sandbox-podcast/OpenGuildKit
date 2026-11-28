"""Runs `ci-check`: the decision records of a change, against its base commit, the files it touches and the guard workflow."""

import calendar
import io
import os
import time
from pathlib import Path, PurePosixPath

from . import incident, short_lane
from .decisions import CLOCK_SKEW, DECISIONS_DIR, approval_policy
from .guard import guard_mode
from .guard_export import conflict_message, record_shape
from .guard_records import record_check
from .project import STATE_DIR, load_profile
from .startup import UNKNOWN_MODE, declared_mode
from .storage import file_sha256, parse_json, read_json

_NEEDS_GIT = "guard --ci"  # What a missing Git stops (git.required).


def _git_lines(root: Path, command: str, *args: str) -> list[str]:
    """The file names a Git command lists, as they are on disk (-z)."""
    from . import git

    result = git.required(root, command, "-z", *args, needs=_NEEDS_GIT)
    if result.returncode:
        raise ValueError(f"git {command} {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return [line for line in git.split_names(result.stdout) if line.strip()]


def _base_files(root: Path, base: str, names: list[str]) -> dict[str, bytes]:
    """The content of files of the base revision, by name; a name the base does not hold as a file is left out.

    One git cat-file process reads them all, however many records the base holds: one git show per file took 23.5 s
    at 990 decisions (issue #532)."""
    from . import git

    # cat-file reads one name per line, and git ls-tree quotes a name that holds a newline.
    names = [name for name in names if not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
             and "\n" not in name]
    if not names:
        return {}
    asked = "".join(f"{base}:{name}\n" for name in names).encode("utf-8")
    output = io.BytesIO(git.required(root, "cat-file", "--batch", stdin=asked, needs=_NEEDS_GIT).stdout)
    files = {}
    for name in names:
        # "<object> <type> <size>", then the content and a newline; or "<name> missing" alone.
        header = output.readline().rstrip(b"\n").rsplit(b" ", 2)
        if len(header) != 3 or not header[2].isdigit():
            continue
        content = output.read(int(header[2]) + 1)
        if len(content) != int(header[2]) + 1:
            break  # git stopped within the file
        if header[1] == b"blob":
            files[name] = content[:-1]
    return files


def _extract_base(root: Path, base: str, directory: Path, names: list[str]) -> None:
    """Copy files of the base revision into directory, at the same relative paths."""
    for name, content in _base_files(root, base, names).items():
        target = directory / PurePosixPath(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _earlier_records(files: dict[str, bytes]) -> dict:
    """The exported decisions of the base revision, by task, at any depth below the decisions folder, as the change's
    own records are found: a record merged in a subfolder still binds its approval. The record in the folder itself
    comes first when a task has several. files holds the base revision's records by name, read in memory: writing
    them to disk and reading them back took 3 s at 990 decisions (issue #532)."""
    folder = PurePosixPath(STATE_DIR, DECISIONS_DIR)
    records = {}
    for name in sorted(files, key=lambda item: (PurePosixPath(item).parent != folder, item)):
        try:
            record = parse_json(files[name], name)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("task"), str):
            records.setdefault(record["task"], record)
    return records


def _no_base_profile(root: Path) -> str:
    """Why nothing is enforced on a base without a profile, and the mode that applies once the profile is merged."""
    if not (root / STATE_DIR / "project.json").is_file():
        return ("The base revision has no OpenGuildKit profile and neither does this change: nothing to enforce. "
                "Run openguildkit init to add one.")
    expected = ("The base revision has no OpenGuildKit profile: nothing is enforced, which is expected for the pull "
                "request that adds it.")
    mode = declared_mode(root)
    if mode == UNKNOWN_MODE:
        return f"{expected} The profile of this change cannot be read: fix it before it is merged."
    return (f"{expected} The guard reads its mode from the base revision, so once the profile is merged the next pull "
            f'requests are checked with the mode it sets ("guard": "{mode}" in this change).')


def _local_records() -> str:
    from .doc_links import doc_link

    return ("Approvals on the base revision are local: CI recomputes each record's seal, but whoever can write a record "
            "can recompute it too, so nothing here proves who approved. Require signed approvals "
            f"({doc_link('docs/workflow.md', 'signed-approvals')})")


WORKFLOW_DIR = ".github/workflows/"


GUARD_STEP = "openguildkit guard --ci"


def _shown_files(paths: list[str], limit: int = 10) -> str:
    return ", ".join(paths[:limit]) + (f" and {len(paths) - limit} more" if len(paths) > limit else "")


def _uncovered(work: list[str], covers: dict) -> str | None:
    """The changed files that no valid record of the change covers, as one problem; None when each is covered.

    covers maps each valid record's task to the files it covers, None when it lists none.
    """
    from . import git
    from .wording import plural

    listed = {git.unquote(path) for files in covers.values() for path in files or []}
    missing = [path for path in work if path not in listed]
    if not missing:
        return None
    unlisted = [task for task, files in covers.items() if files is None]
    detail = (f" The {'record' if len(unlisted) == 1 else 'records'} of {', '.join(unlisted)} "
              f"{'lists' if len(unlisted) == 1 else 'list'} no files: approved before the project had a Git revision, "
              "or exported by an earlier release." if unlisted else "")
    return (f"{plural(len(missing), 'changed file')} {'is' if len(missing) == 1 else 'are'} in no decision record of this "
            f"change: {_shown_files(missing)}. A record "
            "covers the files Git tracks that changed since its approval when it is exported: export it again once the "
            "work is committed (openguildkit task export ID), or open a task for this change." + detail)


def _lane_fault(record: dict, files: list[str] | None, light: list[str], base: str) -> str | None:
    """Why a short-lane record cannot cover the change: the base revision has no light_paths (a change cannot turn on
    the lane it is judged by), or a file the record lists is outside its paths or the base revision's light_paths. The
    files a record covers are those of its base version when the base holds the same approval."""
    if record.get("lane") != short_lane.LANE:
        return None
    where = f"the base revision {base}"
    if not light:
        return short_lane.off_message(record["task"], where)
    outside = short_lane.files_outside(record["paths"], light, files or [])
    return short_lane.outside_message(record["task"], record["paths"], light, outside, where) if outside else None


def _signed_late(root: Path, base: str, record: dict, relative: str) -> str | None:
    """Why a new record cannot be true: its approval says it was signed (signed_at) after the commit of the change that
    first carries the record, the clocks of two machines allowed to differ by CLOCK_SKEW."""
    from . import git

    moment = (record["decision"].get("payload") or {}).get("signed_at")
    brought = git.required(root, "log", "--diff-filter=A", "--reverse", "--format=%ct", f"{base}..HEAD", "--", relative,
                           needs=_NEEDS_GIT)
    first = brought.stdout.split()[:1]
    if not isinstance(moment, str):  # None: the signature check says so.
        return None
    try:
        signed = calendar.timegm(time.strptime(moment, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:  # Malformed: the signature check says so.
        return None
    if brought.returncode or not first or signed <= int(first[0]) + CLOCK_SKEW.total_seconds():
        return None
    return (f"{relative}: the approval says it was signed at {moment}, after the commit that brings this record "
            f"({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(first[0])))}): a signature cannot be later than the "
            "change that carries it. Sign and export the decision again.")


def _workflow_ref() -> str | None:
    """The workflow file GitHub Actions is running, from GITHUB_WORKFLOW_REF (owner/repo/PATH@ref)."""
    reference = os.environ.get("GITHUB_WORKFLOW_REF", "").split("@", 1)[0]
    parts = reference.split("/", 2)
    return parts[2] if len(parts) == 3 and parts[2].startswith(WORKFLOW_DIR) else None


def _changed_guard_workflows(root: Path, base: str, changed: list[str]) -> list[str]:
    """The changed workflow files that run this check, on the base revision or in the change."""
    from . import git

    running = _workflow_ref()
    found = []
    for path in changed:
        if not path.startswith(WORKFLOW_DIR):
            continue
        versions = [git.required(root, "show", f"{revision}:{path}", needs=_NEEDS_GIT) for revision in (base, "HEAD")]
        if path == running or any(not item.returncode and GUARD_STEP.encode() in item.stdout for item in versions):
            found.append(path)
    return found


def _workflow_note(paths: list[str]) -> str:
    from .doc_links import doc_link

    return (f"This change edits {', '.join(paths)}, which runs this check: on pull_request, GitHub runs the pull "
            "request's own copy of a workflow, so this result may come from the edited file. Have a person review the "
            "change, and keep pull requests from editing the check (CODEOWNERS on .github/workflows/, a ruleset that "
            f"requires the workflow; see {doc_link('integrations/README.md', 'protect-the-check')}).")


def _journal_mismatch(root: Path, record: dict) -> str | None:
    """The checks whose journal is in this tree and no longer matches the exported sha256.

    A record exported before journals were hashed has none. A journal that this checkout does not contain
    (the project gitignore leaves .openguildkit/tasks/ out) cannot be re-hashed here: task complete checks
    it on the machine that still has the file.
    """
    result = record.get("result")
    journals = result.get("journals") if isinstance(result, dict) else None
    if not isinstance(journals, list):
        return None
    mismatched = []
    for item in journals:
        if not isinstance(item, dict):
            continue
        evidence, digest, name = item.get("evidence"), item.get("sha256"), item.get("check")
        if not isinstance(evidence, str) or not isinstance(digest, str) or not isinstance(name, str):
            continue
        path = root / evidence
        try:
            current = file_sha256(path) if path.is_file() else None
        except OSError:
            current = None
        if current is not None and current != digest:
            mismatched.append(name)
    if not mismatched:
        return None
    return f"{', '.join(mismatched)}: the journal no longer matches the recorded sha256."


def _judge_record(root: Path, base: str, relative: str, prefix: str, flag, *, fingerprint, policy: dict,
                  base_root: Path, earlier: dict, profile: dict) -> tuple[list[str], dict | None]:
    """The problems of one decision record the change brings, in the order guard --ci reports them, and the record
    when it covers its files (None when it is missing, invalid or faulty)."""
    from . import requester, roles
    from .tasks_blockers import expired_waiver_problem

    problems: list[str] = []
    record = _read_record(root, relative, prefix, flag, problems)
    if record is None:
        return problems, None
    checked = record_check(record, relative, fingerprint, policy, base_root, earlier, extracted=True, history=root)
    fault = (checked[2], checked[1]) if checked else None
    # A waiver that expired opens its blocker again: the record no longer covers the change.
    expired = None if fault else expired_waiver_problem(record, relative)
    fault = fault or (("decision-waiver-expired", expired) if expired else None)
    journal = _journal_mismatch(root, record)
    outside = None if fault else _lane_fault(record, (earlier.get(record["task"]) or record).get("files"),
                                             profile.get("light_paths") or [], base)
    if fault:
        problems.append(flag(fault[0], fault[1], relative))
    if journal:
        problems.append(flag("evidence-journal-changed", journal, relative))
    if outside:
        problems.append(flag("decision-lane-outside", f"{relative}: {outside}", relative))
    if fault:
        return problems, None
    # The base revision's profile says whether the requester may approve: a change cannot turn that off for itself.
    same = requester.record_problem(record, record["task"] not in earlier) if requester.active(profile) else None
    if same:
        problems.append(flag(same[0], f"{relative}: {same[1]}", relative))
    late = None if record["task"] in earlier else _signed_late(root, base, record, relative)
    if late:
        problems.append(flag("decision-signed-late", late, relative))
    # The roles of the base revision judge a record it does not carry: who cleared, who approved (roles.py).
    outside_role = [] if record["task"] in earlier else roles.record_problems(record, profile)
    for message in outside_role:
        problems.append(flag("decision-role-outside", f"{relative}: {message}", relative))
    if not journal and not outside and not same and not late and not outside_role:
        return problems, record
    return problems, None


def _read_record(root: Path, relative: str, prefix: str, flag, problems: list[str]) -> dict | None:
    """The decision record at relative, of the right place and shape, or None with its problem added to problems
    (none for a record the change deletes)."""
    path = root / relative
    if not path.is_file():
        return None
    if PurePosixPath(relative).parent != PurePosixPath(prefix):
        problems.append(flag("decision-record-invalid", f"{relative} is not directly under {prefix}: task export "
                             f"writes each record there, named after its task, and no record elsewhere covers a "
                             f"change. Move it to {prefix}TASK.json or remove it.", relative))
        return None
    try:
        record = read_json(path)
    except (OSError, ValueError):
        problems.append(flag("decision-record-invalid", conflict_message(path, relative) or (
            f"{relative} is not a decision record written by openguildkit task export. "
            "Export the decision again or remove the file."), relative))
        return None
    try:
        record_shape(record, relative)
    except ValueError as error:
        problems.append(flag("decision-record-invalid", str(error), relative))
        return None
    return record


def _judge_records(root: Path, base: str, records: list[str], prefix: str, flag, problems: list[str],
                   **context) -> tuple[list[str], dict, dict]:
    """Judge each decision record of the change, adding its problems: the tasks of the valid ones, the record path
    of each, and the files each covers (its base version's list for an approval already on base)."""
    valid, where, covers = [], {}, {}
    earlier = context["earlier"]
    for relative in records:
        found, record = _judge_record(root, base, relative, prefix, flag, **context)
        problems += found
        if record is not None:
            valid.append(record["task"])
            where[record["task"]] = relative
            covers[record["task"]] = (earlier.get(record["task"]) or record).get("files")
    return valid, where, covers


def _freeze_problem(root: Path, base_state: Path, freeze, changed: list[str], records: list[str], problems: list[str],
                    flag) -> None:
    """A frozen base fails every change but the one that lifts the freeze, whatever the guard mode (incident.py)."""
    if freeze and changed and not incident.lifts_freeze(base_state / "project.json", root / incident.PROFILE,
                                                        changed, records):
        problems.append(flag("guard-frozen", f"This change cannot be accepted: {incident.frozen_text(freeze)}. "
                                             f"{incident.LIFT}"))


def _coverage_problems(work: list[str], records: list[str], valid: list[str], covers: dict, problems: list[str],
                       flag) -> None:
    """Add to problems the decision a change lacks: none exported, none valid, or files no valid one lists."""
    if work and not records:
        problems.append(flag("decision-missing", "The changes come with no exported decision "
                                                 "(openguildkit task export ID)."))
    elif work and not valid and not problems:
        problems.append(flag("decision-missing", "No exported decision in this change is valid."))
    elif work and valid and (uncovered := _uncovered(work, covers)):
        problems.append(flag("decision-files-uncovered", uncovered))


def _unsigned_finding(require_signed: bool, problems: list[str], notes: list[str], flag) -> None:
    """Approvals that are local, not signed: a problem under --require-signed, else a note."""
    if require_signed:
        problems.append(flag("approvals-not-signed", f"{_local_records()}: --require-signed fails this check until they are."))
    else:
        notes.append(flag("approvals-not-signed", f"{_local_records()}, or pass --require-signed to fail this check until "
                                                  "they are.", None, "note"))


def ci_guard(root: Path, base: str, catalog_for, *, require_signed: bool = False, findings: list | None = None,
             org_catalog: list[str] | None = None, org_policy_copy: tuple[str, str] | None = None) -> dict:
    """Check that the changes since base come with a decision valid under the base revision's rules.

    The mode, the profile, the catalog lock and the allowed signers come from base, so a pull request
    cannot weaken the rules it is judged by. Each changed file must be listed by a valid record the change brings;
    a record of an approval already on base covers only the files its base version listed, so re-exporting an
    old approval cannot stretch it over new work. catalog_for(state) loads the catalog of a state directory, inside
    copies_read_from: the copy of an organization catalog is looked for from the real root, or at the NAME=PATH given
    as org_catalog. require_signed makes local approvals a problem. An organization policy (org_policy.py), from
    org_policy_copy (PATH, SHA) or else the base revision's pin, fails a profile under its minimum, and every change
    while it freezes the repositories.

    A list given as findings receives each problem and note as a finding of docs/sarif.md (code, level, message, path,
    line): a problem is an error, a note stays a note, and the path is the file it concerns, None when none does.
    """
    from . import git, org_policy
    from .org_catalog import copies_read_from, parse_copies
    from .project_rules import Fingerprints

    if git.required(root, "rev-parse", "--is-inside-work-tree", needs=_NEEDS_GIT).returncode:
        raise ValueError("guard --ci needs a Git repository: the project folder is not inside one.")
    report = findings if findings is not None else []

    def flag(code: str, message: str, path: str | None = None, level: str = "error") -> str:
        report.append({"code": code, "level": level, "message": message, "path": path, "line": None})
        return message

    if git.required(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", needs=_NEEDS_GIT).returncode:
        raise ValueError(f"base revision {base} not found: pass --base REF")
    changed = _git_lines(root, "diff", "--name-only", "--no-renames", f"{base}...HEAD")
    prefix = f"{STATE_DIR}/{DECISIONS_DIR}/"
    records = [path for path in changed if path.startswith(prefix) and path.endswith(".json")]
    work = [path for path in changed if path not in records]
    problems: list[str] = []
    running = _changed_guard_workflows(root, base, work)
    notes = [_workflow_note(running)] if running else []
    for path in running:
        flag("guard-workflow-edited", notes[0], path, "note")
    import tempfile  # guard --ci only: the edit hook starts without it (#539).

    with tempfile.TemporaryDirectory() as directory:
        base_root = Path(directory)
        names = _git_lines(root, "ls-tree", "-r", "--name-only", base, "--", STATE_DIR)
        if f"{STATE_DIR}/project.json" not in names:
            return {"mode": "off", "changed": len(work), "decisions": [], "records": {},
                    "problems": [flag("guard-no-base-profile", _no_base_profile(root), None, "note")], "notes": notes,
                    "ok": True}
        _extract_base(root, base, base_root, [name for name in names
                                              if not name.startswith((f"{STATE_DIR}/tasks/", prefix))])
        base_state = base_root / STATE_DIR
        with copies_read_from(root, parse_copies(org_catalog)):
            catalog = catalog_for(base_state)
        profile = load_profile(base_state, catalog)
        policy = approval_policy(profile)
        freeze = incident.frozen(profile)
        _freeze_problem(root, base_state, freeze, changed, records, problems, flag)
        floor = [flag(code, message[0].upper() + message[1:]) for code, message in org_policy.ci_problems(
            org_policy_copy, root, base_state, profile, catalog, parse_copies(org_catalog), bool(changed))]
        problems += floor
        if policy["mode"] == "signed":
            _extract_base(root, base, base_root, [PurePosixPath(policy["allowed_signers"]).as_posix()])
        fingerprint = Fingerprints(profile, catalog)
        earlier = _earlier_records(_base_files(root, base, [name for name in names
                                                            if name.startswith(prefix) and name.endswith(".json")]))
        valid, where, covers = _judge_records(root, base, records, prefix, flag, problems, fingerprint=fingerprint,
                                              policy=policy, base_root=base_root, earlier=earlier, profile=profile)
    _coverage_problems(work, records, valid, covers, problems, flag)
    if policy["mode"] != "signed" and guard_mode(profile) != "off":
        _unsigned_finding(require_signed, problems, notes, flag)
    ok = not problems and (not work or bool(valid))
    return {"mode": "enforce" if freeze or floor else guard_mode(profile), "changed": len(work), "decisions": valid, "records": where,
            "problems": problems, "notes": notes, "ok": ok}
