# Project profile reference

For: an administrator or a developer who reads or checks `.openguildkit/project.json`, and the agent that edits a profile through the commands.

`openguildkit init` writes the profile of a project in `.openguildkit/project.json`. Every command reads it through the same validation (`validate_profile` in `project.py`), which refuses a field it does not know and names the one it refuses.
[`project.schema.json`](project.schema.json) is the same shape as a JSON Schema, for an editor or a CI job; it checks the shape of each field, and the validation of OpenGuildKit also checks the values against the catalog (a pack ID, a pattern ID, a board ID).

Change a profile with `openguildkit profile`, which records who, when and why under `changes` and rewrites `AGENTS.md` ([change the profile after setup](patterns.md#change-the-profile-after-setup)). A change to the rules, the checks or the boards voids the approvals made before it ([task workflow](workflow.md)).
`openguildkit profile export` prints the setup answers that give another repository the same profile ([reuse the profile](workflow/following-the-work.md#reuse-the-profile-in-another-repository)).

## The 30 fields

A field marked "absent when empty" is written only when it holds something. Dates are written `YYYY-MM-DD`, and a text that records a person is one line.

| Field | Type and values | Default | Changed with |
|---|---|---|---|
| `schema_version` | Whole number; 1 is the only version | 1 | Written by `init` |
| `name` | Text on one line | The folder name at `init` | Written by `init` |
| `sector` | Sector ID of the catalog (`openguildkit catalog`) | `general` | `profile set sector ID --by INITIALS --reason WHY` |
| `stack` | List of technology names | Empty | Written by `init`; `detect` proposes it |
| `components` | List of `{"id", "stack"}` with an optional `"path"`; an ID is lowercase letters, digits and hyphens, 64 characters at most. Absent when empty | Absent | Written by `init` |
| `roles` | List of role IDs (`openguildkit patterns --role ID` lists the roles). Absent when empty | Absent | `profile add role` and `profile remove role` |
| `patterns` | List of pattern IDs, or `{"id", "components"}` to limit a pattern to components | Chosen at `init` from the stack, the sector and the roles | `profile adopt PATTERN` |
| `packs` | List of rule pack IDs; `agent-workflow` is always in it | The packs of the stack and of the selected patterns | `profile add pack` and `profile remove pack` |
| `resolutions` | List of `{"packs", "keep", "reason"}`: the team's choice between conflicting packs. Absent when empty | Absent | Written by `init` from the setup answers |
| `boards` | List of board IDs the project uses; empty means every board ([brains](brains.md)) | Empty | `profile add board` and `profile remove board` |
| `required_boards` | List of board IDs every task consults. Absent when empty | Absent | `profile add required-board` and `profile remove required-board` |
| `required_rules` | List of `PACK` or `PACK/RULE`: rules every task is asked. Absent when empty | Absent | `profile add required-rule` and `profile remove required-rule` |
| `research` | `local-only` or `public-sources` | `local-only` | `profile set research VALUE` |
| `host` | `claude-code`, `codex`, `gemini-cli` or `other`; absent in a profile written before the field | `other` | `profile set host VALUE` |
| `guard` | `off`, `observe` or `enforce`; absent in a profile written before the field, which then reads as `off` | `observe` for a new project | `profile set guard VALUE`; lowering it is typed by a person at a terminal |
| `waivers` | `{"allowed_by": [names], "max_days": 1 to 366}`. Absent when waivers are not allowed | Absent | `profile set waivers allowed --allowed-by NAME --max-days DAYS`; `none` removes it |
| `approval` | `{"mode": "local"}` or `{"mode": "signed", "allowed_signers": PATH, "approvers": [names]}`; the path is inside the project. Either may add `max_age_days` (1 to 366) and `roles` (each board ID with its people) | Absent: local seals | `profile set approval local` or `signed --signers PATH --approver NAME`; `profile set max-approval-age DAYS` and `profile set approver-roles BOARD NAME...` ([roles by board](workflow/roles-by-board.md)) |
| `tools` | List of tool names the company works with | Empty | `profile add tool` and `profile remove tool` |
| `conventions` | List of one-line texts the agent follows | Empty | `profile add convention` and `profile remove convention` |
| `checks` | List of commands `task verify` runs; every one is mandatory | Empty | `profile add check` and `profile remove check` |
| `personal_data` | `true` or `false` (written from `yes` or `no`); absent when it was not asked | Asked at `init` | `profile set personal-data yes\|no` |
| `people_decisions` | `true` or `false`; absent when it was not asked | Asked at `init` | `profile set people-decisions yes\|no` |
| `declined` | List of pattern IDs, or `{"id", "by", "on", "reason"}`: patterns a person declined, never proposed again. Absent when empty | Absent | `profile decline PATTERN --by INITIALS --reason WHY` |
| `changes` | List of `{"change", "by", "on", "reason"}`: the history of the profile commands. Absent when empty | Absent | Written by every `profile` command |
| `ask_every_rule` | `true`, or absent: every rule is asked of every task instead of the ones that concern it | Absent | `profile set ask-every-rule yes\|no` |
| `light_paths` | List of folder or file globs the short lane covers. Absent or empty: the lane is off | Absent | `profile set light-paths GLOB...`; `none` turns it off ([short lane](workflow/short-lane.md)) |
| `declined_rules` | List of `{"id": "PACK/RULE", "by", "on", "reason"}`: rules set aside while their pack stays in force. Absent when empty | Absent | `profile decline rule PACK/RULE`; `profile adopt rule PACK/RULE` restores one |
| `separate_requester` | `true`, or absent: the requester of a task may not approve it | Absent | `profile set separate-requester on\|off` ([requester and approver](workflow/requester-and-approver.md)) |
| `frozen` | `{"by", "on", "reason"}`, or absent: the edit hook refuses every edit and `guard --ci` every change but the one that lifts it | Absent | `profile set freeze on\|off`; lifting it needs a person at a terminal ([incident response](workflow/incident-response.md)) |
| `restricted_paths` | List of `{"paths": [globs], "class": TEXT, "boards": [board IDs]}`; a path is inside the project, without `..` or parentheses | Absent | `profile set restricted-paths PATH...` or `none` (lifting a path needs a terminal), or by hand; the edit hook refuses an edit of them, `host apply` writes the deny rules ([paths the team closes to the agent](../integrations/README.md#paths-the-team-closes-to-the-agent)) |

## Check a profile

```bash
openguildkit check
```

`check` fails when the instructions, the host settings, the catalog lock or an approval no longer match the profile. A profile with a field outside the table is refused with `Unknown profile fields:` and the names.

To check the shape in an editor, point it at the schema, for example in the settings of VS Code:

```json
{"json.schemas": [{"fileMatch": [".openguildkit/project.json"], "url": "./docs/project.schema.json"}]}
```

The schema describes the file as OpenGuildKit writes it. It does not replace `openguildkit check`, which also reads the catalog.
