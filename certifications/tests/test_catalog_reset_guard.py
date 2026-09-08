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

from certifications.models import OMRIProduct, OrganicSystemPlan, PlanMaterialEntry, WSDAMaterial
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


class MaterialsListCitationTests(TestCase):
    """🔴 2026-09-07 — the SECOND citing relation.

    A plan cites a catalog row two ways: the approved-inputs M2M, and a
    `PlanMaterialEntry` FK. The guard knew the first. The FKs declare
    `related_name="+"`, so no reverse accessor existed for it to find, and `SET_NULL`
    cleared them on reset — leaving the entry on the plan still printing "OMRI listed"
    with no OMRI row anywhere in the database, into `modules/materials_application.pdf`,
    the § 205.201(a)(2) narrative, the workbook and the dossier.

    Knowing three catalogs but one of two citing relations is the same off-by-one
    `catalog_integrity` exists to stop, on the other axis.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Calapooia Bend Farms LLC")
        cls.establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=cls.company, state="OR")
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.establishment, version_number=1, status="active")
        cls.product = OMRIProduct.objects.create(omri_id="dow-2900", product_name="Entrust SC")
        # The materials-list citation ONLY. No M2M — this is exactly the state
        # `remove_approved_input` leaves behind, and it is a normal § 205.400(f) action.
        cls.entry = PlanMaterialEntry.objects.create(
            osp=cls.osp,
            product_name="Entrust SC",
            category="pest_disease_weed",
            listing_basis=PlanMaterialEntry.BASIS_OMRI,
            omri_product=cls.product,
        )

    def test_a_materials_list_entry_alone_makes_a_row_cited(self):
        self.assertEqual(self.osp.approved_omri_products.count(), 0, "M2M must be empty for this to prove anything")
        self.assertEqual(list(cited_rows(OMRIProduct)), [self.product])

    def test_reset_is_refused_for_a_row_only_the_materials_list_cites(self):
        with self.assertRaises(CitedCatalogRowsError) as ctx:
            assert_safe_to_reset(OMRIProduct, force=False)
        message = str(ctx.exception)
        self.assertIn("materials list", message)
        self.assertIn("Entrust SC", message)
        self.assertIn(f"OSP #{self.osp.id}", message)

    def test_seeder_reset_cannot_strand_a_materials_list_entry(self):
        with self.assertRaises(CitedCatalogRowsError):
            call_command("seed_omri_minimal", "--reset", stdout=StringIO(), verbosity=0)
        self.entry.refresh_from_db()
        self.assertIsNotNone(self.entry.omri_product_id)

    def test_listing_statement_never_claims_a_listing_whose_row_is_gone(self):
        """The write path refuses a catalog basis with no FK. This is the READ side of the
        same rule, because the FK can go away after the write and nothing is being written."""
        self.assertEqual(self.entry.listing_statement, "OMRI listed")
        self.assertFalse(self.entry.catalog_basis_unresolved)

        self.product.delete()  # SET_NULL — the entry survives, the citation does not
        self.entry.refresh_from_db()

        self.assertTrue(self.entry.catalog_basis_unresolved)
        statement = self.entry.listing_statement
        self.assertNotEqual(statement, "OMRI listed")
        # Both halves: what the operator claimed, AND that it cannot be substantiated now.
        # Silently degrading would delete the operator's own statement; keeping the bare
        # claim would assert a listing with nothing behind it.
        self.assertIn("OMRI", statement)
        self.assertIn("not on file", statement)

    def test_every_catalog_fk_on_a_materials_entry_is_a_known_citing_field(self):
        """A fourth registry has to be added to BOTH maps. A guard that learns about a new
        catalog on one axis and not the other is how this defect happened."""
        from certifications.services.catalog_integrity import CITABLE_MODELS, ENTRY_CITING_FIELD

        fk_targets = {
            PlanMaterialEntry._meta.get_field(name).related_model.__name__: name
            for name in ("omri_product", "wsda_material", "national_list_substance")
        }
        self.assertEqual(ENTRY_CITING_FIELD, fk_targets)
        self.assertEqual(set(ENTRY_CITING_FIELD), set(CITABLE_MODELS))

    def test_no_listing_statement_contains_the_row_separator(self):
        """`PlanMaterial.display()` joins name, manufacturer and this string with " — ".

        🔴 Caught in review of the fix itself: the first version of the unresolved statement
        read "OMRI listed — cited listing not on file", which turned a three-segment row into
        a four-segment one and, in a cell that truncates at the boundary, printed
        "Entrust SC — Dow — OMRI listed" — the exact bare claim the fix exists to remove.
        Hence the qualifier leads and the separator is banned.
        """
        for basis, _label in PlanMaterialEntry.LISTING_BASIS_CHOICES:
            entry = PlanMaterialEntry(
                product_name="Entrust SC",
                manufacturer="Dow",
                listing_basis=basis,
                certifier_letter_reference="CCOF 2026-04",
            )
            statement = entry.listing_statement
            self.assertNotIn(" — ", statement, f"{basis}: an em-dash segment breaks display()'s row format")
            if entry.catalog_basis_unresolved:
                # Truncating at any point must not leave a sayable claim standing alone.
                self.assertTrue(
                    statement.startswith("unverified"),
                    f"{basis}: the qualifier has to lead, or truncation deletes it",
                )

    def test_an_unresolved_statement_does_not_borrow_the_picker_label(self):
        """The National List choice label carries "(7 CFR 205.601-606)". A CFR cite has no
        business riding along on a claim whose listing cannot be produced."""
        entry = PlanMaterialEntry(
            product_name="Copper hydroxide",
            listing_basis=PlanMaterialEntry.BASIS_NATIONAL_LIST,
        )
        self.assertTrue(entry.catalog_basis_unresolved)
        self.assertNotIn("205.601", entry.listing_statement)
