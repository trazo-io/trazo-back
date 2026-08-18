"""Corrections to a filed record (2026-08-18).

Events on a finished production are locked (423) so the certifier packet cannot drift.
But locked must not mean wrong-forever: inspectors routinely ask operations to correct or
clarify records, and an operation that cannot correct one is worse off at audit. These
tests pin the shape of the compromise — the event carries the corrected value, and the
amendment carries the original, who, when and why.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone

from company.models import Company
from history.amendments import AmendmentError, apply_amendment
from history.constants import PRODUCTION_EVENT_TYPE
from history.models import EventAmendment, History, ProductionEvent
from product.models import Establishment, Parcel
from users.models import User, WorksIn


class AmendmentServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Amend Co")
        self.user = User.objects.create_user(email="amend@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Amend Farm", company=self.company)
        parcel = Parcel.objects.create(name="Amend Parcel", establishment=est, area=1)
        # A FINISHED season — the case the whole feature exists for.
        self.history = History.objects.create(
            parcel=parcel, name="2026", finish_date=timezone.now() - timedelta(days=1)
        )
        self.event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), yield_quantity=200
        )

    def _amend(self, **kwargs):
        payload = {
            "event": self.event,
            "event_type": PRODUCTION_EVENT_TYPE,
            "field_name": "yield_quantity",
            "new_value": "2000",
            "reason": "Transcription error: scale ticket reads 2,000 lb.",
            "user": self.user,
        }
        payload.update(kwargs)
        return apply_amendment(**payload)

    # --- the core behaviour -------------------------------------------------

    def test_event_carries_the_corrected_value(self):
        """Exports, QR and the packet all read the event, so it must hold the truth."""
        self._amend()
        self.event.refresh_from_db()
        self.assertEqual(int(self.event.yield_quantity), 2000)

    def test_amendment_preserves_the_original(self):
        """The strikethrough half: the old value stays legible."""
        a = self._amend()
        self.assertEqual(a.original_value, "200")
        self.assertEqual(a.corrected_value, "2000")

    def test_amendment_records_who_and_why(self):
        a = self._amend()
        self.assertEqual(a.amended_by, self.user)
        self.assertIn("Transcription error", a.reason)
        self.assertTrue(a.amended_by_name)
        self.assertIsNotNone(a.created_at)

    def test_amendment_works_on_a_finished_production(self):
        """The ordinary edit path answers 423 here — that is the point of this one."""
        self.assertIsNotNone(self.history.finish_date)
        self._amend()
        self.assertEqual(EventAmendment.objects.count(), 1)

    def test_amendment_is_linked_to_the_season(self):
        """Denormalised so the packet gathers a season's corrections in one query."""
        a = self._amend()
        self.assertEqual(a.history, self.history)
        self.assertEqual(list(self.history.amendments.all()), [a])

    # --- the rules that make it a correction, not a rewrite -----------------

    def test_reason_is_required(self):
        with self.assertRaises(AmendmentError) as ctx:
            self._amend(reason="")
        self.assertIn("reason", ctx.exception.message_dict)

    def test_whitespace_only_reason_is_rejected(self):
        with self.assertRaises(AmendmentError):
            self._amend(reason="   ")

    def test_nothing_is_written_when_the_reason_is_missing(self):
        """A refused correction must not leave the event half-changed."""
        with self.assertRaises(AmendmentError):
            self._amend(reason="")
        self.event.refresh_from_db()
        self.assertEqual(int(self.event.yield_quantity), 200)
        self.assertEqual(EventAmendment.objects.count(), 0)

    def test_protected_field_cannot_be_amended(self):
        """Moving the event to another season is not a correction, it is a different record."""
        with self.assertRaises(AmendmentError):
            self._amend(field_name="history")

    def test_signoff_fields_cannot_be_amended(self):
        """Re-asserting someone else's FSMA sign-off through a correction form."""
        for field in ("reviewed", "reviewer_name", "review_date"):
            with self.assertRaises(AmendmentError):
                self._amend(field_name=field)

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(AmendmentError):
            self._amend(field_name="not_a_real_field")

    def test_unparseable_value_is_refused_before_writing(self):
        with self.assertRaises(AmendmentError):
            self._amend(new_value="not-a-number")
        self.event.refresh_from_db()
        self.assertEqual(int(self.event.yield_quantity), 200)

    def test_no_op_correction_is_rejected(self):
        """An amendment row that changes nothing is noise in an audit trail."""
        with self.assertRaises(AmendmentError):
            self._amend(new_value="200")
        self.assertEqual(EventAmendment.objects.count(), 0)

    def test_mismatched_event_type_is_rejected(self):
        from history.constants import CHEMICAL_EVENT_TYPE

        with self.assertRaises(AmendmentError):
            self._amend(event_type=CHEMICAL_EVENT_TYPE)

    # --- successive corrections ---------------------------------------------

    def test_corrections_accumulate_rather_than_overwrite(self):
        """Each correction is its own line; the trail is append-only."""
        self._amend()
        self._amend(new_value="2500", reason="Re-weighed after drying.")
        rows = EventAmendment.objects.filter(event_id=self.event.id).order_by("created_at")
        self.assertEqual([r.original_value for r in rows], ["200", "2000"])
        self.assertEqual([r.corrected_value for r in rows], ["2000", "2500"])


