# Tools and MCP servers

## Read an OpenGuildKit project through MCP

Add a local server to an MCP client using its [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
Point it at one initialized project. Use the installed command's absolute path if the
client does not inherit your shell's PATH.

```json
{
  "mcpServers": {
    "openguildkit": {
      "command": "openguildkit",
      "args": ["--project", "/absolute/path/to/project", "mcp"]
    }
  }
}
```

| Tool | Inputs | Result fields |
| --- | --- | --- |
| `project_profile` | None | `sector`, `components` (objects with an `id`), `packs` (active pack references) |
| `project_rule` | `pack_id`, `rule_id` | `pack` (an active pack reference), `rule_id` |
| `task_status` | `task_id` | `id`, `status` as recorded in the task |
| `task_check_results` | `task_id` | `id`, `revision`, `checks` (objects with `check`, `status` and `revision`) |

A pack reference contains `id`, `version` and `scope` from the catalog in force.
Scope is a list of component IDs, or `null` for a project-wide pack. A revision is a
full Git commit ID, `"working tree"` or `null` when no safe commit reference is recorded.
Outcomes use the CLI's check IDs. Imported scenario names that contain free text
are available through `task show` in the terminal. Before a task records any results,
`checks` is empty and `revision` is `null`.

Each successful call returns the same JSON object as structured content and as a
text item. Invalid arguments and unknown IDs return a JSON-RPC parameter error.
If the project files need attention, the tool points to `openguildkit check` for
diagnostics. Access is limited to the project selected at startup. The responses
exclude briefs, approval details, command lines, logs and evidence contents.
Reviews, approvals, changes and publishing stay in the existing human workflows.


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

1. Name the tools in the profile, in the words the team uses. `openguildkit init` asks for them, proposes the tools the repository shows signs of, and keeps the names the registry does not know; `openguildkit profile add tool Jira --by NAME --reason WHY` adds one later. The profile then holds `"tools": ["Jira", "Factorial", "Snyk"]`.
2. `openguildkit tools recommend` resolves those names and adds what the repository shows: a `.github/workflows` folder, a `sentry-sdk` dependency, a `.storybook` folder, a `playwright.config.ts`. Names it does not know are listed apart.
3. `openguildkit tools plan jira factorial snyk` prints what would be configured and writes nothing:

```text
jira, confluence: server `atlassian-rovo` (vendor, streamable-http, status ga).
    Verified 2026-11-21 on https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/
    Each person signs in once: /mcp in Claude Code.
    claude-code: {"type": "http", "url": "https://mcp.atlassian.com/v2/mcp"}
```

Each server of the plan also lists what a security review needs. A fact the registry holds comes from the publisher's page. "Not documented by the publisher (looked for on DATE)" means someone read that page and found nothing; "not recorded in the registry yet: read URL" means nobody has looked yet:

```text
    Publisher: SonarSource (vendor)
    Covers: Inspect issues, hotspots, projects, source, quality gates, metrics and rules, run analysis, ...
    Access: Issues, quality gates, metrics and rules of the projects the token's user can see; write tools such as ...
    Scopes and consent: SonarQube Server needs a user token (project and global tokens do not work); ...
    Read-only mode: SONARQUBE_READ_ONLY=true disables the write tools (default false). Select it with --read-only.
    Version: Docker image sonarsource/sonarqube-mcp without a tag: the documented command pulls latest at every start (--pull=always). ...
    Credentials: Read from each person's environment: SONARQUBE_TOKEN, SONARQUBE_ORG, SONARQUBE_URL; no file holds them.
    Alternatives: The rest API without MCP: https://next.sonarqube.com/sonarqube/web_api
```

`Alternatives` lists the other servers on record for the same tool (pick one with `TOOL/SERVER`, for example `google-workspace/drive-mcp`) and the tool's API. Tool names are accepted whatever their case: `tools plan Notion` works.

`Access` says whether the registered command reads, writes or both. "Read operations described; no enforced read-only mode is recorded" means the publisher lists reads without promising that nothing writes; "depending on the server configuration" means the tools enabled, the settings or the consent decide. Whatever the plan says, give the account or the token only the permissions the task needs.

`--read-only` selects the publisher's read-only mode, and among a tool's servers prefers one that has such a mode. `openguildkit tools plan supabase buildkite --read-only` uses the publishers' restricted endpoints; `openguildkit tools plan google-workspace --read-only` picks the Workspace search server, whose scopes all read. To browse newsletter audiences, `openguildkit tools plan mailchimp/mailchimp-marketing-local --community --read-only` sets `MAILCHIMP_READ_ONLY=true`: review the community server's source before supplying a Marketing API key. The default Mailchimp entry uses Mandrill for transactional mail, and `mailchimp/mailchimp-docs-mcp` searches the public Marketing API documentation. A server without a read-only mode is planned with a warning, never silently.

The plan ends with the `openguildkit tools apply ...` command to paste, with the same options and the tools that can be connected; when none can, it says so instead. `apply` refused for want of `--yes` prints the same command with `--yes`.

4. The team reviews the plan. `openguildkit tools apply ...` with the same arguments writes the entries and records them in `.openguildkit/tools.json`, which is committed. For a live server, `apply` asks for a yes in a terminal and, without a terminal, writes nothing unless `--yes` says the team accepted the plan. Mocks need no confirmation.

| Option | Use |
|---|---|
| `TOOL/SERVER` | Pick a server when a tool has several, for example `github/github-local` |
| `--set TOOL.NAME=VALUE` | A setting the endpoint needs, such as `--set zendesk.subdomain=acme` |
| `--token-env TOOL=VARIABLE` | Read the bearer token of a remote server from this environment variable instead of signing in |
| `--community` | Allow a community-maintained server, once the team has reviewed its source |
| `--read-only` | Select the read-only mode of each server whose publisher documents one (a header, a URL, an argument or a variable), preferring a tool's server that has one; the plan warns for the others. Not with `--mock` |
| `--yes` | With `apply`: write the live servers without asking, once the team reviewed the plan |

`apply` ends with what it connected and what it could not (`Connected servers: atlassian-rovo. Tools not connected: gryzzly.`, or `Connected mocks: ...` with `--mock`). A tool without an MCP server, without a mock, or that the registry does not know (a name the profile kept, such as `steam`), stays in `tools status` as not connected, with the reason, until it is connected or removed with `tools remove`. The exit status lets a script tell the cases apart:

| Exit status | Meaning |
|---|---|
| 0 | Every requested tool is connected |
| 2 | Some tools are connected, others are not (listed on the last line) |
| 1 | Nothing could be connected, or the command was refused (a message says why); nothing was written to the host file |

With the host `other`, `plan` and `apply` write nothing and say which `--host` to pass.
| `--host claude-code` or `codex` | Write for another host than the project's |
| `--mock` | Connect local mocks instead (see below) |

`openguildkit tools status` lists recorded connections, missing environment variables and mock requests that could not be connected. `openguildkit tools recommend` shows which host already has each tool configured and whether it uses a mock or a live server. `openguildkit tools remove TOOL` removes a connection or clears an unavailable mock request.

### What is written

| Host | File | Remote server | Local server |
|---|---|---|---|
| Claude Code | `.mcp.json` at the project root | `{"type": "http", "url": ...}`, plus `"headers": {"Authorization": "Bearer ${VARIABLE}"}` with `--token-env` | `{"command": ..., "args": [...], "env": {"NAME": "${NAME}"}}` |
| Codex | `.codex/config.toml`, between two marker lines | `url`, plus `bearer_token_env_var` with `--token-env` | `command`, `args`, `env_vars = ["NAME"]` |

Entries the team wrote itself are kept. If one already uses the same name with other settings, the command stops and names it. Both hosts ask each person before they use a project's servers: Claude Code asks for approval the first time, Codex reads the project file only in a trusted project.

### Credentials

A server names the variables it reads. The host passes them from each person's environment. `--token-env TOOL=VARIABLE` accepts only an environment variable name (letters, digits and `_`, not starting with a digit), such as `JIRA_TOKEN`; the CLI does not read the variable's value. For OAuth servers each person signs in once in their host (`/mcp` in Claude Code, `codex mcp login NAME`).

`--set TOOL.NAME=VALUE` refuses:

- a setting whose name is a secret word (token, secret, password, passwd, API key, bearer);
- a value that is not plain: letters, digits and `._:/@-` only, up to 200 characters, starting with a letter or digit;
- a value that matches a credential shape of the table below.

| Shape | Recognized by |
|---|---|
| Cloud access key ID | `AKIA` or `ASIA` followed by 16 letters or digits |
| Stripe secret key | `sk_live_`, `sk_test_`, `rk_live_` or `rk_test_` followed by 8 or more letters or digits |
| GitHub token | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` followed by 16 or more letters or digits, or `github_pat_` |
| Slack token | `xoxa-`, `xoxb-`, `xoxp-`, `xoxo-`, `xoxs-`, `xoxr-` or `xoxe-` followed by 8 or more characters |
| GitLab token | `glpat-` followed by 20 or more characters |
| Google API key | `AIza` followed by 35 characters |
| Anthropic API key | `sk-ant-` followed by 20 or more characters |
| OpenAI API key | `sk-`, `sk-proj-`, `sk-svcacct-` or `sk-admin-` followed by 20 or more characters, one of them a digit |
| npm token | `npm_` followed by 36 letters or digits |
| PyPI token | `pypi-AgE` followed by 40 or more characters |
| Hugging Face token | `hf_` followed by 30 or more letters or digits |
| Atlassian API token (Jira, Confluence) | `ATATT3` followed by 20 or more characters |
| Linear API key | `lin_api_` or `lin_oauth_` followed by 32 or more letters or digits |
| Notion token | `ntn_` followed by 40 or more letters or digits |
| Sentry token | `sntrys_` or `sntryu_` followed by 30 or more characters |
| Figma token | `figd_` followed by 30 or more characters |
| Slack webhook link | `https://hooks.slack.com/services/…` (also `workflows/` and `triggers/`); the host and path stay, the rest is replaced |
| Discord webhook link | `https://discord.com/api/webhooks/ID/…`, also `discordapp.com`, `ptb.` and `canary.` |
| Google OAuth client secret | `GOCSPX-` followed by 20 or more characters |
| SendGrid API key | `SG.`, then two dot-separated parts of 16 and 30 or more characters |
| Azure storage key | `AccountKey=` or `SharedAccessKey=` followed by 20 or more base64 characters, as in a connection string |
| JSON Web Token | three dot-separated base64url parts, the first two starting with `eyJ` |
| Private key | a `-----BEGIN ... PRIVATE KEY-----` block |
| Link with a password | `scheme://user:password@host` |
| Secret in a query string | `?token=`, `&api_key=`, `&password=`, `&signature=`, `&sig=` and their variants, with a value |
| Password | `password=`, `password:`, `passwd=` or `mot de passe:` followed by a value |
| Authorization header | `Authorization: Bearer`, `Basic` or `Token` followed by 8 or more characters |
| Secret in a setting | a key ending in `api_key`, `token`, `secret`, `client_secret`, `access_key` or `secret_key` (`AWS_SECRET_ACCESS_KEY`, `x-api-key`, `"api_key"` in JSON), then `:` or `=`, then a quoted value or 8 or more characters with a digit |

A variable name or a placeholder is not a secret and stays as written: `${JIRA_TOKEN}`, `$TOKEN`, `%API_KEY%`, `{{ secrets.TOKEN }}`, `<token>`, `[credential]`, a name in capitals such as `YOUR_TOKEN`, or a value with an ellipsis (`token=...`).

What is not detected: a token without a known prefix written on its own (a random string in a sentence), a secret after a key the table does not name (`pwd:`, `auth:`, `key:`), an unquoted value of a setting without a digit (`api_key: abcdefgh`), a webhook or a token of a provider not listed here, a secret split over several lines, and an encoded or encrypted secret. The detector reduces mistakes; it is not a secret scanner. Keep credentials in each person's environment or in the tool's vault, and run the team's own scanner on the repository.

The table lives in one place, `src/openguildkit/sensitive.py`, and the same shapes apply wherever the CLI records what a person or an agent writes. The refusal never repeats the value, and the apply command a plan or a refusal prints writes `--set TOOL.NAME=VALUE` in place of a value of these shapes.

Use placeholders for sensitive data in task briefs. `task new`, a brief revised with `task consult --brief` and answers given with `--answers` keep the person's words but replace each credential with a placeholder (`[credential]`, `[password]`, `[private key]`) before anything is written, and warn that they did. They also warn, without refusing, about an email address, a phone number or a bank account number: a brief may name a role address. A board's review entry that holds a credential is refused, with the field named; a public evidence link on a private host, or with a credential in its query, is refused.

A server is third-party code with access to company data. Before `apply`, read its `source`, prefer the publisher's own server, and give it the narrowest account the tool allows. The Security brain reviews the choice like any other change when it goes through a task.

## Mocks: demos and tests without an account

`--mock` connects each tool to a stand-in server that ships with OpenGuildKit:

```bash
openguildkit tools apply jira tempo snyk --mock --log mock-calls.jsonl
```

`tools apply --mock` ends with the tools it connected and the ones that have no mock (`Connected mocks: jira, snyk. Tools without a mock: gryzzly.`), keeps the connections it could make, and records the others so that `tools status` lists them as not connected, with the reason. The exit status is the one described above (0, 2 or 1).

The host starts `openguildkit tools mock jira`, a local MCP server that answers with synthetic data over stdio. It runs offline, with no account and no key. By default the data is generic sample data about a fictional support portal, its tickets, its pull request, its time entries, its alerts; a search that finds nothing says so and tells how to list every record. `--log` appends calls received by that server from an MCP client; a call to a write tool is marked `"write": true`, and its answer says that nothing was changed anywhere, that the mock keeps nothing (a refund created now does not appear in `list_refunds` later: mocks answer the same way every time), and that a real write needs `task authorize`. A direct `tools call` runs outside the MCP server and does not add to its journal. Applying a mock again without `--log` keeps the journal its entry already had.

Nineteen tools have a mock: Jira, GitHub, Slack, Notion, Factorial, Tempo, Toggl Track, Snyk, Sentry, SonarQube, HubSpot, Stripe, Pennylane, Zendesk, Google Analytics, Figma, Storybook, Obscura and Datadog (`openguildkit tools list --mocks`).

```bash
openguildkit tools call jira                                            # the mock's tools
openguildkit tools call jira search_issues --args '{"query": "export"}' # one call, no MCP client needed
```

`tools call TOOL` lists each of the mock's tools, marked read or write, with its arguments (type, required or optional, admitted values) and an example call that works; `tools call TOOL --json` gives the same list as JSON, for a program that offers the tools by name (the web interface does). A missing or unknown argument prints the same. A search ignores case and finds every record that contains all the words; an empty query lists them all. An id one call returns is accepted by the other tools of the same mock, except an id a simulated write hands out (`create_issue` returns `SUP-200`): the mock keeps nothing, and a lookup that finds no record names the ids the mock holds, then the ids its writes return and does not keep. A simulated write prints a reminder to use `task authorize` before making a real write.

### Your project's own data

The bundled story rarely fits a clinic, a game or a city service. A scenario file gives the mocks your own records, without writing a mock. No command can invent a clinic's data: the team or its agent writes the records that tell the project's story, with synthetic values only. A starting file helps:

```bash
openguildkit tools scenario --task booking       # or --brief "Let patients book an appointment online"
```

It writes `.openguildkit/catalog/tool-mocks/scenario.json` for the project's tools that have a mock. It names the project, adds to the issue tracker one record for the task (`BOOKING-1`, with the task's brief), and copies the bundled sample records unchanged for you to replace; the brief goes nowhere else. It then prints, per tool, the two or three fields that tell the story, for example `zendesk: tickets (ticket_id, subject, status)`. Name tools to limit it (`tools scenario jira zendesk`); `--force` replaces an existing file. Edit it freely:

