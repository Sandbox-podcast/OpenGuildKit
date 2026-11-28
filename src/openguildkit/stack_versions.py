"""Reads declared versions and version ranges for detection, patterns and the Storybook dependency report.

Entry: declared_version, version_key, parse_version, parse_range, satisfies, lower_bounds
Tests: tests/test_detect_versions.py
"""

import re

from . import lazy_re

# The Storybook release a project is told to create with npm create storybook@VERSION. It lives here, not in
# storybook.py, so that the help of every command shows it without importing the Storybook module.
STORYBOOK_VERSION = "10.6.6"

_NUMERIC = r"\d+(?:\.\d+){0,3}"
_VALUE = rf"(?:v?{_NUMERIC}(?:\.[xX*]|(?:[-+][a-z0-9.-]+)+|(?:a|b|rc)\d+)?|[xX*])"
_OPERATOR = r"===|==|!=|~=|~>|>=|<=|>|<|=|\^|~"
_TERM = rf"(?:(?:{_OPERATOR})[ \t]*)?{_VALUE}"
_CONSTRAINT = rf"{_TERM}(?:(?:[ \t]*(?:\|\|?|,)[ \t]*|[ \t]+-[ \t]+|[ \t]+){_TERM})*"
_SPEC = lazy_re.compile(_CONSTRAINT, re.IGNORECASE | re.ASCII)
STACK_VERSION = lazy_re.compile(rf"(?:@|\s+)({_CONSTRAINT})$", re.IGNORECASE | re.ASCII)
_EXACT = lazy_re.compile(rf"(?:===|==|=)[ \t]*(v?{_NUMERIC})", re.IGNORECASE)


