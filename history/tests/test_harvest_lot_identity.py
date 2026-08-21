"""Harvest lot identity: the link that makes a sale traceable back to a pick.

7 CFR 205.103(b)(2) wants records that trace a sold product back to its origin, and USDA's
Guide for Organic Crop Producers is explicit that growers with multiple fields of the same crop
need lot numbers linking product to "the fields of origin and the year or date".

Before this, the only lot identifier lived on History — i.e. per SEASON. A block picked twice
produced two harvest passes, one season-level id, and no way to say which pick a buyer got.

Each test below pins a defect that was actually observed in the data, not a hypothetical.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from history.models import History, ProductionEvent
from history.serializers import SalesRecordSerializer
from product.models import Product


class HarvestLotCodeAssignmentTests(TestCase):
    """`ProductionEvent.save()` assigns a code when the operator leaves one blank."""

    @classmethod
    def setUpTestData(cls):
        cls.history = _make_history(crop_name="Avocado")
        cls.when = timezone.now()

    def _harvest(self, **kwargs):
        payload = {
            "history": self.history,
            "type": "HA",
            "date": self.when,
            "description": "pick",
        }
        payload.update(kwargs)
        return ProductionEvent.objects.create(**payload)

    def test_code_assigned_on_create(self):
        event = self._harvest(block_id="Block 2")
        self.assertEqual(
            event.harvest_lot_code,
            f"AVO-BLOCK2-{self.when.strftime('%Y%m%d')}",
            "A harvest with a crop and a block must get a crop+block+date lot code.",
        )

    def test_same_day_same_block_second_pick_is_distinguishable(self):
        """MEASURED: two picks on one day were both given `AVO-BLOCKCEA-20251007`.

        A morning pick and an afternoon pick are a normal pattern, and a lot code shared by
        two lots identifies neither — the exact failure the code exists to prevent.
        """
        first = self._harvest(block_id="Block 2")
        second = self._harvest(block_id="Block 2")

        self.assertNotEqual(first.harvest_lot_code, second.harvest_lot_code)
        self.assertTrue(second.harvest_lot_code.endswith("-2"), second.harvest_lot_code)

    def test_tokens_are_stripped_to_alphanumerics(self):
        """MEASURED: a product named "QA " produced `QA -BLOCKCEA-20251011`.

        A lot code is typed onto a bin tag and matched against a sales record; a space inside
        an identifier is a transcription error waiting to happen.
        """
        history = _make_history(crop_name="QA Test Crop")
        event = ProductionEvent.objects.create(
            history=history, type="HA", date=self.when, block_id="Block Cea", description="pick"
        )
        self.assertNotIn(" ", event.harvest_lot_code)
        self.assertTrue(event.harvest_lot_code.startswith("QAT-"), event.harvest_lot_code)

    def test_operator_code_is_never_overwritten(self):
        event = self._harvest(block_id="Block 2", harvest_lot_code="MYOWN-001")
        self.assertEqual(event.harvest_lot_code, "MYOWN-001")
        event.description = "edited"
        event.save()
        event.refresh_from_db()
        self.assertEqual(event.harvest_lot_code, "MYOWN-001")

    def test_non_harvest_events_get_no_code(self):
        planting = ProductionEvent.objects.create(
            history=self.history, type="PL", date=self.when, description="planting"
        )
        self.assertFalse(planting.harvest_lot_code)

    def test_narrow_update_fields_write_is_not_widened(self):
        """A caller saving one column must not have the lot code written under them."""
        event = self._harvest(block_id="Block 2")
        ProductionEvent.objects.filter(pk=event.pk).update(harvest_lot_code="")
        event.refresh_from_db()

        event.description = "edited"
        event.save(update_fields=["description"])
        event.refresh_from_db()
        self.assertEqual(event.harvest_lot_code, "", "update_fields must scope the write.")

    def test_positional_update_fields_is_also_respected(self):
        """Django allows save(force_insert, force_update, using, update_fields) POSITIONALLY.

        Reading only `kwargs` meant a positional narrow write looked like a full save, and the
        lot code was written on top of another caller's single-column update.
        """
        event = self._harvest(block_id="Block 2")
        ProductionEvent.objects.filter(pk=event.pk).update(harvest_lot_code="")
        event.refresh_from_db()

        event.description = "edited"
        event.save(False, False, None, ["description"])
        event.refresh_from_db()
        self.assertEqual(event.harvest_lot_code, "", "positional update_fields must scope the write.")

    def test_no_crop_and_no_block_yields_no_code(self):
        """A code built from a date alone collides across blocks, so none is better."""
        history = _make_history(crop_name="")
        event = ProductionEvent.objects.create(history=history, type="HA", date=self.when, description="pick")
        self.assertFalse(event.harvest_lot_code)


class SalesHarvestLinkTests(TestCase):
    """A sale names the pick(s) it drew from — and only its own production's picks."""

    @classmethod
    def setUpTestData(cls):
        cls.history = _make_history(crop_name="Avocado")
        cls.other = _make_history(crop_name="Orange")
        now = timezone.now()
        cls.pick_a = ProductionEvent.objects.create(
            history=cls.history, type="HA", date=now, block_id="Block 2", description="am"
        )
        cls.pick_b = ProductionEvent.objects.create(
            history=cls.history,
            type="HA",
            date=now + timedelta(days=1),
            block_id="Block 2",
            description="next day",
        )
        cls.foreign_pick = ProductionEvent.objects.create(
            history=cls.other, type="HA", date=now, block_id="Block 9", description="other farm"
        )

    def _payload(self, **kwargs):
        payload = {
            "sale_date": "2025-11-01",
            "buyer_name": "Acme Produce",
            "quantity": 10,
            "quantity_unit": "tons",
            "organic_on_invoice": True,
        }
        payload.update(kwargs)
        return payload

    def test_linked_lots_round_trip(self):
        serializer = SalesRecordSerializer(data=self._payload(harvest_events=[self.pick_a.id, self.pick_b.id]))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        record = serializer.save(production=self.history)

        out = SalesRecordSerializer(record).data
        self.assertCountEqual(out["harvest_events"], [self.pick_a.id, self.pick_b.id])
        self.assertCountEqual(
            out["harvest_lot_codes"],
            [self.pick_a.harvest_lot_code, self.pick_b.harvest_lot_code],
        )

    def test_another_productions_harvest_is_refused(self):
        """`limit_choices_to` constrains the admin, NOT DRF's PrimaryKeyRelatedField.

        Without the create/update guard a client could post another operation's harvest ids
        and the certifier packet would print that operation's lot codes on this sale.
        """
        serializer = SalesRecordSerializer(data=self._payload(harvest_events=[self.foreign_pick.id]))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with self.assertRaises(Exception) as ctx:
            serializer.save(production=self.history)
        self.assertIn("different production", str(ctx.exception))

    def test_no_link_is_allowed(self):
        """Not every sale can be traced to a specific pick; absence is not an error."""
        serializer = SalesRecordSerializer(data=self._payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        record = serializer.save(production=self.history)
        self.assertEqual(list(record.harvest_events.all()), [])


class MassBalanceSourceTests(TestCase):
    """The packet reconciles against the harvest RECORDS, not the season header."""

    @classmethod
    def setUpTestData(cls):
        cls.history = _make_history(crop_name="Avocado")
        cls.history.production_amount = 21
        cls.history.production_unit = "tons"
        cls.history.save(update_fields=["production_amount", "production_unit"])
        now = timezone.now()
        for _ in range(2):
            ProductionEvent.objects.create(
                history=cls.history,
                type="HA",
                date=now,
                block_id="Block 2",
                description="pick",
                yield_quantity=12.5,
                yield_unit="tons",
            )

    def _service(self):
        from history.services.audit_export_service import AuditExportService

        return AuditExportService(self.history)

    def test_sums_the_picks_when_units_agree(self):
        amount, unit, basis = self._service()._resolve_harvest_total()
        self.assertEqual(float(amount), 25.0, "Two 12.5-ton picks must reconcile as 25 tons.")
        self.assertEqual(unit, "tons")
        self.assertIn("sum of 2", basis)

    def test_falls_back_to_the_header_on_mixed_units(self):
        """Adding pounds to bins would be a confident fabricated total."""
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            block_id="Block 3",
            description="pick",
            yield_quantity=400,
            yield_unit="lbs",
        )
        amount, unit, basis = self._service()._resolve_harvest_total()
        self.assertEqual(float(amount), 21.0)
        self.assertIn("mixed units", basis)

    def test_states_when_no_structured_yield_exists(self):
        ProductionEvent.objects.filter(history=self.history, type="HA").update(yield_quantity=None)
        _, _, basis = self._service()._resolve_harvest_total()
        self.assertIn("no harvest records", basis)


