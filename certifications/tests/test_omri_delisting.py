"""An OMRI listing that has lapsed must stop being claimed, without losing the plan row.

Measured, not hypothetical. Diffing OMRI's own published Crop Products List across three
weeks (2026-09-05 -> 2026-09-26): 54 products added, 6 removed, and every one of the six
returns HTTP 404 at its own certificate URL:

    bav-16360  NUTRINATIVA@ Multimineral Fertilizante Foliar
    miz-18207  BioArmor Corn & Soy
    pil-11670  Prathista Aishwarya Organic Nutritional & Complete Fertilizer
    snc-15981  Sierra Natural Science SNS DC Disease & Fungal Control Concentrate
    snc-15983  Sierra Natural Science SNS HydroBiotics Irrigation Line Cleaner Concentrate
    snc-15985  Sierra Natural Science SNS PC Insecticide Concentrate

That is roughly a hundred a year. Re-seeding could not see any of it: `update_or_create`
only ever touches rows the incoming file contains, so a product OMRI had withdrawn kept
rendering in Trazo as an OMRI listing. Same defect class as every other one this codebase
has removed, arriving by omission rather than by invention.

Two properties are under test, and they pull against each other on purpose:

    the CLAIM lapses    Trazo may not state an OMRI listing OMRI no longer publishes
    the RECORD stays    the operator did approve that material; deleting the row cascades
                        the approved-inputs M2M and empties their § 205.201(a)(2) list
"""

from datetime import date

from django.core.management import call_command
from django.test import TestCase

from certifications.models import OMRIProduct, OrganicSystemPlan
from certifications.services.plan_materials import PlanMaterial, plan_materials
from company.models import Company, Establishment


class DelistedRowStillPrintsButStopsClaimingTests(TestCase):
    """`plan_materials()` is the one author of a material's line. It marks the lapse there."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Cascade Ridge LLC")
        cls.farm = Establishment.objects.create(name="Cascade Ridge Orchards", company=cls.company, state="WA")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.farm, version_number=1, status="active")
        cls.live = OMRIProduct.objects.create(
            omri_id="moi-2794", product_name="Grandevo", manufacturer="Marrone Bio Innovations"
        )
        cls.lapsed = OMRIProduct.objects.create(
            omri_id="snc-15985",
            product_name="Sierra Natural Science SNS PC Insecticide Concentrate",
            manufacturer="Sierra Natural Science",
            delisted_on=date(2026, 9, 26),
        )
        cls.osp.approved_omri_products.add(cls.live, cls.lapsed)

    def _row(self, omri_id):
        return next(r for r in plan_materials(self.osp) if omri_id in (r.identifier or ""))

    def test_the_delisted_product_is_still_on_the_plan(self):
        """NEVER dropped. The operator approved it; the row is their filing, not OMRI's."""
        self.assertEqual(len(plan_materials(self.osp)), 2)

    def test_the_lapse_is_stated_on_the_line(self):
        line = self._row("snc-15985").display()
        self.assertIn("no longer on the OMRI list as of 2026-09-26", line)
        self.assertIn("confirm the product's status with your certifier", line)

    def test_a_current_listing_is_not_marked(self):
        self.assertNotIn("no longer on the OMRI list", self._row("moi-2794").display())

    def test_the_lapse_is_not_worded_as_prohibition(self):
        """A withdrawn listing says OMRI stopped vouching, NOT that the substance is barred
        under § 205.602. Wording it as prohibition would manufacture a compliance finding
        out of a paperwork lapse, which is the mirror image of claiming a listing that
        expired."""
        line = self._row("snc-15985").display()
        self.assertNotIn("PROHIBITED", line)
        self.assertFalse(self._row("snc-15985").prohibited)

    def test_the_certifier_facing_form_carries_it_too(self):
        line = self._row("snc-15985").display(stated_absences=True)
        self.assertIn("no longer on the OMRI list", line)

    def test_a_row_with_no_delisting_renders_exactly_as_before(self):
        """Guards against the marker leaking onto every row via a falsy-value slip."""
        row = PlanMaterial(name="Grandevo", source="OMRI", identifier="OMRI #moi-2794")
        self.assertNotIn("[REVIEW]", row.display())


