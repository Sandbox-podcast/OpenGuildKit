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
| Software development (front-end and back-end) | `engineering` | Architecture, contracts, data consistency, maintainability, front-end rendering and browser support |
| Security and privacy | `security` | Application security, privacy engineering, release integrity, control ownership |
| DevOps and reliability | `devops` | Delivery pipeline, progressive delivery, observability, recovery |
| Quality assurance | `qa` | Test design, regressions, exploratory testing, release acceptance |
| Performance | `performance` | Client responsiveness, service latency, capacity, benchmarks |
| Product management | `product` | Discovery, analytics, scope, rollout and adoption |
| Product design | `design` | Interaction, design systems, accessibility, usability research |
| Data and AI | `data` | Data ownership and quality, analytics instrumentation, model evaluation, AI risk |
| Marketing and market research | `marketing` | Market research, positioning, channels, measurement |
| Communication | `communication` | Release and customer communication, crisis communication, plain language, internal communication |
| Sales | `sales` | Discovery, qualification, enablement, procurement |
| Customer support and success | `support` | Support readiness, escalation, knowledge base, customer success |
| Finance and FinOps | `finance` | Planning, FinOps, unit economics, budget ownership |
| Legal and compliance | `legal` | Data protection, contracts, licences, sector regulations |
| Human resources | `hr` | Hiring, employee experience, workforce planning, people data |
| Project management | `project-management` | Delivery planning, capacity, governance, risk and change |
| Business operations | `operations` | Process flow, queues, service quality, process change |
| Executive leadership | `leadership` | Strategy, portfolio, risk governance, benefits |

Each brain has at least four specialists, four evidence requests, four challenge questions, four decision criteria and three primary sources.

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

## Run the review

1. `task consult ID` routes the task and includes each selected brain's specialties, evidence requests, questions and decision criteria. Give each board the scoped brief and the relevant project rules. When using a host agent, assign one independent review per board.
2. Record one finding per specialist before forming the board's verdict. Distinguish a documented fact, an assumption, and a gap. For an observed finding, cite positions in the board's evidence list.
3. Compare the proposal with an alternative, name a failure it could cause and specify a test or observation that would change the decision. Identify blocking findings and who can resolve them.
4. Record the reviews with `task review ID --file FILE`. `task challenge ID` groups the verdicts and shows alternatives, verification steps and unresolved items. The owner makes the decision in their terminal.

## Answer the other boards' objections

When boards disagree, each board answers the others on the same point before the person decides. A board whose verdict is `revise`, `block` or `insufficient-evidence` objects to each board whose verdict is `proceed`.

```bash
openguildkit task deliberate ID      # objections and the response template
openguildkit task respond ID --file deliberation.json
openguildkit task challenge ID       # agreement reached, remaining disagreements, decision needed
```

For each objection, both boards record a `position` (`maintain`, `concede` or `amend`), a `response` and the positions in their own evidence list that support it; maintaining or amending a position needs evidence. An objection one board concedes is resolved. When disagreements remain, `decision_needed` says which decision the responsible person must take. The first reviews stay as recorded, and the decision brief lists objections that were not deliberated.

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

`source` is one of `requester`, `project-file`, `test`, `measurement`, `public`, `interview`, `ticket`, `decision-record` or `other`. `ref` is a project path, a document title or an https link. Public sources, measurements and interviews carry the `date` they were observed; a `revision` pins a file to a commit. The requester's own words (`requester`) cannot be the only support for `proceed` or for high confidence. The decision brief lists, for each board, the evidence its observed findings cite. Reviews recorded before this format keep their text items.

`task template ID` returns the exact shape for the selected boards. In a brain entry, `challenge.specialists` uses the specialist IDs from the prompt. `evidence_refs` contains one-based positions in the board evidence array. For example, `[1, 3]` cites the first and third items. Use `low`, `medium`, or `high` confidence. Proceeding or claiming high confidence requires observed evidence, a block needs at least one blocker, and an insufficient-evidence verdict uses low confidence.

The CLI validates the review record. The host agent or reviewer gathers and interprets the evidence. See the [request status example](../examples/request-status/) for a recorded review with multiple verdicts.

## Contribute a brain

Each board has a JSON file in `src/openguildkit/registry/boards/`. In `review`, add:

- `specialists`, each with a stable `id`, a `title` and a specific `focus`.
- `evidence`, the sources or observations that would support the recommendation.
- `challenge`, questions about alternatives, failure modes and assumptions.
- `decision_criteria`, conditions that change the board's verdict.

Scope triggers to a role's actual work. Link to public primary sources and use concrete checks. [Board schema](catalog-format.md#boards)
