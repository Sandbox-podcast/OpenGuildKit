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
