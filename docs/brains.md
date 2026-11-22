# Professional brains

Each brain is a board with several specialist lenses. Product brings discovery, prioritization, adoption and measurement. Security brings application security, privacy, release integrity and control ownership. The same task can receive a different verdict from each board.

```text
openguildkit brains
openguildkit brains --id product
openguildkit brains --id security --json
```

The catalog has one brain per discipline of a software publisher:

| Brain | ID | Brings |
|---|---|---|
| Software development | `engineering` | Architecture, contracts between tiers, data consistency, maintainability; the default reviewer of features, bugs and maintenance |
| Front-end development | `frontend` | Rendering and state, semantic markup, front-end performance, browser support |
| Back-end development | `backend` | API contracts, data integrity, schema migrations, server-side authorization |
| Security and privacy | `security` | Application security, privacy engineering, release integrity, control ownership |
| DevOps and reliability | `devops` | Delivery pipeline, progressive delivery, observability, recovery |
| Quality assurance | `qa` | Test design, regressions, exploratory testing, release acceptance |
| Performance | `performance` | Client responsiveness, service latency, capacity, benchmarks |
| Product management | `product` | Discovery, analytics, scope, rollout and adoption |
| Product design | `design` | Interaction, design systems, accessibility, usability research |
| Data and AI | `data` | Data ownership and quality, analytics instrumentation, model evaluation, AI risk |
| Marketing and market research | `marketing` | Market research, positioning, channels, measurement |
| Communication | `communication` | Release and customer communication, crisis communication, plain language, internal communication |
| Sales | `sales` | Discovery, qualification, enablement, buyer procurement, deal desk, renewals and expansion |
| Partnerships and channels | `partnerships` | Partner programme, channel economics, partner agreements, partner enablement |
| Customer support and success | `support` | Support readiness, escalation, knowledge base, customer success |
| Customer success | `customer-success` | Account health, renewals, customer onboarding, voice of the customer |
| Finance and FinOps | `finance` | Planning, FinOps, unit economics, budget ownership, revenue recognition, pricing and margin, VAT and invoicing |
| Procurement and vendor management | `procurement` | Sourcing, third-party risk, contract terms, exit and continuity |
| Legal and compliance | `legal` | Data protection, contracts, licences, sector regulations |
| Human resources | `hr` | Hiring, employee experience, workforce planning, people data, compensation and pay equity, employment law, performance and development |
| Internal IT and workplace | `it-and-workplace` | Devices, identity and SaaS access, licences, workplace support |
| Localisation and internationalisation | `localisation` | Internationalisation of code, translation workflow, terminology, locale testing |
| Developer relations and documentation | `developer-relations-and-docs` | API reference, documentation architecture, SDKs and samples, developer community |
| Trust and safety | `trust-and-safety` | Abuse risk, moderation operations, policy and appeals, transparency reporting |
| Project management | `project-management` | Delivery planning, capacity, governance, risk and change |
| Business operations | `operations` | Process flow, queues, service quality, process change |
| Executive leadership | `leadership` | Strategy, portfolio, risk governance, benefits |

Each brain has at least four specialists, four evidence requests, four challenge questions, four decision criteria and three primary sources.

`engineering` stays the brain that reviews features, bugs and maintenance across the code base, and every profile that names it keeps working. `frontend` and `backend` add the depth of each side: a brief that names browser support, a component library or the bundle size reaches `frontend`, one that names a migration, a webhook or idempotency reaches `backend`, and `frontend` or `backend` in a brief reaches both them and `engineering`. When the project declares the role, the stack reaches them too: `frontend` for a customer-facing task on React, Vue, Angular or Svelte, `backend` for a service task on Django, Rails, Spring Boot or FastAPI, and the board of a component's stack when the task names that component ([workflow](workflow.md#how-boards-are-selected)). A profile that lists its boards gets them only once it adds them to `boards`.

### What each brain knows

A brain is more than its review grid. Each specialist lens carries `checks`: what an expert of that lens verifies and the mistakes they catch, such as "Multi-year and bundled contracts list each performance obligation and its standalone selling price" for the revenue accountant. `brains --id` prints them under each specialist, and the consultation brief gives them to the agent that plays the brain. Every lens of the 27 bundled brains has them.

The rest of its knowledge comes from the catalog:

- **methods**: the patterns whose `roles` name the brain, such as MEDDPICC for sales or the double diamond for design;
- **rule packs**: the packs those methods apply, marked active when the project uses them;
- **references and standards**: the entries of the reference library tagged with the brain in `brains`, with their edition and source.

```text
openguildkit brains --id legal
openguildkit brains --id finance --json
openguildkit brains --check
```

