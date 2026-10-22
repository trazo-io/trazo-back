"""The multi-parcel spec (`history/services/multi_target_spec.json`) against the models and the API.

The spec decides, per activity type, what is shared, what differs per parcel and what is refused.
These tests hold it to the code it describes: every subtype it names is a real choice, every key it
lists is one the type's serializer accepts, every included subtype saves one record per parcel
with that parcel's own values, and every excluded subtype is refused.
"""

import json
import uuid

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company, Establishment
from history.models import (
    ChemicalEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from history.serializers import (
    UpdateChemicalEventSerializer,
    UpdateGeneralEventSerializer,
    UpdatePestManagementEventSerializer,
    UpdateProductionEventSerializer,
    UpdateSoilManagementEventSerializer,
    UpdateWeatherEventSerializer,
)
from history.services.multi_target import SPEC_PATH, SPECS
from product.models import Parcel

SERIALIZERS = {
    0: UpdateWeatherEventSerializer,
    1: UpdateProductionEventSerializer,
    2: UpdateChemicalEventSerializer,
    3: UpdateGeneralEventSerializer,
    5: UpdateSoilManagementEventSerializer,
    6: UpdatePestManagementEventSerializer,
}
MODELS = {
    0: WeatherEvent,
    1: ProductionEvent,
    2: ChemicalEvent,
    3: GeneralEvent,
    5: SoilManagementEvent,
    6: PestManagementEvent,
}

# Single-parcel on purpose: a lot, a pile, a sample or a finding is a fact of one place.
EXCLUDED = {
    1: ["HA", "PH", "TP", "BU", "EM", "SS"],
    5: ["ST", "LA", "CO", "GR"],
    # IP records a § 205.206(e) threshold finding, the same observation class as SC and TA.
    6: ["SC", "TM", "PI", "TA", "IP"],
}


def _accepted_keys(serializer_class) -> set:
    """Request keys a serializer takes: its declared fields plus the keys it moves into extra_data."""
    keys = set(serializer_class().fields)
    keys |= set(getattr(serializer_class, "EXTRA_DATA_FIELDS", []))
    return keys


class SpecMatchesTheCodeTests(SimpleTestCase):
    def test_the_file_and_the_loaded_specs_agree(self):
        raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        self.assertEqual({int(k) for k in raw["types"]}, set(SPECS))

    def test_every_listed_subtype_is_a_real_choice(self):
        for event_type, spec in SPECS.items():
            if spec.subtypes is None:
                continue
            choices = {code for code, _ in MODELS[event_type]._meta.get_field("type").choices}
            with self.subTest(event_type=event_type):
                self.assertLessEqual(set(spec.subtypes), choices)
                self.assertLessEqual(set(spec.per_target_by_subtype), set(spec.subtypes))

    def test_every_per_parcel_key_is_one_the_serializer_accepts(self):
        """The keys written per parcel must reach the record. (Refused keys need not be fields:
        several are summary totals the serializer moves into extra_data on its own.)"""
        for event_type, spec in SPECS.items():
            accepted = _accepted_keys(SERIALIZERS[event_type])
            written = set(spec.per_target) | set(spec.either)
            for keys in spec.per_target_by_subtype.values():
                written |= set(keys)
            with self.subTest(event_type=event_type):
                self.assertEqual(sorted(written - accepted), [])

    def test_a_key_is_never_both_per_parcel_and_refused(self):
        for event_type, spec in SPECS.items():
            all_per_target = set(spec.per_target).union(*spec.per_target_by_subtype.values())
            with self.subTest(event_type=event_type):
                self.assertEqual(all_per_target & set(spec.refused), set())
                self.assertEqual(all_per_target, set(spec.per_target_any()))
                self.assertEqual(all_per_target & set(spec.either), set())

    def test_every_top_level_refusal_holds_inside_extra_data_too(self):
        for event_type, spec in SPECS.items():
            with self.subTest(event_type=event_type):
                self.assertLessEqual(set(spec.refused), set(spec.refused_extra_data))

    def test_a_season_summary_is_never_one_application(self):
        """A summary record stands for many applications over a period, so it has no place in a
        group of per-parcel records of one application. Every type refuses its keys."""
        for event_type, spec in SPECS.items():
            with self.subTest(event_type=event_type):
                self.assertLessEqual({"is_summary", "date_start", "date_end", "event_count"}, set(spec.refused))

    def test_an_optional_per_parcel_amount_may_carry_its_unit_per_parcel(self):
        """An optional amount (fuel, irrigation depth) is entered on some parcels and not others.
        Its unit must be able to travel with it: sent shared, a client that only sends a unit
        beside an amount drops it, and the model default ("gal", "inches") is stored against
        figures entered in litres or centimetres."""
        for event_type, spec in SPECS.items():
            raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["types"][str(event_type)]["ui"]
            fields = raw["fields"] + [f for fs in raw.get("fields_by_subtype", {}).values() for f in fs]
            units = {f["unit_key"] for f in fields if f.get("unit_key") and not f.get("required")}
            with self.subTest(event_type=event_type):
                self.assertLessEqual(units, set(spec.either) | set(spec.per_target_any()))

    def test_excluded_subtypes_are_not_in_the_spec(self):
        for event_type, codes in EXCLUDED.items():
            with self.subTest(event_type=event_type):
                self.assertEqual(set(codes) & set(SPECS[event_type].subtypes), set())


class _SeveralParcels(APITestCase):
    """Three parcels with one open season each, and the request helpers."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="spec-grower@example.com", password="pw-for-tests-only")
        company = Company.objects.create(name="Spec Co")
        cls.user.companies.add(company)
        farm = Establishment.objects.create(name="Spec Farm", company=company)
        cls.parcels, cls.seasons = [], []
        for name in ("North", "South", "East"):
            parcel = Parcel.objects.create(name=name, establishment=farm, area=4)
            season = History.objects.create(parcel=parcel, name=f"{name} 2026", start_date=timezone.now())
            parcel.current_history = season
            parcel.save(update_fields=["current_history"])
            cls.parcels.append(parcel)
            cls.seasons.append(season)

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _body(self, subtype, targets, **shared):
        return {
            "event_type": 1,
            "application_group": str(uuid.uuid4()),
            "date": timezone.now().replace(microsecond=0).isoformat(),
            "type": subtype,
            "targets": targets,
            **shared,
        }

    def _post(self, body):
        return self.client.post(reverse("events-list"), body, format="json")

    def _records(self, body):
        return {e.history_id: e for e in ProductionEvent.objects.filter(application_group=body["application_group"])}


class ProductionOnSeveralParcelsTests(_SeveralParcels):
    def test_irrigation_each_parcel_its_own_depth_area_and_fuel(self):
        a, b, _ = self.parcels
        body = self._body(
            "IR",
            [
                {"parcel": a.id, "area_covered": "4", "irrigation_depth": "1.5", "fuel_consumed": "2"},
                {"parcel": b.id, "area_covered": "3", "irrigation_depth": "1", "equipment_hours": "5"},
            ],
            irrigation_method="drip",
            irrigation_depth_unit="inches",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        records = self._records(body)
        ra, rb = records[self.seasons[0].id], records[self.seasons[1].id]
        self.assertEqual((float(ra.area_covered), float(ra.irrigation_depth), float(ra.fuel_consumed)), (4.0, 1.5, 2.0))
        self.assertEqual((float(rb.area_covered), float(rb.irrigation_depth)), (3.0, 1.0))
        self.assertIsNone(rb.fuel_consumed)
        self.assertEqual(float(rb.equipment_hours), 5.0)

    def test_a_unit_travels_with_its_amount_on_the_parcel_that_has_one(self):
        a, b, _ = self.parcels
        body = self._body(
            "IR",
            [
                {
                    "parcel": a.id,
                    "irrigation_depth": "3",
                    "irrigation_depth_unit": "cm",
                    "fuel_consumed": "20",
                    "fuel_unit": "L",
                },
                {"parcel": b.id, "irrigation_depth": "1", "irrigation_depth_unit": "cm"},
            ],
            irrigation_method="drip",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        records = self._records(body)
        ra, rb = records[self.seasons[0].id], records[self.seasons[1].id]
        self.assertEqual((ra.irrigation_depth_unit, ra.fuel_unit), ("cm", "L"))
        self.assertEqual(rb.irrigation_depth_unit, "cm")

    def test_a_unit_sent_once_for_every_parcel_is_still_accepted(self):
        # The client in production before units moved per parcel sends them shared.
        a, b, _ = self.parcels
        body = self._body(
            "MO",
            [{"parcel": a.id, "fuel_consumed": "20"}, {"parcel": b.id}],
            fuel_unit="L",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        self.assertEqual(self._records(body)[self.seasons[0].id].fuel_unit, "L")

    def test_a_unit_sent_both_shared_and_per_parcel_is_refused(self):
        a, b, _ = self.parcels
        body = self._body(
            "MO",
            [{"parcel": a.id, "fuel_consumed": "20", "fuel_unit": "L"}, {"parcel": b.id}],
            fuel_unit="gal",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:300])
        self.assertIn("either", res.json())

    def test_planting_shares_the_seed_lot_and_scope_is_per_parcel(self):
        a, b, _ = self.parcels
        body = self._body(
            "PL",
            [
                {"parcel": a.id, "plants_established": "1200", "applied_scope": "all"},
                {
                    "parcel": b.id,
                    "plants_established": "300",
                    "applied_scope": "part",
                    "applied_scope_detail": "rows 1-9",
                },
            ],
            plant_spacing="2",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        records = self._records(body)
        self.assertEqual(records[self.seasons[0].id].plants_established, 1200)
        self.assertEqual(records[self.seasons[1].id].applied_scope_detail, "rows 1-9")

    def test_pollination_hives_are_per_parcel(self):
        a, b, _ = self.parcels
        body = self._body("PO", [{"parcel": a.id, "hive_count": 8}, {"parcel": b.id, "hive_count": 3}])
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        hives = sorted((r.extra_data or {}).get("hive_count") for r in self._records(body).values())
        self.assertEqual(hives, [3, 8])

    def test_every_included_subtype_saves_on_two_parcels(self):
        a, b, _ = self.parcels
        for subtype in SPECS[1].subtypes:
            with self.subTest(subtype=subtype):
                body = self._body(
                    subtype, [{"parcel": a.id, "area_covered": "1"}, {"parcel": b.id, "area_covered": "2"}]
                )
                res = self._post(body)
                self.assertEqual(res.status_code, status.HTTP_201_CREATED, (subtype, res.content[:400]))
                self.assertEqual(len(self._records(body)), 2)

    def test_refused_shapes(self):
        a, b, _ = self.parcels
        two = [{"parcel": a.id}, {"parcel": b.id}]
        cases = {
            "harvest is single-parcel": (self._body("HA", two), "type"),
            "post-harvest is single-parcel": (self._body("PH", two), "type"),
            "equipment maintenance is single-parcel": (self._body("EM", two), "type"),
            "a season summary": (self._body("IR", two, is_summary="true"), "refused"),
            "a season total in extra_data": (
                self._body("IR", two, extra_data={"water_volume_total": "900"}),
                "refused",
            ),
            "a yield": (self._body("PR", two, yield_quantity="10"), "refused"),
            "area in the shared body": (self._body("MO", two, area_covered="3"), "shared"),
            "fuel inside shared extra_data": (self._body("MO", two, extra_data={"fuel_consumed": "3"}), "shared"),
            "depth in the shared body": (self._body("IR", two, irrigation_depth="1"), "shared"),
            "scope on transplanting (TR has none)": (
                self._body("TR", [{"parcel": a.id, "applied_scope": "all"}, {"parcel": b.id}]),
                "targets",
            ),
            "hives on mowing": (self._body("MO", [{"parcel": a.id, "hive_count": 2}, {"parcel": b.id}]), "targets"),
            "a setting in shared extra_data and per parcel": (
                self._body(
                    "FP",
                    [{"parcel": a.id, "low_temperature": "30"}, {"parcel": b.id}],
                    extra_data={"low_temperature": "31"},
                ),
                "either",
            ),
            "a yield inside shared extra_data": (self._body("PR", two, extra_data={"yield_quantity": "10"}), "refused"),
            "scope on irrigation, shared (only planting asks it)": (
                self._body("IR", two, applied_scope="part", applied_scope_detail="rows 1-9"),
                "shared",
            ),
            "a malformed subtype": (self._body("IR", two) | {"type": ["IR"]}, "type"),
            "a setting sent shared and per parcel": (
                self._body("FP", [{"parcel": a.id, "low_temperature": "30"}, {"parcel": b.id}], low_temperature="31"),
                "either",
            ),
        }
        for label, (body, key) in cases.items():
            with self.subTest(label):
                res = self._post(body)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (label, res.content[:300]))
                self.assertIn(key, res.json(), (label, res.content[:300]))
        self.assertFalse(ProductionEvent.objects.exists())

        # The control: an `either` setting sent once, shared, is accepted.
        res = self._post(self._body("FP", two, low_temperature="31"))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:300])

    def test_soil_amendment_fuel_and_hours_are_per_parcel_now(self):
        a, b, _ = self.parcels
        body = {
            "event_type": 5,
            "application_group": str(uuid.uuid4()),
            "date": timezone.now().replace(microsecond=0).isoformat(),
            "type": "OM",
            "amendment_type": "compost",
            "amendment_amount_unit": "tons",
            "targets": [
                {"parcel": a.id, "amendment_amount": "5", "area_covered": "4", "fuel_consumed": "3"},
                {"parcel": b.id, "amendment_amount": "2", "area_covered": "1"},
            ],
        }
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:400])
        fuel = {
            e.history_id: e.fuel_consumed
            for e in SoilManagementEvent.objects.filter(application_group=body["application_group"])
        }
        self.assertEqual(float(fuel[self.seasons[0].id]), 3.0)
        self.assertIsNone(fuel[self.seasons[1].id])


class SoilAndPestOnSeveralParcelsTests(_SeveralParcels):
    """Soil cover crop, tillage, habitat and nesting structures; pest releases and cultural control."""

    def _soil(self, subtype, targets, **shared):
        return {**self._body(subtype, targets, **shared), "event_type": 5}

    def _pest(self, subtype, targets, **shared):
        return {**self._body(subtype, targets, **shared), "event_type": 6}

    def _by_season(self, model, body):
        return {e.history_id: e for e in model.objects.filter(application_group=body["application_group"])}

    def test_tillage_fuel_and_hours_per_parcel_and_one_working_depth(self):
        a, b, _ = self.parcels
        body = self._soil(
            "TI",
            [{"parcel": a.id, "area_covered": "4", "fuel_consumed": "6"}, {"parcel": b.id, "area_covered": "2"}],
            working_depth="20",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:400])
        records = self._by_season(SoilManagementEvent, body)
        self.assertEqual(float(records[self.seasons[0].id].fuel_consumed), 6.0)
        self.assertIsNone(records[self.seasons[1].id].fuel_consumed)

    def test_every_included_soil_subtype_saves_on_two_parcels(self):
        a, b, _ = self.parcels
        for subtype in ("CC", "TI", "HD"):
            with self.subTest(subtype=subtype):
                body = self._soil(
                    subtype, [{"parcel": a.id, "area_covered": "1"}, {"parcel": b.id, "area_covered": "2"}]
                )
                res = self._post(body)
                self.assertEqual(res.status_code, status.HTTP_201_CREATED, (subtype, res.content[:400]))

    def test_nesting_structures_are_counted_per_parcel(self):
        a, b, _ = self.parcels
        body = self._soil(
            "NS",
            [{"parcel": a.id, "habitat_structure_count": 4}, {"parcel": b.id, "habitat_structure_count": 1}],
            habitat_type="owl_box",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:400])
        counts = sorted(e.habitat_structure_count for e in self._by_season(SoilManagementEvent, body).values())
        self.assertEqual(counts, [1, 4])

    def test_beneficial_release_quantity_per_parcel(self):
        a, b, _ = self.parcels
        body = self._pest(
            "BR",
            [{"parcel": a.id, "release_quantity": "5000"}, {"parcel": b.id, "release_quantity": "2000"}],
            name="Lacewing release",
            beneficial_species="Chrysoperla rufilabris",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:400])
        quantities = sorted(e.release_quantity for e in self._by_season(PestManagementEvent, body).values())
        self.assertEqual(quantities, ["2000", "5000"])

    def test_cultural_control_saves_on_two_parcels(self):
        a, b, _ = self.parcels
        body = self._pest(
            "CU",
            [{"parcel": a.id, "area_covered": "3"}, {"parcel": b.id, "area_covered": "1"}],
            name="Mummy removal",
            cultural_practice="mummy_removal",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:400])

    def test_soil_and_pest_refusals(self):
        a, b, _ = self.parcels
        two = [{"parcel": a.id}, {"parcel": b.id}]
        cases = {
            "scouting is single-parcel": (self._pest("SC", two, name="Scout"), "type"),
            "IPM implementation is single-parcel": (self._pest("IP", two, name="IPM"), "type"),
            "a trap count": (
                self._pest("CU", two, name="x", cultural_practice="mummy_removal", trap_count=4),
                "refused",
            ),
            "a release quantity in the shared body": (self._pest("BR", two, name="x", release_quantity="10"), "shared"),
            "grazing is single-parcel": (self._soil("GR", two), "type"),
            "a soil pH on a cover crop": (self._soil("CC", two, soil_ph="6.2"), "refused"),
            # The pest serializer takes these at the top level and moves them into extra_data
            # itself, so listing them for extra_data alone would let them through.
            "pest pressure at the top level": (
                self._pest("BR", two, name="x", average_pest_pressure="3"),
                "refused",
            ),
            "species observed at the top level": (
                self._pest("BR", two, name="x", pest_species_observed=["aphid"]),
                "refused",
            ),
            "a soil season summary": (self._soil("TI", two, date_start="2026-03-01"), "refused"),
            "working depth shared and per parcel": (
                self._soil("TI", [{"parcel": a.id, "working_depth": "10"}, {"parcel": b.id}], working_depth="20"),
                "either",
            ),
            "structure count on tillage": (
                self._soil("TI", [{"parcel": a.id, "habitat_structure_count": 2}, {"parcel": b.id}]),
                "targets",
            ),
        }
        for label, (body, key) in cases.items():
            with self.subTest(label):
                res = self._post(body)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (label, res.content[:300]))
                self.assertIn(key, res.json(), (label, res.content[:300]))


class GeneralOnSeveralParcelsTests(_SeveralParcels):
    """One incident or one general activity on several parcels: the area hit, per parcel."""

    def test_one_contamination_incident_on_two_parcels(self):
        a, b, _ = self.parcels
        body = {
            **self._body(
                None,
                [
                    {"parcel": a.id, "contamination_affected_area": "1.5", "block_id": "Rows 1-4"},
                    {"parcel": b.id, "contamination_affected_area": "0.5"},
                ],
                name="Neighbour drift",
                is_contamination_incident=True,
                contamination_source="spray_drift",
                corrective_action_taken="Buffer rows harvested separately and sold conventional.",
            ),
            "event_type": 3,
        }
        body.pop("type")
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        records = {e.history_id: e for e in GeneralEvent.objects.filter(application_group=body["application_group"])}
        ra, rb = records[self.seasons[0].id], records[self.seasons[1].id]
        self.assertEqual((float(ra.contamination_affected_area), ra.block_id), (1.5, "Rows 1-4"))
        self.assertEqual(float(rb.contamination_affected_area), 0.5)
        # Shared: the incident is one, with one cause and one corrective action.
        self.assertEqual({ra.contamination_source, rb.contamination_source}, {"spray_drift"})
        self.assertEqual(ra.corrective_action_taken, rb.corrective_action_taken)

    def test_an_affected_area_in_the_shared_body_is_refused(self):
        a, b, _ = self.parcels
        body = {
            **self._body(None, [{"parcel": a.id}, {"parcel": b.id}], name="x", contamination_affected_area="2"),
            "event_type": 3,
        }
        body.pop("type")
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:300])
        self.assertIn("shared", res.json())


class WeatherOnSeveralParcelsTests(_SeveralParcels):
    """One frost night over several parcels: one record per parcel, and no carbon on any."""

    def _weather(self, targets, **shared):
        body = {**self._body("FR", targets, **shared), "event_type": 0}
        return body

    def test_one_frost_on_two_parcels_shares_the_conditions(self):
        from carbon.models import CarbonEntry

        a, b, _ = self.parcels
        body = self._weather(
            [{"parcel": a.id}, {"parcel": b.id}],
            lower_temperature="-3",
            temperature_unit="C",
        )
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:500])
        records = {e.history_id: e for e in WeatherEvent.objects.filter(application_group=body["application_group"])}
        self.assertEqual(len(records), 2)
        self.assertEqual({r.type for r in records.values()}, {"FR"})
        ids = [r.id for r in records.values()]
        self.assertFalse(
            CarbonEntry.objects.filter(registry_verification_id__in=[f"REG-WeatherEvent-{i}" for i in ids]).exists()
        )

    def test_damage_is_never_copied_onto_every_parcel(self):
        # Damage and crop impact describe one place, and there is no per-parcel card to ask
        # them: refused here, recorded on each parcel's own record afterwards.
        a, b, _ = self.parcels
        res = self._post(
            self._weather([{"parcel": a.id}, {"parcel": b.id}], damage_assessment="Leaf burn on the low rows")
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:300])
        self.assertIn("refused", res.json())

    def test_a_section_on_weather_is_refused(self):
        a, b, _ = self.parcels
        res = self._post(self._weather([{"parcel": a.id}, {"parcel": b.id}], block_id="Rows 1-4"))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:300])
        self.assertIn("refused", res.json())
