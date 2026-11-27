# Conventions for agents

These conventions let a coding agent go from a symptom to its cause, its test and its fix with as few reads as possible. They exist because an agent pays for every byte it reads at every later turn: measured on 213 agent sessions of this project (20 to 25 November 2026), 80 % of the cost came from context, tool results made 35 % of the input, 28 % of the commands were searches and 44 % of the file reads were reads of a file already read.

Each convention has a rule, the measure behind it, a check a machine can run, what is true today and the issue that brings the repository in line. A convention without a check is a wish: when the check does not exist yet, its issue adds it. [AGENTS.md](../../AGENTS.md) is the short version an agent reads first; this page is the reference.

Read it by the step you are at: find the code, diagnose a failure, fix and prove, verify fast, measure.

## Find

### `root-agents-file`

**Rule.** The root holds an `AGENTS.md` of 4 KB at most, and a `CLAUDE.md` that only imports it, with the exact commands to run the CLI, check a change, run one test and run the suite, the map, and the known pitfalls.

**Why.** Before this file, an agent read `CONTRIBUTING.md`, `docs/testing.md` and `docs/architecture.md`, 77 KB, about 19,000 tokens read again at every turn, to learn how to check a change.

**Check.** `RootInstructionsTests` in `tests/test_agent_native.py`: size, `CLAUDE.md` equal to `@AGENTS.md`, every path and test module named exists.

**Today.** Done by the pull request that adds this page. Issue #455.

### `module-header-contract`

**Rule.** Every module starts with a docstring of 10 lines at most: its role in one sentence, an `Entry:` line with its entry points and a `Tests:` line with its test files. The docstring is the one source of the role.

**Why.** An agent reads the header, then the one function it needs, instead of the map (43 KB) or the whole file. Today 65 modules of 65 have a docstring, none names a test file, 3 name their entry points, and the role written in the docstring matches the map for none of them.

**Check.** `tests/test_architecture.py`, to extend: the `Tests:` paths exist and the `Entry:` names are defined at the top level of the module.

**Today.** Docstrings everywhere, contract absent. Issue #502.

### `generated-repo-map`

**Rule.** `docs/agents/map.json` is produced by a script from the module headers, the imports of the tests and the parser of the CLI, never edited by hand. It covers `web/src`, `integrations/ci/lib` and `scripts`, and holds an index of the commands: command, function, module, tests.

**Why.** The map is kept by hand: 51 test files import a module they are not attached to (17 for `storage`), the `doc` field is `docs/architecture.md` for 63 entries of 65, and none of the 94 commands leads to its function.

**Check.** `python scripts/build_map.py --check`, to add: regenerates in memory, compares with the committed file, exits 1 with the entries that differ.

**Today.** Map present and tested since #364, written by hand, without commands. Issue #502.

### `map-query-command`

**Rule.** One command prints, in 1 KB at most and without running anything, what an agent needs about a path or a command: role, entry points, tests, documentation page.

**Why.** To know which tests cover a file, an agent reads the whole map (43,324 bytes) or runs the whole check.

**Check.** `python scripts/check_fast.py --plan src/openguildkit/results.py | wc -c` prints 1024 at most and runs no test.

**Today.** `check_fast.py` takes `--base` only. Issue #502.

### `byte-budget-ratchet`

**Rule.** No source, test or documentation file passes 40 KB. A file already above it is listed with its ceiling, which can only go down; a new file is born under the budget.

**Why.** A read tool loads the whole file, read again at every turn. 16 modules of 65 pass 40 KB and hold 58 % of the bytes of `src` (950 KB of 1,617 KB); they were 11 two days earlier. The line limit of `tests/test_architecture.py` lets `tasks_cli.py` reach 94,758 bytes, about 24,000 tokens.

**Check.** `tests/test_architecture.py`, to extend: `git ls-files` compared with a ceiling file, failure above 40,000 bytes outside the list or above a listed ceiling.

**Today.** Line limit only. Issue #486.

### `greppable-doc-lines`

**Rule.** In a Markdown file, a line outside a table holds at most 400 characters: one sentence per line in long paragraphs.

**Why.** A search returns the whole line. `grep -rn 'task verify'` returns 739 bytes per result in the documentation against 133 in the code; `docs/workflow.md` has 20 lines over 1,000 characters, the longest 4,070.

