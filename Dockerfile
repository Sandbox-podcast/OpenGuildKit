# The container image of OpenGuildKit. The `image` job of .github/workflows/release.yml builds it from the wheel
# the release attested and pushes it to ghcr.io, only when the repository variable GHCR_PUBLISH is "true"
# (docs/install.md, "Package managers"). The build context is the folder that holds the wheel.
#   docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" ghcr.io/sandbox-podcast/openguildkit:X.Y.Z check
# 2026-11-28 python:3.13-slim, digest of the multi-platform index read from Docker Hub that day
FROM python:3.13-slim@sha256:168d3a5d10f2152f8e8d77b6843ac82c22a846cfefeef7afdf9aa630404e82a7

COPY openguildkit-*-py3-none-any.whl /tmp/
# The wheel has no dependency: no index is needed.
RUN python -m pip install --no-cache-dir --no-index /tmp/openguildkit-*-py3-none-any.whl \
    && rm /tmp/openguildkit-*-py3-none-any.whl \
    && useradd --create-home --uid 10001 openguildkit

USER openguildkit
WORKDIR /work
ENTRYPOINT ["openguildkit"]
