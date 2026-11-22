"""Wall-clock dates for decisions and an optional reproducible date for exports."""

import os
import re
from datetime import date, datetime, timezone

_SECONDS = re.compile(r"[0-9]+")


def source_date_epoch() -> datetime | None:
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
    """The current UTC time, independent of reproducible-export settings."""
    return datetime.now(timezone.utc)


def today() -> date:
    """Today's local date, independent of reproducible-export settings."""
    return date.today()


def timestamp() -> str:
    """The time a record is written, to the second."""
    return now().isoformat(timespec="seconds")
