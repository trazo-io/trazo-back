"""
NOP 7 CFR 205.202 — Transition status service tests (Sprint 2.2).
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel, ParcelCropHistory, Product
from product.services.transition_status_service import TRANSITION_MONTHS, compute_transition_status
from users.models import User


class TransitionStatusServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="t@test.com", password="x")
        self.company = Company.objects.create(name="Transition Farm")
        self.establishment = Establishment.objects.create(name="Field T", company=self.company)
        self.parcel = Parcel.objects.create(name="P-T", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Tomato")

    def _new_history(self):
        return Production.objects.create(
            name="H",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_no_evidence_returns_eligible_with_note(self):
        status = compute_transition_status(self.parcel)
        self.assertTrue(status.is_eligible)
        self.assertEqual(status.findings, [])
        self.assertIn("affidavits", status.note)
        self.assertEqual(status.to_dict()["note_code"], "none_recorded")

    def test_old_prohibited_substance_eligible(self):
        old = date.today() - relativedelta(months=TRANSITION_MONTHS) - timedelta(days=30)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=old.year,
            crop_grown="Wheat",
            production_method="conventional",
            substances_applied="Glyphosate",
            date_last_prohibited=old,
        )
        status = compute_transition_status(self.parcel)
        self.assertTrue(status.is_eligible)
        self.assertEqual(status.last_prohibited_date, old)
        self.assertEqual(status.to_dict()["note_code"], "elapsed")

    def test_recent_prohibited_substance_not_eligible(self):
        recent = date.today() - timedelta(days=400)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=recent.year,
            crop_grown="Corn",
            production_method="conventional",
            substances_applied="Atrazine",
            date_last_prohibited=recent,
        )
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertEqual(status.last_prohibited_date, recent)
        self.assertEqual(
            status.transition_complete_date,
            recent + relativedelta(months=TRANSITION_MONTHS),
        )
        self.assertGreater(status.days_remaining, 0)
        # The screen words the note in the reader's language from this code (VID-06/VID-07).
        self.assertEqual(status.to_dict()["note_code"], "in_transition")

    def test_chemical_event_classified_organic_does_not_trigger(self):
        history = self._new_history()
        ChemicalEvent.objects.create(
            history=history,
            created_by=self.user,
            description="OMRI-listed fungicide",
            date=timezone.now() - timedelta(days=100),
            chemical_subtype="copper_fungicide",
            commercial_name="Champ",
            organic_approved="omri_listed",
        )
        status = compute_transition_status(self.parcel)
        self.assertTrue(status.is_eligible)
        self.assertEqual(status.findings, [])

    def test_chemical_event_synthetic_resets_clock(self):
        history = self._new_history()
        applied = timezone.now() - timedelta(days=200)
        ChemicalEvent.objects.create(
            history=history,
            created_by=self.user,
            description="Synthetic herbicide",
            date=applied,
            chemical_subtype="synthetic_herbicide",
            commercial_name="RoundUp",
            organic_approved="not_organic",
        )
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertEqual(status.last_prohibited_date, applied.date())
        self.assertEqual(len(status.findings), 1)
        self.assertEqual(status.findings[0].source, "ChemicalEvent")

    def test_uses_most_recent_prohibited_when_multiple(self):
        old = date.today() - relativedelta(months=TRANSITION_MONTHS) - timedelta(days=100)
        recent = date.today() - timedelta(days=600)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=old.year,
            crop_grown="Wheat",
            production_method="conventional",
            substances_applied="Glyphosate",
            date_last_prohibited=old,
        )
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=recent.year,
            crop_grown="Corn",
            production_method="conventional",
            substances_applied="Atrazine",
            date_last_prohibited=recent,
        )
        status = compute_transition_status(self.parcel)
        self.assertEqual(status.last_prohibited_date, recent)
        self.assertEqual(len(status.findings), 2)


class ApprovedInputMustNotResetTheClockTests(TestCase):
    """7 CFR 205.202(b) — only a PROHIBITED substance restarts the 36-month clock.

    Found 2026-08-04 reading a real audit dossier as a certifier. The parcel's
    "Last Prohibited Substance Date" was dated to an application of Kocide 3000,
    an OMRI-listed copper hydroxide fungicide the farmer had recorded as organic.
    The service's allow-list held only three of the five values that mean
    "organic approved", so an approved input fell through to the prohibited
    branch and declared certified land in transition until 2028 — on the document
    that goes to the certifying agent.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="clock@test.com", password="x")
        self.company = Company.objects.create(name="Clock Farm")
        self.establishment = Establishment.objects.create(name="Field C", company=self.company)
        self.parcel = Parcel.objects.create(name="P-C", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = Production.objects.create(
            name="H",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _chem(self, organic_approved, days_ago=10, name="Kocide 3000 (copper hydroxide)"):
        return ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now() - timedelta(days=days_ago),
            commercial_name=name,
            organic_approved=organic_approved,
        )

    def test_every_approved_value_leaves_the_clock_untouched(self):
        # "yes" and "organic" are the two that used to fall through: "yes" is the
        # legacy enum label still selectable in the form, "organic" is a value
        # the production database actually holds.
        for value in ("omri_listed", "usda_nop_approved", "organic_equivalent", "yes", "organic"):
            with self.subTest(organic_approved=value):
                ChemicalEvent.objects.all().delete()
                self._chem(value)
                status = compute_transition_status(self.parcel)
                self.assertTrue(status.is_eligible, f"{value!r} wrongly reset the transition clock")
                self.assertIsNone(status.last_prohibited_date)
                self.assertEqual(status.findings, [])

    def test_prohibited_values_still_reset_the_clock(self):
        for value in ("not_organic", "no", "transitional"):
            with self.subTest(organic_approved=value):
                ChemicalEvent.objects.all().delete()
                self._chem(value, name="Roundup PowerMax 3 (glyphosate)")
                status = compute_transition_status(self.parcel)
                self.assertFalse(status.is_eligible, f"{value!r} failed to reset the clock")
                self.assertIsNotNone(status.last_prohibited_date)

    def test_approved_input_does_not_become_the_last_prohibited_date(self):
        """The exact dossier defect: a prohibited input months earlier, an
        approved one later. The clock must date to the prohibited one."""
        self._chem("not_organic", days_ago=90, name="Phosphojet (potassium phosphite)")
        self._chem("organic", days_ago=10, name="Kocide 3000 (copper hydroxide)")
        status = compute_transition_status(self.parcel)
        expected = (timezone.now() - timedelta(days=90)).date()
        self.assertEqual(status.last_prohibited_date, expected)
        self.assertEqual(status.transition_complete_date, expected + relativedelta(months=TRANSITION_MONTHS))

    def test_unclassified_status_is_reported_but_does_not_date_the_clock(self):
        """Blank is "nobody answered", not "a prohibited substance was applied".
        It must not carry a three-year consequence — but it must not read clean
        either, so it blocks eligibility and says why."""
        for blank in ("", None):
            with self.subTest(organic_approved=blank):
                ChemicalEvent.objects.all().delete()
                self._chem(blank, name="Fish Emulsion 5-1-1")
                status = compute_transition_status(self.parcel)
                self.assertIsNone(status.last_prohibited_date)
                self.assertEqual(status.findings, [])
                self.assertEqual(len(status.unclassified), 1)
                self.assertFalse(status.is_eligible)
                self.assertIn("no organic status recorded", status.note)

    def test_allow_list_covers_every_non_prohibited_enum_choice(self):
        """Guard against the enum growing a value neither list knows about —
        that is precisely how this defect arose."""
        from common.field_registry import (
            ORGANIC_APPROVED,
            ORGANIC_APPROVED_OK_VALUES,
            ORGANIC_PROHIBITED_VALUES,
            ORGANIC_UNRESOLVED_VALUES,
        )

        known = ORGANIC_APPROVED_OK_VALUES | ORGANIC_PROHIBITED_VALUES | ORGANIC_UNRESOLVED_VALUES | {"not_applicable"}
        unaccounted = {value for value, _label in ORGANIC_APPROVED} - known
        self.assertEqual(
            unaccounted,
            set(),
            f"organic_approved choices {unaccounted} are classified by neither list; "
            "add them to field_registry, not to a caller",
        )

    def test_the_two_shared_allow_lists_are_the_same_object(self):
        """claim_resolver and the transition clock disagreed on "yes" for months."""
        from common.field_registry import ORGANIC_APPROVED_OK_VALUES
        from history.services.claim_resolver import ORGANIC_APPROVED_VALUES
        from product.services.transition_status_service import ORGANIC_OK_VALUES

        self.assertIs(ORGANIC_APPROVED_VALUES, ORGANIC_APPROVED_OK_VALUES)
        self.assertIs(ORGANIC_OK_VALUES, ORGANIC_APPROVED_OK_VALUES)


class UnclassifiedApplicationsAreNamedTests(TestCase):
    """An unclassified application must be named, not counted.

    The note used to read "2 chemical application(s) ... have no organic status recorded
    (most recent 2026-06-24)". A grower cannot act on that and an inspector cannot check it:
    neither knows which two records to open. Same rule the packet applies to every other
    value — a compliance document names the thing it is asking about.
    """

    def setUp(self):
        from datetime import timedelta

        from carbon.models import CropType
        from company.models import Company, Establishment
        from history.models import ChemicalEvent, Production
        from product.models import Parcel, Product

        company = Company.objects.create(name="Named Co")
        est = Establishment.objects.create(name="Named Farm", company=company)
        self.parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnut",
            slug="walnut-named",
            category="tree_nut",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnut")
        history = Production.objects.create(
            parcel=self.parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=300),
        )
        for name, days in (("Entrust SC", 40), ("Serenade ASO", 200)):
            ChemicalEvent.objects.create(
                history=history,
                type="FU",
                date=timezone.now() - timedelta(days=days),
                commercial_name=name,
                organic_approved="",
            )

    def test_each_unclassified_product_is_named_with_its_date(self):
        status = compute_transition_status(self.parcel)
        self.assertIn("Entrust SC", status.note)
        self.assertIn("Serenade ASO", status.note)
        self.assertIn("no organic status recorded", status.note)
