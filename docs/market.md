# Market dossiers and competitor watch

Product and Marketing judge a feature against what the market already offers. A market dossier keeps that comparison in the project, with dated sources, so each consultation reuses it instead of starting over.

## The dossier

A dossier is a JSON file in `.openguildkit/market/ID.json`, shared through git. The [example](../examples/market-dossier/support-portals.json) shows the format:

- `market`, `audience` and `feature` say what the comparison is about.
- `competitors` lists direct competitors and substitutes (`kind`: `direct` or `substitute`), such as a spreadsheet, an email routine or doing nothing.
- `observations` record what a competitor offers, each with a `source` (`ref` and `date`): a public page, a sales call note, an interview.
- `unknowns` lists what the team still needs to find out.

The commands write the file in one layout: fields in a fixed order and one competitor, observation, unknown, watched source or change per line, so that a change to one entry shows as a one-line diff in review (adding an entry also adds a comma to the line before). A command rewrites only the top-level fields it changes, in this layout; the rest of the file keeps its bytes, so a dossier written by hand keeps its own layout in the fields no command touched, and a byte order mark and Windows line endings (CRLF) stay as they were.

Dates are written `YYYY-MM-DD` and cannot be in the future (one day of margin for time zones). Each list field must be a JSON list and `paused` is `true` or `false`; a malformed dossier gets a one-line error.

## Record through commands

The commands below create and update a dossier without editing the JSON; each one validates the whole dossier before writing it.

```bash
openguildkit market new ID --market "B2B software vendors" --audience "Support leads" --feature "Request status"
openguildkit market describe ID --feature "Request status and next step"
openguildkit market competitor ID --competitor vendor-a --name "Vendor A" --kind direct --url https://example.com/vendor-a
openguildkit market observe ID --competitor vendor-a --observation a-status-page --claim "Shows a status per request." --source "Sales call notes" --date 2026-11-02
openguildkit market unknown ID --text "Prices of the portal option."      # --remove once it is known
openguildkit market check ID
openguildkit task consult TASK --answers answers.json --market ID
```

`market new` creates a dossier that `market check` accepts; what is not given yet is marked "To describe." and listed as a gap. `market observe` with an existing observation ID replaces it, so a refresh keeps one entry.

`market check` validates the dossier and lists its gaps: a field to describe, a missing kind of competitor, a competitor without an observation, observations older than 180 days, and, under the `local-only` research policy, observations and changes that cite a public page (to confirm a person provided them) and public research still to do. With `--market`, the consultation carries the observations with their age and the gaps. When the dossier's `feature` shares no word with the task brief (as revised, if it was) and its `context` answer, the consultation adds a one-line `relevance` note that names the dossier and its feature, so the boards check it is the right dossier before citing it. A board cites an observation as evidence with `"ref": "market:ID/OBSERVATION"`; the CLI refuses a reference that is not in the attached dossier. Under `local-only`, the dossier only holds material the team provided, and the gaps say what remains to document.

## Competitor watch

A dossier can keep a `watch`: the public pages to follow per competitor (release notes, pricing, announcements, funding news), the review interval `every_days`, and `paused` to suspend it. A watched page, and a `--source` of `market observe` or `market change` that is a link, must be a public https link: one with a user name, a password or a token in its query, or on a private host, is refused, because the dossier is committed and the scheduled watch copies the link into an issue. A source that is a note or a document, not a link, stays as written.

```bash
openguildkit market watch ID --competitor vendor-a --url https://example.com/vendor-a/release-notes --kind "release notes" --every-days 30
openguildkit market due ID                 # or --all for every dossier, --json for a script
openguildkit market checked ID --url https://example.com/vendor-a/release-notes
openguildkit market provided ID --url https://example.com/vendor-a/release-notes --by CM   # local-only
openguildkit market change ID --competitor vendor-a --what "Added priority labels." --source https://example.com/vendor-a/release-notes --date 2026-11-10 --verified-by CM
openguildkit market pause ID               # resume restarts the watch
```

`market due` lists the sources whose last check is older than the interval. The sources are reviewed only when the project's research policy allows public sources. `market checked` records a review with nothing to keep; `market change` records a retained change with what changed, its date, the source link and the person who verified it. Both set `last_checked` of the watched source to today (for `market change`, when its `--source` is a watched page). Under the `local-only` research policy no agent opens the page: `market due` lists the sources due and says that a person reviews each one, then runs `market provided` with their initials ([personal data](personal-data.md)). `market checked` is refused there, and so is `market change` on a watched page no person has provided yet: both name the `market provided` command to run. The issue of the scheduled watch names `market provided` too, and the page offers "Relue par une personne" instead of "Relue, rien de neuf". That records `provided_by` and sets `last_checked` (today, or `--date`) on the watched source, so `market due` no longer lists it until the interval passes again, and `market check` no longer asks to confirm that the observations and changes citing that page were provided. Consultations carry the changes with their age; a board cites one with `market:ID/change-N`. The CLI itself never opens the network.

## The `market-analyst` agent

`openguildkit integrations --host claude-code` installs `.claude/agents/market-analyst.md` next to `guild-board`. It fills and refreshes a dossier through the commands above only. Under `local-only` it works from the documents the team provides and records what needs a public page as an unknown. Under `public-sources` it may also read the approved public pages of the dossier, dates and sources each observation, reads nothing behind a login, collects no personal data and respects the sites' terms. When the project connected a browser tool from the [tool registry](tools.md) (Obscura or Playwright), it may read public pages with it, within the same limits. Codex and the other hosts install no agent file: the skill (`SKILL.md`, section "Market dossiers") carries the same limits, word for word, and the same steps, and the agent of such a host follows them itself; a test compares the two lists of limits.

## Scheduled watch

[`integrations/github/openguildkit-market-watch.yml`](../integrations/github/openguildkit-market-watch.yml) runs `openguildkit market due --all --json` every Monday and opens one issue per source to review, unless an open issue already has its title. The issue says which command records the result. The job opens no competitor page itself. Its actions are pinned by commit SHA.
