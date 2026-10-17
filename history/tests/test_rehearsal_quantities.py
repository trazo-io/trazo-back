"""Quantities and units on a pilot season: the 2026-10-17 rehearsal findings.

WHAT WAS WRONG
--------------
A pilot rehearsal set up a fictional WSDA orchard on production and generated its renewal packet
and audit export. Five defects in how quantities and units travel from the records to the paper:

  1. The harvest was recorded as 40 BINS. The season header (History.production_unit) and the
     sale (SalesRecord.quantity_unit, which shares its vocabulary) offered no "bins", so the
     season and the sale ended in "units" and the packet could not reconcile harvest and sale.
  2. One "oz" unit for two ounces. A liquid applied as "36 oz" printed beside its own
     "6 fl oz/acre" rate, and "128 oz" purchased against an invoice reading 128 fl oz.
  3. The harvest record answered the buffer question ("sold as conventional") with no buffer
     quantity, and the audit trail exhibit printed the whole 40-bin lot as buffer crop sold as
     conventional, beside the organic sale of the same lot.
  4. The same exhibit listed the 40-bin harvest in Part B and then said the balance could not be
     computed because no harvest record existed.
  5. A rate-only correction (50 -> 45 lb/acre) left 300 lb over 6 acres on the record. Nothing
     said the record no longer agreed with itself.

Every assertion here reads the generated text (the exhibit PDF, the audit export's flowables or
PDF), or the API payload the correction form reads. None reads the sibling repository.
"""

import io
import re
from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from rest_framework.test import APIClient

from carbon.utils.unit_converter import UnitConverter
from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import _audit_trail_exhibit_pdf
from common.field_registry import UNIT_VOLUME, UNIT_YIELD
from company.models import Company, Establishment
from history.amendments import apply_amendment
from history.constants import CHEMICAL_EVENT_TYPE
from history.models import ChemicalEvent, History, ProductionEvent, SalesRecord
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User, WorksIn


def _pdf_text(data: bytes) -> str:
    from pdfminer.high_level import extract_text

    return " ".join(extract_text(io.BytesIO(data)).split())


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


class _RehearsalSeason(TestCase):
    """North Block, 6 acres, Honeycrisp, finished, lot ASTRA-HC-26-01 (fictional, as rehearsed)."""

    def setUp(self):
        self.user = User.objects.create_user(email="rehearsal-a@test.com", password="x")
        self.company = Company.objects.create(name="Rehearsal Orchard Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(
            name="Test Block", company=self.company, state="WA", contact_person="Crew lead"
        )
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=6.0)
        self.history = History.objects.create(
            name="Honeycrisp 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Apples"),
            operator=self.user,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
            finish_date=datetime(2026, 10, 10, tzinfo=dt_tz.utc),
            lot_id="ASTRA-HC-26-01",
            production_amount=40,
            production_unit="units",
            published=False,
        )

    def _harvest(self, **extra):
        values = dict(
            history=self.history,
            type="HA",
            date=datetime(2026, 9, 15, 14, tzinfo=dt_tz.utc),
            yield_quantity=Decimal("40"),
            yield_unit="bins",
        )
        values.update(extra)
        return ProductionEvent.objects.create(**values)

    def _sale(self, unit="bins", organic=True, quantity="40", buyer="Fictional Packing Co."):
        return SalesRecord.objects.create(
            production=self.history,
            sale_date=date(2026, 10, 1),
            buyer_name=buyer,
            quantity=Decimal(quantity),
            quantity_unit=unit,
            invoice_number="ASTRA-SALE-1001",
            organic_on_invoice=organic,
        )

    def _chemical(self, **extra):
        values = dict(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            date=datetime(2026, 5, 15, 12, tzinfo=dt_tz.utc),
            commercial_name="Entrust SC",
            area_numeric=Decimal("6"),
            area_unit="acres",
        )
        values.update(extra)
        return ChemicalEvent.objects.create(**values)


class HarvestUnitReachesSeasonAndSaleTests(_RehearsalSeason):
    """Finding 1: harvest, season and sale can share one unit."""

    def test_every_harvest_unit_is_a_season_unit_and_a_sale_unit(self):
        canonical = AuditExportService._canonical_unit
        season_units = {v for v, _ in History.UNIT_CHOICES}
        sale_units = {v for v, _ in SalesRecord._meta.get_field("quantity_unit").choices}
        for code, _label in UNIT_YIELD:
            with self.subTest(harvest_unit=code):
                self.assertIn(canonical(code), season_units)
                self.assertIn(canonical(code), sale_units)

    def test_a_bin_season_and_a_bin_sale_validate(self):
        self.history.production_unit = "bins"
        sale = self._sale(unit="bins")
        try:
            self.history.clean_fields(
                exclude=[f.name for f in History._meta.concrete_fields if f.name != "production_unit"]
            )
            sale.clean_fields(exclude=[f.name for f in SalesRecord._meta.concrete_fields if f.name != "quantity_unit"])
        except ValidationError as exc:
            self.fail(f"bins refused as a season or sale unit: {exc}")

    def test_a_bin_harvest_and_a_bin_sale_reconcile_in_the_exhibit(self):
        self._harvest()
        self._sale(unit="bins")
        text = _pdf_text(_audit_trail_exhibit_pdf(self._osp()))
        self.assertIn("Harvested 40 bins (1 harvest record) · sold 40 bins (1 sale) · harvest and sales balance.", text)

    def _osp(self):
        return OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, created_by=self.user)


