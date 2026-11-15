"""
Regression tests: units of measure served to consumers must match what the farmer recorded.

WHY THIS EXISTS (2026-07-31 consumer editorial review):
``volume_unit`` / ``area_unit`` are real columns on ChemicalEvent, but the public chemical
block in ``PublicHistorySerializer.get_events()`` read the legacy ``extra_data`` mirror first
and fell back to a hardcoded ``"ha"`` / ``"L"``. Rows written after those columns landed have
no mirror, so **141 of 215 chemical events served ``area_unit="ha"`` for values the farmer
entered in ACRES**.

That is not a cosmetic bug. The consumer card converts hectares to acres for US shoppers
(``withUSUnits``), so an 85-acre copper fungicide application rendered on the public page as
**"210 acres (85 ha)"** — a 2.47x overstatement of pesticide-treated area on a certified
organic farm, in front of shoppers and wholesale buyers.

The rule these tests lock down: the model column is canonical, ``extra_data`` is a legacy
fallback, and an unrecorded unit stays unrecorded. Guessing a unit is worse than omitting one,
because the frontend renders a bare number when the unit is absent but will happily convert
(and therefore misstate) a wrong one.

Sibling blocks (production ``:4038``, soil ``:4445``, pest ``:4606``) already read the column
via ``getattr`` and were never affected — chemical was the sole offender.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from history.serializers import PublicHistorySerializer, _public_unit
from product.models import Parcel, Product
from users.models import User


class PublicUnitHelperTests(TestCase):
    """Unit-level contract for the _public_unit resolver."""

    class _Row:
        def __init__(self, column=None, mirror=None):
            self.area_unit = column
            self.extra_data = {"area_unit": mirror} if mirror is not None else None

    def test_model_column_wins_over_legacy_mirror(self):
        """The whole bug: a stale mirror must never override the real column."""
        row = self._Row(column="acres", mirror="ha")
        self.assertEqual(_public_unit(row, "area_unit"), "acres")

    def test_falls_back_to_legacy_mirror_when_column_empty(self):
        """Old rows predate the columns and only have the extra_data mirror."""
        self.assertEqual(_public_unit(self._Row(column="", mirror="m2"), "area_unit"), "m2")
        self.assertEqual(_public_unit(self._Row(column=None, mirror="km2"), "area_unit"), "km2")

    def test_returns_none_when_nothing_recorded(self):
        """No unit recorded must stay unknown — never a guessed 'ha'/'L'."""
        self.assertIsNone(_public_unit(self._Row(), "area_unit"))
        self.assertIsNone(_public_unit(self._Row(column="   ", mirror="  "), "area_unit"))

    def test_tolerates_missing_or_non_dict_extra_data(self):
        row = self._Row(column=None)
        row.extra_data = "not-a-dict"
        self.assertIsNone(_public_unit(row, "area_unit"))


class PublicChemicalUnitFidelityTests(TestCase):
    """End-to-end: what the farmer recorded is what the consumer payload carries."""

    def setUp(self):
        self.user = User.objects.create_user(email="units@test.com", password="x")
        self.company = Company.objects.create(name="Unit Farm")
        self.establishment = Establishment.objects.create(name="U1", company=self.company)
        self.parcel = Parcel.objects.create(name="UP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = Production.objects.create(
            name="Unit Fidelity Production",
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

    def _chemical_event(self):
        data = PublicHistorySerializer(self.history).data
        chem = [e for e in (data.get("events") or []) if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1, "expected exactly one chemical event in public payload")
        return chem[0]

    def test_acres_are_served_as_acres(self):
        """The exact production bug: acres must not be relabelled as hectares.

        Reproduces event 864 (Kocide 3000, 85 acres) which rendered as "210 acres (85 ha)".
        """
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            commercial_name="Kocide 3000",
            area="85",
            area_unit="acres",
            date=timezone.now(),
        )
        event = self._chemical_event()
        self.assertEqual(
            event.get("area_unit"),
            "acres",
            "Consumer payload relabelled an acres value — this is the 2.47x " "pesticide-treated-area overstatement.",
        )
        self.assertEqual(event.get("area"), "85")

    def test_stale_extra_data_mirror_does_not_override_the_column(self):
        """A legacy mirror left behind by an old client must lose to the real column."""
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            commercial_name="Mirror Test",
            area="42.5",
            area_unit="acres",
            extra_data={"area_unit": "ha"},
            date=timezone.now(),
        )
        self.assertEqual(self._chemical_event().get("area_unit"), "acres")

    def test_model_defaults_are_us_units_and_are_honoured(self):
        """The old fallback contradicted the model's OWN defaults.

        ``ChemicalEvent.area_unit`` defaults to ``"acres"`` and ``volume_unit`` to ``"gal"``
        (models.py) — US units, matching the US grower ICP. The serializer nonetheless fell
        back to ``"ha"``/``"L"``. So every row that simply took the model default was
        mislabelled, which is why the mismatch rate was 141/215 rather than a handful of
        edge cases.
        """
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Defaults Test",
            area="10",
            date=timezone.now(),
        )
        event = self._chemical_event()
        self.assertEqual(
            event.get("area_unit"),
            "acres",
            "The model default is 'acres'; the consumer payload must agree with it.",
        )

    def test_explicitly_blank_unit_is_absent_rather_than_guessed(self):
        """A cleared unit (blank=True) must stay unknown, never become a guessed 'ha'/'L'.

        A bare number renders honestly; a guessed unit is an unverifiable claim about how
        much was applied to food, and the consumer card will silently convert it.
        """
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Blank Unit",
            area="10",
            area_unit="",
            volume_unit="",
            date=timezone.now(),
        )
        event = self._chemical_event()
        self.assertNotIn(
            "area_unit",
            event,
            "A blank area_unit must be omitted, never defaulted to 'ha' — "
            "a guessed basis is silently converted by the consumer card.",
        )
        self.assertNotIn("volume_unit", event)

    def test_hectares_still_served_as_hectares(self):
        """Sanity: the fix must not break genuinely metric records."""
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.HERBICIDE,
            commercial_name="Metric Test",
            area="12.5",
            area_unit="ha",
            date=timezone.now(),
        )
        self.assertEqual(self._chemical_event().get("area_unit"), "ha")
