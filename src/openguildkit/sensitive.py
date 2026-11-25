"""Recognize credentials and personal data in what people and agents give the CLI.

CREDENTIAL_SHAPES is the one table that decides what looks like a credential. Tool settings, task briefs and
answers, review entries and public evidence all go through it, without reading the environment or the network.
A message about a match names the field and the kind of value, never the value.
"""

from ipaddress import ip_address
import re
from urllib.parse import parse_qsl, urlsplit

# A value written in place of a secret, not the secret: a variable (${X}, $X, %X%, {{ x }}), a placeholder (<x>,
# [credential], YOUR_TOKEN) or an ellipsis.
_NOT_A_VALUE = r"""(?![\[$<{%]|(?-i:[A-Z_]+)(?![A-Za-z0-9])|[^\s,;"']*(?:\.\.\.|…))"""
# The value of a setting: quoted, or a run of characters that holds a digit, as generated secrets do and words do not.
# An unquoted run that starts with a name and a colon continues a namespaced name (token:color:#0a66c2), not a value.
_SETTING_VALUE = (rf"""(?:"{_NOT_A_VALUE}[^"\r\n]{{4,}}"|'{_NOT_A_VALUE}[^'\r\n]{{4,}}'"""
                  rf"""|{_NOT_A_VALUE}(?![A-Za-z][A-Za-z-]*:)(?=[^\s,;"']*\d)[^\s,;"']{{8,}})""")
# The name of a secret setting: api_key, AWS_SECRET_ACCESS_KEY, secretAccessKey, x-api-key, or a camelCase name such as
# accessToken or the _authToken of an .npmrc.
_SECRET_KEY = (r"(?:(?:[a-z0-9]+[_-])*(?:api[_-]?key|token|secret|access[_-]?key|secret[_-]?key|client[_-]?secret"
               r"|secret[_-]?access[_-]?key)|_?[a-z][a-z0-9]*(?-i:Token|Secret))")
# The name of a password: password, DB_PASSWORD, POSTGRES_PASSWORD, DB_PWD, PASSPHRASE, dbPassword, --password, mdp.
# A bare pwd is the shell command: only a prefixed name (DB_PWD) is a password.
# A name is tried only where it starts (not after a letter, a digit, or a letter and a separator), so a long line costs
# one pass, not one per word.
_PASSWORD_KEY = (r"(?:(?<![A-Za-z0-9])(?<![A-Za-z0-9][_-])"
                 r"(?:(?:[a-z0-9]+[_-])*(?:password|passwd|passphrase|mdp)|(?:[a-z0-9]+[_-])+pwd)"
                 r"|(?<![A-Za-z0-9])[a-z0-9]+(?-i:Password|Passphrase)|mot de passe)")
# The mysql commands: a search for -p stops at the next one, which has its own search.
_MYSQL = r"\bmysql(?:dump|admin|import|check|show)?\b"
# What a requirement says after "Password:": a word of prose, not a value.
_PASSWORD_PROSE = (r"(?:required|optional|mandatory|hidden|masked|hashed|encrypted|empty|none|min|max|minimum|maximum|must|"
                   r"should|needed|policy|rules?|field|input|reset|expires?|never|always|same|the|an?|and|or|not|is|are|at|"
                   r"to|of|in|for|with|requis|obligatoire|facultatif|optionnel|masqué|haché|chiffré|vide|aucun|"
                   r"doit|le|la|les|un|une|et|ou|de|du|des|pas)")
# The value of a password given as an argument after a space: quoted, or a run of characters that holds a digit.
_ARGUMENT_VALUE = (rf"""(?:"{_NOT_A_VALUE}[^"\r\n]+"|'{_NOT_A_VALUE}[^'\r\n]+'"""
                   rf"""|{_NOT_A_VALUE}(?=[^\s'"]*\d)[^\s'"]{{4,}})""")
