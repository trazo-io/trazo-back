"""The materials list in OTCO C11's own columns, and the additions apart from the standing list (2026-11-16).

OTCO C11 Crop Materials List (rev. 2023/09/14, source hash checked 2026-11-16) asks, per product: Full
Product Name including formulation, Full Manufacturer Name, Third Party Review Agency (OMRI / WSDA /
OTHER) and Intended Use; every material "in use or intended for use"; and offers a second mode, "The
products identified below are to be added to my current Materials List". CCOF's materials list update
asks the same additions.

Pinned here:
  * an OTCO plan's module page prints the list as C11's four-column table; other agents keep the
    grouped list, and never see OTCO's form named;
  * the review agency is the listing the operator attached (OMRI, WSDA) or an agency the operator names
    (Other); a row with neither says so, and an OMRI or WSDA row cannot also name another;
  * a catalog attach takes the material's use and section with it, onto the operator's row for that
    product, and taking the product off the plan takes that row with it;
  * an operator-entered material added or removed writes the same dated change log a catalog attach
    does, and the page lists what was added since the plan was filed.
"""

import io
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import (
    ApprovedInputChangeLog,
    NationalListSubstance,
    OMRIProduct,
    OrganicSystemPlan,
    PlanMaterialEntry,
    WSDAMaterial,
)
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import (
    c11_product_cell,
    c11_review_cell,
    c11_use_cell,
    materials_changes_since_filing,
    materials_list_rows,
    plan_materials,
)
from company.models import Company, Establishment
from users.models import User, WorksIn

