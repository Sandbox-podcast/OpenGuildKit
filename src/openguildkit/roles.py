"""Roles by committee (#475), off by default: who may clear a board's blockers and approve what a board blocked.

`approval.roles` maps a board to the people of its role, set by `profile set approver-roles BOARD NAME...`. A blocker a
board raised is then cleared or waived only by a member of its role, and a task on which a board with a role gave a
blocking advice (a block verdict, or a blocker) is approved only by a member of one of those roles. A signed approval or
clearance compares the signer, a principal; a local one compares the name typed with --by, without case or spaces,
which the code does not link to a person. `guard --ci` reads the roles of the base revision. A board without a role,
and a project without roles, are judged as before.
"""

from .requester import same_person


def members(profile: dict, board: str) -> list[str] | None:
    """The people of the board's role; None when the profile gives the board none."""
    roles = (profile.get("approval") or {}).get("roles")
    names = roles.get(board) if isinstance(roles, dict) else None
    return names if isinstance(names, list) and names else None


def _belongs(who: str | None, names: list[str], signed: bool) -> bool:
    if who is None:
        return False
    return who in names if signed else any(same_person(who, name) for name in names)


def _role(names: list[str], boards: list[str], signed: bool) -> str:
    return f"{'a signer' if signed else 'a person'} of role {' or '.join(boards)} ({', '.join(names)})"


def clearance_problem(profile: dict, blocker: dict, by: str, signer: str | None = None,
                      waiver: bool = False) -> str | None:
    """Why this person may not clear or waive the blocker, or None. signer is the verified signer of a signed
    clearance: the role is read from it. A waiver is not signed: it is read from --by."""
    names = members(profile, blocker["board"])
    signed = signer is not None
    who = signer if signed else by
    if names is None or _belongs(who, names, signed):
        return None
    role = _role(names, [blocker["board"]], signed).replace(" (", f" {'waives' if waiver else 'clears'} it (", 1)
    return f"{blocker['id']} was raised by the {blocker['board']} board: {role}. {who} is not one of them."


def blocking_boards(profile: dict, boards: list[dict], blockers: list[dict]) -> list[str]:
    """The boards with a role that blocked: a block verdict, or at least one blocker. boards hold id and verdict."""
    blocked = {item["board"] for item in blockers} | {item["id"] for item in boards if item.get("verdict") == "block"}
    return sorted(board for board in blocked if members(profile, board))


def _admitted(profile: dict, boards: list[str]) -> list[str]:
    return list(dict.fromkeys(name for board in boards for name in members(profile, board) or []))


def approval_problem(task: dict, profile: dict, by: str, signer: str | None = None) -> str | None:
    """Why this approval is refused: a board with a role blocked the task and the approver is of none of those roles."""
    from .workflow import blocker_list  # Only task decide needs it.

    boards = [{"id": entry["id"], "verdict": entry.get("challenge", {}).get("verdict")}
              for entry in task.get("review", {}).get("boards", [])]
    blocked = blocking_boards(profile, boards, blocker_list(task))
    signed, names = signer is not None, _admitted(profile, blocked)
    who = signer if signed else by
    if not blocked or _belongs(who, names, signed):
        return None
    role = _role(names, blocked, signed).replace(" (", " approves it (", 1)
    return (f"The {' and '.join(blocked)} board{'s' if len(blocked) > 1 else ''} gave a blocking advice on "
            f"{task['id']}: {role}. {who} is not one of them.")


def record_problems(record: dict, profile: dict) -> list[str]:
    """What guard --ci refuses in a record the base revision does not carry, by the roles of the base revision: a
    blocker cleared or waived outside the role of its board, an approval outside the roles of the boards that blocked."""
    problems = []
    blockers = [item for item in record.get("blockers", []) if isinstance(item, dict) and isinstance(item.get("board"), str)]
    for item in blockers:
        resolution, names = item.get("resolution"), members(profile, item["board"])
        if not isinstance(resolution, dict) or names is None:
            continue
        signed = isinstance(resolution.get("signer"), str)
        who = resolution["signer"] if signed else resolution.get("by")
        if not _belongs(who, names, signed):
            done = "cleared" if resolution.get("kind") == "cleared" else "waived"
            problems.append(f"{item.get('id')} was {done} by {who}, not {_role(names, [item['board']], signed)}: the "
                            f"base revision gives the {item['board']} board a role.")
    decision = record["decision"]
    boards = [item for item in record.get("boards", []) if isinstance(item, dict) and isinstance(item.get("id"), str)]
    blocked = blocking_boards(profile, boards, blockers)
    signed = isinstance(decision.get("signer"), str)
    who = decision["signer"] if signed else decision.get("by")
    names = _admitted(profile, blocked)
    if blocked and not _belongs(who, names, signed):
        problems.append(f"approved by {who}, not {_role(names, blocked, signed)}: the base revision gives the "
                        f"{' and '.join(blocked)} board a role and it blocked {record['task']}.")
    return problems
