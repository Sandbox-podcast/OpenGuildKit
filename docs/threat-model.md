# Threat model

For: a security architect who reads the model before authorizing the tool, and the administrator who answers the questions that follow. It covers one tenant: one team, its repositories and its agents.

OpenGuildKit makes a team's agents follow a written path and keeps the record of who decided. It is not a sandbox: it cannot stop an agent from using its tools. This page gathers, in one place, what is protected, against whom, by which control and where, and what stays open. Every statement rests on a sentence of another page or on a test, which `tests/test_doc_pages.py` finds again.

## Assumptions

- The person at the terminal is trusted: they approve, sign and decide. An approval needs them at an interactive terminal.
- The host agent and the model are not trusted to follow instructions. What they do is outside this tool ([SECURITY.md](../SECURITY.md#out-of-scope)).
- Git holds the history: the base revision of a pull request, and the files `guard --ci` reads from it, are what the pull request cannot change.
- The CI workflow that runs `guard --ci` is the team's, and a pull request cannot edit it once it is protected ([protect the check](../integrations/README.md#protect-the-check)).
- The CLI makes no call to a model and opens no network connection of its own, one command a person asks for aside ([design decisions](architecture.md#design-decisions)).

## Actors

| Actor | What it can do |
|---|---|
| Agent that writes files | Calls the host's file-edit tools on the project |
| Agent with a shell | Runs commands: writes files by redirection or script, runs Git, may try the approval commands |
| Malicious pull request | Changes files, the profile, the signers file or a workflow in a branch |
| Person inside the team | Has write access to the repository, or a key in the signers file |
| Compromised catalog | A bundled, project or organization catalog record that tells an agent to weaken a rule |
| Injected text | A brief, a research result or a review that contains instructions meant for the agent |

## Assets

The profile (`.openguildkit/project.json`), the catalog lock, the allowed signers file, the task records and the exported decision records (`.openguildkit/decisions/`), the approvals they carry, and the names and reasons they record ([personal data](personal-data.md)).

## What stops what, and where

| Threat | Control | Where | What it stops |
|---|---|---|---|
| An agent edits files with no approved task | Hook before the host's edit tools, in `enforce` | Workstation | The edit through those tools |
| An agent edits files with no approved task | `guard --ci` | CI | The pull request, whatever tool wrote the files |
| An agent approves its own plan | Approval needs a person at an interactive terminal; the host denies the approval commands | Workstation | The commands as written, and a pipe |
| An agent forges an approval | Signed approvals, verified against the signers of the base revision | CI | A seal recomputed by hand, a key added by the pull request |
| A pull request loosens the rules it is judged by | The mode, profile and signers come from the base revision | CI | A change to its own judge |
| A pull request edits the check | `CODEOWNERS` on `.github/workflows/`, or a required workflow | CI | An edit of the workflow by the change it judges |
| A rule changes after approval | The approval is bound to the rules in force by a fingerprint | Both | An approval that no longer matches the rules |
| A catalog record weakens a project | Same schema validation as bundled records; the catalog is adopted by a person | Both | A record that reuses a bundled ID, a silent update |
| Injected text becomes an instruction | Task text is rendered in code fences; research and sources are data | Both | A fence broken by a backtick run; the agent is told, nothing more |

## Residual risks

Each risk names the sentence or the test that establishes it. The quoted words are in the page named.

| Risk | Established by |
|---|---|
| A local seal can be recomputed by an agent that can write files: only a signed approval resists it | [Architecture](architecture.md): "Only a signed approval resists an agent that can write files" |
| A write by the shell or by a script does not go through the hooks | [README](../README.md): "Writes through the shell do not go through the hooks; the CI check catches them." |
| Deny rules match a command line only: `sh -c`, an absolute path or a script file get around them | [Architecture](architecture.md): "Deny rules match the command line only and the hosts say they are not a security boundary" |
| A commit can add a key to the signers file | [Architecture](architecture.md): "A commit can still add a key, since an agent with a shell can run `git commit`" |
| The check runs the pull request's own copy of a workflow until the workflow is protected | [Integrations](../integrations/README.md): "GitHub runs the copy of the workflow file that the pull request carries" |
| An approval covers the work, not a list of files | [Integrations](../integrations/README.md): "an approval covers the work, not a list of files" |
| A cloud session or a CI run of an agent may not load the hooks | [Host coverage](host-coverage.md): "cloud session" and the rows `not established` |
| The hooks were not seen in a live host session | [Integrations](../integrations/README.md): "Not verified in a live host session yet" |
| `host scan` blocks nothing and a clean scan does not say the files are safe | [Host scan](host-scan.md): "It blocks nothing." |
| Names and reasons are recorded in files the team commits | [Personal data](personal-data.md): "OpenGuildKit records who decided what" |
| One maintainer answers a security report | [SECURITY.md](../SECURITY.md): "OpenGuildKit has one maintainer today" |

## Not covered

The behaviour of the host agent and of its model, the security of the projects that use the tool (the packs help a team ask the right questions and are not an audit), leak prevention at the network level, cost budgets, and the choice of model: [host coverage](host-coverage.md) says where to look instead.