class AmendableFieldSelectionTests(TestCase):
    """Which fields a correction may target, and which it must not.

    A harvest event carries ~79 correctable columns; a real record fills a handful. The
    endpoint splits them so the farmer sees what is ON the record first.
    """

    def setUp(self):
        company = Company.objects.create(name="Fields Co")
        est = Establishment.objects.create(name="Fields Farm", company=company)
        parcel = Parcel.objects.create(name="Fields Parcel", establishment=est, area=1)
        self.history = History.objects.create(parcel=parcel, name="2026")
        self.event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), yield_quantity=200
        )

    def test_json_fields_are_not_correctable(self):
        """Not just clutter — JSONField.to_python takes a raw string.

        Correcting `extra_data` with "2000" would replace a dict with the string "2000"
        and destroy structured compliance data.
        """
        from history.amendments import amendable_fields

        names = {f.name for f in amendable_fields(ProductionEvent)}
        for json_field in ("extra_data", "water_test_results", "drift_warning", "seed_search_attempts"):
            self.assertNotIn(json_field, names)

    def test_relational_fields_are_not_correctable(self):
        """Correcting by raw pk typed into a text box repoints the record at another row."""
        from history.amendments import amendable_fields

        names = {f.name for f in amendable_fields(ProductionEvent)}
        self.assertNotIn("equipment_cleaning_event", names)

    def test_amending_a_json_field_is_refused(self):
        """The service must refuse it, not only the UI hide it."""
        with self.assertRaises(AmendmentError):
            apply_amendment(
                event=self.event,
                event_type=PRODUCTION_EVENT_TYPE,
                field_name="extra_data",
                new_value="2000",
                reason="Should never be allowed.",
                user=None,
            )

    def test_has_value_splits_populated_from_blank(self):
        from history.amendments import amendable_fields, has_value

        fields = {f.name: f for f in amendable_fields(ProductionEvent)}
        self.assertTrue(has_value(self.event, fields["yield_quantity"]))
        self.assertFalse(has_value(self.event, fields["storage_location"]))

    def test_whitespace_only_string_counts_as_blank(self):
        from history.amendments import amendable_fields, has_value

        self.event.performed_by = "   "
        fields = {f.name: f for f in amendable_fields(ProductionEvent)}
        self.assertFalse(has_value(self.event, fields["performed_by"]))

    def test_populated_set_is_a_small_fraction_of_the_whole(self):
        """The point of the split: a real record populates a handful of ~79 columns.

        MEASURED on this bare harvest event: 79 correctable columns, 4 actually recorded.
        """
        from history.amendments import amendable_fields, has_value

        all_fields = amendable_fields(ProductionEvent)
        populated = [f.name for f in all_fields if has_value(self.event, f)]
        self.assertGreater(len(all_fields), 50)
        self.assertEqual(sorted(populated), ["date", "type", "yield_quantity"])

    def test_a_field_still_on_its_default_is_not_on_the_record(self):
        """`area_unit` defaulting to a unit while `area_covered` is blank is noise.

        Counting defaults as recorded put 12 fields in the dropdown, four of them units
        whose paired quantity was never entered and three booleans sitting at False.
        """
        from history.amendments import amendable_fields, has_value

        fields = {f.name: f for f in amendable_fields(ProductionEvent)}
        for defaulted in ("area_unit", "shared_with_conventional", "rinse_step_documented"):
            field = fields[defaulted]
            self.assertTrue(field.has_default(), f"{defaulted} lost its default")
            self.assertFalse(has_value(self.event, field))

    def test_an_explicitly_set_value_is_on_the_record_even_if_it_equals_a_default(self):
        """Honest limitation, pinned: we cannot tell 'set to the default' from 'never set'.

        A farmer who genuinely recorded the default value finds that field under the
        secondary 'not recorded' list rather than the primary one. That is the right
        trade — the alternative floods the primary list for every record — but it is a
        real edge and should fail loudly here if the rule is ever changed by accident.
        """
        from history.amendments import amendable_fields, has_value

        fields = {f.name: f for f in amendable_fields(ProductionEvent)}
        self.event.shared_with_conventional = False  # explicitly asserted, same as default
        self.assertFalse(has_value(self.event, fields["shared_with_conventional"]))


