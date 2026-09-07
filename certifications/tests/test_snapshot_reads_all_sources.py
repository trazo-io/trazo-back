"""The frozen submission PDF must print the whole materials list, not two of its four sources.

🔴 2026-09-07 — `osp_pdf_snapshot.generate_osp_snapshot_pdf` read `approved_omri_products` and
`approved_national_list_substances` and nothing else. `approved_wsda_materials` and the
operator-entered `plan_material_entries` were dropped in silence.

Why this artifact and not another: it is the one the certifier receives, it is frozen on submit,
its own footer calls it "the exact content submitted", and the operator cannot fix it —
post-submission edits to the approved-inputs list are refused. So a plan whose materials are
WSDA-listed or operator-entered printed

    "No structured inputs attached to this OSP."

three inches below a § 205.201(a)(2) narrative that listed every one of them, because the
narrative compiler reads `plan_materials()` and this renderer did not. One document, two answers,
and the wrong one is the one that cannot be corrected.

The operator-entered case is not exotic. CCOF NOPB41 §A names *fertilizers, compost, manure,
gypsum, limestone* in its own prompt — materials no catalog supplies, which is the entire reason
`PlanMaterialEntry` exists.
"""

from unittest.mock import patch

from django.test import TestCase

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry, WSDAMaterial
from company.models import Company, Establishment


def _story_text(osp) -> str:
    """The Paragraph text the generator appends, before ReportLab compresses it.

    Grepping rendered PDF bytes is unreliable — the streams are ASCII85+FlateDecode — so this
    intercepts `build()` and reads the flowables, the same technique the existing snapshot tests
    in `test_drift_detector.py` use.
    """
    from certifications.services import osp_pdf_snapshot

    captured = {}

    def fake_build(self, story, **kwargs):
        captured["story"] = story

    with patch.object(osp_pdf_snapshot.SimpleDocTemplate, "build", autospec=True, side_effect=fake_build):
        osp_pdf_snapshot.generate_osp_snapshot_pdf(osp)
    return " ".join(getattr(f, "text", "") for f in captured["story"])


class SnapshotRendersEverySourceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Calapooia Bend Farms LLC")
        cls.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=cls.company, state="OR")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.establishment, version_number=1, status="draft")

        cls.nl = NationalListSubstance.objects.create(
            substance_name="Lime sulfur",
            substance_name_normalized="lime sulfur",
            cfr_section="205.601",
            subsection="e",
            status="allowed",
        )
        cls.omri = OMRIProduct.objects.create(
            omri_id="dow-2900",
            product_name="Entrust SC Naturalyte Insect Control",
            manufacturer="Dow Agrosciences, LLC",
        )
        cls.wsda = WSDAMaterial.objects.create(
            wsda_id="2948",
            brand_name="Nature Safe 13-0-0 Feather Meal Fertilizer",
            manufacturer="Nature Safe",
        )

    def _attach_all(self):
        self.osp.approved_national_list_substances.add(self.nl)
        self.osp.approved_omri_products.add(self.omri)
        self.osp.approved_wsda_materials.add(self.wsda)
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Rexius Organic Compost",
            manufacturer="Rexius",
            listing_basis="none_unlisted",
        )

    def test_all_four_sources_reach_the_frozen_pdf(self):
        self._attach_all()
        text = _story_text(self.osp)

        self.assertIn("Approved Inputs", text)
        self.assertIn("Lime sulfur", text)
        self.assertIn("Entrust SC Naturalyte Insect Control", text)
        # The two that were dropped.
        self.assertIn("Nature Safe 13-0-0 Feather Meal Fertilizer", text)
        self.assertIn("Rexius Organic Compost", text)

    def test_every_source_gets_its_own_heading(self):
        self._attach_all()
        text = _story_text(self.osp)
        for heading in ("National List", "OMRI", "WSDA", "Operator-entered"):
            self.assertIn(heading, text, f"missing group heading: {heading}")

    def test_a_wsda_only_plan_is_not_reported_as_empty(self):
        """The exact false statement: a plan WITH materials printing "No structured inputs"."""
        self.osp.approved_wsda_materials.add(self.wsda)
        text = _story_text(self.osp)

        self.assertNotIn("No structured inputs", text)
        self.assertIn("Nature Safe 13-0-0 Feather Meal Fertilizer", text)

    def test_an_operator_entered_only_plan_is_not_reported_as_empty(self):
        """CCOF NOPB41 §A's own examples — compost, manure, gypsum, limestone."""
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="On-farm compost",
            listing_basis="none_unlisted",
        )
        text = _story_text(self.osp)

        self.assertNotIn("No structured inputs", text)
        self.assertIn("On-farm compost", text)

    def test_an_operator_entered_row_never_claims_a_listing_it_lacks(self):
        """`listing_statement` is server-computed and printed verbatim. An unlisted material
        says it has no listing — it must never acquire "listed"/"approved"/"verified" from
        passing through a renderer."""
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="On-farm compost",
            listing_basis="none_unlisted",
        )
        text = _story_text(self.osp).lower()

        self.assertIn("no third-party listing on file", text)
        for forbidden in ("omri listed", "wsda listed", "approved by", "verified"):
            self.assertNotIn(forbidden, text, f"snapshot over-claims: {forbidden!r}")

    def test_a_fabricated_wsda_identifier_never_reaches_the_certifier(self):
        """A certifier who looks up `WSDA-REG-*` finds nothing — WSDA issues no such id.
        The brand still prints; the invented string does not."""
        fake = WSDAMaterial.objects.create(
            wsda_id="WSDA-REG-BIOAG-2025-003", brand_name="Serenade Opti", manufacturer="Bayer"
        )
        self.osp.approved_wsda_materials.add(fake)
        text = _story_text(self.osp)

        self.assertIn("Serenade Opti", text)
        self.assertNotIn("WSDA-REG-", text)

    def test_a_prohibited_row_is_qualified_not_listed_as_ordinary(self):
        """§ 205.602 substances live in the same catalogue and the write path refuses them —
        but a row predating that guard, or one added by a seeder, must not print here as an
        ordinary input on the plan."""
        banned = NationalListSubstance.objects.create(
            substance_name="Ash from manure burning",
            substance_name_normalized="ash from manure burning",
            cfr_section="205.602",
            status="prohibited",
        )
        self.osp.approved_national_list_substances.add(banned)
        text = _story_text(self.osp)

        self.assertIn("Ash from manure burning", text)
        self.assertIn("PROHIBITED", text)

    def test_a_genuinely_empty_plan_still_says_so(self):
        """The fallback is correct when it is TRUE — the defect was it firing when it was not."""
        text = _story_text(self.osp)
        self.assertIn("No structured inputs", text)

    def test_an_unknown_source_would_appear_rather_than_vanish(self):
        """⛔ Grouping is derived from the rows, never from a hardcoded tuple of source names.
        A fifth source must show up unstyled rather than disappear the way WSDA and
        operator-entered rows did."""
        from certifications.services import osp_pdf_snapshot
        from certifications.services.plan_materials import PlanMaterial

        self._attach_all()
        real = osp_pdf_snapshot.plan_materials if hasattr(osp_pdf_snapshot, "plan_materials") else None
        self.assertIsNone(real, "plan_materials is imported inside the function; patch its home")

        with patch(
            "certifications.services.plan_materials.plan_materials",
            return_value=[PlanMaterial(name="Seed treatment X", source="AOSCA")],
        ):
            text = _story_text(self.osp)

        self.assertIn("AOSCA", text)
        self.assertIn("Seed treatment X", text)