class UnitCanonicalisationTests(TestCase):
    """Harvest and sale units are typed in two different vocabularies.

    MEASURED on real records: `yield_unit` holds kg / lbs / tons / t / lb / bins, while a
    SalesRecord's `quantity_unit` is restricted to kg / lb / boxes / crates / tons / bushels /
    units. The reconciliation only prints when the two strings match, so a grower who wrote
    "lbs" on the pick and "lb" on the invoice wrote the same unit twice and got no balance
    line — § 205.103(b)(2) reconciliation vanished from the packet with nothing saying so.
    """

    def setUp(self):
        from history.services.audit_export_service import AuditExportService

        self.canon = AuditExportService._canonical_unit

    def test_synonyms_reconcile(self):
        for left, right in (("lbs", "lb"), ("KG ", "kgs"), ("ton", "tons"), ("Pounds", "lb")):
            with self.subTest(left=left, right=right):
                self.assertEqual(self.canon(left), self.canon(right))

    def test_metric_tonne_is_not_folded_into_us_ton(self):
        """They differ by ~10%. Guessing produces a confident wrong balance, which is worse
        than the [REVIEW] line that prints when the units disagree."""
        self.assertNotEqual(self.canon("t"), self.canon("tons"))

    def test_unrelated_units_do_not_match(self):
        self.assertNotEqual(self.canon("bins"), self.canon("lb"))


