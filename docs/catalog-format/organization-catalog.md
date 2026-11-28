# Organization catalog

For: an organization that keeps one catalog for several repositories, and the person who pins it.
A part of the [catalog format](../catalog-format.md).

An option, off by default (RFC #446, not decided yet): several repositories can follow the same catalog of an organization, pinned at a commit of a local Git copy.
A project that does not set one reads and writes exactly what it did before, and runs no Git command for it.

The organization's repository holds `packs/`, `boards/`, `sectors/` and `patterns/` at its root, in the format of a project catalog.
Its records pass the same checks as a project's, with two differences: a pack may not declare a `command` check, since nothing read from another repository runs, and an ID that ships with OpenGuildKit is refused, since an organization catalog adds records.
References, deliverables, tools and tool mocks are not read from it.

OpenGuildKit never fetches.
The person keeps the copy up to date (`git -C ../org-catalog fetch`), and OpenGuildKit reads the files at the pinned commit with `git ls-tree` and `git cat-file`, whatever branch the copy has checked out.

```bash
openguildkit org-catalog set --repo ../org-catalog --commit FULL_SHA              # what the commit adds, removes and changes
openguildkit org-catalog set --repo ../org-catalog --commit FULL_SHA --by INITIALS --reason WHY   # pin it, at a terminal
openguildkit profile add pack ORG_PACK --by INITIALS --reason WHY                     # use one of its packs
openguildkit org-catalog show                                                     # what the project follows and replaces
```

- **The pin.** `set` with `--by` and `--reason` asks the person to type the first 12 characters of the commit, then writes the instructions and, in `.openguildkit/catalog.lock.json`, an `organization` entry: the full commit, the `sha256:` fingerprint of the files read, who pinned it, when and why, and the copy (below).
  Changing the commit is the same command: it lists the records added, removed and changed, with the version of each pack, and the tasks consulted under the previous rules.
  A commit that drops a record the profile uses is refused.
  `update --apply` and `sync` keep the pin.
  A new repository can be pinned before `init`, so that `init --answers` reads the organization's packs; `profile export` names the commit to pin there.
- **The copy: a name, or a path.** With `--name acme` the lock keeps the name and no path, so the same lock reads on every machine and on a CI runner.
  Each machine sets `OPENGUILDKIT_ORG_CATALOG_ACME` (the name in capitals, `-` as `_`) to the folder of its copy, and `guard --ci --org-catalog acme=PATH` takes the folder on a runner; the flag wins over the variable.
  Without `--name`, the lock keeps the path of the copy, relative to the project root when it can be: the copy must then sit at that path next to every checkout.
  `org-catalog show` proposes the move to a name when the lock keeps a path.
- **History.** Each pin and each stop is added to `organization_history` in the lock, with the commit, who, when and why: `off` removes the pin, not its trace.
  `org-catalog show --json` prints it under `history`.
- **Order.** The bundled catalog, then the organization's records, then the project's own `.openguildkit/catalog/`.
  The catalog lock does not copy the organization's records: the commit and the fingerprint already fix them.
- **A local replacement.** A project record with the ID of an organization record replaces it (a project board completes it, as it completes a bundled one).
  `check` says so, as a warning with the SARIF code `catalog-org-replaced`, and `org-catalog show` lists it, until a person runs `openguildkit org-catalog accept COLLECTION/ID --by INITIALS --reason WHY` at a terminal.
  The acceptance holds for that edition of the organization record: when a new commit changes it, `check` says so again.
- **When it cannot be read.** If the copy is missing, the commit is not in it, or the files no longer match the fingerprint, every command that reads the catalog stops, `check` included, with the command that fixes it: `git -C PATH fetch`, or `org-catalog set` with the right path or commit.
  The message names the folder it looked in.
  A lock that names the catalog and finds neither the variable nor the flag says which one to set.
- **In CI.** `guard --ci` reads the base revision in a temporary folder but looks for a relative copy from the real project root, so a pin made at `../org-catalog` works when the runner has the copy there.
  For a named pin, check out the catalog repository in the workflow and pass its folder (`integrations/github/openguildkit-guard.yml` shows the step).
  A path given to `set` is stored relative to the project root, never absolute: use a name for a runner.
- **A new commit in N repositories.** [`integrations/github/openguildkit-org-catalog-update.yml`](../../integrations/github/openguildkit-org-catalog-update.yml), copied to each repository, checks out the catalog every Monday and, when its default branch moved past the pinned commit, opens a pull request whose description is the output of `org-catalog set` without `--by` and the command to pin.
  The job pins nothing and writes no file (its branch holds one empty commit): a person checks out the branch, pins at their terminal, commits the lock and pushes, or closes the pull request.
- **Off.** `openguildkit org-catalog off --by INITIALS --reason WHY`, at a terminal, removes the pin once the profile no longer uses its records, and records who stopped it, why and at which commit in the history.

## Organization policy

An option, off by default (RFC #452, not decided yet): the security or platform team writes `policy.json` at the root of the organization catalog, and every repository that pins a commit holding it keeps its minimum.
A repository may be stricter, never less strict.
A commit without `policy.json` keeps the fingerprint it had, and a project that follows no organization catalog reads nothing more.

```json
{"schema_version": 1,
 "minimum": {"guard": "enforce", "approval": "signed", "separate_requester": true},
 "required": {"packs": ["secure-sdlc"]},
 "frozen": {"by": "SEC", "reason": "Compromised model provider", "since": "2026-11-28"}}
```

Every field but `schema_version` is optional; any other field stops the pin, so a requirement OpenGuildKit does not enforce never passes for one it does.
`minimum.guard` is `observe` or `enforce`, `minimum.approval` is `signed`, `minimum.separate_requester` is `true`, `required.packs` lists pack IDs (an organization pack is used once the project follows the catalog that provides it).

- **The pin.** `org-catalog set` reads `policy.json` with the records and says the minimum the commit brings; the person pins it at a terminal, as for the records.
  `openguildkit org-catalog policy` shows the minimum in force and where the profile is under it.
- **Profile changes.** `profile set`, `add`, `remove` and the web page refuse a change that goes under the minimum, even from a person at a terminal, and write nothing.
  A change that raises a setting, or keeps a gap the profile already had, goes on.
- **`check`** fails with one line per gap, which names the setting, the value required, the commit of the policy and the command that meets it (SARIF `policy-below-floor`), and with `policy-frozen` while the policy freezes the repositories.
- **In CI.** `openguildkit guard --ci --org-policy PATH --org-commit SHA` reads the policy from the copy and the commit the organization's required workflow gives, never from the lock a pull request carries; without the options it reads the commit the base revision pins.
  It fails, whatever the guard mode, when the profile of the base revision or the one the change brings is under the minimum.
- **Freeze (#481).** `frozen` stops the merges of every repository whose required workflow passes the policy commit: `guard --ci` fails every change with `policy-frozen`.
  Only a new commit of the policy lifts it.
  Edits on each workstation stop through the freeze of each project (`openguildkit profile set freeze on`, [incident response](../workflow.md#incident-response)).
- **`--policy-repo`** still reads only the central export rule `packs/export-link-expiry.json`; on a commit that holds `policy.json` instead, it names the commands above.
