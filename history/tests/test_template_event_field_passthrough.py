"""
Template-created events must carry the fields the template actually specifies.

WHY (2026-08-12): `_create_single_template_event` built each event from a HAND-MAINTAINED
kwarg list. A field added through the 7-step standard in `src/config/events/ADDING_FIELDS.md`
reached the model, both serializers, the registry, the form and the certifier packet — and was
then silently dropped by the template flow, which is the path most growers actually use. The
standard never mentions `history/views.py`, which is why nobody noticed.

Measured before the fix: **167 concrete fields across production / soil / chemical / pest
existed on the models and could not be set from a template.**

`_template_extra_fields` closes that generically, but "generic" near mass-assignment needs its
limits pinned, not assumed. Both halves are asserted here:

  * real model fields named by a template DO reach the row
  * identity / ownership / audit columns and unknown keys DO NOT, whatever a template says
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent, SoilManagementEvent
from history.views import HistoryViewSet
from product.models import Parcel, Product
from users.models import User


class TemplateExtraFieldsFilterTests(TestCase):
    """The allowlist itself — asserted directly, so the rules are readable without a fixture."""

    def _extras(self, model, backend_fields, already_set=None):
        return HistoryViewSet._template_extra_fields(model, backend_fields, already_set or {})

    def test_passes_through_a_real_model_field(self):
        extras = self._extras(SoilManagementEvent, {"manure_animal_source": "poultry"})
        self.assertEqual(extras, {"manure_animal_source": "poultry"})

    def test_ignores_a_key_that_is_not_a_field_on_that_model(self):
        """Unknown keys must be DROPPED, not forwarded — `create()` would raise on them, and
        one bad template key would kill every event in the production."""
        self.assertEqual(self._extras(SoilManagementEvent, {"not_a_real_column": 1}), {})

    def test_ignores_a_field_that_belongs_to_a_different_event_model(self):
        """`buffer_disposition` is a ProductionEvent field; a soil template naming it is noise."""
        self.assertEqual(self._extras(SoilManagementEvent, {"buffer_disposition": "sold_conventional"}), {})

    def test_never_lets_a_template_repoint_a_relation(self):
        """A template that could set `history` or `created_by` would let one operation's
        template write rows into another operation's audit file."""
        extras = self._extras(ProductionEvent, {"history": 999, "created_by": 999})
        self.assertEqual(extras, {})

    def test_never_overrides_a_value_the_caller_set_explicitly(self):
        """Existing defaults keep winning — the change is additive by construction."""
        extras = self._extras(SoilManagementEvent, {"type": "OM"}, already_set={"type": "ST"})
        self.assertEqual(extras, {})

    def test_denylisted_audit_columns_are_refused(self):
        for key in ("id", "index", "date", "description", "performed_by", "created_at"):
            with self.subTest(key=key):
                self.assertEqual(self._extras(SoilManagementEvent, {key: "x"}), {})

    def test_tolerates_a_non_dict_payload(self):
        for payload in (None, [], "manure"):
            with self.subTest(payload=payload):
                self.assertEqual(self._extras(SoilManagementEvent, payload), {})


