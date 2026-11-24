"""Select the OpenGuildKit command used by every part of a field campaign."""

import os
import sys
import tempfile
from pathlib import Path

INSTALLED_ENV = "OPENGUILDKIT_FIELD_INSTALLED"
SRC = Path(__file__).resolve().parents[2] / "src"


def uses_installed_package() -> bool:
    return os.environ.get(INSTALLED_ENV) == "1"


def command(*arguments: str) -> list[str]:
    # Isolated mode ignores the checkout and PYTHONPATH, even when the kit lives next to the sources.
    options = ["-I", "-X", "utf8"] if uses_installed_package() else []
    return [sys.executable, *options, "-m", "openguildkit", *arguments]


def environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.setdefault("PYTHONPYCACHEPREFIX", str(Path(tempfile.gettempdir()) / "openguildkit-pycache"))
    env["PYTHONIOENCODING"] = "utf-8"
    if uses_installed_package():
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC), env.get("PYTHONPATH")]))
    return env
