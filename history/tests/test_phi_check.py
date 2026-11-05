"""
A pick sooner after a spray than the pre-harvest interval (PHI) the operation recorded for it.

WHY (2026-11-05): the PHI was printed beside each spray, and compared with a pick only inside a sale
trace, for that one sale. Nothing compared a season's picks with its sprays when a record was saved
or on the season's readiness card. `history/services/phi_check.py` is that comparison; it shares its
predicate with the sale trace so the two cannot disagree.

Pinned here:
  * the boundary: a pick on day N of an N-day PHI is outside it; a same-day pick is inside;
  * only a recorded PHI above zero is compared; a pick on another block does not count when both
    records name one; a buffer-row pick counts; another production's pick does not;
  * the save response carries `phi_conflicts` for a spray or a pick, and no key for anything else;
  * the season's readiness row says REVIEW with the first conflict, PASS when sprays with a PHI have
    none, NA when no spray has one.
"""

from datetime import datetime, timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent
from history.services.phi_check import inside_phi, season_conflicts
from product.models import Parcel, Product
from users.models import User, WorksIn


class InsidePhiTests(SimpleTestCase):
    def test_the_boundary_and_the_absences(self):
        cases = [(0, 3, True), (2, 3, True), (3, 3, False), (10, 3, False), (2, None, False), (2, "", False)]
        cases += [(0, 0, False), (None, 3, False), (-1, 3, False), (2, "2.5", True), (3, "2.5", False)]
        for days, phi, expected in cases:
            with self.subTest(days=days, phi=phi):
                self.assertEqual(inside_phi(days, phi), expected)


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="PHI Orchards LLC")
        self.user = User.objects.create_user(email="phi@test.com", password="x", first_name="Ana")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="PHI Orchard", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="Upper Terrace", establishment=self.est, area=4.0)
        self.season = History.objects.create(
            parcel=self.parcel,
            product=Product.objects.create(name="Blueberries"),
            name="Blueberries 2026",
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
        )

    def _at(self, month, day):
        return timezone.make_aware(datetime(2026, month, day, 9))

    def _spray(self, day, phi, block="", name="Entrust SC", season=None):
        return ChemicalEvent.objects.create(
            history=season or self.season,
            description="spray",
            date=self._at(7, day),
            commercial_name=name,
            block_id=block,
            phi_days=phi,
        )

    def _pick(self, day, kind="HA", block="", season=None):
        return ProductionEvent.objects.create(
            history=season or self.season, description="pick", date=self._at(7, day), type=kind, block_id=block
        )


class SeasonConflictTests(_Farm):
    def test_a_pick_inside_the_phi_is_found_and_one_on_the_last_day_is_not(self):
        spray = self._spray(10, 3)
        inside, boundary = self._pick(12), self._pick(13)
        found = season_conflicts(self.season)
        self.assertEqual([(c.application_id, c.pick_id, c.days) for c in found], [(spray.pk, inside.pk, 2)])
        self.assertNotIn(boundary.pk, [c.pick_id for c in found])
        self.assertEqual(
            found[0].as_dict(),
            {
                "application_id": spray.pk,
                "pick_id": inside.pk,
                "product": "Entrust SC",
                "applied": "2026-07-10",
                "phi_days": "3",
                "picked": "2026-07-12",
                "days": 2,
            },
        )

    def test_nothing_to_compare_is_never_a_conflict(self):
        self._spray(10, None, name="No PHI recorded")
        self._spray(10, 0, name="Zero PHI")
        self._pick(10)
        self.assertEqual(season_conflicts(self.season), [])

    def test_another_block_does_not_count_and_a_buffer_pick_does(self):
        self._spray(10, 7, block="UT")
        self._pick(12, block="RB")
        buffer_pick = self._pick(14, kind="BU", block="UT")
        unnamed_block = self._pick(15)
        self.assertEqual({c.pick_id for c in season_conflicts(self.season)}, {buffer_pick.pk, unnamed_block.pk})

    def test_another_productions_pick_does_not_count(self):
        other = History.objects.create(
            parcel=self.parcel, product=self.season.product, name="Second planting", start_date=self._at(3, 1)
        )
        self._spray(10, 7)
        self._pick(12, season=other)
        self.assertEqual(season_conflicts(self.season), [])


class SaveResponseTests(_Farm):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, event_type, **fields):
        payload = {"event_type": event_type, "history": self.season.id, "parcels": [self.parcel.id]}
        payload.update(fields)
        return self.client.post("/api/events/", payload, format="json")

    def test_a_pick_saved_inside_a_phi_says_which_spray(self):
        spray = self._spray(10, 3)
        res = self._post(1, type="HA", date=self._at(7, 12).isoformat(), description="First pick")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn("phi_conflicts", res.data, "a pick's save response must say whether it is inside a PHI")
        self.assertEqual(
            [(c["application_id"], c["days"], c["phi_days"]) for c in res.data["phi_conflicts"]],
            [(spray.pk, 2, "3")],
        )

    def test_a_pick_outside_every_phi_says_so_with_an_empty_list(self):
        self._spray(10, 3)
        res = self._post(1, type="HA", date=self._at(7, 20).isoformat(), description="Later pick")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data.get("phi_conflicts"), [], "an empty list says the pick was checked")

    def test_a_record_that_is_neither_a_spray_nor_a_pick_carries_no_key(self):
        res = self._post(1, type="TP", date=self._at(7, 12).isoformat(), description="Load", transportation_distance=10)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertNotIn("phi_conflicts", res.data)


class ReadinessRowTests(_Farm):
    def _row(self):
        from history.services.audit_export_service import AuditExportService

        rows = AuditExportService(self.season, certification_type="organic").compliance_snapshot_rows()
        return next(r for r in rows if r["row_key"] == "pre_harvest_intervals")

    def test_no_spray_with_a_phi_is_not_applicable(self):
        self._spray(10, None)
        self.assertEqual(self._row()["status"], "NA")

    def test_sprays_with_a_phi_and_no_early_pick_pass(self):
        self._spray(10, 3)
        self._pick(20)
        self.assertEqual(self._row()["status"], "PASS")

    def test_an_early_pick_is_review_with_the_first_conflict_as_data(self):
        self._spray(10, 3)
        self._pick(11)
        self._pick(12)
        row = self._row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertEqual(row["row_key"], "pre_harvest_intervals")
        self.assertEqual(row["detail_code"], "pre_harvest_intervals.inside")
        self.assertEqual(
            row["params"],
            {
                "count": 2,
                "product": "Entrust SC",
                "applied": "2026-07-10",
                "picked": "2026-07-11",
                "days": 1,
                "phi": "3",
            },
        )
        self.assertEqual(row["section_hint"], "Input Material Application Records section")
