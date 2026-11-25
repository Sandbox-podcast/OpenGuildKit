# Testing

The test suite uses `unittest` from the standard library and runs offline. CI runs the standard suite on Linux, macOS and Windows with Python 3.11 and 3.15 (hosted macOS runners are scarce: [CONTRIBUTING.md](../CONTRIBUTING.md#open-a-pull-request) says what to do when one never comes). A separate job runs the timed performance tests once per operating system on Python 3.15. A published release is checked by `.github/workflows/release-check.yml`, not on each pull request: it installs the files attached to the release on Linux, macOS and Windows and upgrades a v0.16.1 project to it ([GOVERNANCE.md](../GOVERNANCE.md#releases), step 7).

```bash
PYTHONPATH=src python -m unittest discover -s tests          # everything, under 5 minutes
PYTHONPATH=src python -m unittest tests.test_robustness      # one kind
PYTHONPATH=src python -m unittest tests.e2e.test_concurrency.LockTests   # one class
```

On Windows, set `PYTHONPATH` with `set PYTHONPATH=src` (cmd) or `$env:PYTHONPATH="src"` (PowerShell), or install the project with `python -m pip install -e .` and drop it.

## How the suite runs the CLI

`tests/support.py` runs the CLI for every test. `run_cli` calls `main()` in the test process and returns the exit code and what the command printed, a few tens of milliseconds a command against some 350 ms for a new `python -m openguildkit` process; `CapturedCli` gives a test case `self.run_cli(...)` on its `self.root`, and `copy_initialized_project` sets up a project once per class and gives each test its own copy. `tests/test_test_suite.py` fails when more than ten helpers of `tests/` run the CLI themselves instead.

A test starts a real process only when it needs one: the person typing at a pseudo-terminal (`CliTestCase.in_terminal`, which captures what the command shows), parallel writers and readers (`tests/e2e/test_concurrency.py`), a hash seed (`tests/test_determinism.py`, one process per seed), the stdio of a tool mock, the `openguildkit ui` server. `CatalogTests` in `tests/e2e/test_cli_flow.py` keeps `subprocess_mode = True`, so the `python -m openguildkit` entry point stays tested end to end. The example scripts of the field kit, the host rehearsal and the Documentalist replay run their commands through one `run()` function, which their tests replace with the in-process runner.

Child processes get `support.subprocess_environment()`: without `PYTHONDONTWRITEBYTECODE`, which made each of them compile the package again, and with `PYTHONPYCACHEPREFIX` in a temporary folder, so the bytecode stays out of the repository.

Git reads no configuration of the machine during the tests. `tests/__init__.py` sets `GIT_CONFIG_GLOBAL` to the null device, `GIT_CONFIG_NOSYSTEM=1` and a test identity for the whole run, so a contributor's commit signing, hooks or name never reach a commit a test makes, and a test needs no `-c user.name=...` of its own. `tests/test_test_suite.py` commits under a global configuration that signs with a key that does not exist.

## Kinds of tests

On 22 November 2026, on a laptop (Apple M1 Pro, macOS 26, Python 3.15.2) whose other applications kept the load average between 3.8 and 6.6: 1 218 tests in 279 s, 3 skipped (the time budgets); the one failure of that run, `test_a_component_path_with_spaces_works_in_the_check_shell`, needs a `python` command, which this laptop does not have. On the same laptop and the same day, the suite took 636 s for 1 198 tests before #252, and 431 s for 1 202 tests after it. A matrix job on GitHub Actions was not timed for this commit. Each time below is the sum of its tests in an earlier run with `--durations 0` on the same laptop and the same day (1 205 tests in 283 s, before the last commits of #252's branch).

| Kind | Where | What it proves | Time |
| --- | --- | --- | --- |
| Setup and profile | `test_core.py`, `test_setup_questionnaire.py`, `test_setup_minor.py`, `test_proportionate_setup.py`, `test_sectors.py`, `test_first_run.py`, `test_detect_versions.py`, `test_project_walk.py`, `test_project_checks.py`, `test_stack_patterns.py`, `test_patterns.py`, `test_components.py`, `test_profile_commands.py`, `test_monorepo_instructions.py`, `test_instruction_files.py`, `test_rule_plan.py`, `test_storage.py`, `test_clock.py`, `test_terminal.py`, `test_task_index.py` | `init` in a terminal and from answers, detection, sectors and norms a person confirms, the managed block of `AGENTS.md`, profile changes with who and why, atomic writes and the lock, the two clocks, the status index of the edit hook. | 15 s |
| Catalog and brains | `test_catalog_sources.py`, `test_source_dates.py`, `test_catalog_format_doc.py`, `test_pack_rules.py`, `test_regulatory_packs.py`, `test_recorded_values.py`, `test_rule_checks.py`, `test_machine_checks.py`, `test_brains.py`, `test_brain_knowledge.py`, `test_brain_selection.py`, `test_new_brains.py`, `test_lenses_and_methods.py`, `test_references.py`, `test_routing.py`, `test_coverage.py`, `test_chaosfolk.py`, `test_edition_watch.py`, `test_check_links.py`, `test_first_contribution.py`, `test_upgrades.py` | Every record and source of the bundled catalog, the regulation packs, machine checks, each brain's lenses and knowledge, routing on a corpus of French and English briefs, the link check and the edition watch without network, a catalog that stops shipping a record. | 12 s |
| Tasks, reviews and decisions | `test_questions.py`, `test_relevance.py`, `test_pass_relevance.py`, `test_board_entries.py`, `test_deliberation.py`, `test_blockers.py`, `test_blocker_clearances.py`, `test_decision_brief.py`, `test_decision_text.py`, `test_decisions.py`, `test_decided_tasks.py`, `test_approval_lifecycle.py`, `test_brief_revision.py`, `test_rule_changes.py`, `test_results.py`, `test_closing_points.py`, `test_chaosfolk_results.py`, `test_task_list.py`, `test_task_weight.py`, `test_output_size.py`, `test_next_steps.py`, `test_clean_errors.py`, `test_sensitive.py`, `test_audit_fixes.py`, `test_record_integrity.py`, `test_record_lifecycle.py`, `test_team_sharing.py` | The task from its questions to its closing: the rules that concern it, board entries and their evidence, deliberation, blockers, the decision brief, sealed and signed approvals (a departed approver included), rule changes, results, exported records as teammates and CI read them, clean errors, credentials and personal data in inputs. | 92 s |
| Guard and hosts | `test_guard.py`, `test_hosts.py`, `test_host_research.py`, `test_hook_examples.py`, `test_written_host_controls.py`, `test_other_host.py`, `test_integrations.py`, `test_agent_instructions.py` | `guard` in the edit hook and `guard --ci`, the settings, hooks and deny rules `host apply` writes, run as written through the shell, the installed skill and subagents. | 24 s |
| Project MCP | `test_project_mcp.py` | A stdio client compares rule, task and check metadata with the CLI, checks the read-only surface, and verifies that error responses keep local details private, a profile or catalog file linked outside `.openguildkit` included. | 3 s |
| Tools and MCP mocks | `test_tools.py`, `test_tool_registry.py`, `test_features.py`, `tests/e2e/test_tool_mocks.py` | The tool registry, the features and their options, the connection plans for each host, and the mocks: an MCP client talks to each over stdio (handshake revisions, every tool), a project connects them, and the bundled demo plays an agent against them. | 7 s |
| Storybook | `test_storybook.py`, `test_storybook_extract.py` | Composition, recorded indexes, the extraction of a design system from a React application, without npm or network. | 2 s |
| Market and alerts | `test_market.py`, `test_alerts.py`, `test_alert_resolution.py`, `test_dependency_watch.py` | Market dossiers, their checks and watch; the alert register from scanner reports, reviews and resolutions; the scheduled dependency watch, its read-only scan and its pull request under the guard. | 8 s |
| Deliverables and documentation | `test_deliverables.py`, `test_publishing.py`, `test_portal_verification.py`, `tests/e2e/test_campaign_links.py` | Business deliverables, campaign links, the Documentalist export (the example replayed to its committed site), the share register and its comparison with a local stand-in for Documentalist's reader settings. | 22 s |
| Web interface | `test_webui.py`, `test_sample_project.py`; in `web/`: `npm test`, `npm run e2e`, `npm run e2e:project` | `test_webui.py`: the local server (host, origin, token, the acts left to a terminal, paths, uploads, concurrency, compression), on Linux, macOS and Windows with the rest of the suite. `test_sample_project.py`: `web/scripts/sample-project.py` prints its usage for `--help` and builds nothing for an argument that starts with a dash. `npm test` (Vitest): the demo's domain rules, the real mode's client and labels, the packaging script; Linux in CI. `npm run e2e` (Playwright, Chrome): the demo's journeys. `npm run e2e:project`: one journey per action of `openguildkit ui` on fresh sample projects, and two sweeps of every route with axe-core (desktop RPG, mobile Pro); both on Linux in CI (`web-e2e`). | 6 s (Python only) |
| End to end | `tests/e2e/test_cli_flow.py`, `test_board_passes.py`, `test_catalog_lock.py`, `test_export_ci.py`, `test_host_rehearsal.py` | The CLI on a temporary project, from `init` to the handoff, with the request status example as fixture; `CatalogTests` through `python -m openguildkit`, the approval through a pseudo-terminal. | 31 s |
| Every command | `tests/e2e/test_more_commands.py`, `tests/test_cli_coverage.py` | `task deliberate`, `respond`, `blockers`, `clear`, `waive`, `storybook compose` and `deliverable list` through the CLI. The coverage test walks the `argparse` tree and fails when a command, a group's action or a mode its positional argument selects (`market resume`, `host apply`, `docs share verify`) has no test that invokes it. | 11 s |
| Concurrency | `tests/e2e/test_concurrency.py` | Real processes on one project: six `task pass` at once all succeed; parallel `task new`, `pass` and `submit` lose nothing; a duplicate task ID is refused once without overwrite; readers running during writes always see whole records; a writer waits for the lock, gives up after `OPENGUILDKIT_LOCK_TIMEOUT` with the usual message, and read commands never wait. Two clones each approve and export a task, then merge without conflict. | 13 s |
| Determinism | `tests/test_determinism.py` | Two fresh projects in different folders, each played in a process with its own `PYTHONHASHSEED`, get byte-identical `AGENTS.md`, `CLAUDE.md`, profile, catalog lock, `catalog --json`, `recommend --json`, `preview --json`, routing, consultation, board pass, decision brief and deliberation request. Only the random consultation ID is replaced before comparing. | 4 s |
| Robustness | `tests/test_robustness.py` | Seeded random and hostile values (wrong types, random Unicode, control characters, 200 000-character strings, 100 000 levels of nesting, removed keys) at each key of setup answers, task answers, reviews, board entries, deliberations, results, the profile, a task record and hook input. No traceback, errors start with `OpenGuildKit:`, task records still load. A small model-based test runs 120 random valid and invalid `task` commands and checks every record against a model of the statuses. | 21 s |
| Performance | `tests/test_performance.py`, `scripts/bench.py` | Time budgets for the commands that run most often, as ratios to the CLI start, so a slow runner does not fail them and a tenfold slowdown does; skipped unless `OPENGUILDKIT_PERF=1`, which the CI `performance` job sets once per system. The catalog reads per command and the start without the CLI run every time. | 2 s without the budgets; about 60 s with them |
| Upgrade | `tests/test_upgrade.py`, `tests/fixtures/upgrade/` | Projects written by v0.1.0 and v0.16.1 themselves (profile, instructions, ignore file, project lock, draft and approved tasks) pass `check`, `update`, `update --apply`, list and show their tasks, and continue a draft through consultation. | 1 s |
| Field kit | `tests/e2e/test_field_kit.py`, `examples/field-tests/` | The campaign file has its thirty testers and every brief is complete; the kit prepares every tester's folder and the teammates' shared repository; two teams that play the scripted part of each of the three scenarios get identical results; a missing report, unusable findings or a difference between teams is named and fails the collection; the person's stand-in approves at a pseudo-terminal. | 10 s |
| The repository itself | `test_architecture.py`, `test_dead_code.py`, `test_python_floor.py`, `test_release.py`, `test_workflows.py`, `test_entry_pages.py`, `test_personal_data_doc.py`, `test_product_docs.py`, `test_test_suite.py`, `test_doc_promises.py`, `test_doc_examples.py`, `test_agent_native.py` | Module and function sizes, no dead code, Python 3.11 syntax, one version everywhere and the wheel as CI builds it, pinned workflow actions, a time limit on every job of the workflows and shipped templates, a label for every tracked file outside the root, the jobs CI puts on macOS and how its gate names a job no runner picked up, READMEs and pages that follow the code (every module in [architecture](architecture.md), every test file in this table), one way to run the CLI in tests, boundaries the pages promise (the last day of a share, the observed finding high confidence needs, the 180 days of a market observation), and examples of the pages run as written (each `openguildkit references` search finds something; `tools scenario` after `tools apply --mock`). | 9 s |

The Node coordinator in `integrations/ci` has its own suite: `cd integrations/ci && npm test`. `tests/e2e/test_export_ci.py` runs the Python side of the cases it shares with that suite.

## Robustness: seeds and known crashes

The robustness tests use a fixed seed, so a failure names the seed, the command and the mutated key, and reproduces. To explore, set another seed:

```bash
OPENGUILDKIT_FUZZ_SEED=7 PYTHONPATH=src python -m unittest tests.test_robustness
```

Every crash fails the run: none is tolerated. A task record edited by hand is checked once when it is loaded, field by field, and a damaged one is reported as `Task record ID is damaged: FIELD ...` instead of crashing a later command. The suite passes with the default seed and with seeds 1, 2 and 3 (`OPENGUILDKIT_FUZZ_SEED=N`).

## Performance numbers

Run the timed tests with `OPENGUILDKIT_PERF=1 PYTHONPATH=src python -m unittest tests.test_performance.PerformanceTests`. On Windows PowerShell, set `$env:OPENGUILDKIT_PERF = "1"` before running the test command.

One test reads the network: `RegistryPackagesExistTests` in `tests/test_tool_registry.py` checks that every Docker image and npm or PyPI package of the tool registry exists. It is skipped unless `OPENGUILDKIT_NETWORK_TESTS=1`, and CI does not set it.

On 22 November 2026 (Windows, Python 3.12.7, with `PYTHONDONTWRITEBYTECODE=1` in the calling environment), the 26 tests in `tests.e2e.test_cli_flow` ran in 9.316 s, down from 50.281 s at `ac33f9f`. Both runs skipped the two POSIX terminal cases. These are single runs of that module on the Windows workstation. The full standard Windows run took 404.551 s for 1,198 tests, with 30 skipped. The full-suite time on the reference macOS machine is under [Kinds of tests](#kinds-of-tests).

`python scripts/bench.py` prints the times as a table and as JSON (`--json` for JSON only, `--repeat N` for more runs). Each command is a real process; the figure is the median of five runs after one warm-up. "x start" divides by `openguildkit --version` in the same run. The project with 500 tasks has 5 approved ones, so the hooks find tasks that cover the edit. Python caches the bytecode in the benchmark's temporary folder, as it does for an installed package, even when `PYTHONDONTWRITEBYTECODE` is set.

Measured on 22 November 2026 on the laptop of the suite timing above (Apple M1 Pro, macOS 26, Python 3.15.2), at a load average of 4 to 5.5 from other applications: two runs of the script after the web interface was added to the CLI (#199) and the CLI split into modules (issue 31 of the second audit). Each figure is the median of a run's five measures; the columns give the lowest and the highest of the two runs. The column of 21 November is the table of #135, at a load average of about 8.

| Command | 21 November (s) | 22 November (s) | x start, 22 November |
| --- | --- | --- | --- |
| `python -c pass` | 0.025 | 0.024 | 0.2 |
| `openguildkit --version` | 0.122 | 0.103 to 0.106 | 1.0 |
| `catalog --json` | 0.176 | 0.237 to 0.248 | 2.3 |
| `init` | 0.196 | 0.266 to 0.293 | 2.6 to 2.8 |
| `task consult` | 0.298 | 0.323 to 0.342 | 3.1 to 3.2 |
| `task list`, 500 tasks | 0.439 | 0.768 to 0.926 | 7.5 to 8.8 |
| `check`, 500 tasks | | 0.959 to 1.145 | 9.4 to 10.8 |
| `references security` | 0.206 | 0.338 to 0.386 | 3.3 to 3.7 |
| `guard --hook pre-edit`, 500 tasks | 0.182 | 0.292 to 0.341 | 2.8 to 3.2 |
| `guard --hook pre-edit`, guard off | | 0.074 to 0.078 | 0.7 |
| `guard --hook prompt`, 500 tasks | 0.182 | 0.300 to 0.318 | 2.9 to 3.0 |
| `detect`, monorepo of 200 packages | 0.324 | 0.290 to 0.297 | 2.8 |
| `init`, monorepo of 200 packages | 0.356 | 0.398 to 0.409 | 3.9 |

Every command that reads the catalog is 60 to 150 ms slower than on 21 November, the edit hook included (0.29 to 0.34 s against 0.18), and `task list` on 500 tasks nearly doubled; `--version` and `detect`, which do not read the catalog, did not move. The ratios stay inside the budgets. This page measures the difference; it does not explain it.

Each budget in `tests/test_performance.py` is at least three times the highest ratio seen, so load on the machine passes, and at most ten times the lowest, so a tenfold slowdown fails. The edit hook's budget (5) also fails if the hook reads every task record again (8 to 9.5 times the start before #135). A run over budget is measured once more before the test fails. `--version` itself must stay under 25 times a bare `python -c pass`.

Where the time went in #135, and what changed:

- Every command validated the bundled catalog twice, and `init`, `sync`, `check` and `task decide` four times, at about 50 ms each (more under load), most of it checking each character of each text for control characters. The bundled records are now validated once per process (they ship with the code that runs, so they cannot change during a command; project records are read again on every load), and text that `str.isprintable()` accepts skips the character-by-character check, which gives the same answer. `tests/test_performance.py` counts the reads per command.
- `guard --hook pre-edit` and `--hook prompt` parsed every task record to find the approved ones. A status index in `.openguildkit/tasks/.status-index` (git-ignored and refused to agent edits like the records) now says which records cannot cover an edit; each entry holds the record file's size, times and inode, and is used only while the file still matches, so a record changed by any means is read again. The index only skips records: approved tasks are read and checked in full, and a missing, stale, corrupt or unwritable index costs time, not a decision (`tests/test_task_index.py`, and a concurrency test with hooks and writers at once).
- `--version` no longer reads the package metadata for every command, and the catalog, the tool registry, references, deliverables and agent files are found next to the package instead of through `importlib.resources`, whose import cost every command about 14 ms.

What is left: a command that needs the catalog still reads its 223 bundled files, about 40 ms on this laptop, and validates them, so the edit hook takes the start time plus about 60 ms. That was 0.18 s on 21 November, above the 0.15 s that #135 aimed for, and 0.29 to 0.34 s on 22 November; reading fewer catalog files would need a catalog cache shared between processes, which this change does not add. Importing the CLI takes about 53 ms with cached bytecode (22 November 2026, `python -X importtime`): `argparse` on Python 3.15 alone takes 5 ms and imports `shutil`, and the `tools`, `market`, `alerts` and `storybook` modules are imported to build their sub-commands. In a Git repository, each approved task also runs `git merge-base` to check that its approved revision is still in the history.

## Field campaigns

The tests above check what the code does. A field campaign checks what a team lives through: thirty autonomous agents each play a team that adopts OpenGuildKit with the documentation as their only help, on mocks, and report where they got stuck. The kit, the thirty testers, the three scenarios played by several teams and each campaign's dated report are in [`examples/field-tests/`](../examples/field-tests/README.md). The first campaign, on 21 November 2026, produced 341 findings grouped into 97 problems and the issues #149 to #180; its report is [`examples/field-tests/reports/2026-11-21.md`](../examples/field-tests/reports/2026-11-21.md).

A campaign is run by a person with an agent host, not by CI. What CI runs is the part that needs no agent: `python examples/field-tests/field.py cohorts --out DIR` plays the scripted part of each scenario in several folders and fails when two of them differ.

## Rehearse the person's acts

Approving, waiving and clearing a blocker need a person at a terminal, so an agent cannot do them. The tests drive them through a pseudo-terminal, on Linux and macOS:

- `python -m unittest tests.e2e.test_more_commands.WaiverCommandTests` repeats the waiver flow in a temporary project: an unauthorized person and a wrong confirmation are refused, then a valid waiver is recorded. A waiver needs a policy in the profile, `"waivers": {"allowed_by": ["CM"], "max_days": 30}`, and `task waive` needs `--by` (a name in `allowed_by`), `--reason`, `--scope` (what the waiver covers) and `--until` (YYYY-MM-DD, at most `max_days` ahead).
- `python -m unittest tests.e2e.test_more_commands.BlockerCommandTests` repeats clearing: refused without a terminal, cancelled by a wrong confirmation, recorded with the person's name, and a second clearing refused; in a project with signed approvals, the clearance is signed with a synthetic key.
- `python examples/host-validation/rehearse.py --project FOLDER` replays a whole task, the person's steps included.

In a test written with `unittest`, patch `sys.stdin.isatty` to return true and `builtins.input` to return the typed task ID, as `tests/test_decision_brief.py` does.

## A fast check of what changed

`python scripts/check_fast.py` (optional `--base REF`, default `origin/main`) runs the tests that [docs/agents/map.json](agents/map.json) attaches to files changed since that revision, including the working tree. A changed test runs itself. A change under `src/openguildkit/registry/` validates the catalog. A change under `web/` runs `npm run typecheck`. A changed file with no attached test is named and the command exits non-zero. This does not replace `python -m unittest discover -s tests`. A single-module run is meant to stay under 30 seconds on the reference machine named under [Kinds of tests](#kinds-of-tests). This page does not record a time for that script on that machine.

## What a local transcript cost

`python scripts/agent_cost.py TRANSCRIPT.jsonl` reads one Claude Code transcript on disk and prints totals only: input, cache and output tokens, turns, subagents, command wait, and a cost from the rates named in the script. It prints no prompt and no tool result. It does not measure a live session and it sends nothing.

## Not covered

- Windows behaviour is covered by CI only: the lock on Windows (`msvcrt.locking`) has not been run by hand, and the approval, waiver and authorization prompts are tested through a pseudo-terminal on Linux and macOS only.
- The concurrency tests run on one machine. A project on a network file system, where file locks may not hold, is not tested.
- No test runs an agent host (Claude Code, Codex) for real; host settings and hooks are tested through the files they read and the input they send.
- The robustness tests do not cover `.claude/settings.json`, `.codex/hooks.json`, market dossiers or the share register, whose known crashes are listed in #99.
- Performance is measured with up to 500 tasks and 200 packages, not with a project's full history over years.
- Upgrade fixtures cover the first and the last release before the catalog lock; releases in between are not kept.
