# Support and deprecation policy

For: a security architect or an administrator who needs the support window before authorizing the tool, and the maintainer who must decide the open points at the end of this page.

This page states what is written today, then proposes a support window and a deprecation rule.
The proposal is not in force until the maintainers confirm it; until then, only what is stated today holds.

## What is stated today

- **Versions that receive fixes.** Only the latest release receives fixes during the 0.x series ([SECURITY.md](../SECURITY.md#supported-versions)).
- **Maturity.** The package declares itself `Development Status :: 3 - Alpha` (`pyproject.toml`).
- **Maintainers.** One maintainer today; the maintainer decides ([GOVERNANCE.md](../GOVERNANCE.md#becoming-a-steward-or-maintainer)).
- **Security reports.** Acknowledged within 14 days, then a disclosure date is agreed with the reporter ([SECURITY.md](../SECURITY.md#reporting-a-vulnerability)).
- **Versioning.** Semantic Versioning for the CLI; packs carry their own versions ([GOVERNANCE.md](../GOVERNANCE.md#releases)).
- **Upgrading.** A catalog update is adopted by a person, never received: [upgrade](install.md#upgrade).
  A release that needs more than that says so in its section of the [changelog](../CHANGELOG.md) ("Upgrading from 0.16.1").

## What the code reads today

Each stored record carries a version, and the code refuses one it does not read:

| Record | Version field | Read today |
|---|---|---|
| Profile (`.openguildkit/project.json`) | `schema_version` | 1 |
| Catalog lock (`.openguildkit/catalog.lock.json`) | `schema_version` | 1 |
| Task record | `schema_version` | 1 |
| Exported decision record | payload version | 3, 2 and 1 (`PAYLOAD_VERSIONS` in `decisions.py`) |

`tests/test_upgrade.py` loads the files that releases 0.1.0 and 0.16.1 wrote (profile, lock, tasks, one of them approved) and requires this release to read them; `tests/fixtures/upgrade/decision-record-v1.json` is a decision record of the first payload version.
`tests/test_doc_pages.py` fails when a version above changes and this table does not.

## Proposed policy

Proposed, to be confirmed by the maintainers.
Written for a team of one maintainer, from the pace the releases have had: v0.1.0 to v0.16.1 were tagged on 20 November 2026, v0.17.0 on 24 November, and `## Unreleased` of the [changelog](../CHANGELOG.md) holds more than 200 entries since.
At that pace a count of versions can pass in a day and a duration can span many versions, so each rule below takes both and ends at the later of the two.

- **Supported versions.** The latest minor version, in its latest patch release, receives every fix.
  The minor version before it receives the security fixes of the [SECURITY.md](../SECURITY.md) scope for 30 days after the next minor version is released, then nothing.
  One earlier line at a time: one maintainer can carry a backport for a month, not several.
  Thirty days leaves an administrator who upgrades hundreds of repositories one monthly change window, and covers the 14 days a security report may wait for its acknowledgement.
- **Deprecation.** A command, an option or a stored format that is to go is announced in the changelog, and from then on prints a `Warning:` line on standard error that names what replaces it.
  It keeps working for at least 2 minor versions and at least 60 days after the first release that warns, whichever ends later; its removal is a line of the changelog of the release that removes it.
  Sixty days covers two monthly upgrades; 2 minor versions alone took less than a day on 20 November 2026.
- **Names kept today without a warning.** `storybook generate --out`, the name before `--output`, and `task show --summary`, the default of `task show` since the summary became the plain form, are accepted and print no warning.
  Under this rule, the count for either one starts only with the first release that makes it warn.
- **Stored records.** Every 0.x release reads the profile, the lock, the task records and the decision records written by 0.1.0 and later, as `tests/test_upgrade.py` checks today.
  OpenGuildKit has no `upgrade` command: a release that stops reading a version, or that needs a command to convert the files of `.openguildkit/`, treats it as a deprecation above, names that command in its changelog ("Upgrading from 0.16.1" named `sync`), and keeps reading the older version until the removal.

## To be decided by the maintainer

Each point below is a decision, not a fact to look up; the first three have a proposal above.

1. **Support window.** Confirm or change the supported versions of the proposed policy.
   Today: "à décider par le mainteneur".
2. **Notice before removing a command or a format.** Confirm or change the deprecation rule of the proposed policy, and say when the names kept without a warning start to warn.
   Today: "à décider par le mainteneur".
   Until it is decided, read the changelog before each upgrade.
3. **Old versions of a stored record.** Confirm or change what the proposed policy says of stored records.
   The table above says what is read today, not what is promised.
4. **Leaving 0.x.** What changes at 1.0: the support window, the deprecation notice, the status `Alpha`?
   Today: "à décider par le mainteneur".
5. **Succession.** With one maintainer, who answers a private security report when the maintainer is away beyond what [SECURITY.md](../SECURITY.md) says?

When these are decided, the proposed policy loses its first line, this page names the supported versions and the deprecation rule as they are in force, and `SECURITY.md` keeps pointing here.
