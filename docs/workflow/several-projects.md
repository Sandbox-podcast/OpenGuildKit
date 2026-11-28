# Several projects at once

For: a person who follows several projects at once.
A part of the [task workflow](../workflow.md).

```bash
openguildkit projects ~/code                      # each project among the subfolders of ~/code
openguildkit projects ~/code/*                    # the folders the shell names, one by one
openguildkit projects ~/code --search "refund"    # briefs, decision reasons and rule IDs that hold the text
openguildkit projects ~/code --json               # every project and every match, for a program
openguildkit projects ~/code --surfaces           # also the agent tools and MCP servers of each folder, a project or not
openguildkit projects ~/code --policy policy.json --strict --format csv > fleet.csv   # gaps to a minimum, one line per folder
```

A tech lead or a security officer who looks after several repositories sees where to act without opening each one.
`projects` takes folders: a project itself, or a folder whose subfolders are projects (one level down; hidden folders are skipped).
Without a folder it reads the current one.
It prints one line per project: the guard mode, whether approvals are signed, the tasks by status, the approvals that no longer hold, the open points (the blockers a reviewed task still waits on and the points a task closed with reservations left open), the critical alerts confirmed in the alert register, and whether `openguildkit check` passes, with its last line when it fails.
The last line gives the `check` command of the first project that fails it.

A folder that is not an OpenGuildKit project is named on one line (`Not OpenGuildKit projects (N): ...`), a path that does not exist on its own line, and a project whose profile, catalog lock or alert register cannot be read on its own line with the reason (`cannot be read: ...`): the other projects are still listed, and the command ends with exit code 0.

`--search TEXT` finds the text, case aside, in the first line of each task's brief, its decision reason and the rule IDs of its result (`rule:python/follow-python-style (failed)`), in the tasks of each copy and then in the exported records of the tasks it does not hold.
Each match names its project.
The first 50 are printed; `--json` gives them all.

`projects` writes nothing and registers no project anywhere: it reads each project as its own commands do, runs `check` in the same process, and takes the folders again at each run.
The web interface runs it on its own project only, since a path outside the project is refused there.

## Inventory of a fleet (options, off by default)

`--surfaces` adds to each project what `host scan` finds in its folder: the host and the state of its hooks, the agent tools, the MCP servers (how many, how many without a fixed version, how many the registry does not know), the permissive settings, the version that wrote the catalog lock, the commit of the organization catalog it follows and the day of its last decision.
A folder without a profile is read the same way: where agents already work, it is printed on its own line (`not an OpenGuildKit project; agents at work: cursor`) instead of among the folders that hold nothing.
That is the list to read before a deployment.

`--policy FILE` compares each project with the minimum a JSON file describes, and reads the surfaces too.
The file is read and never written, and holds any of three fields:

```json
{"guard": "enforce", "approvals": "signed", "separate_requester": true}
```

`guard` is the lowest mode accepted (`off`, `observe` or `enforce`), `approvals` asks for signed approvals, `separate_requester` asks for the [requester kept from approving](requester-and-approver.md).
Each gap is named, with the value found, on the line of the project (`policy gap: guard observe, the policy asks for enforce`) and under `drift` in `--json`.
A folder where agents work without a profile, and a project that cannot be read, are a gap of the field `project`.
Any other field, or a value the policy does not allow, stops the command, so that a typo is not a rule that never fires.
`--strict` ends in 1 when a folder falls short; it needs `--policy`.

`--format csv` prints one line per folder under a header that does not change: `path,state,name,guard,approvals,tasks,attention,open_points,critical_alerts,check,host,hooks,lock,catalog_commit,last_decision,tools,mcp_servers,mcp_unpinned,mcp_unlisted,permissive,drift`.
A cell is empty when its option was not given (`--surfaces` fills `host` to `permissive`, `--policy` fills `drift`, where `none` says that no gap was found), `tools` and `tasks` hold `;`-separated values, and a text that starts with `=`, `+`, `-` or `@` gets a quote before it, so that a spreadsheet shows a project name instead of running it.
It does not go with `--json` or `--search`.
None of this writes in a project: the folders are read as before, and a policy file may sit anywhere.

## A fleet without clones

[`integrations/github/openguildkit-status.yml`](../../integrations/github/openguildkit-status.yml), copied to `.github/workflows/` of each repository, runs `openguildkit projects . --surfaces --json` on each push to the default branch, with a read-only token, and keeps the result, with the name of the repository and the revision, as the artifact `openguildkit-status` for 90 days.
A repository without a profile can carry it too: its status says which agent tools work there.
The security officer then gathers the latest status of each repository with `gh`, without cloning any, and reads them with `jq`:

```bash
for repo in $(gh repo list ORGANIZATION --limit 500 --json nameWithOwner --jq '.[].nameWithOwner'); do
  run=$(gh run list -R "$repo" --workflow openguildkit-status.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId // empty')
  [ -n "$run" ] && gh run download "$run" -R "$repo" -n openguildkit-status -D "fleet/$repo"
done
jq -r '.repository as $r | .projects[] | [$r, .state, .guard // "", (.tools // [] | join(";"))] | @csv' fleet/*/*/openguildkit-status.json
```

A repository that has not pushed since the template was added, or whose artifact expired, has no status: the loop skips it.
