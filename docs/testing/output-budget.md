# Output budget

For: a developer who adds a command or makes one print more.
A part of the [testing guide](../testing.md).

An agent reads again, at every turn, what it has read, so what a command prints has a size budget. `tests/test_command_output_budget.py` runs every command that `tests/test_cli_coverage.py` walks (`command_paths()`) on an example project and fails when it prints more than 10 000 bytes: stdout and stderr counted together, in bytes of UTF-8. The failure names the command and its size:

```text
openguildkit catalog --json prints 495296 bytes, over its budget of 10000 bytes. Shorten what it prints, or list it in EXCEPTIONS ...
```

- **What runs.** A command runs in its plain form and, when it has `--json`, with it. A form that prints far more than the plain one has an example of its own (`brains --id security`, `task brief ID --scope`). Each example first puts a copy of the project in the state the command needs: a draft, a consulted or reviewed task, an approved or completed one, an alert, a Storybook application, a Git history, a central policy. The acts of a person are typed at a simulated terminal. `mcp` and `tools mock` run as real processes and answer a handshake and a `tools/list` request. Each state is reached with the commands of the CLI, not by writing records.
- **Exceptions.** `EXCEPTIONS` in the test lists what prints more than the budget today: the command as its example writes it, a ceiling and the reason its output is large. The ceiling is the size measured, plus 10 %, rounded up to the next 1 000 bytes, so growth fails long before the output doubles. Today they are the `--json` forms of `catalog`, `references`, `patterns`, `brains`, `tools list`, `features list`, `storybook extract` and `task checks`, and `init --questions`, `tools list`, `brains --id`, `task show`, `task brief --scope` and `task challenge`. `NOT_RUN` lists the commands no example runs, each with its reason: `ui`, which serves until it is stopped, and `docs share verify`, which asks a password at a terminal and opens a session on a portal. A mode that a positional argument selects (`market resume`, `docs share add`) is a command here too, as in `tests/test_cli_coverage.py`.
- **SARIF.** `check --format sarif` and `guard --ci --format sarif` have an example each: `check` on a project with one problem (about 1.6 KB) and `guard --ci` on a change with none (about 0.4 KB). A document grows by 500 to 900 bytes per problem, so a project with a dozen of them goes past the budget: write the file with `> openguildkit.sarif` and open it in the viewer of the dashboard instead of reading it on the screen ([SARIF output](../sarif.md)).
- **A new command.** The test fails until its example is in `EXAMPLES`, with a second one that has `--json` when the command takes that option, or until `NOT_RUN` gives the reason for none. If the output passes the budget, shorten it first. If it has to be that long, add the example to `EXCEPTIONS` with a ceiling and the reason, in the same pull request; raising a ceiling needs a reason in the pull request too. An exception whose output fits the budget again fails, so the list does not outlive its reasons.

The consultation, each board pass and the handoff keep their own budgets in `tests/test_output_size.py`: 30 000, 10 000 and 16 000 bytes.
