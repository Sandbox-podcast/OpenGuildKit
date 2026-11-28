# Short lane

For: the person who turns on the short lane, and the agent that opens a task in it.
A part of the [task workflow](../workflow.md).

The six steps above are the same for a typo and for a feature.
When a safeguard is that heavy for a trivial change, a team's first reaction is to turn it off (`"guard": "off"`).
The short lane is an opt-in way through the workflow for a change a person declares trivial, and it takes out only what has no meaning for one reviewing board.
It is off in every project until a person turns it on, and a project that never does behaves exactly as before.

## Turn it on

A profile that names `light_paths`, the folders or files a short-lane task may change, has the lane.
The person types it at their terminal, with who and why:

```bash
openguildkit profile set light-paths 'docs/**' 'tests/**' --by CM --reason "A typo in the docs or a test needs one reviewer"
```

Turning the lane on, or adding a path, lowers the rigor of that part of the project, so the command follows the rule of every setting that weakens a protection: it needs a person at an interactive terminal, who types the paths to confirm, and an agent without one is refused with the same message and nothing is written.
The profile keeps who, when and why in `changes`.
Fewer paths, or `openguildkit profile set light-paths none`, makes the project stricter and needs no terminal, as removing a pack that is not a protection does.
The web page cannot turn the lane on either: it is refused with the command to type.
The setting is not part of what an approval rests on, so turning the lane on or off voids no approval: the edit hook, `task complete` and `guard --ci` read it when they act.
The profile file is protected like every other setting (the edit hook refuses an edit of it in `enforce` and flags it in `observe`), and `guard --ci` reads `light_paths` from the base revision, never from the pull request.
As for every setting, `init --answers` accepts `light_paths` at setup, when there is no approval to weaken.

A path is a folder or file glob inside the project: `*` and `?` stay inside a folder, `**` is a whole segment that crosses folders (`docs/**`, `tests/**/*.py`, `README.md`).
A trailing `/` names a folder.
`**` alone, `..`, a leading `/` and other wildcards are refused, and a list holds at most 50 paths.

## Open a short-lane task

```bash
openguildkit task new "Fix the typo in the export page of the guide" --id guide-typo --lane light --paths 'docs/**'
```

Without `--lane`, a task takes the full path, unchanged.
Every path of `--paths` must be covered by `light_paths`; a path outside is refused with the list of the paths at fault and the command of the full path.
In a project that has not turned the lane on, `task new --lane light` is refused with the command a person types to turn it on.

The lane is declared by the person's request, never guessed: the paths and the lane are part of what the person approves.
The approval prompt, `task challenge` and `task decision-payload` open with a line that names them, the seal of the approval covers them (a signer reads them in clear in the payload, and `guard --ci` refuses an exported record whose `lane` or `paths` differ from the approved ones), and the handoff repeats them.

## What the lane shortens

| Step | Full path | Short lane |
|---|---|---|
| Framing | `task questions`, then `--answers FILE` | No questionnaire: `task consult ID` takes the lane's answers, `kind: maintenance`, `data: none`, `research: local`, `concerns: none` and `surface: other`. `other` is an open answer: the rules of every surface stay asked, as for `unsure`, so the closing asks as much as it would. `task questions` and `task route` say so. |
| Boards | Chosen from the answers and the words of the brief, adjusted with `--add` and `--remove` | One board chosen by the paths: `developer-relations-and-docs` when every path is documentation (`docs/`, `README.md`, `.md`, `.rst`...), `qa` when every path is tests (`tests/`, `test_*.py`, `*.spec.ts`...), `engineering` otherwise, a mix included. The boards the profile requires (`required_boards`) still join: the lane never drops a mandatory review. `--add`, `--remove` and `--answers` are refused. A board the project has not enabled is named, never replaced. |
| Deliberation | `task deliberate` and `task respond` | Nothing to deliberate with one board (a required board that disagrees can still be deliberated). |

## What the lane does not shorten