# Each shape: its name in messages, the pattern, and the replacement that keeps the surrounding words.
CREDENTIAL_SHAPES = (
    ("a cloud access key ID", re.compile(r"(?<![A-Za-z0-9_])(?:AKIA|ASIA)[A-Za-z0-9]{16}(?![A-Za-z0-9_])"),
     "[credential]"),
    ("a Stripe secret key", re.compile(r"(?<![A-Za-z0-9_])[sr]k_(?:live|test)_[A-Za-z0-9]{8,}"), "[credential]"),
    ("a GitHub token", re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})"),
     "[credential]"),
    ("a Slack token", re.compile(r"(?<![A-Za-z0-9_])xox[abposre]-[A-Za-z0-9-]{8,}"), "[credential]"),
    ("a GitLab token", re.compile(r"(?<![A-Za-z0-9_])glpat-[A-Za-z0-9_-]{20,}"), "[credential]"),
    ("a Google API key", re.compile(r"(?<![A-Za-z0-9_])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"), "[credential]"),
    ("an Anthropic API key", re.compile(r"(?<![A-Za-z0-9_])sk-ant-[A-Za-z0-9_-]{20,}"), "[credential]"),
    ("an OpenAI API key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-|admin-)?(?=[A-Za-z0-9_-]*\d)"
                                     r"[A-Za-z0-9_-]{20,}"), "[credential]"),
    ("an npm token", re.compile(r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9_])"), "[credential]"),
    ("a PyPI token", re.compile(r"(?<![A-Za-z0-9_-])pypi-AgE[A-Za-z0-9_-]{40,}"), "[credential]"),
    ("a Hugging Face token", re.compile(r"(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}(?![A-Za-z0-9_])"), "[credential]"),
    ("an Atlassian API token", re.compile(r"(?<![A-Za-z0-9_])ATATT3[A-Za-z0-9_=-]{20,}"), "[credential]"),
    ("a Linear API key", re.compile(r"(?<![A-Za-z0-9_])lin_(?:api|oauth)_[A-Za-z0-9]{32,}"), "[credential]"),
    ("a Notion token", re.compile(r"(?<![A-Za-z0-9_])ntn_[A-Za-z0-9]{40,}"), "[credential]"),
    ("a Sentry token", re.compile(r"(?<![A-Za-z0-9_])sntry[su]_[A-Za-z0-9+/=_-]{30,}"), "[credential]"),
    ("a Figma token", re.compile(r"(?<![A-Za-z0-9_])figd_[A-Za-z0-9_-]{30,}"), "[credential]"),
    ("a Google OAuth access token", re.compile(r"(?<![A-Za-z0-9_])ya29\.[A-Za-z0-9_-]{20,}"), "[credential]"),
    ("a Slack app token", re.compile(r"(?<![A-Za-z0-9_])xapp-\d+-[A-Za-z0-9-]{16,}"), "[credential]"),
    ("a Stripe webhook secret", re.compile(r"(?<![A-Za-z0-9_])whsec_[A-Za-z0-9]{20,}"), "[credential]"),
    ("a DigitalOcean token", re.compile(r"(?<![A-Za-z0-9_])do[opr]_v1_[A-Za-z0-9]{32,}"), "[credential]"),
    ("a Shopify token", re.compile(r"(?<![A-Za-z0-9_])shp(?:at|ca|pa|ss)_[A-Za-z0-9]{20,}"), "[credential]"),
    ("a Slack webhook link", re.compile(r"(https://hooks\.slack\.com/(?:services|workflows|triggers)/)"
                                        r"[A-Za-z0-9_/-]{20,}"), r"\1[credential]"),
    ("a Discord webhook link", re.compile(r"(https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/)"
                                          r"\d+/[A-Za-z0-9_-]{20,}"), r"\1[credential]"),
    ("a Google OAuth client secret", re.compile(r"(?<![A-Za-z0-9_-])GOCSPX-[A-Za-z0-9_-]{20,}"), "[credential]"),
    ("a SendGrid API key", re.compile(r"(?<![A-Za-z0-9_-])SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{30,}"), "[credential]"),
    ("an Azure storage key", re.compile(r"(?i)(\b(?:Account|SharedAccess)Key=)(?![\[$<{%])[A-Za-z0-9+/=]{20,}"),
     r"\1[credential]"),
    ("a JSON Web Token", re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
     "[credential]"),
    ("a private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
                                 r"(?:.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----)?", re.DOTALL), "[private key]"),
    ("a link with a password", re.compile(r"(?i)(\b[a-z][a-z0-9+.-]{0,31}://[^\s/:@]*:)(?!\[)[^\s/@]+@"), r"\1[password]@"),
    ("a secret in a query string", re.compile(
        r"(?i)([?&;](?:[a-z0-9_.-]*[_-])?(?:token|secret|password|passwd|api[_-]?key|access[_-]?key|signature|sig)=)"
        r"(?![\[$<{])[^&#\s\"']+"), r"\1[credential]"),
    ("a password", re.compile(rf"""(?i)({_PASSWORD_KEY}["']?\s*[:=]\s*)(?![\[$<{{%])(?!{_PASSWORD_PROSE}(?![\w'-]))"""
                              r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]*[^\s,;.!?)])"""), r"\1[password]"),
    # mysql -pSECRET, mysqldump -pSECRET: the value follows -p without a space; -p alone asks for it. Elsewhere the value
    # follows --password, --pass or the -p of sshpass and of a login, after a space.
    ("a password on a command line", re.compile(
        rf"({_MYSQL}(?:(?!{_MYSQL})[^\n])*?\s-p)(?![\[$<{{%])[^\s'\"]{{4,}}"
        rf"|((?<![\w-])--pass(?:word|wd|phrase)?[ \t]+|\b(?:sshpass|login)\b[^\n]{{0,200}}?[ \t]-p[ \t]+){_ARGUMENT_VALUE}"),
     r"\1\2[password]"),
    ("an authorization header", re.compile(
        r"""(?i)(\bauthorization["']?\s*[:=]\s*["']?(?:bearer|basic|token)\s+)"""
        rf"""{_NOT_A_VALUE}[A-Za-z0-9._~+/=-]{{8,}}"""), r"\1[credential]"),
    # api_key: …, token=…, client_secret = "…", AWS_SECRET_ACCESS_KEY=…; a query string has its own shape above.
    ("a secret in a setting", re.compile(rf"""(?i)(?<![?&;/=\w-])({_SECRET_KEY}["']?\s*[:=]\s*){_SETTING_VALUE}"""),
     r"\1[credential]"),
)
PERSONAL_SHAPES = (
    ("an email address", re.compile(r"(?<![a-z0-9.!#$%&'*+/=?^_\x60{|}~-])[a-z0-9.!#$%&'*+/=?^_\x60{|}~-]+@"
                                    r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.IGNORECASE | re.ASCII)),
    ("a phone number", re.compile(r"(?<![\w+])(?:\+\d{1,3}[ .-]?\d(?:[ .-]?\d){7,12}|0\d(?:[ .-]?\d{2}){4})(?!\w)")),
    ("a bank account number", re.compile(r"\b[A-Z]{2}\d{2} ?(?:[A-Z0-9]{4} ?){2,7}[A-Z0-9]{1,4}\b")),
)
WHERE = "a credential belongs in each person's environment or in the tool's own vault"
_QUERY_CREDENTIAL = re.compile(
    r"(?:^|[_-])(?:token|secret|password|passwd|api[_-]?key|access[_-]?key|credential|signature|bearer)(?:$|[_-])",
    re.IGNORECASE,
)
_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".test", ".example", ".invalid", ".onion")
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", re.ASCII)


