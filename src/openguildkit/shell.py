"""Commands printed for a person to paste: one quoting rule for the CLI, the tool commands and the local server.

A word that needs quoting goes between single quotes, inside which neither a POSIX shell nor PowerShell expands
anything: `$`, a backtick and a double quote stay as typed. Only the escape of a single quote inside differs, so
the form follows the platform: PowerShell on Windows, a POSIX shell elsewhere. cmd.exe reads neither form.

Entry: shell_word, shell_command
Tests: tests/test_next_steps.py, tests/test_projects.py
"""

import os

from . import lazy_re

# Words any shell reads as typed. A tilde inside a word, as in a Windows short path (RUNNER~1), is read by no shell;
# a leading one, or one after = or :, may stand for a home folder, and zsh reads a leading = as a command path.
_POSIX_PLAIN = lazy_re.compile(r"[\w@%+:,./-][\w@%+=:,./-]*(?:(?<=[\w%+,./@-])~[\w@%+=:,./-]*)*")
# PowerShell also reads a comma as a list and a leading @ as splatting.
_POWERSHELL_PLAIN = lazy_re.compile(r"[\w%+=:./-][\w@%+=:./-]*(?:(?<=[\w%+./@-])~[\w@%+=:./-]*)*")
# PowerShell closes a single-quoted string at any of these; doubling one keeps it.
_POWERSHELL_QUOTES = lazy_re.compile("['‘’‚‛]")


def shell_word(value: str, powershell: bool | None = None) -> str:
    """A command-line word as a person pastes it, quoted only when it needs it; powershell defaults to Windows."""
    if powershell is None:
        powershell = os.name == "nt"
    if powershell:
        if _POWERSHELL_PLAIN.fullmatch(value):
            return value
        return "'" + _POWERSHELL_QUOTES.sub(lambda match: match.group(0) * 2, value) + "'"
    if _POSIX_PLAIN.fullmatch(value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def shell_command(words: list[str], powershell: bool | None = None) -> str:
    """A whole command line, each word quoted by shell_word."""
    return " ".join(shell_word(word, powershell) for word in words)