```json
{
  "about": "Synthetic records for Clinic booking.",
  "records": {
    "jira": {"issues": [{"key": "BOOK-1", "summary": "Book an appointment online", "status": "In progress"}]},
    "hubspot": {
      "deals": [{"deal_id": "d-1", "name": "Riverside Clinic: booking pilot", "company_id": "c-1"}],
      "companies": [{"company_id": "c-1", "name": "Riverside Clinic", "contact": "desk@example.test"}]
    }
  }
}
```

Each tool lists its collections (`tools call TOOL` and the bundled file show their fields). A collection you give replaces the bundled one; the others stay. The file is refused when a record lacks its id, when a record cites an id its collection does not hold, or when an email address is not on a reserved test domain such as `example.test`. Every value stays invented: never paste a real customer's data.

A mock's tool names are its own. It rehearses the agent's flow (find the ticket, cite it, log the time); it does not imitate a publisher's API, and what works against a mock still has to be tried against the real server.

The server answers both generations of the protocol: the revisions that open with an `initialize` handshake (2024-11-05 to 2025-11-25) and the stateless revision 2026-07-28, where each request names its version and `server/discover` replaces the handshake.

A project can also write a whole mock in `.openguildkit/catalog/tool-mocks/TOOL.json`. Records serve list and get tools; canned responses serve the others:

