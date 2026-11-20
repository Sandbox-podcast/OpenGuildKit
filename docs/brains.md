# Professional brains

Each brain is a board with several specialist lenses. Product brings discovery, prioritization, adoption and measurement. Security brings application security, privacy, release integrity and control ownership. The same task can receive a different verdict from each board.

```text
openguildkit brains
openguildkit brains --id product
openguildkit brains --id security --json
```

The catalog covers engineering, security, DevOps, QA, performance, product, design, marketing, sales, finance, project management, HR, executive leadership and operations.

## Run the review

1. `task consult ID` routes the task and includes each selected brain's specialties, evidence requests, questions and decision criteria. Give each board the scoped brief and the relevant project rules. When using a host agent, assign one independent review per board.
2. Record one finding per specialist before forming the board's verdict. Distinguish a documented fact, an assumption, and a gap. For an observed finding, cite positions in the board's evidence list.
3. Compare the proposal with an alternative, name a failure it could cause and specify a test or observation that would change the decision. Identify blocking findings and who can resolve them.
4. Record the reviews with `task review ID --file FILE`. `task challenge ID` groups the verdicts and shows alternatives, verification steps and unresolved items. The owner makes the decision in their terminal.

## What the verdict means

| Verdict | Meaning |
| --- | --- |
| `proceed` | The available evidence supports proceeding within the reviewed scope. |
| `revise` | A change to the approach or scope could address the findings. |
| `block` | The board identifies a condition that needs an accountable decision or resolution. |
| `insufficient-evidence` | The board needs specific evidence before it can judge the proposal. |

`task template ID` returns the exact shape for the selected boards. In a brain entry, `challenge.specialists` uses the specialist IDs from the prompt. `evidence_refs` contains one-based positions in the board evidence array. For example, `[1, 3]` cites the first and third items. Use `low`, `medium`, or `high` confidence. Proceeding or claiming high confidence requires observed evidence, a block needs at least one blocker, and an insufficient-evidence verdict uses low confidence.

The CLI validates the review record. The host agent or reviewer gathers and interprets the evidence. See the [insurance example](../examples/insurance-claims/) for a recorded review with multiple verdicts.

## Contribute a brain

Each board has a JSON file in `src/openguildkit/registry/boards/`. In `review`, add:

- `specialists`, each with a stable `id`, a `title` and a specific `focus`.
- `evidence`, the sources or observations that would support the recommendation.
- `challenge`, questions about alternatives, failure modes and assumptions.
- `decision_criteria`, conditions that change the board's verdict.

Scope triggers to a role's actual work. Link to public primary sources and use concrete checks. [Board schema](catalog-format.md#boards)
