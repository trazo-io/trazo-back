"""Public URL resolution — the values baked into QR images and outbound email links.

Why this file exists: `backend/subdomain_config.py` reads ENVIRONMENT at import time with
`default="development"`, and `backend/settings/prod.py` is imported *after* that default has
already been consumed. Before 2026-08-07 that meant a deployment whose environment did not set
ENVIRONMENT silently inherited `http://consumer.localhost:3000/`.

That is not a degraded experience. `history/models.py` bakes BASE_CONSUMER_URL into the QR
*image* at generation time, so the farm prints dead codes and only discovers it when a buyer
scans one. The same values back every verification, password-reset and invitation email.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

from backend.subdomain_config import find_non_public_urls, get_frontend_urls


class FrontendUrlDerivationTests(SimpleTestCase):
    """`get_frontend_urls` must answer for the environment it is ASKED about."""

    def test_production_resolves_to_public_trazo_hosts(self):
        urls = get_frontend_urls("production")
        self.assertEqual(urls["BASE_APP_URL"], "https://app.trazo.io/")
        self.assertEqual(urls["BASE_CONSUMER_URL"], "https://consumer.trazo.io/")

    def test_staging_uses_its_own_subdomains(self):
        # Regression: the previous implementation read the MODULE-level APP_SUBDOMAIN, which is
        # resolved once from the ambient ENVIRONMENT. Asking for staging from a non-staging
        # process therefore returned app.trazo.io — production's hostname — for staging.
        urls = get_frontend_urls("staging")
        self.assertEqual(urls["BASE_APP_URL"], "https://app-staging.trazo.io/")
        self.assertEqual(urls["BASE_CONSUMER_URL"], "https://consumer-staging.trazo.io/")

    def test_development_is_the_only_environment_that_yields_localhost(self):
        urls = get_frontend_urls("development")
        self.assertIn("localhost", urls["BASE_CONSUMER_URL"])

    def test_unknown_environment_falls_back_to_development(self):
        # A typo in the environment variable must NOT silently produce a plausible-looking
        # public URL. It falls back to localhost, which the boot guard below then rejects
        # loudly — a dead deploy is recoverable, dead printed QR codes are not.
        self.assertEqual(get_frontend_urls("prod"), get_frontend_urls("development"))
        self.assertEqual(get_frontend_urls("PRODUCTION"), get_frontend_urls("development"))


class NonPublicUrlGuardTests(SimpleTestCase):
    """The boot guard deployed settings use to refuse an unreachable configuration."""

    def test_public_urls_pass(self):
        self.assertEqual(
            find_non_public_urls(
                {
                    "BASE_APP_URL": "https://app.trazo.io/",
                    "BASE_CONSUMER_URL": "https://consumer.trazo.io/",
                    "BASE_URL": "https://api.trazo.io/",
                }
            ),
            [],
        )

    def test_localhost_is_reported_with_its_setting_name(self):
        # The message has to name the setting: an operator reading a failed deploy needs to
        # know WHICH variable to set, not merely that something is wrong.
        self.assertEqual(
            find_non_public_urls({"BASE_CONSUMER_URL": "http://consumer.localhost:3000/"}),
            ["BASE_CONSUMER_URL=http://consumer.localhost:3000/"],
        )

    def test_loopback_and_wildcard_hosts_are_caught(self):
        for value in ("http://127.0.0.1:8000/", "http://0.0.0.0:8000/", "http://[::1]:8000/"):
            with self.subTest(value=value):
                self.assertEqual(find_non_public_urls({"BASE_URL": value}), [f"BASE_URL={value}"])

    def test_every_offending_url_is_reported_not_just_the_first(self):
        # Reporting one at a time would mean one failed deploy per misconfigured variable.
        self.assertEqual(
            find_non_public_urls(
                {
                    "BASE_APP_URL": "http://localhost:3000/",
                    "BASE_CONSUMER_URL": "http://localhost:3000/",
                    "BASE_URL": "https://api.trazo.io/",
                }
            ),
            ["BASE_APP_URL=http://localhost:3000/", "BASE_CONSUMER_URL=http://localhost:3000/"],
        )

    def test_a_public_host_merely_containing_localhost_is_not_flagged(self):
        # The check matches the parsed HOSTNAME, not a substring of the URL. `localhost.example.com`
        # is a perfectly reachable public host; failing a deploy over it would be its own outage.
        self.assertEqual(find_non_public_urls({"BASE_URL": "https://localhost.example.com/"}), [])
        self.assertEqual(find_non_public_urls({"BASE_URL": "https://mylocalhost.trazo.io/"}), [])

    def test_localhost_in_a_query_parameter_is_not_flagged(self):
        # The host being served is public; what a query string mentions is not this guard's business.
        self.assertEqual(
            find_non_public_urls({"BASE_APP_URL": "https://app.trazo.io/?next=http://localhost:3000/"}),
            [],
        )

    def test_localhost_subdomain_is_flagged(self):
        # This is the shape development actually uses, and the one that reached QR images.
        self.assertEqual(
            find_non_public_urls({"BASE_CONSUMER_URL": "http://consumer.localhost:3000/"}),
            ["BASE_CONSUMER_URL=http://consumer.localhost:3000/"],
        )

    def test_whole_loopback_range_is_flagged_not_just_127_0_0_1(self):
        self.assertEqual(
            find_non_public_urls({"BASE_URL": "http://127.0.0.53:8000/"}),
            ["BASE_URL=http://127.0.0.53:8000/"],
        )

    def test_a_bare_host_with_no_scheme_is_still_flagged(self):
        # "localhost:3000" parses as scheme="localhost" with no hostname at all, so a naive
        # urlparse().hostname check would wave it through.
        self.assertEqual(find_non_public_urls({"BASE_URL": "localhost:3000"}), ["BASE_URL=localhost:3000"])

    def test_none_and_empty_values_are_not_flagged_as_non_public(self):
        # An unset URL is a different failure (caught elsewhere); this guard is only about
        # values that ARE set and point somewhere unreachable.
        self.assertEqual(find_non_public_urls({"BASE_URL": None, "FRONTEND_URL": ""}), [])


class DeployedSettingsRejectNonPublicUrlsTests(SimpleTestCase):
    """The guard is actually wired into prod.py, not merely available to it."""

    @staticmethod
    def _prod_source():
        return (Path(__file__).resolve().parents[1] / "settings" / "prod.py").read_text()

    def test_prod_settings_module_calls_the_guard(self):
        text = self._prod_source()
        self.assertIn("find_non_public_urls", text)
        # ...and derives its URLs from the environment it knows it is, rather than inheriting
        # base.py's development-defaulted fallback.
        self.assertIn("get_frontend_urls(ENVIRONMENT)", text)

    def test_every_subdomain_config_symbol_prod_uses_is_explicitly_imported(self):
        """prod.py does `from backend.settings.base import *`, which re-exports only the names
        base.py itself imported — a FIXED list. A symbol added to subdomain_config later is
        therefore NOT available in prod.py unless prod.py imports it directly.

        This already bit once: `find_non_public_urls` was called in prod.py while only
        `get_frontend_urls` was reachable, and prod settings died with NameError at boot.
        flake8 cannot catch it — `import *` downgrades undefined names to F405, which is not
        in CI's `--select=E9,F63,F7,F82` gate (verified). Hence this test.
        """
        import backend.subdomain_config as subdomain_config

        tree = ast.parse(self._prod_source())

        explicitly_imported = set()
        bound_locally = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.asname or alias.name for alias in node.names}
                bound_locally |= names
                if node.module == "backend.subdomain_config":
                    explicitly_imported |= names
            elif isinstance(node, ast.Import):
                bound_locally.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
            elif isinstance(node, ast.Assign):
                bound_locally.update(t.id for t in node.targets if isinstance(t, ast.Name))

        # Only the callables matter — a same-named constant in both modules (ENVIRONMENT) is
        # not a shared dependency, and prod.py assigns its own.
        module_functions = {
            name
            for name, value in vars(subdomain_config).items()
            if not name.startswith("_")
            and callable(value)
            and getattr(value, "__module__", "") == subdomain_config.__name__
        }
        used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} & module_functions

        missing = sorted(used - explicitly_imported - bound_locally)
        self.assertEqual(
            missing,
            [],
            f"prod.py references {missing} from backend.subdomain_config without importing "
            "them directly; `import *` from base.py will not provide them and prod will "
            "raise NameError at boot.",
        )
