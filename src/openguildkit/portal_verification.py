"""Compare a local share register with one Documentalist instance on explicit request.

The observation describes the server's invitation policy, not a live reader session.
Credentials are requested at a terminal, held in memory and never saved in the register.
"""

import getpass
import http.cookiejar
import json
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

from . import clock
from .publishing import load_shares, share_space, portal_space
from .storage import project_lock, read_json, write_json


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        fp.close()
        raise ValueError("Documentalist redirected the request; no credentials were forwarded.")


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


def _rows(shares: list[dict], space: str, invited: list[str] | None, expirations: dict | None) -> list[dict]:
    selected = [share for share in shares if share_space(share) == space]
    recipients = sorted({address.strip().lower() for share in selected for address in share["recipients"]})
    result = []
    today = clock.real_now().date()  # Documentalist expires at the end of the UTC day.
    for recipient in recipients:
        current = [s for s in selected if not s["revoked_at"] and recipient in
                   {address.strip().lower() for address in s["recipients"]}]
        expected = max((s["until"] for s in current), default=None)
        row = {"recipient": recipient, "register_until": expected, "shares": [s["id"] for s in current]}
        if invited is None or expirations is None:
            row.update(source="local-register", status="unverified", action="Check the invitation and remove or update it in Documentalist.")
        else:
            present = recipient in {address.strip().lower() for address in invited}
            actual = expirations.get(recipient) if present else None
            # A missing expiry is an indefinite invitation, not a date matching an empty register.
            matches = (not present if expected is None else present and actual == expected)
            active = present and (actual is None or date.fromisoformat(actual) >= today)
            row.update(source="documentalist-api", invited=present, portal_until=actual, policy_active=active,
                       status="matches" if matches else "mismatch",
                       action=None if matches else "Reconcile the date or invitation in Documentalist with the shares of this space.")
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
    source, problem, invited, expirations = "local-register", None, None, None
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
            problem = "This Documentalist version does not expose invitation expiry; check and remove access by hand."
        elif not isinstance(data["expirations"], dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                                     for k, v in data["expirations"].items()):
            problem = "The instance returned an invalid expiry list; check access by hand."
        else:
            invited, expirations, source = data["emails"], data["expirations"], "documentalist-api"
            for day in expirations.values():
                date.fromisoformat(day)
    except (HTTPError, URLError, OSError, ValueError, UnicodeError, json.JSONDecodeError):
        invited, expirations, source = None, None, "local-register"
        problem = "The portal could not be verified. Check the address, account, permissions and access in Documentalist."
    finally:
        password = None
        if logged_in:
            try:
                _json(opener, origin, "/api/auth/logout", {})
            except (HTTPError, URLError, OSError, ValueError, UnicodeError):
                pass
    report = {"space": space, "checked_at": clock.real_timestamp(), "source": source, "problem": problem,
              "rows": _rows(shares, space, invited, expirations),
              "scope": "Invitation settings only; verify actual reader access separately."}
    path = state / "shares" / "portal-observations.json"
    with project_lock(state):
        previous = read_json(path) if path.exists() else {"observations": {}}
        previous.setdefault("observations", {})[space] = report
        write_json(path, previous)
    return report
