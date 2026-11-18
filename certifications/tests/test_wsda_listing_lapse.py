"""A product WSDA drops in a later edition is registered and read as lapsed (OV-MT-C04, WSDA half).

OMRI rows carried `delisted_on` from the start; WSDA rows had nothing, so a product WSDA removed from
a later edition kept reading as WSDA-listed on the plan, the record, the dossier and the buyer page.
Migration 0087 adds `WSDAMaterial.delisted_on`, and `seed_wsda_materials` sets it from absence, with
the guards `seed_omri_minimal` uses.

Pinned here:
  * the seeder marks a product the new edition no longer carries, clears one that returns, never
    touches a hand-entered row, and refuses a partial file or an implausible drop;
  * the buyer-page claim stops saying "WSDA Listed" for a dropped product;
  * the plan list, the C11 review cell and the entry's review position stop treating it as WSDA's;
  * the drift detector adds "wsda_listing_lapsed" as of the application date, unless a current OMRI
    approval covers the record;
  * the lookup, the approved-inputs inline and the dossier carry the date.
"""

import csv
import datetime
import os
import tempfile
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import OMRIProduct, OrganicSystemPlan, PlanMaterialEntry, WSDAMaterial
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel
from users.models import User

OLD = datetime.date(2026, 3, 6)
NEW = datetime.date(2026, 10, 2)
SEEDER = "certifications.management.commands.seed_wsda_materials._DATA_FILE"


def _at(day):
    return timezone.make_aware(datetime.datetime(day.year, day.month, day.day, 9, 0))


class SeederTests(TestCase):
    def _csv(self, ids, edition=NEW):
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
        writer = csv.writer(fh)
        writer.writerow(["wsda_id", "brand_name", "list_effective_date"])
        for i in ids:
            writer.writerow([str(i), f"Product {i}", edition.isoformat()])
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def _seed(self, path, **kwargs):
        out = StringIO()
        with mock.patch(SEEDER, path):
            call_command("seed_wsda_materials", stdout=out, stderr=StringIO(), **kwargs)
        return out.getvalue()

    def setUp(self):
        for i in range(1, 601):
            WSDAMaterial.objects.create(wsda_id=str(i), brand_name=f"Product {i}", list_effective_date=OLD)
        self.hand = WSDAMaterial.objects.create(wsda_id="9999", brand_name="Typed by hand")

    def test_a_product_the_new_edition_no_longer_carries_is_marked_with_that_edition(self):
        out = self._seed(self._csv(range(1, 600)))  # 600 is gone
        self.assertEqual(WSDAMaterial.objects.get(wsda_id="600").delisted_on, NEW)
        self.assertIsNone(WSDAMaterial.objects.get(wsda_id="1").delisted_on)
        self.assertIsNone(
            WSDAMaterial.objects.get(wsda_id="9999").delisted_on, "a hand-entered row was never on a list"
        )
        self.assertIn("1 product(s) are no longer on the WSDA list as of 2026-10-02", out)

    def test_a_product_that_returns_is_cleared(self):
        WSDAMaterial.objects.filter(wsda_id="5").update(delisted_on=datetime.date(2026, 6, 1))
        self._seed(self._csv(range(1, 601)))
        self.assertIsNone(WSDAMaterial.objects.get(wsda_id="5").delisted_on)

    def test_a_partial_file_marks_nothing(self):
        out = self._seed(self._csv(range(1, 11)))
        self.assertFalse(WSDAMaterial.objects.filter(delisted_on__isnull=False).exists())
        self.assertIn("Skipping delisting reconciliation", out)

    def test_an_implausible_drop_is_refused_unless_forced(self):
        path = self._csv(range(1, 501))  # 100 of 601 gone, over the 15% ceiling of 90
        out = self._seed(path)
        self.assertIn("REFUSED", out)
        self.assertFalse(WSDAMaterial.objects.filter(delisted_on__isnull=False).exists())
        self._seed(path, force_delist=True)
        self.assertEqual(WSDAMaterial.objects.filter(delisted_on=NEW).count(), 100)

    def test_the_seed_never_deletes_a_row(self):
        self._seed(self._csv(range(1, 600)))
        self.assertTrue(WSDAMaterial.objects.filter(wsda_id="600").exists())


