# Business deliverables

An approved task often leads to work outside the code: a campaign brief, a release announcement, a support article. A deliverable template gives that work a method, the inputs it needs, the tool actions that need the requester's approval and the checks a reviewer runs.

```bash
openguildkit deliverable list
openguildkit deliverable show campaign-brief
openguildkit deliverable new campaign-brief --task launch --tool Brevo --output marketing/spring-brief.md
openguildkit deliverable check marketing/spring-brief.md
```

| Template | Method | Brains that review it |
|---|---|---|
| `campaign-brief` | `marketing-campaign-planning` | marketing, communication, legal |
| `release-announcement` | | communication, support, product |
| `support-article` | | support, communication |

`deliverable show` and `deliverable new` list, before anyone opens the tool, the data each input needs (`none`, `internal`, `personal` or `regulated`) and the actions that need the requester's recorded approval, such as sending messages or publishing; record those with `openguildkit task authorize`. `new` only starts from an approved task and, when the profile lists approved tools in `"tools"`, only with one of them. The draft carries the task, the approver and the decision reason in its front matter, a section per part of the method, a Sources section and the checks as a checklist. `check` lists what keeps it from review: placeholders, missing sources, or a check not ticked with its evidence. The task record lists its deliverables, so the brains and the owner can find the draft, its sources, its checks and the decision behind it.

A project adds its own templates in `.openguildkit/catalog/deliverables/`, in the same format as `src/openguildkit/registry/deliverables/`.