class ExhibitBufferAndBalanceTests(_RehearsalSeason):
    """Findings 3 and 4: the renewal packet's 05-audit-trail-exhibit."""

    def setUp(self):
        super().setUp()
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, created_by=self.user)

    def _exhibit(self):
        return _pdf_text(_audit_trail_exhibit_pdf(self.osp))

    def test_a_disposition_without_a_buffer_quantity_never_claims_the_lot(self):
        """The rehearsal case: 40 bins, sold_conventional, no buffer quantity, organic sale."""
        self._harvest(buffer_disposition="sold_conventional")
        self._sale(unit="bins")
        text = self._exhibit()
        # Part C read "2026-09-15 · North Block · 40 bins · Sold as conventional".
        self.assertIn("Part C — Buffer crop", text)
        self.assertNotIn("North Block · 40 bins · Sold as conventional", text)
        self.assertIn("North Block · buffer quantity not recorded · Sold as conventional", text)
        # The organic harvest stays with the organic lot, and balances against the organic sale.
        self.assertNotIn("no harvest record is on file", text)
        self.assertIn("Harvested 40 bins (1 harvest record) · sold 40 bins (1 sale)", text)
        self.assertNotIn("harvested from the buffer row", text)

    def test_a_sale_in_another_unit_is_named_as_the_reason(self):
        """Part B listed 40 bins and then said no harvest record existed."""
        self._harvest(buffer_disposition="sold_conventional")
        self._sale(unit="units")
        text = self._exhibit()
        self.assertIn("2026-09-15 · 40 bins 2. Storage", text)  # Part B lists the harvest
        self.assertNotIn("no harvest record is on file", text)
        self.assertIn(
            "Balance not computed: the harvest is recorded in bins and the sales in units, and Trazo does not "
            "convert between units.",
            text,
        )

    def test_with_no_harvest_at_all_the_absence_is_still_stated(self):
        """The mirror: the old sentence stays true where it is true."""
        self._sale(unit="bins")
        self.assertIn("no harvest record is on file for this season", self._exhibit())

    def test_the_audit_export_buffer_table_says_the_quantity_was_not_recorded(self):
        self._harvest(buffer_disposition="sold_conventional")
        svc = AuditExportService(self.history, certification_type="organic")
        text = _flatten(svc._buffer_crop_disposition_rows())
        self.assertIn("Sold as conventional", text)
        self.assertNotIn("40", text.split("Sold as conventional", 1)[1].split("Not recorded", 1)[0])
        self.assertIn("Sold as conventional Not recorded Not recorded", text)


class FluidOunceTests(_RehearsalSeason):
    """Finding 2: fluid ounces are a unit of their own, printed "fl oz"."""

    def test_fluid_and_weight_ounces_are_units_and_the_legacy_oz_still_validates(self):
        codes = [code for code, _ in UNIT_VOLUME]
        self.assertIn("fl_oz", codes)
        self.assertIn("oz_wt", codes)
        # Historical rows keep their value: never rewritten, still valid.
        self.assertIn("oz", codes)

    def test_the_export_prints_fl_oz_for_the_application_and_the_purchase(self):
        self._chemical(
            volume_numeric=Decimal("36"),
            volume_unit="fl_oz",
            application_rate=Decimal("6"),
            application_rate_unit="fl_oz_ac",
            quantity_purchased=Decimal("128"),
            quantity_purchased_unit="fl_oz",
            supplier_name="Fictional Ag Supply",
        )
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertIn("36.00 fl oz (6.00 fl oz/acre)", text)
        self.assertIn("128.00 fl oz", text)
        self.assertNotIn("fl_oz", text)
        self.assertNotIn("not stated", text)

    def test_a_legacy_oz_is_printed_as_recorded_and_says_which_it_does_not_state(self):
        self._chemical(
            volume_numeric=Decimal("36"),
            volume_unit="oz",
            application_rate=Decimal("6"),
            application_rate_unit="fl_oz_ac",
            quantity_purchased=Decimal("128"),
            quantity_purchased_unit="oz",
            supplier_name="Fictional Ag Supply",
        )
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertIn("36.00 oz (fluid or weight not stated) (6.00 fl oz/acre)", text)
        self.assertIn("128.00 oz (fluid or weight not stated)", text)
        # Never upgraded to the unit the rate happens to use.
        self.assertNotIn("36.00 fl oz", text)
        self.assertNotIn("128.00 fl oz", text)
        stored = ChemicalEvent.objects.get(history=self.history)
        self.assertEqual((stored.volume_unit, stored.quantity_purchased_unit), ("oz", "oz"))

    def test_a_legacy_free_text_amount_carrying_its_unit_is_not_printed_twice(self):
        """Review on back#168: "36 oz" in the free-text column printed "36 oz oz (...)"."""
        self._chemical(volume="36 oz", volume_unit="oz")
        text = _flatten(AuditExportService(self.history, certification_type="organic")._build_chemical_log())
        self.assertIn("36 oz (fluid or weight not stated)", text)
        self.assertNotIn("36 oz oz", text)

    def test_carbon_reads_a_fluid_ounce_as_a_volume_not_as_litres_by_default(self):
        self.assertTrue(UnitConverter.is_volume_unit("fl_oz"))
        litres, _ = UnitConverter.convert_volume(36, "fl_oz", to_unit="liters")
        self.assertAlmostEqual(litres, 1.0646, places=3)
        self.assertTrue(UnitConverter.is_mass_unit("oz_wt"))