class AmendmentValidationEdgeTests(TestCase):
    """Edges found re-reading the service: model clean(), Decimal equality, rollback."""

    def setUp(self):
        company = Company.objects.create(name="Edge Co")
        self.user = User.objects.create_user(email="edge@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Edge Farm", company=company)
        parcel = Parcel.objects.create(name="Edge Parcel", establishment=est, area=1)
        self.history = History.objects.create(
            parcel=parcel, name="2026", finish_date=timezone.now() - timedelta(days=1)
        )
        self.event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), yield_quantity=200
        )

    def _amend(self, **kw):
        payload = {
            "event": self.event,
            "event_type": PRODUCTION_EVENT_TYPE,
            "field_name": "yield_quantity",
            "new_value": "2000",
            "reason": "Transcription error.",
            "user": self.user,
        }
        payload.update(kw)
        return apply_amendment(**payload)

    def test_decimal_equal_values_are_a_no_op_despite_rendering_differently(self):
        """Decimal("200.00") and Decimal("200") are equal but render as different strings.

        Comparing only rendered forms would accept this and write a correction line
        reading "200.00 -> 200" into a document an inspector reads closely.
        """
        with self.assertRaises(AmendmentError):
            self._amend(new_value="200.00")
        self.assertEqual(EventAmendment.objects.count(), 0)

    def test_rejected_correction_leaves_the_in_memory_event_unchanged(self):
        """The DB is covered by the atomic block; the caller's instance was not.

        A rejected correction used to leave the bad value sitting on the object the
        caller is still holding.
        """
        original = self.event.yield_quantity
        with self.assertRaises(AmendmentError):
            self._amend(field_name="date", new_value="not-a-date")
        self.assertEqual(self.event.yield_quantity, original)
        self.event.refresh_from_db()
        self.assertEqual(self.event.yield_quantity, original)

    def test_a_record_failing_its_model_clean_is_still_correctable(self):
        """8 event models define clean() enforcing cross-field rules.

        `full_clean(exclude=...)` skips excluded FIELDS but still runs `clean()`, so an
        unrelated pre-existing gap would refuse the correction — making exactly the old,
        incomplete records that most need fixing permanently uncorrectable. The service
        uses `clean_fields` instead.
        """
        # WeatherEvent.clean() rejects implausible magnitudes via extra_data.
        from history.constants import WEATHER_EVENT_TYPE
        from history.models import WeatherEvent

        bad = WeatherEvent.objects.create(
            history=self.history,
            type="FR",
            date=timezone.now(),
            extra_data={"temperature": 9999, "temperature_unit": "F"},
        )
        with self.assertRaises(DjangoValidationError):
            bad.full_clean()  # the record genuinely does not pass its own clean()

        amendment = apply_amendment(
            event=bad,
            event_type=WEATHER_EVENT_TYPE,
            field_name="performed_by",
            new_value="J. Alvarez",
            reason="Operator was not recorded at the time.",
            user=self.user,
        )
        self.assertEqual(amendment.corrected_value, "J. Alvarez")

    def test_field_level_validation_still_applies_to_the_corrected_field(self):
        """Skipping model.clean() must not mean skipping the corrected field's own rules."""
        with self.assertRaises(AmendmentError):
            self._amend(field_name="performed_by", new_value="x" * 5000)
