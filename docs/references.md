# Reference library

For: a contributor or a reviewer who looks up the source behind a rule.

The library starts from the French SOCLE catalog dated 20 November 2026 (`Socle_Catalogue_References.json`). Each entry keeps its family, category, type, description, applicability notes and public source links. Entries whose source ID did not follow the ID convention were renamed and keep that ID as an alias. The descriptions are in French; an entry whose title is French, or an acronym only, also has an English title in `title_en`, which the CLI and the brain briefs show. The library includes conventions, technical specifications, practices, tools and regulations. Families added since then cover the non-technical disciplines: `people` (human resources), `finance`, `legal`, `support`, `communication`, `delivery` (project management and operations) and `strategy` (leadership and governance). [Browse the family files](../src/openguildkit/registry/references/).

## Find a reference

```text
openguildkit references
openguildkit references --family code
openguildkit references "ISO 27001"
openguildkit references --id conventional-commits
openguildkit references --family cloud "observabilite" --json
```

Without options, the command lists the families and their counts. Search matches whole words across names, categories and descriptions, ignoring accents and case. Names are the ID, the title, the English title and the former IDs, so `references GDPR` and `references RGPD` both find `rgpd`, and `references accessibility` finds `wcag-22`. Results with terms in a name appear first. Use `--id` for the full entry and its source links; a former ID such as `pd_iac` or `agent_agent_memory` finds the renamed entry. With `--json`, the command returns an array of matching records. The CLI reads the index locally.

The `work-patterns` family comes from the [pattern catalog](patterns.md). A pattern appears once in the index. When a reference presents it, such as `scrum` for the Scrum pattern, the index shows that reference, which also answers to `pattern-scrum` and ends with the pattern and packs to apply. Other patterns get a generated entry such as `pattern-search-engine-optimization`; edit the pattern record to change it.

## Apply a reference to a project

`openguildkit references` shows material to investigate. `openguildkit catalog` lists the rule packs that can be applied to project instructions. During setup, select the packs that fit your stack and delivery process. For an existing project, run `openguildkit profile add pack ID --by NAME --reason WHY` (or `remove pack`), which rewrites `AGENTS.md`, then `openguildkit check`.

| Optional pack | References used | Evidence to keep |
| --- | --- | --- |
| `release-management` (pattern `release-versioning`) | Conventional Commits, SemVer, Keep a Changelog | Version decision, compatibility checks, release notes |
| `supply-chain` | SLSA, SBOM, SPDX, CycloneDX | Artifact provenance, verification result, SBOM for the shipped version |
| `service-reliability` | SLI, SLO, error budgets, OpenTelemetry, OTLP | SLO definition, dashboard or query, telemetry test |
| `gdpr` | GDPR (Regulation (EU) 2016/679), CNIL guidance, standard contractual clauses | Processing record entry, lawful basis, retention job, DPIA decision |
| `dora` | DORA (Regulation (EU) 2022/2554) | ICT asset inventory, restoration test, register of information |
| `nis2` | NIS 2 (Directive (EU) 2022/2555) and its national transposition | Scope decision, security policy, supplier assessment |
| `eu-ai-act` | AI Act (Regulation (EU) 2024/1689, as amended) | Classification and role, employment use (Annex III, point 4), AI interaction notice, logs kept at least six months, oversight procedure |
| `cyber-resilience-act` | Cyber Resilience Act (Regulation (EU) 2024/2847) | Role decision, release SBOM, disclosure policy, support period |
| `incident-notification` (a dependency of the five packs above) | GDPR Art. 33-34, NIS 2 Art. 23, DORA Art. 19 and Delegated Regulation (EU) 2025/301, Cyber Resilience Act Art. 14, AI Act Art. 73 | One notification matrix in the incident runbook: authority, trigger, deadlines and notifier for each regulation that applies |

When turning a new reference into a pack, confirm its edition, the conditions where it applies and the team that owns it. Write the action to take, how to verify it and what evidence to keep. Use your organization's approved interpretation for regulatory requirements and licensed standards.

### From a reference to a verified rule

