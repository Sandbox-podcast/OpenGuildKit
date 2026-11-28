# Roadmap

For: anyone who decides whether to adopt OpenGuildKit or to contribute to it.

This page separates what exists from what is planned. Open an issue to discuss or claim an item.

## Available

**Project setup**

- Questionnaire with detected components and versions, stack patterns by component, preview of the rules with their origin and scope, resolution of conflicting packs.
- Managed `AGENTS.md` block, catalog lock and explicit `openguildkit update`, host settings and hooks for Claude Code and Codex, board guard in the agent and in CI.
- Installable wheel with the agent skill, the board, market analyst and dependency watch subagents, and the web interface; the tests, the wheel and the web interface are checked in CI on Linux, macOS and Windows.

**Brains and consultation**

- Twenty-seven brains, one per discipline of a software publisher, each with specialists and what each verifies, evidence requests, challenges, decision criteria and a knowledge base of methods, packs and references.
- Adaptive questionnaire, routing tested on a corpus of French and English briefs, preview and adjustment of the brains, required reviews and delegation.
- One pass per brain (subagents or sequential), structured evidence, deliberation between brains, blockers cleared or waived, sealed and optionally signed approvals.
- Market dossiers and competitor watch, dependency alerts, ChaosFolk replays.

**Tooling**

- A tool registry of the company's tools and the MCP servers verified on each publisher's documentation, the tooling section of the setup, connection plans for Claude Code and Codex, and mocks: stand-in MCP servers with synthetic data, to rehearse a task without an account (`openguildkit tools`, [tools](tools.md)).

- Features: twenty purposes a team covers with a tool, each with a lead tool and three alternatives, turned on or off with who and why (`openguildkit features`, [features](tools.md#features)).

- A [local project MCP server](tools.md#read-an-openguildkit-project-through-mcp) for active rule references, recorded task status and check outcomes.

**Web interface**

- `openguildkit ui`: a local web interface on 127.0.0.1 over the same commands, which leaves every decision of a person to their terminal ([interface d'un projet réel](../web/docs/interface-projet.md)).
- The Arsenal (Fonctionnalités in the Pro style) shows the features as cards and asks who decides and why before it turns an option on or off.

**After the decision**

- Results and checks before a task is done, task list and follow-up links, decision export for pull requests.
- Documentation export for Documentalist and a share register, business deliverables (campaign brief, landing page, product one-pager, case study, newsletter, social media plan, press release, webinar, pricing page, competitive battle card, release announcement, support article) and tagged campaign links, Storybook composition and extraction.

**Testing the product with teams**

- A field kit that prepares thirty simulated testers, plays the scripted part of three scenarios with several teams and collects their reports ([field tests](../examples/field-tests/README.md)); a host validation scenario replayed in CI and in Claude Code and Codex sessions ([host validation](../examples/host-validation/README.md)).

**Catalog**

- Rule packs, patterns, references with editions and links to the rules that apply them, regulation packs (GDPR, DORA, NIS2, AI Act, Cyber Resilience Act), a weekly link check, a verification date on every source and a weekly edition watch.
- Sectors that preselect their regulation patterns for the person to confirm or decline: financial services, insurance, healthcare, public sector, e-commerce, education, critical infrastructure, aerospace, automotive and software publishers, with EU packs. Aerospace carries EASA Part-IS and the process controls around DO-178C and DO-326A, automotive UN Regulations No 155 and No 156.
- A first national layer for France on top of the EU packs: health data hosting, RGAA accessibility, public sector security, cookies and trackers, and e-invoicing.
- Stack patterns with a detection of the manifest, among them Rust (`Cargo.toml`), Kotlin servers on Ktor, Symfony, Svelte and SvelteKit, React Native and Expo, Flutter (`pubspec.yaml`), dbt, Apache Airflow, and Elixir with Phoenix (`mix.exs`), next to the web, mobile and cloud stacks.

## Next

- Finish the Codex validation of [#23](https://github.com/Sandbox-podcast/OpenGuildKit/issues/23): the Codex report of 21 November 2026 shows evidence, a decision and results up to `done`, but no disagreement between boards, and the hooks and rules that `host apply` writes for Codex were never seen in a live session. What is left is in the [host validation scenario](../examples/host-validation/README.md#what-the-reports-show-for-issue-23).
- National packs for other countries than France, more sectors, and more stacks. #268 asks to rank them from the pilot.

## How items move up

An item moves to "Next" when someone volunteers to own it and a steward of the domain agrees with the scope (see [GOVERNANCE.md](../GOVERNANCE.md)). Schema changes go through an RFC issue first. Open issues track the work in progress.