```json
{
  "tool": "jira",
  "tools": [
    {
      "name": "get_issue",
      "description": "Get one issue by key.",
      "read_only": true,
      "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
      "serve": {"records": "issues", "action": "get"}
    },
    {
      "name": "add_comment",
      "description": "Comment on an issue.",
      "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "body": {"type": "string"}}, "required": ["key", "body"]},
      "check": {"key": "issues"},
      "responses": [{"result": {"key": "$arg:key", "body": "$arg:body"}}]
    }
  ],
  "records": {
    "issues": {"key": "key", "title": "summary", "items": [{"key": "SUP-142", "summary": "Export as CSV", "status": "In progress"}]}
  }
}
```

A collection has `items`, the `key` its get tools look up, an optional `title` (the field a scenario retitles) and optional `refs` (`{"company_id": "companies"}`: ids that must exist in another collection). `serve` with `"action": "list"` filters the records by each argument: `query` searches the text, an argument with `enum` must equal the field, any other text is contained in it; `fields` keeps some fields, `total` adds a sum. `check` refuses an id its collection does not hold. A tool with `responses` returns the first one whose `when` matches (text matches when it is contained, whatever the case); the last one has no `when` and is the default. `"$arg:NAME"` in a result is replaced by the caller's argument.

## Evidence from a tool

