"""The buyer's carbon figure counts only entries with a recorded basis, and says so.

Recordkeeping review, 2026-10-07 (F-02, F-10). The anonymous payload for the specimen's Onions
2026 season served `total_emissions = 12294.0`, which the database showed to be 12,211.9 from
rows with a factor plus 82.1 from two `area_estimate` rows (a per-hectare guess for a harvest
with no fuel recorded, the class R8-04 retired from every card); the same payload carried
`carbon_scope: "Direct operational emissions only (EPA/USDA-sourced factors)"` (both phrases on
compliance.md's unsafe list), `calculation_method: "USDA_EPA_factors"`, `isEpaFactorsBased` and
the car-mile and phone-charge equivalents R8-14 removed from the page. The operator's records
ZIP carried `trust_score` 0.5 and `data_source "USDA Agricultural Research Service"` on every
carbon row, and `confidence_score` on every production.

Each test here went red on the code before the fix, on an assertion.
"""

import csv
import io
import zipfile
from datetime import timedelta

from django.utils import timezone

from rest_framework.test import APITestCase

from carbon.models import CarbonEntry
from carbon.services.calculator_service import CarbonCalculatorService
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User


class PublicCarbonCountsOnlyRecordedBasisTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="carbon-basis@test.com", password="x")
        cls.company = Company.objects.create(name="Basis Co")
        cls.establishment = Establishment.objects.create(name="Basis Farm", company=cls.company, state="OR")
        cls.parcel = Parcel.objects.create(name="Upper Terrace", establishment=cls.establishment, area=5.0)
        cls.product = Product.objects.create(name="Onions")
        cls.history = History.objects.create(
            name="Onions 2026",
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
            product=cls.product,
            parcel=cls.parcel,
            operator=cls.user,
            earning=0.0,
            production_amount=1000,
            production_unit="lb",
            reputation=0.0,
            confidence_score=64.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        for amount, status, desc in (
            (100.0, "factors_verified", "fertilizer manufacturing, factor applied"),
            (41.0, "area_estimate", "harvest with no fuel recorded, per-hectare guess"),
            (0.0, "no_factor_applied", "scouting, no factor"),
        ):
            CarbonEntry.objects.create(
                establishment=cls.establishment,
                production=cls.history,
                type="emission",
                amount=amount,
                co2e_amount=amount,
                year=2026,
                verification_status=status,
                data_source="USDA Agricultural Research Service",
                description=desc,
                created_by=cls.user,
            )

    # -- the calculator keeps both figures apart ---------------------------------

    def test_the_calculator_reports_the_recorded_total_beside_the_full_one(self):
        result = CarbonCalculatorService().calculate_production_carbon(self.history.id)
        self.assertEqual(result["total_emissions"], 141.0)  # the farmer's dashboard total
        self.assertEqual(result.get("recorded_emissions"), 100.0)
        self.assertEqual(result.get("excluded_entry_count"), 2)
        self.assertAlmostEqual(result.get("recorded_co2_kg_per_kg") or 0.0, 100.0 / 453.59237, places=4)
        self.assertAlmostEqual(result["gross_co2_kg_per_kg"], 141.0 / 453.59237, places=4)

    # -- the anonymous payload -----------------------------------------------------

    def _payload(self):
        response = self.client.get(f"/api/transparency/{self.history.public_id}/")
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_the_buyer_total_and_per_kg_count_only_the_recorded_basis(self):
        carbon = self._payload()["carbon_impact"]
        self.assertEqual(carbon["total_emissions"], 100.0)
        self.assertEqual(carbon["net_impact"], 100.0)
        # 1,000 lb = 453.6 kg; 100 kg CO2e over 453.6 kg of product.
        self.assertEqual(carbon["kg_per_kg"], 0.22)
        self.assertEqual(carbon["consumer_context"]["kg_per_kg"], 0.22)

    def test_the_per_kg_figure_divides_by_kilograms_of_product(self):
        # Found verifying this slice: the figure divided by the raw amount in whatever unit the
        # season recorded, so a 349,000 lb season was treated as 349,000 kg.
        result = CarbonCalculatorService().calculate_production_carbon(self.history.id)
        self.assertAlmostEqual(result.get("recorded_co2_kg_per_kg") or 0.0, 100.0 / 453.59237, places=4)
        History.objects.filter(pk=self.history.pk).update(production_unit="boxes")
        result = CarbonCalculatorService().calculate_production_carbon(self.history.id)
        self.assertEqual(result.get("recorded_co2_kg_per_kg"), 0.0, "boxes are not a mass; no per-kg figure")
        History.objects.filter(pk=self.history.pk).update(production_unit="lb")

    def test_only_a_published_factor_counts_and_every_such_status_is_recognised(self):
        # Review of back #132: a denylist let "estimated" (a per-hour guess) into the buyer
        # figure, and the CSV did not know five statuses the calculator writes for real factors.
        extra = [
            CarbonEntry.objects.create(
                establishment=self.establishment,
                production=self.history,
                type="emission",
                amount=amt,
                co2e_amount=amt,
                year=2026,
                verification_status=status,
                description=status,
                created_by=self.user,
            )
            for amt, status in ((7.0, "estimated"), (3.0, "insufficient_data"), (50.0, "epa_verified"))
        ]
        try:
            result = CarbonCalculatorService().calculate_production_carbon(self.history.id)
            self.assertEqual(result.get("recorded_emissions"), 150.0, "100 factors_verified + 50 epa_verified")
            self.assertEqual(result.get("excluded_entry_count"), 4)
            _header, rows = self._rows(self._zip(), "carbon_entries.csv")
            basis = {r["verification_status"]: r["factor_basis"] for r in rows}
            for status in ("epa_verified", "factors_verified"):
                self.assertNotIn("not stated", basis[status])
                self.assertIn("nitrogen: EPA + IPCC", basis[status])
            self.assertIn("Estimated", basis["estimated"])
        finally:
            for row in extra:
                row.delete()

    def test_a_metric_tonne_is_a_thousand_kilograms(self):
        History.objects.filter(pk=self.history.pk).update(production_unit="t")
        try:
            result = CarbonCalculatorService().calculate_production_carbon(self.history.id)
            self.assertAlmostEqual(result.get("recorded_co2_kg_per_kg") or 0.0, 100.0 / 1_000_000, places=7)
        finally:
            History.objects.filter(pk=self.history.pk).update(production_unit="lb")

    def test_the_payload_carries_no_equivalents_and_no_blanket_attribution(self):
        payload = self._payload()
        carbon = payload["carbon_impact"]
        self.assertNotIn("comparisons", carbon)
        self.assertNotIn("calculation_method", carbon)
        self.assertNotIn("per_kg_miles", carbon["consumer_context"])
        self.assertNotIn("per_kg_phone_charges", carbon["consumer_context"])
        self.assertNotIn("isEpaFactorsBased", payload)
        scope = payload["methodology"]["carbon_scope"]
        self.assertNotIn("EPA/USDA", scope)
        self.assertNotIn("Direct operational emissions only", scope)
        self.assertIn("manufacturing of the fertilizer and crop-protection products", scope)
        self.assertIn("not a full life-cycle footprint", scope)
        self.assertIn("each factor states its own source", scope)
        self.assertIn("no recorded basis are not counted", scope)
        self.assertIn("no recorded basis are not counted", carbon["basis"])

    # -- the operator's records ZIP ------------------------------------------------

    def _zip(self):
        from history.services.records_export import export_establishment_records_zip

        return zipfile.ZipFile(io.BytesIO(export_establishment_records_zip(self.establishment)))

    def _rows(self, zf, name):
        text = zf.read(name).decode("utf-8")
        rows = list(csv.reader(io.StringIO(text)))
        header = rows[0] if rows and len(rows[0]) > 1 else rows[1]
        body = rows[1:] if rows and len(rows[0]) > 1 else rows[2:]
        return header, [dict(zip(header, r)) for r in body]

    def test_the_carbon_csv_drops_the_retired_vocabulary_and_states_a_basis_per_row(self):
        with self._zip() as zf:
            header, rows = self._rows(zf, "carbon_entries.csv")
        for gone in (
            "trust_score",
            "verification_level",
            "additionality_verified",
            "audit_status",
            "data_source",
            "usda_factors_based",
        ):
            self.assertNotIn(gone, header)
        self.assertIn("factor_basis", header)
        by_status = {r["verification_status"]: r["factor_basis"] for r in rows}
        self.assertIn("Estimated from the area recorded", by_status["area_estimate"])
        self.assertEqual(by_status["no_factor_applied"], "No factor applied")
        self.assertIn("Published factor applied; source per input class", by_status["factors_verified"])
        self.assertNotIn("EPA/USDA", by_status["factors_verified"])

    def test_the_productions_csv_drops_the_retired_score(self):
        with self._zip() as zf:
            header, _rows = self._rows(zf, "productions.csv")
        self.assertNotIn("confidence_score", header)
        self.assertNotIn("reputation", header)
        self.assertIn("lot_id", header)
