# Testing

The test suite uses `unittest` from the standard library and runs offline. CI runs the standard suite on Linux, macOS and Windows with Python 3.11 through 3.15. A separate job runs the timed performance tests once per operating system on Python 3.14.

```bash
PYTHONPATH=src python -m unittest discover -s tests          # everything, about 5 minutes
PYTHONPATH=src python -m unittest tests.test_robustness      # one kind
PYTHONPATH=src python -m unittest tests.e2e.test_concurrency.LockTests   # one class
```

On Windows, set `PYTHONPATH` with `set PYTHONPATH=src` (cmd) or `$env:PYTHONPATH="src"` (PowerShell), or install the project with `python -m pip install -e .` and drop it.

## Kinds of tests

Times were measured on a laptop (macOS, Python 3.15) on 21 November 2026; the whole suite (245 tests) took 268 s.

| Kind | Where | What it proves | Time |
| --- | --- | --- | --- |
| Unit | `tests/test_*.py` not listed below | Each module's rules: profile validation, routing, reviews, decisions, results, guard, hosts, catalog records and their sources. | about 50 s |
| End to end | `tests/e2e/test_cli_flow.py`, `test_board_passes.py`, `test_catalog_lock.py`, `test_export_ci.py`, `test_host_rehearsal.py` | The CLI in a temporary project, from `init` to the handoff, with the request status example as fixture. Terminal, environment and concurrency tests use real processes. | about 95 s |
| Every command | `tests/e2e/test_more_commands.py`, `tests/test_cli_coverage.py` | `task deliberate`, `respond`, `blockers`, `clear`, `waive`, `storybook compose` and `deliverable list` through the CLI. The coverage test walks the `argparse` tree and fails when a command or a `task` action has no test that invokes it. | 19 s |
| Concurrency | `tests/e2e/test_concurrency.py` | Real processes on one project: six `task pass` at once all succeed; parallel `task new`, `pass` and `submit` lose nothing; a duplicate task ID is refused once without overwrite; readers running during writes always see whole records; a writer waits for the lock, gives up after `OPENGUILDKIT_LOCK_TIMEOUT` with the usual message, and read commands never wait. Two clones each approve and export a task, then merge without conflict. | 22 s |
| Determinism | `tests/test_determinism.py` | Two fresh projects in different folders, under different `PYTHONHASHSEED` values, get byte-identical `AGENTS.md`, `CLAUDE.md`, profile, catalog lock, `catalog --json`, `recommend --json`, `preview --json`, routing, consultation, board pass, decision brief and deliberation request. Only the random consultation ID is replaced before comparing. | 12 s |
| Robustness | `tests/test_robustness.py` | Seeded random and hostile values (wrong types, random Unicode, control characters, 200 000-character strings, 100 000 levels of nesting, removed keys) at each key of setup answers, task answers, reviews, board entries, deliberations, results, the profile, a task record and hook input. No traceback, errors start with `OpenGuildKit:`, task records still load. A small model-based test runs 120 random valid and invalid `task` commands and checks every record against a model of the statuses. | 24 s |
| Performance | `tests/test_performance.py`, `scripts/bench.py` | Time budgets for the commands that run most often, as ratios to the CLI start, so a slow runner does not fail them and a tenfold slowdown does. | 27 s |
| Upgrade | `tests/test_upgrade.py`, `tests/fixtures/upgrade/` | Projects written by v0.1.0 and v0.16.1 themselves (profile, instructions, ignore file, project lock, draft and approved tasks) pass `check`, `update`, `update --apply`, list and show their tasks, and continue a draft through consultation. | 11 s |
| Field kit | `tests/e2e/test_field_kit.py`, `examples/field-tests/` | The campaign file has its thirty testers and every brief is complete; the kit prepares every tester's folder and the teammates' shared repository; two teams that play the scripted part of each of the three scenarios get identical results; a missing report, unusable findings or a difference between teams is named and fails the collection; the person's stand-in approves at a pseudo-terminal. | 28 s |

