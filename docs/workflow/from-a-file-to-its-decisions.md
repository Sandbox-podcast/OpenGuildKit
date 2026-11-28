# From a file to its decisions

For: a reviewer who asks which decisions cover a file.
A part of the [task workflow](../workflow.md).

```bash
openguildkit trace src/api/auth.py          # the decisions that cover the file, most recent first
openguildkit trace src/api/auth.py --json   # each decision with its checks, evidence and standing
```

A pull request reviewer, a security officer or an auditor asks which decision covers a file and whether the file changed since.
`trace` reads the records of `.openguildkit/decisions/`, teammates' included, and prints one line for each record whose `files` list the path: the task, its status, the day of the approval, the approver's initials, the delivered revision (or the pull request), and how many checks passed and failed.
The line under it names the record and whether it still holds, in the words of `task list --decisions`: a withdrawn approval (`task revoke`, then `task export`) says who withdrew it and that the record covers nothing; a record that no longer matches its digests or its rules says why.
A check log whose sha256 no longer matches the record is named as evidence changed since the export.

A file of the folder that is not a record, or a record without its list of files, is printed as `[unreadable]`: it may cover the path, so fix or remove it and trace again.
A record exported outside Git lists no files and covers no path.

Then Git says whether the file changed after the most recent decision: after its delivered revision when this history holds it, otherwise after the commit that last wrote its record.
A commit on the file after that point prints `Changed since the last decision (commit abc1234): no decision covers this change.` Outside a Git repository, or when the record is neither committed nor names a revision of this history, the check is skipped and the command says so.
The last line gives `openguildkit task show ID` for the most recent decision; a file that no record lists gets one line and `openguildkit task new`.

The path is read from the current folder inside the project, from the project root otherwise; a path outside the project is refused.
`trace` writes nothing: no task, no record, and Git runs without its optional locks, so the index is not refreshed either.
It always ends with exit code 0: what it finds is for a person to read, and `guard --ci` is the check that fails a pull request.

For an auditor, `openguildkit evidence export --output DOSSIER` gathers the exported decisions of a period with the state of their seals and signatures, and `evidence verify DOSSIER` checks that no file changed ([compliance](../compliance.md#the-evidence-dossier)).