class TemplateEventsCarryNewFieldsTests(TestCase):
    """End to end through the real creation path, not just the filter."""

    def setUp(self):
        self.user = User.objects.create_user(email="tmpl@test.com", password="x")
        company = Company.objects.create(name="Tmpl Co")
        establishment = Establishment.objects.create(name="TC1", company=company)
        parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Template Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _create(self, event_data):
        HistoryViewSet()._create_single_template_event(self.history, event_data, 0)

    def test_a_soil_template_carries_the_usda_manure_columns(self):
        self._create(
            {
                "name": "Compost / manure application",
                "backend_event_type": 5,
                "enabled": True,
                "backend_event_fields": {
                    "type": "OM",
                    "amendment_type": "manure",
                    "manure_animal_source": "poultry",
                    "manure_form": "dry",
                    "manure_origin": "on_farm",
                    "manure_application_method": "broadcast_incorporated",
                },
            }
        )
        event = SoilManagementEvent.objects.get(history=self.history)
        self.assertEqual(event.manure_animal_source, "poultry")
        self.assertEqual(event.manure_form, "dry")
        self.assertEqual(event.manure_origin, "on_farm")
        self.assertEqual(event.manure_application_method, "broadcast_incorporated")
        # And USDA's combined column reconstructs from what the template set.
        self.assertEqual(
            event.manure_type_form_source_display(),
            "Poultry (chicken, turkey, duck), Dry / solid, Produced on this operation",
        )

    def test_a_harvest_template_carries_the_buffer_disposition_columns(self):
        self._create(
            {
                "name": "Harvest",
                "backend_event_type": 1,
                "enabled": True,
                "backend_event_fields": {
                    "type": "HA",
                    "buffer_disposition": "sold_conventional",
                    "buffer_disposition_quantity": "1 4x4 bin",
                    "buffer_disposition_evidence": "Delivery tag, buffer-crop folder",
                },
            }
        )
        event = ProductionEvent.objects.get(history=self.history)
        self.assertEqual(event.buffer_disposition, "sold_conventional")
        self.assertEqual(event.buffer_disposition_quantity, "1 4x4 bin")
        self.assertTrue(event.buffer_disposition_entered_commerce())

    def test_a_template_omitting_a_not_null_column_still_creates_the_event(self):
        """The silent-drop bug, pinned.

        Every branch passes `backend_fields.get("x")` for the columns it names, so a template
        that omits "x" sent an explicit None — and an explicit None OVERRIDES a model default.
        `transportation_unit` is null=False default="miles", so the insert died on the
        constraint. `_create_template_events` catches per-event exceptions and continues, so
        the grower ticked the event, saw no error, and simply had no event.

        Measured across the seeded catalogue at the time of the fix:
        **390 of 1029 templates created, 639 failed. After: 1029 of 1029.**
        """
        self._create(
            {
                "name": "Season Irrigation Program",
                "backend_event_type": 1,
                "enabled": True,
                # Deliberately no transportation_unit — 139 of 190 production templates omit it.
                "backend_event_fields": {"type": "IR", "irrigation_method": "drip"},
            }
        )
        event = ProductionEvent.objects.get(history=self.history)
        self.assertEqual(event.transportation_unit, "miles", "model default did not apply")

    def test_an_explicit_none_is_kept_for_a_nullable_column(self):
        """Only NOT NULL columns hand back to the default. On a nullable column None is a
        real value and must survive, or this fix would quietly rewrite grower data."""
        self._create(
            {
                "name": "Harvest",
                "backend_event_type": 1,
                "enabled": True,
                "backend_event_fields": {"type": "HA", "transportation_distance": None},
            }
        )
        self.assertIsNone(ProductionEvent.objects.get(history=self.history).transportation_distance)

    def test_an_unknown_template_key_does_not_kill_the_event(self):
        """Before the filter, forwarding an unknown key to create() would raise TypeError and
        the surrounding savepoint would drop the whole event."""
        self._create(
            {
                "name": "Compost",
                "backend_event_type": 5,
                "enabled": True,
                "backend_event_fields": {"type": "OM", "totally_made_up_key": "x"},
            }
        )
        self.assertEqual(SoilManagementEvent.objects.filter(history=self.history).count(), 1)

    def test_a_template_cannot_write_into_another_operation(self):
        other = History.objects.create(
            name="Someone Else",
            start_date=timezone.now(),
            product=self.history.product,
            parcel=self.history.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        self._create(
            {
                "name": "Compost",
                "backend_event_type": 5,
                "enabled": True,
                "backend_event_fields": {"type": "OM", "history": other.id},
            }
        )
        self.assertEqual(SoilManagementEvent.objects.filter(history=other).count(), 0)
        self.assertEqual(SoilManagementEvent.objects.filter(history=self.history).count(), 1)
