"""Replacing a catalog must not quietly edit an operator's § 205.201(a)(2) filing.

🔴 2026-09-07 — `seed_omri_minimal --reset` / `seed_wsda_materials --reset` ran
``Model.objects.all().delete()``. The approved-inputs M2Ms cascade, so rebuilding the
catalogues from the publishers' real files emptied every plan's materials list. On the pilot
farm four OMRI products and two WSDA materials vanished from plans that had cited them since
January; the only surviving evidence was the append-only `ApprovedInputChangeLog`.

That is not a data-refresh detail. The plan is the operator's filing, and a material leaving
it is a change § 205.400(f)(2) obliges them to notify their certifier about — so a seeder
removing one as a side effect is the tool editing a regulatory document on the operator's
behalf, without telling anyone.

`repair_input_catalogs` already refused to delete a cited row. The seeders never asked it.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from certifications.models import OMRIProduct, OrganicSystemPlan, WSDAMaterial
from certifications.services.catalog_integrity import CitedCatalogRowsError, assert_safe_to_reset, cited_rows
from company.models import Company, Establishment


class CatalogResetGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Calapooia Bend Farms LLC")
        cls.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=cls.company, state="OR")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.establishment, version_number=1, status="active")
        cls.cited = OMRIProduct.objects.create(omri_id="dow-2900", product_name="Entrust SC")
        cls.orphan = OMRIProduct.objects.create(omri_id="zzz-1", product_name="Never used")
        cls.osp.approved_omri_products.add(cls.cited)

    def test_cited_rows_finds_only_what_a_plan_holds(self):
        found = list(cited_rows(OMRIProduct))
        self.assertEqual(found, [self.cited])

    def test_cited_rows_is_empty_for_a_model_no_plan_can_cite(self):
        """Not an error — a catalog outside the approved-inputs relations simply has none."""
        self.assertEqual(list(cited_rows(Company)), [])

    def test_reset_is_refused_while_a_plan_cites_a_row(self):
        with self.assertRaises(CitedCatalogRowsError) as ctx:
            assert_safe_to_reset(OMRIProduct, force=False)
        message = str(ctx.exception)
        # The refusal has to be actionable: which row, whose plan, and why it matters.
        self.assertIn("Entrust SC", message)
        self.assertIn(f"OSP #{self.osp.id}", message)
        self.assertIn("Calapooia Bend Farm", message)
        self.assertIn("205.400(f)(2)", message)

    def test_force_is_allowed_but_returns_what_it_will_destroy(self):
        """⛔ Forcing stays possible — a genuinely fabricated row sometimes has to go. What
        may not happen is destroying a cited row SILENTLY."""
        lines = assert_safe_to_reset(OMRIProduct, force=True)
        self.assertEqual(len(lines), 1)
        self.assertIn("Entrust SC", lines[0])

    def test_reset_is_allowed_when_no_plan_cites_anything(self):
        self.osp.approved_omri_products.clear()
        self.assertEqual(assert_safe_to_reset(OMRIProduct, force=False), [])

    def test_the_omri_seeder_refuses_rather_than_emptying_a_plan(self):
        with self.assertRaises(CitedCatalogRowsError):
            call_command("seed_omri_minimal", "--reset", stdout=StringIO(), verbosity=0)
        # The whole point: the plan still holds its material.
        self.assertEqual(self.osp.approved_omri_products.count(), 1)

    def test_the_seeder_still_runs_without_reset(self):
        """Updating rows in place is the normal path and must stay unblocked — that is how a
        catalog refresh is supposed to work."""
        call_command("seed_omri_minimal", stdout=StringIO(), verbosity=0)
        self.assertEqual(self.osp.approved_omri_products.count(), 1)

    def test_the_wsda_seeder_carries_the_same_guard(self):
        material = WSDAMaterial.objects.create(wsda_id="2948", brand_name="Nature Safe 13-0-0")
        self.osp.approved_wsda_materials.add(material)

        with self.assertRaises(CitedCatalogRowsError):
            call_command("seed_wsda_materials", "--reset", stdout=StringIO(), verbosity=0)
        self.assertEqual(self.osp.approved_wsda_materials.count(), 1)

    def test_every_citable_catalog_is_covered(self):
        """A fourth registry must be added to `CITABLE_MODELS`, or the guard silently stops
        protecting it — the same off-by-one that produced the two-of-four renderers."""
        from certifications.services.catalog_integrity import CITABLE_MODELS

        m2m_targets = {
            OrganicSystemPlan._meta.get_field(name).related_model.__name__
            for name in (
                "approved_omri_products",
                "approved_wsda_materials",
                "approved_national_list_substances",
            )
        }
        self.assertEqual(set(CITABLE_MODELS), m2m_targets)
