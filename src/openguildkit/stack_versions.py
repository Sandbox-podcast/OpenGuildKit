"""Keep declared dependency constraints in the stack and recognize them when matching patterns."""

import re

# The Storybook release a project is told to create with npm create storybook@VERSION. It lives here, not in
# storybook.py, so that the help of every command shows it without importing the Storybook module.
STORYBOOK_VERSION = "10.6.6"

_NUMERIC = r"\d+(?:\.\d+){0,3}"
_VALUE = rf"(?:v?{_NUMERIC}(?:\.[xX*]|(?:[-+][a-z0-9.-]+)+|(?:a|b|rc)\d+)?|[xX*])"
_OPERATOR = r"===|==|!=|~=|~>|>=|<=|>|<|=|\^|~"
_TERM = rf"(?:(?:{_OPERATOR})[ \t]*)?{_VALUE}"
_CONSTRAINT = rf"{_TERM}(?:(?:[ \t]*(?:\|\|?|,)[ \t]*|[ \t]+-[ \t]+|[ \t]+){_TERM})*"
_SPEC = re.compile(_CONSTRAINT, re.IGNORECASE | re.ASCII)
_TERMS = re.compile(_TERM, re.IGNORECASE | re.ASCII)
STACK_VERSION = re.compile(rf"(?:@|\s+)({_CONSTRAINT})$", re.IGNORECASE | re.ASCII)
_BOUND = re.compile(rf"(?P<operator>{_OPERATOR})?[ \t]*v?(?P<version>{_NUMERIC})", re.IGNORECASE)
_EXACT = re.compile(rf"(?:===|==|=)[ \t]*(v?{_NUMERIC})", re.IGNORECASE)


def declared_version(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _SPEC.fullmatch(value) or not re.search(r"\d", value):
        return None
    exact = _EXACT.fullmatch(value)
    return exact.group(1) if exact else value


def version_lower_bound(constraint: str) -> str | None:
    """The lowest numeric bound stated by every branch of a declared constraint."""
    bounds = []
    for alternative in re.split(r"\|\|?", constraint):
        terms = _TERMS.findall(alternative)
        if interval := re.match(rf"\s*(v?{_NUMERIC})\s+-\s+v?{_NUMERIC}", alternative, re.IGNORECASE):
            terms = [interval.group(1)]
        lower = []
        for term in terms:
            match = _BOUND.match(term.strip())
            if match and match["operator"] not in ("<", "<=", "!="):
                lower.append(match["version"])
        if not lower:
            return None
        bounds.append(max(lower, key=version_key))
    return min(bounds, key=version_key)


def version_key(version: str) -> tuple[int, ...]:
    parts = tuple(map(int, version.split(".")))
    return parts + (0,) * (4 - len(parts))