`openguildkit references --id ID` shows the edition the entry describes, then either the pattern and the packs that apply it, with their version and rule IDs, or `Status: documentary reference` when no pack turns it into rules yet. `--json` returns the same information in the `edition`, `pattern`, `packs` and `status` fields.

Before a project activates a requirement, it records four things: the scope (which components and data the requirement covers), the owner who answers for it, the source and edition it relies on, and the evidence a reviewer will check. Record them in a project pack under `.openguildkit/catalog/packs/`, next to the bundled pack it extends, so the agent receives them as rules and `openguildkit check` keeps them in force. The catalog lock pins both packs, so a new edition of the bundled pack reaches the project only through `openguildkit update`.

### Worked example: GDPR for a support console

`openguildkit references --id rgpd` lists the `gdpr` pack and its rules, among them `update-processing-record` and `apply-retention-period`. The team adds the following file as `.openguildkit/catalog/packs/team-gdpr.json`, with its own scope, owner and evidence:

<!-- worked-example: team-gdpr -->
```json
{
  "id": "team-gdpr",
  "title": "Support console GDPR scope",
  "version": "1.0.0",
  "description": "For the support console and its ticket export: the team's scope, owner and evidence for the gdpr pack.",
  "sources": [
    {"title": "Regulation (EU) 2016/679, General Data Protection Regulation", "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng"}
  ],
  "depends_on": ["gdpr"],
  "rules": [
    {
      "id": "confirm-gdpr-scope",
      "instruction": "Apply the gdpr pack to the support console and the ticket export only. Ask the data protection officer before extending it to another component.",
      "verification": "Check that docs/privacy/scope.md lists the two components and the data protection officer's approval date."
    },
    {
      "id": "link-processing-entry",
      "instruction": "Link each change that alters personal data in the support console to entry RT-12 of the record of processing activities.",
      "verification": "Open the change and follow the link to entry RT-12."
    },
    {
      "id": "store-privacy-evidence",
      "instruction": "Store retention tests and impact assessment decisions under docs/privacy/evidence/ with their date and the person who decided.",
      "verification": "List docs/privacy/evidence/ and find one dated file for each decision named in the task."
    }
  ]
}
```

Then it runs `openguildkit profile add pack team-gdpr --by NAME --reason WHY`, with the person's name and reason, and `openguildkit check`. `AGENTS.md` lists `gdpr` before `team-gdpr`, so the regulation's rules come first and the team's scope, owner and evidence next; `task brief ID --pack PACK` prints either in full. The link runs from the reference (`rgpd`) to the bundled rules (`gdpr`) to the project's checks (`team-gdpr`). `tests/test_references.py` loads this example from a temporary project catalog.

## Add references

Contribute a JSON family file in `src/openguildkit/registry/references/`. For internal references, add a file to `.openguildkit/catalog/references/` in your project and manage its version control according to your team's policy.

```json
{
  "id": "team-practices",
  "title": "Team practices",
  "references": [
    {
      "id": "team-change-record",
      "title": "Change record",
      "category": "Delivery",
      "kind": "pratique",
      "brains": ["devops", "operations"],
      "summary": "Record the owner, impact and verification results of a production change.",
      "applies_when": "A change affects an interface or operation used by another team.",
      "sources": [
        {"title": "Team engineering handbook", "url": "https://example.org/engineering/change-records", "checked": "2026-11-21"}
      ]
    }
  ]
}
```

### Reference fields

| Field | Constraint |
| --- | --- |
| `id` | Lowercase letters, digits and single hyphens, without a source prefix (`infrastructure-as-code`, not `pd_iac`). Unique across IDs and aliases of all families. |
| `aliases` | Optional. Former IDs that `references --id` still resolves and search still finds. Use it when you rename an entry. |
| `title`, `category`, `summary`, `applies_when` | Single lines. French for the bundled entries. |
| `title_en` | Optional. The English title, when `title` is in another language or gives only an acronym (`Web Content Accessibility Guidelines (WCAG) 2.2` for `WCAG 2.2`). The CLI and the brain briefs show it, and search reads both titles. Every bundled entry has an English title, in one field or the other. |
| `kind` | One of the types below. |
| `edition` | Optional. The edition or version the entry describes when the source has several, such as `2022`, `Rev. 5` or `5.0.0`. Set it for standards and specifications. |
| `brains` | Optional for project entries, set on every bundled entry. One to three [brain](brains.md) IDs whose work the reference supports, such as `["legal", "security"]`. The tests check that each ID is a bundled board. |
| `pattern` | Optional. The pattern this reference presents. The index then shows the reference instead of a generated `pattern-<id>` entry, and the pattern lists the reference in its `references`. A pattern can be presented by one reference. |
| `packs` | Optional. The rule packs built on this reference. |
| `sources` | At least one source, with the same rules as catalog sources. |

