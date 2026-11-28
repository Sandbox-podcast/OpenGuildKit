"""The `integrations`, `mcp`, `ui` and `ci-check` commands, which connect a project to other tools.

Entry: run.
Tests: tests/test_integrations.py, tests/test_webui.py, tests/test_cli_coverage.py.
"""

from pathlib import Path

from .ci import check_export
from .command import Command
from .errors import OgkError
from .integrations import OTHER_HOST_NOTE, install_agent_files
from .lock import package_version
from .storage import print_json


def _integrations(command: Command) -> None:
    args = command.args
    base = Path.home() if args.user else command.root
    for item in install_agent_files(base, args.host, args.force):
        print(f"{Path(item['file']).as_posix()}: {item['action']} (openguildkit {package_version()})")
    if args.host == "other":
        print(OTHER_HOST_NOTE)


def _mcp(command: Command) -> int:
    args = command.args
    if args.project is None:
        raise OgkError("OGK-INIT-001", "Supply --project PATH to open a project MCP server.")
    state = command.state
    if args.policy_repo is not None or args.policy_commit is not None:
        raise OgkError("OGK-INIT-006", "The MCP server reads the project catalog in force without policy overrides.")
    from .project_mcp import serve_project  # Only this command serves MCP.

    return serve_project(state)


def _ui(command: Command) -> int:
    from . import webui  # Only this command serves pages; every other one starts without the web server.

    args = command.args
    return webui.serve(command.root, args.port, args.static, not args.no_browser, stable_address=args.stable_address)


def _ci_check(command: Command) -> int:
    result = check_export(command.profile, command.catalog, command.args.target_repo, command.args.commit)
    print_json(result)
    return 0 if result["status"] == "success" else 1


HANDLERS = {"integrations": _integrations, "mcp": _mcp, "ui": _ui, "ci-check": _ci_check}


def run(command: Command) -> int | None:
    return HANDLERS[command.args.command](command)