The Node coordinator in `integrations/ci` has its own suite: `cd integrations/ci && npm test`. `tests/e2e/test_export_ci.py` runs the Python side of the cases it shares with that suite.

## Robustness: seeds and known crashes

The robustness tests use a fixed seed, so a failure names the seed, the command and the mutated key, and reproduces. To explore, set another seed:

```bash
OPENGUILDKIT_FUZZ_SEED=7 PYTHONPATH=src python -m unittest tests.test_robustness
```

Every crash fails the run: none is tolerated. A task record edited by hand is checked once when it is loaded, field by field, and a damaged one is reported as `Task record ID is damaged: FIELD ...` instead of crashing a later command. The suite passes with the default seed and with seeds 1, 2 and 3 (`OPENGUILDKIT_FUZZ_SEED=N`).

## Performance numbers

Run the timed tests with `OPENGUILDKIT_PERF=1 PYTHONPATH=src python -m unittest tests.test_performance.PerformanceTests`. On Windows PowerShell, set `$env:OPENGUILDKIT_PERF = "1"` before running the test command.

On 22 November 2026 (Windows, Python 3.12.7, with `PYTHONDONTWRITEBYTECODE=1` in the calling environment), the 26 tests in `tests.e2e.test_cli_flow` ran in 9.316 s, down from 50.281 s at `ac33f9f`. Both runs skipped the two POSIX terminal cases. These are single runs of that module on the Windows workstation.

`python scripts/bench.py` prints the times as a table and as JSON (`--json` for JSON only, `--repeat N` for more runs). Each command is a real process; the figure is the median of five runs after one warm-up. "x start" divides by `openguildkit --version` in the same run. The project with 500 tasks has 5 approved ones, so the hooks find tasks that cover the edit. Python caches the bytecode in the benchmark's temporary folder, as it does for an installed package, even when `PYTHONDONTWRITEBYTECODE` is set.

Measured on 21 November 2026 on a laptop (macOS 26, Python 3.15) that was running other test suites at the same time, three runs of the script before and three after the changes of #135, with the same script. The load average was about 4.5 during the runs before and about 8 during the runs after, so the gains are, if anything, understated. Each figure is the median of the three runs; the last column gives the lowest and highest ratio over the three runs after.

| Command | Before (s) | After (s) | x start, after |
| --- | --- | --- | --- |
| `python -c pass` | 0.024 | 0.025 | 0.2 |
| `openguildkit --version` | 0.102 | 0.122 | 1.0 |
| `catalog --json` | 0.462 | 0.176 | 1.4 to 1.5 |
| `init` | 0.525 | 0.196 | 1.6 |
| `task consult` | 0.725 | 0.298 | 2.4 to 2.5 |
| `task list`, 500 tasks | 1.003 | 0.439 | 3.4 to 3.8 |
| `references security` | 0.510 | 0.206 | 1.6 to 1.7 |
| `guard --hook pre-edit`, 500 tasks | 0.951 | 0.182 | 1.4 to 1.5 |
| `guard --hook prompt`, 500 tasks | 0.964 | 0.182 | 1.4 to 1.6 |
| `detect`, monorepo of 200 packages | 0.604 | 0.324 | 2.4 to 3.4 |
| `init`, monorepo of 200 packages | 0.836 | 0.356 | 2.7 to 3.3 |

Each budget in `tests/test_performance.py` is at least three times the highest ratio seen, so load on the machine passes, and at most ten times the lowest, so a tenfold slowdown fails. The edit hook's budget (5) also fails if the hook reads every task record again (8 to 9.5 times the start before #135). A run over budget is measured once more before the test fails. `--version` itself must stay under 25 times a bare `python -c pass`.

Where the time went, and what changed:

