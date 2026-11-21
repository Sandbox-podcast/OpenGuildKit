# Roadmap

This page separates what exists from what is planned. Open an issue to discuss or claim an item.

## Available

**Project setup**

- Questionnaire with detected components and versions, stack patterns by component, preview of the rules with their origin and scope, resolution of conflicting packs.
- Managed `AGENTS.md` block, catalog lock and explicit `openguildkit update`, host settings and hooks for Claude Code and Codex, board guard in the agent and in CI.
- Installable wheel with the agent skill and subagent, Linux and Windows checked in CI.

**Brains and consultation**

- Twenty-seven brains, one per discipline of a software publisher, each with specialists and what each verifies, evidence requests, challenges, decision criteria and a knowledge base of methods, packs and references.
- Adaptive questionnaire, routing tested on a corpus of French and English briefs, preview and adjustment of the brains, required reviews and delegation.
- One pass per brain (subagents or sequential), structured evidence, deliberation between brains, blockers cleared or waived, sealed and optionally signed approvals.
- Market dossiers and competitor watch, dependency alerts, ChaosFolk replays.

**After the decision**

- Results and checks before a task is done, task list and follow-up links, decision export for pull requests.
- Documentation export for Documentalist and a share register, business deliverables (campaign brief, landing page, product one-pager, case study, newsletter, social media plan, press release, webinar, pricing page, competitive battle card, release announcement, support article) and tagged campaign links, Storybook composition and extraction.

**Catalog**

- Rule packs, patterns, references with editions and links to the rules that apply them, regulation packs (GDPR, DORA, NIS2, AI Act, Cyber Resilience Act), a weekly link check.
- Sectors that preselect their regulation patterns for the person to confirm or decline: financial services, insurance, healthcare, public sector, e-commerce, education and critical infrastructure, with EU packs.

## Next

- Validate the whole flow in Codex with the [host validation scenario](../examples/host-validation/) and publish the report ([#23](https://github.com/Sandbox-podcast/OpenGuildKit/issues/23)).
- More sectors (automotive, aerospace, B2B SaaS), national packs on top of the EU ones, and more stacks (Kotlin, Rust, PHP, Ruby).
- An MCP server exposing the CLI to MCP-capable agents.

## How items move up

An item moves to "Next" when someone volunteers to own it and a steward of the domain agrees with the scope (see [GOVERNANCE.md](../GOVERNANCE.md)). Schema changes go through an RFC issue first. Open issues track the work in progress.
