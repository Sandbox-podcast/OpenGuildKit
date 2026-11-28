# Support and deprecation policy

For: a security architect or an administrator who needs the support window before authorizing the tool, and the maintainer who must decide the open points at the end of this page.

This page states what is written today.
It invents no duration: where a number is missing, the page says that the maintainer decides and asks the question.

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

## To be decided by the maintainer

None of these has a written answer; each is a decision, not a fact to look up.

1. **Support window.** Does a release other than the latest receive fixes after a new minor version appears, and for how long?
   Today: "à décider par le mainteneur".
2. **Notice before removing a command or a format.** How many minor versions, or how many months, between the announcement of a deprecation and the removal?
   Today: "à décider par le mainteneur".
   Until it is decided, read the changelog before each upgrade.
3. **Old versions of a stored record.** From which `schema_version` of the profile, the lock and the task, and from which payload version of a decision record, must a release keep reading older files, and until when?
   The table above says what is read today, not what is promised.
4. **Leaving 0.x.** What changes at 1.0: the support window, the deprecation notice, the status `Alpha`?
   Today: "à décider par le mainteneur".
5. **Succession.** With one maintainer, who answers a private security report when the maintainer is away beyond what [SECURITY.md](../SECURITY.md) says?

When these are decided, this page names the supported versions and the deprecation rule, and `SECURITY.md` keeps pointing here.
