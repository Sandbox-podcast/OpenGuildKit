"""Reads an organization catalog at the commit the catalog lock pins, from a local Git copy and without network;
fingerprints the files read and lists the project records that replace one of its records. Off unless a person pins one.

A person pins, in `catalog.lock.json`, a commit of a local Git copy of the organization's catalog. Its packs,
patterns, brains and sectors, in the format of a project catalog, add to the bundled catalog; the project's own
records come last and may replace one of them, which `check` shows until a person accepts it. OpenGuildKit never
fetches: it reads the files at the pinned commit with `git ls-tree` and `git cat-file`, and the person keeps the copy
up to date with `git fetch`. A project whose lock has no "organization" entry runs no Git command here.

The lock names the catalog (`name`) or, in the first format, the path of a copy (`repo`). A name carries no path: each
machine finds its copy in OPENGUILDKIT_ORG_CATALOG_NAME, and `guard --ci` in `--org-catalog NAME=PATH`. The stops and
the pins stay in `organization_history`.

Entry: read_files, organization_in, validate_pin, changes, replacements
Tests: tests/test_command_output_budget.py, tests/test_org_catalog.py, tests/test_org_policy.py
"""

import hashlib
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import NoReturn

from . import lazy_re

# The edit hook loads this module: git and shell are imported in the functions that use them (#539).

COLLECTIONS = ("packs", "boards", "sectors", "patterns")
# The organization policy (RFC #452, org_policy.py): one file at the root, read and fingerprinted with the records
# when the commit has it, so a commit without it keeps the fingerprint it had before.
POLICY_FILE = "policy.json"
FULL_COMMIT = lazy_re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
FINGERPRINT = lazy_re.compile(r"sha256:[0-9a-f]{64}")
LOCK_NAME = ".openguildkit/catalog.lock.json"
SET_COMMAND = "openguildkit org-catalog set --repo PATH --commit SHA --by INITIALS --reason WHY"
PIN_FIELDS = {"repo", "name", "commit", "fingerprint", "pinned", "exceptions"}
PERSON_FIELDS = {"by", "reason", "on"}
NAME = lazy_re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
HISTORY_FIELDS = {"action", "commit", "by", "reason", "on"}
MIGRATE_COMMAND = "openguildkit org-catalog set --name NAME --repo PATH --commit SHA --by INITIALS --reason WHY"

# Where the copies are looked for while a catalog is loaded from a folder that is not the project: guard --ci extracts
# the base revision to a temporary folder, so a relative path must be read from the real root. (root, NAME -> folder.)
_PLACE: ContextVar[tuple[Path, dict[str, str]] | None] = ContextVar("org_catalog_place", default=None)

# Files already read in this process, by copy and commit: a commit's files cannot change.
_READ: dict[tuple[str, str], dict] = {}
_READ_KEPT = 8
# What a missing Git stops (git.required).
_NEEDS_GIT = "Reading the organization catalog"


def _is_repository(repo: Path) -> bool:
    """True when the folder is the top of a Git working copy or a bare repository, not a folder inside another one."""
    from . import git

    if not repo.is_dir():
        return False
    top = git.required(repo, "rev-parse", "--show-toplevel", needs=_NEEDS_GIT, offline=True)
    if top.returncode == 0 and top.stdout.strip():
        return Path(os.fsdecode(top.stdout.strip())).resolve() == repo.resolve()
    bare = git.required(repo, "rev-parse", "--is-bare-repository", "--absolute-git-dir", needs=_NEEDS_GIT, offline=True)
    lines = bare.stdout.split()
    return bare.returncode == 0 and len(lines) == 2 and lines[0] == b"true" \
        and Path(os.fsdecode(lines[1])).resolve() == repo.resolve()


def repo_folder(repo: str, root: Path) -> Path:
    """The copy's folder: a relative path is read from the project root."""
    path = Path(repo)
    return path if path.is_absolute() else root / path


def variable_name(name: str) -> str:
    return "OPENGUILDKIT_ORG_CATALOG_" + name.upper().replace("-", "_")


def parse_copies(items: list[str] | None) -> dict[str, str]:
    """`--org-catalog NAME=PATH` as a mapping from name to the absolute folder."""
    copies = {}
    for item in items or []:
        name, _, path = item.partition("=")
        if not NAME.fullmatch(name) or not path:
            raise ValueError(f"--org-catalog takes NAME=PATH, such as acme=../acme-catalog, not {item!r}.")
        copies[name] = str(Path(path).resolve())
    return copies


@contextmanager
def copies_read_from(root: Path, named: dict[str, str] | None = None):
    """Inside it, organization_in reads a relative path of a copy from root, and the copy of a name from `named`."""
    token = _PLACE.set((root, named or {}))
    try:
        yield
    finally:
        _PLACE.reset(token)


