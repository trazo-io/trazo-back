"""The Secrets Manager lookups that run on every boot cannot hold the boot for a minute (2026-11-04).

Settings import calls `SecureKeyManager` for ~14 secrets, three times per production boot. The
client was built with botocore's defaults (60 s connect, 60 s read, retries), so a single stalled
connection kept the new container from listening on :8000 long enough for App Platform's readiness
probe to fail and roll the deploy back.
"""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from backend.security import secure_key_manager as skm


class SecretsClientIsBoundedTests(SimpleTestCase):
    @override_settings(ENVIRONMENT="production")
    def test_the_production_client_has_short_timeouts_and_few_retries(self):
        with (
            mock.patch.object(skm.boto3, "client") as client,
            mock.patch.object(skm.SecureKeyManager, "_get_or_create_encryption_key", return_value=b"k"),
        ):
            skm.SecureKeyManager()

        client.assert_called_once()
        config = client.call_args.kwargs.get("config")
        self.assertIsNotNone(config, "the secretsmanager client must be built with an explicit Config")
        self.assertLessEqual(config.connect_timeout, 5)
        self.assertLessEqual(config.read_timeout, 10)
        self.assertLessEqual(config.retries["max_attempts"], 3)

    @override_settings(ENVIRONMENT="production")
    def test_an_unreachable_service_is_asked_once_per_process(self):
        from botocore.exceptions import ConnectTimeoutError

        fake = mock.Mock()
        fake.get_secret_value.side_effect = ConnectTimeoutError(endpoint_url="https://secretsmanager")
        with (
            mock.patch.object(skm.boto3, "client", return_value=fake),
            mock.patch.object(skm.SecureKeyManager, "_get_or_create_encryption_key", return_value=b"k"),
            mock.patch.object(skm.cache, "get", return_value=None),
        ):
            manager = skm.SecureKeyManager()
            for name in ("one", "two", "three"):
                self.assertIsNone(manager.get_secret(f"unit_test_{name}"))

        self.assertEqual(fake.get_secret_value.call_count, 1)
        self.assertIsNone(manager.secrets_client)