def credential_kind(value: str) -> str | None:
    """The name of the first credential shape found in value, or None."""
    return next((name for name, pattern, _ in CREDENTIAL_SHAPES if pattern.search(value)), None)


def looks_like_credential(value: str) -> bool:
    return credential_kind(value) is not None


def redact_credentials(value: str) -> str:
    """The text with every credential replaced by a placeholder, the rest of the words kept."""
    for _, pattern, replacement in CREDENTIAL_SHAPES:
        value = pattern.sub(replacement, value)
    return value


def redact_data(value: object) -> object:
    """A JSON value with every string redacted, such as task answers given in a file."""
    if isinstance(value, str):
        return redact_credentials(value)
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    return value


def personal_data_kinds(value: str) -> list[str]:
    return [name for name, pattern in PERSONAL_SHAPES if pattern.search(value)]


def input_warnings(original: object, recorded: object, label: str) -> list[str]:
    """What a person should know about what was recorded: a credential replaced, personal data kept. No value is shown."""
    warnings = []
    if recorded != original:
        warnings.append(f"Warning: replaced a possible credential in the {label} with a placeholder before recording "
                        f"it: {WHERE}.")
    texts = [recorded] if isinstance(recorded, str) else _texts(recorded)
    kinds = list(dict.fromkeys(kind for text in texts for kind in personal_data_kinds(text)))
    if kinds:
        warnings.append(f"Warning: the {label} contains {' and '.join(kinds)}. It is stored in the task record "
                        "and shown to the boards: keep personal data out unless it is a role address.")
    return warnings


def _texts(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _texts(item)]
    return []


def credential_problems(value: object, path: str) -> list[str]:
    """One problem per field of a JSON value that holds a credential, named by its key path, value not shown."""
    if isinstance(value, str):
        kind = credential_kind(value)
        return [f"{path}: contains what looks like {kind}; remove it, {WHERE}."] if kind else []
    if isinstance(value, list):
        return [problem for index, item in enumerate(value) for problem in credential_problems(item, f"{path}[{index}]")]
    if isinstance(value, dict):
        return [problem for key, item in value.items() for problem in credential_problems(item, f"{path}.{key}")]
    return []


def _carries_credentials(url) -> bool:
    return url.username is not None or url.password is not None or any(
        _QUERY_CREDENTIAL.search(name) or looks_like_credential(value)
        for name, value in parse_qsl(url.query, keep_blank_values=True)
    )


def refuse_link_credentials(ref: str, field: str) -> None:
    """Refuse a link with a user name, a password or a credential in its query string; the link is never repeated."""
    try:
        url = urlsplit(ref.strip())
    except ValueError:
        return
    if _carries_credentials(url):
        raise ValueError(f"{field}: the link must carry no user name, password or token: the address is recorded as "
                         f"written, and {WHERE}.")


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
    if _carries_credentials(url):
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
