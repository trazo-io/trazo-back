"""`Parcel.area` is HECTARES, and every US-facing surface must convert it.

Twice now a certifier-facing document has printed the stored hectare value with the word
"acres" beside it:

  * 2026-08-20 — the Common OSP `field_and_crop_information` workbook, column
    "Acreage or square feet:".
  * 2026-08-20, same day, found by a certifier reading the generated packet — the **Parcel
    Application** PDF, "Mapped area: 11.4931 acres." for a 28.4-acre block. That is the
    § 205.202 page a reviewer works from, so the operation's 59.4 acres presented as 24.0 and
    would have produced a certificate and a fee for the wrong acreage.

The root cause was that 2.47105 lived in six unrelated modules and the unit lived in a
`help_text`, so a new surface had nothing to inherit. The conversion now belongs to the model
that owns the field (`Parcel.area_acres` / `Parcel.area_display`).
"""

from django.test import TestCase

from company.models import Company, Establishment
from product.models import Parcel


class ParcelAreaUnitTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Area Co")
        self.est = Establishment.objects.create(name="Area Farm", company=self.company)
        # 11.4931 ha is the real Ridge Block: 28.4 acres.
        self.parcel = Parcel.objects.create(name="Ridge Block", establishment=self.est, area=11.4931)

    def test_area_acres_converts(self):
        self.assertAlmostEqual(self.parcel.area_acres, 28.4, places=1)

    def test_area_display_carries_both_units(self):
        """A reader who suspects a hectare figure must be able to tell without dividing."""
        text = self.parcel.area_display()
        self.assertIn("28.4 acres", text)
        self.assertIn("11.49 ha", text)

    def test_the_parcel_application_pdf_prints_acres(self):
        """The surface that regressed. Renders the § 205.202 parcel-map block and reads it back."""
        from reportlab.lib.styles import getSampleStyleSheet

        from certifications.services.osp_module_pdf import _parcel_embed_flowables

        styles = getSampleStyleSheet()
        styles.add(styles["BodyText"].clone("body"))
        elements = _parcel_embed_flowables("parcel_map", self.parcel, styles)
        text = " ".join(getattr(el, "text", "") or "" for el in elements)

        self.assertIn("28.4 acres", text)
        # The regression proper: the hectare figure must never appear next to the word "acres".
        self.assertNotIn("11.4931 acres", text)
        self.assertNotIn("11.49 acres", text)

    def test_a_zero_area_parcel_does_not_crash_the_converter(self):
        p = Parcel(name="Unset", establishment=self.est, area=None)
        self.assertEqual(p.area_acres, 0.0)
        self.assertIn("0.0 acres", p.area_display())
