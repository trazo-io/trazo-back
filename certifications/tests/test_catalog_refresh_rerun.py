"""Triage of `refresh_organic_input_catalogs` before anything schedules it (2026-11-02).

The command's docstring said it was "intended" to run weekly and after every deploy, and nothing
ran it. `backend/scheduled_work.py` holds the rule that a dormant scheduled task is ARMED, not
inert, so before wiring it each step was asked what a re-run does to a PRODUCTION database that is
already seeded and whose Organic System Plans cite catalog rows:

  (a) does it create duplicates?           (b) does it delete or re-key a cited row?
  (c) does it overwrite operator data?     (d) does it fabricate identifiers?
  (e) does a failure fail loudly or record IngestionRun(status="error"), never a quiet "ok"?

The answers are pinned here by running the full refresh TWICE against a database holding an OSP
that cites catalog rows through both citing relations (the approved-inputs M2Ms and
`PlanMaterialEntry`'s catalog FKs), plus the legacy rows a production database seeded before
2026-09-06 can still hold. The verdict: re-running is stable, so running it by hand is safe. It is
still NOT scheduled, because its seed steps re-read committed CSVs and a cron would only stamp a
fresh "last synced" date on an unchanged edition. Only the eCFR step is scheduled; the second half
of this module pins that path. Every eCFR call is mocked: CI has no network.
"""

import csv
import os
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from backend.scheduled_work import DISPATCHED_BY_CADENCE, PERIODIC_WORK
from certifications.models import (
    IngestionRun,
    NationalListRevision,
    OMRIProduct,
    OrganicSystemPlan,
    PlanMaterialEntry,
    WSDAMaterial,
)
from certifications.services.national_list_check import check_national_list_ecfr, unreviewed_changes
from company.models import Company, Establishment

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _first_wsda_row():
    with open(os.path.join(_DATA, "wsda_seed.csv"), newline="", encoding="utf-8") as fh:
        return next(csv.DictReader(fh))


def _snapshot():
    return {
        "omri_rows": OMRIProduct.objects.count(),
        "wsda_rows": WSDAMaterial.objects.count(),
        "omri_cdfa_flagged": OMRIProduct.objects.filter(is_cdfa_oim_registered=True).count(),
        "wsda_cdfa_flagged": WSDAMaterial.objects.filter(is_cdfa_oim_registered=True).count(),
        "omri_delisted": OMRIProduct.objects.exclude(delisted_on=None).count(),
        "omri_pks": dict(OMRIProduct.objects.values_list("omri_id", "pk")),
        "wsda_pks": dict(WSDAMaterial.objects.values_list("wsda_id", "pk")),
    }


