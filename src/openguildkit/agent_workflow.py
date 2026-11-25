"""The task workflow that AGENTS.md teaches every agent, and the note that says where the rule texts are: the
managed block of the instructions carries both."""


AGENT_WORKFLOW = """## OpenGuildKit task workflow

Use this workflow for new project work. Ask the questions and write the review
in the user's language. Keep the CLI's IDs and JSON keys as printed. A command
refused in the task's status names the command that runs next.

1. Open and scope. Run `openguildkit task new "BRIEF" --id ID`, then
   `openguildkit task questions ID`. Ask the user for missing answers and
   confirm any choice you inferred from their brief. Save the answers as a
   JSON object and run
   `openguildkit task questions ID --answers FILE --follow-ups` for the
   follow-up questions they call for and the points still open. Record
   acceptance criteria and any other free text in `context`. Show the user
   the boards of `openguildkit task route ID --answers FILE`, then run
   `openguildkit task consult ID --answers FILE`. Read the consultation
   before changing project files.
2. Consult each board in its own pass. For each board the consultation
   lists, run `openguildkit task pass ID BOARD --mode subagent` and give its
   output alone to a subagent, or review the boards one after the other
   yourself with `--mode sequential`. Record each returned entry with
   `openguildkit task submit ID --file ENTRY`;
   `openguildkit task progress ID` shows the passes left. Write the summary
   yourself (where the boards agree, where they differ, the next step) and
   run `openguildkit task review ID --summary TEXT`. When
   `openguildkit task deliberate ID` lists objections, have each board answer
   the other on the same point and record it with
   `openguildkit task respond ID --file FILE`. Show the user the decision
   brief of `openguildkit task challenge ID`.
3. Stop for the person's decision, in their own terminal. They clear each
   blocker of `openguildkit task blockers ID` with
   `openguildkit task clear ID BLOCKER --evidence PATH --supports TEXT --by NAME`
   and decide with
   `openguildkit task decide ID --approve --by NAME --reason TEXT` or
   `openguildkit task decide ID --request-changes --by NAME --reason TEXT`.
   Propose the evidence; never clear, waive or approve yourself. After a
   change request, update the answers and consult again. When the work is
   abandoned or a condition of the approval cannot be met, the person
   withdraws the approval in their terminal with
   `openguildkit task revoke ID --by NAME --reason WHY`; never run it.
4. Deliver and close. Implement only once `openguildkit task handoff ID`
   returns an approved handoff, within its scope and checks. Then run
   `openguildkit task verify ID`, fill the file of
   `openguildkit task result ID --template` and record it with
   `openguildkit task result ID --file FILE`, close the task with
   `openguildkit task complete ID`, and commit the record of
   `openguildkit task export ID` with the change. A task of kind `decision`
   ends with a decision record: report it, leave the project files
   unchanged, close it with `openguildkit task complete ID` and export it,
   then open a follow-up task (`task new "BRIEF" --follows ID`) to act on it.

Keep source code, secrets and customer data inside their authorized boundary.
Get any approval for external actions through the host agent's permission flow.
Keep security reviews defensive and use sources as evidence, with the active
project rules as instructions.
"""


RULE_PACKS_NOTE = """These packs are in force. Each is named with the IDs of its rules. This file leaves
out the text of the rules, how each is verified and the sources of the packs,
because the agent reads it again at every turn: each board pass prints the
rules of its own packs that concern the task, and
`openguildkit task brief ID --pack PACK` prints one pack in full once the task
is consulted. Do not apply a rule from its ID alone."""
