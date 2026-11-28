# Error codes

For: a person or an agent that reads an error of the CLI and looks for where it comes from.

An error that carries a code starts with it: `OpenGuildKit [OGK-TASK-004]: Task already exists: x`, and under `--json` its object holds the same code in `error.code` ([JSON output](#json-output)).
A code is raised from one place and keeps its meaning when its words change: search the code, not the sentence. `python scripts/build_errors.py` writes this page and [`agents/errors.json`](agents/errors.json) from the code; the other errors still print `OpenGuildKit: message`.

| Code | Raised by | Message | Tests |
|---|---|---|---|
| `OGK-BOARD-001` | `board_entries.py:required_text` | {field} must contain text. | tests/e2e/test_board_passes.py |
| `OGK-BOARD-002` | `board_entries.py:_text_list` | {field} must be a list of strings. | tests/test_robustness.py |
| `OGK-BOARD-003` | `board_entries.py:_evidence_day` | {field}: got {received_value(value)}; write the date YYYY-MM-DD. | tests/e2e/test_board_passes.py |
| `OGK-BOARD-004` | `board_entries.py:_evidence_day` | {field}: {value} is not a real date. Write it YYYY-MM-DD. | tests/test_clean_errors.py |
| `OGK-BOARD-005` | `board_entries.py:_evidence_day` | {field}: {value} is in the future. Write the day the evidence was observed. | tests/test_clock.py |
| `OGK-BOARD-006` | `board_entries.py:_check_reference` | {field}: {ref} is not an observation or change of the attached market dossier. | tests/test_market.py |
| `OGK-BOARD-007` | `board_entries.py:_check_reference` | {field}: {ref} is not a story of the Storybook indexes the project recorded. | tests/test_storybook.py |
| `OGK-BOARD-008` | `board_entries.py:_check_reference` | {field}: a tool source is written TOOL:RECORD (for example jira:SUP-142) for a tool connected to the project. Connected: {connected}. | tests/e2e/test_tool_mocks.py |
| `OGK-BOARD-009` | `board_entries.py:validate_board_entry` | id: got {received_value(board_id)}; write the board's ID, one of {', '.join(selected)}. | tests/test_board_entries.py |
| `OGK-BOARD-010` | `board_entries.py:validate_board_entry` | id: board {board_id!r} was not selected for this consultation. Selected: {', '.join(selected)}. | tests/test_robustness.py |
| `OGK-BOARD-011` | `board_entries.py:validate_review` | This review belongs to another consultation. Run task template again. | tests/test_approval_lifecycle.py |
| `OGK-BOARD-012` | `board_entries.py:validate_review` | {problems[0]} | tests/test_brains.py |
| `OGK-BOARD-013` | `board_entries.py:validate_review` | {f'The review has {len(problems)} problems:\n- ' + '\n- '.join(problems)} | tests/test_clean_errors.py |
| `OGK-BOARD-014` | `brains.py:write_brain_skeleton` | Brain {board_id} already exists. To complete it, write .openguildkit/catalog/boards/{board_id}.json with only the lenses, evidence or criteria to add. | tests/test_new_brains.py |
| `OGK-CATALOG-001` | `catalog_cli.py:print_patterns` | {unknown('pattern', args.id, 'patterns')} | tests/test_error_forms.py |
| `OGK-CATALOG-002` | `catalog_cli.py:print_brains` | Unknown brain: {args.id}. Run openguildkit brains. | tests/test_clean_errors.py |
| `OGK-CATALOG-003` | `catalog_queries.py:recorded_value` | {check_id} records the {records['name']}: write it in value, a number with its unit such as "90 % of cases" ({records['description']}). | tests/test_recorded_values.py |
| `OGK-CATALOG-004` | `catalog_queries.py:recorded_value` | {check_id} records the {records['name']}: {problem} ({records['description']}). | tests/test_recorded_values.py |
| `OGK-CHECK-001` | `check_cli.py:check` | --format sarif and --json both print the result on the standard output: use one of them. Type openguildkit check --format sarif for code scanning, or openguildkit check --json for a program. | tests/test_json_output.py |
| `OGK-CI-001` | `ci.py:_committed_bytes` | Git could not read {args[-1]} in {repo}. Fetch the required commit first. | tests/e2e/test_export_ci.py |
| `OGK-CI-002` | `ci.py:_committed_file` | Use a full lowercase Git commit SHA. | tests/e2e/test_export_ci.py |
| `OGK-CI-003` | `ci.py:_committed_file` | The supplied SHA must identify a commit directly. | tests/e2e/test_export_ci.py |
| `OGK-CI-004` | `ci.py:read_policy_pack` | --policy-repo reads only the central export rule ({POLICY_PATH}), and commit {commit[:12]} holds an organization policy ({ORG_POLICY}). Pin it at a terminal: openguildkit org-catalog set --repo PATH --commit SHA --by INITIALS --reason WHY; in CI: openguildkit guard --ci --org-policy PATH --org-commit SHA. | tests/test_org_policy.py |
| `OGK-CI-005` | `ci.py:check_export` | Select the {EXPORT_EXPIRY_ID} pack in the trusted project profile. | tests/test_exit_codes.py |
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
| `OGK-GUARD-001` | `allowlist.py:load_allow` | The allow list {path.as_posix()} cannot be read: {getattr(error, 'strerror', None) or error}. | tests/test_allow_list_scan.py |
| `OGK-GUARD-002` | `allowlist.py:load_allow` | The allow list {path.as_posix()} must be a JSON object with the keys {', '.join(AXES)} only, each a list of non-empty text, alone or under the key allow; a server may be an object with server and name, a name of letters, digits, - and _. | tests/test_managed_settings.py |
| `OGK-GUARD-003` | `guard.py:edited_paths` | the hook input names no tool input | tests/test_robustness.py |
| `OGK-GUARD-004` | `guard.py:edited_paths` | tool_input.{key} is not a file path | tests/test_guard.py |
| `OGK-GUARD-005` | `guard.py:edited_paths` | the hook input names no file to edit | tests/test_guard.py |
| `OGK-GUARD-006` | `guard.py:_decide_hook` | the hook input is not JSON | tests/test_guard.py |
| `OGK-GUARD-007` | `guard_ci.py:ci_guard` | guard --ci needs a Git repository: the project folder is not inside one. | tests/test_guard.py |
| `OGK-GUARD-008` | `guard_ci.py:ci_guard` | base revision {base} not found: pass --base REF | tests/test_error_forms.py |
| `OGK-GUARD-009` | `guard_export.py:_refuse_foreign_record` | {conflict} | tests/test_record_integrity.py |
| `OGK-GUARD-010` | `guard_export.py:_refuse_foreign_record` | {shown} holds a decision record of another task, such as a teammate's task with the same ID: it is left as it is. Read it with openguildkit task list --decisions; export this task with --output to another file, or open it again under another ID. | tests/test_team_sharing.py |
| `OGK-GUARD-011` | `guard_export.py:record_shape` | {relative} is not a decision record written by openguildkit task export: {problem}. Export the decision again or remove the file. | tests/test_guard.py |
| `OGK-GUARD-012` | `guard_export.py:export_withdrawal` | The approval of {task['id']} was withdrawn and {shown} does not exist: there is no exported record to write the withdrawal into, and nothing for guard --ci to accept. | tests/test_record_lifecycle.py |
| `OGK-GUARD-013` | `guard_records.py:exported_decisions` | {conflict_message(path, relative) or f'{relative} is not a decision record written by openguildkit task export. Export the decision again or remove the file.'} | tests/test_team_sharing.py |
| `OGK-GUARD-014` | `sensitive.py:refuse_link_credentials` | {field}: the link must carry no user name, password or token: the address is recorded as written, and {WHERE}. | tests/e2e/test_more_commands.py |
| `OGK-GUARD-015` | `sensitive.py:public_evidence_url` | {field}: a public source must use a link without credentials. | tests/test_board_entries.py |
| `OGK-GUARD-016` | `sensitive.py:public_evidence_url` | {field}: a public source needs a public host. Cite internal evidence as a project file or tool. | tests/test_clean_errors.py |
| `OGK-HOST-001` | `host_coverage.py:run` | --matrix is an option of openguildkit host check. | tests/test_doc_pages.py |
| `OGK-HOST-002` | `hosts.py:_read_settings` | {path.as_posix()} is not valid JSON: {error} | tests/test_gemini_host.py |
| `OGK-HOST-003` | `hosts.py:_read_settings` | {path.as_posix()} must hold a JSON object. | tests/test_gemini_host.py |
| `OGK-HOST-004` | `hosts.py:_check_hook_groups` | {path.as_posix()}: hooks.{event}[{index}].hooks must be a list of handlers. Fix or remove it, then run openguildkit host apply. | tests/test_gemini_host.py |
| `OGK-HOST-005` | `hosts.py:_codex_disable_web_search` | Could not add web_search = "disabled" to {path.as_posix()} safely. Add it at the top of the file yourself. | tests/test_host_research.py |
| `OGK-HOST-006` | `hosts.py:_gemini_hooks_config` | {path.as_posix()}: hooksConfig must be a JSON object. Fix or remove it, then run openguildkit host apply. | tests/test_gemini_host.py |
| `OGK-HOST-007` | `hosts.py:_apply_codex` | {path.as_posix()} sets web_search = "{config['web_search']}". Set it to "disabled" yourself. | tests/test_hosts.py |
| `OGK-HOST-008` | `hosts.py:_apply_codex` | {path.as_posix()} sets web_search = "disabled" but the research policy is public-sources. Remove it yourself, or set research to local-only. | tests/test_host_research.py |
| `OGK-HOST-009` | `workstation.py:policy` | {path.as_posix()} cannot be read as the workstation policy: {error} | tests/test_managed_settings.py |
| `OGK-HOST-010` | `workstation.py:policy` | {path.as_posix()} must be a JSON object with the keys {', '.join(KEYS)} only. | tests/test_managed_settings.py |
| `OGK-LANE-001` | `short_lane.py:normalize_entry` | {entry!r} is not a path: write a folder or file glob such as docs/** or README.md. | tests/test_short_lane.py |
| `OGK-LANE-002` | `short_lane.py:normalize_entry` | {entry!r} is not a path of the short lane: {problem}. | tests/test_short_lane.py |
| `OGK-LANE-003` | `short_lane.py:normalize_entries` | {label} needs a list of at least one path, such as docs/**. | tests/test_short_lane.py |
| `OGK-LANE-004` | `short_lane.py:normalize_entries` | {label} lists {len(entries)} paths: at most {MAX_PATHS}; use folders such as docs/**. | tests/test_short_lane.py |
| `OGK-LANE-005` | `short_lane.py:declare` | --paths belongs to the short lane: add --lane light, or leave --paths out for the full path. | tests/test_short_lane.py |
| `OGK-LANE-006` | `short_lane.py:declare` | the short lane is off in this project: its profile names no paths it may cover (light_paths). A person turns it on at their terminal: {activation_command(_usable(paths))}; a task opened without --lane takes the full path. | tests/test_short_lane.py |
| `OGK-LANE-007` | `short_lane.py:declare` | Name the paths a short-lane task may change: --paths GLOB..., inside {', '.join(light)}. | tests/test_short_lane.py |
| `OGK-LANE-008` | `short_lane.py:declare` | {error} Open the task on the full path: {FULL_PATH}. | tests/test_short_lane.py |
| `OGK-LANE-009` | `short_lane.py:declare` | the short lane of this project covers only {', '.join(light)}; these paths are outside it: {', '.join(outside)}. Open the task on the full path ({FULL_PATH}, without --lane), or have a person widen the lane at their terminal: {activation_command(sorted({*light, *outside}))}. | tests/test_short_lane.py |
| `OGK-LANE-010` | `short_lane.py:proposed_routing` | The short lane calls for the {board} board for {', '.join(task['paths'])}, and this project has not enabled it: a person adds it at their terminal (openguildkit profile add board {board} --by INITIALS --reason WHY), or the work takes the full path ({FULL_PATH}). | tests/test_short_lane.py |
| `OGK-MCP-001` | `mcp_mock.py:_validate_records` | {label}: every item needs a unique {collection['key']}. | tests/test_tools.py |
| `OGK-MCP-002` | `mcp_mock.py:validate_mock` | Mock {tool_id}: {problems[0]} | tests/test_tools.py |
| `OGK-MCP-003` | `mcp_mock.py:check_synthetic` | {label}: {match.group(0)} is not a test address. Use a reserved domain such as example.test. | tests/test_tools.py |
| `OGK-MCP-004` | `mcp_mock.py:apply_scenario` | {label}: {mock['tool']} has no collection {unknown[0]}. Known: {known}. | tests/test_tools.py |
| `OGK-MCP-005` | `mcp_mock.py:apply_scenario` | {label}: {error} | tests/test_tools.py |
| `OGK-ORG-001` | `org_catalog.py:parse_copies` | --org-catalog takes NAME=PATH, such as acme=../acme-catalog, not {item!r}. | tests/test_org_catalog.py |
| `OGK-ORG-002` | `org_catalog.py:_named_folder` | This machine has no copy of the organization catalog {name!r}: set {variable_name(name)} to your Git copy of it (guard --ci: --org-catalog {name}=PATH). | tests/test_org_catalog.py |
| `OGK-ORG-003` | `org_catalog.py:read_files` | Give the full commit SHA of the organization catalog, not {commit!r}: git -C {shell_word(repo)} rev-parse COMMIT prints it. | tests/test_org_catalog.py |
| `OGK-ORG-004` | `org_catalog.py:read_files` | The organization catalog {shown} is not a Git repository on this machine. Clone it at that path, or point the project at your copy at a terminal: {SET_COMMAND}. | tests/test_org_catalog.py |
| `OGK-ORG-005` | `org_catalog.py:read_files` | Commit {commit[:12]} of the organization catalog is not in {shown}: run git -C {shell_word(str(folder) if named else repo)} fetch, then the command again, or pin a commit the copy has at a terminal: {SET_COMMAND}. | tests/test_org_catalog.py |
| `OGK-ORG-006` | `org_catalog.py:organization_in` | The files of the organization catalog at {pin['commit'][:12]} do not match the fingerprint pinned in {LOCK_NAME}. Restore the lock from Git, or review the commit and pin it again at a terminal: {SET_COMMAND}. | tests/test_org_catalog.py |
| `OGK-ORG-007` | `org_catalog_cli.py:_set` | --name is lowercase letters, digits, - and _, such as acme. Nothing was written. | tests/test_org_catalog.py |
| `OGK-ORG-008` | `org_catalog_cli.py:_write_pinned` | {error} Without it, the profile uses a record the catalog no longer provides: remove it from the profile first (openguildkit profile remove pack ID {PERSON}){remedy}. Nothing was written. | tests/test_org_catalog.py |
| `OGK-ORG-009` | `org_policy.py:refuse` | {where}: {problem}. Fix it in the organization catalog, then pin the new commit. | tests/test_org_policy.py |
| `OGK-ORG-010` | `org_policy.py:refuse_lowering` | Refused: {' '.join(new.values())} A repository may be stricter than the organization policy, never less strict. Nothing was written. | tests/test_org_policy.py |
| `OGK-ORG-011` | `org_policy_cli.py:ci_copy` | Supply --org-policy and --org-commit together, such as --org-policy ../acme-catalog --org-commit SHA. | tests/test_org_policy.py |
| `OGK-PROFILE-001` | `profile_edits.py:_decline` | Unknown pattern: {pattern_id}. Run openguildkit patterns. | tests/test_profile_commands.py |
| `OGK-PROFILE-002` | `profile_edits.py:_known_rule` | Name one rule as PACK/RULE, such as python/follow-python-style: {value} is not. AGENTS.md lists the rules in force under their pack. Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-003` | `profile_edits.py:_known_rule` | Unknown rule {rule}.{hint} Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-004` | `profile_edits.py:_decline_rule` | agent-workflow is required by OpenGuildKit: its rules cannot be declined. Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-005` | `profile_edits.py:_decline_rule` | Rule {rule} is already declined. Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-006` | `profile_edits.py:_decline_rule` | Rule {rule} is not in force: its pack {pack_id} is not active in this profile, so no task is asked it. Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-007` | `profile_edits.py:_decline_rule` | Rule {rule} is required by the profile (required_rules lists {required[0]}): remove it from the required rules first, at a terminal: openguildkit profile remove required-rule {required[0]} --by INITIALS --reason WHY. Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-008` | `profile_edits.py:_decline_rule` | {rule_id} is the last rule of pack {pack_id} in force: remove the pack (openguildkit profile remove pack {pack_id}) or decline the pattern that brings it, rather than each of its rules. Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-009` | `profile_edits.py:_adopt_rule` | Rule {rule} is not declined (declined rules: {declined}). Nothing was written. | tests/test_rule_decline.py |
| `OGK-PROFILE-010` | `profile_edits.py:_change_tools` | {value} is {'already in' if add else 'not in'} the profile's tools. Nothing was written. | tests/test_profile_commands.py |
| `OGK-PROFILE-011` | `profile_edits.py:_change_list` | Unknown {field}: {value}. Run openguildkit catalog or openguildkit patterns. | tests/test_profile_commands.py |
| `OGK-PROFILE-012` | `profile_edits.py:_change_list` | {value} is {state} the profile's {key}. Nothing was written. | tests/test_profile_commands.py |
| `OGK-PROFILE-013` | `profile_edits.py:_change_list` | agent-workflow is required by OpenGuildKit and cannot be removed. | tests/test_profile_commands.py |
| `OGK-PROFILE-014` | `profile_edits.py:_approval_setting` | profile set approval signed needs --signers PATH and at least one --approver NAME. | tests/test_profile_commands.py |
| `OGK-PROFILE-015` | `profile_edits.py:_max_age_setting` | profile set max-approval-age takes a whole number of days, 1 to 366, or none. Nothing was written. | tests/test_incident.py |
| `OGK-PROFILE-016` | `profile_edits.py:_waivers_setting` | profile set waivers allowed needs at least one --allowed-by NAME and --max-days DAYS. | tests/test_profile_commands.py |
| `OGK-PROFILE-017` | `profile_edits.py:_set` | {field} must be one of {', '.join(allowed)}. | tests/test_profile_commands.py |
| `OGK-PROFILE-018` | `profile_edits.py:_set` | profile set {field} takes one value, not {len(args.more) + 1}. Nothing was written. | tests/test_short_lane.py |
| `OGK-PROFILE-019` | `profile_edits.py:_set` | --{option} belongs to profile set {' '.join(owner)}. Nothing was written. | tests/test_short_lane.py |
| `OGK-PROFILE-020` | `profile_edits.py:_set` | The project is already frozen by {as_dict(profile)[key]['by']} since {as_dict(profile)[key]['on']}. Nothing was written. | tests/test_incident.py |
| `OGK-PROFILE-021` | `profile_edits.py:_set` | {field} is already {value}. Nothing was written. | tests/test_requester.py |
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
| `OGK-PROJECT-023` | `project.py:_add_rule_choices` | Pack {drafts[0]} is a draft written by task retro: review each rule, replace each TODO and rewrite its description before a profile uses it. | tests/e2e/test_task_retro.py |
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
| `OGK-ROUTE-001` | `routing.py:select_boards` | Only a required board can be delegated: {', '.join(unknown)}. | tests/test_brain_selection.py |
| `OGK-ROUTE-002` | `routing.py:select_boards` | Required reviews are unavailable: {', '.join(missing)} not enabled in the profile. Enable them, or name the person who will review with --delegate BOARD=NAME. | tests/test_brain_selection.py |
| `OGK-ROUTE-003` | `routing.py:select_boards` | Give a --reason for adding or removing a board. | tests/test_brain_selection.py |
| `OGK-ROUTE-004` | `routing.py:select_boards` | Board {board_id!r} is not enabled for this project. | tests/test_brain_selection.py |
| `OGK-ROUTE-005` | `routing.py:select_boards` | The project requires the {board_id} review; it cannot be removed. | tests/test_brain_selection.py |
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
| `OGK-TASK-014` | `consultation.py:research_decision` | Unknown research policy: {policy} | tests/test_host_research.py |
| `OGK-TASK-015` | `handoff.py:handoff` | Task {task['id']} has changes requested by {task['decision']['by']}: there is nothing to implement. Next: openguildkit task consult {task['id']} --reuse-answers | tests/test_decided_tasks.py |
| `OGK-TASK-016` | `requester.py:declared` | This project separates who requests a task from who approves it (profile separate-requester on): name the person who asked for the work with --requested-by NAME. Nothing was written. | tests/test_requester.py |
| `OGK-TASK-017` | `requester.py:declared` | --requested-by takes the name of the person who asked for the work, on one line. Nothing was written. | tests/test_requester.py |
| `OGK-TASK-018` | `requester.py:declared` | {name.strip()} is not a principal of {relative}: in a project with signed approvals, the requester is named as their key signs ({', '.join(known[:10]) or 'no principal'}), so that they cannot approve their own request under another name ({section()}). Nothing was written. | tests/test_requester.py |
| `OGK-TASK-019` | `task_files.py:task_path` | {task_id} is a reserved file name on Windows. Choose another task ID. | tests/test_clean_errors.py |
| `OGK-TASK-020` | `task_files.py:task_path` | Use a task ID of up to 64 lowercase letters, digits and separating hyphens. | tests/test_robustness.py |
| `OGK-TASK-021` | `task_files.py:read_task` | {_unknown_task(state, task_id)} | tests/e2e/test_task_retro.py, tests/test_cli_errors.py, tests/test_json_output.py, tests/test_webui.py |
| `OGK-TASK-022` | `task_files.py:_validated_task` | Unsupported or mismatched task record: {path} | tests/test_sarif_commands.py |
| `OGK-TASK-023` | `task_files.py:_validated_task` | Task record {task_id} is damaged: {problem}. Restore {path.relative_to(state.parent).as_posix()} from a backup, or delete that file and open a new task with openguildkit task new. | tests/test_clean_errors.py |
| `OGK-TASK-024` | `tasks_approval.py:require_current_scope` | {stale_review_message(task['id'])} | tests/test_rule_changes.py |
| `OGK-TASK-025` | `tasks_blockers.py:_clearing_evidence` | Clearing evidence must be an existing file or folder of the project, or an https link: {value}. | tests/test_blockers.py |
| `OGK-TASK-026` | `tasks_blockers.py:_check_clearance_signature` | This project requires a signed clearance. Run task clear with --payload FILE, sign the payload, then pass --signature FILE --signer PRINCIPAL. | tests/e2e/test_more_commands.py |
| `OGK-TASK-027` | `tasks_blockers.py:resolve_blocker` | Unknown blocker {blocker_id}. Blockers: {listed}. | tests/e2e/test_more_commands.py |
| `OGK-TASK-028` | `tasks_blockers.py:resolve_blocker` | Blocker {blocker_id} already has a resolution: {first['kind']} by {first['by']} on {first.get('at', '')[:10]}. It stays as recorded; see task blockers. | tests/test_blockers.py |
| `OGK-TASK-029` | `tasks_blockers.py:resolve_blocker` | {expired_waiver_step(task, blocker)} | tests/test_approval_lifecycle.py |
| `OGK-TASK-030` | `tasks_blockers.py:resolve_blocker` | Resolve a verification blocker after approval and before completion. | tests/test_blockers.py |
| `OGK-TASK-031` | `tasks_blockers.py:resolve_blocker` | {problem} | tests/test_roles.py |
| `OGK-TASK-032` | `tasks_blockers.py:resolve_blocker` | The project's policy allows no waiver. {clear}; if it cannot be met, the person withdraws the approval: {revoke_command(task['id'])}. | tests/test_approval_lifecycle.py |
| `OGK-TASK-033` | `tasks_blockers.py:resolve_blocker` | The project's policy allows no waiver. {clear}, or the person requests changes: openguildkit task decide {task['id']} --request-changes --by INITIALS --reason TEXT. | tests/test_blockers.py |
| `OGK-TASK-034` | `tasks_blockers.py:resolve_blocker` | {by} cannot grant waivers. Allowed: {', '.join(waivers['allowed_by'])}. | tests/test_blockers.py |
| `OGK-TASK-035` | `tasks_blockers.py:resolve_blocker` | {problem} | tests/test_roles.py |
| `OGK-TASK-036` | `tasks_blockers.py:resolve_blocker` | A waiver lasts between 1 and {waivers['max_days']} days. | tests/test_blockers.py |
| `OGK-TASK-037` | `tasks_close_cli.py:_closing` | {'The task cannot be declared done:\n- ' + '\n- '.join(lane)} | tests/test_short_lane.py |
| `OGK-TASK-038` | `tasks_close_cli.py:_closing` | {'The task cannot be declared done:\n- ' + '\n- '.join(blocking)} | tests/test_alerts.py |
| `OGK-TASK-039` | `tasks_close_cli.py:_closing` | Name the person who hands the evidence to a follow-up task: --by INITIALS. | tests/test_results.py |
| `OGK-TASK-040` | `tasks_close_cli.py:_closing` | {f"{plural(len(set_aside), 'data protection, security or AI rule')} {('is' if len(set_aside) == 1 else 'are')} declared not applicable:\n- " + '\n- '.join(set_aside) + f'\nA person confirms each: openguildkit task complete {args.id} --by INITIALS, at a terminal.'} | tests/test_results.py |
| `OGK-TASK-041` | `tasks_close_cli.py:_closing` | {refusal} | tests/test_results.py |
| `OGK-TASK-042` | `tasks_close_cli.py:_declaration_checks` | {check_id} is not a check command of the task: {', '.join(commands) or 'none'}. | tests/test_results.py |
| `OGK-TASK-043` | `tasks_close_cli.py:_declaration_checks` | {DECLARATION_REFUSAL} | tests/test_results.py |
| `OGK-TASK-044` | `tasks_close_cli.py:_cannot_run` | Say why {args.cannot_run} cannot run here, in at least {MIN_REASON_WORDS} words: --reason "The sandbox has no network for npm ci." | tests/test_results.py |
| `OGK-TASK-045` | `tasks_close_cli.py:_cannot_run` | {args.cannot_run} passes in this environment: nothing to declare. Run task verify {args.id} to record it as passed. | tests/test_results.py |
| `OGK-TASK-046` | `tasks_close_cli.py:_withdraw` | {declaration['owner']} declared it: only they withdraw it. | tests/test_results.py |
| `OGK-TASK-047` | `tasks_close_cli.py:_verify_payload` | --cannot-run and --withdraw concern a check command: run them without --chaosfolk. | tests/test_results.py |
| `OGK-TASK-048` | `tasks_close_cli.py:run_diff_review` | {args.submit.as_posix()}: {error} | tests/test_delivered_review.py |
| `OGK-TASK-049` | `tasks_closing.py:record_result` | The task has an expected outcome: report at least one acceptance criterion. Run task result ID --template. | tests/test_results.py |
| `OGK-TASK-050` | `tasks_closing.py:complete_task` | {'The task cannot be declared done:\n- ' + '\n- '.join(problems)} | tests/test_chaosfolk_results.py |
| `OGK-TASK-051` | `tasks_closing.py:complete_task` | {plural(len(sensitive['points']), 'data protection, security or AI point')} {'is' if len(sensitive['points']) == 1 else 'are'} skipped, failed or declared not applicable as a pack. A person confirms closing over them: openguildkit task complete {task['id']} --by INITIALS, at a terminal. | tests/test_results.py |
| `OGK-TASK-052` | `tasks_closing.py:record_decision` | {decided} | tests/test_decided_tasks.py |
| `OGK-TASK-053` | `tasks_closing.py:record_decision` | Resolve each blocker before approving: {', '.join(open_blockers)}. Clear it with evidence (task clear), waive it if the project allows (task waive), or request changes. | tests/test_blockers.py |
| `OGK-TASK-054` | `tasks_closing.py:revoke_approval` | {decided_message(task)} | tests/test_approval_lifecycle.py |
| `OGK-TASK-055` | `tasks_closing.py:record_authorization` | Name the target as a host or tool name, without a query, an address or private details. | tests/test_hosts.py |
| `OGK-TASK-056` | `tasks_consult_cli.py:input_file` | {path.as_posix()}: {error} | tests/e2e/test_more_commands.py, tests/test_robustness.py |
| `OGK-TASK-057` | `tasks_consult_cli.py:run_questions` | {short_lane.no_questions_message(args.id)} | tests/test_short_lane.py |
| `OGK-TASK-058` | `tasks_consult_cli.py:run_route` | {short_lane.no_route_message(args.id)} | tests/test_short_lane.py |
| `OGK-TASK-059` | `tasks_consult_cli.py:_light_answers` | {short_lane.options_message(args.id, used)} | tests/test_short_lane.py |
| `OGK-TASK-060` | `tasks_consult_cli.py:_light_answers` | {problem} | tests/test_short_lane.py |
| `OGK-TASK-061` | `tasks_consult_cli.py:run_pass` | {args.file.as_posix()}: the pass is recorded as failed. {error}
Fix these points in the file and send it again: openguildkit task submit {args.id} --file {args.file.as_posix()} | tests/test_robustness.py |
| `OGK-TASK-062` | `tasks_decide_cli.py:run_revoke` | {refusal} | tests/test_approval_lifecycle.py |
| `OGK-TASK-063` | `tasks_decide_cli.py:run_decide` | {decided_message(task, approval_problem(task, profile, catalog, root))} | tests/test_decided_tasks.py |
| `OGK-TASK-064` | `tasks_decide_cli.py:run_decide` | {lane} | tests/test_short_lane.py |
| `OGK-TASK-065` | `tasks_decide_cli.py:run_decide` | {same} | tests/test_requester.py |
| `OGK-TASK-066` | `tasks_decide_cli.py:run_decide` | --signed-at goes with approving in a project that requires signed approvals. Nothing was written. | tests/test_decisions.py |
| `OGK-TASK-067` | `tasks_decide_cli.py:run_decide` | This project requires a signed approval: run task decision-payload, sign it with ssh-keygen -Y sign -n {NAMESPACE}, then pass --signature FILE --signer PRINCIPAL. | tests/test_decisions.py |
| `OGK-TASK-068` | `tasks_decide_cli.py:run_decide` | {outside} | tests/test_roles.py |
| `OGK-TASK-069` | `tasks_decide_cli.py:run_decide` | {'Approval is blocked:\n- ' + '\n- '.join(blocking)} | tests/test_alert_resolution.py |
| `OGK-TASK-070` | `tasks_decide_cli.py:run_decide` | Approval requires a person at an interactive terminal. | tests/test_terminal.py |
| `OGK-TASK-071` | `tasks_decide_cli.py:run_resolve` | A waiver needs a person at an interactive terminal. | tests/e2e/test_more_commands.py |
| `OGK-TASK-072` | `tasks_decide_cli.py:run_decision_payload` | {same} | tests/test_requester.py |
| `OGK-TASK-073` | `tasks_decide_cli.py:run_authorize` | {refusal} | tests/test_hosts.py |
| `OGK-TASK-074` | `tasks_list_cli.py:_retro_record` | The exported record {where} was written before task {task_id} was completed, so it has no closing to read. Look at it with openguildkit task list --decisions; once the task is closed, openguildkit task export {task_id} writes it. | tests/e2e/test_task_retro.py |
| `OGK-TASK-075` | `tasks_list_cli.py:run_retro` | {'Name the closed task to read, openguildkit task retro ID, or count the whole project with openguildkit task retro --all (task retro ID reads one task and --all counts them all).' if not args.id else 'task retro ID reads one task and --all counts the project: give one of them.'} | tests/e2e/test_task_retro.py |
| `OGK-TASK-076` | `tasks_list_cli.py:run_retro` | --min counts tasks across the project: use it with openguildkit task retro --all. | tests/e2e/test_task_retro.py |
| `OGK-TASK-077` | `tasks_list_cli.py:run_retro` | --draft-rules drafts rules from what comes back across the project: use it with openguildkit task retro --all. | tests/e2e/test_task_retro.py |
| `OGK-TASK-078` | `tasks_list_cli.py:run_retro` | --min counts tasks: give a number of 1 or more. | tests/e2e/test_task_retro.py |
| `OGK-TASK-079` | `tasks_list_cli.py:run_retro` | {state_refusal(task, 'Only a closed task has a retrospective.')} | tests/e2e/test_task_retro.py |
| `OGK-TASK-080` | `tasks_record.py:board_brief_problem` | Task record {task['id']} is damaged: {problem}. Restore it from a backup or consult again. | tests/test_board_entries.py |
| `OGK-TASK-081` | `tasks_record.py:validate_brief` | Supply a task brief. | tests/test_brief_revision.py |
| `OGK-TASK-082` | `tasks_review.py:record_consultation` | {decided_message(task)} | tests/test_rule_changes.py |
| `OGK-TASK-083` | `tasks_review.py:record_consultation` | {stale_review_message(task['id'])} | tests/test_rule_changes.py |
| `OGK-TASK-084` | `tasks_review.py:record_consultation` | {decided_message(task) or f"The review of {task['id']} is recorded and waits for the person's decision: they approve it or request changes at their terminal (openguildkit task decide {task['id']}), and you consult again after a change request."} | tests/test_rule_changes.py |
| `OGK-TASK-085` | `tasks_review.py:submit_pass` | The {board_id} pass was not started on the current consultation. Run openguildkit task pass {task['id']} {board_id}, review through that brief, then submit the entry. | tests/test_board_entries.py |
| `OGK-TASK-086` | `workflow.py:validate_deliberation` | {nothing_to_deliberate(task['id'])} | tests/test_deliberation.py |
| `OGK-TASK-087` | `workflow.py:validate_deliberation` | This deliberation belongs to another consultation. | tests/test_robustness.py |
| `OGK-TASK-088` | `workflow.py:validate_deliberation` | responses must be a list. | tests/test_robustness.py |
| `OGK-TASK-089` | `workflow.py:validate_deliberation` | {f"The deliberation has {len(problems)} problem{('s' if len(problems) > 1 else '')}:\n- " + '\n- '.join(problems)} | tests/test_robustness.py |
| `OGK-TASK-090` | `workflow.py:validate_deliberation` | Some disagreements remain ({', '.join(open_items)}): say in decision_needed which decision the responsible person must take. {RESOLUTION_RULE} | tests/e2e/test_more_commands.py, tests/test_robustness.py |
| `OGK-TOOLS-001` | `tool_connections.py:_mcp_file` | {path.as_posix()} is not valid JSON: {error} | tests/test_clean_errors.py |
| `OGK-TOOLS-002` | `tool_connections.py:_write_host` | {path} already defines mcp_servers.{clash[0]} outside the OpenGuildKit block. Rename or remove it first. | tests/test_tools.py |
| `OGK-TOOLS-003` | `tool_connections.py:check_settings` | {'Settings are missing. ' + '; '.join(blocked) + '.'} | tests/test_tools.py |
| `OGK-TOOLS-004` | `tool_connections.py:apply_connections` | {path} already defines {item['key']} with other settings. Rename or remove it first. | tests/test_tools.py |
| `OGK-TOOLS-005` | `tool_connections.py:_host_entries` | {path.as_posix()}: {error.__cause__} | tests/test_clean_errors.py |
| `OGK-TOOLS-006` | `tools.py:resolve_tool` | Unknown tool: {name}. Run openguildkit tools list. | tests/test_tools.py |
| `OGK-TOOLS-007` | `tools.py:choose_server` | {tool['id']}/{server_id} is a community server: review its source, then pass --community. | tests/test_tools.py |
| `OGK-TOOLS-008` | `tools.py:_settings` | {label}: {item['name']} must be a plain value such as a name or a host, never a credential. | tests/test_tools.py |
| `OGK-TOOLS-009` | `tools.py:_settings` | {label} has no setting {', '.join(unknown)}. | tests/test_tools.py |
| `OGK-TOOLS-010` | `tools.py:_plan_options` | --read-only selects a live server. Use --mock separately for synthetic data. | tests/test_tools.py |
| `OGK-TOOLS-011` | `tools.py:_plan_options` | --set must be a plain value such as a name or a host, never a credential: a token stays in each person's environment, named with --token-env TOOL=VARIABLE. | tests/test_tools.py |
| `OGK-TOOLS-012` | `tools.py:_plan_options` | --token-env names an environment variable, such as JIRA_TOKEN, for a remote server; never the token itself, which stays in each person's environment. | tests/test_tools.py |
| `OGK-TOOLS-013` | `tools_cli.py:_host` | OpenGuildKit writes MCP settings for {' and '.join(HOSTS)}, and the project's host is {host or 'not set'}. Add --host {HOSTS[0]} or --host {HOSTS[1]} to this command to write them for that agent, or change the project's host with openguildkit profile set host. For another agent, run openguildkit tools plan ID --host codex and adapt the server settings to that agent. | tests/test_gemini_host.py |
| `OGK-TOOLS-014` | `tools_cli.py:_confirm_live` | {f"Review the plan of {', '.join(live)} (openguildkit tools plan), then write it with: " + _apply_command(args, host, plan, tools) + ' --yes'} | tests/e2e/test_tool_mocks.py |
| `OGK-TOOLS-015` | `tools_cli.py:_confirm_live` | Nothing written: the plan was not accepted. | tests/test_tools.py |
| `OGK-TOOLS-016` | `tools_cli.py:_scenario` | .openguildkit/catalog/tool-mocks/{SCENARIO} exists. Edit it, or pass --force to replace it. | tests/test_tools.py |
| `OGK-TOOLS-017` | `tools_cli.py:_scenario` | {examined} Name the tools: openguildkit tools scenario TOOL [TOOL ...] (those with a mock: openguildkit tools list --mocks). | tests/test_doc_examples.py |
| `OGK-TOOLS-018` | `tools_cli.py:_call` | --json lists the tools of the mock: run openguildkit tools call {args.id} --json, without a tool name. | tests/test_tools.py |
| `OGK-TOOLS-019` | `tools_cli.py:_call` | --args is not valid JSON: {error} | tests/test_tools.py |

## JSON output

With `--json`, a command prints its answer as JSON on standard output.
With `OPENGUILDKIT_JSON_ENVELOPE=1` in the environment, every answer comes in one object, `{"schema_version": 1, "command": "task checks", "data": ...}`, whose `data` is the answer printed without the variable; the default keeps the shape scripts and the web interface read.
Under `--json`, an error is JSON on standard output too, with the same exit code and its line on standard error: `{"schema_version": 1, "error": {"code": "OGK-TASK-004", "message": ..., "next": ...}}`.
`code` is null for an error that has no code yet, and `next` is the command the message names, or null.
