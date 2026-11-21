# Tools and MCP servers

A company already works with an issue tracker, a time tracker, an HR system, a security scanner, a design tool. An agent that can read them gives the boards real evidence: the ticket, the alert, the design frame. OpenGuildKit keeps a registry of these tools and of the [Model Context Protocol](https://modelcontextprotocol.io) (MCP) servers that connect an agent to them, proposes the ones that match a project, writes the host's configuration once the team accepts it, and can replace every server with a local mock for demos and tests.

The CLI stays offline. It never contacts a tool, never installs a server and never reads a credential. The host agent (Claude Code, Codex) is the MCP client.

## The registry

`openguildkit tools list` shows 133 tools in 22 categories, from issue tracking and time tracking to finance, support, security, observability, design and browsers for agents. Each entry names the brains that use the tool, and each MCP server on record carries:

- who publishes it (`vendor` when it is the tool's own company, `community` otherwise) and its status when the publisher states one (`ga`, `beta`, `preview`...);
- its transport and endpoint: a remote URL, or the command that starts a local server;
- how it authenticates, and the names of the environment variables it reads. Names only, never values;
- the page where this was read and the date it was read (`source`, `verified`).

```bash
openguildkit tools list --category time-tracking
openguildkit tools list --brain security
openguildkit tools show jira
```

A tool without an MCP server is still listed, with its public API, so that nobody goes looking twice. On 2026-11-21 that is the case of Gryzzly, Lucca, PayFit, Spendesk, Agicap, Timely and a few others. When a publisher announces a server but its endpoint could not be read on its own documentation, the entry says so and lists no server.

The registry is checked like the rest of the catalog: the weekly link check opens every `source`, and a server whose page disappears is reported.

## From a project's stack to its servers

1. Name the tools in the profile (`"tools": ["Jira", "Factorial", "Snyk"]` in `.openguildkit/project.json`), in the words the team uses. `openguildkit init` asks for them, proposes the tools the repository shows signs of, and keeps the names the registry does not know.
2. `openguildkit tools recommend` resolves those names and adds what the repository shows: a `.github/workflows` folder, a `sentry-sdk` dependency, a `.storybook` folder, a `playwright.config.ts`. Names it does not know are listed apart.
3. `openguildkit tools plan jira factorial snyk` prints what would be configured and writes nothing:

```text
jira, confluence: server `atlassian-rovo` (vendor, streamable-http, status ga).
    Verified 2026-11-21 on https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/
    Each person signs in once: /mcp in Claude Code.
    claude-code: {"type": "http", "url": "https://mcp.atlassian.com/v2/mcp"}
```

4. The team reviews the plan. `openguildkit tools apply ...` with the same arguments writes the entries and records them in `.openguildkit/tools.json`, which is committed.

| Option | Use |
|---|---|
| `TOOL/SERVER` | Pick a server when a tool has several, for example `github/github-local` |
| `--set TOOL.NAME=VALUE` | A setting the endpoint needs, such as `--set zendesk.subdomain=acme` |
| `--token-env TOOL=VARIABLE` | Read the bearer token of a remote server from this environment variable instead of signing in |
| `--community` | Allow a community-maintained server, once the team has reviewed its source |
| `--host claude-code` or `codex` | Write for another host than the project's |
| `--mock` | Connect local mocks instead (see below) |

`openguildkit tools status` lists the recorded connections, says whether the host file still holds them, and names the variables that are not set on this workstation. `openguildkit tools remove TOOL` takes a connection out.

### What is written

| Host | File | Remote server | Local server |
|---|---|---|---|
| Claude Code | `.mcp.json` at the project root | `{"type": "http", "url": ...}`, plus `"headers": {"Authorization": "Bearer ${VARIABLE}"}` with `--token-env` | `{"command": ..., "args": [...], "env": {"NAME": "${NAME}"}}` |
| Codex | `.codex/config.toml`, between two marker lines | `url`, plus `bearer_token_env_var` with `--token-env` | `command`, `args`, `env_vars = ["NAME"]` |

Entries the team wrote itself are kept. If one already uses the same name with other settings, the command stops and names it. Both hosts ask each person before they use a project's servers: Claude Code asks for approval the first time, Codex reads the project file only in a trusted project.

### Credentials

No command accepts a secret, and no file holds one. A server names the variables it reads; the host passes them from each person's environment. `--set` refuses a value that looks like a credential, and `--token-env` takes the name of a variable. For OAuth servers each person signs in once in their host (`/mcp` in Claude Code, `codex mcp login NAME`).

A server is third-party code with access to company data. Before `apply`, read its `source`, prefer the publisher's own server, and give it the narrowest account the tool allows. The Security brain reviews the choice like any other change when it goes through a task.

## Mocks: demos and tests without an account

`--mock` connects each tool to a stand-in server that ships with OpenGuildKit:

```bash
openguildkit tools apply jira tempo snyk --mock --log mock-calls.jsonl
```

The host then starts `openguildkit tools mock jira`, a local MCP server on stdio that answers with synthetic data: a fictional support portal, its tickets, its pull request, its time entries, its alerts. No network, no account, no key. `--log` appends every call the agent makes, so a test can assert what the agent did.

Nineteen tools have a mock: Jira, GitHub, Slack, Notion, Factorial, Tempo, Toggl Track, Snyk, Sentry, SonarQube, HubSpot, Stripe, Pennylane, Zendesk, Google Analytics, Figma, Storybook, Obscura and Datadog (`openguildkit tools list --mocks`).

```bash
openguildkit tools call jira                                            # the mock's tools
openguildkit tools call jira search_issues --args '{"query": "export"}' # one call, no MCP client needed
```

A mock's tool names are its own. It rehearses the agent's flow (find the ticket, cite it, log the time); it does not imitate a publisher's API, and what works against a mock still has to be tried against the real server.

The server answers both generations of the protocol: the revisions that open with an `initialize` handshake (2024-11-05 to 2025-11-25) and the stateless revision 2026-07-28, where each request names its version and `server/discover` replaces the handshake.

A project adds its own mock in `.openguildkit/catalog/tool-mocks/TOOL.json`:

```json
{
  "tool": "jira",
  "tools": [
    {
      "name": "get_issue",
      "description": "Get one issue by key.",
      "read_only": true,
      "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
      "responses": [
        {"when": {"key": "SUP-142"}, "result": {"key": "SUP-142", "status": "In progress"}},
        {"error": "Issue not found."}
      ]
    }
  ]
}
```

The first response whose `when` matches the arguments is returned (text matches when it is contained, whatever the case); the last one has no `when` and is the default. `"$arg:NAME"` in a result is replaced by the caller's argument.

## Evidence from a tool

When tools are connected, each board's brief lists the ones it can query, and a review can cite what was read there:

```json
{"source": "tool", "ref": "jira:SUP-142", "supports": "The request is tracked and in progress."}
```

The tool must be one of the project's connections; anything else is refused. A board reads; it changes nothing in a tool during a review. Creating a ticket, logging time or posting a message is an external action the person authorizes.

## The tooling section

Four tools have a deeper integration than an MCP entry.

| Tool | What OpenGuildKit does with it | Brains | Limits |
|---|---|---|---|
| [Documentalist](https://github.com/azerothl/documentalist) | `openguildkit docs export` writes the Reference, Learn and Blog folders it imports; `docs share` keeps the register of who was given access. See [documentation.md](documentation.md) | Communication, Support, Product | Its [MCP server](documentation.md#read-published-pages-through-mcp) reads published pages. Import and access management happen in Documentalist |
| [Storybook](https://storybook.js.org) | `openguildkit storybook` composes the company design system, records stories the Design brain can cite, and extracts a design system from an existing application. Its MCP addon lets an agent read stories while Storybook runs. See [storybook.md](storybook.md) | Design, Engineering, QA | The addon is marked preview by its publisher and answers on a local port |
| [ChaosFolk](https://github.com/loukan42/chaosfolk) | `openguildkit task verify ID --chaosfolk SUMMARY` records a replay's scenarios as checks of the task. See the `chaosfolk-e2e` pack | QA, Engineering | No MCP server on record |
| [Obscura](https://obscura.sh) | A headless browser built for agents, listed with its MCP server (`obscura mcp`). QA uses it to open the application and read a page as a snapshot; Product and Marketing use it to read public pages when the research policy allows | QA, Engineering, Product, Marketing | See below |

### Obscura

Obscura is an open-source browser engine (Apache-2.0) with its own renderer, not a Chromium build. `openguildkit tools plan obscura` proposes its stdio server; install the binary from its releases first.

- It blocks localhost and private networks by default. To test an application on a workstation, start the host with `OBSCURA_ALLOW_PRIVATE_NETWORK=1` in the environment.
- Page JavaScript runs inside the Obscura process. Its security policy recommends a container or a virtual machine for pages you do not trust.
- Use the standard build, on your own applications and on sites whose terms allow automated access. The stealth build and proxy rotation are outside what OpenGuildKit sets up: getting around a site's bot protection can breach its terms of use.
- Playwright and Puppeteer can also drive it over the Chrome DevTools Protocol (`obscura serve --port 9222`, then `connectOverCDP`).

The Obscura mock returns the snapshot of a fictional page, so a QA rehearsal runs without the binary.

## Adding a tool

A project adds its own tools, for example an internal MCP server, in `.openguildkit/catalog/tools/CATEGORY.json`, with the same format as the bundled files in `src/openguildkit/registry/tools/`. A project entry cannot redefine a bundled tool.

To contribute to the bundled registry, read [catalog-format.md](catalog-format.md#tools). Every fact comes from the publisher's own documentation or the server's repository, opened on the date written in `verified`. A directory site or a blog post is not a source.

## What was verified

- The registry entries were read on their publisher's pages on 2026-11-21. For some remote servers the page shows an HTTP URL without naming the transport; they are recorded as streamable HTTP.
- The host file formats come from the hosts' documentation of the same day and from what `codex mcp add` writes (Codex 0.171).
- Claude Code 2.1.328 connects to the mocks (`claude mcp list` reports them connected) and reads the `.mcp.json` this command writes, pending each person's approval.
- Not verified: a live session of Codex against the mocks, and any connection to a real tool, which needs an account.