def _named_folder(name: str, named: dict[str, str]) -> Path:
    """The copy of the catalog a lock names: the folder given for guard --ci, else the variable of this machine."""
    given = named.get(name) or os.environ.get(variable_name(name))
    if not given:
        raise ValueError(f"This machine has no copy of the organization catalog {name!r}: set {variable_name(name)} to "
                         f"your Git copy of it (guard --ci: --org-catalog {name}=PATH).")
    return Path(given).resolve()


def _listed_files(repo: Path, commit: str) -> list[tuple[str, str]]:
    """(path, object) of each record file at the commit: COLLECTION/NAME.json, and the policy file at the root, plain
    files only."""
    from . import git

    listing = git.required(repo, "ls-tree", "-r", "-z", commit, "--", *COLLECTIONS, POLICY_FILE, needs=_NEEDS_GIT,
                           offline=True)
    if listing.returncode:
        raise ValueError(f"Git could not list the files of {commit[:12]} in {repo}.")
    files = []
    for item in listing.stdout.split(b"\0"):
        if not item:
            continue
        header, _, name = item.partition(b"\t")
        mode, kind, obj = header.split(b" ")
        path = name.decode("utf-8", "replace")
        parts = path.split("/")
        if kind == b"blob" and mode in (b"100644", b"100755") and (
                len(parts) == 2 and parts[1].endswith(".json") or parts == [POLICY_FILE]):
            files.append((path, obj.decode("ascii")))
    return sorted(files)


def _contents(repo: Path, objects: list[str]) -> list[bytes]:
    """The content of each object, read by one `git cat-file --batch`."""
    from . import git

    if not objects:
        return []
    result = git.required(repo, "cat-file", "--batch", stdin="".join(f"{obj}\n" for obj in objects).encode("ascii"),
                          needs=_NEEDS_GIT, offline=True)
    if result.returncode:
        raise ValueError(f"Git could not read the organization catalog in {repo}.")
    output, position, contents = result.stdout, 0, []
    for _ in objects:
        end = output.index(b"\n", position)
        size = int(output[position:end].split(b" ")[2])
        contents.append(output[end + 1:end + 1 + size])
        position = end + 1 + size + 1
    return contents


def fingerprint(files: dict[str, list[tuple[str, bytes]]]) -> str:
    """The digest of the paths and contents read, in path order."""
    digest = hashlib.sha256()
    for path, data in sorted(item for collection in (*COLLECTIONS, POLICY_FILE) for item in files.get(collection, [])):
        digest.update(path.encode("utf-8") + b"\0" + hashlib.sha256(data).hexdigest().encode("ascii") + b"\n")
    return "sha256:" + digest.hexdigest()


def read_files(repo: str, commit: str, root: Path, folder: Path | None = None) -> dict:
    """The record files of the organization catalog at the commit, with their fingerprint. Raises with the command
    that fixes it when the copy or the commit is missing. repo is what the lock calls the copy (its path, or its name
    with the folder given as `folder`)."""
    from . import git
    from .shell import shell_word

    if not FULL_COMMIT.fullmatch(commit):
        raise ValueError(f"Give the full commit SHA of the organization catalog, not {commit!r}: git -C "
                         f"{shell_word(repo)} rev-parse COMMIT prints it.")
    named = folder is not None
    folder = folder or repo_folder(repo, root)
    key = (str(folder.resolve()) if folder.is_dir() else str(folder), commit)
    if key in _READ and folder.is_dir():
        return _READ[key]
    shown = repo if str(folder) == repo else f"{repo} ({'the copy at' if named else 'resolved to'} {folder.resolve()})"
    if not _is_repository(folder):
        raise ValueError(f"The organization catalog {shown} is not a Git repository on this machine. Clone it at that "
                         f"path, or point the project at your copy at a terminal: {SET_COMMAND}.")
    found = git.required(folder, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}", needs=_NEEDS_GIT,
                         offline=True)
    if found.returncode or found.stdout.strip() != commit.encode("ascii"):
        raise ValueError(f"Commit {commit[:12]} of the organization catalog is not in {shown}: run git -C "
                         f"{shell_word(str(folder) if named else repo)} fetch, then the command again, or "
                         f"pin a commit the copy has at a terminal: {SET_COMMAND}.")
    listed = _listed_files(folder, commit)
    files: dict[str, list[tuple[str, bytes]]] = {}
    for (path, _), data in zip(listed, _contents(folder, [obj for _, obj in listed])):
        files.setdefault(path.split("/")[0], []).append((path, data))
    read = {"repo": repo, "commit": commit, "files": files, "fingerprint": fingerprint(files)}
    if len(_READ) >= _READ_KEPT:
        _READ.clear()
    _READ[key] = read
    return read


