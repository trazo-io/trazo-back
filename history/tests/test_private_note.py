"""`CommonEvent.private_note` — the private half of the note pair.

`observation` publishes: one box of farmer prose reaches the buyer page, in the grower's own
words, labelled as public. Before `private_note` (2026-09-08) there was nowhere else to put a
note, so "rang the neighbour about drift" or "Maria thinks the north block is behind" had to go
in the box that publishes it.

Two things must hold, and they pull in opposite directions:

1. It must ROUND-TRIP on all eight families. A note the form accepts and the API drops is worse
   than no field at all — the grower believes it is recorded. This is the `extra_data_only_fields`
   class from 2026-09-07: written, never read back.
2. It must NEVER reach a buyer or shopper, while still reaching the OWNER (whose own Production
   Profile renders the same event dicts) and the CERTIFIER (§ 205.103(b)(2) is satisfied by what
   the operation recorded, not by the subset it published).

The public half of (2) is enforced in `test_public_response_schema` — a `"private"` key-shape
denylist plus a planted value, both proven to fail when the strip is removed. This file covers the
round-trip and the two audiences that MUST see it.
"""

from django.test import TestCase
from django.utils import timezone

from history import models as hm
from history import serializers as hs

NOTE = "Called Dwyer about drift off the county road; he denies it. Not for buyers."

#: family -> (model, read serializer, update serializer, extra kwargs the model requires)
FAMILIES = {
    "production": (
        hm.ProductionEvent,
        hs.ProductionEventSerializer,
        hs.UpdateProductionEventSerializer,
        {"type": "HA"},
    ),
    "chemical": (hm.ChemicalEvent, hs.ChemicalEventSerializer, hs.UpdateChemicalEventSerializer, {"type": "FE"}),
    "weather": (hm.WeatherEvent, hs.WeatherEventSerializer, hs.UpdateWeatherEventSerializer, {"type": "FR"}),
    "general": (hm.GeneralEvent, hs.GeneralEventSerializer, hs.UpdateGeneralEventSerializer, {}),
    "soil": (
        hm.SoilManagementEvent,
        hs.SoilManagementEventSerializer,
        hs.UpdateSoilManagementEventSerializer,
        {"type": "OM"},
    ),
    "pest": (
        hm.PestManagementEvent,
        hs.PestManagementEventSerializer,
        hs.UpdatePestManagementEventSerializer,
        {"type": "SC"},
    ),
    # ⚠️ business needs BOTH `type` and `business_type` — and the choice of `business_type`
    # matters: "certification" then demands `certification_type` in turn, so a one-field PATCH on
    # a certification event fails three validators deep. "transparency" is the one branch with no
    # dependent requirement, which is why it is used here. Same pre-existing partial-defeating
    # pattern as weather, documented in the update test below.
    "business": (
        hm.BusinessEvent,
        hs.BusinessEventSerializer,
        hs.UpdateBusinessEventSerializer,
        {"type": "CE", "business_type": "transparency"},
    ),
    "equipment": (
        hm.EquipmentEvent,
        hs.EquipmentEventSerializer,
        hs.UpdateEquipmentEventSerializer,
        {"type": "MN"},
    ),
}


class PrivateNoteRoundTripTests(TestCase):
    """Written, then read back — on every family, through the real serializers."""

    @classmethod
    def setUpTestData(cls):
        from company.models import Company, Establishment
        from product.models import Parcel, Product

        company = Company.objects.create(name="Private Note Co")
        establishment = Establishment.objects.create(name="Home Ranch", company=company, country="US", state="CA")
        parcel = Parcel.objects.create(name="River Block", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Walnuts")
        cls.history = hm.Production.objects.create(
            parcel=parcel,
            product=product,
            start_date=timezone.now(),
            published=True,
        )

    def _make(self, family):
        model, _, _, extra = FAMILIES[family]
        return model.objects.create(history=self.history, date=timezone.now(), private_note=NOTE, **extra)

    def test_every_family_stores_it(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                event = self._make(family)
                event.refresh_from_db()
                self.assertEqual(event.private_note, NOTE)

    def test_every_read_serializer_returns_it(self):
        # The `extra_data_only_fields` class: a column that saves and never comes back leaves the
        # grower with no way to see, edit or verify what they wrote.
        for family, (_, read_serializer, _, _) in FAMILIES.items():
            with self.subTest(family=family):
                data = read_serializer(self._make(family)).data
                self.assertIn("private_note", data, f"{family} read serializer drops private_note")
                self.assertEqual(data["private_note"], NOTE)

    def test_every_update_serializer_accepts_it(self):
        replacement = "Superseded: Dwyer's applicator confirmed the wind shift. Still not for buyers."
        for family, (_, _, update_serializer, extra) in FAMILIES.items():
            with self.subTest(family=family):
                event = self._make(family)
                # ⚠️ `extra` is resent, not decoration. `UpdateWeatherEventSerializer` and
                # `UpdateBusinessEventSerializer` re-declare `type` as an explicitly required
                # field, which overrides `partial=True` and makes a one-field PATCH fail with
                # "This field is required." That is a pre-existing inconsistency in those two
                # serializers, not a private_note defect — noted rather than fixed here, since
                # relaxing a required field is a write-path change of its own.
                payload = {"private_note": replacement, **extra}
                serializer = update_serializer(event, data=payload, partial=True)
                self.assertTrue(serializer.is_valid(), f"{family}: {serializer.errors}")
                serializer.save()
                event.refresh_from_db()
                self.assertEqual(event.private_note, replacement)

    def test_it_defaults_to_empty_rather_than_null(self):
        # `blank=True, default=""` and NOT nullable: two empty states for one text field is how
        # `or ""` ends up sprinkled across every reader.
        event = hm.GeneralEvent.objects.create(history=self.history, date=timezone.now())
        self.assertEqual(event.private_note, "")


class PrivateNoteReachesTheRightAudiencesTests(TestCase):
    """The counterpart to the public strip: the people who SHOULD see it, do."""

    def test_the_certifier_packet_prints_it_under_its_own_source(self):
        """Never folded into the published note's cell.

        The notes sub-tables carry a Source column so a reader can tell what the operation
        published in its own words from what it wrote only for this document. A private note
        appearing as "Farmer note" would present it as buyer-facing copy.
        """
        from history.services.audit_export_service import AuditExportService

        service = AuditExportService.__new__(AuditExportService)
        self.assertEqual(service._event_private_note_text(hm.GeneralEvent(private_note=NOTE)), NOTE)
        # A DIFFERENT accessor from the published note — that separation is the point.
        self.assertEqual(service._event_note_text(hm.GeneralEvent(private_note=NOTE)), "")

    def test_the_field_is_stripped_for_non_owners_by_the_certifier_only_list(self):
        self.assertIn("private_note", hs.PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS)

    def test_the_free_records_export_carries_it_without_being_told_to(self):
        # `records_export` walks `model._meta.concrete_fields`, so a new column travels with the
        # farm's own data by construction. Asserted because the ALTERNATIVE — an enumerated column
        # list — is what silently omits a field from the one export a leaving customer relies on.
        for family, (model, _, _, _) in FAMILIES.items():
            with self.subTest(family=family):
                columns = [f.name for f in model._meta.concrete_fields]
                self.assertIn("private_note", columns)
