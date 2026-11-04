"""
One row per material, and the paragraph of the rule that lists it.

From a WSDA reviewer read of the specimen renewal packet (2026-11-04):

1. The Materials List carried 20 rows for about 11 materials: the applied brand from the records
   ("Entrust SC", Corteva Agriscience) on one row and the listed product from the plan ("Entrust SC
   Naturalyte Insect Control", Dow AgroSciences) on another, each with its own maker and blanks.
   When the operator attached that exact listing to the application record, the two are one product
   by the operator's own act, and print as one.
2. Every National List line cited a bare "§ 205.601". The catalogue's one stored letter per
   substance was wrong where the rule lists a substance under several paragraphs (elemental sulfur:
   (e)(5), (h)(2), (i)(10), (j)(2)), and "Pheromone traps" was filed under (e) though the rule lists
   pheromones in (f). The citation now comes from a table read from the eCFR text.
"""

from django.test import TestCase
from django.utils import timezone

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry
from certifications.services import national_list_citations as nlc
from certifications.services.common_osp_workbooks import _material_comments, _material_manufacturer, _material_rows
from certifications.services.plan_materials import plan_materials, unmatched_logged_materials
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel
from users.models import User


def _entry(name, section="205.601", subsection="e"):
    """An unsaved catalogue row: the citation reads only its section and name, and a data migration
    already seeds some of these names."""
    return NationalListSubstance(substance_name=name, cfr_section=section, subsection=subsection)


def _substance(name, section="205.601", subsection="e"):
    return NationalListSubstance.objects.create(
        substance_name=name,
        substance_name_normalized=name.lower(),
        cfr_section=section,
        subsection=subsection,
        category="insecticide",
        status="allowed",
    )