`brains --id` prints the specialists, review criteria and this knowledge, with every reference of the brain. Each consultation gives every selected brain its knowledge: the project's active packs first, then the other packs of its methods, and the twelve references that best fit the task. The references that the project's active packs apply come first; then those whose ID, title, category or summary share the most words with the brief, the answers, the sector and the stack, a word of the title counting double; then the references that packs turn into rules; then alphabetical order. A few English words reach the French summaries and the acronyms of the library, so "SSO with Okta" reaches SAML 2.0, OpenID Connect, OAuth 2.0 and OWASP ASVS. The same task always gets the same list. `brains --check`, run in CI, fails when a brain has no method or no tagged reference. To extend a brain, tag a pattern with its role or a reference with its ID; the catalog refuses an unknown brain.

### Where lenses meet

Some questions concern two brains. Each brain keeps its own angle:

| Topic | Brains | Who answers what |
|---|---|---|
| Rolling out a change | product, devops | Product decides who gets it and how adoption is judged; DevOps decides how it is deployed, paused and reversed |
| Build and release integrity | security, devops | Security decides which provenance and permissions are required; DevOps runs the pipeline that produces them |
| Capacity | performance, devops, hr, project-management, operations | Performance measures system capacity, DevOps runs it; HR plans people, project management schedules them, operations balances work queues |
| Supported consumers and versions | qa, engineering | Engineering decides compatibility and migrations; QA tests the supported combinations |
| Accessibility | design, qa | Design specifies accessible interactions; QA verifies them with keyboard and assistive technology |
| Users' needs | product, design | Product decides which problem is worth solving; design researches how people do the task |
| Measurement | marketing, product, data | Marketing measures acquisition, product measures use and outcomes, data owns definitions and quality |
| Budgets and portfolio | finance, leadership | Finance models costs; leadership decides which work gets the resources |
| Personal data | security, legal | Security protects it; legal confirms the obligations and records attached to it |
| Customer messages | communication, support, marketing | Communication owns what is said and when, support answers the questions it raises, marketing owns promotion |
| Discounts and contract terms | sales, finance, legal | The deal desk applies the approval matrix; finance confirms revenue and margin; legal approves non-standard clauses |
| Buying from a vendor | procurement, security, legal | Procurement compares options and plans the exit; security checks the vendor's controls; legal signs the data processing terms |
| Existing customers | customer-success, support, sales | Customer success follows account health and renewals; support answers tickets; sales owns the renewal and expansion deal |
| Arrivals and departures | hr, it-and-workplace, security | HR owns the person's process; internal IT grants and removes devices and accounts; security defines the access rules |
| User content | trust-and-safety, legal, support | Trust and safety designs reporting, moderation and appeals; legal confirms the obligations; support answers the people affected |

## Complete or add a brain in a project

A company completes a bundled brain without forking it. Write `.openguildkit/catalog/boards/legal.json` with the same `id` and only what to add:

```json
{
  "id": "legal",
  "review": {
    "specialists": [
      {"id": "export-control", "title": "Export control adviser", "focus": "Screen the destination countries against sanctions lists.", "checks": ["The screening log covers every new country."]}
    ],
    "decision_criteria": ["Block a sale to a sanctioned country."]
  }
}
```

Lists gain the new items, a specialist with a bundled `id` replaces it, and `title` or `description` replace the bundled text. A copy of the whole bundled file works too. The catalog lock does not pin a brain the project completes: the project owns it, and a newer OpenGuildKit release reaches it at once.

To add a brain of its own, run `openguildkit brains --new risk-office`. It writes the board with its full review block, a method pattern, a rule pack and a reference family under `.openguildkit/catalog/`, with `TODO:` text to replace; `brains --check` reports the brain until none is left. A project board without a `review` block is refused, so that every brain has lenses.

Adding or completing a brain changes the record that approvals are bound to. When the profile uses every board (`"boards": []`), the new brain becomes one of them: `brains --new` names each task consulted or approved without it, and `openguildkit sync` lists them again. Those tasks need a new review before work continues: consult each again with `task consult ID`. A profile that lists its boards is not affected until the team adds the brain to `boards`.

## Run the review

1. `task consult ID` routes the task and lists the selected brains. `task pass ID BOARD` prints one brain's brief: its questions, the lenses to fill, its evidence requests, challenge and decision criteria, the rules of its packs that concern the task and a bounded reading list. When using a host agent, assign one independent pass per board.
2. Record one finding per specialist before forming the board's verdict. Distinguish a documented fact, an assumption, and a gap. For an observed finding, cite positions in the entry's own evidence list, counted from 1. A lens that names the surfaces it applies to (`applies_to`) and none of the task's is listed as not concerned and left out of the entry.
3. Compare the proposal with an alternative, name a failure it could cause and specify a test or observation that would change the decision. Identify blocking findings and who can resolve them.
4. Record the reviews with `task review ID --file FILE`. `task challenge ID` groups the verdicts and shows alternatives, verification steps and unresolved items. The owner makes the decision in their terminal.

## Answer the other boards' objections