**Check.** A ratchet test that counts, per file, the lines over 400 characters outside tables and fails when a count goes up.

**Today.** 594 such lines in 110 Markdown files. Issue #505.

### `handler-named-after-command`

**Rule.** The function that runs a command bears its name (`task verify` runs `_verify`). A dispatch table never maps a string to a function of another name without the index of the commands saying so.

**Why.** A bug arrives named by its command. `grep 'def _verify'` finds nothing today: `verify`, `result` and `complete` lead to `_outcome`, `clear` and `waive` to `_resolve`, `submit` to `_pass`.

**Check.** A test that compares each key of `tasks_cli.HANDLERS` with the name of its function.

**Today.** 22 actions of `task` of 29. Issue #530.

### `unique-function-names`

**Rule.** A top-level function name is defined in one module. A helper several modules need lives once, in a shared module (`git.py`, `storage.py`).

**Why.** A search for a definition must return one line. 68 names are defined in several modules, 14 of them public: `_git` 6 times with different options and return types, `record_digest` and `timestamp` twice with different meanings.

**Check.** `tests/test_architecture.py`, to extend: names defined in several modules, 0 for public names outside `run` and `add_parser` of command modules, a ratchet for private ones.

**Today.** 95 % of names are unique. Issues #530 and #459.

### `no-computed-dispatch`

**Rule.** No call is built from a computed string (`getattr` on a non-literal name, `import_module` of an assembled name) without an `INTENTIONAL(#N):` marker on the line and an entry in the exception list of the test.

**Why.** A search for the caller must succeed. `cli.py` imports 22 functions of 4 modules by their name in a string; 8 `getattr` with a non-literal name in `src`.

**Check.** `tests/test_architecture.py`, to extend: an AST walk that fails on a `getattr` whose second argument is not a constant, outside the list.

**Today.** 8 sites, no marker. Issue #462.

### `test-file-mirrors-module`

**Rule.** The tests closest to a module live in `tests/test_<module>.py`; behavior that crosses modules lives in `tests/e2e/`; no test file is named after a campaign or a batch of fixes.

**Why.** An agent goes from the module to its test without reading the map. 35 modules of 65 have a test file of their name; `test_core.py` and `test_audit_fixes.py` still hold 15 tests.

**Check.** `tests/test_architecture.py`, to extend: each module has its test file or is in an exception list that can only shrink; no test file name contains `fixes`, `audit`, `core` or `misc`.

**Today.** 54 % of modules. Issue #488.

## Diagnose

### `debug-trace-switch`

**Rule.** With `OPENGUILDKIT_DEBUG=1`, every error the CLI turns into one line also prints its Python traceback on standard error, before the line.

**Why.** `cli.main` turns `OSError`, `ValueError` and `EOFError` from 922 `raise` sites into one line. Of 22 errors provoked, a search for the first 40 characters of the message found one line 5 times and none 14 times.

**Check.** `OPENGUILDKIT_DEBUG=1 PYTHONPATH=src python -m openguildkit task show nope 2>&1 | grep -c '^Traceback'` prints 1, and 0 without the variable.

**Today.** No switch, no `logging`. Issue #504.

### `stable-error-codes`

**Rule.** Every error shown to a person carries a stable, unique code (`OGK-TASK-012`), declared once in a register that gives the module, the function and the test; the code is in the message and in the `--json` output.

**Why.** 785 message templates for 922 `raise` sites, no code; 34 templates are raised from several sites and 44 % start with a variable, so their start cannot be searched. A code is found by one search and returns one line.

**Check.** A test that walks the AST of `src/openguildkit`, requires a code for each error shown, uniqueness, an entry in the register and a test that cites the code.

**Today.** No code; only the web page has refusal codes (`REFUSALS` in `webui.py`). Issue #487.

### `json-envelope`

**Rule.** Every `--json` output is an object with `schema_version`. Under `--json`, an error is JSON too (`error.code`, `error.message`, `error.next`) with the same exit code.

**Why.** 41 terminal commands of 94 have `--json`; of 26 outputs run, none has `schema_version` and 11 are bare lists. Under `--json`, an error is a sentence on standard error: the agent falls back to reading prose.

**Check.** A test that loads each `--json` example of `tests/test_command_output_budget.py` and requires an object with `schema_version`, and an error example with `error.code`.

**Today.** `schema_version` only in the task record. Issue #484.

### `declared-state-machine`

