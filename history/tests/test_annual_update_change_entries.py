"""§ 205.406 additions/deletions must read as facts, not as Python.

WHAT WENT WRONG
---------------
`OSPAnnualUpdate.additions` and `.deletions` are JSONFields that hold BOTH shapes: a plain
string when the operator typed a sentence, and a structured dict when a UI or a seeder recorded
a field-level change. The packet joined them with `str(a)`, which is correct for the strings and
printed the Python repr for the dicts — so the annual-update table showed a certifier:

    {'new': '24 replant trees, North Block', 'field': 'planting', 'section': 'practices_procedures'}

That is the `[object Object]` failure moved into a compliance document. The § 205.406 filing is
precisely the artifact that tells a certifier what changed on the operation this year, and it
was handing them a dict literal. It was live on the walnut showcase farm — the landing hero —
and invisible to any check that did not actually render the PDF.

Only 4 of the 18 stored entries were dicts, which is why it survived: the common case looked
right.
"""

import io
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from carbon.models import CropType
from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService, _fmt_change_entries
from product.models import Parcel, Product
from users.models import User


class AnnualUpdateChangeEntryFormattingTests(SimpleTestCase):
    def test_plain_strings_pass_through(self):
        """The common shape — the operator wrote a sentence. It must not be decorated."""
        text = "Grandevo WDG added; notified to the certifier 12 Feb 2026"
        self.assertEqual(_fmt_change_entries([text]), text)

    def test_structured_entry_reads_as_a_sentence(self):
        entry = {"new": "24 replant trees, North Block", "field": "planting", "section": "practices_procedures"}
        rendered = _fmt_change_entries([entry])
        self.assertEqual(rendered, "Practices Procedures / Planting: 24 replant trees, North Block")

    def test_no_python_punctuation_survives(self):
        """The actual regression. Fails on the old `str(a)` join.

        Asserted on the SHAPE of the output rather than an exact string, because the defect is
        not 'the wrong words' — it is that a serialization leaked into a document a certifier
        reads. Any future entry shape that reintroduces a repr fails here too.
        """
        entries = [
            {"new": "24 replant trees, North Block", "field": "planting", "section": "practices_procedures"},
            {"old": "Serenade ASO", "new": "Serenade Opti", "field": "input", "section": "inputs_list"},
        ]
        rendered = _fmt_change_entries(entries)
        for token in ("{", "}", "'field':", "'section':", "'new':"):
            self.assertNotIn(token, rendered, f"{token!r} leaked into the annual-update table")

    def test_old_and_new_render_as_a_transition(self):
        entry = {"old": "Serenade ASO", "new": "Serenade Opti", "field": "input", "section": "inputs_list"}
        self.assertIn("Serenade ASO → Serenade Opti", _fmt_change_entries([entry]))

    def test_mixed_shapes_in_one_field(self):
        """Both shapes coexist in the same JSON list — that is how the bug hid."""
        rendered = _fmt_change_entries(
            ["A sentence the operator typed", {"new": "x", "field": "planting", "section": "practices_procedures"}]
        )
        self.assertIn("A sentence the operator typed", rendered)
        self.assertIn("Practices Procedures / Planting: x", rendered)
        self.assertNotIn("{", rendered)

    def test_empty_is_none_not_an_empty_row(self):
        """The table skips None rows; an empty string would print a bare '—' for no reason."""
        self.assertIsNone(_fmt_change_entries([]))
        self.assertIsNone(_fmt_change_entries(None))

    def test_unknown_shape_never_produces_a_repr(self):
        """Defensive: a shape nobody anticipated must still not print braces."""
        rendered = _fmt_change_entries([{"unexpected_key": "some value"}])
        self.assertIn("some value", rendered)
        self.assertNotIn("{", rendered)


class AnnualUpdateRendersThroughTheFormatterTests(TestCase):
    """The unit tests above pass even with the call site reverted — so they are not enough.

    They prove `_fmt_change_entries` works; they say nothing about whether the packet calls it.
    That is the same shape as a fix living inside a `console.log`: present to grep, absent to the
    user. This one renders the actual PDF and reads it back.
    """

    def setUp(self):
        user = User.objects.create_user(email="annual@test.com", password="x")
        company = Company.objects.create(name="Annual Co")
        est = Establishment.objects.create(name="Annual Farm", company=company)
        parcel = Parcel.objects.create(name="Block A", establishment=est, area=2.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-annual-fmt",
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
            start_date=timezone.now() - timedelta(days=300),
            finish_date=timezone.now() - timedelta(days=30),
        )
        osp = OrganicSystemPlan.objects.create(establishment=est, version_number=1, status="active", created_by=user)
        # The exact shape that printed a repr on the walnut showcase farm.
        OSPAnnualUpdate.objects.create(
            prior_osp=osp,
            reporting_year=self.history.start_date.year,
            changes_summary="One structural change this year.",
            additions=[
                {"new": "24 replant trees, North Block", "field": "planting", "section": "practices_procedures"}
            ],
            deletions=[],
            submitted_at=timezone.now() - timedelta(days=20),
        )

    def test_no_dict_repr_reaches_the_rendered_packet(self):
        from pdfminer.high_level import extract_text

        buffer = AuditExportService(self.history, certification_type="usda_organic").generate_pdf()
        pdf = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer
        text = extract_text(io.BytesIO(pdf))

        self.assertIn("24 replant trees, North Block", text, "the addition itself vanished from the packet")
        for token in ("'field':", "'section':", "'new':"):
            self.assertNotIn(token, text, f"{token!r} printed into the certifier packet")
