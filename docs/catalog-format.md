# Catalog format

The [reference library](references.md) holds source material you can use when contributing a pack. The records below define what OpenGuildKit can apply to a project or use in a board review.

The catalog has four collections, one JSON file per record:

```text
src/openguildkit/registry/          shared catalog, shipped with the package
  packs/<id>.json
  boards/<id>.json
  sectors/<id>.json
  patterns/<id>.json
.openguildkit/catalog/              optional, private to one project
  packs/ boards/ sectors/ patterns/
```

`catalog.py` validates every file at load time. Use `openguildkit catalog --json` to list packs, boards and sectors. Use `openguildkit patterns --json` for the [pattern collection](patterns.md). A pattern can name the reference entries on its subject in an optional `references` list. `check_reference_links` in `references.py`, run by the tests on the bundled catalog, checks that each one exists and names the pattern or one of its packs back.

## Rules common to all records

| Field | Type | Constraint |
|---|---|---|
| `id` | string | Lowercase letters, digits and single hyphens (`secure-sdlc`). Unique within its collection, across bundled and project records. Use the file name `<id>.json`. |
| `title` | string | Single line, not empty |
| `description` | string | Single line, not empty |
| `sources` | array | Can be empty. Each item is `{"title": "...", "url": "https://..."}`. HTTPS only, no credentials in the URL, no duplicate URL in one record, no tracking parameter (`utm_*`, `trk`, `gclid`, `fbclid`, `visit_id`, `siteLocation`, a copied `#:~:text=` fragment...). |

Also enforced:

- No field outside the schema. A typo such as `"instructions"` instead of `"instruction"` fails.
- No duplicate keys in the same JSON object.
- Every text value is a single line without control characters.
- Files are UTF-8 (a BOM is accepted). Only `.json` files are read.

## Packs

A pack is a versioned set of rules an agent follows and a reviewer can verify.

```json
{
  "id": "iso-27001",
  "title": "ISO/IEC 27001 context",
  "version": "1.0.0",
  "description": "Project evidence and ownership prompts for teams working under an information security management system.",
  "sources": [
    {"title": "ISO/IEC 27001:2022 overview", "url": "https://www.iso.org/standard/27001"}
  ],
  "depends_on": ["secure-sdlc"],
  "rules": [
    {
      "id": "confirm-isms-scope",
      "instruction": "Ask the security owner which systems, teams and data fall within the organization's information security management system.",
      "verification": "Link to the approved scope or record a scope question for the owner."
    }
  ]
}
```

| Field | Constraint |
|---|---|
| `version` | `major.minor.patch`, no leading zeros |
| `depends_on` | Optional. IDs of other packs. Must exist, no duplicates, no cycles. Dependencies are activated before the pack. |
| `conflicts_with` | Optional. IDs of packs whose rules cannot both apply to the same scope. A project that selects both must record which ones it keeps, with a reason. A pack cannot depend on a pack it conflicts with. |
| `rules` | Non-empty array of `{id, instruction, verification}`, each with an optional `check` and an optional `evidence` (see below). Rule IDs follow the ID format and are unique within the pack. A rule with a `check` may leave out `instruction` and `verification`: the CLI writes them from the check. |

Versioning: bump `patch` for wording fixes, `minor` for a new rule, `major` for a removed or reversed rule. Projects pin the records they use in `.openguildkit/catalog.lock.json`, so a changed pack reaches them only when they run `openguildkit update --apply`. From then on their fingerprint changes and pending approvals need a new consultation.

### Machine checks and named evidence

A rule can declare a `check` that `openguildkit task verify` evaluates and records as a check of the task, `rule:PACK/RULE`, with the evidence it found. Only `task verify` records it: `task result` refuses an outcome for it. The declarative kinds read the project's files with the standard library and run nothing:

| `kind` | Fields | Passes when |
|---|---|---|
| `file-exists` | `paths`: 1 to 20 paths | One of the paths exists. |
| `text` | `paths`, `contains`: 1 to 20 literal texts of at most 200 characters, `expect`: `present` or `absent`, optional `ignore_case` | `present`: a file contains one of the texts. `absent`: no file contains any. |
| `field` | `path` of a `.json` or `.toml` file, `field` as a dotted path such as `tool.audit.level`, and at least one of `equals`, `one_of`, `min`, `max`, `integer: true` | The field exists and meets every condition. `true` and `1` are different values. |
| `command` | `command` | The command exits with 0. Only a pack in `.openguildkit/catalog/packs/` may declare it: the project already controls its check commands. A bundled pack, a central policy or a catalog lock with a command is refused. |

Paths are relative to the project root, written with `/`, made of letters, digits, `. _ - @ + =` and the wildcards `*`, `?` and `**`, without `.` or `..` segments; a `field` path names one file, without wildcards. A path that resolves outside the project through a link is ignored, and `.git` and `.openguildkit` are not searched. The work is bounded: at most 200 matched files (more fails the check and asks for narrower paths) and 1,000,000 bytes per file read (a larger file fails the check). Texts are matched literally, never as regular expressions, so a check always runs in time proportional to the files it reads. Field checks read JSON and TOML only; YAML is not supported. A file that is not valid JSON or TOML fails the check with the parser's message.

