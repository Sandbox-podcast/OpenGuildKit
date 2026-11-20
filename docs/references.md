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
| `eu-ai-act` | AI Act (Regulation (EU) 2024/1689, as amended) | Classification and role, AI interaction notice, logs, oversight procedure |
| `cyber-resilience-act` | Cyber Resilience Act (Regulation (EU) 2024/2847) | Role decision, release SBOM, disclosure policy, support period, reporting runbook |

When turning a new reference into a pack, confirm its edition, the conditions where it applies and the team that owns it. Write the action to take, how to verify it and what evidence to keep. Use your organization's approved interpretation for regulatory requirements and licensed standards.

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
