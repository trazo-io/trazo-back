"""
A2 + A6 (2026-06 NOP-alignment audit).

A2 — non-organic seed/planting-stock commercial-availability search (NOP 5029 /
     7 CFR 205.204(a)(1)) is enforced on the API save path (UpdateProductionEventSerializer
     handles both create + update). Re-enabled now that the planting form ships the
     seed-search widget so the farmer can satisfy it.
A6 — frost-protection (FP) events no longer silently drop their technique
     (extra_data.protection_method) and trigger temperature (low_temperature) from the
     certifier PDF, and "FP" renders as a human label, not the raw code.
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework import serializers as drf_serializers

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.serializers import UpdateProductionEventSerializer
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class SeedSearchValidationTests(TestCase):
    """A2 — the >= 3-supplier search rule on the API write path (create + update)."""

    def _validate(self, **data):
        # Object-level validate() directly, isolating the seed rule.
        return UpdateProductionEventSerializer().validate(data)

    def test_non_organic_pl_without_three_attempts_rejected(self):
        with self.assertRaises(drf_serializers.ValidationError) as ctx:
            self._validate(
                type="PL",
                seed_certification_status="non_organic_untreated",
                seed_search_attempts=[],
            )
        self.assertIn("seed_search_attempts", ctx.exception.detail)

    def test_non_organic_pl_with_two_attempts_accepted(self):
        """Changed 2026-08-15: 205.204 sets no supplier COUNT.

        Three is a certifier expectation from USDA's optional Guide, not rule text. Zero
        documented suppliers is still rejected (the test above) because that leaves the
        exemption with no ground at all.
        """
        attempts = [{"supplier": "A"}, {"supplier": "B"}]
        out = self._validate(
            type="PL",
            seed_certification_status="non_organic_treated",
            seed_search_attempts=attempts,
        )
        self.assertEqual(out["seed_search_attempts"], attempts)

    def test_non_organic_tr_without_attempts_rejected(self):
        """Transplanting was exempt from this rule until 2026-08-15."""
        with self.assertRaises(drf_serializers.ValidationError) as ctx:
            self._validate(
                type="TR",
                seed_certification_status="non_organic_untreated",
                seed_search_attempts=[],
            )
        self.assertIn("seed_search_attempts", ctx.exception.detail)

    def test_non_organic_pl_with_three_attempts_ok(self):
        attempts = [{"supplier": "A"}, {"supplier": "B"}, {"supplier": "C"}]
        out = self._validate(
            type="PL",
            seed_certification_status="non_organic_treated",
            seed_search_attempts=attempts,
        )
        self.assertEqual(out["seed_search_attempts"], attempts)

    def test_organic_pl_without_attempts_ok(self):
        out = self._validate(
            type="PL",
            seed_certification_status="certified_organic",
            seed_search_attempts=[],
        )
        self.assertEqual(out["type"], "PL")

    def test_a_count_instead_of_a_supplier_list_is_a_field_error_not_a_500(self):
        """`seed_search_attempts` is a JSONField, so any JSON shape reaches this rule.

        A bare count is exactly what an operator would think to put in a field called
        "search attempts" — and `for a in attempts` then raised
        `TypeError: 'int' object is not iterable`, which DRF does not catch: an unhandled
        500 on the save button instead of a field error telling them what to write.
        Found 2026-08-22 in a pilot fixture that stored `3`.

        The right answer is not to accept the count. It is to reach the message below, which
        says what § 205.204(a)(1) actually wants: the suppliers, not how many there were.
        """
        for bad in (3, "3", {"count": 3}, None):
            with self.subTest(value=bad):
                with self.assertRaises(drf_serializers.ValidationError) as ctx:
                    self._validate(
                        type="PL",
                        seed_certification_status="non_organic_untreated",
                        seed_search_attempts=bad,
                    )
                self.assertIn("seed_search_attempts", ctx.exception.detail)

    def test_non_pl_event_not_subject_to_seed_rule(self):
        out = self._validate(
            type="HA",
            seed_certification_status="non_organic_untreated",
            seed_search_attempts=[],
        )
        self.assertEqual(out["type"], "HA")


class FrostProtectionExportTests(TestCase):
    """A6 — FP technique + trigger temperature must reach the certifier PDF, and the
    type code must render as a human label."""

    def setUp(self):
        self.user = User.objects.create_user(email="frost@test.com", password="x")
        self.company = Company.objects.create(name="Frost Farm")
        self.establishment = Establishment.objects.create(name="FE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="FP-parcel", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="Frost Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="FP",
            date=timezone.now(),
            description="Frost protection night",
            extra_data={"protection_method": "wind_machine", "low_temperature": -2},
        )

    def _production_events_text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        elements = svc._build_production_events()
        out = []
        for el in elements:
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    text = getattr(cell, "text", None)
                    if text:
                        out.append(text)
        return " ".join(out)

    def test_frost_method_label_and_temp_render(self):
        text = self._production_events_text()
        # Type label (previously rendered the raw code "FP").
        self.assertIn("Frost Protection", text)
        # Technique from extra_data.protection_method (previously blank Method cell).
        self.assertIn("Wind machine", text)
        # Trigger temperature from extra_data.low_temperature.
        self.assertIn("-2", text)
