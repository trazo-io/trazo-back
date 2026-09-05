"""
Tests for the California Pesticide Use Report (PUR / DPR-PML-017C) export.

Covers: fertilizer exclusion, DPR box mapping from F20 fields, per-row
completeness flags, month filtering, fumigation FFM requirement, and CSV shape.
"""

import csv
import io
from datetime import datetime
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.pur_export_service import PUR_COLUMNS, PURExportService
from product.models import Parcel, Product
from users.models import User, WorksIn


class PURExportServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pur@test.com", password="x")
        self.company = Company.objects.create(name="Salinas Citrus Co")
        self.establishment = Establishment.objects.create(
            name="Block 7",
            company=self.company,
            address="123 Grove Rd",
            city="Fresno",
            state="CA",
            zip_code="93701",
        )
        self.parcel = Parcel.objects.create(name="North Orchard", establishment=self.establishment, area=40.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="2026 Oranges",
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
            published=True,
        )

    def _full_pesticide(self, **overrides):
        defaults = dict(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            manufacturer="Corteva",
            date=timezone.make_aware(datetime(2026, 6, 15, 7, 0)),
            application_start=timezone.make_aware(datetime(2026, 6, 15, 7, 0)),
            application_end=timezone.make_aware(datetime(2026, 6, 15, 9, 30)),
            volume="12",
            volume_unit="gal",
            area="8",
            area_unit="acres",
            planted_area="40",
            planted_area_unit="acres",
            operator_id="37-1234",
            site_id="0001",
            application_county="Fresno",
            mtrs_section="12",
            mtrs_township="14S",
            mtrs_range="22E",
            mtrs_base_meridian="M",
            epa_registration_number="62719-621",
            application_method_structured="air_blast",
            block_id="B7",
        )
        defaults.update(overrides)
        return ChemicalEvent.objects.create(**defaults)

    def test_excludes_fertilizers(self):
        self._full_pesticide()
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="UN-32",
            date=timezone.make_aware(datetime(2026, 6, 16, 8, 0)),
        )
        rows = PURExportService(self.establishment, 6, 2026).build_rows()
        self.assertEqual(len(rows), 1, "fertilizer must be excluded from the PUR")
        self.assertEqual(rows[0]["product_and_manufacturer"], "Entrust SC / Corteva")

    def test_dpr_box_mapping(self):
        self._full_pesticide()
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        self.assertEqual(row["operator_id"], "37-1234")
        self.assertEqual(row["operator_name"], "Salinas Citrus Co")
        self.assertEqual(row["city"], "Fresno")
        self.assertEqual(row["site_id"], "0001")
        # Box 10 carries the CAC 2-digit county code + name (CalAgPermits validates on the code).
        self.assertEqual(row["county"], "10 (Fresno)")
        self.assertEqual(row["section"], "12")
        self.assertEqual(row["base_meridian"], "M")
        self.assertEqual(row["commodity"], "Navel Orange")
        self.assertEqual(row["field_location"], "North Orchard")
        self.assertEqual(row["acreage_treated"], "8 acres")
        self.assertEqual(row["planted_area"], "40 acres")
        self.assertEqual(row["total_product_used"], "12 gal")
        self.assertEqual(row["application_method"], "Ground (air-blast)")
        self.assertEqual(row["application_start"], "2026-06-15 0700")
        self.assertEqual(row["application_end"], "2026-06-15 0930")
        self.assertEqual(row["epa_registration_number"], "62719-621")
        self.assertEqual(row["missing"], [], f"unexpected gaps: {row['notes']}")

    def test_completeness_flags_missing(self):
        # Minimal event: only the fields a careless quick-entry would have.
        self._full_pesticide(
            operator_id="",
            site_id="",
            application_county="",
            ca_dpr_permit_county="",
            mtrs_section="",
            mtrs_township="",
            mtrs_range="",
            mtrs_base_meridian="",
            application_start=None,
            application_end=None,
            epa_registration_number="",
            planted_area="",
        )
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        missing = set(row["missing"])
        for key in ("operator_id", "site_id", "county", "section", "application_start", "epa_registration_number"):
            self.assertIn(key, missing, f"{key} should be flagged missing")
        self.assertIn("Missing required", row["notes"])

    def test_month_filter(self):
        self._full_pesticide()  # June
        self._full_pesticide(
            date=timezone.make_aware(datetime(2026, 5, 15, 7, 0)),
            commercial_name="May Spray",
        )
        rows = PURExportService(self.establishment, 6, 2026).build_rows()
        self.assertEqual(len(rows), 1, "only June applications belong in the June PUR")

    def test_fumigation_requires_ffm(self):
        self._full_pesticide(application_method_structured="fumigation", ffm_code="")
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        self.assertEqual(row["application_method"], "Fume")
        self.assertIn("ffm_code", row["missing"])

    def test_csv_structure(self):
        self._full_pesticide()
        csv_bytes = PURExportService(self.establishment, 6, 2026).to_csv().read().decode("utf-8-sig")
        self.assertIn("California Pesticide Use Report (DPR-PML-017C)", csv_bytes)
        self.assertIn("Salinas Citrus Co", csv_bytes)
        self.assertIn("3. Operator ID/Permit No.", csv_bytes)
        self.assertIn("28. Product and Manufacturer", csv_bytes)
        self.assertIn("Entrust SC / Corteva", csv_bytes)

    def test_summary_counts(self):
        self._full_pesticide()  # complete
        self._full_pesticide(operator_id="", site_id="", commercial_name="Sparse")  # incomplete
        summary = PURExportService(self.establishment, 6, 2026).summary()
        self.assertEqual(summary["application_count"], 2)
        self.assertEqual(summary["complete_count"], 1)
        self.assertEqual(summary["incomplete_count"], 1)
        self.assertEqual(summary["filing_deadline"], "2026-07-10")
        self.assertEqual(summary["form"], "DPR-PML-017C")

    # ── Preview-only fields (JSON summary) ──────────────────────────────────────────
    #
    # The modal says "open the event to complete them". Until 2026-09-01 the row carried
    # nothing to open it WITH, no date when box 17 was one of the blanks (two "Kocide 3000-O /
    # Ground (air-blast)" rows, indistinguishable), and the gaps only as the CSV's English
    # sentence — which the view then stripped of its key list before responding.

    def test_preview_rows_carry_identity_and_structured_gaps(self):
        event = self._full_pesticide(operator_id="", application_start=None, application_end=None)
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        self.assertEqual(row["event_id"], event.id)
        self.assertEqual(row["event_type"], 2)  # history.constants.CHEMICAL_EVENT_TYPE
        self.assertEqual(row["parcel_id"], self.parcel.id)
        # Box 17 is blank, so the DPR-formatted start is "" — the event's own date is the
        # row's identity, and it is always present (it is what the month filter reads).
        self.assertEqual(row["application_start"], "")
        self.assertTrue(row["event_date"].startswith("2026-06-15"), row["event_date"])
        self.assertEqual(set(row["missing"]), {"operator_id", "application_start", "application_end"})
        self.assertEqual(row["flags"], [])

    def test_flags_are_coded_for_the_client_to_label(self):
        self._full_pesticide(
            application_county="Maricopa",
            extra_data={"tank_mix": "Dyne-Amic", "is_summary": True},
        )
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        by_code = {f["code"]: f for f in row["flags"]}
        self.assertEqual(set(by_code), {"county_unrecognized", "tank_mix_unexported", "aggregate_event"})
        self.assertEqual(by_code["county_unrecognized"]["county"], "Maricopa")
        self.assertEqual(by_code["tank_mix_unexported"]["partners"], "Dyne-Amic")
        # The CSV prose is untouched: the county commissioner still reads English sentences.
        self.assertIn("not a recognized CA county", row["notes"])
        self.assertIn("Aggregate/summary event", row["notes"])

    def test_adjuvant_row_is_flagged_and_openable(self):
        event = self._full_pesticide(
            tank_mix_partners=[{"commercial_name": "Dyne-Amic", "epa_registration_number": "5905-501"}]
        )
        adj = PURExportService(self.establishment, 6, 2026).build_rows()[1]
        # An adjuvant line is a child of the primary event — opening it opens that event.
        self.assertEqual(adj["event_id"], event.id)
        self.assertEqual(adj["parcel_id"], self.parcel.id)
        self.assertEqual(adj["flags"], [{"code": "adjuvant_line", "primary": "Entrust SC"}])

    def test_preview_only_fields_never_reach_csv(self):
        """The filed CSV keeps the DPR column contract: no ids, no codes, no extra cells."""
        self._full_pesticide(operator_id="", application_county="Maricopa")
        csv_text = PURExportService(self.establishment, 6, 2026).to_csv().read().decode("utf-8-sig")
        parsed = list(csv.reader(io.StringIO(csv_text)))
        expected_header = [h for _k, h, _r in PUR_COLUMNS]
        header_idx = next(i for i, r in enumerate(parsed) if r[:1] == ["3. Operator ID/Permit No."])
        self.assertEqual(parsed[header_idx], expected_header)
        for data_row in parsed[header_idx + 1 :]:
            self.assertEqual(len(data_row), len(expected_header), data_row)
        for leaked in ("event_id", "event_type", "parcel_id", "event_date", "county_unrecognized"):
            self.assertNotIn(leaked, csv_text)

    def test_county_code_resolution(self):
        # San Diego -> code 37; case/suffix-insensitive.
        row = self._make_row(application_county="San Diego County")
        self.assertEqual(row["county"], "37 (San Diego County)")

    def test_unrecognized_county_blanked_and_flagged(self):
        # A county name that is not a CA county must NOT emit an unvalidatable box 10.
        row = self._make_row(application_county="Springfield")
        self.assertEqual(row["county"], "")
        self.assertIn("county", row["missing"])
        self.assertIn("not a recognized CA county", row["notes"])

    def test_blank_quantity_flags_box_24_and_19(self):
        # Units default to gal/acres on the model; a blank VALUE must still flag the
        # numeric boxes (24 total product, 19 acreage treated) as missing.
        row = self._make_row(volume="", volume_numeric=None, area="", area_numeric=None)
        self.assertEqual(row["total_product_used"], "")
        self.assertEqual(row["acreage_treated"], "")
        missing = set(row["missing"])
        self.assertIn("total_product_used", missing)
        self.assertIn("acreage_treated", missing)

    def test_adjuvant_emits_separate_pur_row(self):
        self._full_pesticide(
            tank_mix_partners=[
                {
                    "commercial_name": "Dyne-Amic",
                    "manufacturer": "Helena",
                    "epa_registration_number": "5905-501",
                    "volume": "1",
                    "volume_unit": "gal",
                    "organic_approved": True,
                }
            ]
        )
        rows = PURExportService(self.establishment, 6, 2026).build_rows()
        self.assertEqual(len(rows), 2, "adjuvant must emit its own PUR line")
        adj = rows[1]
        self.assertEqual(adj["epa_registration_number"], "5905-501")
        self.assertEqual(adj["total_product_used"], "1 gal")
        self.assertEqual(adj["product_and_manufacturer"], "Dyne-Amic / Helena")
        # shared context copied from the primary row
        self.assertEqual(adj["county"], "10 (Fresno)")
        self.assertIn("Tank-mix adjuvant", adj["notes"])

    def test_empty_adjuvant_entries_skipped(self):
        self._full_pesticide(tank_mix_partners=[{"commercial_name": "", "epa_registration_number": ""}])
        rows = PURExportService(self.establishment, 6, 2026).build_rows()
        self.assertEqual(len(rows), 1, "blank adjuvant rows must be skipped")

    # ── 2026-09-05 audit fixes (documentation/audits: CA PUR flow vs CDPR sources) ──────

    def test_pcb_applications_are_not_the_growers_to_report(self):
        """PUE Compendium Vol. 1 Ch. 4 p. 4-8: the grower "should not include applications made
        by pest control businesses on his/her use report". 3 CCR 6626(b) makes the business the
        reporter. Before this, every hired pass was exported as the grower's own — twice filed."""
        self._full_pesticide()
        hired = self._full_pesticide(
            commercial_name="Metam CLR",
            applied_by_pcb=True,
            pcb_name="Valley Ag Spray Inc.",
            date=timezone.make_aware(datetime(2026, 6, 20, 5, 0)),
        )
        service = PURExportService(self.establishment, 6, 2026)
        rows, excluded = service.build()
        self.assertEqual([r["product_and_manufacturer"] for r in rows], ["Entrust SC / Corteva"])
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["event_id"], hired.id)
        self.assertEqual(excluded[0]["pcb_name"], "Valley Ag Spray Inc.")
        self.assertEqual(excluded[0]["product"], "Metam CLR")
        summary = service.summary()
        self.assertEqual(summary["application_count"], 1)
        self.assertEqual(summary["pcb_excluded_count"], 1)
        # Visible in the filed worksheet, never silently dropped.
        csv_text = service.to_csv().read().decode("utf-8-sig")
        self.assertIn("NOT reported here: 1 (Valley Ag Spray Inc.)", csv_text)
        self.assertIn("3 CCR 6626(b)", csv_text)
        self.assertNotIn("Metam CLR", csv_text.split("3. Operator ID/Permit No.")[1])

    def test_chemigation_is_other_not_ground(self):
        """CalPIP glossary: "O - Other application methods ... may include: paint, ear tag,
        injection, chemigation". Box 21 ticked Ground for every drip/fertigation pass."""
        for method in ("chemigation", "drip", "fertigation"):
            row = self._make_row(application_method_structured=method)
            self.assertEqual(row["application_method"], "Other (chemigation)", method)
            ChemicalEvent.objects.all().delete()
        self.assertEqual(
            self._make_row(application_method_structured="injection")["application_method"], "Other (injection)"
        )
        ChemicalEvent.objects.all().delete()
        self.assertEqual(
            self._make_row(application_method_structured="subsurface")["application_method"], "Ground (subsurface)"
        )
        ChemicalEvent.objects.all().delete()
        self.assertEqual(
            self._make_row(application_method_structured="air_blast")["application_method"], "Ground (air-blast)"
        )

    def test_hectares_convert_to_acres(self):
        """DPR unit-treated codes are A/S/U/C/T/P/K — no hectare. A "12.5 ha" box 19 cannot be keyed."""
        row = self._make_row(
            area="10", area_unit="ha", planted_area="20", planted_area_unit="ha", volume="24.71", volume_unit="gal"
        )
        self.assertEqual(row["acreage_treated"], "24.71 acres")
        self.assertEqual(row["planted_area"], "49.42 acres")
        # Box 26 is per ACRE: 24.71 gal over 24.71 acres.
        self.assertEqual(row["rate_per_acre"], "1.00 gal/acre")
        self.assertIn("converted from hectares (20 ha, 10 ha)", row["notes"])
        self.assertIn({"code": "area_converted_from_ha", "from": "20 ha, 10 ha"}, row["flags"])
        self.assertEqual(row["missing"], [])

    def test_square_feet_stay_as_entered_and_have_no_per_acre_rate(self):
        row = self._make_row(area="4000", area_unit="sq_ft", volume="2", volume_unit="gal")
        # The form's slug never reaches the filing; the box reads the unit the way the CAC does.
        self.assertEqual(row["acreage_treated"], "4000 sq ft")
        self.assertEqual(row["rate_per_acre"], "")

    def test_blank_area_unit_never_becomes_a_per_acre_rate(self):
        # A rate needs BOTH units. An area with no unit is not "probably acres" on a state filing.
        row = self._make_row(area="10", area_unit="", volume="5", volume_unit="gal")
        self.assertEqual(row["rate_per_acre"], "")

    def test_rate_uses_the_same_amount_as_box_24(self):
        # Box 24 falls back to volume_numeric when the legacy string is blank; box 26 must too.
        row = self._make_row(volume="", volume_numeric=12, volume_unit="gal", area="8", area_unit="acres")
        # DecimalField(decimal_places=2) renders "12.00"; the form allows decimals in box 24.
        self.assertEqual(row["total_product_used"], "12.00 gal")
        self.assertEqual(row["rate_per_acre"], "1.50 gal/acre")

    def test_unrecognized_county_is_named_in_a_multi_county_preamble(self):
        self._full_pesticide(application_county="Yolo")
        self._full_pesticide(application_county="Maricopa", commercial_name="Out of state")
        service = PURExportService(self.establishment, 6, 2026)
        counties = service.summary()["counties"]
        self.assertEqual(counties[-1], {"code": "", "name": "Maricopa", "count": 1})
        csv_text = service.to_csv().read().decode("utf-8-sig")
        self.assertIn("Maricopa (not a recognized CA county) — 1", csv_text)

    def test_operator_and_site_ids_fall_back_to_farm_and_parcel(self):
        """The county issues the OIN to the OPERATOR and the site ID to the SITE (3 CCR 6622).
        A record logged through the quick form or voice never shows the CA block, so without
        the fallbacks box 3 and box 8 were blank on every such row."""
        self.establishment.ca_operator_id = "10-26-0007"
        self.establishment.save(update_fields=["ca_operator_id"])
        self.parcel.ca_site_id = "N-01"
        self.parcel.save(update_fields=["ca_site_id"])
        row = self._make_row(operator_id="", ca_dpr_permit_number="", site_id="")
        self.assertEqual(row["operator_id"], "10-26-0007")
        self.assertEqual(row["site_id"], "N-01")
        self.assertNotIn("operator_id", row["missing"])
        self.assertNotIn("site_id", row["missing"])
        ChemicalEvent.objects.all().delete()
        # The event's own value always wins over the farm/parcel default.
        row = self._make_row(operator_id="10-26-9999", site_id="0002")
        self.assertEqual(row["operator_id"], "10-26-9999")
        self.assertEqual(row["site_id"], "0002")

    def test_rows_group_by_county_and_summary_lists_counties(self):
        """A use report goes to the commissioner of the county where the work was performed
        (3 CCR 6626(a)). A two-county month is two filings; the rows must not interleave."""
        self._full_pesticide(application_county="Yolo", date=timezone.make_aware(datetime(2026, 6, 1, 7, 0)))
        self._full_pesticide(
            application_county="Solano",
            commercial_name="Solano spray",
            date=timezone.make_aware(datetime(2026, 6, 2, 7, 0)),
        )
        self._full_pesticide(
            application_county="Yolo",
            commercial_name="Yolo later",
            date=timezone.make_aware(datetime(2026, 6, 3, 7, 0)),
        )
        service = PURExportService(self.establishment, 6, 2026)
        rows = service.build_rows()
        self.assertEqual([r["county"] for r in rows], ["48 (Solano)", "57 (Yolo)", "57 (Yolo)"])
        self.assertEqual(
            [r["product_and_manufacturer"] for r in rows][1:], ["Entrust SC / Corteva", "Yolo later / Corteva"]
        )
        self.assertEqual(
            service.summary()["counties"],
            [{"code": "48", "name": "Solano", "count": 1}, {"code": "57", "name": "Yolo", "count": 2}],
        )
        csv_text = service.to_csv().read().decode("utf-8-sig")
        self.assertIn("Counties: 48 Solano — 1, 57 Yolo — 2.", csv_text)
        self.assertIn("3 CCR 6626(a)", csv_text)
        # Preview-only grouping keys never become CSV columns.
        self.assertNotIn("county_code", csv_text)

    def test_single_county_month_has_no_county_preamble(self):
        self._full_pesticide()
        csv_text = PURExportService(self.establishment, 6, 2026).to_csv().read().decode("utf-8-sig")
        self.assertNotIn("Counties:", csv_text)

    def _make_row(self, **overrides):
        self._full_pesticide(**overrides)
        return PURExportService(self.establishment, 6, 2026).build_rows()[0]