def validate_pin(pin: object, where: str) -> None:
    """The "organization" entry of a catalog lock."""
    def refuse(problem: str) -> NoReturn:
        raise ValueError(f"{where}: organization {problem}. Restore the file from Git, or pin the organization "
                         f"catalog again at a terminal: {SET_COMMAND}.")

    if not isinstance(pin, dict) or not {"commit", "fingerprint", "pinned"} <= pin.keys() <= PIN_FIELDS \
            or ("repo" in pin) == ("name" in pin):
        refuse("must hold commit, fingerprint and pinned, a name or a repo (not both), and may hold exceptions")
    if "repo" in pin and (not isinstance(pin["repo"], str) or not pin["repo"].strip()):
        refuse("repo must be the path of a local Git copy")
    if "name" in pin and (not isinstance(pin["name"], str) or not NAME.fullmatch(pin["name"])):
        refuse("name must be lowercase letters, digits, - and _")
    if not isinstance(pin["commit"], str) or not FULL_COMMIT.fullmatch(pin["commit"]):
        refuse("commit must be a full commit SHA")
    if not isinstance(pin["fingerprint"], str) or not FINGERPRINT.fullmatch(pin["fingerprint"]):
        refuse("fingerprint must be sha256: and 64 hexadecimal characters")
    exceptions = pin.get("exceptions", [])
    people = [pin["pinned"], *exceptions] if isinstance(exceptions, list) else None
    if people is None or not all(isinstance(item, dict) and all(isinstance(item.get(key), str) for key in PERSON_FIELDS)
                                 for item in people):
        refuse("pinned and each exception must name by, reason and on")
    if not all(isinstance(item.get("record"), str) and isinstance(item.get("digest"), str) for item in exceptions):
        refuse("exceptions must name the record and its digest")


def validate_history(history: object, where: str) -> None:
    """The `organization_history` of a catalog lock: each pin and each stop, with who, when, why and the commit."""
    if not isinstance(history, list) or not all(
            isinstance(item, dict) and item.keys() == HISTORY_FIELDS and item["action"] in ("pinned", "stopped")
            and all(isinstance(item[key], str) for key in HISTORY_FIELDS) for item in history):
        raise ValueError(f"{where}: organization_history must list pinned and stopped entries with action, commit, "
                         f"by, reason and on. Restore the file from Git.")


def organization_in(lock: dict | None, state: Path) -> dict | None:
    """The organization catalog's files at the commit the lock pins; None when the project follows none."""
    pin = (lock or {}).get("organization")
    if pin is None:
        return None
    place = _PLACE.get()
    root = place[0] if place else state.parent
    if "name" in pin:
        read = read_files(pin["name"], pin["commit"], root, _named_folder(pin["name"], place[1] if place else {}))
    else:
        read = read_files(pin["repo"], pin["commit"], root)
    if read["fingerprint"] != pin["fingerprint"]:
        raise ValueError(f"The files of the organization catalog at {pin['commit'][:12]} do not match the fingerprint "
                         f"pinned in {LOCK_NAME}. Restore the lock from Git, or review the commit and pin it again "
                         f"at a terminal: {SET_COMMAND}.")
    return read


def records_of(catalog: dict) -> dict[str, dict]:
    """The organization records of a catalog, by collection/id."""
    provided = catalog.get("organization", {}).get("records", {})
    return {f"{collection}/{record_id}": catalog[collection][record_id]
            for collection in COLLECTIONS for record_id in provided.get(collection, [])}


def changes(before: dict[str, dict], after: dict[str, dict]) -> dict:
    """What a new commit adds, removes and changes, with the version of each changed pack."""
    changed = []
    for name in sorted(before.keys() & after.keys()):
        if before[name] != after[name]:
            change = {"record": name}
            if "version" in after[name]:
                change["version"] = [before[name].get("version"), after[name]["version"]]
            changed.append(change)
    return {"added": sorted(after.keys() - before.keys()), "removed": sorted(before.keys() - after.keys()),
            "changed": changed}


def replacements(catalog: dict, lock: dict | None) -> list[dict]:
    """The project records that replace an organization record, each with the acceptance that covers it, or None.
    An acceptance covers the organization record it was given for: a new edition of it needs a new one."""
    replaced = catalog.get("organization", {}).get("replaced", {})
    exceptions = {item["record"]: item for item in ((lock or {}).get("organization") or {}).get("exceptions", [])}
    rows = []
    for record, digest in replaced.items():
        exception = exceptions.get(record)
        accepted = None if exception is None or exception["digest"] != digest else {
            key: exception[key] for key in ("by", "reason", "on")}
        rows.append({"record": record, "accepted": accepted})
    return rows


def unaccepted_replacements(catalog: dict, lock: dict | None) -> dict[str, str]:
    """The line check prints for each replacement no person accepted, by collection/id."""
    return {row["record"]: (f"the project catalog replaces {row['record']} of the organization catalog "
                            f"(.openguildkit/catalog/{row['record']}.json). If a person agrees, openguildkit "
                            f"org-catalog accept {row['record']} --by INITIALS --reason WHY at a terminal.")
            for row in replacements(catalog, lock) if row["accepted"] is None}
