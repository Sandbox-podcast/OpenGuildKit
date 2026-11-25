"""Whether a person can type at this process's standard input."""

import sys

if sys.platform == "win32":
    import ctypes
    import msvcrt

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.GetConsoleMode.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint))
    _KERNEL32.GetConsoleMode.restype = ctypes.c_int


def interactive_input() -> bool:
    """True when stdin is a console a person can type at.

    On Windows, isatty() is true for every character device, including NUL. A command that
    treats NUL as a terminal then reads a line and fails with EOF. GetConsoleMode on the
    input handle is what distinguishes a console. A test that replaces isatty() is stating
    the case it wants; that replaced method is not the NUL device.
    """
    stream = sys.stdin
    if not stream.isatty():
        return False
    if _isatty_replaced(stream) or sys.platform != "win32":
        return True
    return _windows_console(stream)


def _isatty_replaced(stream) -> bool:
    """True when a test replaced isatty on this stream. A real file keeps the method on its class."""
    return "isatty" in getattr(stream, "__dict__", {})


def _windows_console(stream) -> bool:
    try:
        fileno = stream.fileno()
    except (AttributeError, OSError, ValueError):
        return True
    try:
        handle = msvcrt.get_osfhandle(fileno)
    except OSError:
        return False
    mode = ctypes.c_uint()
    return bool(_KERNEL32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)))
