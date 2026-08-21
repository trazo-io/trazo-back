"""
Tests for the four Common OSP required attachments.

The load-bearing rule is `NeverGuessTests`: a generated regulatory attachment must leave a cell
blank rather than invent an answer. This matters most on "Name and Application Date of Last
Prohibited Input", which USDA requires for EVERY field including already-organic ones — a wrong
value there is a false statement about land history, which is exactly what a 3-year transition
turns on.
"""

from datetime import date

from django.test import TestCase

import openpyxl

from certifications.models import OrganicSystemPlan
from certifications.services.common_osp_workbooks import WORKBOOKS, WORKBOOKS_BY_KEY, build_workbook, workbook_summary
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent
from product.models import Parcel, ParcelCropHistory, Product
from users.models import User, WorksIn


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Tule River Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="Block 8", establishment=self.establishment, area=40.0)

    def _sheet(self, key):
        wb = openpyxl.load_workbook(build_workbook(self.establishment, key))
        return wb.active

    def _header_row(self, ws):
        for row in ws.iter_rows(values_only=True):
            if row and row[0] in (
                "Location Name:",
                "Organic Product (Required)",
                "Product",
                "Product Name",
            ):
                return list(row)
        raise AssertionError("header row not found")

    def _data_rows(self, ws):
        header_seen = False
        out = []
        for row in ws.iter_rows(values_only=True):
            if header_seen and any(c is not None for c in row):
                out.append(list(row))
            if row and row[0] in (
                "Location Name:",
                "Organic Product (Required)",
                "Product",
                "Product Name",
            ):
                header_seen = True
        return out


class HeadersMatchUSDATests(_Base):
    """Headers are verbatim from the USDA .xlsx files — a paraphrase breaks the match."""

    def test_field_and_crop_information_headers(self):
        headers = self._header_row(self._sheet("field_and_crop_information"))
        self.assertEqual(
            headers,
            [
                "Location Name:",
                "Field or Parcel ID:",
                "Acreage or square feet:",
                "Status:",
                "Crop(s)/Cover Crops:",
                "Name and Application Date of Last Prohibited Input:",
            ],
        )

    def test_materials_list_headers(self):
        headers = self._header_row(self._sheet("materials_list"))
        self.assertEqual(
            headers,
            ["Product", "Manufacturer", "Reason for use", "In use", "Intended for use", "Comments"],
        )

    def test_supplier_list_headers(self):
        headers = self._header_row(self._sheet("supplier_list"))
        self.assertEqual(headers[:2], ["Product Name", "Supplier Name"])
        self.assertIn("Certifier", headers[2])

    def test_product_list_carries_every_export_market_column(self):
        headers = self._header_row(self._sheet("crop_livestock_product_list"))
        for market in ("Canada", "Japan", "EU/UK", "Korea", "Switzerland", "Taiwan"):
            self.assertIn(market, headers)

    def test_every_workbook_renders_with_an_excel_safe_tab_name(self):
        """🔴 Regression. Excel rejects \\ / ? * [ ] : in a sheet TAB name and openpyxl raises.
        "Crop/Livestock Product List" hit this and 500'd the download for that workbook — a
        smoke test over only two of the four had missed it. The A1 cell still carries the USDA
        title verbatim; only the tab is sanitized."""
        for key, spec in WORKBOOKS_BY_KEY.items():
            ws = self._sheet(key)
            self.assertNotIn("/", ws.title, key)
            self.assertLessEqual(len(ws.title), 31, key)
            # The verbatim USDA title survives in the first cell.
            self.assertEqual(ws["A1"].value, spec.title, key)

    def test_all_four_workbooks_exist(self):
        self.assertEqual(len(WORKBOOKS), 4)
        for key in (
            "field_and_crop_information",
            "crop_livestock_product_list",
            "materials_list",
            "supplier_list",
        ):
            self.assertIn(key, WORKBOOKS_BY_KEY)


