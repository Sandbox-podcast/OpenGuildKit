# Business deliverables

An approved task often leads to work outside the code: a campaign brief, a landing page, a release announcement, a support article. A deliverable template gives that work a method, the inputs it needs, the tool actions that need the requester's approval and the checks a reviewer runs.

```bash
openguildkit deliverable list
openguildkit deliverable show campaign-brief
openguildkit deliverable new campaign-brief --task launch --tool Brevo --output marketing/spring-brief.md
openguildkit deliverable check marketing/spring-brief.md
openguildkit deliverable utm --url https://www.example.test/pricing --campaign spring-launch --source newsletter --medium email
```

`deliverable check` reads a draft saved as UTF-8, with or without a byte order mark, and refuses a draft in another encoding by name.

| Template | Method | Market dossier | Brains that review it |
|---|---|---|---|
| `campaign-brief` | `marketing-campaign-planning` | yes | marketing, communication, legal |
| `landing-page-brief` | `search-engine-optimization` | yes | marketing, design, communication |
| `product-one-pager` | | yes | product, marketing, sales |
| `case-study` | | yes | marketing, sales, communication, legal |
| `newsletter-issue` | `utm-campaign-measurement` | | marketing, communication, legal |
| `social-media-plan` | `marketing-channel-planning` | yes | marketing, communication, legal |
| `press-release` | `release-and-incident-communication` | | communication, legal, leadership |
| `webinar-plan` | `marketing-campaign-planning` | | marketing, product, sales, legal |
| `pricing-page-brief` | `market-competitor-analysis` | yes | product, marketing, finance, sales, legal |
| `competitive-battle-card` | `market-competitor-analysis` | yes | sales, marketing, product, legal |
| `release-announcement` | | | communication, support, product |
| `support-article` | | | support, communication |
| `architecture-decision-record` | | | engineering, project-management |

The method is a pattern of the bundled catalog (see [patterns](patterns.md)): its rules and its sources apply to the deliverable. A template without a method relies on its sections and checks only; none of the new marketing templates cites a source of its own.

`deliverable show` and `deliverable new` list, before anyone opens the tool, the data each input needs (`none`, `internal`, `personal` or `regulated`) and the actions that need the requester's recorded approval, such as sending messages or publishing; record those with `openguildkit task authorize`. `new` starts from an approved or completed task (`approved`, `done` or `done-with-reservations`) and takes an optional `--tool`, required only when the template declares `"requires_tool": true`: when it is given and the profile lists approved tools in `"tools"`, it must be one of them. `--output` is a path inside the project and outside `.openguildkit/`, once symbolic links are followed. The draft may go to a client, so it carries no internal approval field: its front matter names the deliverable, the task and the tool, and the approver and the reason stay in the task record. It holds the inputs, a section per part of the method, a Sources section and the checks as a checklist.

A template marked "Market dossier" uses the [market dossier](market.md) the task was consulted with (`task consult --market ID`): the draft records `market: "ID"` in its front matter and lists the dossier file under Inputs, so its observations can be cited as `market:ID/OBSERVATION`. When the task has no dossier, the Inputs say how to attach one.

`check` lists what keeps a draft from review:

- the front matter fields `deliverable` or `task` missing, `tool` missing when the template requires one, or the internal fields `approved_by` and `decision_reason` that drafts of earlier versions carried;
- a section of the template, `Inputs`, `Sources` or `Checks` missing or empty, each named;
- placeholders that still say TODO;
- no source listed under `## Sources`;
- a check not ticked with its evidence under `## Checks`.

Only what a reader sees counts: a heading, a source or a ticked check inside an HTML comment (`<!-- -->`) or a fenced code block is ignored. An empty draft therefore lists every missing section. The task record lists its deliverables, so the brains and the owner can find the draft, its sources, its checks and the decision behind it.

## Architecture decision record

`architecture-decision-record` keeps an approved decision task in the repository, where the code it shapes lives:

```bash
openguildkit deliverable new architecture-decision-record --task choose-bus --output docs/adr/0007-choose-bus.md
openguildkit deliverable check docs/adr/0007-choose-bus.md
```

It starts only from a decision task (answer `kind` set to `decision` at `task consult`) that is approved or closed. Any other task is refused with its kind and the way out: open a decision task for the choice, or pick another template. The draft is filled from the task record:

| Section | Filled with |
|---|---|
| Status | Accepted, with the day of the approval; closed on a day, closed with reservations (`task show ID --closing` lists them, the draft does not copy them), or not closed yet with `task complete ID`; and the task it follows, if any |
| Context | The brief, then the context and who it affects, as answered at consultation |
| Options considered | The answer to the `options` question |
| Decision | The reason the person gave when approving, who approved and on which day, and the summary of the boards' review |
| Board advice and disagreements | Each board's verdict and recommendation; the disagreements the deliberation left open and the decision it said was needed, or the objections no deliberation answered |
| Conditions | Each blocker a board set, before or after the decision, with when it clears and whether it was cleared (with the evidence), waived (until when, why, for what scope) or is still open |
| Consequences | `TODO`: what becomes easier or harder is the person's to write |
| Decision record | The exported decision record, `.openguildkit/decisions/ID.json`, written by `task export ID`, and the decision seal it carries |

What a person typed (the brief, the answers, the reason, the summary) is quoted with `>`, so a heading in it cannot open a section of the draft. Unlike the other templates, this draft holds the reason of the approval and the name of the approver as the decision records them: it stays in the repository next to the exported record, which carries both already. No other name is copied: not the owners of the blockers, not who cleared or waived them, nor who closed the task. A section the task cannot fill, such as options a task of an earlier release never recorded, says `TODO` with what to write. `deliverable check` then names what is left, as for every draft: the `TODO` of Consequences, a section emptied by hand, and the three checks to tick with their evidence (`options-compared`, `consequences-stated`, `record-linked`). The format follows Michael Nygard's [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) (title, status, context, decision, consequences), with the committees' advice and the conditions added.

## Tagged campaign links

`deliverable utm` prints a landing page address tagged for analytics, following the `campaign-measurement` pack (pattern `utm-campaign-measurement`):

```bash
openguildkit deliverable utm --url "https://www.example.test/pricing?plan=team" --campaign spring-launch --source newsletter --medium email --content header-button
# https://www.example.test/pricing?plan=team&utm_source=newsletter&utm_medium=email&utm_campaign=spring-launch&utm_content=header-button
```

`--campaign`, `--source` and `--medium` are required; `--content` and `--term` are optional. The pack asks for the values agreed with the analytics owner, in the same case on every link, and for no personal data in them. Since analytics tools treat `Email` and `email` as two mediums, the command trims each value and accepts only lowercase letters, digits, `.`, `-` and `_`: a value with a capital or a space is refused rather than rewritten, so you correct it to the agreed spelling. A value that looks like an email address is refused. The landing URL must be an https address with a host; one that already carries `utm_` parameters is refused, its other parameters and its `#fragment` are kept. The command prints the link and opens nothing. The templates that publish links (`campaign-brief`, `landing-page-brief`, `newsletter-issue`, `social-media-plan`, `webinar-plan`) point to it in their measurement or promotion section.

A project adds its own templates in `.openguildkit/catalog/deliverables/`, in the same format as `src/openguildkit/registry/deliverables/`. Set `"market": true` on a template that should carry the task's market dossier, `"requires_tool": true` when its draft needs a named tool, and `"decision": true` when it is written from a decision task: its sections whose `id` is `status`, `context`, `options`, `decision`, `advice`, `conditions` or `record` are filled as above, and any other section says `TODO`.
