# Closing a task

Read this file in step 5 of SKILL.md when you fill in the result template, when a check command fails or cannot run, and when the task is of kind `decision` or closes with reservations.

## The result template

It lists only the rules that concern the task; the others are under `not_concerned` and need no answer.
A pack that does not apply can be answered once in `packs`.

Write criteria `status` as `met` or `not-met` and checks as `passed`, `failed`, `skipped` or `not-applicable`, as the template says.

## A check that fails or cannot run

When a check command fails, show the user the cause, last lines and log path that `task verify` prints; when dependencies or the network are missing, ask the user to install them or to run the check, and never record it as passed.
If it cannot run here, the user records it in their terminal with `openguildkit task verify ID --cannot-run command:N --by NAME --reason TEXT`.
That declaration is theirs: never withdraw it, and run `task verify` again only to check whether the command now passes.

## A task that closes with reservations

When the task closes as `done-with-reservations`, show the open points as listed (`task show ID --closing` prints them again) and offer a follow-up task linked with `task new "BRIEF" --follows ID`.

## A task of kind decision

A task of kind `decision` returns an "Approved decision record" instead. Report the decision and do not change project files. Close it with `openguildkit task complete ID` and export its record with `openguildkit task export ID`. If the user wants to act on it, open a follow-up task with `task new "BRIEF" --follows ID` (the decision task's ID), which records the link, and take that task through consultation and approval.
