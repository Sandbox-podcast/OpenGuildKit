"""Compare a local share register with one Documentalist instance on explicit request.

The observation describes the server's invitation policy, not a live reader session.
Credentials are requested at a terminal, held in memory and never saved in the register.
"""

import getpass
import http.cookiejar
import json
import re
import ssl
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

from . import clock
from .publishing import load_shares, portal_space, share_space
from .storage import project_lock, read_json, write_json


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        fp.close()
        raise ValueError("Documentalist redirected the request; no credentials were forwarded.")


_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _reason(error: Exception, origin: str, signed_in: bool = False) -> str:
    """Why the comparison could not run, in words the owner can act on.

    Documentalist answers 429 for its sign-in limit (10 per account in 10 minutes, no Retry-After)
    and for its per-route limit (Retry-After in seconds). A 401 after a successful sign-in means the
    session cookie did not come back: an instance started for production marks it Secure, which an
    http address cannot return unless the instance runs with DOCUMENTALIST_COOKIE_SECURE=false.
    """
    if isinstance(error, HTTPError):
        # The report is persisted. Server error bodies may echo credentials.
        error.close()
        hint = {400: "give --portal the address the instance is configured with (DOCUMENTALIST_URL)",
                401: "check the account and its password", 403: "use an editor account allowed in this space",
                404: "check the space in --portal", 409: "set the space's portal access to magic link",
                429: "wait ten minutes: the instance limits sign-in attempts"}.get(error.code, "check the instance")
        if error.code == 401 and signed_in:
            hint = ("the instance kept no session after the sign-in; over http, start it with "
                    "DOCUMENTALIST_COOKIE_SECURE=false, or give --portal its https address")
        retry = error.headers.get("Retry-After", "") if error.headers else ""
        if error.code == 429 and retry.isdigit():
            hint = f"wait {retry} seconds: the instance limits requests"
        return f"Documentalist answered HTTP {error.code}; {hint}."
    if isinstance(error, URLError):
        reason = error.reason
        if isinstance(reason, ssl.SSLCertVerificationError):
            return f"the TLS certificate of {origin} could not be verified ({reason.verify_message})."
        return f"{origin} did not answer ({reason})."
    if isinstance(error, (TimeoutError, OSError)):
        return f"{origin} did not answer ({error})."
    return str(error) if isinstance(error, ValueError) else "the answer could not be read."


def _origin(portal: str) -> tuple[str, str, str]:
    space = portal_space(portal)
    address = urlsplit(portal.strip())
    if address.username is not None or address.password is not None:
        raise ValueError("Remove credentials from --portal. Enter the password at the prompt.")
    slug = address.path.split("/")[2]
    return f"{address.scheme}://{address.netloc}", space, slug