class ReRunningTheRefreshIsStable(TestCase):
    """Two full runs, `--skip-ecfr`, against an already-cited catalogue."""

    @classmethod
    def setUpTestData(cls):
        company = Company.objects.create(name="Rerun Orchards")
        establishment = Establishment.objects.create(name="Home Block", company=company, state="WA")
        cls.osp = OrganicSystemPlan.objects.create(establishment=establishment, version_number=1, status="active")

        # Rows a production database seeded before 2026-09-06 can still hold, both cited.
        cls.legacy_omri = OMRIProduct.objects.create(omri_id="zzz-0001", product_name="Lapsed Listing Example")
        published = _first_wsda_row()
        cls.published_wsda_id = published["wsda_id"]
        cls.legacy_wsda = WSDAMaterial.objects.create(wsda_id="WSDA-REG-LEGACY-001", brand_name=published["brand_name"])
        cls.osp.approved_omri_products.add(cls.legacy_omri)
        cls.osp.approved_wsda_materials.add(cls.legacy_wsda)

        call_command("refresh_organic_input_catalogs", skip_ecfr=True, verbosity=0, stdout=_Sink())

        # Citations made against freshly seeded rows, as an operator would after the first load.
        cls.entrust = OMRIProduct.objects.get(omri_id="dow-2900")
        cls.entrust.cdfa_oim_reg_number = "CERTIFIER-SUPPLIED-7"  # out-of-band, per the help text
        cls.entrust.save(update_fields=["cdfa_oim_reg_number"])
        cls.published_wsda = WSDAMaterial.objects.get(wsda_id=cls.published_wsda_id)
        cls.osp.approved_omri_products.add(cls.entrust)
        cls.osp.approved_wsda_materials.add(cls.published_wsda)
        cls.entry_omri = PlanMaterialEntry.objects.create(
            osp=cls.osp,
            product_name="Entrust SC, our label wording",
            listing_basis=PlanMaterialEntry.BASIS_OMRI,
            omri_product=cls.entrust,
            reason_for_use="Codling moth",
        )
        cls.entry_legacy = PlanMaterialEntry.objects.create(
            osp=cls.osp,
            product_name="Old bag, kept for the record",
            listing_basis=PlanMaterialEntry.BASIS_WSDA,
            wsda_material=cls.legacy_wsda,
        )

        cls.after_first = _snapshot()
        cls.runs_before_second = set(IngestionRun.objects.values_list("pk", flat=True))
        call_command("refresh_organic_input_catalogs", skip_ecfr=True, verbosity=0, stdout=_Sink())
        cls.after_second = _snapshot()

    # (a) duplicates ---------------------------------------------------------------------------
    def test_a_second_run_creates_no_rows(self):
        for key in ("omri_rows", "wsda_rows", "omri_cdfa_flagged", "wsda_cdfa_flagged", "omri_delisted"):
            with self.subTest(count=key):
                self.assertEqual(self.after_second[key], self.after_first[key])

    def test_the_second_run_records_zero_created(self):
        second = IngestionRun.objects.exclude(pk__in=self.runs_before_second)
        for source in ("omri", "wsda"):
            with self.subTest(source=source):
                run = second.get(source=source)
                self.assertEqual(run.status, "ok")
                self.assertEqual(run.rows_created, 0)

    def test_a_legacy_fabricated_wsda_row_is_kept_next_to_the_real_one(self):
        """The known limit, pinned so nobody mistakes the seed for a repair.

        The seed upserts by `wsda_id`, so a pre-2026-09-06 row keyed `WSDA-REG-...` is not
        matched: the real row is created beside it on the FIRST run and the pair is stable after
        that. Folding the two together is `repair_input_catalogs --apply`, which re-keys in place
        and moves both citing relations. That is why it exists separately.
        """
        same_brand = WSDAMaterial.objects.filter(brand_name=self.legacy_wsda.brand_name)
        self.assertEqual(
            set(same_brand.values_list("wsda_id", flat=True)), {"WSDA-REG-LEGACY-001", self.published_wsda_id}
        )

    # (b) deleted or re-keyed rows ------------------------------------------------------------
    def test_no_row_is_deleted_or_re_keyed(self):
        self.assertEqual(self.after_second["omri_pks"], self.after_first["omri_pks"])
        self.assertEqual(self.after_second["wsda_pks"], self.after_first["wsda_pks"])

    def test_every_osp_citation_survives_both_relations(self):
        self.assertEqual(
            set(self.osp.approved_omri_products.values_list("pk", flat=True)),
            {self.legacy_omri.pk, self.entrust.pk},
        )
        self.assertEqual(
            set(self.osp.approved_wsda_materials.values_list("pk", flat=True)),
            {self.legacy_wsda.pk, self.published_wsda.pk},
        )
        self.entry_omri.refresh_from_db()
        self.entry_legacy.refresh_from_db()
        self.assertEqual(self.entry_omri.omri_product_id, self.entrust.pk)
        self.assertEqual(self.entry_legacy.wsda_material_id, self.legacy_wsda.pk)

    def test_a_cited_row_off_the_published_list_is_marked_not_deleted(self):
        """Absent from a full OMRI edition: `delisted_on` is stamped, the row and its citation stay."""
        self.legacy_omri.refresh_from_db()
        self.assertIsNotNone(self.legacy_omri.delisted_on)
        self.assertIn(self.osp, self.legacy_omri.approving_osps.all())

    # (c) operator data -----------------------------------------------------------------------
    def test_the_operators_materials_list_wording_is_untouched(self):
        self.entry_omri.refresh_from_db()
        self.assertEqual(self.entry_omri.product_name, "Entrust SC, our label wording")
        self.assertEqual(self.entry_omri.reason_for_use, "Codling moth")
        self.assertEqual(self.entry_omri.listing_basis, PlanMaterialEntry.BASIS_OMRI)

    def test_a_certifier_supplied_cdfa_number_is_not_overwritten(self):
        self.entrust.refresh_from_db()
        self.assertEqual(self.entrust.cdfa_oim_reg_number, "CERTIFIER-SUPPLIED-7")

    # (d) fabricated identifiers --------------------------------------------------------------
    def test_no_seed_writes_a_cdfa_number(self):
        written = OMRIProduct.objects.exclude(cdfa_oim_reg_number=None).exclude(pk=self.entrust.pk)
        self.assertFalse(written.exists())
        self.assertFalse(WSDAMaterial.objects.exclude(cdfa_oim_reg_number=None).exists())