class SeederReconcilesDelistingsTests(TestCase):
    """`seed_omri_minimal` infers a delisting from ABSENCE, which is why it is fenced."""

    def _seed(self, **kwargs):
        call_command("seed_omri_minimal", verbosity=0, **kwargs)

    def test_a_full_edition_marks_what_fell_off_the_list(self):
        """A product not in the committed CSV is dated to the edition that revealed it."""
        ghost = OMRIProduct.objects.create(omri_id="zzz-99999", product_name="Withdrawn Product")
        self._seed()
        ghost.refresh_from_db()
        self.assertIsNotNone(ghost.delisted_on)

    def test_products_on_the_edition_are_left_alone(self):
        self._seed()
        self.assertFalse(OMRIProduct.objects.filter(omri_id="moi-2794", delisted_on__isnull=False).exists())

    def test_a_returning_product_is_unmarked(self):
        """Listings come back. A stale marker would keep denying a listing the grower holds."""
        row = OMRIProduct.objects.create(omri_id="moi-2794", product_name="Grandevo", delisted_on=date(2026, 9, 26))
        self._seed()
        row.refresh_from_db()
        self.assertIsNone(row.delisted_on)

    def test_a_delisted_product_is_never_deleted(self):
        """The whole reason this is a FLAG. `--reset` emptied every plan on 2026-09-07 by
        cascading this same M2M; delisting must not find a new route to the same outcome."""
        ghost = OMRIProduct.objects.create(omri_id="zzz-99999", product_name="Withdrawn Product")
        self._seed()
        self.assertTrue(OMRIProduct.objects.filter(pk=ghost.pk).exists())

    def test_a_partial_file_delists_nothing(self):
        """The guard that matters most. Absence is only evidence when the file is a whole
        edition; a truncated CSV would otherwise mark thousands of live products withdrawn
        in one pass, and every plan citing them would print a lapse that never happened."""
        import csv
        import tempfile

        from certifications.management.commands.seed_omri_minimal import MIN_FULL_EDITION_ROWS

        survivor = OMRIProduct.objects.create(omri_id="zzz-99999", product_name="Still Listed")
        with tempfile.NamedTemporaryFile("w", suffix=".csv", newline="", delete=False) as fh:
            writer = csv.DictWriter(fh, fieldnames=["omri_id", "product_name", "list_edition_date"])
            writer.writeheader()
            writer.writerow({"omri_id": "moi-2794", "product_name": "Grandevo", "list_edition_date": "2026-09-26"})
            path = fh.name

        from certifications.management.commands import seed_omri_minimal

        original = seed_omri_minimal._DATA_FILE
        seed_omri_minimal._DATA_FILE = path
        try:
            self._seed()
        finally:
            seed_omri_minimal._DATA_FILE = original

        survivor.refresh_from_db()
        self.assertIsNone(survivor.delisted_on)
        self.assertGreater(MIN_FULL_EDITION_ROWS, 1)

    def test_the_thresholds_are_stated_not_magic(self):
        from certifications.management.commands.seed_omri_minimal import MAX_DELIST_FRACTION, MIN_FULL_EDITION_ROWS

        self.assertGreaterEqual(MIN_FULL_EDITION_ROWS, 1000)
        self.assertLess(MAX_DELIST_FRACTION, 0.1)


class DelistingTravelsToTheClientTests(TestCase):
    """The panel renders whatever arrives, so the lapse has to be IN the payload."""

    def test_the_serializer_emits_the_field(self):
        from certifications.serializers import _ApprovedOMRIInline

        self.assertIn("delisted_on", _ApprovedOMRIInline().fields)

    def test_the_serialized_value_is_the_stored_one(self):
        from certifications.serializers import _ApprovedOMRIInline

        product = OMRIProduct.objects.create(
            omri_id="snc-15985", product_name="SNS PC Insecticide Concentrate", delisted_on=date(2026, 9, 26)
        )
        self.assertEqual(_ApprovedOMRIInline(product).data["delisted_on"], "2026-09-26")

    def test_a_current_listing_serializes_null(self):
        from certifications.serializers import _ApprovedOMRIInline

        product = OMRIProduct.objects.create(omri_id="moi-2794", product_name="Grandevo")
        self.assertIsNone(_ApprovedOMRIInline(product).data["delisted_on"])