When tools are connected, each board's brief lists the ones it can query, and a review can cite what was read there:

```json
{"source": "tool", "ref": "jira:SUP-142", "supports": "The request is tracked and in progress."}
```

Use one of the project's connected tools. When recording a review, the CLI warns if the tool falls outside that board's scope. For a live tool, it warns when the local journals hold no call with the cited record: live host calls do not appear in them, so check those citations in the host.

Evidence read from a mock is synthetic. It may be recorded, so a demo or a rehearsal completes, even behind a proceed with high confidence, and it is always labelled: the review warns that the cited record comes from the mock, or that the mock holds no such record and nothing supports the citation; the decision brief and the approval prompt carry one line, `Mock data: N evidence item(s) come from mock tools, ...`, and the exported decision record lists them under `mock_evidence`.

Use HTTPS links without credentials for public evidence. The CLI checks the literal hostname and query without resolving the host. Cite internal evidence with a project file or a connected tool. A board only reads during a review. Creating a ticket, logging time or posting a message is an external action the person authorizes.

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

A project adds its own tools, for example an internal MCP server, in `.openguildkit/catalog/tools/CATEGORY.json`, with the same format as the bundled files in `src/openguildkit/registry/tools/`. A project entry cannot redefine a bundled tool or take one of its names (ID, title or alias): typing a bundled tool's name always selects the bundled record. `tools plan` and `tools apply` mark a project tool `[project catalog]` and say that its facts and its command are the team's own, not verified by OpenGuildKit.

