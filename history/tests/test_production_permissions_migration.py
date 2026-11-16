"""history 0265: the `*_history` permissions hand their grants to `*_production`, then go.

Runs the migration's own `forward` and `backward`, on rows built the way prod has them: 0264
renamed the model, the old permissions stayed on its ContentType, and post_migrate added the new
ones beside them. They get the app registry `migrate` gives them (the historical state just
before 0265), not the live one, so a historical through model or verbose_name is what they read.
"""

import importlib

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase

from history.models import Production
from users.models import User

NAME = "0265_production_permissions_take_over_history"
migration = importlib.import_module(f"history.migrations.{NAME}")
ACTIONS = migration.ACTIONS


class ProductionPermissionsTakeOverTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.state_apps = MigrationLoader(connection).project_state(("history", NAME), at_end=False).apps

    @classmethod
    def setUpTestData(cls):
        cls.content_type = ContentType.objects.get_for_model(Production)
        cls.old = {
            action: Permission.objects.create(
                content_type=cls.content_type, codename=f"{action}_history", name=f"Can {action} history"
            )
            for action in ACTIONS
        }
        cls.staff = User.objects.create_user(
            email="staff@trazo.example", password="x", first_name="S", last_name="T", is_staff=True
        )
        cls.editors = Group.objects.create(name="Editors")
        cls.staff.user_permissions.add(cls.old["view"], cls.old["change"])
        cls.editors.permissions.add(cls.old["add"], cls.old["view"])
        # Already holds the new one too: the move must not duplicate it.
        cls.staff.user_permissions.add(
            Permission.objects.get(content_type=cls.content_type, codename="view_production")
        )

    def _codenames(self):
        return set(Permission.objects.filter(content_type=self.content_type).values_list("codename", flat=True))

    def test_the_fixture_is_the_state_prod_is_in(self):
        """Guards the tests below: both sets present, grants on the old ones."""
        self.assertTrue({f"{a}_history" for a in ACTIONS} <= self._codenames())
        self.assertTrue({f"{a}_production" for a in ACTIONS} <= self._codenames())
        self.assertTrue(self.staff.user_permissions.filter(codename="change_history").exists())

    def test_grants_move_to_the_new_permissions_and_the_old_rows_go(self):
        others_before = Permission.objects.exclude(content_type=self.content_type).count()
        migration.forward(self.state_apps, None)

        self.assertEqual(self._codenames() & {f"{a}_history" for a in ACTIONS}, set())
        self.assertTrue({f"{a}_production" for a in ACTIONS} <= self._codenames())
        self.assertEqual(
            set(self.staff.user_permissions.values_list("codename", flat=True)),
            {"view_production", "change_production"},
        )
        self.assertEqual(
            set(self.editors.permissions.values_list("codename", flat=True)), {"add_production", "view_production"}
        )
        self.assertEqual(Permission.objects.exclude(content_type=self.content_type).count(), others_before)

    def test_an_old_row_with_no_new_one_is_renamed_in_place(self):
        """0264 and 0265 in one run, before post_migrate has created `view_production`."""
        Permission.objects.get(content_type=self.content_type, codename="view_production").delete()
        old_view = self.old["view"]
        migration.forward(self.state_apps, None)

        old_view.refresh_from_db()
        self.assertEqual((old_view.codename, old_view.name), ("view_production", "Can view production"))
        self.assertTrue(self.editors.permissions.filter(pk=old_view.pk).exists())
        self.assertTrue(self.staff.user_permissions.filter(pk=old_view.pk).exists())

    def test_running_again_changes_nothing(self):
        migration.forward(self.state_apps, None)
        before = sorted(Permission.objects.values_list("pk", "codename"))
        grants = (self.staff.user_permissions.count(), self.editors.permissions.count())
        migration.forward(self.state_apps, None)
        self.assertEqual(sorted(Permission.objects.values_list("pk", "codename")), before)
        self.assertEqual((self.staff.user_permissions.count(), self.editors.permissions.count()), grants)

    def test_grants_on_a_leftover_history_content_type_move_too(self):
        """Django skips the ContentType rename when `history.production` already existed, leaving the
        old permissions on `history.history`. The ContentType itself stays: LogEntry cascades."""
        Permission.objects.filter(content_type=self.content_type, codename__endswith="_history").delete()
        leftover = ContentType.objects.create(app_label="history", model="history")
        old_change = Permission.objects.create(
            content_type=leftover, codename="change_history", name="Can change history"
        )
        self.staff.user_permissions.add(old_change)

        migration.forward(self.state_apps, None)

        self.assertFalse(Permission.objects.filter(pk=old_change.pk).exists())
        self.assertTrue(
            self.staff.user_permissions.filter(content_type=self.content_type, codename="change_production").exists()
        )
        self.assertTrue(ContentType.objects.filter(pk=leftover.pk).exists())

    def test_the_reverse_hands_the_grants_back_to_history(self):
        """A rollback past 0264 restores the `History` model, which checks `*_history`."""
        migration.forward(self.state_apps, None)
        migration.backward(self.state_apps, None)

        self.assertEqual(self._codenames(), {f"{a}_history" for a in ACTIONS})
        self.assertEqual(
            set(self.staff.user_permissions.values_list("codename", flat=True)), {"view_history", "change_history"}
        )
        self.assertEqual(
            set(self.editors.permissions.values_list("codename", flat=True)), {"add_history", "view_history"}
        )
        self.assertEqual(
            Permission.objects.get(content_type=self.content_type, codename="view_history").name, "Can view history"
        )