**Rule.** The transitions of a record (status, allowed action, next status) are declared in one table, from which the refusals, the next command and the table of the documentation come.

**Why.** An invariant written once is read in one excerpt. 141 comparisons of `status` are spread over 24 modules.

**Check.** A ratchet test that counts the comparisons of `["status"]` per module and fails when the count goes up outside the module that declares the table.

**Today.** Required fields per status declared in `tasks.py`; transitions not declared. Issue #506.

### `fail-fast-toolchain`

**Rule.** Run with a tool out of its version, the repository answers in one line that names the expected version. The versions of Python and Node live in one file that CI and a `doctor` command read.

**Why.** With the Python 3.9 of macOS, the CLI, the tests and `check_fast.py` end on `TypeError: unsupported operand type(s) for |`. Versions are typed 6 times in `ci.yml`; `web/package.json` has no `engines` field.

**Check.** `/usr/bin/python3 -m openguildkit --version` names Python 3.11 on a workstation whose system Python is older; `ci.yml` reads a version file.

**Today.** Absent. Issue #520.

## Fix and prove

### `regression-test-names-issue`

**Rule.** The test that reproduces a bug names its issue: its docstring starts with `Issue #N:` and the symptom as the person saw it.

**Why.** The issue number is the one key shared by the issue, the commit and the test. Of 159 closed bugs, 40 have their number in `tests/`, none in `src` or `CHANGELOG.md`.

**Check.** A script that reads the `Closes #N` of the branch and requires `Issue #N` in `tests/` for each bug.

**Today.** 25 % of closed bugs. Issue #488.

### `fix-ledger`

**Rule.** Every fixed bug adds one line to `docs/agents/fixes.jsonl`: issue, symptom word for word, cause as `file:function`, test identifier, commit.

**Why.** Before searching, an agent asks the ledger by symptom or by file: one line of 300 bytes instead of a squash commit body of 13,755 or 77,742 bytes. 58 closed bugs of 159 cannot be found by their number in tests, code, changelog or log.

**Check.** A test that reads each line as JSON with its five fields, checks that the file of the cause exists and that the test loads.

**Today.** Absent. Issue #488.

### `commit-names-its-issues`

**Rule.** A squash commit on `main` names each issue it closes in its body, one line per issue: `#N symptom (file:function)`. Its subject names no range (`#377 to #407`).

**Why.** `git blame` must lead from a line to its issue. One commit of 523 files owns 41 to 77 % of the lines of the five central modules, and `git log --grep '#381'` finds a range only in its body.

**Check.** A CI step that rejects a pull request title with a range of issues and a body without one line per `Closes #N`.

**Today.** 10 subjects of 105 list several issues, 4 by a range. Issue #483.

### `changelog-entry-shape`

**Rule.** A changelog entry fits on one line of 400 characters at most, starts with the command or area it touches and ends with its issue `(#N)`. The detail lives in the documentation.

**Why.** The changelog is the one history searchable by symptom outside Git. `## Unreleased` weighs 47 KB for 83 entries: 45 pass 400 characters and 58 have no number.

**Check.** `tests/test_release.py`, to extend with the shape above.

**Today.** Absent. Issue #483.

### `protected-oracle-diff`

**Rule.** A branch that changes `src/` and removes or changes an assertion of `tests/` lists each assertion it touched under `## Assertions changed` in the pull request.

**Why.** A test made green by weakening it is the most expensive silent failure to catch, and nothing in the repository flags it.

**Check.** `python scripts/check_oracle.py --base origin/main`, to add: each removed line that holds `self.assert` or `expect(` must be listed.

**Today.** Absent. Issue #522.

### `not-verified-section`

**Rule.** Every report of an agent (pull request, issue comment) ends with `## Not verified`: what was not run, or "nothing".

**Why.** A reviewer must tell a check that passed from a check that was skipped.

**Check.** The pull request template holds the section; a CI step fails when it is missing or empty.

**Today.** The template has the section since the pull request that adds this page; the CI step is missing. Issue #522.

### `intent-markers-on-suppressions`

**Rule.** Every suppression of a check (`noqa`, `type: ignore`, `eslint-disable`, `@ts-ignore`, `@ts-expect-error`) carries `INTENTIONAL(#N):` and the reason on its line.

**Why.** An agent that makes code uniform removes what it does not understand. 24 suppressions, no marker.

