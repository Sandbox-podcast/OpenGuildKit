# Reference library

The library starts from the French SOCLE catalog dated 20 November 2026 (`Socle_Catalogue_References.json`). Each entry keeps its family, category, type, description, applicability notes and public source links. Entries whose source ID did not follow the ID convention were renamed and keep that ID as an alias. The descriptions are in French. The library includes conventions, technical specifications, practices, tools and regulations. Families added since then cover the non-technical disciplines: `people` (human resources), `finance`, `legal`, `support`, `communication`, `delivery` (project management and operations) and `strategy` (leadership and governance). [Browse the family files](../src/openguildkit/registry/references/).

## Find a reference

```text
openguildkit references
openguildkit references --family code
openguildkit references "ISO 27001"
openguildkit references --id conventional-commits
openguildkit references --family cloud "observabilite" --json
```

Without options, the command lists the families and their counts. Search matches whole words across names, categories and descriptions, ignoring accents and case. Results with terms in the title or ID appear first. Use `--id` for the full entry and its source links; a former ID such as `pd_iac` or `agent_agent_memory` finds the renamed entry. With `--json`, the command returns an array of matching records. The CLI reads the index locally.

The `work-patterns` family comes from the [pattern catalog](patterns.md). A pattern appears once in the index. When a reference presents it, such as `scrum` for the Scrum pattern, the index shows that reference, which also answers to `pattern-scrum` and ends with the pattern and packs to apply. Other patterns get a generated entry such as `pattern-search-engine-optimization`; edit the pattern record to change it.

## Apply a reference to a project

`openguildkit references` shows material to investigate. `openguildkit catalog` lists the rule packs that can be applied to project instructions. During setup, select the packs that fit your stack and delivery process. For an existing project, edit the `packs` array in `.openguildkit/project.json`, then run `openguildkit sync` and `openguildkit check`.

| Optional pack | References used | Evidence to keep |
| --- | --- | --- |
| `release-management` | Conventional Commits, SemVer, Keep a Changelog | Version decision, compatibility checks, release notes |
| `supply-chain` | SLSA, SBOM, SPDX, CycloneDX | Artifact provenance, verification result, SBOM for the shipped version |
| `service-reliability` | SLI, SLO, error budgets, OpenTelemetry, OTLP | SLO definition, dashboard or query, telemetry test |
| `gdpr` | GDPR (Regulation (EU) 2016/679), CNIL guidance, standard contractual clauses | Processing record entry, lawful basis, retention job, DPIA decision |
| `dora` | DORA (Regulation (EU) 2022/2554) | ICT asset inventory, restoration test, register of information, incident runbook |
| `nis2` | NIS 2 (Directive (EU) 2022/2555) and its national transposition | Scope decision, security policy, supplier assessment, incident runbook |
| `eu-ai-act` | AI Act (Regulation (EU) 2024/1689, as amended) | Classification and role, employment use (Annex III, point 4), AI interaction notice, logs, oversight procedure |
| `cyber-resilience-act` | Cyber Resilience Act (Regulation (EU) 2024/2847) | Role decision, release SBOM, disclosure policy, support period, reporting runbook |

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
    {"title": "Regulation (EU) 2016/679, General Data Protection Regulation", "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra"}
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

Then it adds `"team-gdpr"` to `packs` in `.openguildkit/project.json` and runs `openguildkit sync` and `openguildkit check`. `AGENTS.md` lists `gdpr` before `team-gdpr`, so the agent reads the regulation's rules first and the team's scope, owner and evidence next. The link runs from the reference (`rgpd`) to the bundled rules (`gdpr`) to the project's checks (`team-gdpr`). `tests/test_references.py` loads this example from a temporary project catalog.

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
        {"title": "Team engineering handbook", "url": "https://example.org/engineering/change-records"}
      ]
    }
  ]
}
```

### Reference fields

| Field | Constraint |
| --- | --- |
| `id` | Lowercase letters, digits and single hyphens, without a source prefix (`infrastructure-as-code`, not `pd_iac`). Unique across IDs and aliases of all families. |
| `aliases` | Optional. Former IDs that `references --id` still resolves. Use it when you rename an entry. |
| `title`, `category`, `summary`, `applies_when` | Single lines. French for the bundled entries. |
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

Save this example as `team-practices.json` and replace the example URL with the source your team uses. Sources follow the [catalog rules](catalog-format.md#rules-common-to-all-records): HTTPS, the canonical page, no tracking parameter. To extend a bundled family locally, use its existing family ID and title in your file, and include only the new entries. Reference IDs must be unique across all families. Run `openguildkit references` to validate the result.

For pack fields and verification examples, see the [catalog format](catalog-format.md).