class NeverGuessTests(_Base):
    """🔴 A blank cell is a prompt. An invented one is a false statement on a regulatory form."""

    def test_last_prohibited_input_is_blank_when_not_recorded(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2025,
            crop_grown="Walnuts",
            production_method="organic",
            # The operator recorded a substances summary but never named the last prohibited
            # input. The summary lists everything applied that year and cannot identify which
            # was last, so the cell must stay empty.
            substances_applied="Compost, sulfur, neem oil",
        )
        row = self._data_rows(self._sheet("field_and_crop_information"))[0]
        self.assertIsNone(row[5], "last-prohibited cell must not be inferred from substances_applied")

    def test_last_prohibited_input_renders_name_and_date_when_recorded(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2025,
            crop_grown="Walnuts",
            production_method="organic",
            last_prohibited_substance="Glyphosate",
            date_last_prohibited=date(2023, 6, 12),
        )
        row = self._data_rows(self._sheet("field_and_crop_information"))[0]
        self.assertEqual(row[5], "Glyphosate, 6/12/2023")

    def test_last_prohibited_renders_whichever_half_exists(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2025, crop_grown="Walnuts", last_prohibited_substance="Glyphosate"
        )
        self.assertEqual(self._data_rows(self._sheet("field_and_crop_information"))[0][5], "Glyphosate")

    def test_status_is_blank_rather_than_assumed_organic(self):
        """A parcel with no recorded production method is not assumed to be certified."""
        ParcelCropHistory.objects.create(parcel=self.parcel, year=2025, crop_grown="Walnuts")
        self.assertIsNone(self._data_rows(self._sheet("field_and_crop_information"))[0][3])

    def test_parcel_with_no_history_still_appears_with_blank_cells(self):
        """The field exists and must be listed; its unknowns are the operator's to fill."""
        rows = self._data_rows(self._sheet("field_and_crop_information"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "Block 8")
        self.assertIsNone(rows[0][4])
        self.assertIsNone(rows[0][5])

    def test_in_use_checkbox_is_left_for_the_operator(self):
        """USDA defines "In Use" as CURRENTLY used. Trazo only knows a product was applied at
        some point — an input last sprayed in 2019 is not in use — so ticking it would be the
        same guess this module refuses to make on the last-prohibited-input cell."""
        history = History.objects.create(
            name="2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=date(2026, 3, 1),
        )
        ChemicalEvent.objects.create(history=history, type="FE", date=date(2026, 4, 1), commercial_name="Fish Emulsion")
        row = self._data_rows(self._sheet("materials_list"))[0]
        self.assertEqual(row[0], "Fish Emulsion")
        self.assertIsNone(row[3], "'In use' is the operator's statement, not ours")
        self.assertIsNone(row[4])

    def test_seed_supplier_product_column_names_the_crop_not_the_season(self):
        """🔴 Regression. This read `history.name`, a season label like "Hass Avocado Hillside
        Grove A 2026", and wrote it into the USDA "Product Name" column — describing a season to
        a certifier who expects the product the supplier provided."""
        history = History.objects.create(
            name="Hass Avocado Hillside Grove A 2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Avocado"),
            start_date=date(2026, 3, 1),
        )
        ProductionEvent.objects.create(
            history=history,
            type="PL",
            date=date(2026, 3, 5),
            seed_supplier_name="Saticoy Grove Nursery",
        )
        row = next(r for r in self._data_rows(self._sheet("supplier_list")) if r[1] == "Saticoy Grove Nursery")
        self.assertEqual(row[0], "Avocado")

    def test_formula_injection_is_defused(self):
        """These files go to a CERTIFIER. Excel executes any cell starting with = + - @, and every
        string here is farmer-typed free text."""
        history = History.objects.create(
            name="2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=date(2026, 3, 1),
        )
        ChemicalEvent.objects.create(
            history=history,
            type="FE",
            date=date(2026, 4, 1),
            commercial_name='=HYPERLINK("http://evil.example","click")',
        )
        cell = self._data_rows(self._sheet("materials_list"))[0][0]
        self.assertTrue(cell.startswith("'"), f"formula not defused: {cell!r}")

    def test_beneficial_organism_suppliers_reach_the_supplier_list(self):
        """🔴 Regression, second instance. The workbook's USDA instruction line opens with
        "live animals", and a beneficial-insect release is bought from a named supplier exactly
        like a fertiliser is. `PestManagementEvent.beneficial_supplier` had held it since the BR
        subtype shipped and no row was ever emitted — the same omission soil amendments had.
        """
        from history.models import PestManagementEvent

        history = History.objects.create(
            name="2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=date(2026, 3, 1),
        )
        PestManagementEvent.objects.create(
            history=history,
            type="BR",
            date=date(2026, 5, 1),
            beneficial_species="Trichogramma platneri",
            beneficial_supplier="Rincon-Vitova Insectaries",
        )
        row = next(r for r in self._data_rows(self._sheet("supplier_list")) if r[1] == "Rincon-Vitova Insectaries")
        self.assertEqual(row[0], "Trichogramma platneri")
        self.assertIsNone(row[2], "certifier must be blank, not guessed")

    def test_beneficial_supplier_without_a_species_still_names_the_category(self):
        """A row reading "— / Rincon-Vitova" tells a certifier nothing about what was released."""
        from history.models import PestManagementEvent

        history = History.objects.create(
            name="2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=date(2026, 3, 1),
        )
        PestManagementEvent.objects.create(
            history=history,
            type="BR",
            date=date(2026, 5, 1),
            beneficial_supplier="Rincon-Vitova Insectaries",
        )
        row = next(r for r in self._data_rows(self._sheet("supplier_list")) if r[1] == "Rincon-Vitova Insectaries")
        self.assertEqual(row[0], "Beneficial organisms")

    def test_supplier_certifier_column_is_never_invented(self):
        """The supplier's certifier comes off THEIR organic certificate, which Trazo lacks."""
        history = History.objects.create(
            name="2026",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=date(2026, 3, 1),
        )
        ChemicalEvent.objects.create(
            history=history,
            type="FE",
            date=date(2026, 4, 1),
            commercial_name="Fish Emulsion",
            supplier_name="Coastal Harvest",
        )
        row = self._data_rows(self._sheet("supplier_list"))[0]
        self.assertEqual(row[0], "Fish Emulsion")
        self.assertEqual(row[1], "Coastal Harvest")
        self.assertIsNone(row[2], "certifier must be blank, not guessed")


