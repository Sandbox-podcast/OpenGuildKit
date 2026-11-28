# Error codes

For: a person or an agent that reads an error of the CLI and looks for where it comes from.

An error that carries a code starts with it: `OpenGuildKit [OGK-TASK-004]: Task already exists: x`, and under `--json` its object holds the same code in `error.code` ([JSON output](#json-output)).
A code is raised from one place and keeps its meaning when its words change: search the code, not the sentence. `python scripts/build_errors.py` writes this page and [`agents/errors.json`](agents/errors.json) from the code; the other errors still print `OpenGuildKit: message`.

| Code | Raised by | Message | Tests |
|---|---|---|---|
| `OGK-CHECK-001` | `check_cli.py:check` | --format sarif and --json both print the result on the standard output: use one of them. Type openguildkit check --format sarif for code scanning, or openguildkit check --json for a program. | tests/test_json_output.py |
| `OGK-TASK-001` | `tasks.py:dependencies` | A task cannot wait for itself: {task_id}. | tests/test_error_codes.py |
| `OGK-TASK-002` | `tasks.py:dependencies` | Task {task_id} cannot wait for {cycle[1]}: that would close a cycle ({' -> '.join(cycle)}). Remove that --after. | tests/test_error_codes.py |
| `OGK-TASK-003` | `tasks.py:create_task` | The task ID is empty. Omit --id to generate one. | tests/test_error_codes.py |
| `OGK-TASK-004` | `tasks.py:create_task` | Task already exists: {task_id} | tests/e2e/test_concurrency.py, tests/test_error_codes.py |
| `OGK-TASK-005` | `tasks.py:create_task` | Task {follows} has no recorded decision to follow. | tests/test_error_codes.py |
| `OGK-TASK-006` | `tasks.py:_period_day` | {option}: {value!r} is not a real date. Write it YYYY-MM-DD. | tests/test_error_codes.py, tests/test_json_output.py, tests/test_task_list.py |
| `OGK-TASK-007` | `tasks_cli.py:_new` | Supply either a task brief or --file PATH. | tests/test_error_codes.py |
| `OGK-TASK-008` | `tasks_cli.py:_new` | Task ID {args.id} is already used by the exported decision {record.relative_to(root).as_posix()}, a teammate's task or an earlier one: read it with openguildkit task show {args.id}, and choose another ID. | tests/test_error_codes.py |
| `OGK-TASK-009` | `tasks_cli.py:run` | {state_refusal(task, str(error), approval_problem(task, profile, catalog, root))} | tests/test_error_codes.py, tests/test_robustness.py |
| `OGK-TASK-010` | `tasks_cli.py:_run` | Task {args.id} exists here only as the exported record, which has no summary: run openguildkit task show {args.id}. | tests/test_error_codes.py |
| `OGK-TASK-011` | `tasks_cli.py:_run` | Task {args.id} exists here only as the exported record {record.relative_to(root).as_posix()}, a teammate's task or an earlier one: read it with openguildkit task show {args.id} or openguildkit task list --decisions. | tests/test_error_codes.py |
| `OGK-TASK-012` | `tasks_cli.py:_run` | {problem['message']} | tests/test_approval_lifecycle.py, tests/test_error_codes.py, tests/test_upgrade.py |
| `OGK-TASK-013` | `tasks_decide_cli.py:_save_decided` | The task changed while you were deciding. Review it and retry. | tests/test_error_codes.py |

## JSON output

With `--json`, a command prints its answer as JSON on standard output.
With `OPENGUILDKIT_JSON_ENVELOPE=1` in the environment, every answer comes in one object, `{"schema_version": 1, "command": "task checks", "data": ...}`, whose `data` is the answer printed without the variable; the default keeps the shape scripts and the web interface read.
Under `--json`, an error is JSON on standard output too, with the same exit code and its line on standard error: `{"schema_version": 1, "error": {"code": "OGK-TASK-004", "message": ..., "next": ...}}`.
`code` is null for an error that has no code yet, and `next` is the command the message names, or null.
