# Field campaigns

Unit and end-to-end tests check what the code does. A field campaign checks what a team lives through: thirty
autonomous agents each receive the brief of a team that adopts OpenGuildKit, with the documentation and the command's
own messages as their only help. They set the project up, answer the questionnaire as their person would, connect the
company's tools as mocks, take real work through the boards, the person's decision and the results, and report
where they got stuck, misled or let down.

No network, no account and no key are needed. Company tools are [mocks](../../docs/tools.md),
and every name, company and figure in the campaign is invented.

## The thirty testers

`campaign.json` holds them, in three groups:

| Group | Testers | What it shows |
|---|---|---|
| Personas | 18 teams on their own project: a payments startup, an HR software company, an online shop, a clinic scheduler, a mobile studio, a data team, a marketing agency run by a non-developer, an open-source maintainer, a game studio, a city portal, an insurer, a homework app, a platform team, a model team, a design system owner, a support lead, a French freelancer, a forty-developer monorepo | Whether each sector, stack and trade gets a setup and a review that fit it |
| Scenarios | 3 scenarios (`scenarios/s1` to `s3`), each played by 3 teams | Whether the same inputs give the same results |
| Teammates | 3 developers pushing to one repository | What git shares, what stays local, what changes under a teammate |

A persona names who the person is, the project to create, how the person answers the questionnaire, a first piece
of work and what to look at closely. A scenario has a project, the setup answers and a task; its first part is
scripted to the command, its second part is free.

```bash
python examples/field-tests/field.py list
```

## Run a campaign

A campaign needs Linux or macOS (the person's stand-in types at a pseudo-terminal), `git`, and an agent host that
can run an agent in a folder with a shell. Use a clean checkout of the commit under test.

To rehearse an installable release, install the verified wheel in a fresh virtual
environment and run the kit with that interpreter and
`OPENGUILDKIT_FIELD_INSTALLED=1`. The setup and scripted runs use the installed
package. The generated commands for logging, fingerprints and the simulated
person's input keep that interpreter and mode. The campaign manifest records
the kit's Git commit and the CLI version it ran.

```bash
OPENGUILDKIT_FIELD_INSTALLED=1 "$VENV/bin/python" examples/field-tests/field.py prepare --out ../campaign-release
OPENGUILDKIT_FIELD_INSTALLED=1 "$VENV/bin/python" examples/field-tests/field.py cohorts --out ../campaign-release
```

Use a fresh output directory for each version. The scripted comparison also
runs on Windows. Preparing a full campaign and running the simulated person's
terminal still require Linux or macOS.

1. Prepare a campaign folder outside the repository. It gets one folder per tester, the commands on a `bin` folder
   (`openguildkit` running this checkout, `person-decide`, `person-act`, `fingerprint`) and the teammates' shared repository. The
   `openguildkit` command on that folder records every call made in a tester's folder, with what it printed and its
   exit code, in `runs/TESTER/commands.log`: the tester has nothing to do to keep its transcript.

   ```bash
   python examples/field-tests/field.py prepare --out ../campaign
   ```

2. Give each tester its brief, one agent per tester, each started in its own folder `../campaign/runs/TESTER`. The
   brief is plain text for any host:

   ```bash
   python examples/field-tests/field.py brief fintech --out ../campaign
   ```

   The three teammates must run at the same time. The others can run in any order.

3. Collect. Every tester leaves `REPORT.md` and `findings.json` in its folder; scenario teams also leave
   `fingerprint.json`.

   ```bash
   python examples/field-tests/field.py collect --out ../campaign
   ```

   The command exits 1 and names what is missing when a tester left no report, unusable findings, or a transcript
   that stops before `task handoff`. It writes `results/summary.md`, the merged `results/findings.json`, and, for a
   scenario whose teams differ, an issue draft `results/divergence-SCENARIO.md`. The threshold is zero: one key
   that differs between two teams is enough for a draft. With `--open-issues`, it also files each draft as a GitHub
   issue with `gh issue create --title --body-file --label` in the repository of this checkout, and prints the
   address of each issue it opened; without the flag it opens nothing.

   ```bash
   python examples/field-tests/field.py collect --out ../campaign --open-issues
   ```

4. Group the findings that describe the same thing (one group per distinct defect, the references of every finding
   kept, the shortest reproduction taken from the findings), then have each serious group checked independently on
   a fresh project before an issue is opened: a report can be wrong, or depend on something the tester did earlier.
   Both steps are an agent's or a person's work; the kit does not automate them.

5. Write the campaign's report in `reports/DATE.md`: the commit, the host and models that played the testers, the
   counts, the comparison of the scenario teams, the groups with their issue numbers, what worked well, the limits.

## The roles a tester keeps apart

`TESTERS.md` is given to every tester. Its main rule: a tester plays the team's coding agent and the person it
works for, and never lets the first decide for the second. The agent may not approve its own plan, and
`openguildkit task decide` only accepts a person at a terminal. When the scenario says the person decides, the tester
runs `person-decide`, which types the decision at a pseudo-terminal and prints what the prompt showed. The person's
other acts at a terminal (clearing a blocker, closing over a skipped sensitive rule, declaring that a check cannot run)
go through `person-act` the same way. Outside a
campaign, nothing of the kind exists: a person decides.

## Same scenario, same results

The scripted part of a scenario is deterministic, so the threshold is zero: any difference between two teams is a
defect. `fingerprint.py` prints a digest of each file OpenGuildKit wrote and of each answer it gives about the
project (the rule plan, the route, the boards consulted, the packs in scope, the expected checks), with the
project's path, random identifiers and timestamps replaced first.

The comparison also runs without any agent, in a few seconds, and in the test suite:

```bash
python examples/field-tests/field.py cohorts --out ../campaign    # three folders per scenario, compared
```

The free part of a scenario is compared by reading: which verdicts the boards gave, what the person decided, what
each team found.

## What is in the repository and what is not

The kit, the campaign file, the scenarios and each campaign's report are here. The testers' own folders (their
projects, their full reports, the reproduction projects) stay in the campaign folder: they are large and
reproducible. Tests: `tests/e2e/test_field_kit.py`.