class _Sink:
    """A stdout that discards, so two 9,000-row runs do not flood the test log."""

    def write(self, *_args, **_kwargs):
        return None

    def flush(self):
        return None


class AMissingSeedFileIsRecordedAsAnError(TestCase):
    """(e) The defect the triage found, fixed in the same change.

    Each seed wrote "Seed CSV not found" to stderr and RETURNED. The orchestrator records any step
    that returns as IngestionRun(status="ok"), so a deploy that lost a data file would have printed
    "Input catalogs last synced: OMRI <today>" on the certifier packet over an empty catalogue.
    """

    def test_each_seed_raises_and_the_orchestrator_records_error(self):
        missing = "/nonexistent/seed.csv"
        with (
            mock.patch("certifications.management.commands.seed_omri_minimal._DATA_FILE", missing),
            mock.patch("certifications.management.commands.seed_wsda_materials._DATA_FILE", missing),
            mock.patch("certifications.management.commands.seed_cdfa_oim._DATA_FILE", missing),
        ):
            for command in ("seed_omri_minimal", "seed_wsda_materials", "seed_cdfa_oim"):
                with self.subTest(command=command), self.assertRaises(CommandError):
                    call_command(command, verbosity=0)
            call_command("refresh_organic_input_catalogs", skip_ecfr=True, verbosity=0, stdout=_Sink(), stderr=_Sink())

        for source in ("omri", "wsda", "cdfa_oim"):
            with self.subTest(source=source):
                self.assertEqual(IngestionRun.objects.get(source=source).status, "error")


class _Ecfr:
    """`requests.get` stand-in: the titles index, then the Subpart G text the test sets."""

    TITLES = {"titles": [{"number": 7, "latest_issue_date": "2026-09-01"}]}

    def __init__(self):
        self.text = '<DIV8 N="205.601">original 601</DIV8><DIV8 N="205.602">original 602</DIV8>'
        self.fail = False

    def get(self, url, *args, **kwargs):
        if "titles.json" in url:
            response = mock.Mock(status_code=200)
            response.json.return_value = self.TITLES
            return response
        if self.fail:
            return mock.Mock(status_code=503, text="")
        return mock.Mock(status_code=200, text=self.text)


class TheScheduledCheckIsTheEcfrStepOnly(TestCase):
    def test_it_is_dispatched_monthly_and_the_seeds_are_not(self):
        self.assertIn("check-national-list-ecfr", DISPATCHED_BY_CADENCE["monthly"])
        dispatched = {spec.get("command") for spec in PERIODIC_WORK.values()} | {
            spec.get("run") for spec in PERIODIC_WORK.values()
        }
        for seed in ("refresh_organic_input_catalogs", "seed_omri_minimal", "seed_wsda_materials", "seed_cdfa_oim"):
            with self.subTest(seed=seed):
                self.assertNotIn(seed, dispatched)

    def test_the_monthly_dry_run_lists_it(self):
        from io import StringIO

        out = StringIO()
        call_command("run_due_maintenance", cadence="monthly", dry_run=True, stdout=out)
        self.assertIn("check-national-list-ecfr", out.getvalue())


