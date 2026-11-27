"""An organization catalog that several repositories follow (RFC #446): an option, off by default.

A person pins, in `catalog.lock.json`, a commit of a local Git copy of the organization's catalog. Its packs,
patterns, brains and sectors, in the format of a project catalog, add to the bundled catalog; the project's own
records come last and may replace one of them, which `check` shows until a person accepts it. OpenGuildKit never
fetches: it reads the files at the pinned commit with `git ls-tree` and `git cat-file`, and the person keeps the copy
up to date with `git fetch`. A project whose lock has no "organization" entry runs no Git command here.
"""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from .shell import shell_word

COLLECTIONS = ("packs", "boards", "sectors", "patterns")
FULL_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")
LOCK_NAME = ".openguildkit/catalog.lock.json"
SET_COMMAND = "openguildkit org-catalog set --repo PATH --commit SHA --by INITIALS --reason WHY"
PIN_FIELDS = {"repo", "commit", "fingerprint", "pinned", "exceptions"}
PERSON_FIELDS = {"by", "reason", "on"}

# Files already read in this process, by copy and commit: a commit's files cannot change.
_READ: dict[tuple[str, str], dict] = {}
_READ_KEPT = 8


def _git(repo: Path, *arguments: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    """Run Git on the local copy, with every way to reach a network turned off."""
    return subprocess.run(
        ["git", "--no-replace-objects", "-c", "protocol.allow=never", "-C", str(repo), *arguments],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}, input=stdin,
        capture_output=True, check=False,
    )


def _is_repository(repo: Path) -> bool:
    """True when the folder is the top of a Git working copy or a bare repository, not a folder inside another one."""
    if not repo.is_dir():
        return False
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top.returncode == 0 and top.stdout.strip():
        return Path(os.fsdecode(top.stdout.strip())).resolve() == repo.resolve()
    bare = _git(repo, "rev-parse", "--is-bare-repository", "--absolute-git-dir")
    lines = bare.stdout.split()
    return bare.returncode == 0 and len(lines) == 2 and lines[0] == b"true" \
        and Path(os.fsdecode(lines[1])).resolve() == repo.resolve()


def repo_folder(repo: str, root: Path) -> Path:
    """The copy's folder: a relative path is read from the project root."""
    path = Path(repo)
    return path if path.is_absolute() else root / path


def _listed_files(repo: Path, commit: str) -> list[tuple[str, str]]:
    """(path, object) of each record file at the commit: COLLECTION/NAME.json, plain files only."""
    listing = _git(repo, "ls-tree", "-r", "-z", commit, "--", *COLLECTIONS)
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
        if kind == b"blob" and mode in (b"100644", b"100755") and len(parts) == 2 and parts[1].endswith(".json"):
            files.append((path, obj.decode("ascii")))
    return sorted(files)


def _contents(repo: Path, objects: list[str]) -> list[bytes]:
    """The content of each object, read by one `git cat-file --batch`."""
    if not objects:
        return []
    result = _git(repo, "cat-file", "--batch", stdin="".join(f"{obj}\n" for obj in objects).encode("ascii"))
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
    for path, data in sorted(item for collection in COLLECTIONS for item in files.get(collection, [])):
        digest.update(path.encode("utf-8") + b"\0" + hashlib.sha256(data).hexdigest().encode("ascii") + b"\n")
    return "sha256:" + digest.hexdigest()


def read_files(repo: str, commit: str, root: Path) -> dict:
    """The record files of the organization catalog at the commit, with their fingerprint. Raises with the command
    that fixes it when the copy or the commit is missing."""
    if not FULL_COMMIT.fullmatch(commit):
        raise ValueError(f"Give the full commit SHA of the organization catalog, not {commit!r}: git -C "
                         f"{shell_word(repo)} rev-parse COMMIT prints it.")
    folder = repo_folder(repo, root)
    key = (str(folder.resolve()) if folder.is_dir() else str(folder), commit)
    if key in _READ and folder.is_dir():
        return _READ[key]
    if not _is_repository(folder):
        raise ValueError(f"The organization catalog {repo} is not a Git repository on this machine. Clone it at that "
                         f"path, or point the project at your copy at a terminal: {SET_COMMAND}.")
    found = _git(folder, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    if found.returncode or found.stdout.strip() != commit.encode("ascii"):
        raise ValueError(f"Commit {commit[:12]} of the organization catalog is not in {repo}: run git -C "
                         f"{shell_word(repo)} fetch, then the command again, or pin a commit the copy has at a "
                         f"terminal: {SET_COMMAND}.")
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
    def refuse(problem: str):
        raise ValueError(f"{where}: organization {problem}. Restore the file from Git, or pin the organization "
                         f"catalog again at a terminal: {SET_COMMAND}.")

    if not isinstance(pin, dict) or not {"repo", "commit", "fingerprint", "pinned"} <= pin.keys() <= PIN_FIELDS:
        refuse(f"must hold {', '.join(sorted(PIN_FIELDS - {'exceptions'}))} and may hold exceptions")
    if not isinstance(pin["repo"], str) or not pin["repo"].strip():
        refuse("repo must be the path of a local Git copy")
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


def organization_in(lock: dict | None, state: Path) -> dict | None:
    """The organization catalog's files at the commit the lock pins; None when the project follows none."""
    pin = (lock or {}).get("organization")
    if pin is None:
        return None
    read = read_files(pin["repo"], pin["commit"], state.parent)
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
