#!/bin/sh
# Install the OpenGuildKit command from a GitHub release, in one line:
#
#   curl --proto '=https' --tlsv1.2 -fsSL https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.sh | sh
#   curl --proto '=https' --tlsv1.2 -fsSL https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.sh | sh -s -- --version 0.18.0
#
# It downloads SHA256SUMS.txt and the wheel of the release, checks the wheel's SHA-256 against that file and
# only then installs it with pipx, or with uv when pipx is missing. Without a version it takes the latest release,
# which GitHub never sets to a pre-release; a pre-release is installed only when named with --version.
# Its own downloads use https only, also after a redirect, and TLS 1.2 or later.
# docs/install.md describes it, and the manual installation it replaces.
#
# OPENGUILDKIT_RELEASES_URL replaces https://github.com/Sandbox-podcast/OpenGuildKit/releases. It is reserved
# for the tests, which serve a fake release from a local folder: do not set it otherwise.
set -eu

RELEASES="${OPENGUILDKIT_RELEASES_URL:-https://github.com/Sandbox-podcast/OpenGuildKit/releases}"
VERSION=""
# https only, which curl also applies to a redirect. The tests serve a folder through file://.
PROTO='=https'
case "$RELEASES" in file://*) PROTO='=https,file' ;; esac

fail() {
    printf 'openguildkit install: %s\n' "$1" >&2
    exit 1
}

# download URL FILE: the reason curl gives stays in $WORK/curl.err for the message that follows a failure.
download() {
    curl --proto "$PROTO" --tlsv1.2 -fsSL -o "$2" "$1" 2> "$WORK/curl.err"
}

why() {
    sed -e '$!d' -e 's/^curl: //' "$WORK/curl.err"
}

usage() {
    printf '%s\n' "Usage: install.sh [--version X.Y.Z]" \
        "Installs the OpenGuildKit wheel of a GitHub release with pipx or uv, after checking its SHA-256." \
        "Without --version, installs the latest release (never a pre-release)."
}

while [ $# -gt 0 ]; do
    case "$1" in
        --version)
            [ $# -ge 2 ] || fail "--version needs a version, for example --version 0.18.0."
            VERSION="$2"
            shift 2
            ;;
        --version=*)
            VERSION="${1#--version=}"
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "unknown argument '$1'."
            ;;
    esac
done

VERSION="${VERSION#v}"
case "$VERSION" in
    *[!0-9A-Za-z.+-]* | .* | *..*)
        fail "'$VERSION' is not a version: give it as on the releases page, for example --version 0.18.0." ;;
esac

if command -v pipx > /dev/null 2>&1; then
    INSTALLER=pipx
elif command -v uv > /dev/null 2>&1; then
    INSTALLER=uv
else
    printf '%s\n' "openguildkit install: neither pipx nor uv is installed. Install one of them, then run this again:" \
        "  pipx: python3 -m pip install --user pipx && python3 -m pipx ensurepath   (https://pipx.pypa.io/stable/how-to/install-pipx.html)" \
        "  uv:   curl -LsSf https://astral.sh/uv/install.sh | sh   (https://docs.astral.sh/uv/getting-started/installation/)" >&2
    exit 1
fi

command -v curl > /dev/null 2>&1 || fail "curl is needed to download the release: install it, then run this again."

if command -v sha256sum > /dev/null 2>&1; then
    SHA256="sha256sum"
elif command -v shasum > /dev/null 2>&1; then
    SHA256="shasum -a 256"
elif command -v openssl > /dev/null 2>&1; then
    SHA256="openssl dgst -sha256 -r"
else
    fail "no SHA-256 tool found (sha256sum, shasum or openssl): install one, then run this again."
fi

WORK=$(mktemp -d 2> /dev/null || mktemp -d -t openguildkit)
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM

if [ -n "$VERSION" ]; then
    SUMS_URL="$RELEASES/download/v$VERSION/SHA256SUMS.txt"
    WHERE="release v$VERSION"
else
    SUMS_URL="$RELEASES/latest/download/SHA256SUMS.txt"
    WHERE="latest release"
fi
download "$SUMS_URL" "$WORK/SHA256SUMS.txt" \
    || fail "could not download SHA256SUMS.txt of the $WHERE ($SUMS_URL): $(why). Check the version on $RELEASES."

# The wheel's line names the version: the latest release says which one it is.
LINE=$(grep -E '^[0-9a-fA-F]{64}  ?\*?openguildkit-[0-9A-Za-z.+]+-py3-none-any\.whl$' "$WORK/SHA256SUMS.txt" | head -n 1 || true)
[ -n "$LINE" ] || fail "SHA256SUMS.txt of the $WHERE lists no OpenGuildKit wheel: nothing was installed."
EXPECTED=$(printf '%s\n' "$LINE" | cut -d ' ' -f 1 | tr 'A-F' 'a-f')
WHEEL=$(printf '%s\n' "$LINE" | sed -e 's/^[0-9a-fA-F]* *\**//')
FOUND="${WHEEL#openguildkit-}"
FOUND="${FOUND%-py3-none-any.whl}"
if [ -n "$VERSION" ] && [ "$FOUND" != "$VERSION" ]; then
    fail "SHA256SUMS.txt of release v$VERSION lists $WHEEL, not version $VERSION: nothing was installed."
fi
VERSION="$FOUND"

WHEEL_URL="$RELEASES/download/v$VERSION/$WHEEL"
download "$WHEEL_URL" "$WORK/$WHEEL" \
    || fail "could not download $WHEEL of release v$VERSION ($WHEEL_URL): $(why)."
printf 'Downloaded OpenGuildKit %s from %s/tag/v%s\n' "$VERSION" "$RELEASES" "$VERSION"

ACTUAL=$($SHA256 "$WORK/$WHEEL" | cut -d ' ' -f 1 | tr 'A-F' 'a-f')
if [ "$ACTUAL" != "$EXPECTED" ]; then
    fail "the SHA-256 of $WHEEL ($ACTUAL) differs from SHA256SUMS.txt of release v$VERSION ($EXPECTED): nothing was installed. Download it again; if it still differs, report it to the maintainers (SECURITY.md)."
fi
printf 'Checked its SHA-256 against SHA256SUMS.txt of release v%s\n' "$VERSION"

# --force replaces an installed version, so the same line upgrades.
if [ "$INSTALLER" = pipx ]; then
    set -- pipx install --force "$WORK/$WHEEL"
else
    set -- uv tool install --force "$WORK/$WHEEL"
fi
if ! "$@" > "$WORK/install.log" 2>&1; then
    cat "$WORK/install.log" >&2
    fail "$* failed: the output above says why."
fi
printf 'Installed with %s\n' "$INSTALLER"
printf 'Next: openguildkit --version, then openguildkit init in your repository\n'