class DelistedRowIsNeverFoldedAwayTests(TestCase):
    """The review note must survive the merge with an operator-entered row.

    `_fold_into_entry` promotes a catalog row's `source` and `identifier` onto the operator's
    own entry. Folding a withdrawn OMRI row therefore printed "OMRI #<id>" on the merged line
    while dropping the one sentence saying OMRI no longer lists it, which reassembles the
    exact claim this flag exists to stop. Reachable in practice: `_listing_basis_for` links an
    operator entry to an approved OMRI product by normalized name, which is the fold condition.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Tule River LLC")
        cls.farm = Establishment.objects.create(name="Tule River Citrus", company=cls.company, state="CA")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.farm, version_number=1, status="active")
        cls.product = OMRIProduct.objects.create(
            omri_id="snc-15985",
            product_name="SNS PC Insecticide Concentrate",
            delisted_on=date(2026, 9, 26),
        )
        cls.osp.approved_omri_products.add(cls.product)

    def _lines(self):
        return [row.display() for row in plan_materials(self.osp)]

    def test_the_note_survives_an_operator_entry_of_the_same_name(self):
        from certifications.models import PlanMaterialEntry

        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="SNS PC Insecticide Concentrate",
            listing_basis="omri_listed",
            omri_product=self.product,
        )
        self.assertTrue(
            any("no longer on the OMRI list" in line for line in self._lines()),
            f"the lapse vanished when the row folded: {self._lines()}",
        )

    def test_a_current_listing_still_folds(self):
        """The exemption is narrow. A listed product merges with its entry as before, so this
        does not quietly double every row on the materials list."""
        from certifications.models import PlanMaterialEntry

        current = OMRIProduct.objects.create(omri_id="moi-2794", product_name="Grandevo")
        self.osp.approved_omri_products.add(current)
        PlanMaterialEntry.objects.create(
            osp=self.osp, product_name="Grandevo", listing_basis="omri_listed", omri_product=current
        )
        self.assertEqual(sum(1 for line in self._lines() if "Grandevo" in line), 1)


class DelistingReconciliationIsCaseInsensitiveTests(TestCase):
    """`omri_id` is written verbatim; `seen_codes` is lowercased. They have to agree.

    `looks_like_omri_code` normalizes before checking shape, so "DOW-2900" passes validation
    and is stored as typed. A case-sensitive `__in` then misses it, stamping `delisted_on` on
    a product the same run just re-seeded, with no way to clear it afterwards.
    `seed_omri_from_csv` writes arbitrary codes with no shape check, so this is reachable.
    """

    def test_an_uppercase_code_is_not_delisted_by_its_own_reseed(self):
        from certifications.management.commands import seed_omri_minimal

        OMRIProduct.objects.create(omri_id="MOI-2794", product_name="Grandevo")
        call_command("seed_omri_minimal", verbosity=0)
        row = OMRIProduct.objects.get(omri_id="MOI-2794")
        self.assertIsNone(
            row.delisted_on,
            "an uppercase code was delisted by the very run that re-seeded it",
        )
        self.assertGreater(seed_omri_minimal.MIN_FULL_EDITION_ROWS, 0)

    def test_an_uppercase_code_can_be_un_delisted(self):
        OMRIProduct.objects.create(omri_id="MOI-2794", product_name="Grandevo", delisted_on=date(2026, 9, 26))
        call_command("seed_omri_minimal", verbosity=0)
        self.assertIsNone(OMRIProduct.objects.get(omri_id="MOI-2794").delisted_on)
