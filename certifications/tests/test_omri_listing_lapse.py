"""An OMRI listing is read as of the application date (overall review 2026-11, OV-MT-C04).

`OMRIProduct.delisted_on` is the edition date of the first OMRI list Trazo loaded that no longer
carried the product. The plan's materials list and the buyer-page claim check read it; the lookup,
the drift detector and the audit dossier's input table did not, so a spray applied after OMRI dropped
the product read everywhere else as an ordinary OMRI-listed, plan-approved input.

Pinned here:
  * one helper decides, as of the application day: a record from before the drop is untouched;
  * the drift detector adds an "omri_listing_lapsed" issue to an approved product applied on or
    after the drop, on the FK path, the rescue path and the name path, unless a WSDA approval still
    covers the record or the approval rests on a National List substance;
  * the lookup returns the drop date; the dossier prints it beside the OMRI ID with a [REVIEW] note;
  * nothing says the material is prohibited.
"""

import datetime

from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, WSDAMaterial
from certifications.services.listing_lapse import omri_listing_lapsed_by, omri_listing_lapsed_on
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel
from users.models import User

DROPPED = datetime.date(2026, 9, 26)


def _at(day):
    return timezone.make_aware(datetime.datetime(day.year, day.month, day.day, 9, 0))


class TheRuleTests(SimpleTestCase):
    class _P:
        def __init__(self, delisted_on):
            self.delisted_on = delisted_on

    def test_lapsed_on_and_after_the_drop_never_before(self):
        product = self._P(DROPPED)
        self.assertIsNone(omri_listing_lapsed_by(product, _at(DROPPED - datetime.timedelta(days=1))))
        self.assertEqual(omri_listing_lapsed_by(product, _at(DROPPED)), DROPPED)
        self.assertEqual(omri_listing_lapsed_by(product, DROPPED + datetime.timedelta(days=40)), DROPPED)

    def test_a_listed_product_or_no_date_is_never_lapsed_by_a_record(self):
        self.assertIsNone(omri_listing_lapsed_by(self._P(None), _at(DROPPED)))
        self.assertIsNone(omri_listing_lapsed_by(self._P(DROPPED), None))
        self.assertIsNone(omri_listing_lapsed_by(None, _at(DROPPED)))
        self.assertEqual(omri_listing_lapsed_on(self._P(DROPPED)), DROPPED)