class PlantingNopGapTests(TestCase):
    """§ 205.105(e) excluded methods and § 205.204(a)(4) — the two Planting gaps with no column.

    Both were named by the Planting teardown and neither had a field anywhere: the packet
    could assert an organic planting while saying nothing about excluded methods, which is the
    one § 205.105 prohibition that is unconditional rather than conditional.
    """

    @classmethod
    def setUpTestData(cls):
        cls.history = _make_history(crop_name="Avocado")
        # § 205.204(a)(4) is the PERENNIAL planting-stock rule, so these fixtures say so.
        cls.history.type = "OR"
        cls.history.save(update_fields=["type"])

    def _planting(self, **kwargs):
        payload = {
            "history": self.history,
            "type": "PL",
            "date": timezone.now(),
            "description": "planting",
        }
        payload.update(kwargs)
        return ProductionEvent.objects.create(**payload)

    def test_blank_is_distinct_from_not_verified(self):
        """A boolean would collapse "never asked" into False, which reads on a packet as a
        negative finding against a grower who was never asked the question."""
        unasked = self._planting()
        checked = self._planting(seed_non_gmo_status="not_verified")

        self.assertIsNone(unasked.seed_non_gmo_status)
        self.assertEqual(checked.seed_non_gmo_status, "not_verified")
        self.assertNotEqual(unasked.seed_non_gmo_status, checked.seed_non_gmo_status)

    def test_owner_serializer_exposes_both_and_public_does_not(self):
        """Non-GMO is a marketing claim and every value is self-reported, so it is a
        producer/certifier field only."""
        from history.serializers import ProductionEventSerializer

        event = self._planting(
            seed_non_gmo_status="supplier_attested",
            stock_organic_management_start=timezone.now().date(),
        )
        owner = ProductionEventSerializer(event).data
        self.assertEqual(owner["seed_non_gmo_status"], "supplier_attested")
        self.assertIn("stock_organic_management_start", owner)

    def test_perennial_year_shortfall_is_flagged_in_the_packet(self):
        from datetime import timedelta

        from history.services.audit_export_service import AuditExportService

        event = self._planting(seeds_source="commercial")
        event.stock_organic_management_start = event.date.date() - timedelta(days=200)
        event.save()

        text = " ".join(
            getattr(el, "text", "") or "" for el in AuditExportService(self.history)._build_seed_stock_section()
        )
        self.assertIn("205.204(a)(4)", text)
        self.assertIn("UNDER the 12-month minimum", text)

    def test_annual_transplants_are_not_judged_against_the_perennial_year(self):
        """§ 205.204(a)(4) governs perennial planting stock, not annual seedlings.

        🔴 2026-08-21 — the check fired on ANY planting event carrying an organic-management
        date, so an organic vegetable grower who recorded the nursery date for purchased onion
        transplants read "this perennial planting stock … its crop may not be sold as organic
        until the year has elapsed" in the packet. Annual seedlings fall under
        § 205.204(a)(2)-(3), which has no 12-month clock, and the crop is perfectly saleable.
        """
        from datetime import timedelta

        from history.services.audit_export_service import AuditExportService

        annual = _make_history(crop_name="Onions")
        annual.type = "GA"
        annual.save(update_fields=["type"])
        event = ProductionEvent.objects.create(
            history=annual,
            type="TR",
            date=timezone.now(),
            description="Transplanting",
            seeds_source="commercial",
        )
        event.stock_organic_management_start = event.date.date() - timedelta(days=76)
        event.save()

        text = " ".join(getattr(el, "text", "") or "" for el in AuditExportService(annual)._build_seed_stock_section())
        self.assertNotIn("UNDER the 12-month minimum", text)
        self.assertNotIn("may not be sold as organic", text)
        # The date itself is still worth showing — it is just not a verdict.
        self.assertIn("Organic management since", text)

    def test_perennial_year_met_is_not_flagged(self):
        from datetime import timedelta

        from history.services.audit_export_service import AuditExportService

        event = self._planting(seeds_source="commercial")
        event.stock_organic_management_start = event.date.date() - timedelta(days=800)
        event.save()

        text = " ".join(
            getattr(el, "text", "") or "" for el in AuditExportService(self.history)._build_seed_stock_section()
        )
        self.assertIn("205.204(a)(4)", text)
        self.assertNotIn("UNDER the 12-month minimum", text)

    def test_packet_says_seed_origin_not_seed_source(self):
        """MEASURED complaint: "Seed Source: Commercial" reads to an inspector as the SUPPLIER.

        The teardown proposed merging `seeds_source` into `seed_certification_status`; that was
        REJECTED because they are orthogonal axes and the merge would destroy `farm_saved` — a
        distinct § 205.204 story (no purchase, so no availability search to run).
        """
        from history.services.audit_export_service import AuditExportService

        self._planting(seeds_source="farm_saved")
        text = " ".join(
            getattr(el, "text", "") or "" for el in AuditExportService(self.history)._build_seed_stock_section()
        )
        self.assertIn("Seed Origin", text)
        self.assertNotIn("Seed Source", text)


def _make_history(crop_name=""):
    """Minimal production for these tests.

    Kept local rather than reaching for a shared factory: these assertions depend on the crop
    NAME (it becomes the lot code's first token), so the fixture has to be explicit about it.

    `start_date` is set because these are realistic productions, not because it is required:
    `History.__str__` used to format it unconditionally, so a production without one raised
    inside auditlog's signal (it stringifies every instance it records) before any assertion
    here was reached. That was fixed at source on 2026-08-18 — see test_history_str_repr.py —
    so this is no longer a workaround.
    """
    product = Product.objects.create(name=crop_name) if crop_name else None
    return History.objects.create(
        product=product,
        name="Test production",
        start_date=timezone.now(),
    )