- Every command validated the bundled catalog twice, and `init`, `sync`, `check` and `task decide` four times, at about 50 ms each (more under load), most of it checking each character of each text for control characters. The bundled records are now validated once per process (they ship with the code that runs, so they cannot change during a command; project records are read again on every load), and text that `str.isprintable()` accepts skips the character-by-character check, which gives the same answer. `tests/test_performance.py` counts the reads per command.
- `guard --hook pre-edit` and `--hook prompt` parsed every task record to find the approved ones. A status index in `.openguildkit/tasks/.status-index` (git-ignored and refused to agent edits like the records) now says which records cannot cover an edit; each entry holds the record file's size, times and inode, and is used only while the file still matches, so a record changed by any means is read again. The index only skips records: approved tasks are read and checked in full, and a missing, stale, corrupt or unwritable index costs time, not a decision (`tests/test_task_index.py`, and a concurrency test with hooks and writers at once).
- `--version` no longer reads the package metadata for every command, and the catalog, the tool registry, references, deliverables and agent files are found next to the package instead of through `importlib.resources`, whose import cost every command about 14 ms.

What is left: a command that needs the catalog still reads its 223 bundled files, about 40 ms on this laptop, and validates them, so the edit hook takes the start time plus about 60 ms. That is 0.18 s at the load of these runs and 0.17 s at a load average of 5.5, above the 0.15 s that #135 aimed for; reading fewer catalog files would need a catalog cache shared between processes, which this change does not add. Importing the CLI takes about 45 ms with cached bytecode: `argparse` on Python 3.15 alone takes 5 ms and imports `shutil`, and the `tools`, `market`, `alerts` and `storybook` modules are imported to build their sub-commands. In a Git repository, each approved task also runs `git merge-base` to check that its approved revision is still in the history.

## Field campaigns

The tests above check what the code does. A field campaign checks what a team lives through: thirty autonomous agents each play a team that adopts OpenGuildKit with the documentation as their only help, on mocks, and report where they got stuck. The kit, the thirty testers, the three scenarios played by several teams and each campaign's dated report are in [`examples/field-tests/`](../examples/field-tests/README.md). The first campaign, on 21 November 2026, produced 341 findings grouped into 97 problems and the issues #149 to #180; its report is [`examples/field-tests/reports/2026-11-21.md`](../examples/field-tests/reports/2026-11-21.md).

A campaign is run by a person with an agent host, not by CI. What CI runs is the part that needs no agent: `python examples/field-tests/field.py cohorts --out DIR` plays the scripted part of each scenario in several folders and fails when two of them differ.

## Rehearse the person's acts

Approving, waiving and clearing a blocker need a person at a terminal, so an agent cannot do them. The tests drive them through a pseudo-terminal, on Linux and macOS:

- `python -m unittest tests.e2e.test_more_commands.WaiverCommandTests` repeats the waiver flow in a temporary project: an unauthorized person and a wrong confirmation are refused, then a valid waiver is recorded. A waiver needs a policy in the profile, `"waivers": {"allowed_by": ["CM"], "max_days": 30}`, and `task waive` needs `--by` (a name in `allowed_by`), `--reason`, `--scope` (what the waiver covers) and `--until` (YYYY-MM-DD, at most `max_days` ahead).
- `python -m unittest tests.e2e.test_more_commands.BlockerCommandTests` repeats clearing: refused without a terminal, cancelled by a wrong confirmation, recorded with the person's name, and a second clearing refused; in a project with signed approvals, the clearance is signed with a synthetic key.
- `python examples/host-validation/rehearse.py --project FOLDER` replays a whole task, the person's steps included.

In a test written with `unittest`, patch `sys.stdin.isatty` to return true and `builtins.input` to return the typed task ID, as `tests/test_decision_brief.py` does.

## Not covered

- Windows behaviour is covered by CI only: the lock on Windows (`msvcrt.locking`) has not been run by hand, and the approval, waiver and authorization prompts are tested through a pseudo-terminal on Linux and macOS only.
- The concurrency tests run on one machine. A project on a network file system, where file locks may not hold, is not tested.
- No test runs an agent host (Claude Code, Codex) for real; host settings and hooks are tested through the files they read and the input they send.
- The robustness tests do not cover `.claude/settings.json`, `.codex/hooks.json`, market dossiers or the share register, whose known crashes are listed in #99.
- Performance is measured with up to 500 tasks and 200 packages, not with a project's full history over years.
- Upgrade fixtures cover the first and the last release before the catalog lock; releases in between are not kept.
