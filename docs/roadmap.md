# Roadmap

This page separates what exists from what is planned. Items under "Next" and "Later" are not built. Open an issue to discuss or claim one.

## Available

- Catalog of rule packs, specialist boards and sector profiles in validated JSON.
- Searchable [reference library](references.md) from the SOCLE catalog. Opt-in packs for releases, the software supply chain and service reliability.
- Regulatory packs for GDPR, DORA, NIS 2, the AI Act and the Cyber Resilience Act, offered to the legal and security roles, and a financial services sector. Each pack asks the owner and gathers evidence; none claims compliance.
- [Work and stack patterns](patterns.md) link project context to rule packs and surface methods by role.
- Pull requests carry path-based labels. A required CI check protects `main`, and the release workflow refreshes a changelog draft after merges.
- CLI: `init` questionnaire, managed `AGENTS.md` block, `sync`, `check`, project-level catalog additions.
- Task flow: scoping QCM, deterministic board routing, consultation request, review validation, human approval at a terminal, handoff bound to the rules in force.
- Skills for Claude Code and Codex that drive the flow.
- Optional [ChaosFolk end-to-end replays](../integrations/chaosfolk/): the `chaosfolk-e2e` pack and CI guide, pinned to ChaosFolk commit `b406600`. Storing replay results in the task record waits for post-handoff checks (#16).
- Tests, cross-platform CI and a reproducible support request example.
- Weekly check of the catalog's source links, with a dated report that lists the records citing each link.

## Next: breadth of the catalog

The catalog is where most contributions will go. Priorities, by domain:

- **Security and compliance context:** OWASP ASVS levels, OWASP Top 10 for LLM applications, SOC 2, PCI DSS. Each pack asks the owner and gathers evidence; none claims compliance.
- **Engineering conventions:** twelve-factor apps, Go, Java, Kotlin, C#, Swift, Terraform, Kubernetes, containers.
- **Agentic work:** prompt-injection handling, tool and permission scoping, MCP server hygiene, evaluation before release, AI cost budgets.
- **Sectors:** healthcare, retail, public sector, industry, education. Financial services is available.
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
- **Catalog upkeep:** detect new versions of the standards that packs refer to; broken and redirected links are already reported weekly.
- **Beyond software teams:** profiles and boards for marketing, sales and finance teams running their own projects with agents.

## How items move up

A roadmap item moves to "Next" when someone volunteers to own it and a steward of the domain agrees with the scope (see [GOVERNANCE.md](../GOVERNANCE.md)). Schema changes go through an RFC issue first.
