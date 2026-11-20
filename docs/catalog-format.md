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

`catalog.py` validates every file at load time. Use `openguildkit catalog --json` to list packs, boards and sectors. Use `openguildkit patterns --json` for the [pattern collection](patterns.md).

## Rules common to all records

| Field | Type | Constraint |
|---|---|---|
| `id` | string | Lowercase letters, digits and single hyphens (`secure-sdlc`). Unique within its collection, across bundled and project records. Use the file name `<id>.json`. |
| `title` | string | Single line, not empty |
| `description` | string | Single line, not empty |
| `sources` | array | Can be empty. Each item is `{"title": "...", "url": "https://..."}`. HTTPS only, no credentials in the URL, no duplicate URL in one record. |

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
| `rules` | Non-empty array of `{id, instruction, verification}`. Rule IDs follow the ID format and are unique within the pack. |

Versioning: bump `patch` for wording fixes, `minor` for a new rule, `major` for a removed or reversed rule. Any change to a pack changes the fingerprint of projects that use it, so their pending approvals need a new consultation.

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
| `review` | Optional [brain review](brains.md) with specialists, evidence requests, challenge prompts and decision criteria. |
| `triggers` | Non-empty list. Words or phrases that select the board when they appear as whole words in a brief. Matching ignores case and Unicode width. Add translations (`sécurité`, `rgpd`) so non-English briefs route correctly. |
| `questions` | Non-empty list. What the board asks of every task it reviews. |

## Sectors

A sector adds domain context to every consultation and to `AGENTS.md`.

```json
{
  "id": "insurance",
  "title": "Insurance",
  "description": "Adapt the review to the insurer, intermediary or software supplier and the insurance workflow in scope.",
  "context": [
    "Identify the insurance line, jurisdiction, organisation's role and affected workflow, such as quotes, underwriting, distribution, policy servicing or claims."
  ],
  "sources": [
    {"title": "Regulation (EU) 2022/2554, DORA", "url": "https://eur-lex.europa.eu/eli/reg/2022/2554/oj/eng"}
  ]
}
```

| Field | Constraint |
|---|---|
| `context` | Non-empty list of instructions specific to the sector. |

## Writing good records

- Write each instruction as an action an agent can take in a repository or a question it must ask a named owner.
- Write each verification as something a reviewer can check: a file, a test, a record, a link.
- Link the official source (standard body, regulator, project documentation). Paraphrase; do not copy text from paid standards.
- Do not claim compliance. "Map project controls to the Statement of Applicability" is a rule. "This makes you ISO 27001 compliant" is not.
- Keep one idea per rule. Split a rule that needs "and" twice.