OTCO = "Oregon Tilth Certified Organic"
WSDA = "Washington State Department of Agriculture"
CIVE = "OTCO Crop Input Verification Evaluation"


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Plan(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c11@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Willamette Pear Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Willamette Pears", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name=OTCO
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.omri = OMRIProduct.objects.create(product_name="Entrust SC", omri_id="dow-2900", manufacturer="Corteva")
        self.wsda = WSDAMaterial.objects.create(wsda_id="2948", brand_name="Nature Safe 13-0-0")
        self.sulfur = NationalListSubstance.objects.create(
            substance_name="Test sulfur", substance_name_normalized="test sulfur", cfr_section="205.601"
        )
        self.spinosad = NationalListSubstance.objects.create(
            substance_name="Test spinosad",
            substance_name_normalized="test spinosad",
            cfr_section=NationalListSubstance.NONSYNTHETIC,
        )

    def url(self, tail):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/{tail}"

    def attach(self, kind, pk, **extra):
        return self.client.post(self.url("add-approved-input/"), {"kind": kind, "id": pk, **extra}, format="json")

    def detach(self, kind, pk):
        return self.client.post(self.url("remove-approved-input/"), {"kind": kind, "id": pk}, format="json")

    def answer(self, **body):
        return self.client.post(self.url("materials-list/answer/"), body, format="json")

    def page(self):
        return _pdf_text(generate_module_pdf(OrganicSystemPlan.objects.get(pk=self.osp.pk), "materials_application"))

    def row(self, name):
        return next(r for r in plan_materials(OrganicSystemPlan.objects.get(pk=self.osp.pk)) if r.name == name)

    def log(self, name, action, kind=ApprovedInputChangeLog.KIND_OPERATOR, when=None):
        entry = ApprovedInputChangeLog.objects.create(
            osp=self.osp, kind=kind, target_name_at_change=name, action=action
        )
        if when is not None:
            ApprovedInputChangeLog.objects.filter(pk=entry.pk).update(changed_at=when)
        return entry


class TheReviewAgencyCell(_Plan):
    def test_an_operator_row_names_its_other_agency_and_it_prints(self):
        res = self.answer(
            name="Rexius Organic Compost",
            manufacturer="Rexius",
            category="fertilizer_amendment",
            status="in_use",
            other_review_agency=CIVE,
            other_review_reference="CIVE 2291, 2025-03-04",
        )
        self.assertEqual(res.status_code, 201, res.content[:300])
        row = next(r for r in materials_list_rows(self.osp) if r["name"] == "Rexius Organic Compost")
        self.assertEqual(
            (row["review_position"], row["other_review_agency"], row["other_review_reference"]),
            ("other", CIVE, "CIVE 2291, 2025-03-04"),
        )
        cell = c11_review_cell(self.row("Rexius Organic Compost"))
        self.assertEqual(cell, [f"Other: {CIVE}, CIVE 2291, 2025-03-04", "no third-party listing on file"])
        # A table cell wraps, so the page is read for the part that fits on one line.
        self.assertIn("Other: OTCO Crop Input", self.page())

    def test_each_listing_fills_its_own_box(self):
        for kind, pk in (("omri", self.omri.pk), ("wsda", self.wsda.pk), ("national_list", self.sulfur.pk)):
            self.attach(kind, pk)
        self.assertEqual(c11_review_cell(self.row("Entrust SC")), ["OMRI", "OMRI #dow-2900"])
        self.assertEqual(c11_review_cell(self.row("Nature Safe 13-0-0"))[0], "WSDA")
        sulfur = c11_review_cell(self.row("Test sulfur"))
        self.assertEqual(sulfur[0], "No review agency named")
        self.assertTrue(sulfur[1].startswith("National List substance"), sulfur)
        positions = {r["name"]: r["review_position"] for r in materials_list_rows(self.osp)}
        self.assertEqual(
            positions, {"Entrust SC": "omri", "Nature Safe 13-0-0": "wsda", "Test sulfur": "other"}, positions
        )

    def test_a_lapsed_omri_listing_may_name_the_agency_that_reviews_it_now(self):
        """Review of back #457: the stored basis still says OMRI after the listing lapses, and refusing on
        it left the row stuck at "No review agency named" with no way to say who reviewed it."""
        self.attach("omri", self.omri.pk)
        self.answer(name="Entrust SC", status="in_use")
        OMRIProduct.objects.filter(pk=self.omri.pk).update(delisted_on=timezone.localdate())
        row = next(r for r in materials_list_rows(self.osp) if r["name"] == "Entrust SC")
        self.assertEqual(row["review_position"], "other")
        res = self.answer(name="Entrust SC", other_review_agency=CIVE, other_review_reference="CIVE 3310")
        self.assertEqual(res.status_code, 200, res.content[:300])
        entry = PlanMaterialEntry.objects.get(osp=self.osp, product_name="Entrust SC")
        self.assertEqual((entry.listing_basis, entry.other_review_agency), ("omri", CIVE))

    def test_an_omri_or_wsda_row_cannot_also_name_another_agency(self):
        self.attach("omri", self.omri.pk)
        res = self.answer(name="Entrust SC", other_review_agency=CIVE)
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertIn("other_review_agency", res.json())
        self.assertFalse(PlanMaterialEntry.objects.filter(other_review_agency=CIVE).exists())


class TheC11Table(_Plan):
    def setUp(self):
        super().setUp()
        self.attach("omri", self.omri.pk, status="in_use", category="pest_disease_weed")
        self.attach("national_list", self.sulfur.pk)
        self.answer(
            name="Rexius Organic Compost",
            manufacturer="Rexius",
            category="fertilizer_amendment",
            reason_for_use="Nitrogen before bloom",
            status="planned",
        )

    def test_an_otco_plan_prints_the_four_columns_with_every_cell_stated(self):
        page = self.page()
        for words in (
            "Full product name",
            "Manufacturer",
            "Third party review agency",
            "Intended use",
            "OMRI #dow-2900",
            "Pest, disease or weed control",
            "Fertility and soil amendment",
            "reason for use: Nitrogen before bloom",
            "intended for use",
            # The National List substance attached with no answers: every cell it lacks is said. A table
            # cell wraps, so the words are read as far as one line holds them.
            "brand and formulation not",
            "use category not stated",
            "use not stated",
        ):
            with self.subTest(words=words):
                self.assertIn(words, page)
        # The grouped list is replaced, not printed beside the table.
        self.assertNotIn("Each row: product", page)
        self.assertEqual(c11_product_cell(self.row("Test sulfur")), ["Test sulfur", "brand and formulation not stated"])
        self.assertEqual(
            c11_use_cell(self.row("Test sulfur")),
            ["use category not stated", "reason for use not stated", "use not stated"],
        )

    def test_another_agent_keeps_the_grouped_list_and_never_sees_otco_named(self):
        OrganicSystemPlan.objects.filter(pk=self.osp.pk).update(certifier_name=WSDA)
        page = self.page()
        self.assertIn("Each row: product", page)
        self.assertNotIn("Third party review agency", page)
        self.assertNotIn("C11", page)
        self.assertNotIn("OTCO", page)


class TheUseAndSectionComeWithTheAttach(_Plan):
    def test_the_attach_files_them_on_the_products_own_row(self):
        res = self.attach("omri", self.omri.pk, status="in_use", category="pest_disease_weed")
        self.assertEqual(res.status_code, 200, res.content[:300])
        entries = list(PlanMaterialEntry.objects.filter(osp=self.osp))
        self.assertEqual(len(entries), 1, "the attach files its answers on one row for the product")
        entry = entries[0]
        self.assertEqual(
            (entry.product_name, entry.listing_basis, entry.omri_product_id, entry.status, entry.category),
            ("Entrust SC", "omri", self.omri.pk, "in_use", "pest_disease_weed"),
        )
        row = self.row("Entrust SC")
        self.assertEqual((row.source, row.status, row.identifier), ("OMRI", "in_use", "OMRI #dow-2900"))
        # One material, one logged change: the attach. The answers row is not a second material.
        self.assertEqual(
            list(ApprovedInputChangeLog.objects.filter(osp=self.osp).values_list("kind", "action")),
            [("omri", "added")],
        )

    def test_an_attach_without_them_is_as_before(self):
        self.attach("omri", self.omri.pk)
        self.assertFalse(PlanMaterialEntry.objects.filter(osp=self.osp).exists())
        self.assertEqual(self.row("Entrust SC").status, "")

    def test_a_refused_answer_attaches_nothing(self):
        res = self.attach("omri", self.omri.pk, status="sometimes")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertFalse(self.osp.approved_omri_products.exists())
        self.assertFalse(ApprovedInputChangeLog.objects.exists())

    def test_a_substance_with_a_use_is_still_a_substance_with_no_brand(self):
        self.attach("national_list", self.sulfur.pk, status="in_use", category="pest_disease_weed")
        row = self.row("Test sulfur")
        self.assertIsNotNone(row.entry_id)
        self.assertIn("brand and formulation not stated", row.display(stated_absences=True))
        brand = PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Brand X sulfur 80 DF",
            listing_basis="national_list",
            national_list_substance=self.sulfur,
        )
        self.assertNotIn("brand and formulation not stated", self.row(brand.product_name).display(stated_absences=True))

    def test_a_nonsynthetic_substance_is_never_printed_as_a_listing(self):
        self.attach("national_list", self.spinosad.pk, status="in_use")
        row = self.row("Test spinosad")
        self.assertNotIn("National List substance", row.display(stated_absences=True))
        self.assertEqual(c11_review_cell(row), ["No review agency named", "nonsynthetic, no National List entry"])

    def test_taking_the_product_off_takes_its_answers_with_it(self):
        self.attach("national_list", self.sulfur.pk, status="in_use")
        brand = PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Brand X sulfur 80 DF",
            listing_basis="national_list",
            national_list_substance=self.sulfur,
        )
        res = self.detach("national_list", self.sulfur.pk)
        self.assertEqual(res.status_code, 200, res.content[:300])
        # The answers row for "Test sulfur" left with it; a brand of the substance is a material of its own.
        self.assertEqual(list(PlanMaterialEntry.objects.filter(osp=self.osp).values_list("pk", flat=True)), [brand.pk])
        self.assertNotIn("Test sulfur", [r.name for r in plan_materials(OrganicSystemPlan.objects.get(pk=self.osp.pk))])


