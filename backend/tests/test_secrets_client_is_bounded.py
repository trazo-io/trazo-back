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

    def _manager_with(self, fake):
        for patcher in (
            mock.patch.object(skm.boto3, "client", return_value=fake),
            mock.patch.object(skm.SecureKeyManager, "_get_or_create_encryption_key", return_value=b"k"),
            mock.patch.object(skm.cache, "get", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        return skm.SecureKeyManager()

    @override_settings(ENVIRONMENT="production")
    def test_after_a_timeout_lookups_skip_aws_for_a_window_then_retry(self):
        """Review of back #288: a permanent switch would latch a long-lived worker (and its
        health_check() answer) on one blip. It is a window, then AWS is asked again."""
        from botocore.exceptions import ConnectTimeoutError

        fake = mock.Mock()
        fake.get_secret_value.side_effect = ConnectTimeoutError(endpoint_url="https://secretsmanager")
        manager = self._manager_with(fake)
        clock = [1000.0]
        with mock.patch.object(skm.time, "monotonic", side_effect=lambda: clock[0]):
            for name in ("one", "two", "three"):
                self.assertIsNone(manager.get_secret(f"unit_test_{name}"))
            self.assertEqual(fake.get_secret_value.call_count, 1, "inside the window nothing waits on AWS")
            self.assertIsNotNone(manager.secrets_client, "the client is kept, not discarded")
            self.assertEqual(manager.health_check()["status"], "degraded")

            clock[0] += skm.UNREACHABLE_BACKOFF_SECONDS + 1
            fake.get_secret_value.side_effect = None
            fake.get_secret_value.return_value = {"SecretString": "value"}
            fake.list_secrets.return_value = {}
            self.assertEqual(manager.get_secret("unit_test_four"), "value")
            self.assertEqual(fake.get_secret_value.call_count, 2, "after the window it asks again")
            self.assertEqual(manager.health_check()["status"], "healthy")

    @override_settings(ENVIRONMENT="production")
    def test_the_environment_fallback_answers_inside_the_window(self):
        from botocore.exceptions import ReadTimeoutError

        fake = mock.Mock()
        fake.get_secret_value.side_effect = ReadTimeoutError(endpoint_url="https://secretsmanager")
        manager = self._manager_with(fake)
        with mock.patch.dict("os.environ", {"UNIT_TEST_FALLBACK": "from-env"}):
            self.assertEqual(manager.get_secret("unit_test_x", "UNIT_TEST_FALLBACK"), "from-env")
            self.assertEqual(manager.get_secret("unit_test_y", "UNIT_TEST_FALLBACK"), "from-env")
        self.assertEqual(fake.get_secret_value.call_count, 1)