class CorrectionLeavesRelatedQuantitiesTests(_RehearsalSeason):
    """Finding 5: a rate-only correction on a closed season."""

    def setUp(self):
        super().setUp()
        self.event = self._chemical(
            commercial_name="Surround WP Crop Protectant",
            date=datetime(2026, 4, 25, 12, tzinfo=dt_tz.utc),
            volume_numeric=Decimal("300"),
            volume_unit="lbs",
            application_rate=Decimal("50"),
            application_rate_unit="lb_ac",
        )
        self.url = (
            f"/api/companies/{self.company.id}/establishments/{self.est.id}"
            f"/events/{self.event.id}/amend/?event_type={CHEMICAL_EVENT_TYPE}"
        )

    def _quantities(self):
        # Looked up, not imported, so a tree without it fails as an assertion, not an import.
        from history import amendments

        fn = getattr(amendments, "application_quantities", None)
        self.assertIsNotNone(fn, "history.amendments.application_quantities does not exist")
        return fn(self.event)

    def _correct_rate(self):
        return apply_amendment(
            event=self.event,
            event_type=CHEMICAL_EVENT_TYPE,
            field_name="application_rate",
            new_value="45",
            reason="Rate on the spray log is 45 lb/ac.",
            user=self.user,
        )

    def _get(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_before_the_correction_the_record_agrees(self):
        body = self._get()
        self.assertIn("related_quantities", body)
        self.assertIs(body["related_quantities"]["agrees"], True)

    def test_the_correction_form_shows_the_related_values_and_that_they_disagree(self):
        self._correct_rate()
        body = self._get()
        self.assertIn("related_quantities", body)
        related = body["related_quantities"]
        values = {f["name"]: (f["value"], f["unit"]) for f in related["fields"]}
        self.assertEqual(values["volume_numeric"], ("300", "lbs"))
        self.assertEqual(values["area_numeric"], ("6", "acres"))
        self.assertEqual(values["application_rate"], ("45", "lbs/acre"))
        self.assertIs(related["agrees"], False)
        self.assertEqual(related["computed_amount"], "270 lbs")
        # The form computes against a new value with this factor: 45 x 6 x 1 = 270.
        self.assertAlmostEqual(related["factor"], 1.0)

    def test_the_correction_changes_only_the_field_it_names(self):
        self._correct_rate()
        self.event.refresh_from_db()
        self.assertEqual((self.event.volume_numeric, self.event.area_numeric), (Decimal("300"), Decimal("6")))
        self.assertEqual(self.event.application_rate, Decimal("45"))

    def test_the_export_flags_the_disagreement_on_the_row_and_under_the_correction(self):
        self._correct_rate()
        svc = AuditExportService(self.history, certification_type="organic")
        row_text = _flatten(svc._build_chemical_log())
        self.assertIn("[REVIEW] corrected: rate × area = 270 lbs, not the amount recorded", row_text)
        corrections = _flatten(svc._amendments_table())
        self.assertIn(
            "after the correction to application rate, the amount, area and rate on this record no longer agree. "
            "45 lbs/acre × 6 acres = 270 lbs; the amount recorded is 300 lbs.",
            corrections,
        )

    def test_the_disagreement_reaches_the_generated_pdf(self):
        self._correct_rate()
        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        text = _pdf_text(buf.getvalue())
        self.assertIn("45 lbs/acre × 6 acres = 270 lbs; the amount recorded is 300 lbs.", text)

    def test_a_correction_that_restores_agreement_is_not_flagged(self):
        """The mirror: correcting the AMOUNT to match the new rate clears the flag."""
        self._correct_rate()
        apply_amendment(
            event=self.event,
            event_type=CHEMICAL_EVENT_TYPE,
            field_name="volume_numeric",
            new_value="270",
            reason="Amount follows the corrected rate.",
            user=self.user,
        )
        self.assertIs(self._quantities()["agrees"], True)
        svc = AuditExportService(self.history, certification_type="organic")
        self.assertNotIn("no longer agree", _flatten(svc._amendments_table()))

    def test_a_legacy_oz_amount_is_not_compared(self):
        """Comparing it would decide for the operator which ounce "oz" meant."""
        self.event.volume_unit = "oz"
        self.event.application_rate_unit = "fl_oz_ac"
        self.event.save(update_fields=["volume_unit", "application_rate_unit"])
        result = self._quantities()
        self.assertIsNone(result["agrees"])
        self.assertIsNone(result["factor"])
