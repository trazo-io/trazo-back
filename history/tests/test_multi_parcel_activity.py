"""One activity logged on several parcels at once (`targets`, history/services/multi_target.py).

A grower sprays one tank mix over three blocks. The server writes ONE RECORD PER PARCEL, linked by
`application_group`, all or none. What these tests pin is that each record carries its OWN amount
and place, under every column a document reads: before this path existed, the create loop copied
one `validated_data` onto every parcel, so a three-block spray printed the whole tank on each
block, and the CA PUR export (which reads the legacy `volume` string first) and the packet (which
reads `volume_numeric`) could disagree about the same record.
"""

import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from history.models import ChemicalEvent, History, SoilManagementEvent
from history.services.audit_export_service import _purchase_rows
from history.services.multi_target import MAX_TARGETS
from history.services.pur_export_service import PURExportService
from product.models import Establishment, Parcel
from product.serializers import ParcelBasicSerializer, with_open_season_count
from subscriptions.storage_accounting import ESTIMATED_IMAGE_SIZE, media_storage_bytes
from users.models import WorksIn


def _parcel(establishment, name, season=True):
    parcel = Parcel.objects.create(name=name, establishment=establishment, area=5)
    history = None
    if season:
        history = History.objects.create(parcel=parcel, name=f"{name} 2026", start_date=timezone.now())
        parcel.current_history = history
        parcel.save(update_fields=["current_history"])
    return parcel, history


class MultiParcelActivityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="grower-mp@example.com", password="pw-for-tests-only")
        cls.company = Company.objects.create(name="Orchard Co")
        cls.user.companies.add(cls.company)
        # The nested /companies/<pk>/establishments/<pk>/events/ route writes only for a Company
        # Admin or Farm Manager (`ReadOnlyForViewers`); the flat route checks tenancy alone.
        WorksIn.objects.filter(user=cls.user, company=cls.company).update(role=WorksIn.COMPANY_ADMIN)
        cls.farm = Establishment.objects.create(name="North Farm", company=cls.company)
        cls.block_a, cls.season_a = _parcel(cls.farm, "Block A")
        cls.block_b, cls.season_b = _parcel(cls.farm, "Block B")
        cls.block_c, cls.season_c = _parcel(cls.farm, "Block C")

        other_farm = Establishment.objects.create(name="South Farm", company=cls.company)
        cls.other_farm_block, _ = _parcel(other_farm, "South Block")

        stranger = get_user_model().objects.create_user(email="stranger-mp@example.com", password="pw-for-tests-only")
        stranger_company = Company.objects.create(name="Stranger Co")
        stranger.companies.add(stranger_company)
        stranger_farm = Establishment.objects.create(name="Stranger Farm", company=stranger_company)
        cls.foreign_block, _ = _parcel(stranger_farm, "Foreign Block")
        cls.foreign_block_2, _ = _parcel(stranger_farm, "Foreign Block 2")

    def setUp(self):
        self.client.force_authenticate(user=self.user)
        self.when = timezone.now().replace(day=10, hour=9, minute=0, second=0, microsecond=0)

    def _spray(self, targets, **extra):
        body = {
            "event_type": 2,
            "application_group": str(uuid.uuid4()),
            "date": self.when.isoformat(),
            "type": "FU",
            "commercial_name": "Kocide 3000-O",
            "application_rate": "2",
            "application_rate_unit": "gal_ac",
            "volume_unit": "gal",
            "area_unit": "acres",
            "quantity_purchased": "48",
            "quantity_purchased_unit": "gal",
            "targets": targets,
        }
        body.update(extra)
        return body

    def _three_blocks(self):
        return [
            {"parcel": self.block_a.id, "area_treated": "12.4", "volume_applied": "24.8"},
            {"parcel": self.block_b.id, "area_treated": "6", "volume_applied": "12"},
            {
                "parcel": self.block_c.id,
                "area_treated": "3.5",
                "volume_applied": "7",
                "applied_scope_detail": "rows 1-9",
            },
        ]

    def _post(self, body):
        return self.client.post(reverse("events-list"), body, format="json")

    # --- the write ---------------------------------------------------------------------------

    def test_one_record_per_parcel_each_with_its_own_amount_under_every_column(self):
        body = self._spray(self._three_blocks())
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)

        records = ChemicalEvent.objects.filter(application_group=body["application_group"]).order_by("id")
        self.assertEqual(records.count(), 3)
        expected = {
            self.season_a.id: ("24.8", "12.4"),
            self.season_b.id: ("12", "6"),
            self.season_c.id: ("7", "3.5"),
        }
        for record in records:
            volume, area = expected[record.history_id]
            # The legacy string AND the numeric twin: PUR reads the first, the packet the second.
            self.assertEqual(record.volume, volume)
            self.assertEqual(float(record.volume_numeric), float(volume))
            self.assertEqual(record.area, area)
            self.assertEqual(float(record.area_numeric), float(area))
            self.assertEqual(record.commercial_name, "Kocide 3000-O")
            self.assertEqual(record.created_by, self.user)
        self.assertEqual(records.get(history=self.season_c).applied_scope_detail, "rows 1-9")
        self.assertFalse(records.get(history=self.season_a).applied_scope_detail)

        payload = res.json()
        self.assertEqual(payload["application_group"], body["application_group"])
        self.assertEqual([r["parcel"] for r in payload["records"]], [self.block_a.id, self.block_b.id, self.block_c.id])
        self.assertEqual(payload["id"], payload["records"][0]["id"])

    def test_pur_export_prints_each_blocks_own_amount(self):
        body = self._spray(self._three_blocks())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)

        rows = PURExportService(self.farm, self.when.month, self.when.year).build_rows()
        by_parcel = {row["parcel_id"]: row["total_product_used"] for row in rows}
        self.assertEqual(by_parcel[self.block_a.id], "24.8 gal")
        self.assertEqual(by_parcel[self.block_b.id], "12 gal")
        self.assertEqual(by_parcel[self.block_c.id], "7 gal")

    def test_one_purchase_spread_over_three_blocks_is_counted_once(self):
        body = self._spray(self._three_blocks())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)

        rows, totals = _purchase_rows(ChemicalEvent.objects.filter(application_group=body["application_group"]), [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(totals["gal"]["counted"], 48.0)

    def test_a_retry_with_the_same_group_returns_the_records_already_written(self):
        body = self._spray(self._three_blocks())
        first = self._post(body)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        again = self._post(body)
        self.assertEqual(again.status_code, status.HTTP_200_OK, again.content)
        self.assertEqual(ChemicalEvent.objects.filter(application_group=body["application_group"]).count(), 3)
        self.assertEqual(again.json()["records"], first.json()["records"])

    def test_a_group_written_by_another_operation_is_refused(self):
        body = self._spray(self._three_blocks())
        self.assertEqual(self._post(body).status_code, status.HTTP_201_CREATED)

        stranger = get_user_model().objects.get(email="stranger-mp@example.com")
        self.client.force_authenticate(user=stranger)
        # The stranger's own two parcels: a valid request in every respect but the group, so the
        # group is the only thing that can refuse it.
        res = self._post(
            self._spray(
                [{"parcel": self.foreign_block.id}, {"parcel": self.foreign_block_2.id}],
                application_group=body["application_group"],
            )
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertEqual(list(res.json()), ["application_group"])
        self.assertEqual(ChemicalEvent.objects.count(), 3)

    # --- all or nothing ----------------------------------------------------------------------

    def test_one_refused_target_writes_nothing(self):
        # Block B's season closed before the spray date: the record would backdate a closed season.
        self.season_b.finish_date = self.when + timedelta(days=1)
        self.season_b.save(update_fields=["finish_date"])
        targets = self._three_blocks()
        targets[1]["history"] = self.season_b.id

        res = self._post(self._spray(targets))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn(str(self.block_b.id), res.json()["targets"])
        self.assertFalse(ChemicalEvent.objects.exists())

    def test_post_harvest_work_on_a_finished_season_is_accepted_by_name(self):
        self.season_b.finish_date = self.when - timedelta(days=5)
        self.season_b.save(update_fields=["finish_date"])
        targets = self._three_blocks()
        targets[1]["history"] = self.season_b.id

        res = self._post(self._spray(targets))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertTrue(ChemicalEvent.objects.filter(history=self.season_b).exists())

    def test_a_parcel_with_no_open_season_is_refused_not_skipped(self):
        bare, _ = _parcel(self.farm, "Bare Block", season=False)
        res = self._post(self._spray([{"parcel": self.block_a.id}, {"parcel": bare.id}]))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(str(bare.id), res.json()["targets"])
        self.assertFalse(ChemicalEvent.objects.exists())

    def test_two_open_seasons_need_the_season_named(self):
        second = History.objects.create(parcel=self.block_b, name="Block B 2027", start_date=timezone.now())
        targets = [{"parcel": self.block_a.id}, {"parcel": self.block_b.id}]
        res = self._post(self._spray(targets))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(str(self.block_b.id), res.json()["targets"])

        targets[1]["history"] = second.id
        res = self._post(self._spray(targets))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertTrue(ChemicalEvent.objects.filter(history=second).exists())

    def test_a_season_of_another_parcel_is_refused(self):
        targets = [{"parcel": self.block_a.id, "history": self.season_b.id}, {"parcel": self.block_b.id}]
        res = self._post(self._spray(targets))
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(list(res.json()["targets"]), [str(self.block_a.id)])
        self.assertFalse(ChemicalEvent.objects.exists())

    # --- refused shapes: 400 before anything is read or written ------------------------------

    def test_refused_shapes(self):
        """Each case is refused for ITS reason: the error key is asserted, not just the 400, so a
        case that broke for an unrelated reason (a missing required field) cannot pass here."""
        two = [{"parcel": self.block_a.id}, {"parcel": self.block_b.id}]
        cases = {
            "one target": (self._spray([{"parcel": self.block_a.id}]), "targets"),
            "too many targets": (self._spray([{"parcel": i} for i in range(1, MAX_TARGETS + 2)]), "targets"),
            "duplicate parcel": (self._spray([{"parcel": self.block_a.id}, {"parcel": self.block_a.id}]), "targets"),
            "boolean parcel id": (self._spray([{"parcel": True}, {"parcel": self.block_b.id}]), "targets"),
            "fractional parcel id": (self._spray([{"parcel": 1.9}, {"parcel": self.block_b.id}]), "targets"),
            "parcels beside targets": (self._spray(two, parcels=[self.block_a.id]), "parcels"),
            "history beside targets": (self._spray(two, history=self.season_a.id), "history"),
            "plan item": (self._spray(two, plan_item_id=1), "plan_item_id"),
            "crew note": (self._spray(two, field_note=str(uuid.uuid4())), "field_note"),
            "amount in the shared body": (self._spray(two, volume_applied="40"), "shared"),
            "numeric amount in the shared body": (self._spray(two, area_numeric="10"), "shared"),
            "block in the shared body": (self._spray(two, block_id="4"), "shared"),
            "tank-mix partner volumes": (
                self._spray(two, tank_mix_partners=[{"product": "x", "volume": "2"}]),
                "refused",
            ),
            "season summary total": (self._spray(two, extra_data={"volume_applied_total": "300"}), "refused"),
            "fuel": (self._spray(two, application_fuel_consumed="3"), "refused"),
            "unknown key in a target": (
                self._spray([{"parcel": self.block_a.id, "commercial_name": "other"}, {"parcel": self.block_b.id}]),
                "targets",
            ),
            "parcel on another farm": (
                self._spray([{"parcel": self.block_a.id}, {"parcel": self.other_farm_block.id}]),
                "targets",
            ),
            "foreign parcel": (
                self._spray([{"parcel": self.block_a.id}, {"parcel": self.foreign_block.id}]),
                "parcels",
            ),
            "weather is single-parcel": (self._spray(two, event_type=0), "targets"),
            "missing group": (self._spray(two, application_group=""), "application_group"),
        }
        for label, (body, key) in cases.items():
            with self.subTest(label):
                res = self._post(body)
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (label, res.content))
                self.assertIn(key, res.json(), (label, res.content))
        self.assertFalse(ChemicalEvent.objects.exists())

        # The control: the same base body with nothing wrong in it is accepted.
        self.assertEqual(self._post(self._spray(two)).status_code, status.HTTP_201_CREATED)

    def test_a_farm_in_the_url_must_be_the_farm_of_every_parcel(self):
        url = reverse(
            "establishment-events-list",
            kwargs={"company_pk": self.company.pk, "establishment_pk": self.other_farm_block.establishment_id},
        )
        res = self.client.post(url, self._spray(self._three_blocks()), format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn("targets", res.json())
        self.assertFalse(ChemicalEvent.objects.exists())

        url = reverse(
            "establishment-events-list", kwargs={"company_pk": self.company.pk, "establishment_pk": self.farm.pk}
        )
        self.assertEqual(
            self.client.post(url, self._spray(self._three_blocks()), format="json").status_code,
            status.HTTP_201_CREATED,
        )

    def test_a_foreign_parcel_gets_the_same_body_as_a_missing_one(self):
        missing = self._post(self._spray([{"parcel": self.block_a.id}, {"parcel": 987654}]))
        foreign = self._post(self._spray([{"parcel": self.block_a.id}, {"parcel": self.foreign_block.id}]))
        self.assertEqual(missing.status_code, foreign.status_code)
        self.assertEqual(missing.json(), foreign.json())

    # --- soil amendment ------------------------------------------------------------------------

    def test_soil_amendment_spread_over_two_blocks(self):
        body = {
            "event_type": 5,
            "application_group": str(uuid.uuid4()),
            "date": self.when.isoformat(),
            "type": "PA",
            "amendment_type": "lime",
            "amendment_amount_unit": "tons",
            "targets": [
                {"parcel": self.block_a.id, "amendment_amount": "4", "area_covered": "2"},
                {"parcel": self.block_b.id, "amendment_amount": "6", "area_covered": "3"},
            ],
        }
        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        amounts = {
            e.history_id: (e.amendment_amount, float(e.amendment_amount_numeric))
            for e in SoilManagementEvent.objects.filter(application_group=body["application_group"])
        }
        self.assertEqual(amounts, {self.season_a.id: ("4", 4.0), self.season_b.id: ("6", 6.0)})

    def test_a_soil_reading_is_never_copied_onto_every_parcel(self):
        """The PA/OM form offers the pH and organic matter behind the amendment. In a multi-parcel
        save that one reading would be written onto every parcel's record as if each was tested."""
        base = {
            "event_type": 5,
            "date": self.when.isoformat(),
            "type": "PA",
            "amendment_type": "lime",
            "amendment_amount_unit": "tons",
            "targets": [
                {"parcel": self.block_a.id, "amendment_amount": "4", "area_covered": "2"},
                {"parcel": self.block_b.id, "amendment_amount": "6", "area_covered": "3"},
            ],
        }
        cases = {
            "soil_ph": {"soil_ph": "5.4"},
            "organic_matter_percentage": {"organic_matter_percentage": "2.1"},
            "test_results": {"test_results": "pH 5.4, OM 2.1"},
            "soil_ph inside extra_data": {"extra_data": {"soil_ph": "5.4"}},
        }
        for label, extra in cases.items():
            with self.subTest(label):
                res = self._post({**base, "application_group": str(uuid.uuid4()), **extra})
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, (label, res.content))
                self.assertIn("refused", res.json(), (label, res.content))
        self.assertFalse(SoilManagementEvent.objects.exists())

        # A blank reading (what the form posts when nobody typed one) is not a reading: accepted.
        res = self._post({**base, "application_group": str(uuid.uuid4()), "soil_ph": "", "test_results": ""})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)

    def test_soil_tests_stay_single_parcel(self):
        body = {
            "event_type": 5,
            "application_group": str(uuid.uuid4()),
            "date": self.when.isoformat(),
            "type": "ST",
            "targets": [{"parcel": self.block_a.id}, {"parcel": self.block_b.id}],
        }
        self.assertEqual(self._post(body).status_code, status.HTTP_400_BAD_REQUEST)

    # --- photos --------------------------------------------------------------------------------

    def test_photos_are_checked_once_copied_per_record_and_counted_once(self):
        urls = ["http://localhost/media/p1.jpg", "http://localhost/media/p2.jpg"]
        with mock.patch("requests.get", side_effect=OSError("offline")) as fetch:
            res = self._post(self._spray(self._three_blocks(), album_images=urls))
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertEqual(fetch.call_count, 2)

        albums = {e.album_id for e in ChemicalEvent.objects.all()}
        self.assertEqual(len(albums), 3)
        for event in ChemicalEvent.objects.all():
            self.assertEqual(sorted(i.image_url for i in event.album.images.all()), urls)
        self.assertEqual(media_storage_bytes(self.company), 2 * ESTIMATED_IMAGE_SIZE)

    # --- the group is not editable -------------------------------------------------------------

    def test_a_correction_cannot_move_a_record_out_of_its_group(self):
        body = self._spray(self._three_blocks())
        res = self._post(body)
        record_id = res.json()["records"][0]["id"]

        patched = self.client.patch(
            reverse("events-detail", args=[record_id]) + "?event_type=2",
            {"application_group": str(uuid.uuid4())},
            format="json",
        )
        self.assertIn(patched.status_code, (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST, status.HTTP_423_LOCKED))
        self.assertEqual(str(ChemicalEvent.objects.get(id=record_id).application_group), body["application_group"])

    def test_a_parcels_list_of_two_is_refused_and_points_to_targets(self):
        body = self._spray([])
        body.pop("targets")
        body.pop("application_group")
        body.update({"parcels": [self.block_a.id, self.block_b.id], "volume_applied": "24.8"})

        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("targets", res.json()["parcels"][0])
        self.assertFalse(ChemicalEvent.objects.exists())

    # --- the single-parcel path is unchanged ---------------------------------------------------

    def test_single_parcel_save_is_unchanged(self):
        body = self._spray([])
        body.pop("targets")
        body.pop("application_group")
        body.update({"parcels": [self.block_a.id], "volume_applied": "24.8", "area_treated": "12.4"})

        res = self._post(body)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertNotIn("records", res.json())
        record = ChemicalEvent.objects.get()
        self.assertIsNone(record.application_group)
        self.assertEqual(record.volume, "24.8")


class OpenSeasonCountTests(APITestCase):
    def test_counts_open_seasons_and_says_unknown_when_not_annotated(self):
        company = Company.objects.create(name="Count Co")
        farm = Establishment.objects.create(name="Count Farm", company=company)
        one, _ = _parcel(farm, "One")
        two, _ = _parcel(farm, "Two")
        History.objects.create(parcel=two, name="Two 2027", start_date=timezone.now())
        closed, history = _parcel(farm, "Closed")
        history.finish_date = timezone.now()
        history.save(update_fields=["finish_date"])

        served = {
            row["id"]: row["open_season_count"]
            for row in ParcelBasicSerializer(with_open_season_count(farm.parcels.all()), many=True).data
        }
        self.assertEqual(served, {one.id: 1, two.id: 2, closed.id: 0})
        self.assertIsNone(ParcelBasicSerializer(one).data["open_season_count"])
