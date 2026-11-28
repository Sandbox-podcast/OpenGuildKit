# Error codes

For: a person or an agent that reads an error of the CLI and looks for where it comes from.

An error that carries a code starts with it: `OpenGuildKit [OGK-TASK-004]: Task already exists: x`, and under `--json` its object holds the same code in `error.code` ([JSON output](#json-output)).
A code is raised from one place and keeps its meaning when its words change: search the code, not the sentence. `python scripts/build_errors.py` writes this page and [`agents/errors.json`](agents/errors.json) from the code; the other errors still print `OpenGuildKit: message`.

| Code | Raised by | Message | Tests |
|---|---|---|---|
| `OGK-CHECK-001` | `check_cli.py:check` | --format sarif and --json both print the result on the standard output: use one of them. Type openguildkit check --format sarif for code scanning, or openguildkit check --json for a program. | tests/test_json_output.py |
| `OGK-CORE-001` | `clock.py:_source_date_epoch` | SOURCE_DATE_EPOCH must be a whole number of seconds since 1970-01-01 UTC. Fix or unset it. | tests/test_clock.py |
| `OGK-CORE-002` | `detect.py:_json_manifest` | {path.as_posix()}: JSON nested too deeply | tests/test_clean_errors.py |
| `OGK-CORE-003` | `git.py:required` | {needs} needs Git: it is not installed or not on the PATH. | tests/test_guard.py |
| `OGK-CORE-004` | `lock.py:_validated_lock` | {path}: {collection}/{record_id} is not an object. Restore the file from Git, or delete it and run openguildkit update --apply, which locks the catalog installed on this machine. | tests/e2e/test_catalog_lock.py |
| `OGK-CORE-005` | `managed.py:run` | host managed needs --host (claude-code, codex or gemini-cli) and --os (macos, linux or windows). | tests/test_managed_settings.py |
| `OGK-CORE-006` | `managed.py:run` | host managed prints the file as it is deployed, so --json is not an option of it. | tests/test_command_output_budget.py |
| `OGK-CORE-007` | `patterns.py:check_pattern_choices` | Choose one pattern in {group}: {selected[group]} or {pattern_id}. | tests/test_patterns.py |
| `OGK-CORE-008` | `storage.py:unique_fields` | duplicate JSON field {key!r} | tests/test_robustness.py |
| `OGK-CORE-009` | `storage.py:parse_json` | Invalid JSON in {label}: {error} | tests/test_clean_errors.py |
| `OGK-CORE-010` | `storage.py:parse_json` | Expected a JSON object in {label} | tests/test_robustness.py |
| `OGK-CORE-011` | `storage.py:write_text` | Refusing to replace a symbolic link: {path} | tests/test_storage.py |
| `OGK-CORE-012` | `storage.py:_held_lock` | Another OpenGuildKit command is writing this project. Try again. | tests/e2e/test_concurrency.py |
| `OGK-CORE-013` | `terminal.py:typed` | {cancelled} | tests/e2e/test_more_commands.py, tests/test_terminal.py |
| `OGK-PROJECT-001` | `project.py:_texts` | {field} must be a list of non-empty strings | tests/test_robustness.py |
| `OGK-PROJECT-002` | `project.py:_texts` | Each entry of {field} must be a single line | tests/test_instruction_files.py |
| `OGK-PROJECT-003` | `project.py:catalog_ids` | Unknown {field}: {', '.join(unknown)}.{hint} | tests/test_robustness.py |
| `OGK-PROJECT-004` | `project.py:_components` | Component {component_id} needs a path relative to the project root | tests/test_components.py |
| `OGK-PROJECT-005` | `project.py:project_context` | Unknown sector: {sector}. Run openguildkit catalog. | tests/test_robustness.py |
| `OGK-PROJECT-006` | `project.py:_yes_no` | {field} must be yes, no, true or false | tests/test_robustness.py |
| `OGK-PROJECT-007` | `project.py:_decision_text` | {field} must be a non-empty single line | tests/test_incident.py |
| `OGK-PROJECT-008` | `project.py:declined_entries` | Unknown declined: {pattern_id}. Run openguildkit catalog. | tests/test_sectors.py |
| `OGK-PROJECT-009` | `project.py:_declined_rules` | A declined_rules entry is {"id": "PACK/RULE", "by", "on", "reason"} | tests/test_rule_decline.py |
| `OGK-PROJECT-010` | `project.py:_declined_rules` | A declined rule is named PACK/RULE, as openguildkit catalog lists it: {rule!r} is not | tests/test_rule_decline.py |
| `OGK-PROJECT-011` | `project.py:_declined_rules` | Rule {rule} is both required and declined: remove {both[0]} from the required rules (openguildkit profile remove required-rule {both[0]}) or restore the rule (openguildkit profile adopt rule {rule}). | tests/test_rule_decline.py |
| `OGK-PROJECT-012` | `project.py:_approval_roles` | Unknown board in approval.roles: {', '.join(unknown)}. Run openguildkit catalog. | tests/test_roles.py |
| `OGK-PROJECT-013` | `project.py:pattern_entries` | patterns must be a list | tests/test_robustness.py |
| `OGK-PROJECT-014` | `project.py:pattern_entries` | Pattern {entry['id']} names unknown components: {', '.join(unknown)} | tests/test_components.py |
| `OGK-PROJECT-015` | `project.py:_resolutions` | keep must list one or more of the resolution's packs | tests/test_rule_plan.py |
| `OGK-PROJECT-016` | `project.py:restricted_paths` | {shape} | tests/test_hosts.py |
| `OGK-PROJECT-017` | `project.py:validate_profile` | Unsupported project schema version: {version} | tests/test_robustness.py |
| `OGK-PROJECT-018` | `project.py:validate_profile` | research must be local-only or public-sources | tests/test_robustness.py |
| `OGK-PROJECT-019` | `project.py:_chosen_patterns` | Pattern {', '.join(both)} is both selected and declined: remove it from one of the lists. | tests/test_sectors.py |
| `OGK-PROJECT-020` | `project.py:_add_agent_settings` | host must be one of {', '.join(HOSTS)} | tests/test_gemini_host.py |
| `OGK-PROJECT-021` | `project.py:_add_agent_settings` | guard must be off, observe or enforce | tests/test_robustness.py |
| `OGK-PROJECT-022` | `project.py:_add_rule_choices` | Unknown required rule {item}: use PACK or PACK/RULE from openguildkit catalog | tests/test_profile_commands.py |
| `OGK-PROJECT-023` | `project.py:_add_rule_choices` | Pack {drafts[0]} is a draft written by task retro: review each rule, replace each TODO and rewrite its description before a profile uses it. | tests/test_retro.py |
| `OGK-PROJECT-024` | `project.py:_add_options` | separate_requester must be true, or absent when the option is off | tests/test_requester.py |
| `OGK-PROJECT-025` | `project.py:_add_options` | ask_every_rule must be true or false | tests/test_relevance.py |
| `OGK-PROJECT-026` | `project.py:load_profile` | No OpenGuildKit project found for {state.parent.as_posix()}: {STATE_DIR}/project.json does not exist. cd into the project folder or pass --project PATH; run openguildkit init only to set up a new project here. | tests/test_clean_errors.py, tests/test_sarif_commands.py |
| `OGK-PROJECT-027` | `project.py:load_profile` | .openguildkit/project.json names the sector {sector!r}, which neither this release nor the catalog lock provides: choose one listed by openguildkit catalog, set it in .openguildkit/project.json, then run openguildkit sync. | tests/test_upgrade.py |
| `OGK-PROJECT-028` | `project.py:load_profile` | .openguildkit/project.json uses records that neither this release nor the catalog lock provides: remove {entries}, then run openguildkit sync. | tests/test_upgrades.py |
| `OGK-PROJECT-029` | `project_instructions.py:merged_instructions` | {label} ends inside an unclosed code block at line {open_fence}. Close it and retry. | tests/test_monorepo_instructions.py |
| `OGK-PROJECT-030` | `project_instructions.py:merged_instructions` | {label} has malformed OpenGuildKit markers. Repair the marked block and retry. | tests/test_instruction_files.py |
| `OGK-PROJECT-031` | `project_instructions.py:_read_instructions` | Refusing a symbolic link as project instructions: {path} | tests/test_instruction_files.py |
| `OGK-PROJECT-032` | `project_instructions.py:_read_instructions` | {path.name} is not UTF-8 (byte {error.start + 1}): convert it to UTF-8 and retry. | tests/test_monorepo_instructions.py |
| `OGK-PROJECT-033` | `project_mcp.py:_check_path` | Project metadata must stay inside the project state directory. | tests/test_project_mcp.py |
| `OGK-PROJECT-034` | `project_setup.py:_norm_answers` | norms must be an object such as {"gdpr-personal-data": "yes"} | tests/test_setup_questionnaire.py |
| `OGK-PROJECT-035` | `project_setup.py:_norm_answers` | Unknown norm: {pattern_id}. Use the IDs listed in the norms question of init --questions. | tests/test_setup_questionnaire.py |
| `OGK-PROJECT-036` | `project_setup.py:_norm_answers` | Declining norm {pattern_id} records who and why: write {"answer": "no", "by": "NAME", "reason": "WHY"}, with the name of the person who decided. | tests/test_setup_questionnaire.py |
| `OGK-PROJECT-037` | `project_setup.py:_norm_answers` | The answer for norm {pattern_id} must be yes or no | tests/test_setup_questionnaire.py |
| `OGK-PROJECT-038` | `project_setup.py:setup_profile` | Ask the person about each norm the project meets, then record the answers under norms: {listed}. Add this line to the answers file, "yes" for a norm that applies, or {"answer": "no", "by": "NAME", "reason": "WHY"} to decline it: "norms": {json.dumps({entry['id']: 'yes' for entry in missing})}. Nothing was written. | tests/test_proportionate_setup.py |
| `OGK-PROJECT-039` | `project_setup.py:setup_profile` | replace_default_packs must be true or false | tests/test_setup_questionnaire.py |
| `OGK-PROJECT-040` | `projects_cli.py:run` | --strict compares each project with a policy: add --policy FILE. | tests/test_projects.py |
| `OGK-PROJECT-041` | `projects_cli.py:run` | --format csv prints the projects only: use --json for the matches of --search, or for a program. | tests/test_projects.py |
| `OGK-PROJECT-042` | `projects_cli.py:read_policy` | The policy file cannot be read: {error} | tests/test_projects.py |
| `OGK-PROJECT-043` | `projects_cli.py:read_policy` | The policy file {path.name} names {', '.join(unknown)}: a policy holds {', '.join(POLICY_FIELDS)}. | tests/test_projects.py |
| `OGK-PROJECT-044` | `projects_cli.py:read_policy` | The guard of the policy must be {', '.join(list(GUARD_RANK)[:-1])} or {list(GUARD_RANK)[-1]}. | tests/test_projects.py |
| `OGK-RULE-001` | `project_rules.py:require_resolved_conflicts` | Conflicting rule packs: {names}. Keep only one of them, or record which apply in "resolutions" of the profile (the file passed to init --answers, or .openguildkit/project.json once the project is set up), for example {"packs": ["first", "second"], "keep": ["second"], "reason": "Why"}. Run openguildkit preview --answers FILE to check it. | tests/test_rule_plan.py |
| `OGK-RULE-002` | `rule_checks.py:_fields` | {label} is missing fields: {', '.join(sorted(missing))} | tests/test_rule_checks.py |
| `OGK-RULE-003` | `rule_checks.py:_fields` | {label} has unknown fields: {', '.join(sorted(extra))} | tests/test_rule_checks.py |
| `OGK-RULE-004` | `rule_checks.py:validate_path` | {label} must be a relative path of at most 300 characters | tests/test_rule_checks.py |
| `OGK-RULE-005` | `rule_checks.py:validate_path` | {label} {path!r} must stay inside the project: relative, with / and without . or .. | tests/test_rule_checks.py |
| `OGK-RULE-006` | `rule_checks.py:validate_path` | {label} {path!r} names one file: wildcards are not allowed | tests/test_rule_checks.py |
| `OGK-RULE-007` | `rule_checks.py:_validate_check_path` | {label} {path!r} is not searched: a check does not read inside .git or .openguildkit | tests/test_rule_checks.py |
| `OGK-RULE-008` | `rule_checks.py:_validate_paths` | {label}.paths must list 1 to {MAX_PATHS} paths | tests/test_rule_checks.py |
| `OGK-RULE-009` | `rule_checks.py:_validate_text` | {label}.contains holds literal texts of 1 to {MAX_LITERAL_LENGTH} characters | tests/test_rule_checks.py |
| `OGK-RULE-010` | `rule_checks.py:_validate_text` | {label}.each must be true, with expect present; omit it otherwise | tests/test_rule_checks.py |
| `OGK-RULE-011` | `rule_checks.py:_validate_size` | {label}.max_bytes must be a whole number of bytes from 1 to {MAX_SIZE_BYTES} | tests/test_rule_checks.py |
| `OGK-RULE-012` | `rule_checks.py:_validate_field` | {label}.integer must be true; omit it otherwise | tests/e2e/test_export_ci.py |
| `OGK-RULE-013` | `rule_checks.py:validate_check` | {label}.kind must be one of {', '.join(CHECK_KINDS)} | tests/test_rule_checks.py |
| `OGK-RULE-014` | `rule_checks.py:validate_check` | {label} runs a command: only a pack in .openguildkit/catalog/packs/ may declare one | tests/test_rule_checks.py |
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