class _Orchard(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name="WSDA Lapse Orchard")
        self.establishment = Establishment.objects.create(name="Main", company=company, state="WA")
        parcel = Parcel.objects.create(name="B1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(name="Pears", start_date=timezone.now(), parcel=parcel)
        self.dropped = WSDAMaterial.objects.create(
            wsda_id="3001", brand_name="Dropped Kelp 0-0-1", list_effective_date=OLD, delisted_on=NEW
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=1, status="active", effective_date=timezone.now().date()
        )
        self.osp.approved_wsda_materials.add(self.dropped)

    def _spray(self, day, **kwargs):
        kwargs.setdefault("commercial_name", "Dropped Kelp 0-0-1")
        ev = ChemicalEvent.objects.create(history=self.history, date=_at(day), description="kelp", **kwargs)
        ev.refresh_from_db()
        return ev


class ClaimTests(_Orchard):
    def test_the_buyer_page_stops_saying_wsda_listed(self):
        from history.services.claim_authority import LABEL_INPUT_WSDA_LISTED, may_claim_input_listing

        ev = self._spray(NEW + datetime.timedelta(days=3), wsda_material=self.dropped)
        self.assertNotEqual(may_claim_input_listing(ev).safe_label, LABEL_INPUT_WSDA_LISTED)
        WSDAMaterial.objects.filter(pk=self.dropped.pk).update(delisted_on=None)
        ev = ChemicalEvent.objects.get(pk=ev.pk)
        self.assertEqual(may_claim_input_listing(ev).safe_label, LABEL_INPUT_WSDA_LISTED)


class PlanListTests(_Orchard):
    def test_the_plan_row_says_wsda_no_longer_lists_it(self):
        from certifications.services.plan_materials import c11_review_cell, plan_materials

        row = next(r for r in plan_materials(self.osp) if r.source == "WSDA")
        self.assertEqual(row.delisted_on, "2026-10-02")
        self.assertIn("[REVIEW] no longer on the WSDA list as of 2026-10-02", " ".join(row.review_notes()))
        self.assertEqual(row.review_position, "other")
        self.assertIn("WSDA listing lapsed as of 2026-10-02", c11_review_cell(row))

    def test_a_dropped_listing_is_never_folded_into_the_operators_row(self):
        from certifications.services.plan_materials import plan_materials

        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Dropped Kelp 0-0-1",
            wsda_material=self.dropped,
            listing_basis=PlanMaterialEntry.BASIS_WSDA,
        )
        rows = [r for r in plan_materials(self.osp) if r.name == "Dropped Kelp 0-0-1"]
        self.assertTrue(any(r.source == "WSDA" and r.delisted_on for r in rows), [r.source for r in rows])

    def test_the_entry_may_name_another_agency_once_wsda_dropped_it(self):
        entry = PlanMaterialEntry.objects.create(
            osp=self.osp, product_name="Kelp", wsda_material=self.dropped, listing_basis=PlanMaterialEntry.BASIS_WSDA
        )
        self.assertEqual(entry.listing_review_position, "other")

    def test_the_approved_inputs_inline_carries_the_date(self):
        from certifications.serializers import _ApprovedWSDAInline

        self.assertEqual(str(_ApprovedWSDAInline(self.dropped).data["delisted_on"]), "2026-10-02")


class DriftTests(_Orchard):
    def test_an_application_after_the_drop_carries_the_issue(self):
        ev = self._spray(NEW + datetime.timedelta(days=4), wsda_material=self.dropped)
        dw = ev.drift_warning
        self.assertEqual(dw["reason_code"], "approved_with_issues")
        self.assertIn("wsda_listing_lapsed", dw["reason_params"]["issues"])
        self.assertEqual(dw["reason_params"]["wsdaDelistedOn"], "2026-10-02")
        self.assertEqual(dw["reason_params"]["appliedOn"], "2026-10-06")
        self.assertIn("WSDA's published list stopped carrying this product as of 2026-10-02", dw["reason"])

    def test_an_application_before_the_drop_is_untouched(self):
        ev = self._spray(NEW - datetime.timedelta(days=30), wsda_material=self.dropped)
        self.assertIsNone(ev.drift_warning)

    def test_the_name_path_reads_it_too(self):
        ev = self._spray(NEW + datetime.timedelta(days=1))
        self.assertIn("wsda_listing_lapsed", ev.drift_warning["reason_params"]["issues"])

    def test_a_current_omri_approval_covers_the_record(self):
        omri = OMRIProduct.objects.create(omri_id="kel-1", product_name="Dropped Kelp 0-0-1")
        self.osp.approved_omri_products.add(omri)
        ev = self._spray(NEW + datetime.timedelta(days=4), wsda_material=self.dropped, omri_product=omri)
        self.assertIsNone(ev.drift_warning)

    def test_a_lapsed_wsda_listing_no_longer_covers_a_lapsed_omri_one(self):
        """Before this slice, any approved WSDA listing cleared an OMRI lapse, dropped or not."""
        omri = OMRIProduct.objects.create(
            omri_id="kel-2", product_name="Other Kelp", delisted_on=datetime.date(2026, 9, 26)
        )
        self.osp.approved_omri_products.add(omri)
        ev = self._spray(
            NEW + datetime.timedelta(days=4),
            commercial_name="Other Kelp",
            omri_product=omri,
            wsda_material=self.dropped,
        )
        self.assertIn("omri_listing_lapsed", ev.drift_warning["reason_params"]["issues"])


class LookupAndDossierTests(_Orchard):
    def test_the_lookup_returns_the_drop_date(self):
        user = User.objects.create_user(email="wlapse@test.com", password="x")
        client = APIClient()
        client.force_authenticate(user)
        body = client.get(reverse("verify_input"), {"name": "Dropped Kelp 0-0-1"}).json()
        self.assertEqual(body["wsda_material_pk"], self.dropped.pk)
        self.assertEqual(body["wsda_material_delisted_on"], "2026-10-02")
        self.assertEqual(body["wsda_candidates"][0]["delisted_on"], "2026-10-02")

    def test_the_dossier_states_it_beside_the_status(self):
        from history.services.audit_export_service import AuditExportService
        from history.tests.test_pdf_field_coverage import flowable_text

        self._spray(NEW + datetime.timedelta(days=4), wsda_material=self.dropped)
        txt = flowable_text(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertIn("Farmer-reported WSDA (WSDA listing lapsed 2026-10-02, on or before this application)", txt)
        self.assertIn("[REVIEW] OMRI or WSDA listing lapsed:", txt)
