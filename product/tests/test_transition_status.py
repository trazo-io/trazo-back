"""
NOP 7 CFR 205.202 — Transition status service tests (Sprint 2.2).
"""

import uuid
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from dateutil.relativedelta import relativedelta
from rest_framework.test import APITestCase

from common.field_registry import (
    ORGANIC_APPROVED,
    ORGANIC_APPROVED_OFFERED,
    ORGANIC_APPROVED_OK_VALUES,
    ORGANIC_APPROVED_REFUSED_ON_WRITE,
    ORGANIC_PROHIBITED_VALUES,
)
from company.models import Company, Establishment
from history.constants import CHEMICAL_EVENT_TYPE, SOIL_MANAGEMENT_EVENT_TYPE
from history.models import ChemicalEvent, Production, SoilManagementEvent
from history.services.organic_basis import TRANSITIONAL_BASIS_REFUSED
from product.models import Parcel, ParcelCropHistory, Product
from product.services.transition_status_service import TRANSITION_MONTHS, compute_transition_status
from users.models import User, WorksIn


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

    def _unclassified_spray(self):
        ChemicalEvent.objects.create(
            history=self._new_history(),
            created_by=self.user,
            description="Spray with no basis recorded",
            date=timezone.now() - timedelta(days=60),
            chemical_subtype="copper_fungicide",
            commercial_name="Unnamed copper",
            organic_approved="",
        )

    def test_unclassified_inputs_and_no_prohibited_record_is_none_recorded(self):
        """Review of back #498: the app words the note from the code. No prohibited record with
        unclassified inputs in the window is "none_recorded" (the note says so, then names them),
        while `is_eligible` is False."""
        self._unclassified_spray()
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertTrue(status.unclassified)
        self.assertEqual(status.to_dict()["note_code"], "none_recorded")

    def test_an_elapsed_clock_with_unclassified_inputs_is_elapsed(self):
        old = date.today() - relativedelta(months=TRANSITION_MONTHS) - timedelta(days=30)
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=old.year,
            crop_grown="Wheat",
            production_method="conventional",
            substances_applied="Glyphosate",
            date_last_prohibited=old,
        )
        self._unclassified_spray()
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertEqual(status.to_dict()["note_code"], "elapsed")

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


