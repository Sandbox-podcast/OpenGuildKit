# Market dossiers and competitor watch

Product and Marketing judge a feature against what the market already offers. A market dossier keeps that comparison in the project, with dated sources, so each consultation reuses it instead of starting over.

## The dossier

A dossier is a JSON file in `.openguildkit/market/ID.json`, shared through git. The [example](../examples/market-dossier/support-portals.json) shows the format:

- `market`, `audience` and `feature` say what the comparison is about.
- `competitors` lists direct competitors and substitutes (`kind`: `direct` or `substitute`), such as a spreadsheet, an email routine or doing nothing.
- `observations` record what a competitor offers, each with a `source` (`ref` and `date`): a public page, a sales call note, an interview.
- `unknowns` lists what the team still needs to find out.

```bash
openguildkit market check ID
openguildkit task consult TASK --answers answers.json --market ID
```

`market check` validates the dossier and lists its gaps: a missing kind of competitor, a competitor without an observation, observations older than 180 days, and, under the `local-only` research policy, public pages to confirm and public research still to do. With `--market`, the consultation carries the observations with their age and the gaps. A board cites an observation as evidence with `"ref": "market:ID/OBSERVATION"`; the CLI refuses a reference that is not in the attached dossier. Under `local-only`, the dossier only holds material the team provided, and the gaps say what remains to document.

## Competitor watch

A dossier can keep a `watch`: the public pages to follow per competitor (release notes, pricing, announcements, funding news), the review interval `every_days`, and `paused` to suspend it.

```bash
openguildkit market due ID
```

`market due` lists the sources whose last check is older than the interval. The host agent reviews them only when the project's research policy allows public sources, then records each change it retains in `watch.changes` with what changed, its date, the source link and the person who verified it, and updates `last_checked`. Consultations carry the changes with their age; a board cites one with `market:ID/change-N`. The CLI itself never opens the network.
