"""
Characterisation test: where event subtype codes ARE and ARE NOT validated.

WHY (2026-08-01 consumer editorial review): 26 events on PUBLISHED productions carry truncated
one-letter subtype codes — ``production/H``, ``production/P``, ``chemical/F`` — matching no
subtype in the frontend registry. Their cards resolve almost no fields, so the consumer page
shows a near-empty entry and the certifier export loses the classification.

Investigating produced a more useful answer than the guard I first wrote:

  * ``full_clean()`` ALREADY rejects them — Django validates ``choices`` there, so every
    forms / DRF-serializer / explicit-``full_clean`` path is safe. A custom check in ``clean()``
    was pure duplication and was removed rather than shipped as dead code.
  * ``save()`` does NOT validate. ``ProductionEvent.objects.create(type="H")`` succeeds
    silently. That is the real gap, and it is how the bad rows got in — all 26 sit on
    ``GreenHarvest*`` seed farms with names like "Test Spring Fertilization", i.e. a seed
    script using raw ORM writes, not a live user flow.

This test pins both halves so the split is explicit rather than folklore. Closing the ``save()``
gap means overriding ``save()`` (or a DB CheckConstraint), which would start raising inside
existing seed scripts and data migrations — a deliberate, separately-scoped change, not a
drive-by. The consumer-side harm is already mitigated: ``humanizeEnumFallback``
(config/events/formatters.ts) now DROPS unrecognised short codes instead of printing them, so a
bad row no longer renders "LA" or "H" at a shopper.
"""

import decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, ProductionEvent
from product.models import Parcel, Product
from users.models import User


class EventSubtypeValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="subtype@test.com", password="x")
        self.company = Company.objects.create(name="Subtype Farm")
        self.establishment = Establishment.objects.create(name="S1", company=self.company)
        self.parcel = Parcel.objects.create(name="SP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = Production.objects.create(
            name="Subtype Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    # --- What IS protected -----------------------------------------------------------------

    def test_full_clean_rejects_the_truncated_codes_found_in_live_data(self):
        """Every validated write path (DRF, forms) goes through this."""
        for bad in ("H", "P"):
            event = ProductionEvent(history=self.history, type=bad, description="x", date=timezone.now())
            with self.assertRaises(ValidationError) as ctx:
                event.full_clean()
            self.assertIn("type", ctx.exception.message_dict)

    def test_full_clean_rejects_a_truncated_chemical_code(self):
        event = ChemicalEvent(history=self.history, type="F", description="x", date=timezone.now())
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("type", ctx.exception.message_dict)

    def test_full_clean_accepts_a_declared_subtype(self):
        """Guards against over-eager validation blocking legitimate writes."""
        event = ProductionEvent(history=self.history, type="HA", description="Harvest", date=timezone.now())
        event.full_clean()
        event.save()
        self.assertIsNotNone(event.pk)

    # --- What is NOT protected (the real gap, documented deliberately) ------------------------

    def test_raw_save_still_accepts_an_invalid_subtype(self):
        """DOCUMENTS A KNOWN GAP — this is not an endorsement.

        Django does not validate ``choices`` on ``save()``. If this test ever starts failing,
        someone has closed the gap (a ``save()`` override or a CheckConstraint) — that is a
        GOOD change: delete this test and move the assertion up to the protected block above.
        """
        event = ProductionEvent.objects.create(history=self.history, type="H", description="x", date=timezone.now())
        self.assertEqual(
            ProductionEvent.objects.filter(pk=event.pk).values_list("type", flat=True).first(),
            "H",
            "raw ORM writes bypass choice validation — see this module's docstring",
        )


class NpkMixedNumericTypeTests(TestCase):
    """`ChemicalEvent.clean()` must not explode when NPK values have mixed numeric types.

    Found 2026-08-10 while baselining the history suite (4 errors traced to one line,
    `history/models.py` NPK total). N/P/K are `DecimalField`s, so a value read back from the
    database is a `Decimal` — but a value assigned in Python stays whatever it was: a float
    off deserialised JSON, a template default, a management command. Summing the mix raised

        TypeError: unsupported operand type(s) for +: 'decimal.Decimal' and 'float'

    which escapes `clean()` as an unhandled 500 rather than a validation error, on the
    fertiliser path — the most-used event type in the ICP. Reproduced on a bare instance with
    no database or fixture involved, so it was never a test artefact.

    These tests are typed deliberately as MIXED. An all-Decimal or all-float test passes
    against the broken code and would have pinned nothing.
    """

    def _event(self, n, p, k):
        return ChemicalEvent(nitrogen_percentage=n, phosphorus_percentage=p, potassium_percentage=k)

    def test_mixed_types_under_limit_validate_cleanly(self):
        self._event(decimal.Decimal("10.00"), 10.5, decimal.Decimal("5.00")).clean()

    def test_mixed_types_over_limit_raise_validation_not_type_error(self):
        with self.assertRaises(ValidationError) as ctx:
            self._event(decimal.Decimal("60.00"), 50.5, decimal.Decimal("5.00")).clean()
        self.assertIn("cannot exceed 100%", str(ctx.exception))

    def test_error_message_does_not_leak_float_representation(self):
        # Decimal(str(x)) not Decimal(x): the latter converts the binary representation
        # exactly, so a 10.5 would surface to the grower as 10.50000000000000177635683940025046...
        with self.assertRaises(ValidationError) as ctx:
            self._event(60.1, 30.2, 20.3).clean()
        self.assertNotIn("0000000", str(ctx.exception))

    def test_all_float_still_validates(self):
        with self.assertRaises(ValidationError):
            self._event(60.0, 50.5, 5.0).clean()