class PURExportStateGateTests(TestCase):
    """The PUR is a California filing (3 CCR 6626) and the CSV embeds CA county
    codes, so the endpoint must not serve it to an out-of-state farm.

    Before this gate a Florida grower could generate a document titled "California
    Pesticide Use Report (DPR-PML-017C)" carrying a note that their real county was
    "not a recognized CA county" — a misleading artifact on a regulator-facing
    export, not merely an empty one.
    """

    def setUp(self):
        from subscriptions.testing import grant_compliance_exports

        self.user = User.objects.create_user(email="gate@test.com", password="x")
        self.company = Company.objects.create(name="Gate Co")
        # The PUR export is a Compliance artifact (2026-08-14, subscriptions/gating.py). Without a
        # plan every case below would 403 before reaching the STATE check these tests are about,
        # and the two 404 cases would pass for the wrong reason.
        grant_compliance_exports(self.company)
        self.url = "/api/histories/pur-export/"

    def _establishment(self, state):
        est = Establishment.objects.create(name=f"Farm {state or 'blank'}", company=self.company, state=state)
        WorksIn.objects.create(user=self.user, company=self.company, role="CA")
        return est

    def _get(self, est):
        # Auth is httpOnly-cookie JWT, so Django's session force_login yields 401 here.
        client = APIClient()
        client.force_authenticate(user=self.user)
        return client.get(self.url, {"establishment_id": est.id, "month": 6, "year": 2026})

    def test_json_preview_keeps_missing_keys_and_flags(self):
        """The view used to pop the gap-key list before responding, leaving the modal with the
        English `notes` sentence as its only rendering of a gap (untranslatable by construction)."""
        est = self._establishment("CA")
        parcel = Parcel.objects.create(name="Row 1", establishment=est, area=1.0)
        history = History.objects.create(
            name="Gate season",
            start_date=timezone.now(),
            product=Product.objects.create(name="Lemon"),
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        event = ChemicalEvent.objects.create(
            history=history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Kocide 3000-O",
            date=timezone.make_aware(datetime(2026, 6, 3, 6, 0)),
        )
        body = self._get(est).json()
        self.assertEqual(body["application_count"], 1)
        row = body["rows"][0]
        self.assertEqual(row["event_id"], event.id)
        self.assertEqual(row["parcel_id"], parcel.id)
        self.assertIn("operator_id", row["missing"])
        self.assertIsInstance(row["flags"], list)
        self.assertNotIn("_missing_required", row)

    def test_empty_month_csv_is_not_filed_in_documents(self):
        """The modal disables the download for an empty month; a direct API call used to file a
        zero-application worksheet under Documents → Exports every time it was asked."""
        from documents.models import GeneratedDocument

        est = self._establishment("CA")
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(self.url, {"establishment_id": est.id, "month": 6, "year": 2026, "export_format": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(GeneratedDocument.objects.filter(establishment=est, source="pur").count(), 0)

    def test_california_farm_is_allowed(self):
        response = self._get(self._establishment("CA"))
        self.assertEqual(response.status_code, 200)

    def test_full_state_name_still_resolves_to_california(self):
        # 35 of 105 live rows stored "California" rather than "CA".
        response = self._get(self._establishment("California"))
        self.assertEqual(response.status_code, 200)

    def test_out_of_state_farm_gets_404(self):
        response = self._get(self._establishment("FL"))
        self.assertEqual(response.status_code, 404)

    def test_unknown_state_gets_404_rather_than_being_assumed_californian(self):
        response = self._get(self._establishment(""))
        self.assertEqual(response.status_code, 404)


class MTRSAndCountyFallbackTests(TestCase):
    """PUR boxes that could never be filled before 2026-08-09.

    Boxes 11-14 (Section / Township / Range / Base & Meridian) are read from
    `ChemicalEvent.mtrs_*`, which is capturable NOWHERE in the UI — so every exported
    row was incomplete no matter how diligently the grower filled the spray form. What
    they do have is the parcel's PLSS descriptor, one string: "S14 T8N R2E".

    Same for box 10 (County): read only from the event, while the operator entered it on
    the Parcel Application.
    """

    def test_parses_the_plss_descriptor_the_grower_actually_wrote(self):
        from history.services.pur_export_service import _parse_mtrs

        self.assertEqual(
            _parse_mtrs("S14 T8N R2E"),
            {"section": "14", "township": "8N", "range": "2E", "base_meridian": ""},
        )
        self.assertEqual(
            _parse_mtrs("Sec 14 Twp 8N Rge 2E MD"),
            {"section": "14", "township": "8N", "range": "2E", "base_meridian": "MD"},
        )
        self.assertEqual(
            _parse_mtrs("14/8N/2E"),
            {"section": "14", "township": "8N", "range": "2E", "base_meridian": ""},
        )

    def test_never_guesses_on_a_state_filing(self):
        """A wrong section number on a PUR is worse than an empty box."""
        from history.services.pur_export_service import _parse_mtrs

        blank = {"section": "", "township": "", "range": "", "base_meridian": ""}
        for junk in ("", None, "   ", "north forty", "the block by the creek", "T8N"):
            self.assertEqual(_parse_mtrs(junk), blank, f"{junk!r} must not parse")

    def test_county_falls_back_to_the_parcel_application_answer(self):
        from history.services.pur_export_service import _parcel_county

        self.assertEqual(_parcel_county(SimpleNamespace(application_answers={"county": "Yolo"})), "Yolo")
        self.assertEqual(_parcel_county(SimpleNamespace(application_answers={})), "")
        self.assertEqual(_parcel_county(SimpleNamespace(application_answers=None)), "")
        self.assertEqual(_parcel_county(SimpleNamespace(application_answers="not-a-dict")), "")
