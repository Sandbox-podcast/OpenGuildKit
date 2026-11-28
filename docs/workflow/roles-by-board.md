# Roles by board

For: an administrator who gives the blockers of a board to its members.
A part of the [task workflow](../workflow.md).

Until the project decides, `approval.approvers` and `waivers.allowed_by` are flat lists: a blocker the security board raised is cleared by whoever types `--by`, or, in a signed project, by the signature of any approver, and the final approval is the same.
OpenGuildKit offers an option, `approver-roles`, off in every project: a project that sets none behaves exactly as before, and its records, approvals and exports are read as they were.
A role only restricts, so setting one needs no terminal; giving a role more people, or removing it, weakens a protection and is a person's act at an interactive terminal, who types the board and the names to confirm.

```bash
openguildkit profile set approver-roles security CM JD --by SAM --reason "Security signs for security"
openguildkit profile set approver-roles legal AB --by SAM --reason "Legal signs for legal"
openguildkit profile set approver-roles security none --by SAM --reason "Roles ended"     # a person, at a terminal
```

The profile then holds `"approval": {"mode": "local", "roles": {"security": ["CM", "JD"], "legal": ["AB"]}}`; the keys are board IDs.
In a signed project the names are the principals of the allowed signers file.

- **Clearing and waiving.** `task clear` and `task waive` of a blocker a board with a role raised are refused unless the person is in that role, with `security:1 was raised by the security board: a signer of role security clears it (CM, JD). PL is not one of them.` A signed clearance compares the verified signer;
  a local one, and every waiver, the name given with `--by`, without case or spaces.
  A board without a role is as before.
- **The final approval.** `task decide --approve` is refused when a board with a role gave a blocking advice on the task (a `block` verdict, or at least one blocker) and the approver is in none of those roles: the signer of a signed approval, else `--by`.
  One person approves, so a task blocked by two boards is approved by a member of either role, the blockers having been cleared by their own.
- **`guard --ci`** reads the roles of the base revision, so a pull request cannot give itself a role.
  A record the base revision does not carry is refused (`decision-role-outside`) when a blocker was cleared or waived by someone outside the role of its board, or when its approval is outside the roles of the boards that blocked.
  A record the base revision already carries is not judged again.
- **What it does not do.** A name typed with `--by` is not linked to a person: someone can type a member's name at a terminal they control, as `separate-requester` says of requesters.
  Only signed approvals tie a role to a key.
  The role does not void an approval, and it does not make `--requested-by` a principal: a requester is still compared by name.