To contribute to the bundled registry, read [catalog-format.md](catalog-format.md#tools). Every fact comes from the publisher's own documentation or the server's repository, opened on the date written in `verified`. A directory site or a blog post is not a source.

## What was verified

- The registry entries were read on their publisher's pages on 2026-11-21. Access, scopes and read-only modes were looked for the same day on the publishers' pages of GitHub (remote and local), the Atlassian server, Slack, Notion, Linear, Sentry (remote), Snyk, Stripe, HubSpot, Figma (remote), Datadog, Zendesk, SonarQube, Azure DevOps (remote), Microsoft Teams (Work IQ), Google Workspace and Mailchimp Transactional. The other servers carry whether they read, write or both, and for some the consent, the scopes and the read-only mode, from the same source pages without a `reviewed` date; whatever is missing, `tools plan` says is not recorded yet and names the page to read. For some remote servers the page shows an HTTP URL without naming the transport; they are recorded as streamable HTTP.
- The host file formats come from the hosts' documentation of the same day and from what `codex mcp add` writes (Codex 0.171).
- Claude Code 2.1.328 connects to the mocks (`claude mcp list` reports them connected) and reads the `.mcp.json` this command writes, pending each person's approval.
- Not verified: a live session of Codex against the mocks, and any connection to a real tool, which needs an account.
