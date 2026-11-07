"""A superuser is created from the environment, never from credentials in the repository.

`create_staging_superuser` (deleted 2026-11-07) carried a superuser email and password in its
source, deleted the existing user of that email before recreating it, and printed the password.
Deleting a user cascades to everything that user owns. Django's own `createsuperuser --noinput`
reads DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD and refuses an email that is taken,
which is the whole of what that command should have done. PRODUCTION_DEPLOYMENT_README.md says so.
"""

import os
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command, get_commands
from django.test import TestCase

from users.models import User

ENV = {"DJANGO_SUPERUSER_EMAIL": "ops@trazo.test", "DJANGO_SUPERUSER_PASSWORD": "a-long-test-passphrase"}


def _create():
    out = StringIO()
    with mock.patch.dict(os.environ, ENV):
        call_command("createsuperuser", interactive=False, stdout=out)
    return out.getvalue()


class SuperuserFromEnvironmentTests(TestCase):
    def test_the_command_with_credentials_in_its_source_stays_deleted(self):
        registered = get_commands()
        self.assertIn("createsuperuser", registered)  # read the real registry
        self.assertNotIn("create_staging_superuser", registered)

    def test_createsuperuser_reads_the_environment(self):
        output = _create()
        user = User.objects.get(email="ops@trazo.test")
        self.assertTrue(user.is_superuser and user.is_staff and user.is_active)
        self.assertTrue(user.check_password("a-long-test-passphrase"))
        self.assertNotIn("a-long-test-passphrase", output)

    def test_an_existing_account_is_refused_not_replaced(self):
        _create()
        original = User.objects.get(email="ops@trazo.test")
        with self.assertRaises(CommandError):
            _create()
        self.assertEqual(list(User.objects.filter(email="ops@trazo.test").values_list("pk", flat=True)), [original.pk])