**Check.** `grep -rnE 'noqa|type: ignore|eslint-disable|@ts-(ignore|expect-error)' src tests scripts web/src integrations/ci | grep -vc INTENTIONAL` prints 0.

**Today.** 24 suppressions without a marker. Issue #522.

## Verify fast

### `fast-check-time-budget`

**Rule.** The targeted check answers in 30 seconds at most for one changed module: it runs test modules in parallel processes, the closest first, stops at the budget and names what it did not run.

**Why.** A changed `clock.py` runs 166 tests and 42 s of CPU, `guard.py` 323 tests and 100 s, `storage.py` 1,058 tests. The agent sessions of this project waited 12.6 hours on 2,146 test runs.

**Check.** A timed test that changes the module with the most attached tests in a copy and runs `scripts/check_fast.py` under 30 seconds.

**Today.** The command exists (#365); no module of five measured stays under the budget. Issue #456.

### `lint-and-type-ratchet`

**Rule.** CI runs a linter and a type checker on `src/`, `scripts/` and `web/src` with the settings committed in the repository. The count of findings per rule can only go down.

**Why.** Without them, an agent learns the style by reading. `ruff` with its defaults reports 189 findings, `mypy` 320 errors in 46 files; `web/` has neither formatter nor linter, with lines up to 731 characters.

**Check.** A CI job that compares the counts with a committed baseline.

**Today.** Absent. Issues #501 and #515.

### `typed-records`

**Rule.** A record read from disk (profile, task, decision, catalog entry) has a `TypedDict` that names its fields; functions take and return that type, not a bare `dict`.

**Why.** 1,115 parameters are annotated `dict`, 4,924 accesses by key, no `TypedDict`: the fields of a task are found only by reading its validator.

**Check.** The type checker of `lint-and-type-ratchet`, with a ratchet on the parameters annotated `dict`.

**Today.** Absent. Issue #507.

## Measure

### `cost-per-task-with-subagents`

**Rule.** The cost measure reads the whole session (main transcript and `subagents/*.jsonl`), applies the price of the model named on each line and ties the total to a task.

**Why.** Subagents made 76 % of the cost of this project's sessions. `scripts/agent_cost.py` reads one file, counts each message 2.15 times and prints 0 subagents.

**Check.** `AgentCostTests` in `tests/test_agent_native.py`, to extend with a session folder holding one subagent file and two models.

**Today.** Done for the session folder, the message counted once and the price by model (a model without a rate is named, none but one has a rate yet); the total is not yet tied to a task. Issue #485.

## Stay fast

### `hook-latency-budget`

**Rule.** The guard hook, which runs at every tool call of the agent, imports only what its decision needs, and its timed budget stays within twice its measured median; so does the start of the CLI.

**Why.** The hook imports 32 modules of the package and `tempfile`, and the CLI imports 53 modules and compiles 123 regular expressions before any command: `--version` takes 115 ms for 23 ms of interpreter. The budgets of `tests/test_performance.py` are 2.2 to 7.5 times the measured time, so a regression of several times goes unseen.

**Check.** `tests/test_performance.py`, budgets tightened to twice the median, and a test that lists the modules the hook imports against an allowed set.

**Today.** Budgets loose, imports eager. Issues #538 and #539.

### `read-once-per-command`

**Rule.** A command reads each file once, loads the catalog once and starts one Git process per kind of read, not per file. Every listing command has a timed test on a project of 1,000 tasks.

**Why.** `task list`, `check` and `projects` read each closed task 2 to 4 times (4.9 to 10 s at 1,000 tasks); the catalog is read from 289 files in every process and copied 2 to 6 times per command; `guard --ci` starts one `git show` per file (23.5 s at 990 decisions, 0.3 s with one `git cat-file --batch`).

**Check.** A test that counts file reads per command on a project of 50 tasks, and timed tests at 1,000 tasks in `tests/test_performance.py`.

**Today.** Absent. Issues #534, #533 and #532.

## One source

### `generated-not-mirrored`

**Rule.** A text present in two places of the repository is produced by a script from one source, and the copy says on its first line where it comes from.

**Why.** A search returns each result twice and a fix is forgotten on one side. 11 files are identical byte for byte between `src/openguildkit/agent_files/` and `integrations/` (43 KB).

**Check.** A `--check` mode of the generating script, run by the tests.

**Today.** Equality tested, not produced. Issue #502.
