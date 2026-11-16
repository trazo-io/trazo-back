"""`History` is `Production`: a rename that moves no row (schema remodel Phase 3, 2026-11-14).

The migration (history 0264) must change nothing in the database but the `django_content_type`
row, and must change that row IN PLACE: auditlog entries point at the content type by id, so a new
id would detach the season's whole audit trail. This replays the deploy on a database that holds a
season, a post-harvest link and the season's audit entries, the way production does:

1. step the database back to 0263 with the migration executor (no signals run, so the content type
   is left alone) and put the content type row back to the name it has in production today;
2. run the real `migrate` command forward. Its pre-migrate hook is what injects the content type
   rename; the executor alone never would.

A backward `migrate` command is not used to get to step 1: its post-migrate hook would create a
"production" content type from today's models, and the forward rename would then fall back to
leaving the old row behind. That is a test artefact; production only ever migrates forward.
"""

from io import StringIO

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from auditlog.models import LogEntry

BEFORE_RENAME = ("history", "0263_production_method_has_no_default")


class HistoryIsProductionTests(TransactionTestCase):
    def setUp(self):
        from certifications.models import PostHarvestFacility
        from company.models import Company, Establishment
        from history.models import Production
        from product.models import Parcel

        est = Establishment.objects.create(name="Rename Farm", company=Company.objects.create(name="Rename Co"))
        parcel = Parcel.objects.create(name="North", establishment=est, area=1)
        self.season = Production.objects.create(parcel=parcel, name="2026 Walnuts")
        self.facility = PostHarvestFacility.objects.create(
            establishment=est, name="Huller", facility_type="huller", role="both", operated_by="third_party"
        )
        self.season.post_harvest_facilities.add(self.facility)
        self.content_type = ContentType.objects.get_for_model(Production)
        self.entries = LogEntry.objects.filter(content_type_id=self.content_type.pk, object_pk=str(self.season.pk))

    def test_the_names_are_the_new_ones(self):
        from history import models as history_models
        from history.models import Production, ProductionPostHarvestFacility

        # The alias old imports used, until the PR that deletes it. Read by name, so the guard against
        # the old name in code (test_model_is_called_production) does not count this as a use.
        self.assertIs(getattr(history_models, "History", None), Production)
        self.assertEqual(Production._meta.db_table, "history_history")
        self.assertEqual((self.content_type.app_label, self.content_type.model), ("history", "production"))
        link = ProductionPostHarvestFacility._meta
        self.assertEqual(link.db_table, "history_history_post_harvest_facilities")
        self.assertEqual(link.get_field("history").column, "history_id")

    def test_the_deploy_renames_the_content_type_in_place_and_moves_no_row(self):
        from history.models import Production

        audit_entries = self.entries.count()
        self.assertGreaterEqual(audit_entries, 1)

        executor = MigrationExecutor(connection)
        executor.migrate([BEFORE_RENAME])
        ContentType.objects.filter(pk=self.content_type.pk).update(model="history")
        ContentType.objects.clear_cache()
        with connection.cursor() as cursor:  # the link table as the previous release reads it
            cursor.execute("SELECT history_id, postharvestfacility_id FROM history_history_post_harvest_facilities")
            self.assertEqual(cursor.fetchall(), [(self.season.pk, self.facility.pk)])

        call_command("migrate", verbosity=0, stdout=StringIO())

        ContentType.objects.clear_cache()
        renamed = ContentType.objects.get(pk=self.content_type.pk)
        self.assertEqual((renamed.app_label, renamed.model), ("history", "production"))
        self.assertFalse(ContentType.objects.filter(app_label="history", model="history").exists())
        self.assertEqual(self.entries.count(), audit_entries)
        season = Production.objects.get(pk=self.season.pk)
        self.assertEqual(list(season.post_harvest_facilities.values_list("pk", flat=True)), [self.facility.pk])
        with connection.cursor() as cursor:
            cursor.execute("SELECT history_id FROM history_history_post_harvest_facilities")
            self.assertEqual(cursor.fetchall(), [(self.season.pk,)])
