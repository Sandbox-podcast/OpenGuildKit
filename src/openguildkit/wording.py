"""The words of the outputs: a count with its noun, in the singular when the count is one.

Entry: plural
Tests: tests/test_cli_surface.py
"""


def plural(count: int, word: str) -> str:
    """`1 file`, `2 files`, `0 files`: the count and its noun, for every output that counts something."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