def declared_version(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _SPEC.fullmatch(value) or not re.search(r"\d", value):
        return None
    exact = _EXACT.fullmatch(value)
    return exact.group(1) if exact else value


def version_key(version: str) -> tuple[int, ...]:
    parts = tuple(map(int, version.split(".")))
    return parts + (0,) * (4 - len(parts))


# Ranges, read with npm's grammar: alternatives with ||, hyphen ranges, ^, ~, x-ranges and comparators. The same
# reading takes what Python, Ruby and Composer write: a comma between comparators, ==, ===, != and ~=, a single |
# between alternatives, a fourth number and a prerelease such as 3.12rc1. A version is the tuple
# (major, minor, patch, fourth, 1 for a release or 0 for a prerelease, prerelease).

_PARTIAL = lazy_re.compile(r"v?(\d+|[x*])(?:\.(\d+|[x*]))?(?:\.(\d+|[x*]))?(?:\.(\d+|[x*]))?"
                      r"(?:-([0-9a-z.-]+)|((?:a|b|rc)\d+))?(?:\+[0-9a-z.-]+)?", re.IGNORECASE)
_COMPARATOR = lazy_re.compile(r"(\^|~>|~=|~|===|==|!=|>=|<=|>|<|=)?(.+)")
_OPERATORS = ("^", "~", "~>", "~=", "===", "==", "!=", ">=", "<=", ">", "<", "=")
_PARTS = 4


def _partial(text: str):
    match = _PARTIAL.fullmatch(text.strip())
    if not match:
        return None
    parts = [None if part is None or part in "xX*" else int(part) for part in match.groups()[:_PARTS]]
    for index in range(1, _PARTS):
        if parts[index - 1] is None:
            parts[index] = None
    return parts, match.group(5) or match.group(6)


def _version(parts, prerelease=None) -> tuple:
    # A release sorts after its prereleases.
    return (*(part or 0 for part in parts), 0 if prerelease else 1, prerelease or "")


def parse_version(text: str) -> tuple | None:
    """A complete version, such as 18.3.1; None for a partial one or a range."""
    parsed = _partial(text)
    if not parsed or None in parsed[0][:3]:
        return None
    return _version(*parsed)


def _bump(parts, position: int, prerelease: str | None = "0") -> tuple:
    bumped = [part or 0 for part in parts]
    bumped[position] += 1
    for index in range(position + 1, _PARTS):
        bumped[index] = 0
    return _version(bumped, prerelease)


def _comparators(operator: str, parts: list, prerelease) -> list[tuple]:
    known = len([part for part in parts if part is not None])
    if operator in ("==", "==="):
        operator = "="
    if known == 0:
        unbounded = operator in ("", "=", "^", "~", "~>", "~=", ">=", "<=", "!=")
        return [] if unbounded else [("<", _version([0] * _PARTS, "0"))]
    low = _version(parts, prerelease)
    if operator == "^":
        # Bump the first non-zero part: ^1.2.3 is below 2.0.0, ^0.2.3 below 0.3.0, ^0.0.3 below 0.0.4.
        position = next((index for index, part in enumerate(parts[:known]) if part), known - 1)
        return [(">=", low), ("<", _bump(parts, position))]
    if operator in ("~", "~>"):
        return [(">=", low), ("<", _bump(parts, 1 if known > 1 else 0))]
    if operator == "~=":
        # A compatible release: ~=3.11 is below 4.0, ~=3.11.2 below 3.12.
        return [(">=", low), ("<", _bump(parts, max(known - 2, 0)))]
    if operator in ("", "="):
        return [("=", low)] if known >= 3 else [(">=", low), ("<", _bump(parts, known - 1))]
    if operator == ">":
        # npm reads >1.2 as >=1.3.0: no version of 1.2 is above 1.2.
        return [(">", low)] if known >= 3 else [(">=", _bump(parts, known - 1, None))]
    if operator == "<=":
        return [("<=", low)] if known >= 3 else [("<", _bump(parts, known - 1))]
    return [(operator, low)]


def parse_range(text: str) -> list[list[tuple]] | None:
    """The alternatives of a range, each a list of (operator, version) that a version must all meet; None when the
    text is not a range, such as latest, a tag or a Git URL."""
    if not isinstance(text, str) or re.search(r"[:/#]|^\s*(latest|next|workspace)", text):
        return None
    alternatives = []
    for alternative in re.split(r"\|\|?", text):
        alternative = alternative.replace(",", " ").strip()
        hyphen = re.fullmatch(r"(\S+)\s+-\s+(\S+)", alternative)
        if hyphen:
            low, high = _partial(hyphen.group(1)), _partial(hyphen.group(2))
            if not low or not high:
                return None
            alternatives.append(_comparators(">=", *low) + _comparators("<=", *high))
            continue
        tokens: list[str] = []
        for token in alternative.split():
            if tokens and tokens[-1] in _OPERATORS:
                tokens[-1] += token
            else:
                tokens.append(token)
        comparators = []
        for token in tokens or ["*"]:
            operator, value = _COMPARATOR.fullmatch(token).groups()
            parsed = _partial(value)
            if not parsed:
                return None
            comparators.extend(_comparators(operator or "", *parsed))
        alternatives.append(comparators)
    return alternatives


def satisfies(version: tuple, ranges: list[list[tuple]]) -> bool:
    checks = {"=": lambda a, b: a == b, ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
              "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, "!=": lambda a, b: a != b}
    return any(all(checks[operator](version, bound) for operator, bound in alternative) for alternative in ranges)


def _above(version: tuple) -> tuple:
    """The lowest version above a complete one, as npm finds it: the next patch, or the next fourth number."""
    if not version[-2]:
        return (*version[:-1], f"{version[-1]}.0")
    numbers = list(version[:_PARTS])
    numbers[_PARTS - 1 if numbers[_PARTS - 1] else 2] += 1
    return _version(numbers)


def lower_bounds(ranges: list[list[tuple]]) -> list[tuple] | None:
    """The lowest version each alternative accepts; None when one of them sets no lower bound, so that "<2 || >=3"
    says nothing about the version in use."""
    bounds = []
    for alternative in ranges:
        lows = [bound for operator, bound in alternative if operator in (">=", "=")]
        lows += [_above(bound) for operator, bound in alternative if operator == ">"]
        if not lows:
            return None
        bounds.append(max(lows))
    return bounds or None


def version_text(version: tuple) -> str:
    """A version as npm writes it: three numbers, a fourth when it is set, then the prerelease."""
    numbers = version[:_PARTS] if version[_PARTS - 1] else version[:3]
    return ".".join(map(str, numbers)) + (f"-{version[-1]}" if not version[-2] else "")


def version_lower_bound(constraint: str) -> str | None:
    """The lowest version a declared constraint accepts, without its zero parts and its prerelease: ^18.2 gives
    18.2. None when one of its alternatives sets no lower bound."""
    ranges = parse_range(constraint)
    bounds = lower_bounds(ranges) if ranges else None
    if not bounds:
        return None
    numbers = list(min(bounds)[:_PARTS])
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return ".".join(map(str, numbers))
