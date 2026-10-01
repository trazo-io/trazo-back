"""
A partial update must not overwrite the description it never mentioned.

WHY (2026-08-12): `ensure_event_description` (the F01 fix for blank Observations returning a
silent 400) ran unconditionally at the top of `to_internal_value`, which DRF calls for PATCH
as well as POST. So any partial update omitting `description` had a placeholder written into
`data` before field processing — DRF's own default-skipping for partial updates never got a
say, because this is not a field default.

⚠️ The placeholder shape in the examples below is HISTORICAL. `ensure_event_description` stopped
prefixing the internal event type on 2026-09-28, because "Production activity: Irrigation" was
reaching a farmer's screen under a heading that says Field Notes. It now stores the event name
alone. What these tests pin is unchanged and is the thing that matters: an update never replaces a
description already on the record.

Measured on a real harvest event:

    PATCH {"buffer_disposition_quantity": "1 4x4 bin"}
    description: "Shake and pickup, north rows first. Scale ticket 4471."
              -> "Production activity"

The grower's note and its scale-ticket reference — audit-trail material under § 205.103(b)(2)
— replaced by a placeholder, silently, by a request that never named the field. Six event
types were affected, which is consistent with the earlier incident where editing a description
destroyed a weather record.

Three behaviours are pinned, because the fix must not undo F01:
  1. PATCH without `description`      -> preserved
  2. PATCH with a BLANK `description` -> still defaulted (the user cleared the notes box)
  3. CREATE without `description`     -> still defaulted (the original silent-400 case)
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History
from history.serializers import (
    UpdateBusinessEventSerializer,
    UpdateEquipmentEventSerializer,
    UpdateGeneralEventSerializer,
    UpdateProductionEventSerializer,
    UpdateSoilManagementEventSerializer,
    UpdateWeatherEventSerializer,
)
from product.models import Parcel, Product
from users.models import User

GROWER_NOTE = "Shake and pickup, north rows first. Scale ticket 4471."

# serializer -> (a harmless field to PATCH that is NOT description, the rest of a valid
# create payload). The two are separate because a PATCH legitimately omits required fields
# while a create must supply them — conflating them made the first version of this test fail
# on empty `validated_data` and look like a code bug when it was a fixture bug.
CASES = [
    (UpdateProductionEventSerializer, {"buffer_disposition_quantity": "1 4x4 bin"}, {"type": "HA"}),
    (UpdateWeatherEventSerializer, {"observation": "clear"}, {"type": "FR"}),
    (UpdateGeneralEventSerializer, {"observation": "walkthrough"}, {"name": "Walkthrough"}),
    (UpdateSoilManagementEventSerializer, {"amendment_type": "compost"}, {}),
    # "transparency", not "certification": the latter also demands certification_type.
    (UpdateBusinessEventSerializer, {"observation": "note"}, {"business_type": "transparency"}),
    (UpdateEquipmentEventSerializer, {"observation": "note"}, {}),
]


class PartialUpdatePreservesDescriptionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = User.objects.create_user(email="desc@test.com", password="x")
        company = Company.objects.create(name="Desc Co")
        establishment = Establishment.objects.create(name="DC1", company=company)
        parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)
        product = Product.objects.create(name="Walnuts")
        cls.history = History.objects.create(
            name="Desc Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def test_partial_update_without_description_leaves_it_alone(self):
        """The bug: every one of these rewrote the grower's note to a placeholder."""
        for serializer_cls, payload, create_extra in CASES:
            with self.subTest(serializer=serializer_cls.__name__):
                # create_extra is merged in because Weather and Business validate their type
                # field unconditionally — even under partial=True, a PATCH omitting it 400s.
                # That is its own oddity (noted, not fixed here); it is not what this asserts.
                serializer = serializer_cls(data={**payload, **create_extra}, partial=True)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertNotIn(
                    "description",
                    serializer.validated_data,
                    f"{serializer_cls.__name__} injected a description into a partial update "
                    "that never mentioned one — this overwrites the grower's note on save",
                )

    def test_a_blank_description_is_still_defaulted_on_partial_update(self):
        """F01 must survive: clearing the notes box must not 400."""
        for serializer_cls, _payload, create_extra in CASES:
            with self.subTest(serializer=serializer_cls.__name__):
                # create_extra carries any field the serializer validates unconditionally
                # (weather `type`, business `business_type`) even under partial=True.
                serializer = serializer_cls(data={"description": "", **create_extra}, partial=True)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertTrue(
                    str(serializer.validated_data.get("description") or "").strip(),
                    f"{serializer_cls.__name__} left description blank — F01 regression, "
                    "this is the silent 400 that made the save button look dead",
                )

    def test_a_missing_description_is_still_defaulted_on_create(self):
        for serializer_cls, payload, create_extra in CASES:
            with self.subTest(serializer=serializer_cls.__name__):
                serializer = serializer_cls(
                    data={**payload, **create_extra, "history": self.history.id, "date": "2026-08-12T00:00:00Z"}
                )
                # Assert validity FIRST: an invalid payload leaves validated_data empty, and
                # the description assertion below would then "fail" for the wrong reason.
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertTrue(
                    str(serializer.validated_data.get("description") or "").strip(),
                    f"{serializer_cls.__name__} did not default description on create — F01 regression",
                )

    def test_the_saved_row_keeps_the_grower_note(self):
        """End to end on a real row, because validated_data alone would not prove the save."""
        from history.models import ProductionEvent

        event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), description=GROWER_NOTE
        )
        serializer = UpdateProductionEventSerializer(
            event, data={"buffer_disposition_quantity": "1 4x4 bin"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        event.refresh_from_db()
        self.assertEqual(event.description, GROWER_NOTE)
        self.assertEqual(event.buffer_disposition_quantity, "1 4x4 bin")

    # ------------------------------------------------------------------
    # 2026-08-15: the PUT half. The 08-12 fix guarded on `partial`, and the
    # app's own edit form does not send PATCH — so none of the tests above
    # covered the path a grower actually takes.
    # ------------------------------------------------------------------

    def test_full_update_with_a_blank_description_keeps_the_stored_one(self):
        """The live bug: open Edit, change nothing, press Update.

        The edit form prefills its notes box from `observation` only, so a row whose text
        lives in `description` opens with an empty box and PUTs that blank straight back.
        Measured before the fix, on a Planting event:

            PUT  /api/companies/91/establishments/127/events/3882/
            "Replanted 40 Hass on Duke 7 rootstock, rows 1-12, east buffer."
                -> "Production activity: Planting"
        """
        from history.models import ProductionEvent

        for serializer_cls, _payload, create_extra in CASES:
            with self.subTest(serializer=serializer_cls.__name__):
                event = ProductionEvent.objects.create(
                    history=self.history, type="HA", date=timezone.now(), description=GROWER_NOTE
                )
                serializer = serializer_cls(
                    event,
                    data={"description": "", "date": "2026-08-15T00:00:00Z", **create_extra},
                    partial=False,
                )
                # Assert validity first: an invalid payload leaves validated_data empty and
                # the assertion below would fail for the wrong reason (the fixture trap this
                # file already documents for the create case).
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(
                    serializer.validated_data.get("description"),
                    GROWER_NOTE,
                    f"{serializer_cls.__name__} blanked a stored description on a full update — "
                    "this is the silent destruction of § 205.103 record content",
                )

    def test_full_update_omitting_description_keeps_the_stored_one(self):
        from history.models import ProductionEvent

        event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), description=GROWER_NOTE
        )
        serializer = UpdateProductionEventSerializer(
            event, data={"type": "HA", "date": "2026-08-15T00:00:00Z"}, partial=False
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        event.refresh_from_db()
        self.assertEqual(event.description, GROWER_NOTE)

    def test_a_grower_can_still_rewrite_the_note(self):
        """The guard preserves; it must not freeze. Explicit new text always wins."""
        from history.models import ProductionEvent

        event = ProductionEvent.objects.create(
            history=self.history, type="HA", date=timezone.now(), description=GROWER_NOTE
        )
        serializer = UpdateProductionEventSerializer(
            event,
            data={"type": "HA", "date": "2026-08-15T00:00:00Z", "description": "Rewritten by the grower"},
            partial=False,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        event.refresh_from_db()
        self.assertEqual(event.description, "Rewritten by the grower")

    def test_a_blank_description_on_a_row_that_has_none_is_still_defaulted(self):
        """F01 must survive the new guard: preservation only applies to a stored value."""
        from history.models import ProductionEvent

        event = ProductionEvent.objects.create(history=self.history, type="HA", date=timezone.now(), description="")
        serializer = UpdateProductionEventSerializer(
            event,
            data={"type": "HA", "date": "2026-08-15T00:00:00Z", "name": "Harvest", "description": ""},
            partial=False,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertTrue(str(serializer.validated_data.get("description") or "").strip())
