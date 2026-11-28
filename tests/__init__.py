"""OpenGuildKit tests."""

import os

# Git reads neither the system nor the user's configuration in the tests, and commits under a test identity: a
# contributor's commit.gpgsign, signing key, hooks or name must not change what a test commits. Set for this
# process, the variables reach every git command a test runs and every child process it starts.
GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "OpenGuildKit tests",
    "GIT_AUTHOR_EMAIL": "tests@example.invalid",
    "GIT_COMMITTER_NAME": "OpenGuildKit tests",
    "GIT_COMMITTER_EMAIL": "tests@example.invalid",
}
os.environ.update(GIT_ENVIRONMENT)

# The suite types at a terminal by patching sys.stdin.isatty (support.run_cli, typed=). On Windows the product also
# asks the system whether the handle of standard input is a console, which a CI runner's is not: the suite answers
# yes for every descriptor. tests/test_terminal.py checks the real answer for the NUL device on Windows.
from openguildkit import terminal  # noqa: E402 - INTENTIONAL(#522): after the environment set above

terminal.console = lambda descriptor: True