class CitationTableTests(TestCase):
    def test_every_seeded_row_is_in_the_table_and_the_table_names_no_other(self):
        from certifications.management.commands import seed_national_list as seed

        seeded = {("205.601", r[2]) for r in seed.SECTION_601_ALLOWED}
        seeded |= {("205.602", r[2]) for r in seed.SECTION_602_PROHIBITED}
        seeded |= {("205.605", r[2]) for r in seed.SECTION_605_ALLOWED}
        self.assertGreater(len(seeded), 70, "the seed lists were not read: the comparison would be vacuous")
        self.assertEqual(sorted(seeded - set(nlc.PARAGRAPHS)), [], "a seeded row has no paragraph")
        self.assertEqual(sorted(set(nlc.PARAGRAPHS) - seeded), [], "the table names a row the seed does not")

    def test_a_substance_listed_under_several_paragraphs_names_each_with_its_use(self):
        sulfur = _entry("Elemental sulfur")
        self.assertEqual(
            nlc.citation_with_uses(sulfur),
            "§ 205.601(e)(5) insecticide, (h)(2) slug or snail bait, (i)(10) crop disease control, "
            "(j)(2) crop or soil amendment",
        )
        # The buyer page's letter-level citation cannot pick one of four: it cites the section.
        self.assertEqual(sulfur.citation, "§ 205.601")

    def test_the_rule_wins_over_the_stored_letter(self):
        traps = _entry("Pheromone traps", subsection="e")
        self.assertEqual(
            (traps.citation, nlc.citation_with_uses(traps)), ("§ 205.601(f)", "§ 205.601(f) insect management")
        )

    def test_handling_and_prohibited_rows_cite_their_own_paragraph_without_a_crop_use(self):
        peracetic = _entry("Peracetic acid/Peroxyacetic acid", section="205.605", subsection="b")
        self.assertEqual((peracetic.citation, nlc.citation_with_uses(peracetic)), ("§ 205.605(b)", "§ 205.605(b)(22)"))
        chloride = _entry("Calcium chloride (brine process)", section="205.602", subsection="c")
        self.assertEqual(nlc.citation_with_uses(chloride), "§ 205.602(c)")

    def test_a_row_the_table_does_not_name_keeps_its_stored_form_and_prints_no_paragraph(self):
        unknown = _entry("Test copper", subsection="i")
        self.assertEqual((unknown.citation, nlc.citation_with_uses(unknown)), ("§ 205.601(i)", ""))


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rows@test.com", password="x", first_name="Lu")
        self.company = Company.objects.create(name="Rows Orchards LLC")
        self.est = Establishment.objects.create(name="Rows Orchard", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.history = History.objects.create(name="Pears 2026", start_date=timezone.now(), parcel=parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _apply(self, name, **fields):
        with self.captureOnCommitCallbacks(execute=True):
            return ChemicalEvent.objects.create(
                history=self.history,
                date=timezone.now(),
                description="spray",
                type="PE",
                commercial_name=name,
                **fields,
            )

    def _rows(self):
        return {r.name: r for r in _material_rows(self.est, osp=self.osp)}


class OneRowPerMaterialTests(_Farm):
    def setUp(self):
        super().setUp()
        self.entrust = OMRIProduct.objects.create(
            product_name="Entrust SC Naturalyte Insect Control", omri_id="dow-2900", manufacturer="Dow AgroSciences"
        )
        self.osp.approved_omri_products.add(self.entrust)

    def test_a_record_naming_the_plans_listing_joins_its_row_and_says_how(self):
        self._apply("Entrust SC", omri_product=self.entrust, manufacturer="Corteva Agriscience")
        self._apply("entrust  sc", omri_product=self.entrust, manufacturer="Corteva Agriscience")
        rows = self._rows()
        self.assertEqual(sorted(rows), ["Entrust SC Naturalyte Insect Control"])
        row = rows["Entrust SC Naturalyte Insect Control"]
        self.assertEqual(_material_manufacturer(row), "Dow AgroSciences")
        self.assertIn(
            "Also logged as 'Entrust SC' (Corteva Agriscience): every application record under this name "
            "names this OMRI listing.",
            _material_comments(row, self.osp),
        )
        self.assertEqual(unmatched_logged_materials(self.osp), [])

    def test_a_name_with_one_record_that_does_not_name_the_listing_stays_its_own_row(self):
        self._apply("Entrust SC", omri_product=self.entrust)
        self._apply("Entrust SC")
        self.assertEqual(sorted(self._rows()), ["Entrust SC", "Entrust SC Naturalyte Insect Control"])
        self.assertEqual(unmatched_logged_materials(self.osp), ["Entrust SC"])

    def test_a_listing_the_plan_does_not_hold_joins_nothing(self):
        other = OMRIProduct.objects.create(product_name="Grandevo", omri_id="mar-1", manufacturer="Marrone")
        self._apply("Grandevo WDG", omri_product=other)
        self.assertIn("Grandevo WDG", self._rows())


class SubstanceRowTests(_Farm):
    def setUp(self):
        super().setUp()
        self.lime_sulfur = _substance("Lime sulfur")
        self.osp.approved_national_list_substances.add(self.lime_sulfur)

    def test_the_operators_classification_joins_the_substance_row_which_takes_the_records_maker(self):
        self._apply(
            "Rex Lime Sulfur",
            manufacturer="OR-Cal Inc.",
            national_list_substance=self.lime_sulfur,
            national_list_basis=ChemicalEvent.NL_BASIS_OPERATOR,
        )
        rows = self._rows()
        self.assertEqual(sorted(rows), ["Lime sulfur"])
        self.assertEqual(_material_manufacturer(rows["Lime sulfur"]), "OR-Cal Inc.")

    def test_a_matchers_classification_is_not_the_operators_and_joins_nothing(self):
        for basis in ("legacy_unverified", "alias"):
            with self.subTest(basis=basis):
                ChemicalEvent.objects.all().delete()
                self._apply(
                    "Rex Lime Sulfur",
                    manufacturer="OR-Cal Inc.",
                    national_list_substance=self.lime_sulfur,
                    national_list_basis=basis,
                )
                self.assertEqual(sorted(self._rows()), ["Lime sulfur", "Rex Lime Sulfur"])

    def test_two_makers_leave_the_cell_blank_and_each_is_named(self):
        for name, maker in (("Rex Lime Sulfur", "OR-Cal Inc."), ("Lime Sulfur Ultra", "Miller Chemical")):
            self._apply(
                name,
                manufacturer=maker,
                national_list_substance=self.lime_sulfur,
                national_list_basis=ChemicalEvent.NL_BASIS_OPERATOR,
            )
        row = self._rows()["Lime sulfur"]
        self.assertIsNone(_material_manufacturer(row))
        comments = _material_comments(row, self.osp)
        self.assertIn("'Rex Lime Sulfur' (OR-Cal Inc.)", comments)
        self.assertIn("'Lime Sulfur Ultra' (Miller Chemical)", comments)

    def test_the_certifier_line_cites_the_paragraphs_and_their_uses(self):
        line = next(m for m in plan_materials(self.osp) if m.name == "Lime sulfur").display(stated_absences=True)
        self.assertIn("§ 205.601(e)(6) insecticide, (i)(6) crop disease control", line)

    def test_an_entry_linked_to_the_substance_inherits_the_paragraphs(self):
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Rex Lime Sulfur",
            listing_basis=PlanMaterialEntry.BASIS_NATIONAL_LIST,
            national_list_substance=self.lime_sulfur,
        )
        rex = next(m for m in plan_materials(self.osp) if m.name == "Rex Lime Sulfur")
        self.assertEqual(rex.identifier, "§ 205.601(e)(6) insecticide, (i)(6) crop disease control")
