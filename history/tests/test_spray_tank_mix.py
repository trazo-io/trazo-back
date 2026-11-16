"""Several products sprayed from one tank (overall review 2026-11, OV-RK-C04 / OV-FJ-C10).

WHAT WAS MISSING
----------------
A tank of Entrust, Kocide and a spreader-sticker could not be held as one application: the
products after the first went into `tank_mix_partners`, with no rate, REI, PHI, lot, invoice,
receipt or National List classification, and a spray over several blocks refused that block.
Three products on three blocks were nine records typed by hand, and nothing stored the tank.

WHAT THIS PINS
--------------
`products` x `targets` written in one request, all or none, one FULL record per product and per
target, tied by `tank_mix_group` (history/services/tank_mix.py): the record count and each record's
own amount, all-or-nothing on a bad line, an idempotent replay, the per-line `application_group`
(distinct per line, stable across a replay, never the tank), purchases and receipts per product,
one application pass per target and its hand-off when line 1 is deleted, the air-blast fuel
estimate, the National List per line, the packet's "one tank with", one PUR row per line with the
adjuvant's own, a sealed season's hash across the migration, and old `tank_mix_partners` records
printing as they did.
"""

import csv
import io
import re
import uuid
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from carbon.event_link import entries_for_event
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import VerifiedEmissionFactors
from certifications.models import NationalListSubstance
from company.models import Company
from history import seals
from history.amendments import AmendmentError, amendable_fields, apply_amendment
from history.constants import CHEMICAL_EVENT_TYPE
from history.models import ChemicalEvent, Production
from history.services import multi_target, tank_mix
from history.services.audit_export_service import AuditExportService, _purchase_rows
from history.services.pur_export_service import PURExportService
from history.services.record_receipts import receipt_files, shared_from
from product.models import Establishment, Parcel, Product
from users.models import WorksIn

WHEN = datetime(2026, 5, 2, 6, 30, tzinfo=dt_tz.utc)


def _flatten(elements) -> str:
    """Every string the flowables carry, cell by cell, the way the PDF prints them."""
    out = []
    for el in elements:
        text = getattr(el, "text", None)
        if isinstance(text, str):
            out.append(text)
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                t = getattr(cell, "text", None)
                out.append(t if isinstance(t, str) else str(cell))
    return re.sub(r"\s+", " ", " ".join(out))


def _parcel(establishment, name, area=4):
    parcel = Parcel.objects.create(name=name, establishment=establishment, area=area)
    history = Production.objects.create(
        parcel=parcel,
        name=f"{name} 2026",
        product=Product.objects.create(name="Apples"),
        start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
    )
    parcel.current_history = history
    parcel.save(update_fields=["current_history"])
    return parcel, history


def _three_products():
    return [
        {
            "tank_mix_role": "product",
            "commercial_name": "Entrust SC",
            "active_ingredient": "Spinosad",
            "epa_registration_number": "62719-621",
            "concentration": "22.5%",
            "volume_unit": "fl_oz",
            "application_rate": "6",
            "application_rate_unit": "fl_oz_ac",
            "rei_hours": "4",
            "phi_days": "7",
            "target_pest_disease": "Codling moth",
            "organic_approved": "omri_listed",
            "supplier_name": "Wilbur-Ellis",
            "purchase_invoice": "INV-1",
            "chemical_lot_number": "LOT-E1",
            "quantity_purchased": "64",
            "quantity_purchased_unit": "fl_oz",
        },
        {
            "tank_mix_role": "product",
            "type": "FU",
            "commercial_name": "Kocide 3000-O",
            "active_ingredient": "Copper hydroxide",
            "epa_registration_number": "91411-7",
            "concentration": "30%",
            "volume_unit": "lbs",
            "application_rate": "1.5",
            "application_rate_unit": "lb_ac",
            "rei_hours": "48",
            "phi_days": "0",
            "target_pest_disease": "Fire blight",
            "organic_approved": "omri_listed",
            "supplier_name": "Wilbur-Ellis",
            "purchase_invoice": "INV-2",
            "quantity_purchased": "25",
            "quantity_purchased_unit": "lbs",
        },
        {
            "tank_mix_role": "adjuvant",
            "commercial_name": "Dyne-Amic",
            "concentration_not_recorded": True,
            "volume_unit": "fl_oz",
            "supplier_name": "Helena",
            "purchase_invoice": "INV-3",
            "quantity_purchased": "32",
            "quantity_purchased_unit": "fl_oz",
        },
    ]