When boards disagree, each board answers the others on the same point before the person decides. An objection goes from a board to the boards whose position it contradicts, on a named point: the board's blockers, or else its failure mode. A board whose verdict is `revise`, `block` or `insufficient-evidence` can object to a board whose verdict is `proceed`, and a board that answers `block` also to a board that answers `revise`. The objection reaches that board only when their domains meet: the point uses words of the other board's domain (its title and the triggers that route tasks to it), or the other board's recommendation uses words of the objector's domain. Every routed board's words compete for a text, so that "contract test" belongs to QA and does not reach Legal through "contract", and the domains meet on two words, on a phrase of several words, or on a word only one board's domain holds. A generic failure mode is no objection to everyone; a point that meets no board stands as its board's advice, and the decision brief says which boards it concerns. Boards that give the same verdict do not object to each other. When two verdicts differ and no objection links them (`revise` and `insufficient-evidence`, `block` and `insufficient-evidence`), the decision brief says so and why.

```bash
openguildkit task deliberate ID      # objections, the rules of an answer, one filled example and the template
openguildkit task respond ID --file deliberation.json
openguildkit task challenge ID       # each objection once, resolved or open, and the decision needed
```

The template has one response per board and side: a board answers all the objections it raised in one response, and all those it received in another. A board that raised and received objections has two responses: merge them when it takes the same position on all. Split a response when the board takes different positions on different objections; `objections` lists the IDs a response answers. Each response gives:

- `position`: `maintain` (the board keeps its position), `amend` (it changes its position to meet the other's point, and says how) or `concede` (it accepts the other's point);
- `response`: the answer, in text;
- `evidence_refs`: positions in the board's own evidence list from its review entry, counted from 1. Maintaining or amending needs at least one; conceding needs none.

An objection is resolved when one of the two boards concedes, or when both amend. A concession closes it alone: the other board need not answer it. Otherwise it stays open, and `decision_needed` must say which decision the responsible person takes. For example:

```json
{"objections": ["security-to-product"], "board": "product", "position": "amend", "response": "The export goes through the same ownership check as the page; we add the cross-account test.", "evidence_refs": [1]}
```

The first reviews stay as recorded. The decision brief warns that approving goes against the boards' advice only for the boards whose objections were not all resolved; for a decision task, it says that the decision record carries their reservations.

## What the verdict means

| Verdict | Meaning |
| --- | --- |
| `proceed` | The available evidence supports proceeding within the reviewed scope. |
| `revise` | A change to the approach or scope could address the findings. |
| `block` | The board identifies a condition that needs an accountable decision or resolution. |
| `insufficient-evidence` | The board needs specific evidence before it can judge the proposal. |

Each item of a board's `evidence` list records where it comes from and what it establishes:

```json
{"source": "project-file", "ref": "src/permissions.py", "supports": "Requests are filtered by owner on the server.", "revision": "3fffa1c"}
```

`source` is one of `requester`, `project-file`, `test`, `measurement`, `public`, `interview`, `ticket`, `decision-record` or `other`. `ref` is a project path, a document title or an https link. Public sources, measurements and interviews carry the `date` they were observed, a real `YYYY-MM-DD` day that is not in the future; a `revision` pins a file to a commit. A `project-file` or `test` item names a file or folder that exists in the project, optionally followed by `:LINE`, `#anchor` or `::test`, when `task review` or `task submit` records it. The template's `evidence_item` shows this shape. The requester's own words (`requester`) cannot be the only support for `proceed` or for high confidence. The decision brief lists, for each board, the evidence its observed findings cite. Reviews recorded before this format keep their text items.

`task template ID` returns the exact shape for the selected boards. In a brain entry, `challenge.specialists` uses the specialist IDs from the prompt. `evidence_refs` contains positions in this entry's own `evidence` list, counted from 1 (not paths, not counted from 0). For example, `[1, 3]` cites the first and third items; `task submit` names a wrong reference and the valid range. Use `low`, `medium`, or `high` confidence. Proceeding or claiming high confidence requires observed evidence, a block needs at least one blocker, and an insufficient-evidence verdict uses low confidence.

The CLI validates the review record. The host agent or reviewer gathers and interprets the evidence. See the [request status example](../examples/request-status/) for a recorded review with multiple verdicts.

## Contribute a brain

Each board has a JSON file in `src/openguildkit/registry/boards/`. In `review`, add:

- `specialists`, each with a stable `id`, a `title`, a specific `focus` and `checks`, two to four things an expert of that lens verifies.
- `evidence`, the sources or observations that would support the recommendation.
- `challenge`, questions about alternatives, failure modes and assumptions.
- `decision_criteria`, conditions that change the board's verdict.

Scope triggers to a role's actual work. A trigger written after a negation ("no payments") does not select the brain; see [routing](workflow.md#2-scope-the-task). Link to public primary sources and use concrete checks. [Board schema](catalog-format.md#boards)