The pass of the board and its entry (`task pass`, `task submit`, with their validations), the review (`task review`), the blockers (`task clear`, `task waive`, with the person at a terminal), the decision by a person at a terminal (`task decide`, the typed ID, the sealed approval, the signature when the profile requires signed approvals), the handoff, `task verify`, `task result`,
`task complete` (with the person's `--by` for what only a person closes), `task export` and the exported record.
A request for changes and `task revoke` work as on the full path.

## What the lane covers

The task records `lane` and `paths`; `task list` shows them (`(short lane: docs/**)`), and the exported record carries `"lane": "light"` and `"paths"`.

- **The edit hook** (`guard --hook pre-edit`) holds a short-lane task to its paths.
  An approved short-lane task covers an edit to a file its paths and the profile's `light_paths` both name.
  An edit outside is refused in `enforce` and flagged, not blocked, in `observe`, unless an approved task of the full path covers it (which covers everything, as it does today).
  Inside its paths, a short-lane task counts as an approved task, with no message of its own.
- **`task verify` and `task complete`** list and refuse a short-lane task when a file Git tracks has changed outside its paths since the approval (committed or not, and the new files Git does not track yet), or when the profile no longer allows its paths.
- **`guard --ci`** refuses a short-lane record whose `files` leave its paths or the `light_paths` of the base revision (`decision-lane-outside`), the same way it reads the guard mode: a pull request cannot widen the lane it is judged by, or turn the lane on for itself.

## Never in the lane

Whatever the profile and the task say, the lane never covers a change of rules, dependencies or the profile.
Each of these is refused in `light_paths` and in `--paths`, and a file of them stays out of the lane even when a glob that the task names would match it (`docs/**` does not cover `docs/example/package.json`):

- the state of the project: everything under `.openguildkit/` (the profile, the catalog, the decisions);
- CI workflows: `.github/workflows/` and `.github/actions/`;
- the instructions and settings of agents: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `WARP.md`, `AGENTS.override.md` and `CLAUDE.local.md` in any folder, and the files and folders `host scan` reads:
  `.claude/`, `.codex/`, `.cursor/`, `.cursorrules`, `.windsurf/`, `.windsurfrules`, `.clinerules`, `.roo/`, `.kilocode/`, `.junie/`, `.rules`, `.gemini/`, `.mcp.json`, `.vscode/mcp.json`, `.goosehints`, `.opencode/`, `.agents/skills/`, `.github/copilot-instructions.md`, `.github/instructions/`, `.github/prompts/` and `.github/agents/`;
- the dependency manifests and lockfiles, in any folder: `package.json`, `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml`, `pnpm-workspace.yaml`, `bun.lock`, `bun.lockb`, `.npmrc`, `.yarnrc`, `.yarnrc.yml`, `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `uv.lock`, `pdm.lock`, `go.mod`, `go.sum`, `go.work`, `go.work.sum`,
  `Cargo.toml`, `Cargo.lock`, `composer.json`, `composer.lock`, `Gemfile`, `Gemfile.lock`, `pom.xml`, `build.gradle`, `build.gradle.kts`, `settings.gradle`, `settings.gradle.kts`, `gradle.lockfile`, `libs.versions.toml`, `packages.config`, `Directory.Packages.props`, `Directory.Build.props`, `Package.swift`, `Package.resolved`, `mix.exs`, `mix.lock`, `pubspec.yaml`, `pubspec.lock`,
  `deno.json`, `deno.jsonc`, `deno.lock`, `environment.yml`, `conda-lock.yml`, `flake.lock`, `requirements*.txt` and `constraints*.txt`, and any file ending in `.lock`, `.lockb`, `-lock.json`, `-lock.yaml`, `-lock.yml`, `.csproj`, `.fsproj`, `.vbproj` or `.gemspec`.

A change of these goes through the full path.

## What the review must decide

The lane was proposed as an RFC (#422), and these points are open for the pull request that adds it:

- whether the list above is the right one: it stays short on purpose, and says nothing of a `Dockerfile`, of `CODEOWNERS`, of the CI of other systems (`.gitlab-ci.yml`, `Jenkinsfile`) or of the files that generate code;
- whether `surface: other` is the right default: it keeps the closing as heavy as an `unsure` task (the answers of the rules of every surface), where a surface chosen from the paths would ask fewer rules and guess a fact about the change;
- whether the required boards should join the lane (they do: a project that requires `security` gets it on every task, a docs typo included), or whether such a project should refuse the lane;
- whether the lane should be refused outside a Git repository (it is not: there, nothing compares the changed files with the paths, as for the checks the full path makes);
- whether an agent may open a task in the lane by itself: it can, since nothing in `task new` is the person's act, and the lane is declared by a person at the approval, which shows the lane and the paths and seals them; the alternative is to ask for the person's initials at the opening.