class _Orchard(APITestCase):
    """A fictional Washington orchard with three blocks, one open season each."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="tank-mix@example.com", password="pw-for-tests-only")
        cls.company = Company.objects.create(name="Fictional Bench Orchard")
        WorksIn.objects.create(user=cls.user, company=cls.company, role=WorksIn.COMPANY_ADMIN)
        cls.farm = Establishment.objects.create(name="Fictional Bench", company=cls.company, state="WA")
        cls.north, cls.north_season = _parcel(cls.farm, "North Block")
        cls.south, cls.south_season = _parcel(cls.farm, "South Block", area=6)
        cls.east, cls.east_season = _parcel(cls.farm, "East Block", area=3)

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _tank(self, targets, products=None, **shared):
        body = {
            "event_type": CHEMICAL_EVENT_TYPE,
            "tank_mix_group": str(uuid.uuid4()),
            "date": WHEN.isoformat(),
            "type": "PE",
            "application_method": "air_blast",
            "area_unit": "acres",
            "wind_from": "NW",
            "wind_speed_mph": "4",
            "products": products if products is not None else _three_products(),
            "targets": targets,
        }
        body.update(shared)
        return body

    def _three_targets(self):
        return [
            {
                "parcel": self.north.id,
                "area_treated": "4",
                "application_fuel_consumed": "3",
                "products": [{"volume_applied": "24"}, {"volume_applied": "6"}, {"volume_applied": "8"}],
            },
            {
                "parcel": self.south.id,
                "area_treated": "6",
                "application_fuel_consumed": "4.5",
                "products": [{"volume_applied": "36"}, {"volume_applied": "9"}, {"volume_applied": "12"}],
            },
            {
                "parcel": self.east.id,
                "area_treated": "3",
                "products": [{"volume_applied": "18"}, {"volume_applied": "4.5"}, {"volume_applied": "6"}],
            },
        ]

    def _one_target(self, products=None):
        products = products if products is not None else _three_products()
        for line, amount in zip(products, ("24", "6", "8")):
            line.setdefault("volume_applied", amount)
        return self._tank([{"parcel": self.north.id, "area_treated": "4"}], products=products)

    def _post(self, body):
        return self.client.post(reverse("events-list"), body, format="json")


class TankWriteTests(_Orchard):
    def test_three_products_on_three_blocks_are_nine_full_records(self):
        body = self._tank(self._three_targets())
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)

        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        self.assertEqual(records.count(), 9)
        amounts = {
            (self.north_season.id, 1): "24",
            (self.north_season.id, 2): "6",
            (self.north_season.id, 3): "8",
            (self.south_season.id, 1): "36",
            (self.south_season.id, 2): "9",
            (self.south_season.id, 3): "12",
            (self.east_season.id, 1): "18",
            (self.east_season.id, 2): "4.5",
            (self.east_season.id, 3): "6",
        }
        for record in records:
            expected = amounts[(record.history_id, record.tank_mix_line)]
            # Each product's own amount on each block, under both columns the documents read.
            self.assertEqual(record.volume, expected)
            self.assertEqual(record.volume_numeric, Decimal(expected))
            # Shared facts of the one pass are on every record.
            self.assertEqual(record.way_of_application, "air_blast")
            self.assertEqual(record.wind_from, "NW")
            self.assertEqual(record.date, WHEN)
            # Each product names its own target (OV-RK-C04 follow-up): never one pest for the tank.
            self.assertEqual(
                record.target_pest_disease, {1: "Codling moth", 2: "Fire blight", 3: None}[record.tank_mix_line]
            )
            # New entries never write the legacy partner list.
            self.assertEqual(record.tank_mix_partners, [])

        line_1 = records.filter(tank_mix_line=1)
        self.assertEqual(set(line_1.values_list("commercial_name", flat=True)), {"Entrust SC"})
        self.assertEqual(set(line_1.values_list("type", flat=True)), {"PE"})
        line_2 = records.filter(tank_mix_line=2)
        self.assertEqual(set(line_2.values_list("type", flat=True)), {"FU"})  # a line names its own type
        self.assertEqual(set(line_2.values_list("rei_hours", flat=True)), {Decimal("48")})
        line_3 = records.filter(tank_mix_line=3)
        self.assertEqual(set(line_3.values_list("tank_mix_role", flat=True)), {"adjuvant"})
        self.assertEqual(set(line_3.values_list("type", flat=True)), {"PE"})  # the shared type is the default
        self.assertTrue(all(r.concentration_not_recorded for r in line_3))
        self.assertEqual(set(records.exclude(tank_mix_line=3).values_list("tank_mix_role", flat=True)), {"product"})

        payload = res.json()
        self.assertEqual(payload["tank_mix_group"], body["tank_mix_group"])
        self.assertEqual(len(payload["records"]), 9)
        self.assertEqual(
            [(r["parcel"], r["tank_mix_line"]) for r in payload["records"][:3]],
            [(self.north.id, 1), (self.north.id, 2), (self.north.id, 3)],
        )

    def test_the_passs_fuel_goes_on_line_one_only(self):
        body = self._tank(self._three_targets(), application_fuel_type="diesel")
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        north_1 = records.get(history=self.north_season, tank_mix_line=1)
        self.assertEqual(north_1.application_fuel_consumed, Decimal("3"))
        self.assertEqual(north_1.application_fuel_type, "diesel")
        self.assertEqual(
            records.get(history=self.south_season, tank_mix_line=1).application_fuel_consumed, Decimal("4.5")
        )
        for record in records.exclude(tank_mix_line=1):
            self.assertIsNone(record.application_fuel_consumed, record.tank_mix_line)
            self.assertEqual(record.application_fuel_type, "", record.tank_mix_line)

    def test_each_target_can_carry_its_own_window_on_every_line(self):
        """One tank sprayed over several blocks, block after block: a target's start and stop go on
        every product line written for it, and a target without its own window gets none."""
        targets = self._three_targets()
        targets[0].update(
            application_start=WHEN.replace(hour=6).isoformat(), application_end=WHEN.replace(hour=7).isoformat()
        )
        targets[1].update(
            application_start=WHEN.replace(hour=7, minute=15).isoformat(),
            application_end=WHEN.replace(hour=9).isoformat(),
        )
        body = self._tank(targets)
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)

        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        self.assertEqual(records.count(), 9)
        by_season = {}
        for record in records:
            by_season.setdefault(record.history_id, set()).add((record.application_start, record.application_end))
        north, south, east = (by_season[s.id] for s in (self.north_season, self.south_season, self.east_season))
        self.assertEqual(len(north), 1)
        self.assertEqual(len(south), 1)
        self.assertEqual({(start.hour, end.hour) for start, end in north}, {(6, 7)})
        self.assertEqual({(start.minute, end.hour) for start, end in south}, {(15, 9)})
        self.assertEqual(east, {(None, None)})

    def test_one_parcel_tank_uses_the_same_path_with_one_target(self):
        body = self._one_target()
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"]).order_by("tank_mix_line")
        self.assertEqual([r.volume for r in records], ["24", "6", "8"])
        self.assertEqual({r.history_id for r in records}, {self.north_season.id})
        # One product on one parcel is not "one product over several parcels".
        self.assertEqual({r.application_group for r in records}, {None})
        # A carrier total for the tank is honest when the tank covered one parcel.
        body = self._one_target()
        body.update({"carrier_volume": "400", "carrier_volume_unit": "gal_total"})
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)

    def test_two_blocks_of_one_parcel_are_two_targets(self):
        targets = [
            {
                "parcel": self.north.id,
                "block_id": "Block 1",
                "area_treated": "2",
                "products": [{"volume_applied": "12"}, {"volume_applied": "3"}],
            },
            {
                "parcel": self.north.id,
                "block_id": "Block 2",
                "area_treated": "2",
                "products": [{"volume_applied": "12"}, {"volume_applied": "3"}],
            },
        ]
        body = self._tank(targets, products=_three_products()[:2])
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        self.assertEqual(
            sorted(records.values_list("block_id", "tank_mix_line")),
            [("Block 1", 1), ("Block 1", 2), ("Block 2", 1), ("Block 2", 2)],
        )

    def test_a_bad_line_writes_nothing(self):
        products = _three_products()
        products[1]["rei_hours"] = "-4"
        body = self._tank(self._three_targets(), products=products)
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        # The line's own fault, said once for the line rather than once per block.
        self.assertIn("rei_hours", res.json()["products"]["2"])
        self.assertFalse(ChemicalEvent.objects.exists())

    def test_one_closed_target_writes_nothing(self):
        finished = Production.objects.create(
            parcel=self.east,
            name="East 2025",
            start_date=datetime(2025, 3, 1, tzinfo=dt_tz.utc),
            finish_date=datetime(2026, 9, 1, tzinfo=dt_tz.utc),
        )
        targets = self._three_targets()
        targets[2]["history"] = finished.id
        res = self._post(self._tank(targets))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertFalse(ChemicalEvent.objects.exists())

    def test_a_replay_returns_the_records_already_written(self):
        body = self._tank(self._three_targets())
        first = self._post(body)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        again = self._post(body)
        self.assertEqual(again.status_code, status.HTTP_200_OK, again.content)
        self.assertEqual(ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"]).count(), 9)
        self.assertEqual(again.json()["records"], first.json()["records"])

    def test_a_tank_id_of_another_operation_is_refused(self):
        body = self._tank(self._three_targets())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        stranger = get_user_model().objects.create_user(email="stranger-tank@example.com", password="pw")
        company = Company.objects.create(name="Stranger Co")
        WorksIn.objects.create(user=stranger, company=company, role=WorksIn.COMPANY_ADMIN)
        farm = Establishment.objects.create(name="Elsewhere", company=company)
        parcel, _ = _parcel(farm, "Theirs")
        self.client.force_authenticate(user=stranger)
        theirs = self._tank([{"parcel": parcel.id, "area_treated": "1"}], tank_mix_group=body["tank_mix_group"])
        for line in theirs["products"]:
            line["volume_applied"] = "1"
        res = self._post(theirs)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn("tank_mix_group", res.json())
        self.assertFalse(ChemicalEvent.objects.filter(history__parcel=parcel).exists())

    def test_each_line_has_its_own_application_group_stable_across_a_replay(self):
        body = self._tank(self._three_targets())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        tank = uuid.UUID(body["tank_mix_group"])
        records = ChemicalEvent.objects.filter(tank_mix_group=tank)
        groups = {
            line: set(records.filter(tank_mix_line=line).values_list("application_group", flat=True))
            for line in (1, 2, 3)
        }
        for line, found in groups.items():
            # One product across the three blocks shares ONE group, derived from the tank and line.
            self.assertEqual(found, {tank_mix.line_application_group(tank, line)}, line)
        self.assertEqual(len({next(iter(g)) for g in groups.values()}), 3)  # never the same for two lines
        self.assertNotIn(tank, {next(iter(g)) for g in groups.values()})  # and never the tank itself
        self.assertEqual(self._post(body).status_code, status.HTTP_200_OK)
        self.assertEqual(
            {
                line: set(records.filter(tank_mix_line=line).values_list("application_group", flat=True))
                for line in (1, 2, 3)
            },
            groups,
        )

    def test_refused_shapes(self):
        """Each case is refused for ITS reason; nothing is written by any of them."""
        two = [
            {"parcel": self.north.id, "area_treated": "4", "products": [{"volume_applied": "1"}] * 3},
            {"parcel": self.south.id, "area_treated": "6", "products": [{"volume_applied": "1"}] * 3},
        ]

        def without(key, index=0):
            products = _three_products()
            products[index].pop(key)
            return products

        only_adjuvants = _three_products()
        for line in only_adjuvants:
            line["tank_mix_role"] = "adjuvant"
        cases = {
            "one product is not a tank": (self._tank(two, products=_three_products()[:1]), "products"),
            "not a list of products": (self._tank(two, products={"a": 1}), "products"),
            "missing role": (self._tank(two, products=without("tank_mix_role")), "products"),
            "only adjuvants": (self._tank(two, products=only_adjuvants), "products"),
            "legacy partners beside a tank": (self._tank(two, tank_mix_partners=[{"commercial_name": "x"}]), "refused"),
            "a client-sent application group": (self._tank(two, application_group=str(uuid.uuid4())), "refused"),
            "a product key in the shared body": (self._tank(two, commercial_name="Entrust SC"), "shared"),
            # A shared pest would print one product's target on every product of the tank.
            "a target pest in the shared body": (self._tank(two, target_pest_disease="Codling moth"), "shared"),
            "a target pest in the shared extra_data": (
                self._tank(two, extra_data={"target_pest_disease": "Codling moth"}),
                "shared",
            ),
            "an active ingredient in the shared extra_data": (
                self._tank(two, extra_data={"active_ingredient": "Spinosad"}),
                "shared",
            ),
            "fuel on a product line": (
                self._tank(two, products=[{**p, "application_fuel_consumed": "3"} for p in _three_products()]),
                "products",
            ),
            "an amount on the line with several targets": (
                self._tank(two, products=[{**p, "volume_applied": "3"} for p in _three_products()]),
                "products",
            ),
            "an amount straight in the target": (
                self._tank([{**t, "volume_applied": "3"} for t in two]),
                "targets",
            ),
            "amounts for the wrong number of lines": (
                self._tank([{**t, "products": [{"volume_applied": "1"}]} for t in two]),
                "targets",
            ),
            "the same parcel twice without blocks": (
                self._tank([two[0], {**two[0]}]),
                "targets",
            ),
            "a tank total over two parcels": (
                self._tank(two, carrier_volume="400", carrier_volume_unit="gal_total"),
                "refused",
            ),
            "missing tank id": (self._tank(two, tank_mix_group=""), "tank_mix_group"),
            "a plan item": (self._tank(two, plan_item_id=1), "plan_item_id"),
            "not a spray": (self._tank(two, event_type=1), "products"),
        }
        for label, (body, key) in cases.items():
            with self.subTest(label):
                res = self._post(body)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (label, res.content))
                self.assertIn(key, res.json(), (label, res.content))
        self.assertFalse(ChemicalEvent.objects.exists())

        # The control: the same base body with nothing wrong in it is accepted.
        self.assertEqual(self._post(self._tank(two)).status_code, status.HTTP_201_CREATED)

    def test_the_split_names_keys_the_serializer_takes(self):
        from history.serializers import UpdateChemicalEventSerializer

        fields = set(UpdateChemicalEventSerializer().fields) | {"active_ingredient"}
        for key in tank_mix.TANK.per_line | tank_mix.TANK.per_line_per_target | tank_mix.TANK.first_line_only:
            self.assertIn(key, fields, key)
        spec = multi_target.spec_for(CHEMICAL_EVENT_TYPE)
        self.assertTrue(tank_mix.TANK.per_line_per_target <= spec.per_target)
        self.assertFalse(tank_mix.TANK.per_line & spec.per_target_any())
        # What each product of a tank answers for itself, never once for the tank.
        for key in (
            "target_pest_disease",
            "application_purpose",
            "supplier_name",
            "purchase_date",
            "purchase_invoice",
            "receipt_document",
            "quantity_purchased",
            "quantity_purchased_unit",
            "chemical_lot_number",
        ):
            self.assertIn(key, tank_mix.TANK.per_line, key)
        self.assertNotIn("target_pest_disease", tank_mix.TANK.per_line_default_from_shared)


class EditTests(_Orchard):
    def _tank_records(self):
        body = self._one_target()
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        return {r.tank_mix_line: r for r in ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])}

    def test_the_detail_names_the_tanks_other_lines(self):
        records = self._tank_records()
        res = self.client.get(reverse("events-detail", args=[records[2].id]), {"event_type": 2})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        tank = res.json()["tank_mix"]
        self.assertEqual(tank["line"], 2)
        self.assertFalse(tank["carries_pass"])
        self.assertEqual(tank["pass_line"], 1)
        self.assertEqual(tank["pass_record"], records[1].id)
        self.assertEqual(
            [(line["line"], line["commercial_name"], line["role"]) for line in tank["lines"]],
            [(1, "Entrust SC", "product"), (3, "Dyne-Amic", "adjuvant")],
        )

    def test_a_single_products_detail_has_no_tank(self):
        record = ChemicalEvent.objects.create(
            history=self.north_season, type="PE", date=WHEN, commercial_name="Entrust SC"
        )
        res = self.client.get(reverse("events-detail", args=[record.id]), {"event_type": 2})
        self.assertIsNone(res.json()["tank_mix"])

    def test_each_line_is_edited_on_its_own_and_cannot_leave_its_tank(self):
        records = self._tank_records()
        res = self.client.patch(
            reverse("events-detail", args=[records[2].id]) + "?event_type=2",
            {"rei_hours": "24", "tank_mix_group": str(uuid.uuid4()), "tank_mix_line": 9, "tank_mix_role": "adjuvant"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        for line, record in records.items():
            record.refresh_from_db()
            self.assertEqual(record.tank_mix_line, line)
        self.assertEqual(records[2].rei_hours, Decimal("24"))
        self.assertEqual(records[2].tank_mix_role, "product")
        self.assertEqual(records[1].rei_hours, Decimal("4"))  # the other lines are untouched
        self.assertEqual(len({r.tank_mix_group for r in records.values()}), 1)
        for name in ("tank_mix_group", "tank_mix_line", "tank_mix_role"):
            self.assertNotIn(name, {f.name for f in amendable_fields(ChemicalEvent)}, name)

    def test_fuel_is_taken_only_on_the_line_that_carries_the_pass(self):
        records = self._tank_records()
        res = self.client.patch(
            reverse("events-detail", args=[records[2].id]) + "?event_type=2",
            {"application_fuel_consumed": "3"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:300])
        self.assertIn("line 1", str(res.json()["application_fuel_consumed"]))
        with self.assertRaises(AmendmentError):
            apply_amendment(
                event=records[3],
                event_type=CHEMICAL_EVENT_TYPE,
                field_name="application_fuel_consumed",
                new_value="3",
                reason="From the spray log.",
                user=self.user,
            )
        res = self.client.patch(
            reverse("events-detail", args=[records[1].id]) + "?event_type=2",
            {"application_fuel_consumed": "3"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])


class PurchaseAndReceiptTests(_Orchard):
    def test_each_products_purchase_is_its_own_line_counted_once_over_the_blocks(self):
        body = self._tank(self._three_targets())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        north = ChemicalEvent.objects.filter(history=self.north_season)
        rows, totals = _purchase_rows(north, [])
        lines = [row.first for row in rows]
        self.assertEqual(sorted(line.invoice for line in lines), ["INV-1", "INV-2", "INV-3"])
        for line in lines:
            self.assertEqual(line.also_on, ("East Block", "South Block"), line.invoice)
        # Across the whole tank each product's purchase is counted once, not once per block.
        rows, totals = _purchase_rows(ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"]), [])
        self.assertEqual(sorted(row.first.invoice for row in rows), ["INV-1", "INV-2", "INV-3"])

    def test_a_receipt_is_shared_across_one_products_blocks_never_across_products(self):
        from documents.models import GeneratedDocument

        body = self._tank(self._three_targets())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        doc = GeneratedDocument.objects.create(
            establishment=self.farm,
            source="upload",
            folder="uploads",
            title="Wilbur-Ellis invoice 1",
            file=ContentFile(b"receipt", name="inv-1.pdf"),
            content_type="application/pdf",
            size_bytes=7,
        )
        north_1 = records.get(history=self.north_season, tank_mix_line=1)
        ChemicalEvent.objects.filter(pk=north_1.pk).update(receipt_document=doc)
        south_1 = records.get(history=self.south_season, tank_mix_line=1)
        others = list(records.exclude(tank_mix_line=1))
        files = receipt_files([south_1, *others])
        self.assertEqual(files[(CHEMICAL_EVENT_TYPE, south_1.pk)], [doc])
        self.assertEqual(shared_from(files, south_1), ("North Block",))
        for other in others:
            self.assertNotIn((CHEMICAL_EVENT_TYPE, other.pk), files, other.tank_mix_line)


class NationalListTests(_Orchard):
    def test_every_line_is_classified_and_reports_its_own_owed_basis(self):
        spinosad = NationalListSubstance.objects.create(
            substance_name="Spinosad",
            substance_name_normalized="spinosad",
            cfr_section="205.601",
            subsection="e",
            category="insecticide",
            status="allowed",
        )
        copper = NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            subsection="i",
            category="fungicide",
            status="allowed",
        )
        products = _three_products()
        products[2]["organic_approved"] = "unverified"
        body = self._tank(self._three_targets(), products=products)
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        for record in records.filter(tank_mix_line=1):
            self.assertEqual(record.confirmed_national_list_substance, spinosad)
        for record in records.filter(tank_mix_line=2):
            self.assertEqual(record.confirmed_national_list_substance, copper)
        for record in records.filter(tank_mix_line=3):
            self.assertIsNone(record.confirmed_national_list_substance)
        # A basis still owed is reported on the line that owes it, and only there.
        gaps = {
            r["tank_mix_line"]: r["completeness_gaps"] for r in res.json()["records"] if r["parcel"] == self.north.id
        }
        self.assertIn("organic_approved", gaps[3])
        self.assertNotIn("organic_approved", gaps[1])
        self.assertNotIn("organic_approved", gaps[2])


class CarbonTests(_Orchard):
    def _entry(self, record):
        entries = list(entries_for_event(record, link=False))
        return entries[0].baseline_data if entries else None

    def test_one_application_pass_per_target_and_its_hand_off(self):
        body = self._one_target()
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        records = {r.tank_mix_line: r for r in ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])}

        line_1 = self._entry(records[1])
        self.assertGreater(line_1["application_emissions_kg_co2e"], 0)
        self.assertNotIn("application_pass_counted_on_line", line_1)
        line_2 = self._entry(records[2])
        self.assertEqual(line_2["application_emissions_kg_co2e"], 0)
        self.assertEqual(line_2["application_pass_counted_on_line"], 1)
        self.assertGreater(line_2["manufacturing_emissions_kg_co2e"], 0)  # its own product still counts
        # The adjuvant has no concentration and no pass: nothing to count, so no entry.
        self.assertIsNone(self._entry(records[3]))
        calculated = EventCarbonCalculator().calculate_chemical_event_impact(records[3])
        self.assertEqual(calculated["breakdown"]["application_pass_counted_on_line"], 1)

        pass_kg = line_1["application_emissions_kg_co2e"]
        records[1].delete()
        records[2].refresh_from_db()
        handed = self._entry(records[2])
        self.assertAlmostEqual(handed["application_emissions_kg_co2e"], pass_kg, places=3)
        self.assertNotIn("application_pass_counted_on_line", handed)
        calculated = EventCarbonCalculator().calculate_chemical_event_impact(records[3])
        self.assertEqual(calculated["breakdown"]["application_pass_counted_on_line"], 2)

    def test_each_block_counts_its_own_pass(self):
        body = self._tank(self._three_targets())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        for record in records:
            breakdown = EventCarbonCalculator().calculate_chemical_event_impact(record)["breakdown"]
            if record.tank_mix_line == 1:
                self.assertGreater(breakdown["application_emissions_kg_co2e"], 0, record.history_id)
            else:
                self.assertEqual(breakdown["application_emissions_kg_co2e"], 0, record.history_id)

    def test_a_line_moved_to_another_block_hands_its_pass_over(self):
        body = self._one_target()
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        records = {r.tank_mix_line: r for r in ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])}
        records[1].block_id = "Block 9"
        records[1].save()
        self.assertGreater(self._entry(records[2])["application_emissions_kg_co2e"], 0)
        self.assertGreater(self._entry(records[1])["application_emissions_kg_co2e"], 0)


class PassCarrierTests(_Orchard):
    """Review of back #408: the pass is counted once, on ONE record that can count it, and a
    measured fuel figure stays measured when that record leaves."""

    def _records(self, body):
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        return {r.tank_mix_line: r for r in ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])}

    def _breakdown(self, record):
        return EventCarbonCalculator().calculate_chemical_event_impact(record)["breakdown"]

    def _with_fuel(self):
        body = self._one_target()
        body["targets"][0]["application_fuel_consumed"] = "3"
        body["application_fuel_type"] = "diesel"
        body["application_fuel_unit"] = "gal"
        return self._records(body)

    # --- 1. the measured fuel follows the pass ---------------------------------------------------

    def test_deleting_the_carrier_hands_its_measured_fuel_to_the_next_line(self):
        records = self._with_fuel()
        measured = entries_for_event(records[1], link=False)[0].baseline_data
        self.assertAlmostEqual(measured["application_fuel_gallons"], 3.0, places=3)
        records[1].delete()
        records[2].refresh_from_db()
        self.assertEqual(records[2].application_fuel_consumed, Decimal("3"))
        self.assertEqual(records[2].application_fuel_type, "diesel")
        handed = entries_for_event(records[2], link=False)[0].baseline_data
        # Still the recorded 3 gallons, not an area estimate (4 L/ha over 4 acres is 1.71 gal).
        self.assertAlmostEqual(handed["application_fuel_gallons"], 3.0, places=3)
        self.assertAlmostEqual(
            handed["application_emissions_kg_co2e"], measured["application_emissions_kg_co2e"], places=3
        )
        self.assertEqual(self._breakdown(records[3])["application_pass_counted_on_line"], 2)

    def test_the_fuel_carrier_cannot_leave_its_block_before_the_other_products(self):
        records = self._with_fuel()
        url = reverse("events-detail", args=[records[1].id]) + "?event_type=2"
        res = self.client.patch(url, {"block_id": "Block 9"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:300])
        self.assertIn("Move them first", str(res.json()["block_id"]))
        with self.assertRaises(AmendmentError):
            apply_amendment(
                event=records[1],
                event_type=CHEMICAL_EVENT_TYPE,
                field_name="block_id",
                new_value="Block 9",
                reason="Wrong block.",
                user=self.user,
            )
        records[1].refresh_from_db()
        self.assertIsNone(records[1].block_id)
        # The other products move freely, and then the carrier moves last with its fuel.
        for line in (2, 3):
            other = reverse("events-detail", args=[records[line].id]) + "?event_type=2"
            self.assertEqual(self.client.patch(other, {"block_id": "Block 9"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"block_id": "Block 9"}, format="json").status_code, 200)
        moved = ChemicalEvent.objects.get(pk=records[1].pk)
        self.assertEqual((moved.block_id, moved.application_fuel_consumed), ("Block 9", Decimal("3")))
        self.assertEqual(
            self._breakdown(ChemicalEvent.objects.get(pk=records[2].pk))["application_pass_counted_on_line"], 1
        )

    # --- 2. the carrier is a record that can count the pass ------------------------------------

    def test_a_line_with_no_amount_carries_the_pass_from_its_area(self):
        # 2026-11-12: the pass is estimated from the area treated, never from the product's amount
        # (a blank amount used to read as 50), so line 1 keeps the pass with its amount blank.
        products = _three_products()
        for line, amount in zip(products, ("", "6", "8")):
            line["volume_applied"] = amount
        products[0].pop("volume_applied")
        records = self._records(self._tank([{"parcel": self.north.id, "area_treated": "4"}], products=products))
        line_1 = self._breakdown(records[1])
        self.assertNotIn("application_pass_counted_on_line", line_1)
        self.assertGreater(line_1["application_emissions_kg_co2e"], 0)
        self.assertEqual(line_1["application_pass_basis"], "estimated_application_fuel")
        self.assertEqual(line_1["manufacturing_emissions_kg_co2e"], 0)
        self.assertTrue(line_1["manufacturing_emissions_omitted"])
        self.assertEqual(self._breakdown(records[2])["application_pass_counted_on_line"], 1)
        self.assertEqual(self._breakdown(records[3])["application_pass_counted_on_line"], 1)

    def test_a_tank_with_no_amount_on_any_line_counts_its_pass_once(self):
        # Under the amount test this tank had no carrier, so every line counted the same pass.
        products = _three_products()
        records = self._records(self._tank([{"parcel": self.north.id, "area_treated": "4"}], products=products))
        counted = [self._breakdown(r)["application_emissions_kg_co2e"] for r in records.values()]
        self.assertEqual(sum(1 for kg in counted if kg > 0), 1, counted)
        self.assertGreater(self._breakdown(records[1])["application_emissions_kg_co2e"], 0)
        stored = [e for r in records.values() for e in entries_for_event(r, link=False)]
        self.assertEqual(len(stored), 1, "only the carrier has anything to store")

    def test_an_amount_of_zero_on_line_one_does_not_lose_the_pass(self):
        products = _three_products()
        for line, amount in zip(products, ("0", "6", "8")):
            line["volume_applied"] = amount
        records = self._records(self._tank([{"parcel": self.north.id, "area_treated": "4"}], products=products))
        # The pass is counted once, from the area treated, whatever line 1's amount says.
        counted = [self._breakdown(r).get("application_emissions_kg_co2e", 0) for r in records.values()]
        self.assertEqual(sum(1 for kg in counted if kg > 0), 1, counted)

    def test_when_no_line_can_count_the_pass_no_line_skips(self):
        # No fuel and no area on any line: there is no pass estimate to place, so no line skips
        # one, and none invents one either.
        records = {
            line: ChemicalEvent.objects.create(
                history=self.north_season,
                type="PE",
                date=WHEN,
                commercial_name=f"Product {line}",
                tank_mix_group=uuid.UUID("00000000-0000-4000-8000-000000000001"),
                tank_mix_line=line,
                tank_mix_role="product",
            )
            for line in (1, 2)
        }
        for record in records.values():
            breakdown = self._breakdown(record)
            self.assertNotIn("application_pass_counted_on_line", breakdown)
            self.assertEqual(breakdown["application_emissions_kg_co2e"], 0)
            self.assertEqual(breakdown["application_pass_basis"], "application_not_estimated")

    # --- 3. one record, even when two share a line number -----------------------------------------

    def test_two_records_with_one_line_number_count_the_pass_once(self):
        targets = [
            {
                "parcel": self.north.id,
                "block_id": "Block 1",
                "area_treated": "2",
                "products": [{"volume_applied": "12"}, {"volume_applied": "3"}],
            },
            {
                "parcel": self.north.id,
                "block_id": "Block 2",
                "area_treated": "2",
                "products": [{"volume_applied": "12"}, {"volume_applied": "3"}],
            },
        ]
        body = self._tank(targets, products=_three_products()[:2])
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        records = ChemicalEvent.objects.filter(tank_mix_group=body["tank_mix_group"])
        stray = records.get(block_id="Block 2", tank_mix_line=1)
        apply_amendment(
            event=stray,
            event_type=CHEMICAL_EVENT_TYPE,
            field_name="block_id",
            new_value="Block 1",
            reason="It went on Block 1.",
            user=self.user,
        )
        on_block_1 = list(records.filter(block_id="Block 1").order_by("pk"))
        self.assertEqual(sorted(r.tank_mix_line for r in on_block_1), [1, 1, 2])
        carrying = [r for r in on_block_1 if self._breakdown(r)["application_emissions_kg_co2e"] > 0]
        self.assertEqual(len(carrying), 1)
        self.assertEqual(carrying[0].pk, min(r.pk for r in on_block_1 if r.tank_mix_line == 1))
        detail = self.client.get(reverse("events-detail", args=[stray.id]), {"event_type": 2}).json()["tank_mix"]
        self.assertFalse(detail["carries_pass"])
        self.assertEqual(detail["pass_record"], carrying[0].pk)


class AirBlastFuelTests(SimpleTestCase):
    def _fuel_per_ha(self, method):
        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="PE",
            volume_liters=1.0,
            area_hectares=2.0,
            npk_content={"N": 0, "P": 0, "K": 0},
            application_method=method,
            concentration=22.5,
        )
        return result["breakdown"]["application_fuel_liters"] / 2.0

    def test_the_stored_air_blast_code_gets_the_orchard_estimate(self):
        self.assertAlmostEqual(self._fuel_per_ha("air_blast"), 4.0)
        self.assertAlmostEqual(self._fuel_per_ha("airblast"), 4.0)

    def test_the_stored_soil_incorporation_code_gets_the_incorporation_estimate(self):
        self.assertAlmostEqual(self._fuel_per_ha("soil_incorporation"), 3.0)
        self.assertAlmostEqual(self._fuel_per_ha("incorporation"), 3.0)

    def test_every_app_method_code_reaches_a_named_branch_or_is_listed_as_default(self):
        """Every spray method the app stores either has its own estimate or is known to fall to the
        2.0 L/ha default: a new code that silently lands on the default is the air_blast defect."""
        from common.field_registry import APPLICATION_METHOD

        default = {"ground_spray", "chemigation", "fumigation", "banding", "hand_dispenser"}
        for code, _label in APPLICATION_METHOD:
            with self.subTest(code):
                if code in default:
                    self.assertAlmostEqual(self._fuel_per_ha(code), 2.0)
                else:
                    self.assertNotAlmostEqual(self._fuel_per_ha(code), 2.0)


class PrintingTests(_Orchard):
    def _tank_on_north(self):
        body = self._one_target()
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)
        return body

    def test_the_packet_prints_a_row_per_line_and_says_which_shared_a_tank(self):
        self._tank_on_north()
        text = _flatten(AuditExportService(self.north_season, certification_type="organic")._build_chemical_log())
        for name in ("Entrust SC", "Kocide 3000-O", "Dyne-Amic"):
            self.assertIn(name, text)
        self.assertIn("Application Context", text)
        self.assertIn("Entrust SC (line 1 of 3. One tank with: Kocide 3000-O, Dyne-Amic (adjuvant))", text)
        self.assertIn("Dyne-Amic (line 3 of 3, adjuvant. One tank with: Entrust SC, Kocide 3000-O)", text)
        self.assertIn("Adjuvant", text)
        self.assertNotIn("Tank-mix partner", text)
        # Each row's Target column (Table 1) is its own product's pest.
        table = next(
            el._cellvalues
            for el in AuditExportService(self.north_season, certification_type="organic")._build_chemical_log()
            if any(
                getattr(c, "text", None) == "Target / Purpose" for c in (getattr(el, "_cellvalues", None) or [[]])[0]
            )
        )
        col = [getattr(c, "text", None) for c in table[0]].index("Target / Purpose")
        rows = {
            row[1].text: row[col].text
            for row in table[1:]
            if getattr(row[1], "text", None) in ("Entrust SC", "Kocide 3000-O")
        }
        self.assertEqual(rows, {"Entrust SC": "Codling moth", "Kocide 3000-O": "Fire blight"})

    def test_the_audit_csv_carries_the_tank_in_notes(self):
        body = self._tank_on_north()
        raw = AuditExportService(self.north_season, certification_type="organic").generate_csv().getvalue()
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        header = next(r for r in rows if "Notes" in r and "Product / Input" in r)
        notes_col, product_col, type_col = (
            header.index("Notes"),
            header.index("Product / Input"),
            header.index("Event Type"),
        )
        by_product = {r[product_col]: r for r in rows[rows.index(header) + 1 :] if len(r) > notes_col}
        self.assertIn(
            f"Tank {body['tank_mix_group']}, line 2 of 3. One tank with: Entrust SC",
            by_product["Kocide 3000-O"][notes_col],
        )
        self.assertEqual(by_product["Dyne-Amic"][type_col], "Adjuvant")
        self.assertNotIn("Tank", header)  # the header did not move

    def test_every_line_is_its_own_pur_row_adjuvant_included(self):
        self._tank_on_north()
        rows = PURExportService(self.farm, WHEN.month, WHEN.year).build_rows()
        by_product = {row["product_and_manufacturer"]: row for row in rows}
        self.assertEqual(set(by_product), {"Entrust SC", "Kocide 3000-O", "Dyne-Amic"})
        self.assertEqual(by_product["Dyne-Amic"]["total_product_used"], "8 fl oz")
        self.assertIn("Tank mix line 3 of 3, adjuvant", by_product["Dyne-Amic"]["notes"])
        self.assertEqual(by_product["Entrust SC"]["epa_registration_number"], "62719-621")
        # No phantom partner rows: the adjuvant is a record, not a partner of one.
        self.assertFalse(any(f["code"] == "adjuvant_line" for row in rows for f in row["flags"]))

    def test_an_old_partner_record_prints_as_it_did(self):
        ChemicalEvent.objects.create(
            history=self.north_season,
            type="PE",
            date=WHEN,
            commercial_name="Entrust SC",
            volume_numeric=Decimal("24"),
            volume_unit="fl_oz",
            area_numeric=Decimal("4"),
            area_unit="acres",
            way_of_application="air_blast",
            tank_mix_partners=[
                {
                    "commercial_name": "Dyne-Amic",
                    "manufacturer": "Helena",
                    "epa_registration_number": "",
                    "volume": "8",
                    "volume_unit": "fl_oz",
                    "organic_approved": True,
                }
            ],
        )
        text = _flatten(AuditExportService(self.north_season, certification_type="organic")._build_chemical_log())
        self.assertIn("Tank-mix partner: Dyne-Amic [mfr: Helena]", text)
        self.assertNotIn("One tank with", text)
        self.assertNotIn("Application Context", text)
        rows = PURExportService(self.farm, WHEN.month, WHEN.year).build_rows()
        self.assertEqual([row["product_and_manufacturer"] for row in rows], ["Entrust SC", "Dyne-Amic / Helena"])
        self.assertTrue(all("Tank mix line" not in row["notes"] for row in rows))


class SealAcrossTheMigrationTests(TransactionTestCase):
    """A season sealed before the tank columns existed still verifies after they arrive, and back.

    A seal hashes `id, index, date, description` per record (history/seals.py), so three nullable
    columns cannot move it; this proves it on the migration itself rather than by reading it.
    """

    BEFORE = "0261_chemical_event_state_application_facts"
    AFTER = "0262_chemical_event_tank_mix"

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _migrate(self, name):
        executor = MigrationExecutor(connection)
        executor.migrate([("history", name)])

    def test_a_sealed_season_verifies_on_both_sides_of_the_migration(self):
        company = Company.objects.create(name="Sealed Co")
        farm = Establishment.objects.create(name="Sealed Farm", company=company)
        parcel = Parcel.objects.create(name="Sealed Block", establishment=farm, area=2)
        season = Production.objects.create(
            parcel=parcel, name="Sealed 2025", start_date=datetime(2025, 3, 1, tzinfo=dt_tz.utc)
        )
        ChemicalEvent.objects.create(
            history=season, type="PE", date=WHEN, description="Entrust SC", commercial_name="Entrust SC", index=1
        )
        ChemicalEvent.objects.create(
            history=season, type="FU", date=WHEN, description="Kocide 3000-O", commercial_name="Kocide 3000-O", index=2
        )
        sealed = seals.seal(season)["finalization_hash"]

        self._migrate(self.BEFORE)
        self.assertEqual(seals.v2_hash(season)[0], sealed)
        self._migrate(self.AFTER)
        season.refresh_from_db()
        self.assertEqual(seals.verify(season).status, seals.INTACT)
        self.assertEqual(seals.v2_hash(season)[0], sealed)
        self.assertEqual(
            set(
                ChemicalEvent.objects.filter(history=season).values_list(
                    "tank_mix_group", "tank_mix_line", "tank_mix_role"
                )
            ),
            {(None, None, "")},
        )
