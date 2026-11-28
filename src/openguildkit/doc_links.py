"""The address of a documentation page, for a message that sends the reader to it.

A workstation installed from a wheel has no `docs/` folder, so a message gives the page on GitHub, at the tag of the
installed version (`main` for a source checkout or a development version, which no tag names).

Entry: doc_link
Tests: tests/test_doc_links.py, tests/test_workflow_pages.py
"""

from functools import cache

REPOSITORY = "https://github.com/Sandbox-podcast/OpenGuildKit"


@cache
def _revision() -> str:
    from .lock import package_version  # Heavy to import, and only a message with a link needs it.

    version = package_version()
    return "main" if "+" in version or ".dev" in version or version == "unknown" else f"v{version}"


def doc_link(page: str, anchor: str = "") -> str:
    """The https address of a repository page (`docs/workflow.md`) and of a heading of it (`signed-approvals`)."""
    return f"{REPOSITORY}/blob/{_revision()}/{page}" + (f"#{anchor}" if anchor else "")
