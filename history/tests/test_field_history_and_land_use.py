"""
USDA forms #1 (Field History / Previous Land Use) and #2 (Land Use History Verification).

WHY (2026-08-12):

**#1** asks three columns per material — "Material / Product Brand Name", "Manufacturer",
"Application Date(s)". `ParcelCropHistory.substances_applied` is a single prose blob and
answers none of them; a 36-month eligibility check needs the DATE, and "roundup, some 10-10-10"
has not got one. `substance_applications` adds structured rows ALONGSIDE the blob. The blob is
never parsed into them — splitting prose means guessing which word is a brand and which is a
manufacturer, and that guess would land in an eligibility determination.

Two rendering defects were found while wiring it, both pre-existing:

  * the field-history column headed "Last Prohibited Substance" rendered
    `date_last_prohibited`, so a certifier read "Last Prohibited Substance: 2019-05-12" —
    and `last_prohibited_substance`, the NAME that USDA asks for on every field, was never
    printed at all
  * the affidavit table repeated the same mislabel

**#2** prints a "☐ No materials applied" checkbox that Trazo had no column for, so an empty
`yearly_history` was ambiguous in the worst direction: unanswered and "the signer declared
none" looked identical. Rendering the first as the second manufactures the § 205.202(b)
attestation the whole eligibility determination rests on. Three states now, never two.
"""

import datetime
import io
import re

from django.test import TestCase
from django.utils import timezone

from certifications.models import LandownerAffidavit
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService, _last_prohibited_input
from product.models import Parcel, ParcelCropHistory, Product
from users.models import User


class LastProhibitedInputTests(TestCase):
    """Name AND date. Either can stand alone; neither is invented."""

    def _entry(self, name, date):
        return ParcelCropHistory(last_prohibited_substance=name, date_last_prohibited=date)

    def test_renders_both_when_both_are_recorded(self):
        got = _last_prohibited_input(self._entry("Glyphosate", datetime.date(2019, 5, 12)))
        self.assertEqual(got, "Glyphosate — 2019-05-12")

    def test_a_name_without_a_date_still_renders(self):
        """Useless for the 36-month window, but it is what the operator recorded."""
        self.assertEqual(_last_prohibited_input(self._entry("Glyphosate", None)), "Glyphosate")

    def test_a_date_without_a_name_still_renders(self):
        self.assertEqual(_last_prohibited_input(self._entry(None, datetime.date(2019, 5, 12))), "2019-05-12")

    def test_neither_recorded_is_a_dash_not_a_declaration_of_none(self):
        """ "—" means unrecorded. "None applied" would be an attestation nobody made."""
        self.assertEqual(_last_prohibited_input(self._entry(None, None)), "—")
        self.assertEqual(_last_prohibited_input(self._entry("   ", None)), "—")


class AffidavitNegativeDeclarationTests(TestCase):
    """`no_materials_applied` is tri-state on purpose."""

    def test_only_an_explicit_true_counts_as_a_declaration(self):
        self.assertTrue(LandownerAffidavit(no_materials_applied=True).declared_no_materials_applied())

    def test_unanswered_is_not_a_declaration(self):
        self.assertFalse(LandownerAffidavit(no_materials_applied=None).declared_no_materials_applied())

    def test_an_empty_history_is_not_a_declaration(self):
        """The trap this field exists to close: absence of rows is not a denial."""
        affidavit = LandownerAffidavit(no_materials_applied=None, yearly_history=[])
        self.assertFalse(affidavit.declared_no_materials_applied())

    def test_false_means_materials_were_applied(self):
        self.assertFalse(LandownerAffidavit(no_materials_applied=False).declared_no_materials_applied())


