"""The clock that stamps every record.

When SOURCE_DATE_EPOCH is set, following the reproducible-builds convention, its value in
seconds since 1970-01-01 UTC replaces the current time, so a replay writes the same dates
on any day. Measuring a duration uses time.monotonic instead and is not affected.
"""

import os
import re
from datetime import date, datetime, timezone

_SECONDS = re.compile(r"[0-9]+")


def _source_date_epoch() -> datetime | None:
    value = os.environ.get("SOURCE_DATE_EPOCH", "")
    if not value:
        return None
    try:
        if not _SECONDS.fullmatch(value):
            raise ValueError
        return datetime.fromtimestamp(int(value), timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ValueError("SOURCE_DATE_EPOCH must be a whole number of seconds since 1970-01-01 UTC. Fix or unset it.") from None


def now() -> datetime:
    """The current UTC time, or SOURCE_DATE_EPOCH when it is set."""
    return _source_date_epoch() or datetime.now(timezone.utc)


def today() -> date:
    """Today's local date, or the UTC date of SOURCE_DATE_EPOCH when it is set."""
    fixed = _source_date_epoch()
    return fixed.date() if fixed else date.today()


def timestamp() -> str:
    """The time a record is written, to the second."""
    return now().isoformat(timespec="seconds")
