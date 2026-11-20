# Reference library

The library starts from the French SOCLE catalog dated 20 November 2026 (`Socle_Catalogue_References.json`). Each entry keeps its source ID, family, category, type, description, applicability notes and public source links. The descriptions are in French. The library includes conventions, technical specifications, practices, tools and regulations. [Browse the family files](../src/openguildkit/registry/references/).

## Find a reference

```text
openguildkit references
openguildkit references --family code
openguildkit references "ISO 27001"
openguildkit references --id conventional-commits
openguildkit references --family cloud "observabilite" --json
```

Without options, the command lists the families and their counts. Search matches whole words across names, categories and descriptions, ignoring accents and case. Results with terms in the title or ID appear first. Use `--id` for the full entry and its source links. With `--json`, the command returns an array of matching records. The CLI reads the index locally.

## Apply a reference to a project

`openguildkit references` shows material to investigate. `openguildkit catalog` lists the rule packs that can be applied to project instructions. During setup, select the packs that fit your stack and delivery process. For an existing project, edit the `packs` array in `.openguildkit/project.json`, then run `openguildkit sync` and `openguildkit check`.

| Optional pack | References used | Evidence to keep |
| --- | --- | --- |
| `release-management` | Conventional Commits, SemVer, Keep a Changelog | Version decision, compatibility checks, release notes |
| `supply-chain` | SLSA, SBOM, SPDX, CycloneDX | Artifact provenance, verification result, SBOM for the shipped version |
| `service-reliability` | SLI, SLO, error budgets, OpenTelemetry, OTLP | SLO definition, dashboard or query, telemetry test |

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
      "kind": "Practice",
      "summary": "Record the owner, impact and verification results of a production change.",
      "applies_when": "A change affects an interface or operation used by another team.",
      "sources": [
        {"title": "Team engineering handbook", "url": "https://example.org/engineering/change-records"}
      ]
    }
  ]
}
```

Save this example as `team-practices.json` and replace the example URL with the source your team uses. To extend a bundled family locally, use its existing family ID and title in your file, and include only the new entries. Reference IDs must be unique across all families. Run `openguildkit references` to validate the result.

For pack fields and verification examples, see the [catalog format](catalog-format.md).
