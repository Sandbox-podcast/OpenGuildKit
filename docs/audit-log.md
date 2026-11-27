# Audit log: what OpenGuildKit did, one event per line

The decision records and the history of the profile say what the rules are and who approved. They are states, not events: a refusal of the guard in `enforce` writes nothing, and an approval withdrawn before its export leaves no trace in a file Git carries.
The audit log keeps the acts of OpenGuildKit itself as events, for the security operations team of a company that collects them with its own log agent.
It is off by default. It is not a log of what the agent does: it records the refusals of the guard hook and the acts of the people who approve, withdraw and change the rules.

## Turn it on

A person sets one of these on the workstation. Nothing else changes while it is off: a refusal leaves the files of the project as they were.

- `OPENGUILDKIT_AUDIT_LOG=1` in the environment of the agent and of the person's terminal writes `.openguildkit/audit/audit.jsonl`. A file name (`OPENGUILDKIT_AUDIT_LOG=soc.jsonl`) picks another file of that folder; a path, a name with a slash or a name that starts with a dot is refused.
- `"audit_log": true` (or a file name) in the workstation policy, `/etc/openguildkit/config.json` (on macOS also `/Library/Application Support/OpenGuildKit/config.json`, on Windows `%ProgramData%\OpenGuildKit\config.json`), which an administrator deploys and no variable can move. A policy file with another key, or that is not JSON, is refused with its name.

The folder is `.openguildkit/audit/`. Git ignores it (the folder holds its own `.gitignore`), and the guard refuses an agent's edit of anything in it, even under an approved task: only the commands of OpenGuildKit write there.
A collector rule points at `.openguildkit/audit/*.jsonl` of each clone. The command opens no connection.

A log that cannot be written (a full disk, a link in place of the folder, a bad name) says so in one line on standard error and changes nothing else: the hook still refuses, the approval still happens.
A link in place of the folder or the file is never followed.

## The lines

Each line is a JSON object on its own line, ASCII only, with `v` (1), `at` (UTC), `event`, `project` (the name of the project folder) and `prev`, the SHA-256 of the line before it, or 64 zeros for the first. The other fields depend on the event:

| Event | Written when | Other fields |
|---|---|---|
| `guard.refused` | the pre-edit hook exits 2 | `host` (the host of the profile), `mode`, `paths` (project paths, at most 20, never the content of the edit) |
| `task.approved` | `task decide --approve` | `task`, `by`, `signer` (a signed approval), `seal` |
| `task.revoked` | `task revoke` | `task`, `by` |
| `profile.changed` | any `profile` command, or a profile saved in `openguildkit ui` | `by`, `change` (the words of the history, such as `set host claude-code`) |
| `host.applied` | `host apply` writes a file | `host`, `paths` (the files written) |

A reason, a brief, the content of an edit and any credential never go in. `by` and `signer` are personal data, listed in [personal data](personal-data.md#files-that-stay-on-one-machine).
One example of each event, which `tests/test_audit_log.py` reads and checks against the schema:

```
{"v":1,"at":"2026-11-27T09:14:02+00:00","event":"guard.refused","project":"portal","host":"claude-code","mode":"enforce","paths":["app.py"],"prev":"0000000000000000000000000000000000000000000000000000000000000000"}
{"v":1,"at":"2026-11-27T09:20:41+00:00","event":"task.approved","project":"portal","task":"request-status","by":"CM","signer":"cm","seal":"4f1c0a9e8d7b6a5f4e3d2c1b0a9f8e7d6c5b4a39281706f5e4d3c2b1a0f9e8d7","prev":"9c1e5f0a7b3d28e64f1a0c9b8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e"}
{"v":1,"at":"2026-11-27T10:02:13+00:00","event":"task.revoked","project":"portal","task":"request-status","by":"CM","prev":"2d7a9e1c3b5f40682a1c3e5f7091b3d5f70a2c4e6081a3c5e7f9b1d3f5a70c2e"}
{"v":1,"at":"2026-11-27T10:05:50+00:00","event":"profile.changed","project":"portal","by":"CM","change":"set host claude-code","prev":"7e3b1d9f5a2c4086e1f3a5c7d9b0e2f4a6c8d1e3f5a7b9c0d2e4f6a8b1c3d5e7"}
{"v":1,"at":"2026-11-27T10:06:12+00:00","event":"host.applied","project":"portal","host":"claude-code","paths":[".claude/settings.json"],"prev":"b5d3f1a9c7e5038a1c3e5f7a9b1d3f5a7c9e0b2d4f6a8c1e3a5c7e9b0d2f4a6c"}
```

Not written yet, though the audit that asked for the log lists them (issue #454): `guard.flagged` (a hook in `observe`), `blocker.cleared`, `blocker.waived`, `task.authorized`, `org-catalog.pinned`, `org-catalog.off`.
The hook records no reason code for a refusal: the line says which paths were refused, not whether no task covered them or the file is protected.

## Verify the chain

```bash
openguildkit audit verify                  # the log of the project
openguildkit audit verify PATH             # a copy, or an export
```

It prints `3 events, chain intact` and exits 0, or exits 1 and names the first line that no longer follows the line before it (`line 3 does not follow line 2`): a line was changed or removed, or one was inserted.
The chain detects a change in the middle of the file. Removing the last lines, or changing the last one, leaves a chain that is intact: keep the hash of the last line in the collector to catch that.
Whoever can write the file can also rewrite the whole chain from the first changed line: the log shows tampering by an agent that cannot recompute it, not by a person with the file system.

## Export for a SIEM

```bash
openguildkit audit export --since 2026-11-01 > events.jsonl
```

The file of the audit log is already one event per line, which a log agent collects as it grows.
`audit export` serves another need: it rebuilds events for the days before the log was on, from what the repository holds, the approvals of `.openguildkit/decisions/*.json` and the changes of the profile in `.openguildkit/project.json`, oldest first, chained like the log, each marked `"reconstructed":true`.
The history of the profile keeps a day and no time, so a `profile.changed` event of an export is dated 00:00:00 UTC of that day. Withdrawals, refusals and the other events are in the live log only.

## The date of an approval

An approval is sealed: the seal is a SHA-256 over what was approved. The date of the decision (`decision.at`) is under neither the seal nor a signature, so a record can be moved to another day without the seal noticing.
From version 4 of the sealed payload the date is covered. A person who turns the audit log on has their local approvals sealed at version 4: changing `decision.at` in the task or in the exported record breaks the seal, and `guard --ci` refuses a record whose date differs from the sealed one.
Without the audit log, an approval is sealed as before: that format is a default for every team, and an older release cannot verify a version 4 seal, so a team on mixed versions turns the log on together.
Records sealed at versions 1 to 3 verify as before, whatever their date.
A signed approval stays at version 3, because the person signs the payload before the decision is dated: its date is still outside the signature, and how the signer gets the date is an open question of issue #454.
