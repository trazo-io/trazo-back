"""
Post-Harvest Sanitation PDF section tests — P0-6 (2026-04-15).

Covers the new Post-Harvest Sanitation subsection (7 CFR 205.272 + § 205.605)
rendered underneath the Equipment Cleaning Logs table:
- Subsection is suppressed when no cleaning event carries sanitizer detail.
- Fully-documented sanitizer event renders with a compliance attestation.
- Missing ppm / rinse step / NOP reference emits per-event inspector flags.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class PostHarvestSanitationSectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="san@test.com", password="x")
        self.company = Company.objects.create(name="San Farm")
        self.establishment = Establishment.objects.create(name="S1", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Avocado")
        self.history = History.objects.create(
            name="H1",
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
        )

    def _pdf_text(self):
        """Render the PDF and return the raw text contents via pdftotext-less parsing.
        We read the ReportLab flowable stream and extract paragraph text only — enough
        for keyword assertions without invoking a PDF parser binary."""
        service = AuditExportService(self.history, certification_type="organic")
        # Exercise only the section we care about to keep tests fast and
        # independent of unrelated modules (photos, drift, etc.).
        elements = service._build_equipment_section()
        from reportlab.platypus import Paragraph

        texts = []
        for el in elements:
            if isinstance(el, Paragraph):
                texts.append(el.text)
            elif hasattr(el, "_cellvalues"):
                for row in el._cellvalues:
                    for cell in row:
                        if isinstance(cell, Paragraph):
                            texts.append(cell.text)
                        else:
                            texts.append(str(cell))
        return "\n".join(texts)

    def test_no_sanitizer_detail_suppresses_subsection(self):
        # EM event with cleaning data but NO sanitizer fields → no Post-Harvest
        # Sanitation subsection rendered.
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Pressure wash",
            cleaned_by="Miguel",
            shared_with_conventional=True,
        )
        text = self._pdf_text()
        self.assertNotIn("Post-Harvest Sanitation", text)

    def test_fully_documented_sanitizer_renders_attestation(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Pressure wash + brush wash",
            cleaned_by="Miguel",
            shared_with_conventional=True,
            sanitizer_name="Sodium hypochlorite",
            sanitizer_ppm=150,
            rinse_step_documented=True,
            sanitizer_nop_reference="§ 205.605(b) - Sodium hypochlorite",
        )
        text = self._pdf_text()
        self.assertIn("Post-Harvest Sanitation", text)
        self.assertIn("Sodium hypochlorite", text)
        self.assertIn("150", text)
        # Attestation line appears when all four fields populated.
        self.assertIn("recorded, as entered by the operator, for every post-harvest cleaning event", text)
        # Inspector flag does NOT appear when nothing is missing.
        self.assertNotIn("Inspector flag", text)

    def test_missing_ppm_and_rinse_emits_inspector_flag(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Brush wash",
            cleaned_by="Miguel",
            shared_with_conventional=True,
            sanitizer_name="Sodium hypochlorite",
            sanitizer_ppm=None,
            rinse_step_documented=False,
            sanitizer_nop_reference="",
        )
        text = self._pdf_text()
        self.assertIn("Post-Harvest Sanitation", text)
        self.assertIn("Inspector flag", text)
        self.assertIn("concentration (ppm)", text)
        self.assertIn("rinse step", text)
        self.assertIn("regulatory reference", text)

    def test_missing_sanitizer_name_is_flagged(self):
        # Regression: farmer entered ppm but forgot the sanitizer name.
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            cleaning_date=timezone.now().date(),
            cleaning_method="Brush wash",
            cleaned_by="Miguel",
            sanitizer_name="",
            sanitizer_ppm=150,
            rinse_step_documented=True,
            sanitizer_nop_reference="§ 205.605(b) - Sodium hypochlorite",
        )
        text = self._pdf_text()
        self.assertIn("Inspector flag", text)
        self.assertIn("sanitizer name", text)

    def test_sanitizer_only_em_event_still_renders_subsection(self):
        # Regression: EM event with ONLY sanitizer detail (no cleaning_date /
        # method / shared flag) was previously filtered out of cleaning_events
        # and the sanitation subsection was never rendered.
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            area_covered=0.0,
            sanitizer_name="Peracetic acid",
            sanitizer_ppm=80,
            rinse_step_documented=True,
            sanitizer_nop_reference="§ 205.605(b) - Peracetic acid",
        )
        text = self._pdf_text()
        self.assertIn("Post-Harvest Sanitation", text)
        self.assertIn("Peracetic acid", text)
