# Catalog format

The [reference library](references.md) holds source material you can use when contributing a pack. The records below define what OpenGuildKit can apply to a project or use in a board review.

The catalog has four collections of records, one JSON file per record, and five folders of material that the records and the commands use:

```text
src/openguildkit/registry/          shared catalog, shipped with the package
  packs/<id>.json                   rule packs (below)
  boards/<id>.json                  brains (below)
  sectors/<id>.json                 sectors (below)
  patterns/<id>.json                patterns, see patterns.md
  references/<family>.json          reference library, see references.md
  deliverables/<id>.json            deliverable templates, see deliverables.md
  tools/<category>.json             tools and their MCP servers, see tools.md
  tool-mocks/<tool>.json            synthetic answers of a tool's mock, see tools.md
  features/features.json            features: a lead tool and three alternatives, see tools.md
.openguildkit/catalog/              optional, private to one project
  packs/ boards/ sectors/ patterns/ references/ deliverables/ tools/ tool-mocks/
```

A project folder holds files in the same format as the bundled one and adds to it; an ID that already exists is refused, with two exceptions: a project board completes the bundled board of the same ID (see [Boards](#boards)), and a project mock replaces the bundled mock of the same tool. `openguildkit brains --new ID` writes a project brain in `boards/`, `patterns/`, `packs/` and `references/`.

`catalog.py` validates every file at load time. Use `openguildkit catalog --json` to list packs, boards and sectors. Use `openguildkit patterns --json` for the [pattern collection](patterns.md). A pattern can name the reference entries on its subject in an optional `references` list. A method without a `match` can name, in an optional `core_for` list, the roles of the pattern for which it is preselected by the role alone: its rules apply to any work of that discipline, whatever the product, its interface or its domain, and the catalog marks one or two per role at most. The other methods of a role are suggested, with their description as the reason. A regulation is never preselected by a role. A pattern's `match` can also hold `"people_decisions": true`: the project scores, ranks or decides about people (the EU AI Act). `check_reference_links` in `references.py`, run by the tests on the bundled catalog, checks that each one exists and names the pattern or one of its packs back, and that the packs and brains a reference names exist; `openguildkit check`, `openguildkit references`, `openguildkit brains` and `task consult` run it on the project's own references, against the catalog the project uses with its lock, and stop on the first error.

## Rules common to all records

| Field | Type | Constraint |
|---|---|---|
| `id` | string | Lowercase letters, digits and single hyphens (`secure-sdlc`). Unique within its collection, across bundled and project records. Use the file name `<id>.json`. |
| `title` | string | Single line, not empty |
| `description` | string | Single line, not empty |
| `sources` | array | Can be empty. Each item is `{"title": "...", "url": "https://...", "checked": "YYYY-MM-DD"}`. `checked` is required in the bundled catalog and recommended in a project's own (see [Source dates](#source-dates)). HTTPS only, no credentials in the URL, no duplicate URL in one record, no tracking parameter (`utm_*`, `trk`, `gclid`, `fbclid`, `visit_id`, `siteLocation`, a copied `#:~:text=` fragment...). |

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
    {"title": "ISO/IEC 27001:2022 overview", "url": "https://www.iso.org/standard/27001", "checked": "2026-11-20"}
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
| `rules` | Non-empty array of `{id, instruction, verification}`, each with an optional `check`, an optional `evidence`, an optional `records` and an optional `manual` (see below). Rule IDs follow the ID format and are unique within the pack. A rule with a `check` may leave out `instruction` and `verification`: the CLI writes them from the check. |

Versioning: bump `patch` for wording fixes, `minor` for a new rule, `major` for a removed or reversed rule. Projects pin the records they use in `.openguildkit/catalog.lock.json`, so a changed pack reaches them only when they run `openguildkit update --apply`. From then on their fingerprint changes and pending approvals need a new consultation.

### Machine checks and named evidence

A rule can declare a `check` that `openguildkit task verify` evaluates and records as a check of the task, `rule:PACK/RULE`, with the evidence it found. Only `task verify` records it: `task result` refuses an outcome for it. The declarative kinds read the project's files with the standard library and run nothing:

| `kind` | Fields | Passes when |
|---|---|---|
| `file-exists` | `paths`: 1 to 20 paths | One of the paths exists. |
| `text` | `paths`, `contains`: 1 to 20 literal texts of at most 200 characters, `expect`: `present` or `absent`, optional `ignore_case`, optional `each: true` with `present` | `present`: a file contains one of the texts; with `each`, every file the paths match does, and the check names the files that do not. `absent`: no file contains any. |
| `field` | `path` of a `.json` or `.toml` file, `field` as a dotted path such as `tool.audit.level`, and at least one of `equals`, `one_of`, `min`, `max`, `integer: true` | The field exists and meets every condition. `true` and `1` are different values. |
| `size` | `paths`: 1 to 20 paths, `max_bytes`: a whole number from 1 to 1,000,000,000 | Every file the paths name is at most `max_bytes` bytes. The evidence names the largest file and its size, and every file above the limit when one is. No matching file passes, like `text` with `absent`: nothing is above the limit. Add a `file-exists` check to require the file. |
| `command` | `command` | The command exits with 0. Only a pack in `.openguildkit/catalog/packs/` may declare it: the project already controls its check commands. A bundled pack, a central policy or a catalog lock with a command is refused. |

Paths are relative to the project root, written with `/`, made of letters, digits, `. _ - @ + =` and the wildcards `*`, `?` and `**`, without `.` or `..` segments; a `field` path names one file, without wildcards. A path that resolves outside the project through a link is ignored, a wildcard never matches inside `.git` or `.openguildkit`, and the catalog refuses a path that names one of them. The work is bounded: at most 200 matched files (more fails the check and asks for narrower paths) and 1,000,000 bytes per file read (a larger file fails the check). Texts are matched literally, never as regular expressions, so a check always runs in time proportional to the files it reads. A `size` check does not read the file: it counts its bytes, so the 1,000,000 bytes per file limit does not apply to it, and it measures files only, not folders. Field checks read JSON and TOML only; YAML is not supported. A file that is not valid JSON or TOML fails the check with the parser's message.

A rule can also name pieces of evidence that a person keeps outside the code, such as the record of processing activities:

```json
{
  "id": "update-processing-record",
  "instruction": "When the change creates or alters a processing of personal data, ask the privacy owner to update the record of processing activities.",
  "verification": "Link the updated entry of the record of processing activities from the change.",
  "evidence": [{"id": "processing-record", "title": "Record of processing activities"}]
}
```

Each entry becomes a check `evidence:PACK/RULE/ID` that a task answers in `task result` when its pack concerns the task (see [workflow](workflow.md#only-the-rules-that-concern-the-task)) and, for an entry with `when`, when the task's `data` meets it: either the evidence itself, status `passed` with a project path that exists or an `https://` link and the `owner` who provided or confirmed it, or status `not-applicable` with a `reason` and an `owner` when it does not concern the task. `task complete` refuses the task while an asked evidence has no answer. The evidence must be supplied (`"requirement": "passed"` in the template), and `not-applicable` is held back, when the rule or its pack is listed in the profile's `required_rules`, or when the entry declares `"when": {"data": [...]}` and the task's `data` answer is one of the listed values (`none`, `internal`, `personal`, `regulated`, `unsure`). The `gdpr` pack uses `"when": {"data": ["personal", "regulated", "unsure"]}` for the record of processing activities and the decision on a data protection impact assessment: when the requester does not know whether personal data is involved, the evidence is supplied or the answer is settled first. A rule names at most 5 pieces of evidence.

A rule that no file of the project can settle says why in `manual`, one line: the record lives outside the repository, the decision is a legal assessment, the behaviour shows only in a running system. A rule has a `check` or a `manual`, never both. Every rule of the bundled regulation packs (`gdpr`, `dora`, `nis2`, `iso-27001`, `pci-dss`, `eu-ai-act`, `cyber-resilience-act`, `european-accessibility-act`) has one of the two, and most stack packs carry at least one `text` or `field` check; `tests/test_machine_checks.py` lists the stack packs without one and why. [Catalog coverage](coverage.md#machine-checks-by-pack) counts both per pack.

### A value the task records

A rule whose answer means nothing without a number, such as a quality threshold or a regression budget, names that value in `records`, with a `name` in the ID format, a one-line `description` and optional bounds on its number: `min` (at least), `above` (strictly more than, instead of `min`) and `max` (at most):

```json
{
  "id": "compare-evaluation-baselines",
  "instruction": "Run the evaluation on the approved baseline and on the proposed configuration, ... against the regression budget agreed with the workflow owner.",
  "verification": "Review the cases that changed between the two runs, check that no critical task group drops by more than the recorded budget, and record the release decision.",
  "records": {"name": "regression-budget", "description": "The largest drop from the baseline accepted for a critical task group, such as 2 percentage points of pass rate.", "min": 0, "max": 100}
}
```

`task result ID --template` shows `records`, with the accepted range, and an empty `value` on the check of that rule. A `passed` or `failed` outcome of the check is refused until `value` holds the number with its unit (`2 percentage points`, `95 % of critical cases`), and refused with the accepted range when the first number of the value falls outside the bounds; a `skipped` or `not-applicable` outcome needs none. The value is kept in the task's result next to the evidence. A task consulted before the rule declared `records` keeps the rule as it was approved, so its result is read and completed as before. In the bundled catalog, the `llm-evaluations` rules `evaluate-user-outcomes` (`pass-threshold`), `review-grading-rubric` (`grader-agreement`) and `compare-evaluation-baselines` (`regression-budget`) and the `nist-ai-risk` rule `set-risk-evidence` (`acceptance-threshold`) declare one. The pass threshold and the grader agreement are above 0 and at most 100: a threshold of 0 % accepts every run, so it says nothing. The regression budget and the acceptance threshold are at least 0 and at most 100: 0 is a strict and valid answer, no drop or no failure accepted. The two other `llm-evaluations` rules answer without a number: `check-permitted-tool-use` passes when the traces show no live action and blocked steps stopping, and `record-evaluation-setup` when the run record names each item.

The [central export-rule example](../examples/export-expiry/README.md) is a pack `export-link-expiry` with one rule whose check is a `field` check: `{"kind": "field", "path": "export.json", "field": "downloadLinkMinutes", "integer": true, "min": 1, "max": 60}`. `ci-check` evaluates it on the exact target commit with the same evaluator as `task verify`, and the CLI derives the instruction and verification text from the check. The former form, `"check": {"max_minutes": 60}`, is still read as that same field check. The Node coordinator in `integrations/ci/` supports this one rule, in either form; it does not evaluate a `size` check, and the central policy of `ci-check` takes a `field` check only.

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
  "sources": [{"title": "Google, Web Vitals", "url": "https://web.dev/articles/vitals", "checked": "2026-11-21"}]
}
```

| Field | Constraint |
|---|---|
| `expertises` | Non-empty list. The specialties the board brings. |
| `review` | [Brain review](brains.md) with specialists, evidence requests, challenge prompts and decision criteria. Each specialist has an `id`, a `title`, a `focus` and optional `checks`: a list of what an expert of that lens verifies. An optional `applies_to` lists the task surfaces the lens can concern, among `customer`, `service`, `infrastructure` and `business` (the answers of the task's surface question): for a task whose surfaces meet none of them, the lens is listed as not concerned and the review entry does not ask for its finding. A task whose surface is `unsure` or `other` keeps every lens. Without `applies_to`, a lens concerns every task. An optional `applies_to_concerns` lists the task concerns the lens needs, among `money`, `ai`, `people-decisions` and `credentials`: a task whose concerns name none of them leaves the lens out, and a missing, `unsure` or `other` answer keeps it. Required for a board added by a project; every bundled board has one. |
| `triggers` | Non-empty list. Words or phrases that select the board when they appear as whole words in a brief. Matching ignores case, accents, the kind of apostrophe and regular plurals; the longest overlapping phrase wins, and a board's own shorter phrase never cancels its longer one, so `dora lead time` in `devops` keeps `dora` from selecting `legal`. Add translations (`sécurité`, `rgpd`) so non-English briefs route correctly, and avoid words that are common in other disciplines. |
| `questions` | Non-empty list. What the board asks of every task it reviews. |

A project file in `.openguildkit/catalog/boards/` whose `id` is a bundled board completes that board instead of being refused as a duplicate. It may hold only the fields it changes: `title` and `description` replace the bundled text, the lists (`expertises`, `triggers`, `questions`, `sources`, and in `review` the `evidence`, `challenge` and `decision_criteria`) gain the new items, and a specialist replaces the bundled one with the same `id` or is added. The merged board is validated like any other. A replaced title, description or specialist is the team's choice, and it changes what the board asks of every task: `check` and `task consult` name each one, with the bundled text it replaces, so the person sees it. An edit to `.openguildkit/catalog/` is work an approved task must cover when the guard is on ([the board before every change](../integrations/README.md#the-board-before-every-change)). `openguildkit brains --new ID` writes the skeleton of a new project board, with its pattern, pack and reference.

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

A sector selects rules through the patterns that list it in `match.sectors`: `init` and `recommend` preselect them for the person to confirm or decline (see [patterns](patterns.md#browse-and-preview)). The bundled sectors are `general`, `financial-services`, `insurance`, `healthcare`, `public-sector`, `e-commerce`, `education`, `critical-infrastructure`, `aerospace` and `software-publisher`; `openguildkit catalog` prints the packs each one preselects. Their packs cover EU law and name the jurisdiction in their description; national rules come on top. `aerospace` proposes the information security rules of EASA Part-IS (`aviation-information-security`) and, for software on board an aircraft, the process controls built on ED-12C / DO-178C and ED-202A / DO-326A through EASA AMC 20-115D and AMC 20-42 (`airborne-software-assurance`); its context asks who is in scope and says that state aircraft are outside, and the standards, sold by RTCA and EUROCAE, are named, never quoted. `software-publisher` proposes ISO/IEC 27001 (`iso-27001-certification`, the norm form of the `iso-27001-isms` method, for a certification that customers ask for) and the Cyber Resilience Act; the norms question of `init --questions` gives each norm a `help`, the pattern's description that says when it does not apply (a SaaS outside the CRA, the PCI DSS questionnaire that depends on the payment integration), and the `sources` behind it.

To add a sector of your own, put its record in the project catalog and a pattern that names it, then answer the sector question with its ID:

```text
.openguildkit/catalog/sectors/internal-tools.json
.openguildkit/catalog/patterns/internal-tools-access.json   "match": {"sectors": ["internal-tools"]}
```

The pattern can reuse bundled packs or packs from `.openguildkit/catalog/packs/`. A pattern that names a sector absent from the catalog is refused when the catalog loads.

`general` is the default. If a saved profile uses a sector absent from the current catalog, add that sector to the project's local catalog. Otherwise set `sector` to an available ID in `.openguildkit/project.json` by hand, then run `openguildkit sync`: no command can read a profile whose sector is unknown, `openguildkit profile set sector` included. Once the sector is known again, change it with `openguildkit profile set sector ID --by NAME --reason WHY`.

## References

A file in `references/` is a family of reference entries: standards, regulations, methods and tools that a brain reads during a consultation. `references.py` loads the bundled families, then the project's, and validates each one: the family has `id`, `title` and `references`, the file is named `<id>.json`, and a project family with a bundled ID must keep its title and adds its entries to it. Reference IDs and aliases are unique across all families. The fields of an entry and the closed list of `kind` values are in [references.md](references.md#add-references).

```json
{
  "id": "team-practices",
  "title": "Team practices",
  "references": [
    {
      "id": "team-change-record", "title": "Change record", "category": "Delivery", "kind": "pratique",
      "brains": ["devops"], "summary": "Record the owner, impact and verification results of a production change.",
      "applies_when": "A change affects an interface or operation used by another team.",
      "sources": [{"title": "Team engineering handbook", "url": "https://example.org/engineering/change-records",
                   "checked": "2026-11-21"}]
    }
  ]
}
```

`brains` ties the reference to the brains that read it: a brain's briefs keep the references that best fit the task. `pattern` and `packs` link it to the method and the rule packs that apply it, and `check_reference_links` verifies that those name it back. Every source needs `title`, `url` (HTTPS) and, in the shared catalog, a `checked` date.

## Deliverables

A file in `deliverables/` is the template of a business deliverable: its method, its inputs, the tool actions that need approval and the checks a reviewer runs. `deliverables.py` loads the bundled templates, then the project's; a project template with a bundled ID is refused. The format and the commands are in [deliverables.md](deliverables.md).

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

The file name is the category, one of the 27 that `tools.py` admits: `issue-tracking`, `source-control`, `ci-cd`, `documentation`, `design`, `communication`, `time-tracking`, `hr`, `finance`, `crm`, `marketing`, `support`, `security`, `quality`, `observability`, `cloud`, `data`, `browser`, `testing`, `analytics`, `automation`, `product`, `identity`, `ide`, `registries`, `containers`, `api-management`. A file with another name is refused. A project file in `.openguildkit/catalog/tools/` uses the same names and adds tools to the category; a tool ID that already exists is refused, and so is a project tool whose ID, title (with or without its vendor) or alias is a bundled tool's name, so that typing `Jira` never selects a project record. `tools plan` and `tools apply` mark each project tool `[project catalog]`.

`registry/features/features.json` groups tools into features (see [tools.md](tools.md#features)). Each feature has an `id`, a `purpose`, a `lead` and exactly three `alternatives`; each option names a `tool` of the registry and may carry an `as` label, such as `{"tool": "aws", "as": "Amazon ECR"}`. The four tools of a feature are different. A project cannot add features.

| Field | Constraint |
|---|---|
| `brains` | Non-empty list of board IDs that use the tool. |
| `aliases` | Optional. Other names a team writes for the tool. |
| `detect` | Optional signs of the tool in a repository: `files` (paths or `*` patterns inside the project), `npm` and `pypi` dependency names. |
| `servers` | The MCP servers verified for the tool. Empty when none is on record: say what exists instead in `notes` and `api`. |
| `servers[].publisher` | `vendor` when the tool's own company publishes or hosts the server, `community` otherwise. A community server is proposed only when the team asks for it. |
| `servers[].transport` | `streamable-http`, `sse` or `stdio`. A remote server has a `url`; a `stdio` server has `command`, `args` and `package` (`registry` and `name`). A `docker` command names each variable of `env` with `-e`, or the container never receives it. |
| `servers[].env` | Names of the environment variables the server reads. Never a value: an argument such as `TOKEN=...` is refused, and so is a credential in a URL. |
| `servers[].access`, `scopes` | Optional, only when the publisher's page says it, as one line of text each. `access`: the data the server reaches and whether it reads, writes or both, as registered ("Read operations described; no enforced read-only mode is recorded" when the page lists only reads without promising them). `scopes`: the scopes, permissions, consent or token type it asks, and who consents. Set `reviewed` to the day you looked for them: `tools plan` then prints "not documented by the publisher" for what the page does not say, and "not recorded in the registry yet" when `reviewed` is absent. |
| `servers[].read_only` | Optional. The publisher's read-only mode: `how` (one line) and what selects it: `headers` (plain names and values, never a credential) or a read-only `url` with the same settings for a remote server; the full `args` (a `docker` command still names each `env` variable with `-e`) or `env`, plain values such as `{"MAILCHIMP_READ_ONLY": "true"}` for a local server that is not run by `docker`. `how` alone says the server only reads as registered: nothing to select. `--read-only` on `tools plan` and `tools apply` selects the mode, and prefers the tool's server that has one. |
| `servers[].pin` | Optional. What the publisher says about versions, such as the image tags it documents. Whether the documented command pins a version is read from `args`. |
| `servers[].settings` | `name` and `description` of each `{placeholder}` used in the `url`, the `command` or the `args`, such as a subdomain or the path of a clone; the description says where to find the value, and `tools plan` prints it. A command or an argument copied with the publisher's stand-in (`path/to/`, `<...>`) is refused. |
| `servers[].status`, `status_source` | `ga`, `beta`, `preview`, `experimental` or `deprecated` as the publisher states it, with `status_source`, the page where it says so (often the `source` itself); `unknown` otherwise, without `status_source`. A test refuses a known status without the page that states it. |
| `servers[].source`, `verified` | The publisher's page or the server's repository where the endpoint or the command was read, and the day it was read. A directory site or a blog post is not a source. |
| `api` | Optional. The tool's main public API: `kind` (`rest`, `graphql`, `other`) and `docs`. |

A server shared by several tools (one server for an issue tracker and its wiki) keeps the same `id` and the same endpoint in each entry. `registry/tool-mocks/TOOL.json` holds the synthetic answers of a tool's mock; its format is in [tools.md](tools.md#mocks-demos-and-tests-without-an-account). Mock data is fictional: no real person, company or address, emails on `example.test`.

## Source dates

Every source carries `checked`, a date written `YYYY-MM-DD`, placed right after its `url`:

```json
{
  "title": "Regulation (EU) 2016/679 (GDPR), official text",
  "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng",
  "checked": "2026-11-20"
}
```

`checked` is the day the page was last opened and answered; a contributor who writes or changes a rule re-reads its source and sets the date to that day. It does not certify that someone re-read the whole document on that day.

How a bundled source is verified and dated:

- **A contributor writes or changes a rule.** They open the source, check the rule's article, threshold or wording against it, and set `checked` to that day. The loader refuses a bundled source without a valid date, and a test reads every packs, boards, patterns, sectors, references and deliverables file. Every loader refuses a `checked` date, or a tool server's `verified` or `reviewed` date, that is not a calendar day or that is after today (one day of margin for time zones); a test refuses any bundled date after the day it runs.
- **A maintainer runs the link check.** `python3 -I scripts/check_links.py --out link-report --stamp` opens every source page and writes the dates: a page that answered (available, or redirected to a page that answered) gets the day of the report; a page that did not answer or refused the script (dead, 401, 403, 429, a timeout) keeps its date, and a source that has none gets the day its URL entered the catalog, read from the Git history (`git log -S`, the oldest commit's author date; a shallow clone is refused). The script prints each source that did not answer, to open by hand. It never gives the day of the run to a page that did not answer. `--stamp-from link-report/links-DATE.json` writes the dates from a saved report without opening the pages again, so the result depends only on the report and the history and can be run again after a merge.
- **Every Monday** the `Check catalog links` workflow lists, besides dead, redirected and to-recheck links, the sources whose `checked` date is older than 180 days (`--max-age DAYS` to change it), with the records that cite each one. It fails only on dead links.
- **Editions.** `scripts/watch_editions.py`, run each Monday by the `Watch reference editions` workflow, opens the source pages of each reference that declares an `edition` and looks for the edition's text. A page whose address does not carry the edition is read first; once the watch has seen the edition there, that page alone decides, and the pages whose address carries an edition are no longer opened. It records in `scripts/edition-watch.json`, per reference, the page, the edition last seen and the day (`seen`, `seen_on`), where it was seen (`seen_in`: on the `page`, or in the `catalog` on the latest `checked` date of the reference's sources until the watch finds it on its page), the day of the check (`checked`) and a status: `from-catalog` (seeded, no page opened yet), `found`, `not-found` (the page answered, never showed the edition, and the catalog gives no date), `unreachable`, or `may-have-changed` (the edition recorded as seen is no longer on the page). The workflow opens one issue per reference in `may-have-changed`, never a second one while the first is open, and keeps the updated file as an artifact; the [reference library](references.md#edition-watch) says who commits the file and when. The heuristic compares text: a page that reformats its edition text (`Rev 5` for `Rev. 5`) raises a false alarm; a publisher that keeps the old edition's page online, unchanged, hides a new edition and nothing is detected; a page built by scripts or served as a PDF rarely shows its edition, so it is reported once its catalog date is the last observation, until the reference points at a page that shows the edition; a short edition such as a year can match an unrelated date.

What a project sees:

- `openguildkit references --id ID` and `openguildkit patterns --id ID` print each source with its date, `(checked 2026-11-20)`, and the JSON outputs carry `checked`.
- `openguildkit update` starts with the date of the installed catalog, the most recent `checked` date among its bundled sources, and the number of records that changed since the project's lock: `Installed catalog: sources checked up to 2026-11-21. 3 records changed since the project's lock.` A record whose only change is a newer date shows `~ N sources checked again, latest DATE`; applying it changes no rule and leaves consulted tasks current.
- A project's own sources in `.openguildkit/catalog/` (packs, boards, sectors, patterns, references, deliverables) load without a date, so an upgrade breaks nothing, but `openguildkit check` prints a notice that names each record with an undated source. To date one, open the page, check what the record says against it and add `"checked": "YYYY-MM-DD"` after its `url` with that day's date; change the date each time you re-read the page for a rule. The link check and the edition watch read only the bundled catalog: a project that wants the same watch runs its own.

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