class ContentTests(_Base):
    def _history(self):
        return History.objects.create(
            name="2026 Season",
            parcel=self.parcel,
            product=Product.objects.create(name="Walnut"),
            start_date=date(2026, 3, 1),
        )

    def test_materials_list_deduplicates_repeated_applications(self):
        """The Materials List is a list of PRODUCTS — an input sprayed 3 times is one row."""
        history = self._history()
        for day in (1, 8, 15):
            ChemicalEvent.objects.create(
                history=history, type="FU", date=date(2026, 4, day), commercial_name="Kocide 3000"
            )
        rows = self._data_rows(self._sheet("materials_list"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Kocide 3000")

    def test_materials_reason_for_use_maps_from_subtype(self):
        history = self._history()
        ChemicalEvent.objects.create(history=history, type="HE", date=date(2026, 4, 1), commercial_name="Weed Slayer")
        self.assertEqual(self._data_rows(self._sheet("materials_list"))[0][2], "Weed control")

    def test_every_sheet_carries_provenance_and_the_operator_authorship_reminder(self):
        for key in WORKBOOKS_BY_KEY:
            text = "\n".join(str(c) for row in self._sheet(key).iter_rows(values_only=True) for c in row if c)
            self.assertIn("Generated by Trazo", text, key)
            self.assertIn("205.201(a)", text, key)
            self.assertIn("Blank cells", text, key)

    def test_declarations_appear_on_the_forms_that_have_them(self):
        text = "\n".join(
            str(c) for row in self._sheet("field_and_crop_information").iter_rows(values_only=True) for c in row if c
        )
        self.assertIn("must be available for inspection and copying", text)

    def test_unknown_workbook_key_raises(self):
        with self.assertRaises(ValueError):
            build_workbook(self.establishment, "not_a_workbook")


class CurrentSeasonCropTests(_Base):
    """The Field and Crop form must not contradict the packet it ships inside.

    Found 2026-08-21 on a pilot renewal: field history was filled through 2025, the farm had
    2026 seasons running, and the form filed "Full-season cover crop" for a parcel the same
    packet listed as growing onions in 2026. The § 205.202(b) history stays the source for
    prior years; the crop in the ground now comes from the season the operator opened.
    """

    def _crop_cell(self):
        ws = self._sheet("field_and_crop_information")
        rows = self._data_rows(ws)
        self.assertTrue(rows, "no data rows")
        return rows[0][4]

    def test_a_season_newer_than_the_history_names_the_current_crop(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2025, crop_grown="Full-season cover crop", production_method="organic"
        )
        product = Product.objects.create(name="Onions")
        History.objects.create(
            parcel=self.parcel,
            name="Onions 2026",
            start_date=date(2026, 4, 1),
            product=product,
            production_method="organic",
        )
        cell = self._crop_cell()
        self.assertIn("Onions", cell)
        self.assertIn("2026", cell)
        self.assertNotIn("cover crop", cell.lower())

    def test_history_that_is_current_still_wins(self):
        """A history row for the season year is the operator's own statement — do not override it."""
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2026, crop_grown="Carrots (Bolero)", production_method="organic"
        )
        product = Product.objects.create(name="Onions")
        History.objects.create(
            parcel=self.parcel,
            name="Onions 2026",
            start_date=date(2026, 4, 1),
            product=product,
            production_method="organic",
        )
        self.assertEqual(self._crop_cell(), "Carrots (Bolero)")

    def test_no_season_and_no_history_leaves_the_cell_blank(self):
        self.assertIsNone(self._crop_cell())


class SummaryTests(_Base):
    def test_summary_counts_rows_and_remaining_blanks(self):
        ParcelCropHistory.objects.create(parcel=self.parcel, year=2025, crop_grown="Walnuts")
        entry = next(s for s in workbook_summary(self.establishment) if s["key"] == "field_and_crop_information")
        self.assertEqual(entry["rows"], 1)
        self.assertGreater(entry["blank_cells"], 0)
        self.assertFalse(entry["error"])

    def test_summary_exposes_no_score_or_percentage(self):
        for entry in workbook_summary(self.establishment):
            for key in entry:
                for banned in ("score", "grade", "percent", "complete"):
                    self.assertNotIn(banned, key.lower())


class AttachmentsAPITests(_Base):
    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.user = User.objects.create_user(email="grower-wb@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")
        # Downloading a workbook is a Compliance artifact (2026-08-15, subscriptions/gating.py) —
        # the four Common OSP attachments are named on the price list. The summary branch
        # (no `?workbook=`) stays open on every plan; only the .xlsx download is gated, so
        # `test_summary_*` here would pass either way and the download cases need a plan.
        from subscriptions.testing import grant_compliance_exports

        grant_compliance_exports(self.company)
        self.client.force_authenticate(user=self.user)

    def _url(self, query=""):
        base = (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}"
            f"/osps/{self.osp.id}/attachments/"
        )
        return base + query

    def test_summary_lists_all_four(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["workbooks"]), 4)

    def test_download_returns_an_xlsx_attachment(self):
        response = self.client.get(self._url("?workbook=materials_list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])
        self.assertIn("Materials_List.xlsx", response["Content-Disposition"])

    def test_unknown_workbook_is_rejected(self):
        self.assertEqual(self.client.get(self._url("?workbook=nope")).status_code, 400)

    def test_non_member_cannot_download_another_operations_attachments(self):
        other_company = Company.objects.create(name="Other Co")
        other_est = Establishment.objects.create(name="Other", company=other_company, state="CA")
        other_osp = OrganicSystemPlan.objects.create(establishment=other_est, version_number=1, status="draft")
        url = f"/api/companies/{other_company.id}/establishments/{other_est.id}" f"/osps/{other_osp.id}/attachments/"
        self.assertIn(self.client.get(url).status_code, (403, 404))

    def test_anonymous_is_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self._url()).status_code, (401, 403))
