"""A component that detection proposes, and the bounded read of the manifest it comes from."""

from pathlib import Path

MAX_MANIFEST_BYTES = 2_000_000


class DetectedComponent:
    def __init__(self, path: str):
        self.path = path
        self.technologies: dict[str, dict] = {}

    def add(self, name: str, version: str | None, evidence: str, inferred: bool = False, note: str = "") -> None:
        if inferred:
            # A client library's version says nothing about the server it talks to.
            version = None
        current = self.technologies.get(name)
        if current is None or (version and not current["version"]):
            self.technologies[name] = {
                "name": name,
                "version": version,
                "evidence": evidence,
                "inferred": inferred,
            }
            # Why a technology carries no version although its manifest is read.
            if note and not version:
                self.technologies[name]["note"] = note


def read_manifest_text(path: Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None