class AnOperatorMaterialIsLoggedLikeACatalogOne(_Plan):
    def kinds(self):
        return list(
            ApprovedInputChangeLog.objects.filter(osp=self.osp)
            .order_by("pk")
            .values_list("kind", "action", "target_name_at_change")
        )

    def test_adding_and_removing_an_own_material_is_dated(self):
        res = self.client.post(
            self.url("plan-materials/"),
            {"product_name": "Rexius Organic Compost", "listing_basis": "none_unlisted"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.client.delete(self.url(f"plan-materials/{res.json()['id']}/"))
        self.assertEqual(
            self.kinds(),
            [
                ("operator_entered", "added", "Rexius Organic Compost"),
                ("operator_entered", "removed", "Rexius Organic Compost"),
            ],
        )

    def test_an_answer_that_puts_a_logged_material_on_the_plan_is_an_addition(self):
        self.answer(name="Douglas-fir sawdust", status="in_use")
        self.attach("omri", self.omri.pk)
        self.answer(name="Entrust SC", status="in_use")
        self.assertEqual(
            self.kinds(),
            [("operator_entered", "added", "Douglas-fir sawdust"), ("omri", "added", "Entrust SC")],
        )

    def test_the_plan_review_flags_it(self):
        from certifications.services.plan_review import plan_review

        answered = (timezone.now() - timedelta(days=3)).isoformat()
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {"materials_application": {"answers": {"no_materials_used": {"value": False, "at": answered}}}},
        }
        self.osp.save(update_fields=["module_responses"])
        self.answer(name="Douglas-fir sawdust", status="in_use")
        review = plan_review(OrganicSystemPlan.objects.get(pk=self.osp.pk), reference=timezone.now())
        findings = {f.code: f for f in review.findings}
        self.assertIn("inputs_changed", findings)
        self.assertIn("Douglas-fir sawdust", " ".join(findings["inputs_changed"].details))


class TheAdditionsSinceTheFiling(_Plan):
    def setUp(self):
        super().setUp()
        self.filed = timezone.now() - timedelta(days=60)
        OrganicSystemPlan.objects.filter(pk=self.osp.pk).update(status="active", submitted_at=self.filed)
        self.osp.refresh_from_db()
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="Rexius Organic Compost", status="in_use")
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="Douglas-fir sawdust", status="in_use")

    def test_a_material_added_after_the_filing_is_marked_and_listed(self):
        self.log("Rexius Organic Compost", "added", when=self.filed - timedelta(days=5))
        self.log("Douglas-fir sawdust", "added", when=self.filed + timedelta(days=10))
        day = (self.filed + timedelta(days=10)).date().isoformat()
        since = self.filed.date().isoformat()
        page = self.page()
        self.assertIn(f"Added to the list on {day}, after the plan was filed on {since}.", page)
        self.assertIn(
            f"Added to the Materials List since the plan was filed on {since}: Douglas-fir sawdust ({day}).", page
        )
        self.assertEqual(page.count("Added to the list on"), 1)

    def test_the_renewal_draft_reads_the_lineage(self):
        from certifications.services.osp_fork import fork_plan

        self.log("Douglas-fir sawdust", "added", when=self.filed + timedelta(days=10))
        draft = fork_plan(self.osp, self.user)
        changes = materials_changes_since_filing(draft)
        self.assertEqual(changes["since"], self.filed.date().isoformat())
        self.assertEqual([name for name, _ in changes["added"]], ["Douglas-fir sawdust"])

    def test_added_then_taken_off_is_neither_and_a_removal_is_listed(self):
        self.log("Copper sulfate", "added", when=self.filed + timedelta(days=1))
        self.log("Copper sulfate", "removed", when=self.filed + timedelta(days=2))
        self.log("Fish emulsion", "removed", when=self.filed + timedelta(days=3))
        changes = materials_changes_since_filing(self.osp)
        self.assertEqual(changes["added"], [])
        self.assertEqual([name for name, _ in changes["removed"]], ["Fish emulsion"])
        self.assertIn("Taken off the Materials List since the plan was filed on", self.page())

    def test_taken_off_then_put_back_is_not_an_addition(self):
        """Review of back #457: a product already on the filed list, removed and re-added in the window,
        printed as added."""
        self.log("Rexius Organic Compost", "removed", when=self.filed + timedelta(days=1))
        self.log("Rexius Organic Compost", "added", when=self.filed + timedelta(days=2))
        changes = materials_changes_since_filing(self.osp)
        self.assertEqual((changes["added"], changes["removed"]), ([], []))

    def test_no_change_is_said_and_a_plan_never_filed_has_no_additions(self):
        self.assertIn("No material was added to or taken off the list since the plan was filed on", self.page())
        OrganicSystemPlan.objects.filter(pk=self.osp.pk).update(status="draft", submitted_at=None)
        self.assertIsNone(materials_changes_since_filing(OrganicSystemPlan.objects.get(pk=self.osp.pk)))
        self.assertNotIn("since the plan was filed", self.page())
