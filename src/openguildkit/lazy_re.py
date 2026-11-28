"""Regular expressions compiled when a command first uses them, not when their module is imported.

A command imports many more modules than it runs code of, and compiling each module's expressions at import cost
about 10 ms per command (#539). compile() gives an object that stands for the pattern: it compiles the pattern the
first time one of its attributes is read, then keeps each attribute it hands out, so later calls cost what calls on
a compiled pattern cost. Use its methods (search, match, sub, finditer...); do not pass it to the functions of re.

Entry: compile
Tests: tests/test_performance.py, tests/test_routing.py, tests/test_sensitive.py
"""

import re
from typing import cast


class _Pattern:
    def __init__(self, pattern: str, flags: int):
        self._source = (pattern, flags)

    def __getattr__(self, name: str):
        compiled = self.__dict__.get("_compiled")
        if compiled is None:
            compiled = self.__dict__["_compiled"] = re.compile(*self._source)
        value = getattr(compiled, name)
        self.__dict__[name] = value
        return value


def compile(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """re.compile(pattern, flags), compiled at its first use."""
    return cast(re.Pattern[str], _Pattern(pattern, flags))
