"""Cross-surface buffer-zone round-trip (2026-08-09 P0 regression lock).

`Parcel.buffer_zones` is an untyped JSON blob with two writers — the Parcel page
(`CreateParcelSerializer`) and the OSP Parcel Application wizard
(`ParcelViewSet.application`). Until 2026-08-09 they owned different spellings of the same
record, which produced two failures that chained:

  1. One save on the Parcel page rebuilt every row from that serializer's whitelist, so the
     wizard's answers were destroyed, `adjacent_organic` became an affirmative `False`, and
     the § 205.202(c) `prohibited_use_last_date` was dropped.
  2. The row then carried the other vocabulary, so the wizard's next PUT was rejected with
     `unknown buffer keys` — the server refusing the payload its own GET had just served.
     Parcel Application gates OSP completion, so the operation was blocked outright.

These tests drive both surfaces in both orders. They are deliberately about the HANDOFF, not
about either writer alone: each writer's own tests passed throughout the incident.
"""

import json

from django.test import TestCase

from rest_framework.test import APIClient, APIRequestFactory

from company.models import Company, Establishment
from product.models import Parcel
from product.serializers import CreateParcelSerializer
from product.services.buffer_zones import CANONICAL_KEYS, drop_stamped_booleans, normalize_buffer_rows
from users.models import User, WorksIn

# Exactly what ParcelApplicationWizard.tsx sends.
WIZARD_ROW = {
    "direction": "North",
    "adjoining_land_use": "Neighbour almond orchard, certified organic",
    "buffer_type": "hedgerow",
    "buffer_width_ft": 25,
    "crop_grown_in_buffer": "Cover crop, mowed, never sold",
    "adjacent_is_organic": True,
    "prohibited_use_last_date": "2019-04-15",
}

# Exactly what ParcelComplianceCard.tsx / StandardParcelForm.tsx sent before 2026-08-09.
LEGACY_ROW = {
    "direction": "North",
    "adjoining_land_use": "Nonorganic almonds",
    "buffer_width_m": 7.6,
    "adjacent_organic": True,
    "crop_in_buffer": "grass",
    "neighbor_notified": True,
    "neighbor_notification_date": "2026-02-15",
}


class BufferZoneCrossSurfaceTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email="roundtrip@test.com", password="x")
        self.company = Company.objects.create(name="Round Trip Farm")
        self.establishment = Establishment.objects.create(name="RT1", company=self.company)
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.establishment, area=40.0)

    def _parcel_page_save(self, rows):
        """A save through the Parcel page / compliance card."""
        ser = CreateParcelSerializer(
            self.parcel,
            data={"buffer_zones": rows},
            partial=True,
            context={"request": self.factory.post("/", {}, format="json")},
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        ser.save()
        self.parcel.refresh_from_db()
        return self.parcel.buffer_zones

    def test_parcel_page_save_preserves_wizard_answers(self):
        """The original P0: a Parcel-page save must not destroy the wizard's record."""
        stored = normalize_buffer_rows([WIZARD_ROW])
        self.parcel.buffer_zones = stored
        self.parcel.save(update_fields=["buffer_zones"])

        # The farmer opens the Parcel page, which echoes the rows back on save.
        after = self._parcel_page_save(stored)[0]

        self.assertEqual(after["buffer_width_ft"], 25)
        self.assertEqual(after["crop_grown_in_buffer"], "Cover crop, mowed, never sold")
        self.assertIs(after["adjacent_is_organic"], True)
        self.assertEqual(after["prohibited_use_last_date"], "2019-04-15")

    def test_wizard_accepts_rows_written_by_the_parcel_page(self):
        """The chained blocker: the wizard must accept what the other surface stored."""
        stored = self._parcel_page_save([LEGACY_ROW])
        # normalize_buffer_rows is exactly what the wizard's PUT runs; it must not raise.
        echoed = normalize_buffer_rows(stored)
        self.assertEqual(echoed, stored)

    def test_round_trip_is_idempotent_in_both_directions(self):
        """Bouncing a record between surfaces must converge, not drift."""
        first = self._parcel_page_save([WIZARD_ROW])
        second = self._parcel_page_save(normalize_buffer_rows(first))
        third = self._parcel_page_save(normalize_buffer_rows(second))
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_legacy_and_canonical_spellings_converge(self):
        """Both vocabularies must land on the same stored record."""
        canonical = normalize_buffer_rows(
            [{"direction": "N", "adjoining_land_use": "x", "adjacent_is_organic": True, "crop_grown_in_buffer": "rye"}]
        )
        legacy = normalize_buffer_rows(
            [{"direction": "N", "adjoining_land_use": "x", "adjacent_organic": True, "crop_in_buffer": "rye"}]
        )
        self.assertEqual(canonical, legacy)

    def test_unanswered_boolean_is_never_stored_as_a_denial(self):
        """A missing answer must not become "the neighbour is not certified organic"."""
        row = normalize_buffer_rows([{"direction": "N", "adjoining_land_use": "Roadside"}])[0]
        self.assertIsNone(row["adjacent_is_organic"])
        self.assertIsNone(row["neighbor_notified"])

    def test_migration_drops_stamped_false_but_keeps_a_real_answer(self):
        """Migration 0023's judgement call, locked.

        The old serializer wrote `adjacent_organic: False` onto every row unprompted, so that
        value means "unanswered". `adjacent_is_organic: False` comes only from a farmer
        unticking the wizard checkbox, so it means "no" and must survive the migration.
        """
        legacy = drop_stamped_booleans(
            {"direction": "N", "adjoining_land_use": "x", "adjacent_organic": False, "neighbor_notified": False}
        )
        self.assertNotIn("adjacent_organic", legacy)
        self.assertNotIn("neighbor_notified", legacy)
        self.assertIsNone(normalize_buffer_rows([legacy])[0]["adjacent_is_organic"])

        wizard = drop_stamped_booleans({"direction": "N", "adjoining_land_use": "x", "adjacent_is_organic": False})
        self.assertIs(wizard["adjacent_is_organic"], False)
        self.assertIs(normalize_buffer_rows([wizard])[0]["adjacent_is_organic"], False)

        # A legacy True was only ever set by a farmer ticking the box — it is preserved.
        kept = drop_stamped_booleans({"direction": "N", "adjoining_land_use": "x", "adjacent_organic": True})
        self.assertIs(normalize_buffer_rows([kept])[0]["adjacent_is_organic"], True)

    def test_every_writer_produces_the_full_canonical_key_set(self):
        for label, row in (("wizard", WIZARD_ROW), ("legacy", LEGACY_ROW)):
            with self.subTest(writer=label):
                self.assertEqual(set(normalize_buffer_rows([row])[0]), set(CANONICAL_KEYS))

    def test_both_width_units_are_populated_from_either_entry(self):
        from_ft = normalize_buffer_rows([{**WIZARD_ROW}])[0]
        self.assertEqual(from_ft["buffer_width_ft"], 25)
        self.assertEqual(from_ft["buffer_width_m"], 7.6)

        # Rows written before migration 0023 carried metres alone; feet is derived for them.
        from_m = normalize_buffer_rows([{**LEGACY_ROW}])[0]
        self.assertEqual(from_m["buffer_width_m"], 7.6)
        self.assertEqual(from_m["buffer_width_ft"], 24.9)

    def test_metres_is_derived_and_never_trusted_as_an_independent_input(self):
        """Feet is the entry unit; a stale or edited metres value must not win.

        Every buffer-width input collects feet. If metres were accepted as a second editable
        source, a row saved by a feet surface and then by a metres surface would carry two
        disagreeing numbers for one quantity, and the width on the compliance record would
        depend on which reader you asked.
        """
        row = normalize_buffer_rows(
            [{"direction": "North", "adjoining_land_use": "x", "buffer_width_ft": 50, "buffer_width_m": 7.6}]
        )[0]
        self.assertEqual(row["buffer_width_ft"], 50)
        self.assertEqual(row["buffer_width_m"], 15.2)  # recomputed from 50 ft, not the stale 7.6

    def test_width_survives_repeated_normalization_without_drifting(self):
        row = {"direction": "North", "adjoining_land_use": "x", "buffer_width_m": 7.6}
        for _ in range(5):
            row = normalize_buffer_rows([row])[0]
        self.assertEqual(row["buffer_width_ft"], 24.9)
        self.assertEqual(row["buffer_width_m"], 7.6)

    def test_prohibited_use_date_survives_a_parcel_page_save(self):
        """§ 205.202(c): this date decides whether a buffer is required at all."""
        stored = self._parcel_page_save([WIZARD_ROW])
        self.assertEqual(stored[0]["prohibited_use_last_date"], "2019-04-15")

    def test_lone_prohibited_use_date_is_a_valid_boundary_record(self):
        """§ 205.202(c): that date is what proves a boundary needs NO buffer."""
        row = normalize_buffer_rows([{"direction": "East", "prohibited_use_last_date": "2024-06-15"}])[0]
        self.assertEqual(row["prohibited_use_last_date"], "2024-06-15")
        self.assertIsNone(row["adjoining_land_use"])

    def test_row_with_only_a_direction_is_rejected_as_empty(self):
        from product.services.buffer_zones import BufferZoneError

        with self.assertRaises(BufferZoneError):
            normalize_buffer_rows([{"direction": "West"}])

    def test_unknown_key_still_fails_loudly(self):
        ser = CreateParcelSerializer(
            self.parcel,
            data={"buffer_zones": [{"direction": "N", "adjoining_land_use": "x", "adjacent_organik": True}]},
            partial=True,
            context={"request": self.factory.post("/", {}, format="json")},
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("buffer_zones", ser.errors)


class BufferZoneEndpointRoundTripTests(TestCase):
    """The same handoff, driven through the real HTTP surfaces.

    The class above exercises the shared normalizer directly. This one goes through the
    Parcel Application endpoint and the parcel PATCH, because the incident was not a bug in
    either writer's logic — it was the boundary between two endpoints, and only a test that
    crosses that boundary would have caught it.
    """

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Round Trip API Farm")
        self.user = User.objects.create_user(email="rt-api@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="RT Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.establishment, area=40.0)
        self.client.force_authenticate(user=self.user)

    def _app_url(self):
        return (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}"
            f"/parcels/{self.parcel.id}/application/"
        )

    def _parcel_url(self):
        return f"/api/companies/{self.company.id}/establishments/{self.establishment.id}" f"/parcels/{self.parcel.id}/"

    def _parcel_page_save(self, rows):
        """Save through the Parcel page exactly as `updateParcelCompliance` does.

        That surface posts multipart/form-data with `buffer_zones` as a JSON string — the
        parcel endpoint rejects an application/json body outright — so the field arrives as
        a string and is parsed by DRF's JSONField. Sending JSON here instead would exercise
        a transport no client actually uses.
        """
        return self.client.patch(
            self._parcel_url(),
            {"buffer_zones": json.dumps(rows)},
            format="multipart",
        )

    def test_wizard_then_parcel_page_then_wizard_again(self):
        # 1. The farmer fills buffers in the OSP Parcel Application wizard.
        r = self.client.put(
            self._app_url(),
            {"values": {}, "buffer_zones": [WIZARD_ROW]},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)

        # 2. Later they save the Parcel page, which echoes those rows back. Before the fix
        #    this silently rebuilt the row and destroyed four of the wizard's answers.
        served = r.data["buffer_zones"]
        r2 = self._parcel_page_save(served)
        self.assertEqual(r2.status_code, 200, getattr(r2, "data", r2))

        self.parcel.refresh_from_db()
        row = self.parcel.buffer_zones[0]
        self.assertEqual(row["buffer_width_ft"], 25)
        self.assertEqual(row["crop_grown_in_buffer"], "Cover crop, mowed, never sold")
        self.assertIs(row["adjacent_is_organic"], True)
        self.assertEqual(row["prohibited_use_last_date"], "2019-04-15")

        # 3. They return to the wizard and save what the GET just served them. Before the
        #    fix this was a 400 — the server refusing its own payload.
        served_again = self.client.get(self._app_url()).data["buffer_zones"]
        r3 = self.client.put(
            self._app_url(),
            {"values": {}, "buffer_zones": served_again},
            format="json",
        )
        self.assertEqual(r3.status_code, 200, r3.data)

    def test_parcel_page_rows_are_accepted_by_the_wizard(self):
        """The other order: legacy-vocabulary rows written first."""
        r = self._parcel_page_save([LEGACY_ROW])
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))

        served = self.client.get(self._app_url()).data["buffer_zones"]
        r2 = self.client.put(self._app_url(), {"values": {}, "buffer_zones": served}, format="json")
        self.assertEqual(r2.status_code, 200, r2.data)

        self.parcel.refresh_from_db()
        row = self.parcel.buffer_zones[0]
        self.assertIs(row["adjacent_is_organic"], True)
        self.assertEqual(row["crop_grown_in_buffer"], "grass")