A rule can also name pieces of evidence that a person keeps outside the code, such as the record of processing activities:

```json
{
  "id": "update-processing-record",
  "instruction": "When the change creates or alters a processing of personal data, ask the privacy owner to update the record of processing activities.",
  "verification": "Link the updated entry of the record of processing activities from the change.",
  "evidence": [{"id": "processing-record", "title": "Record of processing activities"}]
}
```

Each entry becomes a check `evidence:PACK/RULE/ID` that every task answers in `task result`: either the evidence itself, status `passed` with a project path that exists or an `https://` link, or status `not-applicable` with a `reason` and an `owner` when it does not concern the task. `task complete` refuses the task while an evidence has no answer. The evidence must be supplied, and `not-applicable` is refused, when the rule or its pack is listed in the profile's `required_rules`, or when the entry declares `"when": {"data": [...]}` and the task's `data` answer is one of the listed values (`none`, `internal`, `personal`, `regulated`, `unsure`). The `gdpr` pack uses `"when": {"data": ["personal", "regulated"]}` for the record of processing activities and the decision on a data protection impact assessment. A rule names at most 5 pieces of evidence.

The [central export-rule example](../examples/export-expiry/README.md) is a pack `export-link-expiry` with one rule whose check is a `field` check: `{"kind": "field", "path": "export.json", "field": "downloadLinkMinutes", "integer": true, "min": 1, "max": 60}`. `ci-check` evaluates it on the exact target commit with the same evaluator as `task verify`, and the CLI derives the instruction and verification text from the check. The former form, `"check": {"max_minutes": 60}`, is still read as that same field check. The Node coordinator in `integrations/ci/` supports this one rule, in either form.

## Boards

A board is a discipline's review lens.

```json
{
  "id": "performance",
  "title": "Performance",
  "description": "Set a measurable performance target and compare the change with a representative baseline.",
  "expertises": [
    "Client-side responsiveness and rendering",
    "Service latency, throughput and resource use",
    "Benchmark design and regression analysis"
  ],
  "triggers": ["performance", "latency", "throughput", "slow", "latence", "temps de réponse"],
  "questions": [
    "Which user journey or service call needs a performance budget?",
    "What baseline, traffic shape and dataset represent real use?",
    "Which measurement separates client rendering, service work and upstream delays?"
  ],
  "sources": [{"title": "Google, Web Vitals", "url": "https://web.dev/articles/vitals"}]
}
```

| Field | Constraint |
|---|---|
| `expertises` | Non-empty list. The specialties the board brings. |
| `review` | [Brain review](brains.md) with specialists, evidence requests, challenge prompts and decision criteria. Each specialist has an `id`, a `title`, a `focus` and optional `checks`: a list of what an expert of that lens verifies. Required for a board added by a project; every bundled board has one. |
| `triggers` | Non-empty list. Words or phrases that select the board when they appear as whole words in a brief. Matching ignores case, accents, the kind of apostrophe and regular plurals; the longest overlapping phrase wins, and a board's own shorter phrase never cancels its longer one, so `dora lead time` in `devops` keeps `dora` from selecting `legal`. Add translations (`sécurité`, `rgpd`) so non-English briefs route correctly, and avoid words that are common in other disciplines. |
| `questions` | Non-empty list. What the board asks of every task it reviews. |

A project file in `.openguildkit/catalog/boards/` whose `id` is a bundled board completes that board instead of being refused as a duplicate. It may hold only the fields it changes: `title` and `description` replace the bundled text, the lists (`expertises`, `triggers`, `questions`, `sources`, and in `review` the `evidence`, `challenge` and `decision_criteria`) gain the new items, and a specialist replaces the bundled one with the same `id` or is added. The merged board is validated like any other. `openguildkit brains --new ID` writes the skeleton of a new project board, with its pattern, pack and reference.

## Sectors

A sector adds domain context to every consultation and to `AGENTS.md`.

```json
{
  "id": "internal-tools",
  "title": "Internal tools",
  "description": "Adapt reviews to applications with named teams and internal operators.",
  "context": [
    "Identify the operating team, the groups who can access each workflow and the owner who approves role changes."
  ],
  "sources": []
}
```

| Field | Constraint |
|---|---|
| `context` | Non-empty list of instructions specific to the sector. |

