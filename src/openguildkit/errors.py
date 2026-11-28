"""The one-line forms of the errors a person reads: a file that cannot be opened, in words, and an unknown identifier
with the command that lists them.

Entry: os_error_message, unknown
Tests: tests/test_error_forms.py
"""


def os_error_message(error: OSError) -> str:
    """What failed on which file, in words, never the `[Errno N]` text of Python."""
    name = error.filename
    if name is None:
        return f"{error.strerror or error}".rstrip(".") + "."
    if isinstance(error, FileNotFoundError):
        return f"Cannot open {name}: it does not exist."
    if isinstance(error, PermissionError):
        return f"Cannot open {name}: permission denied."
    if isinstance(error, IsADirectoryError):
        return f"Cannot open {name}: it is a folder, not a file."
    return f"Cannot open {name}: {(error.strerror or 'it cannot be read').rstrip('.').lower()}."


def unknown(kind: str, value: object, command: str) -> str:
    """The error for an identifier the project does not know: the kind, the value and the command that lists them."""
    return f"Unknown {kind}: {value}. Run openguildkit {command}."