class _Orchard(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name="Lapse Orchard")
        self.establishment = Establishment.objects.create(name="Main", company=company, state="WA")
        parcel = Parcel.objects.create(name="B1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(name="Apples", start_date=timezone.now(), parcel=parcel)
        self.dropped = OMRIProduct.objects.create(
            omri_id="tst-1001", product_name="Dropped Fish 2-4-1", delisted_on=DROPPED
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=1, status="active", effective_date=timezone.now().date()
        )
        self.osp.approved_omri_products.add(self.dropped)

    def _spray(self, day, **kwargs):
        kwargs.setdefault("commercial_name", "Dropped Fish 2-4-1")
        ev = ChemicalEvent.objects.create(history=self.history, date=_at(day), description="spray", **kwargs)
        ev.refresh_from_db()
        return ev


class DriftTests(_Orchard):
    def test_an_application_after_the_drop_carries_the_lapse_issue(self):
        ev = self._spray(DROPPED + datetime.timedelta(days=5), omri_product=self.dropped)
        dw = ev.drift_warning
        self.assertIsNotNone(dw)
        self.assertEqual(dw["reason_code"], "approved_with_issues")
        self.assertIn("omri_listing_lapsed", dw["reason_params"]["issues"])
        self.assertEqual(dw["reason_params"]["omriDelistedOn"], "2026-09-26")
        self.assertEqual(dw["reason_params"]["appliedOn"], "2026-10-01")
        self.assertIn("stopped carrying this product as of 2026-09-26", dw["reason"])
        self.assertNotIn("prohibited.", dw["reason"].lower().replace("not make the material prohibited", ""))

    def test_an_application_before_the_drop_is_untouched(self):
        ev = self._spray(DROPPED - datetime.timedelta(days=10), omri_product=self.dropped)
        self.assertIsNone(ev.drift_warning)

    def test_the_name_path_reads_it_too(self):
        ev = self._spray(DROPPED + datetime.timedelta(days=1))
        self.assertIsNone(ev.omri_product_id)
        self.assertIn("omri_listing_lapsed", ev.drift_warning["reason_params"]["issues"])

    def test_a_wsda_approval_that_still_covers_the_record_clears_it(self):
        wsda = WSDAMaterial.objects.create(wsda_id="9001", brand_name="Dropped Fish 2-4-1")
        self.osp.approved_wsda_materials.add(wsda)
        ev = self._spray(DROPPED + datetime.timedelta(days=5), omri_product=self.dropped, wsda_material=wsda)
        self.assertIsNone(ev.drift_warning)

    def test_an_approval_resting_on_a_plan_substance_does_not_read_the_listing(self):
        """The record's OMRI listing is not on the plan; the plan lists the substance the record is
        confirmed as. That approval never rested on OMRI, so OMRI's drop is not a gap."""
        self.osp.approved_omri_products.clear()
        fish = NationalListSubstance.objects.create(
            substance_name="Fish emulsion test",
            substance_name_normalized="fish emulsion test",
            cfr_section="205.601",
            subsection="j",
            status="allowed",
        )
        self.osp.approved_national_list_substances.add(fish)
        ev = self._spray(
            DROPPED + datetime.timedelta(days=5),
            omri_product=self.dropped,
            extra_data={"active_ingredient": "Fish emulsion test"},
        )
        self.assertEqual(ev.national_list_substance_id, fish.id)
        self.assertIsNone(ev.drift_warning)

    def test_an_operator_identity_decision_reads_it_too(self):
        """Review of back #472: a name that matches no catalog row, declared by the operator to be the
        plan's OMRI product, reached the approved check without the product."""
        from certifications.models import MaterialIdentityDecision as MID
        from certifications.services.material_identity import record_decision
        from users.models import WorksIn

        user = User.objects.create_user(email="ident@test.com", password="x", is_verified=True, first_name="Ana")
        WorksIn.objects.create(user=user, company=self.establishment.company, role=WorksIn.COMPANY_ADMIN)
        ev = self._spray(DROPPED + datetime.timedelta(days=3), commercial_name="Grandpa fish mix")
        self.assertEqual(ev.drift_warning["reason_code"], "unresolved")
        record_decision(
            self.osp,
            user,
            {
                "source": "chemical",
                "logged_name": "Grandpa fish mix",
                "decision": MID.SAME_AS,
                "target_kind": MID.TARGET_OMRI,
                "target_id": self.dropped.pk,
                "event_ids": [ev.pk],
                "formulation_difference_acknowledged": True,
                "formulation_note": "Same product, bought in bulk under a farm name.",
            },
        )
        ev.save()
        ev.refresh_from_db()
        self.assertEqual(ev.drift_warning["reason_code"], "approved_with_issues")
        self.assertIn("omri_listing_lapsed", ev.drift_warning["reason_params"]["issues"])


class LookupTests(_Orchard):
    def test_the_lookup_returns_the_drop_date(self):
        user = User.objects.create_user(email="lapse@test.com", password="x")
        client = APIClient()
        client.force_authenticate(user)
        body = client.get(reverse("verify_input"), {"name": "tst-1001"}).json()
        self.assertEqual(body["omri_product_pk"], self.dropped.pk)
        self.assertEqual(body["omri_product_delisted_on"], "2026-09-26")
        self.assertEqual(body["omri_candidates"][0]["delisted_on"], "2026-09-26")


class DossierTests(_Orchard):
    def _table_text(self):
        from history.services.audit_export_service import AuditExportService
        from history.tests.test_pdf_field_coverage import flowable_text

        return flowable_text(AuditExportService(self.history, certification_type="organic")._build_chemical_log())

    def test_the_input_table_prints_the_lapse_beside_the_omri_id(self):
        self._spray(DROPPED + datetime.timedelta(days=5), omri_product=self.dropped)
        txt = self._table_text()
        self.assertIn("tst-1001 (OMRI listing lapsed 2026-09-26, on or before this application)", txt)
        self.assertIn("[REVIEW] OMRI listing lapsed:", txt)
        self.assertIn("1 input(s) were applied on or after", txt)

    def test_a_record_from_before_the_drop_prints_as_it_always_did(self):
        self._spray(DROPPED - datetime.timedelta(days=5), omri_product=self.dropped)
        txt = self._table_text()
        self.assertNotIn("listing lapsed", txt)
        self.assertIn("tst-1001", txt)
