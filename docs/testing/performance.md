# Performance numbers

For: a developer who runs the timed tests or changes a timed path.
A part of the [testing guide](../testing.md).

Run the timed tests with `OPENGUILDKIT_PERF=1 PYTHONPATH=src python -m unittest tests.test_performance.PerformanceTests`.
On Windows PowerShell, set `$env:OPENGUILDKIT_PERF = "1"` before running the test command.

One test reads the network: `RegistryPackagesExistTests` in `tests/test_tool_registry.py` checks that every Docker image and npm or PyPI package of the tool registry exists.
It is skipped unless `OPENGUILDKIT_NETWORK_TESTS=1`, and CI does not set it.

On 22 November 2026 (Windows, Python 3.12.7, with `PYTHONDONTWRITEBYTECODE=1` in the calling environment), the 26 tests in `tests.e2e.test_cli_flow` ran in 9.316 s, down from 50.281 s at `ac33f9f`.
Both runs skipped the two POSIX terminal cases.
These are single runs of that module on the Windows workstation.
The full standard Windows run took 404.551 s for 1,198 tests, with 30 skipped.
The full-suite time on the reference macOS machine is under [Kinds of tests](../testing.md#kinds-of-tests).

`python scripts/bench.py` prints the times as a table and as JSON (`--json` for JSON only, `--repeat N` for more runs).
Each command is a real process; the figure is the median of five runs after one warm-up.
"x start" divides by `openguildkit --version` in the same run.
The project with 500 tasks has 5 approved ones, so the hooks find tasks that cover the edit.
The `guard --ci` scenario checks a change of one file and its record against a base revision that holds 200 decision records: 5.07 s at `3975a41`, which started one `git show` per record, and 0.46 to 0.51 s (x start 3.0 to 4.1) with one `git cat-file --batch` (#532, 27 November 2026, Apple M1 Pro, load average 11 to 38).
Python caches the bytecode in the benchmark's temporary folder, as it does for an installed package, even when `PYTHONDONTWRITEBYTECODE` is set.
The project of 500 closed tasks holds the records the normal path leaves: one task taken the whole way, then copies of it under other IDs, each sealed for its ID and exported (#534).

The budgets of `tests/test_performance.py` come from the table below (#538): two runs of `python scripts/bench.py --repeat 5 --dependencies 500` on 28 November 2026 (Apple M1 Pro, Python 3.15.2, load average 10 to 15 from other agents, bundled catalog read from its record files), each figure the median of a run's five measures, low to high.
Each budget is about 2.5 times the highest ratio and at most three times it, so a command twice as slow fails, where the earlier budgets let the start grow fourfold; a run over budget is measured once more before the test fails.
The edit hook is held to "x python", its time over a bare interpreter start, so that a slower `--version` does not loosen it, and `--version` itself to 4 times a bare start.
`BudgetTableTests` checks the budgets against this table without a clock.
The project of closed tasks also holds one reviewed task, whose decision brief (`task challenge`) reads only the record of the last approval (#535), and the hook runs with the payloads of Claude Code, Codex and Gemini CLI.
The git processes of `guard --ci` and the record reads of the commands on closed tasks are counted without a clock in `tests/test_guard.py` and `tests/test_performance.py`.

| Command | median s | x start | x python |
| --- | --- | --- | --- |
| `python -c pass` | 0.023 to 0.025 | 0.6 to 0.7 | 1.0 to 1.0 |
| `start (--version)` | 0.033 to 0.036 | 1.0 to 1.0 | 1.4 to 1.6 |
| `catalog --json` | 0.211 to 0.406 | 5.8 to 12.3 | 9.3 to 16.6 |
| `init` | 0.251 to 0.297 | 7.6 to 8.2 | 10.2 to 13.0 |
| `task consult` | 0.268 to 0.374 | 7.4 to 11.3 | 11.7 to 15.2 |
| `task consult, bug, 5000 source files` | 0.495 to 0.523 | 14.5 to 14.9 | 20.2 to 22.9 |
| `task list (500 tasks)` | 0.811 to 0.824 | 22.8 to 24.5 | 33.0 to 36.1 |
| `check (500 tasks)` | 0.826 to 0.866 | 22.8 to 26.1 | 35.3 to 36.2 |
| `task list (500 closed tasks)` | 0.228 to 0.241 | 6.3 to 7.3 | 9.8 to 10.0 |
| `check (500 closed tasks)` | 1.693 to 1.724 | 47.6 to 51.1 | 69.0 to 75.6 |
| `task challenge (500 closed tasks)` | 0.280 to 0.307 | 8.5 to 8.5 | 11.4 to 13.5 |
| `references search` | 0.262 to 0.290 | 7.3 to 8.8 | 11.5 to 11.8 |
| `guard --hook pre-edit (500 tasks)` | 0.245 to 0.249 | 6.8 to 7.5 | 10.1 to 10.7 |
| `guard --hook pre-edit, Codex (500 tasks)` | 0.176 to 0.215 | 4.9 to 6.5 | 7.7 to 8.8 |
| `guard --hook pre-edit, Gemini CLI (500 tasks)` | 0.175 to 0.229 | 4.8 to 6.9 | 7.7 to 9.3 |
| `guard --hook pre-edit (Git, 5 approvals)` | 0.246 to 0.252 | 7.0 to 7.4 | 10.0 to 11.1 |
| `guard --hook pre-edit, guard off` | 0.035 to 0.038 | 1.0 to 1.1 | 1.5 to 1.5 |
| `guard --hook prompt (500 tasks)` | 0.239 to 0.246 | 6.8 to 7.2 | 9.7 to 10.8 |
| `detect (monorepo, 200 packages)` | 0.253 to 0.282 | 7.6 to 7.8 | 10.3 to 12.4 |
| `init (monorepo, 200 packages)` | 0.300 to 0.331 | 8.3 to 10.0 | 13.2 to 13.5 |
| `guard --ci (200 records on the base)` | 0.510 to 0.515 | 14.2 to 15.4 | 20.8 to 22.6 |
| `projects --surfaces (30 projects)` | 1.419 to 1.499 | 39.2 to 45.2 | 61.0 to 62.2 |

Measured on 22 November 2026 on the laptop of the suite timing above (Apple M1 Pro, macOS 26, Python 3.15.2), at a load average of 4 to 5.5 from other applications: two runs of the script after the web interface was added to the CLI (#199) and the CLI split into modules (issue 31 of the second audit).
Each figure is the median of a run's five measures; the columns give the lowest and the highest of the two runs.
The column of 21 November is the table of #135, at a load average of about 8.

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

Every command that reads the catalog is 60 to 150 ms slower than on 21 November, the edit hook included (0.29 to 0.34 s against 0.18), and `task list` on 500 tasks nearly doubled; `--version` and `detect`, which do not read the catalog, did not move.
The ratios stay inside the budgets.
This page measures the difference; it does not explain it.

Until 28 November 2026, each budget was at least three times the highest ratio seen and at most ten times the lowest, so only a tenfold slowdown failed, and `--version` could take 25 times a bare `python -c pass`; the budgets now follow the table of 28 November above (#538).

Where the time went in #135, and what changed:

- Every command validated the bundled catalog twice, and `init`, `sync`, `check` and `task decide` four times, at about 50 ms each (more under load), most of it checking each character of each text for control characters.
  The bundled records are now validated once per process (they ship with the code that runs, so they cannot change during a command; project records are read again on every load), and text that `str.isprintable()` accepts skips the character-by-character check, which gives the same answer.
  `tests/test_performance.py` counts the reads per command.
- `guard --hook pre-edit` and `--hook prompt` parsed every task record to find the approved ones.
  A status index in `.openguildkit/tasks/.status-index` (git-ignored and refused to agent edits like the records) now says which records cannot cover an edit; each entry holds the record file's size, times and inode, and is used only while the file still matches, so a record changed by any means is read again.
  The index only skips records: approved tasks are read and checked in full, and a missing, stale, corrupt or unwritable index costs time, not a decision (`tests/test_task_index.py`, and a concurrency test with hooks and writers at once).
- `--version` no longer reads the package metadata for every command, and the catalog, the tool registry, references, deliverables and agent files are found next to the package instead of through `importlib.resources`, whose import cost every command about 14 ms.

What is left: an installed wheel reads its packs, boards, sectors and patterns from one file, `registry/catalog.bundle.json`, which `scripts/build_catalog_bundle.py` validates and writes before the build (#533): `load_catalog()` takes 8 ms in a new process instead of 91 (27 November 2026), and the CI `performance` job builds that file before it times the commands.
A checkout without it still reads and validates the 289 record files in each process.
Importing the CLI takes about 53 ms with cached bytecode (22 November 2026, `python -X importtime`): `argparse` on Python 3.15 alone takes 5 ms and imports `shutil`, and the `tools`, `market`, `alerts` and `storybook` modules are imported to build their sub-commands.
In a Git repository, each approved task also runs `git merge-base` to check that its approved revision is still in the history.
