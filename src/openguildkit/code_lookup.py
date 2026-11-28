"""Looks up in the project's code the names a task cites, from the files Git tracks or a bounded walk of the folder."""

import os
import re
import subprocess
from pathlib import Path

from . import lazy_re
from .detect import SKIPPED_DIRECTORIES, walk

_CODE_SUFFIXES = (
    "py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "java", "kt", "cs", "go", "rb", "php", "rs", "swift", "sql", "vue",
    "svelte", "c", "h", "cpp", "scala", "ex", "exs", "dart",
)


_CODE_PATH = lazy_re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.(?:" + "|".join(_CODE_SUFFIXES) + r"))(?![\w-])")


_CODE_NAME = lazy_re.compile(r"`([A-Za-z_][\w.]{2,})(?:\(\))?`|(?<![\w.])([A-Za-z_]\w{2,})\(\)")


# "function missingFn" in prose: a name written like code (camelCase or snake_case) after the word.
_NAMED_FUNCTION = lazy_re.compile(r"\b(?:function|fonction|method|méthode)\s+([a-z_]\w*(?:[A-Z_]\w*)+)\b", re.IGNORECASE)


MAX_SCANNED_FILES = 5000
MAX_SOURCE_BYTES = 1_000_000
# The source files a Git search reads: the code suffixes, outside the folders every walk of the project skips.
_GIT_SOURCES = (*(f":(glob)**/*.{suffix}" for suffix in _CODE_SUFFIXES),
                *(f":(glob,exclude)**/{name}/**" for name in sorted(SKIPPED_DIRECTORIES)))


def _source_files(root: Path):
    """The project's source files, outside the folders every walk of the project skips (dependencies, builds,
    caches): a large node_modules is never listed. The caller stops reading them when it has enough."""
    for folder, _, files, _ in walk(root):
        for name in files:
            path = folder / name
            if path.suffix[1:] not in _CODE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > MAX_SOURCE_BYTES:
                    continue
            except OSError:
                continue
            yield path


def _code_names(text: str) -> tuple[list[str], list[str]]:
    """The file paths and the function names a brief writes like code."""
    paths = list(dict.fromkeys(_CODE_PATH.findall(text)))
    names = list(dict.fromkeys([*(first or second for first, second in _CODE_NAME.findall(text)
                                  if (first or second) not in paths),
                                *(name for name in _NAMED_FUNCTION.findall(text) if any(c.isupper() or c == "_"
                                                                                       for c in name))]))
    return paths, names


def _words_in(path: Path, words: set[str]) -> set[str]:
    """The words of the set that the file uses as whole words."""
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return set()
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {word for word in words if re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", content)}


def _git_lookup(root: Path, file_names: set[str], words: set[str]) -> tuple[set[str], set[str]] | None:
    """In a Git repository, the file names and the words the project's source files hold, tracked or not and
    outside what Git ignores, each set in one git call; None outside a repository or without git."""
    found_names: set[str] = set()
    found_words: set[str] = set()
    try:
        if file_names:
            listed = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                 *(f":(glob)**/{name}" for name in sorted(file_names)), *_GIT_SOURCES[len(_CODE_SUFFIXES):]],
                capture_output=True, check=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
            if listed.returncode:
                return None
            found_names = {Path(item).name for item in os.fsdecode(listed.stdout).split("\0") if item}
        if words:
            # -o -h prints each match alone: the words found, whatever file holds them.
            grep = subprocess.run(
                ["git", "-C", str(root), "grep", "-o", "-h", "-I", "-w", "-F", "--untracked",
                 *(argument for word in sorted(words) for argument in ("-e", word)), "--", *_GIT_SOURCES],
                capture_output=True, check=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
            if grep.returncode not in (0, 1):
                return None
            found_words = set(grep.stdout.decode("utf-8", errors="replace").split()) & words
    except OSError:
        return None
    return found_names, found_words


def code_lookup(text: str, root: Path) -> tuple[list[str], list[str]]:
    """The files and functions a bug brief names that the project does not contain, so the boards can say so, and
    those a search stopped at MAX_SCANNED_FILES source files did not reach, which are not said to be absent.

    The files the brief names are read first. Then, in a Git repository, one git call finds the rest in every
    source file; elsewhere, the walk reads at most MAX_SCANNED_FILES source files."""
    paths, names = _code_names(text)
    if not paths and not names:
        return [], []
    words = {name: name.split(".")[-1] for name in names}
    remaining = set(words.values())
    unresolved = [path for path in paths if not (root / path).exists()]
    for path in paths:  # The code a bug brief means is most often in the file it names.
        if remaining and path not in unresolved and (root / path).is_file():
            remaining -= _words_in(root / path, remaining)
    unread: set[str] = set()
    found = _git_lookup(root, {Path(path).name for path in unresolved}, remaining) \
        if unresolved or remaining else (set(), set())
    if found is not None:
        unresolved = [path for path in unresolved if Path(path).name not in found[0]]
        remaining -= found[1]
    else:
        files: list[Path] = []
        for item in _source_files(root):
            if len(files) == MAX_SCANNED_FILES:
                unread = {Path(path).name for path in unresolved} | remaining
                break
            files.append(item)
            if remaining:
                remaining -= _words_in(item, remaining)
        listed = {item.name for item in files}
        unresolved = [path for path in unresolved if Path(path).name not in listed]
    missing = [path for path in unresolved if Path(path).name not in unread] + \
              [f"{name}()" for name in names if words[name] in remaining and words[name] not in unread]
    not_searched = [path for path in unresolved if Path(path).name in unread] + \
                   [f"{name}()" for name in names if words[name] in remaining and words[name] in unread]
    return missing, not_searched
