# Business deliverables

An approved task often leads to work outside the code: a campaign brief, a landing page, a release announcement, a support article. A deliverable template gives that work a method, the inputs it needs, the tool actions that need the requester's approval and the checks a reviewer runs.

```bash
openguildkit deliverable list
openguildkit deliverable show campaign-brief
openguildkit deliverable new campaign-brief --task launch --tool Brevo --output marketing/spring-brief.md
openguildkit deliverable check marketing/spring-brief.md
openguildkit deliverable utm --url https://www.example.test/pricing --campaign spring-launch --source newsletter --medium email
```

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

## Tagged campaign links

`deliverable utm` prints a landing page address tagged for analytics, following the `campaign-measurement` pack (pattern `utm-campaign-measurement`):

```bash
openguildkit deliverable utm --url "https://www.example.test/pricing?plan=team" --campaign spring-launch --source newsletter --medium email --content header-button
# https://www.example.test/pricing?plan=team&utm_source=newsletter&utm_medium=email&utm_campaign=spring-launch&utm_content=header-button
```

`--campaign`, `--source` and `--medium` are required; `--content` and `--term` are optional. The pack asks for the values agreed with the analytics owner, in the same case on every link, and for no personal data in them. Since analytics tools treat `Email` and `email` as two mediums, the command trims each value and accepts only lowercase letters, digits, `.`, `-` and `_`: a value with a capital or a space is refused rather than rewritten, so you correct it to the agreed spelling. A value that looks like an email address is refused. The landing URL must be an https address with a host; one that already carries `utm_` parameters is refused, its other parameters and its `#fragment` are kept. The command prints the link and opens nothing. The templates that publish links (`campaign-brief`, `landing-page-brief`, `newsletter-issue`, `social-media-plan`, `webinar-plan`) point to it in their measurement or promotion section.

A project adds its own templates in `.openguildkit/catalog/deliverables/`, in the same format as `src/openguildkit/registry/deliverables/`. Set `"market": true` on a template that should carry the task's market dossier and `"requires_tool": true` when its draft needs a named tool.
