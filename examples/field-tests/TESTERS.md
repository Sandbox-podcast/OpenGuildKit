# Field test: how to work

You are trying OpenGuildKit the way a real team would on its first day: with the documentation, the command's own
help and messages, and nothing else. The goal is to learn where a real user gets stuck, misled or let down, and what
works well. A run that finds nothing wrong is a valid result; a finding that is not backed by a command you ran is not.

## Your tools

- The command line under test: `openguildkit`. Put it on your PATH at the start of every shell command:
  `export PATH={out}/bin:$PATH`. Check it with `openguildkit --version`.
- The documentation a user has: `{repo}/README.md` (French version: `README.fr.md`), `{repo}/docs/`,
  `{repo}/examples/`, `{repo}/CONTRIBUTING.md`, and `--help` on every command. Read them as a user would. Do NOT
  read `{repo}/src/` or `{repo}/tests/`: a user installs a package and does not read its source. If you are truly
  stuck and only the source could unblock you, that is a finding ("had to read the source to ..."); write it down,
  then you may look.
- Your workspace: only the folder named in your task. Create your project inside it. Never write anywhere else,
  never use the network, never push to a remote other than one your task gives you, no real secrets or personal
  data (use `example.test` addresses and invented names).
- Git: `git init` your project and commit with
  `git -c user.name="Field tester" -c user.email="tester@example.test" commit ...`.

## Who you are in the scenario

You play two people, and you keep them apart:
- the **coding agent** of the team, which follows the project's `AGENTS.md` and the OpenGuildKit skill
  (`openguildkit integrations --host ...` installs it in the project; read the installed SKILL.md and follow it);
- the **person** you work for (described in your task), who answers the questions and takes the decisions. Answer
  as that person honestly would, from the description you were given: do not pick the answers that make things
  easy. When the description does not say, the person answers "unsure" or the plain default.

Board reviews: if your host gives you no subagents, review each board yourself, one after the other
(`--mode sequential`), honestly, with real evidence from your project files. Do not paste the same text into two
boards and do not approve your own work on the boards' behalf.

The decision is the person's. When your scenario reaches the moment the person decides, and only then, run:
`person-decide --project DIR TASK_ID --approve --by "NAME" --reason "TEXT"` (or `--request-changes`). It types
at a terminal as the person would and prints what the prompt showed. If the prompt asks something more (for example
to confirm a removed board), pass `--answer TEXT` for each extra line. Never approve in any other way.

Company tools (issue tracker, time tracking, HR, scanner...): there are no accounts here. Connect mocks with
`openguildkit tools apply TOOL... --mock` and query them the way an agent would through MCP with
`openguildkit tools call TOOL` (lists what the mock offers) and `openguildkit tools call TOOL NAME --args '{...}'`.

## How much to do

Follow your scenario. About 60 to 90 commands is the right size; stop when the scenario is complete or when you are
blocked (say what blocked you). Implement real, small code changes when a task is approved: the point is to develop
with the framework, not only to fill forms.

## What to report

For every finding: the exact command, what you observed (quote the message, trimmed), what you expected and why a
user would expect it, and how serious it is:
- **blocker**: you could not go on, or the tool did something wrong or unsafe (wrong result, lost data, a rule
  bypassed, a crash with a traceback);
- **major**: you lost real time or were misled (a documented command that does not work, a message that points to
  the wrong step, a default that surprises);
- **minor**: friction, unclear wording, a missing example;
- **suggestion**: an idea, not a defect.

Kind: `bug`, `confusing`, `missing` (a need the product does not cover), `docs`.
Also report what worked well, in a few lines: a user's praise is evidence too.
Report only what you ran yourself. If you did not try something, do not report on it.

## What to leave in your workspace

Before you stop, write these files in your workspace folder (not in your project):

- `REPORT.md`: what you did step by step, each finding with its command and output, what worked well.
- `findings.json`: one object, with
  - `outcome`: `completed`, `partial` or `blocked`;
  - `summary`: two or three sentences;
  - `commands_run`: a number;
  - `findings`: a list of objects with `title`, `severity`, `kind`, `command`, `observed` (under 600 characters)
    and `expected` (under 300 characters);
  - `worked_well`: a list of short sentences.
