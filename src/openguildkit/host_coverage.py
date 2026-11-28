"""The coverage of each host and surface (hook before an edit, approval commands refused), with the pages read; `host
check --matrix` prints it and docs/host-coverage.md carries its table.

`openguildkit host check --matrix --json` prints it for a fleet view, `host check --matrix` prints the table of
docs/host-coverage.md, and tests/test_doc_pages.py fails when the page and this table differ. The hosts with a hook
come from HOOK_HOSTS and EDIT_MATCHERS of hosts.py, the tools without one from UNHOOKED_TOOLS: a row that names no
page read says `not established`.

Entry: add_options, matrix, markdown_table, run.
Tests: tests/test_doc_pages.py (HostCoverageTests), tests/test_cli_coverage.py.
"""

from . import hosts
from .errors import OgkError
from .storage import print_json

STATUSES = ("enforced", "partial", "instruction", "none", "not established")
CONTROLS = ("hook_before_edit", "approval_command_refused")
CLAUDE_PAGES = (("Hooks", "https://code.claude.com/docs/en/hooks"),
                ("permissions", "https://code.claude.com/docs/en/permissions"))
CLAUDE_SETTINGS = (("Settings", "https://code.claude.com/docs/en/settings"),)
CODEX_PAGES = (("Rules", "https://learn.chatgpt.com/docs/agent-configuration/rules"),
               ("hooks", "https://learn.chatgpt.com/docs/hooks"))
GEMINI_PAGES = (("Hooks", "https://geminicli.com/docs/hooks/"),
                ("hooks reference", "https://geminicli.com/docs/hooks/reference/"),
                ("configuration", "https://geminicli.com/docs/reference/configuration/"))
NOT_ESTABLISHED = ("not established", "")


def _tools(host: str) -> str:
    """The edit tools the hook of a host runs on, as the page writes them: `Edit`, `Write` and `NotebookEdit`."""
    names = [f"`{name}`" for name in hosts.EDIT_MATCHERS[host].split("|")]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _row(host: str, surface: str, hook: tuple[str, str], approval: tuple[str, str], pages=(), read=None) -> dict:
    return {"host": host, "surface": surface,
            "controls": {name: {"status": status, "detail": detail}
                         for name, (status, detail) in zip(CONTROLS, (hook, approval), strict=True)},
            "pages": [{"title": title, "url": url} for title, url in pages], "read": read,
            **({"edit_tools": hosts.EDIT_MATCHERS[host].split("|")} if host in hosts.EDIT_MATCHERS else {})}


def matrix() -> list[dict]:
    """One row per host and surface, in the order of docs/host-coverage.md."""
    rows = [
        _row("claude-code", "Terminal, with `host apply`",
             ("partial", f"the hooks run on {_tools('claude-code')}; a write by the shell or by a script is not stopped"),
             ("partial", "deny rules match a command line; a script file gets around them"), CLAUDE_PAGES, "2026-11-21"),
        _row("claude-code", "Editor extension, desktop application",
             ("not established", "the settings page says they read the same files as the terminal; no session was run"),
             NOT_ESTABLISHED, CLAUDE_SETTINGS, "2026-11-28"),
        _row("claude-code", "Cloud thread in a project (claude.ai/code)",
             ("none", "none of the repository's `.claude/settings.json` hooks apply"),
             ("none", "none of its permission rules apply"), CLAUDE_SETTINGS, "2026-11-28"),
        _row("claude-code", "Cloud session on one repository, outside a project's threads",
             ("not established", ("the page says `.claude/settings.json` is read; whether the hook's `openguildkit` "
                                 "is installed in the cloud environment is not")),
             ("not established", "the page says the file is read; no session was run"), CLAUDE_SETTINGS, "2026-11-28"),
        _row("claude-code", "Cloud session on several repositories",
             ("none", "only `enabledPlugins` and `extraKnownMarketplaces` are read from each `.claude/settings.json`"),
             ("none", "permission rules are not read"), CLAUDE_SETTINGS, "2026-11-28"),
        _row("claude-code", "Action or headless run in CI", NOT_ESTABLISHED, NOT_ESTABLISHED),
        _row("codex", "Terminal, trusted project, with `host apply`",
             ("partial", ("`.codex/hooks.json` runs before `apply_patch`; Codex reads project settings only once the "
                         "project is trusted")),
             ("partial", ("`.codex/rules/openguildkit.rules` forbids the commands as written, and an exact prefix does "
                         "not match `--project /other/path`")), CODEX_PAGES, "2026-11-21"),
        _row("codex", "Cloud, CI", NOT_ESTABLISHED, NOT_ESTABLISHED),
        _row("gemini-cli", "Terminal, with `host apply`",
             ("partial", (f"the hooks on `BeforeAgent` and `BeforeTool` cover {_tools('gemini-cli')}; a hook that "
                         "cannot start lets the action through")),
             ("instruction", ""), GEMINI_PAGES, "2026-11-25"),
        _row("gemini-cli", "Non-interactive mode, IDE, GitHub Action",
             ("not established", "the pages say nothing about them"), NOT_ESTABLISHED, GEMINI_PAGES[:1], "2026-11-25"),
    ]
    for tool_id, tool in hosts.UNHOOKED_TOOLS.items():
        rows.append(_row(tool_id, "Any, including the cloud agent" if tool_id == "copilot" else "Any",
                         ("none", "no page shows the file an edit tool changes, so no hook is written"),
                         ("instruction", ""), zip(tool["titles"], tool["pages"], strict=True), tool["read"]))
    rows.append(_row("other", "Any", ("instruction", "the AGENTS.md instruction and `guard --ci`"), ("instruction", "")))
    return rows


def _cell(control: dict) -> str:
    return f"`{control['status']}`" + (f": {control['detail']}" if control["detail"] else "")


def _pages(row: dict) -> str:
    if not row["pages"]:
        return "Not applicable" if row["host"] == "other" else "None read"
    links = [f"[{page['title']}]({page['url']})" for page in row["pages"]]
    joined = links[0] if len(links) == 1 else f"{', '.join(links[:-1])} and {links[-1]}"
    return f"{joined}, read {row['read']}"


def markdown_table() -> str:
    """The table of docs/host-coverage.md, "Each host and surface"."""
    lines = ["| Host | Surface | Hook before an edit | Approval command refused | Pages read |", "|---|---|---|---|---|"]
    for row in matrix():
        host = "Any other agent (`other`)" if row["host"] == "other" else f"`{row['host']}`"
        hook, approval = (_cell(row["controls"][name]) for name in CONTROLS)
        lines.append(f"| {host} | {row['surface']} | {hook} | {approval} | {_pages(row)} |")
    return "\n".join(lines) + "\n"


def add_options(host) -> None:
    host.add_argument("--matrix", action="store_true",
                      help="With check: print the coverage of every host and surface; needs no project.")


def run(args) -> int:
    """host check --matrix: the table of every host and surface, as JSON with --json."""
    if args.mode != "check":
        raise OgkError("OGK-HOST-001", "--matrix is an option of openguildkit host check.")
    if args.json:
        print_json({"statuses": list(STATUSES), "rows": matrix()})
    else:
        print(markdown_table(), end="")
    return 0