class FieldHistorySerializerRoundTripTests(TestCase):
    """The form posts every field it renders, so blank optional inputs arrive as "".

    Adding the "Date Applied" input to the field-history form immediately created this:
    DRF's DateField rejects "" with "Date has wrong format", 400ing the whole entry over a
    field the form itself labels optional — the same class as seed_purchase_date,
    cleaning_date and ca_dpr_permit_expires before it.
    """

    def setUp(self):
        user = User.objects.create_user(email="rt@test.com", password="x")
        company = Company.objects.create(name="RT Co")
        establishment = Establishment.objects.create(name="RT1", company=company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)
        self.user = user

    def _serializer(self, **overrides):
        from product.serializers import ParcelCropHistorySerializer

        data = {
            "parcel": self.parcel.id,
            "year": 2023,
            "crop_grown": "Walnuts",
            "production_method": "organic",
        }
        data.update(overrides)
        return ParcelCropHistorySerializer(data=data)

    def test_a_blank_date_is_accepted_and_stored_as_null(self):
        serializer = self._serializer(date_last_prohibited="")
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data.get("date_last_prohibited"))

    def test_a_real_date_still_parses(self):
        """The coercion must not swallow genuine values."""
        serializer = self._serializer(date_last_prohibited="2023-05-12")
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["date_last_prohibited"], datetime.date(2023, 5, 12))

    def test_structured_material_rows_survive_a_round_trip(self):
        rows = [{"material": "Roundup PowerMAX", "manufacturer": "Bayer", "application_dates": "3/14 and 6/2"}]
        serializer = self._serializer(substance_applications=rows, date_last_prohibited="")
        self.assertTrue(serializer.is_valid(), serializer.errors)
        entry = serializer.save()
        entry.refresh_from_db()
        self.assertEqual(entry.substance_applications, rows)

    def test_a_partial_update_does_not_clear_the_block_id(self):
        """The form renders no block_id, so it must never send one — and PATCH must not
        reset it. This is the clobber class that hit four other editors."""
        from product.serializers import ParcelCropHistorySerializer

        entry = ParcelCropHistory.objects.create(
            parcel=self.parcel, year=2023, crop_grown="Walnuts", block_id="rows 1-40"
        )
        serializer = ParcelCropHistorySerializer(entry, data={"crop_grown": "Almonds"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        entry.refresh_from_db()
        self.assertEqual(entry.block_id, "rows 1-40")


class FieldHistoryPacketTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="fh@test.com", password="x")
        company = Company.objects.create(name="FH Co")
        establishment = Establishment.objects.create(name="FH1", company=company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="FH Production",
            start_date=timezone.now(),
            product=product,
            parcel=self.parcel,
            operator=user,
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

    def _text(self):
        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def test_the_substance_name_reaches_the_paper_beside_its_date(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2023,
            crop_grown="Walnuts",
            last_prohibited_substance="Glyphosate",
            date_last_prohibited=datetime.date(2023, 5, 12),
        )
        text = self._text()
        self.assertIn("Last Prohibited Input", text)
        self.assertIn("Glyphosate — 2023-05-12", text)
        # The old header claimed a substance over a date-only cell.
        self.assertNotIn("Last Prohibited Substance |", text)

    def test_structured_material_rows_render_brand_manufacturer_and_dates(self):
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2023,
            crop_grown="Walnuts",
            substances_applied="roundup, some 10-10-10",
            substance_applications=[
                {"material": "Roundup PowerMAX", "manufacturer": "Bayer", "application_dates": "3/14 and 6/2"}
            ],
        )
        text = self._text()
        self.assertIn("Roundup PowerMAX", text)
        self.assertIn("mfr: Bayer", text)
        self.assertIn("applied: 3/14 and 6/2", text)
        # The prose blob survives untouched alongside the structured rows.
        self.assertIn("roundup, some 10-10-10", text)

    def test_malformed_structured_rows_do_not_break_the_export(self):
        """This column is JSON a client writes; it will eventually contain junk."""
        ParcelCropHistory.objects.create(
            parcel=self.parcel,
            year=2023,
            crop_grown="Walnuts",
            substance_applications=["not a dict", {}, {"material": "Real Product"}],
        )
        text = self._text()
        self.assertIn("Real Product", text)

    def test_no_material_lines_when_nothing_is_structured(self):
        ParcelCropHistory.objects.create(parcel=self.parcel, year=2023, crop_grown="Walnuts")
        self.assertNotIn("Materials by year", self._text())

    def test_affidavit_distinguishes_declared_none_from_unanswered(self):
        """The heart of #2. These two must never render the same way."""
        LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="J. Prior",
            no_materials_applied=True,
            management_period_start=datetime.date(2019, 1, 1),
            management_period_end=datetime.date(2022, 12, 31),
        )
        LandownerAffidavit.objects.create(parcel=self.parcel, previous_manager_name="K. Unanswered")
        text = self._text()
        self.assertIn("None applied (declared)", text)
        self.assertIn("Not answered", text)
        self.assertIn("2019-01-01 – 2022-12-31", text)

    def test_an_affidavit_that_contradicts_itself_is_flagged_not_silently_resolved(self):
        """Declared "none applied" over a table that lists applications.

        Showing only the declaration hides the rows a certifier needs; showing only the rows
        hides a signed statement. Neither is Trazo's call to make — same treatment as the
        page-1/page-12 sales disagreement.
        """
        LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="J. Contradictory",
            no_materials_applied=True,
            yearly_history=[{"year": 2021, "land_use": "corn", "inputs": "atrazine"}],
        )
        text = self._text()
        self.assertIn("CONTRADICTION", text)
        self.assertIn("declare that no materials were applied", text)

    def test_affidavit_shows_the_management_window_it_attests_for(self):
        """Without it, a signer who managed one of three years reads as covering all three."""
        LandownerAffidavit.objects.create(
            parcel=self.parcel,
            previous_manager_name="J. Prior",
            management_period_start=datetime.date(2021, 3, 1),
        )
        text = self._text()
        self.assertIn("Management Period", text)
        # A half-open window prints the known end and marks the unknown one, rather than
        # silently implying it runs to today.
        self.assertIn("2021-03-01 – ?", text)
