"""
Settings for the test suite: CI and local `manage.py test`.

This is `dev` plus the overrides that only make tests faster. It deliberately does NOT carry its
own database, cache, middleware or storage configuration: until 2026-10-02 this file did, nothing
ran it (CI used `backend.settings.dev`), and it had drifted far enough that a later security
system check (`security.E002`, local media storage) refused to boot it. A second, independent
settings tree that nobody executes is a copy waiting to disagree. Anything a test needs that dev
does not provide belongs in dev or in the test itself.

Usage:
    DJANGO_SETTINGS_MODULE=backend.settings.test poetry run python manage.py test ... --parallel 4

On a multi-core laptop `--parallel` roughly halves the run. In CI it does not (see
backend/test_runner.py); CI splits the suite into shards instead.
"""

from backend.settings.dev import *  # noqa: F401,F403

# Argon2 is deliberately slow (that is its job in production). The suite creates ~500 users and
# hashes a password for each, so under test it was a fixed tax on every setUp. Measured on the
# CI module list (1605 tests): 451s -> 416s. Nothing in the suite asserts on the algorithm.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# base.py turns this on whenever DEBUG is falsy, and dev.py takes DEBUG from the environment with a
# False default. CI sets DEBUG=True; a plain local `manage.py test` does not, and then
# SecurityMiddleware 301s every test-client request before it reaches a view. Pinned here so the
# suite does not depend on an environment variable to mean what it says.
SECURE_SSL_REDIRECT = False
