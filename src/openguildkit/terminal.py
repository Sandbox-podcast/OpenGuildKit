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