def _json(opener, origin: str, path: str, payload=None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json", "Origin": origin}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(origin + path, data=body, headers=headers)
    with opener.open(request, timeout=10) as response:
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("The Documentalist response exceeded the size limit.")
    data = json.loads(content.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("The Documentalist response is not an object.")
    return data


def _action(recipient: str, space: str, expected: str | None, present: bool | None, actual: str | None,
            no_end_dates: bool = False) -> str | None:
    """What the owner still does by hand in the portal; None when the portal already agrees."""
    where = f"in the reader settings of space {space}"
    if present is None:  # Not verified: the portal enforces nothing OpenGuildKit could read.
        if expected is None:
            return f"Check {where} that {recipient} no longer has access; remove it there (\"Retirer l'accès\") if it does."
        if no_end_dates:
            return (f"This instance keeps no end date: remove {recipient}'s access {where} (\"Retirer l'accès\") "
                    f"after {expected}, then record it with docs share revoke.")
        return (f"Check that {recipient} has the last day {expected} {where}; on an instance without end dates remove "
                f"the access there (\"Retirer l'accès\") after {expected}, then record it with docs share revoke.")
    if expected is None:
        return None if not present else f"Remove {recipient}'s access {where} (\"Retirer l'accès\"): no running share gives it."
    if not present:
        return f"Invite {recipient} {where} with the last day {expected}, or revoke the share that still gives that access."
    if actual is None:
        return f"Set the last day {expected} for {recipient} {where}: the portal gives that access with no end date."
    if actual != expected:
        return f"Change the last day for {recipient} {where} from {actual} to {expected}, or correct the register."
    return None


def _rows(shares: list[dict], space: str, invited: list[str] | None, expirations: dict | None,
          no_end_dates: bool = False) -> list[dict]:
    """One row per recipient of the space's shares: the register's last day against the portal's.

    Several running shares of one address and space are one access in Documentalist, so the
    register's last day is the latest of them; a revoked share gives no access.
    """
    selected = [share for share in shares if share_space(share) == space]
    recipients = sorted({address.strip().lower() for share in selected for address in share["recipients"]})
    result = []
    today = clock.real_now().date()  # real_now() is UTC, and Documentalist ends access at 00:00 UTC.
    for recipient in recipients:
        current = [s for s in selected if not s["revoked_at"] and recipient in
                   {address.strip().lower() for address in s["recipients"]}]
        expected = max((s["until"] for s in current), default=None)
        row = {"recipient": recipient, "register_until": expected, "shares": [s["id"] for s in current]}
        if invited is None or expirations is None:
            row.update(source="local-register", status="unverified",
                       action=_action(recipient, space, expected, None, None, no_end_dates))
        else:
            present = recipient in {address.strip().lower() for address in invited}
            actual = expirations.get(recipient) if present else None
            action = _action(recipient, space, expected, present, actual)
            active = present and (actual is None or date.fromisoformat(actual) >= today)
            row.update(source="documentalist-api", invited=present, portal_until=actual, policy_active=active,
                       status="matches" if action is None else "mismatch", action=action)
        result.append(row)
    return result


def verify_portal(state: Path, portal: str, user: str) -> dict:
    origin, space, slug = _origin(portal)
    shares = load_shares(state)
    if not any(share_space(share) == space for share in shares):
        raise ValueError(f"The local register has no shares for {space}.")
    if not sys.stdin.isatty():
        raise ValueError("Portal verification needs an interactive terminal for the Documentalist password.")
    password = getpass.getpass(f"Documentalist password for {user}: ")
    opener = build_opener(_NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
    logged_in = False
    source, problem, invited, expirations, no_end_dates = "local-register", None, None, None, False
    try:
        _json(opener, origin, "/api/auth/login", {"email": user, "password": password})
        password = None
        logged_in = True
        listing = _json(opener, origin, "/api/spaces")
        spaces = listing.get("spaces")
        if not isinstance(spaces, list):
            raise ValueError("The instance did not return a space list.")
        found = [item for item in spaces if isinstance(item, dict) and item.get("slug") == slug]
        if len(found) != 1 or not isinstance(found[0].get("id"), str):
            raise ValueError("The selected space is not visible to this account.")
        data = _json(opener, origin, f"/api/spaces/{quote(found[0]['id'], safe='')}/access/invites")
        if not isinstance(data.get("emails"), list) or not all(isinstance(v, str) for v in data["emails"]):
            raise ValueError("The instance did not return its invitation list.")
        if "expirations" not in data:
            no_end_dates = True
            problem = "This Documentalist version keeps no end date per reader; remove each access by hand after its last day."
        elif not isinstance(data["expirations"], dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                                     for k, v in data["expirations"].items()):
            problem = "The instance returned an invalid expiry list; check access by hand."
        elif not all(_DAY.fullmatch(day) for day in data["expirations"].values()):
            problem = "The instance returned an expiry that is not a YYYY-MM-DD day; check access by hand."
        else:
            for day in data["expirations"].values():
                date.fromisoformat(day)
            invited, source = data["emails"], "documentalist-api"
            expirations = {address.strip().lower(): day for address, day in data["expirations"].items()}
    except (HTTPError, URLError, OSError, ValueError, UnicodeError) as error:
        invited, expirations, source = None, None, "local-register"
        problem = f"The portal could not be verified: {_reason(error, origin, logged_in)}"
    finally:
        password = None
        if logged_in:
            try:
                _json(opener, origin, "/api/auth/logout", {})
            except (HTTPError, URLError, OSError, ValueError, UnicodeError):
                pass
    report = {"space": space, "checked_at": clock.real_timestamp(), "source": source, "problem": problem,
              "rows": _rows(shares, space, invited, expirations, no_end_dates),
              "scope": "Invitation settings only; verify actual reader access separately."}
    path = state / "shares" / "portal-observations.json"
    with project_lock(state):
        previous = read_json(path) if path.exists() else {"observations": {}}
        previous.setdefault("observations", {})[space] = report
        write_json(path, previous)
    return report
