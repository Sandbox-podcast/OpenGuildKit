"""Whether a person can answer at this terminal.

Every act left to a person, and every question asked at a terminal, starts with `interactive()`. Python's
`isatty()` is true on Windows for any character device, the NUL device included: there the handle of standard
input must also be a console. `typed()` is the one place where a person confirms an act by typing its name.
"""
import os
import sys


def interactive() -> bool:
    """True when standard input is a terminal a person types in."""
    stream = sys.stdin
    try:
        if stream is None or not stream.isatty():
            return False
    except ValueError:  # A closed stream.
        return False
    try:
        descriptor = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return True  # A stand-in stream with no device behind it: its own answer stands.
    return console(descriptor)


def typed(expected: str, prompt: str, *, refusal: str | Exception, cancelled: str) -> None:
    """The person types `expected` at this terminal, or the act stops: ValueError(refusal) without a terminal (or the
    exception given), ValueError(cancelled) when they type anything else. The prompt goes to standard error."""
    if not interactive():
        raise refusal if isinstance(refusal, Exception) else ValueError(refusal)
    print(prompt, end="", file=sys.stderr, flush=True)
    if input().strip() != expected:
        raise ValueError(cancelled)


def console(descriptor: int) -> bool:
    """True unless the system says the descriptor is not a console (only Windows can tell NUL from a console)."""
    return windows_console(descriptor) if os.name == "nt" else True


def windows_console(descriptor: int) -> bool:
    """True when Windows has a console mode for the handle: a console answers, NUL or a serial port does not."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = msvcrt.get_osfhandle(descriptor)
    except OSError:
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    mode = wintypes.DWORD()
    return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def reader_closed() -> int:
    """The reader of the output stopped early, as `| head` does: end quietly, like a command that finished.

    Standard output then points at the null device, so the interpreter's last flush cannot fail again.
    """
    try:
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, sys.stdout.fileno())
        os.close(null)
    except (OSError, ValueError, AttributeError):
        pass  # Not a real file descriptor, as when a test captures the output: nothing is flushed at exit.
    return 0


def utf8_streams() -> None:
    """Write redirected output in UTF-8 on every platform, as agents and scripts read it, and never fail on a
    character standard error cannot show. cli.main and the edit hook call it when run as a command."""
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="backslashreplace")


def warn(message: str) -> None:
    """One line on standard error, after the name of the tool."""
    print(f"OpenGuildKit: {message}", file=sys.stderr)
