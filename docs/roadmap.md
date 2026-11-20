# Roadmap

This page separates what exists from what is planned. Items under "Next" and "Later" are not built. Open an issue to discuss or claim one.

## Available

- Catalog of rule packs, specialist boards and sector profiles in validated JSON.
- Searchable [reference library](references.md) from the SOCLE catalog. Opt-in packs for releases, the software supply chain and service reliability.
- CLI: `init` questionnaire, managed `AGENTS.md` block, `sync`, `check`, project-level catalog additions.
- Task flow: scoping QCM, deterministic board routing, consultation request, review validation, human approval at a terminal, handoff bound to the rules in force.
- Skills for Claude Code and Codex that drive the flow.
- Tests, cross-platform CI, a reproducible insurance example.

## Next: breadth of the catalog

The catalog is where most contributions will go. Priorities, by domain:

- **Security and compliance context:** OWASP ASVS levels, OWASP Top 10 for LLM applications, GDPR, DORA, NIS2, SOC 2, PCI DSS. Each pack asks the owner and gathers evidence; none claims compliance.
- **Engineering conventions:** twelve-factor apps, Go, Java, Kotlin, C#, Swift, Terraform, Kubernetes, containers.
- **Agentic work:** prompt-injection handling, tool and permission scoping, MCP server hygiene, evaluation before release, AI cost budgets.
- **Sectors:** banking, healthcare, retail, public sector, industry, education.
- **Boards:** legal, data and AI, customer support, people and HR.

## Next: depth of the review

- Board rounds: boards read each other's recommendations and record agreement or dissent before the person decides.
- Evidence requirements per board (for example, security must cite the permission model it inspected).
- `task list` and a project summary of consulted, approved and pending tasks.

## Later

- **Market intelligence:** agents that follow direct and indirect competitors in public sources (product pages, release notes, social posts, funding announcements) and feed the product and marketing boards. Runs only under the `public-sources` research policy.
- **Generated documentation:** API reference, changelog, roadmap and component catalog (Storybook) produced from the approved handoffs, with access links to share them with customers.
- **Dependency watch:** checks the libraries in use against vulnerability databases and proposes fixes or alternatives through the normal task flow.
- **Distribution:** PyPI package, an MCP server exposing the CLI to any MCP-capable agent, a community registry of signed packs, and `openguildkit update` to pull newer catalog versions.
- **Catalog upkeep:** scheduled checks for broken source links and new versions of the standards packs refer to.
- **Beyond software teams:** profiles and boards for marketing, sales and finance teams running their own projects with agents.

## How items move up

A roadmap item moves to "Next" when someone volunteers to own it and a steward of the domain agrees with the scope (see [GOVERNANCE.md](../GOVERNANCE.md)). Schema changes go through an RFC issue first.