class TransitionalIsNeverGivenAsAnInputBasisTests(APITestCase):
    """M7-I1 (overall review 2026-11-24): "Transitional - In certification process" was offered as the
    organic basis of an input on the spray form, the soil amendment form, a tank's lines and quick add.
    It names the OPERATION's status, so a grower on a transitional farm picked it in good faith, and
    its stored value is a prohibited-substance answer: one pick on a fish fertilizer record moved a
    certified parcel to "In transition, 964 days remaining".

    Pinned here: the value is refused on create (spray, soil amendment, a tank line) and on an edit or
    a correction that changes the value to it, with a coded refusal that says what to pick instead; a
    record already holding it still saves when an edit leaves it as it is, and still counts as a
    prohibited answer (its classification is not this fix's to change).
    """

    def setUp(self):
        self.user = User.objects.create_user(email="m7-i1@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Certified Bench LLC")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Certified Bench", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Block 1", establishment=self.est, area=4.0)
        self.season = Production.objects.create(
            name="Apples 2026",
            start_date=timezone.now() - timedelta(days=120),
            product=Product.objects.create(name="Apples"),
            parcel=self.parcel,
            operator=self.user,
            published=False,
        )
        # Certified ground: the last prohibited application is 40 months back, so the clock has run.
        self.last = date.today() - timedelta(days=40 * 30)
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=self.last.year, crop_grown="Apples", date_last_prohibited=self.last
        )
        self.client.force_authenticate(user=self.user)

    def _post(self, event_type, **fields):
        payload = {
            "event_type": event_type,
            "history": self.season.id,
            "parcels": [self.parcel.id],
            "date": (timezone.now() - timedelta(days=5)).isoformat(),
        }
        payload.update(fields)
        return self.client.post("/api/events/", payload, format="json")

    def _patch(self, record, event_type, **fields):
        url = f"{reverse('events-detail', args=[record.pk])}?event_type={event_type}"
        return self.client.patch(url, fields, format="json")

    def _stored_spray(self, organic_approved):
        return ChemicalEvent.objects.create(
            history=self.season,
            date=timezone.now() - timedelta(days=10),
            description="fish fertilizer",
            commercial_name="Fish emulsion 5-1-1",
            type="FE",
            organic_approved=organic_approved,
            created_by=self.user,
        )

    def _assert_coded_refusal(self, body, field):
        self.assertIn(field, body)
        sentence = " ".join(str(m) for m in body[field])
        self.assertIn('"Transitional" describes a farm in conversion, not this input', sentence)
        # It says what to pick instead, in the words the forms show.
        self.assertIn('"No organic basis: conventional use only"', sentence)
        self.assertIn('"Not yet confirmed"', sentence)
        self.assertEqual(body["error_codes"][field], {"code": TRANSITIONAL_BASIS_REFUSED})

    def _assert_still_certified(self):
        status = compute_transition_status(self.parcel)
        on_records = [f for f in status.findings if f.source != "ParcelCropHistory"]
        self.assertEqual(on_records, [], "a refused write must leave no prohibited finding behind")
        self.assertEqual(status.last_prohibited_date, self.last, "the clock still dates to the field history")
        self.assertTrue(status.is_eligible)

    def test_the_offered_list_never_carries_a_refused_value_and_both_stay_stored_values(self):
        stored = {value for value, _label in ORGANIC_APPROVED}
        self.assertNotIn("transitional", ORGANIC_APPROVED_OFFERED)
        self.assertEqual(set(ORGANIC_APPROVED_OFFERED) & ORGANIC_APPROVED_REFUSED_ON_WRITE, set())
        self.assertLessEqual(set(ORGANIC_APPROVED_OFFERED), stored)
        # Refused on write, still a stored value with its label: an existing row renders.
        self.assertIn("transitional", ORGANIC_APPROVED_REFUSED_ON_WRITE)
        self.assertEqual(dict(ORGANIC_APPROVED)["transitional"], "Transitional - In certification process")

    def test_the_classification_is_unchanged(self):
        self.assertIn("transitional", ORGANIC_PROHIBITED_VALUES)
        self.assertNotIn("transitional", ORGANIC_APPROVED_OK_VALUES)
        self._stored_spray("transitional")
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertIsNotNone(status.last_prohibited_date)

    def test_a_new_spray_record_is_refused(self):
        res = self._post(
            CHEMICAL_EVENT_TYPE,
            type="FE",
            commercial_name="Fish emulsion 5-1-1",
            description="fish fertilizer",
            organic_approved="transitional",
        )
        self.assertEqual(res.status_code, 400, res.content[:500])
        self._assert_coded_refusal(res.json(), "organic_approved")
        self.assertFalse(ChemicalEvent.objects.exists())
        self._assert_still_certified()

    def test_a_new_spray_record_with_an_offered_basis_still_saves(self):
        """The mirror: refusing every basis would pass the test above."""
        res = self._post(
            CHEMICAL_EVENT_TYPE,
            type="FE",
            commercial_name="Fish emulsion 5-1-1",
            description="fish fertilizer",
            organic_approved="omri_listed",
        )
        self.assertEqual(res.status_code, 201, res.content[:500])
        self._assert_still_certified()

    def test_a_new_soil_amendment_is_refused(self):
        res = self._post(
            SOIL_MANAGEMENT_EVENT_TYPE,
            type="OM",
            description="feather meal",
            amendment_type="Feather meal 12-0-0",
            amendment_organic_approved="transitional",
        )
        self.assertEqual(res.status_code, 400, res.content[:500])
        self._assert_coded_refusal(res.json(), "amendment_organic_approved")
        self.assertFalse(SoilManagementEvent.objects.exists())
        self._assert_still_certified()

    def test_a_tank_line_is_refused_and_nothing_of_the_tank_is_written(self):
        lines = [
            {"tank_mix_role": "product", "commercial_name": "Entrust SC", "organic_approved": "omri_listed"},
            {"tank_mix_role": "product", "commercial_name": "Fish emulsion 5-1-1", "organic_approved": "transitional"},
        ]
        res = self.client.post(
            "/api/events/",
            {
                "event_type": CHEMICAL_EVENT_TYPE,
                "tank_mix_group": str(uuid.uuid4()),
                "date": (timezone.now() - timedelta(days=5)).isoformat(),
                "type": "PE",
                "products": lines,
                "targets": [{"parcel": self.parcel.id}],
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.content[:500])
        self._assert_coded_refusal(res.json()["products"]["2"], "organic_approved")
        self.assertFalse(ChemicalEvent.objects.exists())

    def test_an_edit_that_changes_the_basis_to_it_is_refused(self):
        for event_type, record, field in (
            (CHEMICAL_EVENT_TYPE, self._stored_spray("omri_listed"), "organic_approved"),
            (
                SOIL_MANAGEMENT_EVENT_TYPE,
                SoilManagementEvent.objects.create(
                    history=self.season,
                    date=timezone.now() - timedelta(days=10),
                    type="OM",
                    amendment_type="Feather meal 12-0-0",
                    amendment_organic_approved="omri_listed",
                    created_by=self.user,
                ),
                "amendment_organic_approved",
            ),
        ):
            with self.subTest(record=type(record).__name__):
                res = self._patch(record, event_type, **{field: "transitional"})
                self.assertEqual(res.status_code, 400, res.content[:500])
                self._assert_coded_refusal(res.json(), field)
                record.refresh_from_db()
                self.assertEqual(getattr(record, field), "omri_listed")
        self._assert_still_certified()

    def test_an_edit_that_leaves_a_stored_transitional_as_it_is_still_saves(self):
        """The edit form round-trips every field, the stored basis included."""
        spray = self._stored_spray("transitional")
        res = self._patch(spray, CHEMICAL_EVENT_TYPE, organic_approved="transitional", description="corrected note")
        self.assertEqual(res.status_code, 200, res.content[:500])
        spray.refresh_from_db()
        self.assertEqual((spray.organic_approved, spray.description), ("transitional", "corrected note"))
        # A partial edit that does not send the field changes nothing about it either.
        res = self._patch(spray, CHEMICAL_EVENT_TYPE, description="second note")
        self.assertEqual(res.status_code, 200, res.content[:500])
        # The answer on file is untouched, and so is what it means: no migration, no rewrite.
        spray.refresh_from_db()
        self.assertEqual(spray.organic_approved, "transitional")
        self.assertFalse(compute_transition_status(self.parcel).is_eligible)

        soil = SoilManagementEvent.objects.create(
            history=self.season,
            date=timezone.now() - timedelta(days=10),
            type="OM",
            amendment_type="Feather meal 12-0-0",
            amendment_organic_approved="transitional",
            created_by=self.user,
        )
        res = self._patch(
            soil, SOIL_MANAGEMENT_EVENT_TYPE, amendment_organic_approved="transitional", description="corrected"
        )
        self.assertEqual(res.status_code, 200, res.content[:500])
        soil.refresh_from_db()
        self.assertEqual(soil.amendment_organic_approved, "transitional")

    def test_moving_a_stored_transitional_to_an_offered_basis_saves(self):
        spray = self._stored_spray("transitional")
        res = self._patch(spray, CHEMICAL_EVENT_TYPE, organic_approved="omri_listed")
        self.assertEqual(res.status_code, 200, res.content[:500])
        self._assert_still_certified()

    def test_a_correction_never_gives_it_and_may_take_it_away(self):
        from history.amendments import AmendmentError, apply_amendment

        spray = self._stored_spray("omri_listed")
        with self.assertRaises(AmendmentError) as raised:
            apply_amendment(
                event=spray,
                event_type=CHEMICAL_EVENT_TYPE,
                field_name="organic_approved",
                new_value="transitional",
                reason="The farm is transitional.",
                user=self.user,
            )
        self.assertIn('"Transitional" describes a farm in conversion', str(raised.exception.message_dict))
        spray.refresh_from_db()
        self.assertEqual(spray.organic_approved, "omri_listed")

        stored = self._stored_spray("transitional")
        amendment = apply_amendment(
            event=stored,
            event_type=CHEMICAL_EVENT_TYPE,
            field_name="organic_approved",
            new_value="omri_listed",
            reason="The product is OMRI listed; transitional was the farm's status.",
            user=self.user,
        )
        self.assertEqual(amendment.corrected_value, "omri_listed")
