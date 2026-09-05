"""A spray volume may not print as the amount of product applied.

🔴 2026-09-03, found in the activity wizard's buyer-page preview while filming the demo. The
grower dictated "Sprayed Entrust on the east block. Six fluid ounces an acre, 40 gallons total,
airblast." The 40 gallons is the TANK -- the carrier the product was mixed into -- and the voice
mapper wrote it to `volume_numeric`, which the Input Application Log prints under
"Amount / Rate" as the amount of product applied.

Six fluid ounces an acre over twelve acres is 72 fl oz. Forty gallons is 5,120. Both numbers sat
on the same row of the same table and the packet asserted both. That column is what an inspector
runs the § 205.103(b)(2) mass balance from (applied vs purchased), and what CA PUR DPR-PML-017C
and the CCOF materials form ask for.

The voice mapper no longer writes a carrier volume there (`productTotalFromAmounts`, frontend).
This is the other half: a value typed by hand, imported, or already on file gets the same
treatment, because the export is where the claim is actually made.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.audit_export_service import _amount_reconciles_with_rate, _recorded_rate_text
from product.models import Parcel, Product
from users.models import User


class _Stub:
    """The four recorded numbers the reconciliation reads, and nothing else."""

    def __init__(self, **kwargs):
        self.volume_numeric = None
        self.volume_unit = ""
        self.application_rate = None
        self.application_rate_unit = ""
        self.area_numeric = None
        self.area_unit = "acres"
        for key, value in kwargs.items():
            setattr(self, key, value)


class RecordedRateTextTests(SimpleTestCase):
    def test_it_prints_the_rate_the_operator_recorded(self):
        # `application_rate` became a real column on 2026-09-03 and the packet did not read it,
        # so the one number a reviewer checks a label maximum against was Trazo's arithmetic.
        self.assertEqual(
            _recorded_rate_text(_Stub(application_rate=Decimal("6"), application_rate_unit="fl_oz_ac")),
            "6.00 fl oz/acre",
        )

    def test_it_says_nothing_without_both_halves(self):
        self.assertIsNone(_recorded_rate_text(_Stub(application_rate=Decimal("6"))))
        self.assertIsNone(_recorded_rate_text(_Stub(application_rate_unit="fl_oz_ac")))

    def test_an_unrecognised_code_prints_nothing_rather_than_machine_text(self):
        # Django enforces `choices` on neither save() nor a DRF write, and this file has three
        # prior incidents of a raw stored value reaching a regulatory document.
        self.assertIsNone(_recorded_rate_text(_Stub(application_rate=Decimal("6"), application_rate_unit="fl_oz_tree")))


class AmountRateReconciliationTests(SimpleTestCase):
    def test_the_demo_record_does_not_reconcile(self):
        # The exact shape that was on camera.
        self.assertIs(
            _amount_reconciles_with_rate(
                _Stub(
                    volume_numeric=Decimal("40"),
                    volume_unit="gal",
                    application_rate=Decimal("6"),
                    application_rate_unit="fl_oz_ac",
                    area_numeric=Decimal("12"),
                    area_unit="acres",
                )
            ),
            False,
        )

    def test_the_honest_version_of_the_same_record_reconciles(self):
        # 6 fl oz/acre x 12 acres = 72 fl oz = 0.5625 gal. Anti-vacuity for the test above: a
        # check that answered False for everything would flag every row in every packet.
        self.assertIs(
            _amount_reconciles_with_rate(
                _Stub(
                    volume_numeric=Decimal("0.5625"),
                    volume_unit="gal",
                    application_rate=Decimal("6"),
                    application_rate_unit="fl_oz_ac",
                    area_numeric=Decimal("12"),
                    area_unit="acres",
                )
            ),
            True,
        )

    def test_it_tolerates_the_slack_a_real_application_carries(self):
        # A partial pass, a rounded tank, a second touch-up. 3.5 lb/acre over 85 acres is
        # 297.5 lb; the operator recorded 300.
        self.assertIs(
            _amount_reconciles_with_rate(
                _Stub(
                    volume_numeric=Decimal("300"),
                    volume_unit="lbs",
                    application_rate=Decimal("3.5"),
                    application_rate_unit="lb_ac",
                    area_numeric=Decimal("85"),
                    area_unit="acres",
                )
            ),
            True,
        )

    def test_it_crosses_units_and_denominators(self):
        # 200 kg/ha over 4 ha = 800 kg, recorded in pounds.
        self.assertIs(
            _amount_reconciles_with_rate(
                _Stub(
                    volume_numeric=Decimal("1764"),
                    volume_unit="lbs",
                    application_rate=Decimal("200"),
                    application_rate_unit="kg_ha",
                    area_numeric=Decimal("4"),
                    area_unit="ha",
                )
            ),
            True,
        )
        # ...and catches a metric record with a tank volume in it: 20 L/ha over 4 ha is 80 L,
        # and 400 gallons is 1,514 L. (A gallons total against a kg/ha RATE is a different
        # question entirely and answers None -- see the declines-to-judge test below.)
        self.assertIs(
            _amount_reconciles_with_rate(
                _Stub(
                    volume_numeric=Decimal("400"),
                    volume_unit="gal",
                    application_rate=Decimal("20"),
                    application_rate_unit="L_ha",
                    area_numeric=Decimal("4"),
                    area_unit="ha",
                )
            ),
            False,
        )

    def test_it_declines_to_judge_what_it_cannot_compare(self):
        # None, not False. An unverifiable comparison must never become an accusation on a
        # certifier document: a false discrepancy is a nonconformance the farm did not commit.
        for stub in (
            _Stub(volume_numeric=Decimal("40"), volume_unit="gal"),  # no rate
            _Stub(  # no area
                volume_numeric=Decimal("40"),
                volume_unit="gal",
                application_rate=Decimal("6"),
                application_rate_unit="fl_oz_ac",
            ),
            _Stub(  # mass rate against a liquid total: two dimensions, nothing to compare
                volume_numeric=Decimal("40"),
                volume_unit="gal",
                application_rate=Decimal("6"),
                application_rate_unit="lb_ac",
                area_numeric=Decimal("12"),
                area_unit="acres",
            ),
            _Stub(  # a unit this table does not know
                volume_numeric=Decimal("40"),
                volume_unit="bushels",
                application_rate=Decimal("6"),
                application_rate_unit="fl_oz_ac",
                area_numeric=Decimal("12"),
                area_unit="acres",
            ),
            _Stub(  # zero area
                volume_numeric=Decimal("40"),
                volume_unit="gal",
                application_rate=Decimal("6"),
                application_rate_unit="fl_oz_ac",
                area_numeric=Decimal("0"),
                area_unit="acres",
            ),
        ):
            self.assertIsNone(_amount_reconciles_with_rate(stub))


class InputApplicationLogCellTests(TestCase):
    """The finding as a reviewer meets it: the cell itself."""

    def setUp(self):
        self.user = User.objects.create_user(email="tank@test.com", password="x")
        company = Company.objects.create(name="Tank Farm")
        est = Establishment.objects.create(name="East Block", company=company)
        parcel = Parcel.objects.create(name="P1", establishment=est, area=5.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-tank",
            category="tree_nut",
            description="Tree nut",
            typical_farm_size="10-40 ha",
            growing_season="Feb-Oct",
            harvest_season="Sep-Oct",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _spray(self, **kwargs):
        defaults = dict(
            history=self.history,
            date=timezone.now() - timedelta(days=20),
            description="Spinosad application",
            commercial_name="Entrust SC",
            type="PE",
            area_numeric=Decimal("12"),
            area_unit="acres",
            created_by=self.user,
        )
        defaults.update(kwargs)
        return ChemicalEvent.objects.create(**defaults)

    def _cells(self):
        from history.services import audit_export_service as svc

        captured = []
        original = svc.AuditExportService._cell

        def spy(self, value, *args, **kwargs):
            captured.append(value)
            return original(self, value, *args, **kwargs)

        svc.AuditExportService._cell = spy
        try:
            svc.AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        finally:
            svc.AuditExportService._cell = original
        return [str(c) for c in captured if c is not None]

    def test_the_tank_volume_is_never_presented_as_the_product_amount(self):
        self._spray(
            volume_numeric=Decimal("40"),
            volume_unit="gal",
            application_rate=Decimal("6"),
            application_rate_unit="fl_oz_ac",
        )
        cells = self._cells()
        amount_cells = [c for c in cells if "fl oz/acre" in c or "40.00 gal" in c]
        self.assertTrue(amount_cells, "the Amount / Rate cell was not rendered at all")
        # The recorded rate is kept, the total is stated as unreconciled, and nowhere does the
        # column present "40.00 gal" as the amount applied.
        self.assertTrue(any("not reconciled" in c for c in amount_cells), amount_cells)
        self.assertTrue(any("6.00 fl oz/acre" in c for c in amount_cells), amount_cells)
        # The old shape: total first, derived rate in parentheses.
        self.assertFalse(any(c.startswith("40.00 gal (") for c in amount_cells), amount_cells)

    def test_a_reconciled_record_reads_normally(self):
        # Anti-vacuity: the guard must not turn every application log into a discrepancy report.
        self._spray(
            volume_numeric=Decimal("72"),
            volume_unit="oz",
            application_rate=Decimal("6"),
            application_rate_unit="fl_oz_ac",
        )
        cells = self._cells()
        self.assertFalse(any("not reconciled" in c for c in cells), "flagged an honest record")
        self.assertTrue(
            any("72.00 oz" in c and "6.00 fl oz/acre" in c for c in cells),
            [c for c in cells if "oz" in c],
        )

    def test_the_recorded_rate_wins_over_the_derived_one(self):
        # 75 oz over 12 acres derives 6.25 fl oz/acre. The operator recorded 6.00, which is what
        # the label is written in and what a reviewer checks against it.
        self._spray(
            volume_numeric=Decimal("75"),
            volume_unit="oz",
            application_rate=Decimal("6"),
            application_rate_unit="fl_oz_ac",
        )
        cells = self._cells()
        self.assertTrue(any("6.00 fl oz/acre" in c for c in cells), [c for c in cells if "oz" in c])
        self.assertFalse(any("6.25" in c for c in cells))

    def test_a_record_with_no_recorded_rate_still_derives_one(self):
        # Every row written before `application_rate` existed.
        self._spray(volume_numeric=Decimal("75"), volume_unit="oz")
        cells = self._cells()
        self.assertTrue(any("6.25 oz/acre" in c for c in cells), [c for c in cells if "oz" in c])
