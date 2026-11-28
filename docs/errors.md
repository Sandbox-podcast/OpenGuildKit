# Error codes

For: a person or an agent that reads an error of the CLI and looks for where it comes from.

An error that carries a code starts with it: `OpenGuildKit [OGK-TASK-004]: Task already exists: x`, and under `--json` its object holds the same code in `error.code` ([JSON output](#json-output)).
A code is raised from one place and keeps its meaning when its words change: search the code, not the sentence. `python scripts/build_errors.py` writes this page and [`agents/errors.json`](agents/errors.json) from the code; the other errors still print `OpenGuildKit: message`.
The register holds the message of each code as the code writes it and the tests that cite it: `grep -n OGK-TASK-004 docs/agents/errors.json`. This page lists the codes by module and function.

## Codes by module

### alerts.py

- `_report_text`: OGK-ALERTS-002
- `accept_alert`: OGK-ALERTS-009, OGK-ALERTS-017
- `check_scope`: OGK-ALERTS-001
- `find_alert`: OGK-ALERTS-005
- `load_register`: OGK-ALERTS-013
- `read_report`: OGK-ALERTS-003, OGK-ALERTS-004, OGK-ALERTS-010, OGK-ALERTS-011, OGK-ALERTS-012
- `set_severity`: OGK-ALERTS-015, OGK-ALERTS-016
- `set_status`: OGK-ALERTS-006, OGK-ALERTS-007, OGK-ALERTS-008, OGK-ALERTS-014

### alerts_cli.py

- `task_command`: OGK-ALERTS-018

### allowlist.py

- `load_allow`: OGK-GUARD-001, OGK-GUARD-002, OGK-GUARD-022

### audit_cli.py

- `run`: OGK-AUDIT-001, OGK-AUDIT-007, OGK-AUDIT-008

### audit_log.py

- `_append`: OGK-AUDIT-003, OGK-AUDIT-004
- `_bad`: OGK-AUDIT-005
- `log_path`: OGK-AUDIT-002

### board_brief.py

- `board_brief`: OGK-BOARD-018
- `pack_rules`: OGK-BOARD-017

### board_entries.py

- `_check_reference`: OGK-BOARD-006, OGK-BOARD-007, OGK-BOARD-008, OGK-BOARD-020
- `_evidence_day`: OGK-BOARD-003, OGK-BOARD-004, OGK-BOARD-005
- `_evidence_outcome`: OGK-BOARD-019
- `_project_path`: OGK-BOARD-015
- `_text_list`: OGK-BOARD-002
- `required_text`: OGK-BOARD-001
- `validate_board_entry`: OGK-BOARD-009, OGK-BOARD-010, OGK-BOARD-016, OGK-BOARD-021
- `validate_review`: OGK-BOARD-011, OGK-BOARD-012, OGK-BOARD-013, OGK-BOARD-022, OGK-BOARD-023, OGK-BOARD-024

### brains.py

- `write_brain_skeleton`: OGK-BOARD-014, OGK-BOARD-025, OGK-BOARD-026, OGK-BOARD-027

### catalog.py

- `_add_central_policy`: OGK-CATALOG-066, OGK-CATALOG-067
- `_check_links`: OGK-CATALOG-068, OGK-CATALOG-069
- `_load_entry`: OGK-CATALOG-051, OGK-CATALOG-052, OGK-CATALOG-053
- `_merged_records`: OGK-CATALOG-065
- `_organization_records`: OGK-CATALOG-060, OGK-CATALOG-061, OGK-CATALOG-062, OGK-CATALOG-063, OGK-CATALOG-064
- `_read_records`: OGK-CATALOG-057
- `_validate_board_review`: OGK-CATALOG-050
- `_validate_core_roles`: OGK-CATALOG-035, OGK-CATALOG-036
- `_validate_evidence`: OGK-CATALOG-028, OGK-CATALOG-029, OGK-CATALOG-030
- `_validate_lens_concerns`: OGK-CATALOG-048, OGK-CATALOG-049
- `_validate_lens_surfaces`: OGK-CATALOG-047
- `_validate_pack`: OGK-CATALOG-020, OGK-CATALOG-021, OGK-CATALOG-022, OGK-CATALOG-023, OGK-CATALOG-024
- `_validate_pattern`: OGK-CATALOG-037, OGK-CATALOG-038, OGK-CATALOG-039, OGK-CATALOG-040, OGK-CATALOG-041, OGK-CATALOG-042, OGK-CATALOG-043, OGK-CATALOG-044, OGK-CATALOG-045, OGK-CATALOG-046
- `_validate_records`: OGK-CATALOG-025, OGK-CATALOG-026, OGK-CATALOG-027
- `_validate_rule`: OGK-CATALOG-031, OGK-CATALOG-032, OGK-CATALOG-033, OGK-CATALOG-034
- `load_catalog`: OGK-CATALOG-070
- `read_record_files`: OGK-CATALOG-058, OGK-CATALOG-059
- `record_files`: OGK-CATALOG-005
- `validate_day`: OGK-CATALOG-013, OGK-CATALOG-014
- `validate_dependencies`: OGK-CATALOG-054, OGK-CATALOG-055, OGK-CATALOG-056
- `validate_fields`: OGK-CATALOG-006, OGK-CATALOG-007, OGK-CATALOG-008
- `validate_id`: OGK-CATALOG-011
- `validate_list`: OGK-CATALOG-012
- `validate_sources`: OGK-CATALOG-015, OGK-CATALOG-016, OGK-CATALOG-017, OGK-CATALOG-018, OGK-CATALOG-019
- `validate_text`: OGK-CATALOG-009, OGK-CATALOG-010

### catalog_cli.py

- `print_brains`: OGK-CATALOG-002
- `print_patterns`: OGK-CATALOG-001, OGK-CATALOG-110

### catalog_queries.py

- `recorded_value`: OGK-CATALOG-003, OGK-CATALOG-004

### check_cli.py

- `_check_project`: OGK-CHECK-013, OGK-CHECK-014, OGK-CHECK-015
- `_host`: OGK-CHECK-006
- `_require_sarif_options`: OGK-CHECK-002, OGK-CHECK-003, OGK-CHECK-004, OGK-CHECK-005
- `check`: OGK-CHECK-001

### ci.py

- `_committed_bytes`: OGK-CI-001
- `_committed_file`: OGK-CI-002, OGK-CI-003
- `check_export`: OGK-CI-005, OGK-CI-006
- `read_policy_pack`: OGK-CI-004

### cli.py

- `main`: OGK-CLI-001, OGK-CLI-002

### clock.py

- `_source_date_epoch`: OGK-CORE-001

### connect_cli.py

- `_mcp`: OGK-INIT-001, OGK-INIT-006

### consultation.py

- `research_decision`: OGK-TASK-014

### controls.py

- `_frameworks`: OGK-CONTROL-012, OGK-CONTROL-015
- `_mapping`: OGK-CONTROL-002, OGK-CONTROL-003, OGK-CONTROL-004, OGK-CONTROL-005, OGK-CONTROL-006, OGK-CONTROL-007, OGK-CONTROL-008, OGK-CONTROL-009, OGK-CONTROL-010, OGK-CONTROL-011, OGK-CONTROL-014
- `_require_line`: OGK-CONTROL-001
- `update_page`: OGK-CONTROL-021
- `validate`: OGK-CONTROL-013, OGK-CONTROL-016, OGK-CONTROL-017, OGK-CONTROL-018, OGK-CONTROL-019, OGK-CONTROL-020

### decisions.py

- `_ssh_verify`: OGK-DECISION-010, OGK-DECISION-015
- `changed_paths_since`: OGK-DECISION-012
- `check_decision`: OGK-DECISION-016
- `check_decision_seal`: OGK-DECISION-006, OGK-DECISION-007, OGK-DECISION-008
- `committed_signers`: OGK-DECISION-004, OGK-DECISION-005, OGK-DECISION-013
- `signing_time`: OGK-DECISION-001, OGK-DECISION-002
- `verify_recorded_signature`: OGK-DECISION-011
- `verify_signature`: OGK-DECISION-009, OGK-DECISION-014
- `verify_time`: OGK-DECISION-003

### deliverables.py

- `_decision_refusal`: OGK-RESULT-035
- `_validate`: OGK-RESULT-036, OGK-RESULT-037, OGK-RESULT-038, OGK-RESULT-039, OGK-RESULT-040
- `load_deliverables`: OGK-RESULT-041, OGK-RESULT-042
- `new_draft`: OGK-RESULT-007, OGK-RESULT-008, OGK-RESULT-043, OGK-RESULT-044
- `project_path`: OGK-RESULT-001, OGK-RESULT-002
- `utm_link`: OGK-RESULT-003, OGK-RESULT-004, OGK-RESULT-005, OGK-RESULT-006

### delivered_review.py

- `board_brief`: OGK-RESULT-010
- `delivered_change`: OGK-RESULT-047
- `record_findings`: OGK-RESULT-011
- `require_reviewable`: OGK-RESULT-009, OGK-RESULT-032, OGK-RESULT-045, OGK-RESULT-046

### detect.py

- `_json_manifest`: OGK-CORE-002

### docs_cli.py

- `_share_add`: OGK-DOCS-027
- `_share_revoke`: OGK-DOCS-028
- `_share_verify`: OGK-DOCS-005
- `deliverable`: OGK-DOCS-001, OGK-DOCS-002, OGK-DOCS-026

### errors.py

- `file_error`: OGK-FILE-001, OGK-FILE-002, OGK-FILE-003, OGK-FILE-004

### evidence_cli.py

- `_day`: OGK-EVIDENCE-002
- `_signature`: OGK-EVIDENCE-005
- `_verify`: OGK-EVIDENCE-003, OGK-EVIDENCE-006
- `run`: OGK-EVIDENCE-001, OGK-EVIDENCE-004

### features.py

- `_feature`: OGK-FEATURE-007, OGK-FEATURE-008, OGK-FEATURE-009, OGK-FEATURE-010
- `_option`: OGK-FEATURE-004, OGK-FEATURE-005, OGK-FEATURE-006
- `load_features`: OGK-FEATURE-011

### features_cli.py

- `_refuse`: OGK-FEATURE-012
- `_targets`: OGK-FEATURE-001
- `edit`: OGK-FEATURE-002, OGK-FEATURE-003

### git.py

- `required`: OGK-CORE-003

### guard.py

- `_decide_hook`: OGK-GUARD-006, OGK-GUARD-019
- `edited_paths`: OGK-GUARD-003, OGK-GUARD-004, OGK-GUARD-005

### guard_ci.py

- `_git_lines`: OGK-GUARD-020
- `ci_guard`: OGK-GUARD-007, OGK-GUARD-008

### guard_export.py

- `_refuse_foreign_record`: OGK-GUARD-009, OGK-GUARD-010
- `export_decision`: OGK-GUARD-017
- `export_withdrawal`: OGK-GUARD-012, OGK-GUARD-018, OGK-GUARD-021
- `record_shape`: OGK-GUARD-011

### guard_records.py

- `exported_decisions`: OGK-GUARD-013

### handoff.py

- `handoff`: OGK-TASK-015, OGK-TASK-094

### host_coverage.py

- `run`: OGK-HOST-001

### hosts.py

- `_apply_claude`: OGK-HOST-013, OGK-HOST-014
- `_apply_codex`: OGK-HOST-007, OGK-HOST-008, OGK-HOST-015
- `_check_hook_groups`: OGK-HOST-004
- `_codex_config`: OGK-HOST-011
- `_codex_disable_web_search`: OGK-HOST-005
- `_codex_lift_web_search`: OGK-HOST-012
- `_gemini_hooks_config`: OGK-HOST-006
- `_read_settings`: OGK-HOST-002, OGK-HOST-003

### init_cli.py

- `_confirm_rule_plan`: OGK-INIT-002
- `_require_answers`: OGK-INIT-003
- `init`: OGK-INIT-004, OGK-INIT-005

### integrations.py

- `install_agent_files`: OGK-CI-007, OGK-CI-008

### lock.py

- `_validated_lock`: OGK-CORE-004, OGK-CORE-015, OGK-CORE-016, OGK-CORE-017, OGK-CORE-018
- `apply_lock`: OGK-CORE-020
- `central_policy`: OGK-CORE-019
- `require_instructions`: OGK-CORE-022

### managed.py

- `run`: OGK-CORE-005, OGK-CORE-006, OGK-CORE-023

### market.py

- `_competitor`: OGK-MARKET-005
- `_day`: OGK-MARKET-001, OGK-MARKET-002, OGK-MARKET-003
- `_list`: OGK-MARKET-004
- `_one_text_line`: OGK-MARKET-015
- `_source`: OGK-MARKET-016
- `_watch`: OGK-MARKET-032
- `add_competitor`: OGK-MARKET-030
- `describe`: OGK-MARKET-029
- `dossier_path`: OGK-MARKET-014
- `load_dossier`: OGK-MARKET-008
- `mark_checked`: OGK-MARKET-034
- `mark_provided`: OGK-MARKET-009
- `set_unknown`: OGK-MARKET-031
- `validate_dossier`: OGK-MARKET-017, OGK-MARKET-018, OGK-MARKET-019, OGK-MARKET-020, OGK-MARKET-021, OGK-MARKET-022, OGK-MARKET-023
- `validate_watch`: OGK-MARKET-006, OGK-MARKET-007, OGK-MARKET-024, OGK-MARKET-025, OGK-MARKET-026, OGK-MARKET-027, OGK-MARKET-028
- `watch_source`: OGK-MARKET-033

### market_cli.py

- `_changed`: OGK-MARKET-011
- `_due`: OGK-MARKET-035
- `_person_reviews`: OGK-MARKET-012
- `_require`: OGK-MARKET-010
- `run`: OGK-MARKET-013, OGK-MARKET-036

### mcp_mock.py

- `_validate_records`: OGK-MCP-001, OGK-MCP-006, OGK-MCP-007, OGK-MCP-008, OGK-MCP-009, OGK-MCP-010
- `_validate_serving`: OGK-MCP-011, OGK-MCP-012, OGK-MCP-013, OGK-MCP-014, OGK-MCP-015, OGK-MCP-016
- `apply_scenario`: OGK-MCP-004, OGK-MCP-005, OGK-MCP-029
- `check_synthetic`: OGK-MCP-003
- `validate_mock`: OGK-MCP-002, OGK-MCP-017, OGK-MCP-018, OGK-MCP-019, OGK-MCP-020, OGK-MCP-021, OGK-MCP-022, OGK-MCP-023, OGK-MCP-024, OGK-MCP-025, OGK-MCP-026, OGK-MCP-027, OGK-MCP-028

### org_catalog.py

- `_contents`: OGK-ORG-014
- `_listed_files`: OGK-ORG-013
- `_named_folder`: OGK-ORG-002
- `organization_in`: OGK-ORG-006
- `parse_copies`: OGK-ORG-001
- `read_files`: OGK-ORG-003, OGK-ORG-004, OGK-ORG-005
- `refuse`: OGK-ORG-015
- `validate_history`: OGK-ORG-016

### org_catalog_cli.py

- `_accept`: OGK-ORG-019, OGK-ORG-020
- `_person`: OGK-ORG-017
- `_set`: OGK-ORG-007, OGK-ORG-018
- `_write_pinned`: OGK-ORG-008

### org_policy.py

- `given`: OGK-ORG-022
- `parse`: OGK-ORG-021
- `refuse`: OGK-ORG-009
- `refuse_lowering`: OGK-ORG-010

### org_policy_cli.py

- `check_policy`: OGK-ORG-012
- `ci_copy`: OGK-ORG-011

### patterns.py

- `check_pattern_choices`: OGK-CORE-007

### portal_verification.py

- `_json`: OGK-PORTAL-005, OGK-PORTAL-006
- `_origin`: OGK-PORTAL-004
- `redirect_request`: OGK-PORTAL-001
- `verify_portal`: OGK-PORTAL-002, OGK-PORTAL-003, OGK-PORTAL-007, OGK-PORTAL-008, OGK-PORTAL-009

### profile_changes.py

- `edit`: OGK-PROFILE-032, OGK-PROFILE-033, OGK-PROFILE-036
- `refuse`: OGK-PROFILE-034

### profile_cli.py

- `_confirm`: OGK-PROFILE-035

### profile_edits.py

- `_adopt`: OGK-PROFILE-022, OGK-PROFILE-023
- `_adopt_rule`: OGK-PROFILE-009
- `_approval_setting`: OGK-PROFILE-014
- `_approver_roles_setting`: OGK-PROFILE-027, OGK-PROFILE-028, OGK-PROFILE-029
- `_change_list`: OGK-PROFILE-011, OGK-PROFILE-012, OGK-PROFILE-013
- `_change_tools`: OGK-PROFILE-010
- `_decline`: OGK-PROFILE-001, OGK-PROFILE-024
- `_decline_rule`: OGK-PROFILE-004, OGK-PROFILE-005, OGK-PROFILE-006, OGK-PROFILE-007, OGK-PROFILE-008
- `_known_rule`: OGK-PROFILE-002, OGK-PROFILE-003
- `_light_paths_setting`: OGK-PROFILE-031
- `_max_age_setting`: OGK-PROFILE-015
- `_restricted_setting`: OGK-PROFILE-030
- `_set`: OGK-PROFILE-017, OGK-PROFILE-018, OGK-PROFILE-019, OGK-PROFILE-020, OGK-PROFILE-021
- `_waivers_setting`: OGK-PROFILE-016
- `rule_argument`: OGK-PROFILE-025, OGK-PROFILE-026

### project.py

- `_add_agent_settings`: OGK-PROJECT-020, OGK-PROJECT-021
- `_add_approval`: OGK-PROJECT-068, OGK-PROJECT-069, OGK-PROJECT-070, OGK-PROJECT-071, OGK-PROJECT-072
- `_add_options`: OGK-PROJECT-024, OGK-PROJECT-025, OGK-PROJECT-073, OGK-PROJECT-074, OGK-PROJECT-075
- `_add_rule_choices`: OGK-PROJECT-022, OGK-PROJECT-023
- `_approval_roles`: OGK-PROJECT-012, OGK-PROJECT-055, OGK-PROJECT-056
- `_changes`: OGK-PROJECT-057, OGK-PROJECT-058
- `_chosen_patterns`: OGK-PROJECT-019
- `_components`: OGK-PROJECT-004, OGK-PROJECT-047, OGK-PROJECT-048, OGK-PROJECT-049, OGK-PROJECT-050
- `_decision_text`: OGK-PROJECT-007
- `_declined_rules`: OGK-PROJECT-009, OGK-PROJECT-010, OGK-PROJECT-011, OGK-PROJECT-054
- `_resolutions`: OGK-PROJECT-015, OGK-PROJECT-061, OGK-PROJECT-062, OGK-PROJECT-063, OGK-PROJECT-064, OGK-PROJECT-065
- `_texts`: OGK-PROJECT-001, OGK-PROJECT-002
- `_yes_no`: OGK-PROJECT-006
- `catalog_ids`: OGK-PROJECT-003
- `decision_record`: OGK-PROJECT-051
- `declined_entries`: OGK-PROJECT-008, OGK-PROJECT-052, OGK-PROJECT-053
- `load_profile`: OGK-PROJECT-026, OGK-PROJECT-027, OGK-PROJECT-028
- `pattern_entries`: OGK-PROJECT-013, OGK-PROJECT-014, OGK-PROJECT-059, OGK-PROJECT-060
- `project_context`: OGK-PROJECT-005
- `project_root`: OGK-PROJECT-045
- `restricted_paths`: OGK-PROJECT-016
- `state_path`: OGK-PROJECT-046
- `validate_profile`: OGK-PROJECT-017, OGK-PROJECT-018, OGK-PROJECT-066, OGK-PROJECT-067

### project_instructions.py

- `_read_instructions`: OGK-PROJECT-031, OGK-PROJECT-032
- `check_instructions`: OGK-PROJECT-076, OGK-PROJECT-077
- `initialize`: OGK-PROJECT-079
- `merged_instructions`: OGK-PROJECT-029, OGK-PROJECT-030, OGK-PROJECT-078

### project_mcp.py

- `_check_path`: OGK-PROJECT-033
- `_project`: OGK-PROJECT-080

### project_rules.py

- `require_resolved_conflicts`: OGK-RULE-001
- `task_scope_profile`: OGK-RULE-028

### project_setup.py

- `_norm_answers`: OGK-PROJECT-034, OGK-PROJECT-035, OGK-PROJECT-036, OGK-PROJECT-037
- `complete_answers`: OGK-PROJECT-081
- `setup_profile`: OGK-PROJECT-038, OGK-PROJECT-039

### projects_cli.py

- `read_policy`: OGK-PROJECT-042, OGK-PROJECT-043, OGK-PROJECT-044, OGK-PROJECT-084, OGK-PROJECT-085
- `run`: OGK-PROJECT-040, OGK-PROJECT-041, OGK-PROJECT-082

### prompts.py

- `prompt_choices`: OGK-BOARD-028
- `prompt_questions`: OGK-BOARD-029

### publishing.py

- `_check_dedication`: OGK-PUBLISH-011, OGK-PUBLISH-012
- `_exported_files`: OGK-PUBLISH-001
- `_share_end`: OGK-PUBLISH-013, OGK-PUBLISH-014, OGK-PUBLISH-015
- `_shared_item`: OGK-PUBLISH-006, OGK-PUBLISH-007
- `add_share`: OGK-PUBLISH-010, OGK-PUBLISH-017
- `export_docs`: OGK-PUBLISH-002, OGK-PUBLISH-003, OGK-PUBLISH-004, OGK-PUBLISH-005, OGK-PUBLISH-016
- `portal_space`: OGK-PUBLISH-008, OGK-PUBLISH-009
- `revoke_share`: OGK-PUBLISH-018, OGK-PUBLISH-019, OGK-PUBLISH-020

### questionnaire.py

- `_assumptions`: OGK-RESULT-015
- `_optional_answers`: OGK-RESULT-012, OGK-RESULT-013
- `require_concerns`: OGK-RESULT-014
- `task_questions`: OGK-RESULT-048
- `validate_answers`: OGK-RESULT-016, OGK-RESULT-017, OGK-RESULT-018, OGK-RESULT-019, OGK-RESULT-020, OGK-RESULT-049, OGK-RESULT-050, OGK-RESULT-051

### references.py

- `_merge_family`: OGK-DOCS-013, OGK-DOCS-014
- `_validate_family`: OGK-DOCS-010, OGK-DOCS-011, OGK-DOCS-012
- `_validate_links`: OGK-DOCS-006, OGK-DOCS-007, OGK-DOCS-008, OGK-DOCS-009
- `check_reference_links`: OGK-DOCS-018, OGK-DOCS-019, OGK-DOCS-020, OGK-DOCS-021
- `find_references`: OGK-DOCS-003, OGK-DOCS-004, OGK-DOCS-029, OGK-DOCS-030
- `load_references`: OGK-DOCS-015, OGK-DOCS-016, OGK-DOCS-017
- `with_pattern_references`: OGK-DOCS-022, OGK-DOCS-023, OGK-DOCS-024, OGK-DOCS-025

### requester.py

- `declared`: OGK-TASK-016, OGK-TASK-017, OGK-TASK-018
- `principals`: OGK-TASK-109

### result_form.py

- `_check_entry`: OGK-RESULT-023
- `_check_source`: OGK-RESULT-024, OGK-RESULT-025, OGK-RESULT-026, OGK-RESULT-027, OGK-RESULT-054
- `_evidence_reference`: OGK-RESULT-021, OGK-RESULT-052
- `_refusal`: OGK-RESULT-033
- `raise_any`: OGK-RESULT-022

### results.py

- `chaosfolk_checks`: OGK-RESULT-028, OGK-RESULT-056
- `decision_changes`: OGK-RESULT-055

### retro.py

- `_refusal`: OGK-RESULT-034
- `facts_of_record`: OGK-RESULT-029
- `write_draft`: OGK-RESULT-031

### routing.py

- `select_boards`: OGK-ROUTE-001, OGK-ROUTE-002, OGK-ROUTE-003, OGK-ROUTE-004, OGK-ROUTE-005, OGK-ROUTE-006, OGK-ROUTE-007

### rule_checks.py

- `_fields`: OGK-RULE-002, OGK-RULE-003
- `_validate_check_path`: OGK-RULE-007
- `_validate_field`: OGK-RULE-012, OGK-RULE-018, OGK-RULE-019, OGK-RULE-020, OGK-RULE-021, OGK-RULE-022, OGK-RULE-023, OGK-RULE-024
- `_validate_paths`: OGK-RULE-008
- `_validate_size`: OGK-RULE-011
- `_validate_text`: OGK-RULE-009, OGK-RULE-010, OGK-RULE-015, OGK-RULE-016, OGK-RULE-017
- `parse_fields`: OGK-RULE-027
- `validate_check`: OGK-RULE-013, OGK-RULE-014, OGK-RULE-025, OGK-RULE-026
- `validate_path`: OGK-RULE-004, OGK-RULE-005, OGK-RULE-006

### sarif.py

- `_clean_path`: OGK-CHECK-007, OGK-CHECK-016
- `_prepared`: OGK-CHECK-008, OGK-CHECK-009, OGK-CHECK-010, OGK-CHECK-011
- `_rule`: OGK-CHECK-012, OGK-CHECK-017
- `to_sarif`: OGK-CHECK-018

### sensitive.py

- `public_evidence_url`: OGK-GUARD-015, OGK-GUARD-016, OGK-GUARD-023
- `refuse_link_credentials`: OGK-GUARD-014

### short_lane.py

- `declare`: OGK-LANE-005, OGK-LANE-006, OGK-LANE-007, OGK-LANE-008, OGK-LANE-009
- `normalize_entries`: OGK-LANE-003, OGK-LANE-004, OGK-LANE-011
- `normalize_entry`: OGK-LANE-001, OGK-LANE-002
- `proposed_routing`: OGK-LANE-010

### storage.py

- `_held_lock`: OGK-CORE-012
- `_loads`: OGK-CORE-021
- `lock_timeout`: OGK-CORE-014
- `parse_json`: OGK-CORE-009, OGK-CORE-010
- `project_lock`: OGK-CORE-024
- `unique_fields`: OGK-CORE-008
- `write_text`: OGK-CORE-011

### storybook.py

- `_check_name`: OGK-STORY-030
- `_check_proposal_items`: OGK-STORY-009, OGK-STORY-033
- `_check_proposed_component`: OGK-STORY-010, OGK-STORY-034, OGK-STORY-035
- `_check_proposed_tokens`: OGK-STORY-011, OGK-STORY-012
- `_check_ref_url`: OGK-STORY-003, OGK-STORY-004
- `_validate_story`: OGK-STORY-021
- `compose`: OGK-STORY-005, OGK-STORY-006, OGK-STORY-007, OGK-STORY-008, OGK-STORY-019, OGK-STORY-020
- `import_indexes`: OGK-STORY-028, OGK-STORY-029
- `propose`: OGK-STORY-036
- `read_index`: OGK-STORY-001, OGK-STORY-002, OGK-STORY-015, OGK-STORY-016, OGK-STORY-017, OGK-STORY-018
- `ref_id`: OGK-STORY-014
- `source_files`: OGK-STORY-027
- `validate_proposals`: OGK-STORY-031, OGK-STORY-032
- `validate_record`: OGK-STORY-022, OGK-STORY-023, OGK-STORY-024, OGK-STORY-025, OGK-STORY-026

### storybook_stories.py

- `generate`: OGK-STORY-013, OGK-STORY-037

### task_files.py

- `_validated_task`: OGK-TASK-022, OGK-TASK-023
- `read_task`: OGK-TASK-021
- `task_path`: OGK-TASK-019, OGK-TASK-020, OGK-TASK-110

### tasks.py

- `_period_day`: OGK-TASK-006
- `create_task`: OGK-TASK-003, OGK-TASK-004, OGK-TASK-005
- `dependencies`: OGK-TASK-001, OGK-TASK-002

### tasks_approval.py

- `require_approval`: OGK-TASK-111
- `require_current_scope`: OGK-TASK-024, OGK-TASK-112

### tasks_blockers.py

- `_check_clearance_signature`: OGK-TASK-026
- `_clearing_evidence`: OGK-TASK-025
- `require_blocker_status`: OGK-TASK-103
- `resolve_blocker`: OGK-TASK-027, OGK-TASK-028, OGK-TASK-029, OGK-TASK-030, OGK-TASK-031, OGK-TASK-032, OGK-TASK-033, OGK-TASK-034, OGK-TASK-035, OGK-TASK-036, OGK-TASK-113, OGK-TASK-114, OGK-TASK-115, OGK-TASK-116, OGK-TASK-117, OGK-TASK-118

### tasks_cli.py

- `_new`: OGK-TASK-007, OGK-TASK-008
- `_run`: OGK-TASK-010, OGK-TASK-011, OGK-TASK-012
- `run`: OGK-TASK-009

### tasks_close_cli.py

- `_cannot_run`: OGK-TASK-044, OGK-TASK-045
- `_closing`: OGK-TASK-037, OGK-TASK-038, OGK-TASK-039, OGK-TASK-040, OGK-TASK-041, OGK-TASK-119
- `_declaration_checks`: OGK-TASK-042, OGK-TASK-043, OGK-TASK-120
- `_verify_payload`: OGK-TASK-047, OGK-TASK-123
- `_withdraw`: OGK-TASK-046, OGK-TASK-121, OGK-TASK-122
- `run_checks`: OGK-TASK-098
- `run_diff_review`: OGK-TASK-048, OGK-TASK-125
- `run_outcome`: OGK-TASK-100, OGK-TASK-124
- `run_result_template`: OGK-TASK-099
- `run_runs`: OGK-TASK-101

### tasks_closing.py

- `complete_task`: OGK-TASK-050, OGK-TASK-051
- `defer_evidence`: OGK-TASK-126, OGK-TASK-127
- `record_authorization`: OGK-TASK-055, OGK-TASK-131, OGK-TASK-132
- `record_decision`: OGK-TASK-052, OGK-TASK-053, OGK-TASK-106, OGK-TASK-128, OGK-TASK-129
- `record_result`: OGK-TASK-049, OGK-TASK-105
- `revoke_approval`: OGK-TASK-054, OGK-TASK-107, OGK-TASK-130

### tasks_consult_cli.py

- `_light_answers`: OGK-TASK-059, OGK-TASK-060
- `_read_consultation`: OGK-TASK-102
- `_reused_answers`: OGK-TASK-138
- `_selection`: OGK-TASK-133
- `input_file`: OGK-TASK-056
- `run_consult`: OGK-TASK-137
- `run_pass`: OGK-TASK-061
- `run_questions`: OGK-TASK-057, OGK-TASK-134
- `run_respond`: OGK-TASK-135
- `run_review`: OGK-TASK-140
- `run_route`: OGK-TASK-058, OGK-TASK-136

### tasks_decide_cli.py

- `_save_decided`: OGK-TASK-013
- `run_authorize`: OGK-TASK-073
- `run_decide`: OGK-TASK-063, OGK-TASK-064, OGK-TASK-065, OGK-TASK-066, OGK-TASK-067, OGK-TASK-068, OGK-TASK-069, OGK-TASK-070, OGK-TASK-091
- `run_decision_payload`: OGK-TASK-072, OGK-TASK-104, OGK-TASK-143
- `run_resolve`: OGK-TASK-071, OGK-TASK-141, OGK-TASK-142
- `run_revoke`: OGK-TASK-062

### tasks_list_cli.py

- `_closing_points`: OGK-TASK-108
- `_retro_record`: OGK-TASK-074, OGK-TASK-145
- `run_retro`: OGK-TASK-075, OGK-TASK-076, OGK-TASK-077, OGK-TASK-078, OGK-TASK-079
- `run_show`: OGK-TASK-146
- `show_exported`: OGK-TASK-144

### tasks_record.py

- `board_brief_problem`: OGK-TASK-080
- `validate_brief`: OGK-TASK-081

### tasks_review.py

- `_passes`: OGK-TASK-096
- `assemble_review`: OGK-TASK-097
- `record_consultation`: OGK-TASK-082, OGK-TASK-083, OGK-TASK-084
- `record_review`: OGK-TASK-095
- `start_pass`: OGK-TASK-147, OGK-TASK-148
- `submit_pass`: OGK-TASK-085

### terminal.py

- `typed`: OGK-CORE-013, OGK-CORE-025

### tool_connections.py

- `_host_entries`: OGK-TOOLS-005
- `_mcp_file`: OGK-TOOLS-001, OGK-TOOLS-035
- `_split_codex`: OGK-TOOLS-034
- `_write_host`: OGK-TOOLS-002, OGK-TOOLS-036
- `apply_connections`: OGK-TOOLS-004
- `check_settings`: OGK-TOOLS-003
- `read_manifest`: OGK-TOOLS-032, OGK-TOOLS-033
- `remove_connections`: OGK-TOOLS-037

### tool_registry.py

- `_catalog_line`: OGK-CATALOG-071
- `_check_forwarded`: OGK-CATALOG-087
- `_check_project_names`: OGK-CATALOG-102
- `_check_stand_ins`: OGK-CATALOG-086
- `_https`: OGK-CATALOG-072, OGK-CATALOG-073
- `_load_tool_file`: OGK-CATALOG-103, OGK-CATALOG-104, OGK-CATALOG-105, OGK-CATALOG-106, OGK-CATALOG-107
- `_names`: OGK-CATALOG-074
- `_read_on`: OGK-CATALOG-085
- `_read_only_args`: OGK-CATALOG-091
- `_read_only_env`: OGK-CATALOG-092
- `_remote_placeholders`: OGK-CATALOG-080
- `_server_settings`: OGK-CATALOG-079
- `_stdio_placeholders`: OGK-CATALOG-081, OGK-CATALOG-082, OGK-CATALOG-083, OGK-CATALOG-084
- `_tool_api_and_detect`: OGK-CATALOG-093, OGK-CATALOG-094, OGK-CATALOG-095
- `_validate_read_only`: OGK-CATALOG-088, OGK-CATALOG-089, OGK-CATALOG-090
- `_validate_server`: OGK-CATALOG-075, OGK-CATALOG-076, OGK-CATALOG-077, OGK-CATALOG-078
- `_validate_tool`: OGK-CATALOG-096, OGK-CATALOG-097, OGK-CATALOG-098, OGK-CATALOG-099, OGK-CATALOG-100, OGK-CATALOG-101
- `check_tool_links`: OGK-CATALOG-109
- `load_tools`: OGK-CATALOG-108

### tools.py

- `_live_connection`: OGK-TOOLS-027
- `_plan_options`: OGK-TOOLS-010, OGK-TOOLS-011, OGK-TOOLS-012, OGK-TOOLS-026
- `_settings`: OGK-TOOLS-008, OGK-TOOLS-009
- `choose_server`: OGK-TOOLS-007, OGK-TOOLS-025
- `load_mock`: OGK-TOOLS-020, OGK-TOOLS-023, OGK-TOOLS-024
- `read_scenario`: OGK-TOOLS-021, OGK-TOOLS-022
- `resolve_tool`: OGK-TOOLS-006

### tools_cli.py

- `_call`: OGK-TOOLS-018, OGK-TOOLS-019, OGK-TOOLS-030
- `_confirm_live`: OGK-TOOLS-014, OGK-TOOLS-015
- `_host`: OGK-TOOLS-013
- `_list`: OGK-TOOLS-031
- `_pairs`: OGK-TOOLS-028, OGK-TOOLS-029
- `_scenario`: OGK-TOOLS-016, OGK-TOOLS-017

### trace_cli.py

- `project_file`: OGK-AUDIT-006, OGK-AUDIT-009

### web_requests.py

- `_resolve`: OGK-WEB-013, OGK-WEB-014, OGK-WEB-015, OGK-WEB-016
- `_resolved`: OGK-WEB-010
- `check_paths`: OGK-WEB-011, OGK-WEB-012
- `check_request`: OGK-WEB-003, OGK-WEB-004, OGK-WEB-005, OGK-WEB-006, OGK-WEB-007, OGK-WEB-008, OGK-WEB-009
- `read`: OGK-WEB-017, OGK-WEB-018, OGK-WEB-019, OGK-WEB-020
- `write`: OGK-WEB-021, OGK-WEB-022, OGK-WEB-023, OGK-WEB-024, OGK-WEB-025

### webui.py

- `_body`: OGK-WEB-040, OGK-WEB-041, OGK-WEB-042, OGK-WEB-043, OGK-WEB-044, OGK-WEB-045
- `_decision_line`: OGK-WEB-056
- `_options`: OGK-WEB-026
- `_static`: OGK-WEB-038
- `_with_uploads`: OGK-WEB-030, OGK-WEB-031, OGK-WEB-032, OGK-WEB-033
- `do_GET`: OGK-WEB-034, OGK-WEB-035, OGK-WEB-036, OGK-WEB-037
- `do_POST`: OGK-WEB-039
- `handle`: OGK-WEB-046, OGK-WEB-047
- `launch_key`: OGK-WEB-001
- `parse`: OGK-WEB-027
- `run`: OGK-WEB-028, OGK-WEB-029
- `save_prefs`: OGK-WEB-048, OGK-WEB-049, OGK-WEB-050, OGK-WEB-051
- `save_profile`: OGK-WEB-002, OGK-WEB-052, OGK-WEB-053, OGK-WEB-054, OGK-WEB-055

### workflow.py

- `challenge_report`: OGK-TASK-093
- `deliberation_request`: OGK-TASK-092
- `validate_deliberation`: OGK-TASK-086, OGK-TASK-087, OGK-TASK-088, OGK-TASK-089, OGK-TASK-090, OGK-TASK-149

### workstation.py

- `policy`: OGK-HOST-009, OGK-HOST-010

## JSON output

With `--json`, a command prints its answer as JSON on standard output.
With `OPENGUILDKIT_JSON_ENVELOPE=1` in the environment, every answer comes in one object, `{"schema_version": 1, "command": "task checks", "data": ...}`, whose `data` is the answer printed without the variable; the default keeps the shape scripts and the web interface read.
Under `--json`, an error is JSON on standard output too, with the same exit code and its line on standard error: `{"schema_version": 1, "error": {"code": "OGK-TASK-004", "message": ..., "next": ...}}`.
`code` is null for an error that has no code yet, and `next` is the command the message names, or null.
