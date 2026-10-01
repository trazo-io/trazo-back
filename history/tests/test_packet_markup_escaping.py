"""
Operator free text must survive the certifier packet verbatim.

WHY (2026-08-12): ReportLab `Paragraph` parses a mini-HTML dialect. `_cell` escaped for
table cells, but hand-built `Paragraph(f"...{value}...")` lines did not — and `_label_value`,
which 39 call sites use for farm name, contacts, lot IDs and seed source, interpolated the
raw value. Two failure modes, both measured on the real service:

    "Walnuts & almonds <north lot>"  -> rendered as "Walnuts & almonds". The operator's own
                                       text SILENTLY DESTROYED, in a document whose entire
                                       purpose is to record it. Same class as the truncation
                                       bug `_cell`'s docstring describes.
    "Bob & Sons <b>bold"             -> ValueError. The whole export fails; a farm named
                                       "Smith & Sons <Ranch>" could not produce a packet.

An ampersand in a farm name is not an edge case — "Smith & Sons" is one of the most ordinary
names in US agriculture.
"""

import io
import re

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService, _esc, _val
from product.models import Parcel, Product
from users.models import User

# Ampersand, angle brackets, a tag-shaped run, and an unclosed tag — the last is what raised.
HOSTILE = "Smith & Sons <Ranch> 3 < 7 <b>unclosed"


class EscapeHelperTests(TestCase):
    def test_escapes_the_three_xml_significant_characters(self):
        self.assertEqual(_esc("a & b < c > d"), "a &amp; b &lt; c &gt; d")

    def test_escapes_ampersand_before_angle_brackets(self):
        """Order matters: escaping "<" first would then re-escape its own "&"."""
        self.assertEqual(_esc("<"), "&lt;")
        self.assertEqual(_esc("&lt;"), "&amp;lt;")

    def test_keeps_val_semantics_for_empty_values(self):
        self.assertEqual(_esc(None), _val(None))
        self.assertEqual(_esc(""), _val(""))
        self.assertEqual(_esc(None, fallback="n/a"), "n/a")


class PacketSurvivesHostileFreeTextTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="esc@test.com", password="x")
        company = Company.objects.create(name="Esc Co")
        self.establishment = Establishment.objects.create(name=HOSTILE, company=company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=self.establishment, area=42.5)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Esc Production",
            start_date=timezone.now(),
            product=product,
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

    def _text(self):
        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        from pdfminer.high_level import extract_text

        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def test_a_farm_name_with_an_unclosed_tag_does_not_fail_the_export(self):
        """This raised ValueError before the fix — no packet at all for that operation."""
        self.assertGreater(len(self._text()), 0)

    def test_the_farm_name_reaches_the_paper_intact(self):
        """Not just "did not crash" — the characters must actually be THERE."""
        self.assertIn(HOSTILE, self._text())

    def test_every_operator_controlled_string_can_hold_markup_at_once(self):
        """One render with hostile text in EVERY operator-controlled string.

        Written this way on purpose: field-by-field would be 14 renders (~30s) and would
        still only prove the fields someone thought to list. Setting them all at once puts
        hostile text through every code path in a single build, so any remaining raw
        `Paragraph(f"...")` site fails here. Three were found this way — the cover-page
        title, `_label_value`, and the § 205.307 lot-ID sentence — and only the first was
        found by reading the code.
        """
        from history.models import ProductionEvent

        self.establishment.name = HOSTILE
        self.establishment.save()
        self.parcel.name = HOSTILE
        self.parcel.buffer_zones = [{"direction": HOSTILE, "crop_grown_in_buffer": HOSTILE, "buffer_type": HOSTILE}]
        self.parcel.save()
        self.history.lot_id = HOSTILE
        self.history.name = HOSTILE
        self.history.sold_to = HOSTILE
        self.history.save()
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description=HOSTILE,
            storage_location=HOSTILE,
            buffer_disposition="sold_conventional",
            buffer_disposition_quantity=HOSTILE,
            buffer_disposition_evidence=HOSTILE,
        )

        text = self._text()
        # Not merely "it rendered" — the values must survive to the page.
        self.assertIn(HOSTILE, text)
        self.assertGreater(text.count(HOSTILE), 3, "hostile text reached only a few of its render sites")

    def test_buffer_detail_line_preserves_operator_text(self):
        """The hand-built buffer detail Paragraph, the site where this was first found."""
        self.parcel.buffer_zones = [{"direction": "North", "crop_grown_in_buffer": "Walnuts & almonds <north lot>"}]
        self.parcel.save()
        self.assertIn("crop grown in buffer: Walnuts & almonds <north lot>", self._text())
