"""The two clocks: the date records are written with (`SOURCE_DATE_EPOCH`) and the real time decisions are made with.

When SOURCE_DATE_EPOCH is set, following the reproducible-builds convention, its value in
seconds since 1970-01-01 UTC replaces the current time in now(), today() and timestamp(), so a
replay writes the same dates on any day; the first use in a process says so on stderr. Decisions
that depend on time (a share's end, a waiver's length and its expiry, an approval's age, the age
of a market observation or a Storybook index, a date in the future) read real_now() and
real_today(), which the variable never changes. Measuring a duration uses time.monotonic instead.

Which clock dates which field:

- the record clock (timestamp, today), which SOURCE_DATE_EPOCH replaces: a task's created_at and
  completed_at, the times of board passes, results, check runs and deferrals, the alert register,
  a deliverable's created_at, and the dates an exported docs site or record shows, so that a
  replayed export is the same on any day;
- the real clock (real_timestamp, real_today), which it never changes: what a person decides and
  whose age or end is measured later, that is a decision (decision.at), the withdrawal of an
  approval (revoked.at and the decision that withdraws it), the clearance or waiver of a blocker
  (at), the authorization of an external action (at), and a share of the publishing register.

One time zone, UTC, dates everything on both clocks: a time is written in UTC (+00:00), and a day
(today, real_today, a share's last day, a waiver's end, the day of a profile change) is the UTC day,
as Documentalist counts a reader's last day. The local time zone is never read: two acts seconds
apart show the same day, and a share ends at the same instant on every machine.

Entry: now, today, timestamp, real_now, real_today, real_timestamp
Tests: tests/test_clock.py
"""

import os
import re
import sys
from datetime import date, datetime, timezone

from .errors import OgkError

_SECONDS = re.compile(r"[0-9]+")
_announced: set[str] = set()


def _source_date_epoch() -> datetime | None:
    value = os.environ.get("SOURCE_DATE_EPOCH", "")
    if not value:
        return None
    try:
        if not _SECONDS.fullmatch(value):
            raise ValueError
        fixed = datetime.fromtimestamp(int(value), timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise OgkError("OGK-CORE-001", "SOURCE_DATE_EPOCH must be a whole number of seconds since 1970-01-01 UTC. Fix or unset it.") from None
    _announce(value, fixed)
    return fixed


def _announce(value: str, fixed: datetime) -> None:
    """Say once per process and value that dates are fixed, so a variable left in a shell does not go unseen."""
    if value in _announced:
        return
    _announced.add(value)
    print(f"OpenGuildKit: SOURCE_DATE_EPOCH is set: this command dates what it writes "
          f"{fixed.isoformat(timespec='seconds')}, not now. Unset it unless you replay an export.", file=sys.stderr)


def now() -> datetime:
    """The time written into a record: the current UTC time, or SOURCE_DATE_EPOCH when it is set."""
    return _source_date_epoch() or datetime.now(timezone.utc)


def today() -> date:
    """The day written into a record: the UTC date of now(), so that of SOURCE_DATE_EPOCH when it is set."""
    return now().date()


def timestamp() -> str:
    """The time a record is written, to the second."""
    return now().isoformat(timespec="seconds")


def real_now() -> datetime:
    """The current UTC time, whatever SOURCE_DATE_EPOCH says: for ages and lengths that decide something."""
    return datetime.now(timezone.utc)


def real_today() -> date:
    """Today's UTC date, whatever SOURCE_DATE_EPOCH says: for end dates that decide something."""
    return real_now().date()


def real_timestamp() -> str:
    """The current time to the second, for a register that must say when something really happened."""
    return real_now().isoformat(timespec="seconds")