`kind` uses a closed list:

| Kind | Use for |
| --- | --- |
| `norme` | A standard from a standards body: ISO, IEC, ETSI, NIST FIPS, Ecma, HL7, NEMA |
| `spécification` | A technical specification from a consortium, a community or the IETF: W3C, WHATWG, OMG, OASIS, an RFC, OpenAPI |
| `protocole` | An exchange, messaging or authentication protocol |
| `format` | A data, file or encoding format |
| `réglementation` | A law or regulation |
| `référentiel` | A set of requirements, controls or criteria, a design system or reference data |
| `méthode` | A structured method with steps or artifacts |
| `pratique` | An engineering, operations or organization practice |
| `principe` | A design principle or heuristic |
| `concept` | A theoretical notion or property |
| `convention` | A naming, style or collaboration convention |
| `guide` | A writing, design or usage guide |
| `outil` | Software or a service |
| `indicateur` | A metric or numeric objective |
| `taxonomie` | A classification of risks, weaknesses or attacks |

Generated `work-patterns` entries use `Stack pattern` or `Work method`.

A reference, the packs built on it and the pattern that applies them name each other: the reference lists `pattern` and `packs`, and the pattern lists the reference in `references`. `tests/test_references.py` checks these links for the bundled catalog. Place each entry in the family of its discipline: Core Web Vitals sits under quality, SPF, DKIM and DMARC under security.

Save this example as `team-practices.json` and replace the example URL with the source your team uses. Sources follow the [catalog rules](catalog-format.md#rules-common-to-all-records): HTTPS, the canonical page, no tracking parameter, and `checked`, the day you opened the page and checked the entry against it ([source dates](catalog-format.md#source-dates)). To extend a bundled family locally, use its existing family ID and title in your file, and include only the new entries. Reference IDs must be unique across all families. Run `openguildkit references` to validate the result.

For pack fields and verification examples, see the [catalog format](catalog-format.md).

## Edition watch

Every Monday the `Watch reference editions` workflow opens the source pages of each bundled reference that declares an `edition`, and opens an issue titled `Edition may have changed: ID` when the edition is no longer on its page. [Source dates](catalog-format.md#source-dates) says what this text comparison can miss or raise by mistake.

The watch starts from `scripts/edition-watch.json`, which the repository keeps seeded from the catalog. An edition the watch has not yet found on its page counts as seen on the latest `checked` date of the reference's sources, the day a person read it there (`"seen_in": "catalog"`, status `from-catalog`). So the first weekly run already reports an edition that is gone, and the workflow changes no file: it keeps its updated copy of the watch file as an artifact.

Who commits the watch file, and when:

- **A contributor who adds a reference with an edition, or changes a reference's `edition` or sources,** runs `python3 -I scripts/watch_editions.py --seed` and commits the file in the same pull request. The seed opens no page: it keeps what the watch observed for the same edition on the same page and starts every other reference from the catalog. `tests/test_edition_watch.py` fails while a reference is missing from the file, cites another edition, or waits for a first observation.
- **The maintainer who closes an `Edition may have changed` issue** updates the reference (its `edition`, or a source page that shows it, with that source's `checked` date), then runs the same command and commits the file with that change.
- **Committing the weekly artifact is optional.** It replaces catalog dates with the days the watch found each edition on its page, which makes a later alarm say "last seen there on" a more recent day. A maintainer who wants that downloads the artifact of the latest run and commits it as is.