class ADriftStaysVisibleUntilReviewed(TestCase):
    def setUp(self):
        self.ecfr = _Ecfr()
        patcher = mock.patch("requests.get", side_effect=self.ecfr.get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _latest(self):
        return IngestionRun.objects.filter(source="national_list_ecfr").order_by("-ran_at", "-pk").first()

    def test_the_first_snapshot_is_a_baseline_not_a_change(self):
        check_national_list_ecfr()
        self.assertEqual(self._latest().status, "unchanged")
        self.assertEqual(NationalListRevision.objects.count(), 2)

    def test_a_change_fails_the_job_and_is_recorded(self):
        check_national_list_ecfr()
        self.ecfr.text = self.ecfr.text.replace("original 601", "amended 601")

        with self.assertRaises(CommandError) as ctx:
            check_national_list_ecfr()

        self.assertIn("205.601", str(ctx.exception))
        self.assertNotIn("205.602", str(ctx.exception))
        run = self._latest()
        self.assertEqual(run.status, "changed")
        self.assertIn("seed_national_list", run.message)

    def test_the_change_is_still_reported_the_month_after(self):
        """The defect in the previous-fetch comparison: it lasted one run."""
        check_national_list_ecfr()
        self.ecfr.text = self.ecfr.text.replace("original 601", "amended 601")
        with self.assertRaises(CommandError):
            check_national_list_ecfr()

        with self.assertRaises(CommandError):
            check_national_list_ecfr()  # same amended text: the fetch alone would say unchanged

        self.assertEqual(self._latest().status, "changed")

    def test_re_seeding_the_committed_list_clears_it(self):
        check_national_list_ecfr()
        self.ecfr.text = self.ecfr.text.replace("original 601", "amended 601")
        with self.assertRaises(CommandError):
            check_national_list_ecfr()

        call_command("seed_national_list", verbosity=0, stdout=_Sink())
        self.assertEqual(unreviewed_changes(), {})
        check_national_list_ecfr()
        self.assertEqual(self._latest().status, "unchanged")

    def test_a_failed_fetch_is_recorded_and_raised(self):
        self.ecfr.fail = True
        with self.assertRaises(CommandError):
            check_national_list_ecfr()
        self.assertEqual(self._latest().status, "error")

    def test_the_monthly_job_reports_the_failure(self):
        check_national_list_ecfr()
        self.ecfr.text = self.ecfr.text.replace("original 602", "amended 602")
        with self.assertRaises(CommandError) as ctx:
            call_command("run_due_maintenance", cadence="monthly", stdout=_Sink(), stderr=_Sink())
        self.assertIn("check-national-list-ecfr", str(ctx.exception))

    def test_the_hand_run_orchestrator_records_the_same_status_and_exits_cleanly(self):
        check_national_list_ecfr()
        self.ecfr.text = self.ecfr.text.replace("original 601", "amended 601")
        # Seeds patched out: they are covered above, and only step 4 is under test here.
        with mock.patch("certifications.management.commands.refresh_organic_input_catalogs.call_command"):
            call_command("refresh_organic_input_catalogs", verbosity=0, stdout=_Sink())
        self.assertEqual(self._latest().status, "changed")


class ThePacketDoesNotPrintAnUnreviewedListAsSynced(TestCase):
    def setUp(self):
        from django.utils import timezone

        from history.models import History
        from history.services.audit_export_service import AuditExportService
        from product.models import Parcel, Product
        from users.models import User

        company = Company.objects.create(name="Packet Farm")
        establishment = Establishment.objects.create(name="Home", company=company, state="WA")
        parcel = Parcel.objects.create(name="P", establishment=establishment, area=1.0)
        history = History.objects.create(
            name="2026 Pears",
            start_date=timezone.now(),
            product=Product.objects.create(name="Pears"),
            parcel=parcel,
            operator=User.objects.create_user(email="packet@test.com", password="x"),
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        self.svc = AuditExportService(history, "organic")

    def test_a_changed_check_is_named_not_dated_as_synced(self):
        IngestionRun.objects.create(source="national_list_ecfr", status="unchanged")
        changed = IngestionRun.objects.create(source="national_list_ecfr", status="changed", message="x")

        line = self.svc._catalog_freshness_line()

        self.assertNotIn("National List (eCFR) " + changed.ran_at.date().isoformat() + ".", line)
        self.assertNotIn("National List (eCFR) " + changed.ran_at.date().isoformat() + ",", line)
        self.assertIn("Not confirmed current", line)
        self.assertIn("has changed since Trazo's National List was last reviewed against it", line)

    def test_an_unchanged_check_still_prints_its_date(self):
        run = IngestionRun.objects.create(source="national_list_ecfr", status="unchanged")
        line = self.svc._catalog_freshness_line()
        self.assertIn(f"National List (eCFR) {run.ran_at.date().isoformat()}", line)
