"""Recognize common credentials without reading the environment or using the network."""

from ipaddress import ip_address
import re
from urllib.parse import parse_qsl, urlsplit


_CREDENTIAL = re.compile(
    r"(?<![a-z0-9_])(?:sk_(?:live|test)_[a-z0-9]{8,}|gh[pousr]_[a-z0-9]{16,}|"
    r"github_pat_[a-z0-9_]{20,}|(?:AKIA|ASIA)[a-z0-9]{16}|xox[baprs]-[a-z0-9-]{8,})(?![a-z0-9_])",
    re.IGNORECASE | re.ASCII,
)
_PASSWORD = re.compile(r"""(\b(?:password|passwd|mot de passe)\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)""",
                       re.IGNORECASE)
_EMAIL = re.compile(r"[a-z0-9.!#$%&'*+/=?^_\x60{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.IGNORECASE | re.ASCII)
_QUERY_CREDENTIAL = re.compile(
    r"(?:^|[_-])(?:token|secret|password|passwd|api[_-]?key|access[_-]?key|credential|signature|bearer)(?:$|[_-])",
    re.IGNORECASE,
)
_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".test", ".example", ".invalid", ".onion")
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", re.ASCII)


def looks_like_credential(value: str) -> bool:
    return bool(_CREDENTIAL.search(value))


def redact_credentials(value: str) -> str:
    return _CREDENTIAL.sub("[credential]", _PASSWORD.sub(r"\1[password]", value))


def contains_email(value: str) -> bool:
    return bool(_EMAIL.search(value))


def public_evidence_url(ref: str, field: str) -> None:
    """Validate an HTTPS citation's literal host and query, without resolving its address."""
    try:
        url = urlsplit(ref)
        hostname = url.hostname
        _ = url.port
    except ValueError:
        hostname = None
    if not hostname or url.scheme != "https" or any(char.isspace() for char in ref):
        raise ValueError(f"{field}: a public source needs an https link in ref.")
    if url.username is not None or url.password is not None or any(
        _QUERY_CREDENTIAL.search(name) or looks_like_credential(value)
        for name, value in parse_qsl(url.query, keep_blank_values=True)
    ):
        raise ValueError(f"{field}: a public source must use a link without credentials.")
    host = hostname.rstrip(".")
    try:
        address = ip_address(host)
    except ValueError:
        if (_DOMAIN.fullmatch(host) and not host.rsplit(".", 1)[-1].isdigit()
                and not host.endswith(_PRIVATE_SUFFIXES)):
            return
    else:
        if address.is_global and not address.is_multicast and not address.is_reserved:
            return
    raise ValueError(f"{field}: a public source needs a public host. Cite internal evidence as a project file or tool.")