A sector selects rules through the patterns that list it in `match.sectors`: `init` and `recommend` preselect them for the person to confirm or decline (see [patterns](patterns.md#browse-and-preview)). The bundled sectors are `general`, `financial-services`, `insurance`, `healthcare`, `public-sector`, `e-commerce`, `education` and `critical-infrastructure`; `openguildkit catalog` prints the packs each one preselects. Their packs cover EU law and name the jurisdiction in their description; national rules come on top.

To add a sector of your own, put its record in the project catalog and a pattern that names it, then answer the sector question with its ID:

```text
.openguildkit/catalog/sectors/internal-tools.json
.openguildkit/catalog/patterns/internal-tools-access.json   "match": {"sectors": ["internal-tools"]}
```

The pattern can reuse bundled packs or packs from `.openguildkit/catalog/packs/`. A pattern that names a sector absent from the catalog is refused when the catalog loads.

`general` is the default. If a saved profile uses a sector absent from the current catalog, add that sector to the project's local catalog or set `sector` to an available ID in `.openguildkit/project.json`, then run `openguildkit sync`.

## Tools

`registry/tools/CATEGORY.json` lists the tools of a company's stack and the MCP servers that connect an agent to them (see [tools.md](tools.md)). One file per category:

```json
{
  "id": "issue-tracking",
  "title": "Issue tracking and work management",
  "tools": [
    {
      "id": "linear",
      "title": "Linear",
      "vendor": "Linear",
      "summary": "Issue tracking and product planning for software teams.",
      "homepage": "https://linear.app",
      "brains": ["project-management", "engineering", "product"],
      "servers": [
        {
          "id": "linear-remote",
          "name": "Linear MCP Server",
          "publisher": "vendor",
          "maintainer": "Linear",
          "transport": "streamable-http",
          "url": "https://mcp.linear.app/mcp",
          "auth": "oauth-or-token",
          "env": [],
          "status": "unknown",
          "capabilities": "Find, create and update Linear issues, projects and comments.",
          "source": "https://linear.app/docs/mcp",
          "verified": "2026-11-21"
        }
      ],
      "api": {"kind": "graphql", "docs": "https://linear.app/developers"}
    }
  ]
}
```

| Field | Constraint |
|---|---|
| `brains` | Non-empty list of board IDs that use the tool. |
| `aliases` | Optional. Other names a team writes for the tool. |
| `detect` | Optional signs of the tool in a repository: `files` (paths or `*` patterns inside the project), `npm` and `pypi` dependency names. |
| `servers` | The MCP servers verified for the tool. Empty when none is on record: say what exists instead in `notes` and `api`. |
| `servers[].publisher` | `vendor` when the tool's own company publishes or hosts the server, `community` otherwise. A community server is proposed only when the team asks for it. |
| `servers[].transport` | `streamable-http`, `sse` or `stdio`. A remote server has a `url`; a `stdio` server has `command`, `args` and `package` (`registry` and `name`). |
| `servers[].env` | Names of the environment variables the server reads. Never a value: an argument such as `TOKEN=...` is refused, and so is a credential in a URL. |
| `servers[].settings` | `name` and `description` of each `{placeholder}` used in the `url` or the `args`, such as a subdomain. |
| `servers[].status` | `ga`, `beta`, `preview`, `experimental` or `deprecated` as the publisher states it, `unknown` otherwise. |
| `servers[].source`, `verified` | The publisher's page or the server's repository where the endpoint or the command was read, and the day it was read. A directory site or a blog post is not a source. |
| `api` | Optional. The tool's main public API: `kind` (`rest`, `graphql`, `other`) and `docs`. |

A server shared by several tools (one server for an issue tracker and its wiki) keeps the same `id` and the same endpoint in each entry. `registry/tool-mocks/TOOL.json` holds the synthetic answers of a tool's mock; its format is in [tools.md](tools.md#mocks-demos-and-tests-without-an-account). Mock data is fictional: no real person, company or address, emails on `example.test`.

## Writing good records

- Write each instruction as an action an agent can take in a repository or a question it must ask a named owner.
- Write each verification as something a reviewer can check: a file, a test, a record, a link.
- Link the official source (standard body, regulator, project documentation). Paraphrase; do not copy text from paid standards.
- Link the canonical page, not a search result, a template download or a course page. Give the source a title that describes it, such as `IETF RFC 7208, Sender Policy Framework`, not the browser tab text or the host name.
- Use one address for a document across packs, patterns, boards and references, at the edition the catalog cites. `tests/test_catalog_sources.py` checks the usual variants (an RFC on two IETF sites, `index.html`, a final slash).
- Do not claim compliance. "Map project controls to the Statement of Applicability" is a rule. "This makes you ISO 27001 compliant" is not.
- Keep one idea per rule. Split a rule that needs "and" twice.
- Start a pack description with the context it applies to, such as "For a service in production: ...". [Catalog coverage](coverage.md) shows, for each brain, the packs its patterns reach and the references no pack applies yet.
- Keep one method per pack, so that a pattern activates only the rules of its method. When you split a pack, keep its ID for the part its name describes, move the other rules to a new pack and bump the major version.
- When a service pack serves HTTP endpoints, declare `depends_on: ["api-design"]` so the contract rules apply to every stack.
