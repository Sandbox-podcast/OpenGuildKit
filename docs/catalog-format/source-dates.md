# Source dates

For: a contributor who writes or re-reads the source of a rule, and a maintainer who runs the link check.
A part of the [catalog format](../catalog-format.md).

Every source carries `checked`, a date written `YYYY-MM-DD`, placed right after its `url`:

```json
{
  "title": "Regulation (EU) 2016/679 (GDPR), official text",
  "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng",
  "checked": "2026-11-20"
}
```

`checked` is the day the page was last opened and answered; a contributor who writes or changes a rule re-reads its source and sets the date to that day.
It does not certify that someone re-read the whole document on that day.

How a bundled source is verified and dated:

- **A contributor writes or changes a rule.** They open the source, check the rule's article, threshold or wording against it, and set `checked` to that day.
  The loader refuses a bundled source without a valid date, and a test reads every packs, boards, patterns, sectors, references and deliverables file.
  Every loader refuses a `checked` date, or a tool server's `verified` or `reviewed` date, that is not a calendar day or that is after today (one day of margin for time zones); a test refuses any bundled date after the day it runs.
- **A maintainer runs the link check.** `python3 -I scripts/check_links.py --out link-report --stamp` opens every source page and writes the dates: a page that answered (available, or redirected to a page that answered) gets the day of the report; a page that did not answer or refused the script (dead, 401, 403, 429, a timeout) keeps its date, and a source that has none gets the day its URL entered the catalog, read from the Git history (`git log -S`, the oldest commit's author date; a shallow clone is refused).
  The script prints each source that did not answer, to open by hand.
  It never gives the day of the run to a page that did not answer.
  `--stamp-from link-report/links-DATE.json` writes the dates from a saved report without opening the pages again, so the result depends only on the report and the history and can be run again after a merge.
- **Every Monday** the `Check catalog links` workflow lists, besides dead, redirected and to-recheck links, the sources whose `checked` date is older than 180 days (`--max-age DAYS` to change it), with the records that cite each one.
  It fails only on dead links.
- **Editions.** `scripts/watch_editions.py`, run each Monday by the `Watch reference editions` workflow, opens the source pages of each reference that declares an `edition` and looks for the edition's text.
  A page whose address does not carry the edition is read first; once the watch has seen the edition there, that page alone decides, and the pages whose address carries an edition are no longer opened.
  It records in `scripts/edition-watch.json`, per reference, the page, the edition last seen and the day (`seen`, `seen_on`), where it was seen (`seen_in`: on the `page`, or in the `catalog` on the latest `checked` date of the reference's sources until the watch finds it on its page), the day of the check (`checked`) and a status: `from-catalog` (seeded, no page opened yet), `found`, `not-found` (the page answered, never showed the edition, and the catalog gives no date), `unreachable`, or `may-have-changed` (the edition recorded as seen is no longer on the page).
  The workflow opens one issue per reference in `may-have-changed`, never a second one while the first is open, and keeps the updated file as an artifact; the [reference library](../references.md#edition-watch) says who commits the file and when.
  The heuristic compares text: a page that reformats its edition text (`Rev 5` for `Rev. 5`) raises a false alarm; a publisher that keeps the old edition's page online, unchanged, hides a new edition and nothing is detected; a page built by scripts or served as a PDF rarely shows its edition, so it is reported once its catalog date is the last observation, until the reference points at a page that shows the edition; a short edition such as a year can match an unrelated date.

What a project sees:

- `openguildkit references --id ID` and `openguildkit patterns --id ID` print each source with its date, `(checked 2026-11-20)`, and the JSON outputs carry `checked`.
- `openguildkit update` starts with the date of the installed catalog, the most recent `checked` date among its bundled sources, and the number of records that changed since the project's lock: `Installed catalog: sources checked up to 2026-11-21. 3 records changed since the project's lock.` A record whose only change is a newer date shows `~ N sources checked again, latest DATE`; applying it changes no rule and leaves consulted tasks current.
- A project's own sources in `.openguildkit/catalog/` (packs, boards, sectors, patterns, references, deliverables) load without a date, so an upgrade breaks nothing, but `openguildkit check` prints a notice that names each record with an undated source.
  To date one, open the page, check what the record says against it and add `"checked": "YYYY-MM-DD"` after its `url` with that day's date; change the date each time you re-read the page for a rule.
  The link check and the edition watch read only the bundled catalog: a project that wants the same watch runs its own.
