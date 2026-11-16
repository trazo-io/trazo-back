"""A finished production is a closed record (2026-08-18).

Events on a finished production were hard-locked (423/403), but the lot header they
describe travelled through the ordinary PATCH with no guard at all. Measured before the
fix: `PATCH /histories/<id>/` rewrote lot_id, production_amount, quality_grade,
harvest_method and finish_date on a finished, published season and returned 200.

That is backwards. `lot_id` and `production_amount` are the traceability spine
7 CFR 205.103(b)(2) asks to be auditable "back to the last certified operation"; the
spray records underneath them were the part already protected.

`finish_date` mattered twice over: it was a working undocumented re-open (clearing it
released every event lock), and `retention_until` is computed only inside
History.finish(), so moving it desynchronised the 5-year floor.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company
from history.models import Production
from history.serializers import HistoryWriteSerializer
from product.models import Establishment, Parcel


class ClosedRecordGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = Company.objects.create(name="Guard Co")
        est = Establishment.objects.create(name="Guard Farm", company=company)
        cls.parcel = Parcel.objects.create(name="Guard Parcel", establishment=est, area=1)

    def _history(self, finished):
        h = Production.objects.create(
            parcel=self.parcel,
            name="Season",
            lot_id="LOT-ORIGINAL",
            production_amount=100,
            start_date=timezone.now() - timedelta(days=200),
        )
        if finished:
            h.finish_date = timezone.now() - timedelta(days=1)
            h.save()
        return h

    def _errors(self, history, payload):
        s = HistoryWriteSerializer(instance=history, data=payload, partial=True)
        return {} if s.is_valid() else s.errors

    # --- open productions stay fully editable -------------------------------

    def test_open_production_lot_header_is_editable(self):
        """The guard must not freeze a season that is still running."""
        errors = self._errors(self._history(finished=False), {"lot_id": "LOT-CORRECTED"})
        self.assertEqual(errors, {})

    def test_open_production_may_be_finished(self):
        errors = self._errors(self._history(finished=False), {"finish_date": timezone.now()})
        self.assertEqual(errors, {})

    # --- finished productions are frozen ------------------------------------

    def test_finished_lot_id_is_rejected(self):
        errors = self._errors(self._history(finished=True), {"lot_id": "LOT-REWRITTEN"})
        self.assertIn("lot_id", errors)

    def test_finished_production_amount_is_rejected(self):
        errors = self._errors(self._history(finished=True), {"production_amount": 99999})
        self.assertIn("production_amount", errors)

    def test_finished_quality_and_harvest_are_rejected(self):
        errors = self._errors(
            self._history(finished=True),
            {"quality_grade": "premium", "harvest_method": "mechanical"},
        )
        self.assertIn("quality_grade", errors)
        self.assertIn("harvest_method", errors)

    def test_finish_date_cannot_be_nulled_the_reopen_path(self):
        """PATCH {"finish_date": null} used to release every event lock at once."""
        errors = self._errors(self._history(finished=True), {"finish_date": None})
        self.assertIn("finish_date", errors)

    def test_finish_date_cannot_be_moved(self):
        """Moving it desynchronised retention_until, which finish() alone computes."""
        errors = self._errors(self._history(finished=True), {"finish_date": timezone.now() - timedelta(days=30)})
        self.assertIn("finish_date", errors)

    # --- a no-op resubmit must not be treated as a rewrite -------------------

    def test_resubmitting_identical_values_is_allowed(self):
        """Guard compares against the stored value, so an idempotent PATCH still works."""
        h = self._history(finished=True)
        errors = self._errors(h, {"lot_id": h.lot_id, "finish_date": h.finish_date})
        self.assertEqual(errors, {})

    def test_unrelated_field_still_editable_after_finish(self):
        """Freezing the harvest record must not freeze the whole row."""
        errors = self._errors(self._history(finished=True), {"name": "Renamed season"})
        self.assertEqual(errors, {})


class AmendmentDivergenceTests(TestCase):
    """A correction moves the harvest records; the frozen header does not follow.

    Found 2026-08-20 by actually amending a closed season and re-reading the packet. The two
    guards work as designed and pull in opposite directions:

      * `_reject_closed_record_rewrites` freezes `production_amount` once a season is
        finished — the lot header is the traceability spine and must not be rewritten.
      * `EventViewSet.amend` keeps the harvest records correctable, because a wrong number in
        a filed packet is worse for an audit than a documented correction.

    So a legitimate correction of one harvest pass (558,000 -> 560,000 lb) leaves the header
    reading 971,100 against records totalling 973,100. `_resolve_harvest_total` prefers the
    records and prints its basis, so the packet reported the NEW sum and the header number
    simply vanished — no flag, no note. The mass balance is the section the WA certifier
    reviewer singled out as the most trustworthy thing in the packet, and a silent 2,000 lb
    gap there costs more than a loud one.
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta

        from django.utils import timezone

        from carbon.models import CropType
        from product.models import Product

        cls.company = Company.objects.create(name="Divergence Co")
        cls.est = Establishment.objects.create(name="Divergence Farm", company=cls.company)
        cls.parcel = Parcel.objects.create(name="Block", establishment=cls.est, area=11.5)
        cls.crop = CropType.objects.create(
            name="Apple",
            slug="apple-divergence",
            category="tree_fruit",
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
        cls.product = Product.objects.create(name="Apple")
        cls.now = timezone.now()
        cls.delta = timedelta

    def _season(self, header_amount, picks, header_unit="lb", pick_unit="lbs", finished=True):
        from history.models import Production, ProductionEvent

        history = Production.objects.create(
            parcel=self.parcel,
            product=self.product,
            crop_type=self.crop,
            start_date=self.now - self.delta(days=200),
            finish_date=self.now - self.delta(days=10) if finished else None,
            production_amount=header_amount,
            production_unit=header_unit,
        )
        for i, qty in enumerate(picks):
            ProductionEvent.objects.create(
                history=history,
                type="HA",
                date=self.now - self.delta(days=30 - i),
                description=f"Pick {i + 1}",
                yield_quantity=qty,
                yield_unit=pick_unit,
            )
        return history

    def _service(self, history):
        from history.services.audit_export_service import AuditExportService

        return AuditExportService(history, certification_type="organic")

    def test_a_matching_season_reports_no_divergence(self):
        history = self._season(971100, [558000, 413100])
        self.assertIsNone(self._service(history)._harvest_header_divergence())

    def test_an_amended_pick_is_reported_against_the_frozen_header(self):
        history = self._season(971100, [560000, 413100])
        divergence = self._service(history)._harvest_header_divergence()
        self.assertIsNotNone(divergence, "a 2,000 lb gap between records and header went unreported")
        self.assertEqual(divergence["header"], 971100.0)
        self.assertEqual(divergence["recorded"], 973100.0)
        self.assertEqual(divergence["gap"], 2000.0)

    def test_lb_and_lbs_are_the_same_unit(self):
        """The first version of this guard compared unit STRINGS and disabled itself.

        Season headers are written "lb" and harvest events "lbs" on real operations, so a
        literal comparison bails out on the most common shape there is and the check silently
        never fires — the failure mode the check exists to prevent.
        """
        history = self._season(971100, [560000, 413100], header_unit="lb", pick_unit="lbs")
        self.assertIsNotNone(self._service(history)._harvest_header_divergence())

    def test_an_open_season_has_no_header_to_diverge_from(self):
        """A season still in progress is not a reconciliation failure.

        `production_amount` is written when the operator FINISHES a production; until then it
        sits at its 0.0 default. Comparing harvest records against that default produced
        "the harvest records total 348,000 lb but this season's header records 0 lb —
        reconcile the two before certifier submission" on a season the same page reports as
        "Production finalized: No". Found 2026-08-21 on a pilot renewal with three open
        seasons, each carrying its own spurious § 205.103(b)(2) REVIEW.
        """
        history = self._season(0, [348000], finished=False)
        self.assertIsNone(
            self._service(history)._harvest_header_divergence(),
            "an in-progress season was reported as a header/record divergence",
        )

    def test_the_same_season_once_finished_is_compared_again(self):
        """Closing the season restores the check — the exemption is about timing, not silence."""
        history = self._season(340000, [348000], finished=True)
        divergence = self._service(history)._harvest_header_divergence()
        self.assertIsNotNone(divergence)
        self.assertEqual(divergence["gap"], 8000.0)

    def test_genuinely_different_units_are_not_compared(self):
        """Bins against pounds would fabricate a discrepancy, not find one."""
        history = self._season(971100, [1079], header_unit="lb", pick_unit="bins")
        self.assertIsNone(self._service(history)._harvest_header_divergence())

    def test_the_flag_reaches_the_packet_and_names_the_corrections_table(self):
        from reportlab.platypus import Paragraph

        history = self._season(971100, [560000, 413100])
        elements = self._service(history)._build_mass_balance_section()
        text = " ".join((getattr(el, "text", "") or "") for el in elements if isinstance(el, Paragraph))
        self.assertIn("harvest records total", text)
        # It must point the certifier at the explanation, not just assert a gap.
        self.assertIn("Documented Corrections", text)
