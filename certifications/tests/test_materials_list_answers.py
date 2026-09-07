"""The three Materials List columns a catalog cannot answer must have somewhere to be answered.

WHY THIS EXISTS (2026-09-07)
----------------------------
The Common OSP Materials List asks four things per product: name, manufacturer, reason for use,
and whether it is IN USE or INTENDED for use. A catalog listing answers the first and none of the
other three — it says a product is allowed, never that this operation uses it or why. So an
operation whose materials arrived from OMRI, WSDA or the National List generated an attachment
with three empty columns on every row.

Found on the pilot farm's own panel: "Materials List — 18 rows · 47 cells to fill in Trazo",
while nowhere in Trazo could any of those 47 cells be filled. A number with no destination reads
to a farmer as a fault in their own records, and it was ours.

The answers live on `PlanMaterialEntry`, which already owned them for operator-authored rows. A
catalog-attached product now gets an entry created for it carrying the catalog FK, so its listing
basis is the one it really has rather than a claim typed by hand — and `plan_materials()` folds
the M2M attachment and the entry into ONE printed row, because a regulatory list that names the
same product twice, with the two lines disagreeing, is worse than one that says less.
"""

from rest_framework.test import APITestCase

from certifications.models import OMRIProduct, OrganicSystemPlan, PlanMaterialEntry
from certifications.services.common_osp_workbooks import WORKBOOKS_BY_KEY, workbook_summary
from certifications.services.plan_materials import materials_list_rows, plan_materials
from company.models import Company, Establishment
from users.models import User, WorksIn


class MaterialsListAnswerTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="mlanswer@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Answer Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Answer Ranch", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.user
        )
        self.omri = OMRIProduct.objects.create(product_name="Serenade ASO", omri_id="bay-1234", manufacturer="Bayer")
        self.osp.approved_omri_products.add(self.omri)
        self.client.force_authenticate(user=self.user)
        base = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}"
        self.list_url = f"{base}/materials-list/"
        self.answer_url = f"{base}/materials-list/answer/"

    # -- the defect --------------------------------------------------------

    def test_a_catalog_material_starts_with_the_three_columns_blank(self):
        rows = self.client.get(self.list_url).data["materials"]
        row = next(r for r in rows if r["name"] == "Serenade ASO")
        self.assertEqual(row["reason"], "")
        self.assertFalse(row["in_use"])
        self.assertFalse(row["intended_for_use"])
        self.assertIsNone(row["entry_id"], "nothing of the operator's exists for it yet")

    def test_answering_fills_the_columns_the_attachment_prints(self):
        response = self.client.post(
            self.answer_url,
            {"name": "Serenade ASO", "status": "in_use", "reason_for_use": "Fire blight"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        row = next(r for r in self.client.get(self.list_url).data["materials"] if r["name"] == "Serenade ASO")
        self.assertEqual(row["reason"], "Fire blight")
        self.assertTrue(row["in_use"])
        self.assertFalse(row["intended_for_use"], "in use and intended for use are different claims")

        # And the generated workbook agrees, because it is the same reading.
        spec = WORKBOOKS_BY_KEY["materials_list"]
        source = next(r for r in spec.rows(self.est) if r.name == "Serenade ASO")
        cells = {c.header: c.value(source, self.est) for c in spec.columns}
        self.assertEqual(cells["In use"], "Yes")
        self.assertIsNone(cells["Intended for use"])
        self.assertEqual(cells["Reason for use"], "Fire blight")

    def test_the_entry_it_creates_claims_only_the_listing_it_really_has(self):
        """⛔ An entry born of a catalog attachment may say "OMRI listed" only because the plan
        holds the OMRI product, and the FK is stored so a reviewer can check the claim rather
        than take it. Typed-in listing claims are the defect `PlanMaterialEntry` exists under."""
        self.client.post(self.answer_url, {"name": "Serenade ASO", "status": "in_use"}, format="json")
        entry = self.osp.plan_material_entries.get()
        self.assertEqual(entry.listing_basis, PlanMaterialEntry.BASIS_OMRI)
        self.assertEqual(entry.omri_product_id, self.omri.pk)
        self.assertEqual(entry.created_by, self.user)

    def test_a_material_with_no_catalog_attachment_says_it_has_none(self):
        self.client.post(
            self.answer_url,
            {"name": "Home-made compost tea", "status": "planned"},
            format="json",
        )
        entry = self.osp.plan_material_entries.get(product_name="Home-made compost tea")
        self.assertEqual(entry.listing_basis, PlanMaterialEntry.BASIS_NONE)
        self.assertEqual(entry.listing_statement, "no third-party listing on file")

    # -- the fold ----------------------------------------------------------

    def test_the_fold_keeps_what_only_the_catalog_row_carries(self):
        """🔴 The fold MERGES; a straight replace deleted the OMRI number and the manufacturer.

        `PlanMaterialEntry.listing_statement` says "OMRI listed" and carries no registration
        number, and an entry created from an answer has no manufacturer unless the operator
        typed one. So replacing the catalog row with the entry meant that stating "in use"
        silently removed `OMRI #bay-1234` and "Bayer" from the certifier's copy of the materials
        list — the two fields on that line a reviewer can actually check.
        """
        self.client.post(self.answer_url, {"name": "Serenade ASO", "status": "in_use"}, format="json")
        row = next(r for r in plan_materials(self.osp) if r.name == "Serenade ASO")
        self.assertEqual(row.identifier, "OMRI #bay-1234")
        self.assertEqual(row.manufacturer, "Bayer")
        self.assertIn("OMRI #bay-1234", row.display())
        self.assertEqual(row.source, "OMRI", "a listed product stays under the registry that lists it")
        self.assertEqual(row.entry_id, self.osp.plan_material_entries.get().pk)

    def test_the_fold_works_for_the_registry_that_is_read_LAST(self):
        """🔴 Source ORDER must not decide correctness.

        The entries were emitted third of four sources, so a WSDA attachment — read fourth — was
        folded AFTER its entry had already been built, and the entry inherited nothing. The bug
        the OMRI test above pins was still live for one of the three registries, invisible
        because the OMRI case passed.
        """
        from certifications.models import WSDAMaterial

        mat = WSDAMaterial.objects.create(brand_name="Tiger 90CR", wsda_id="1123", manufacturer="Tiger-Sul")
        self.osp.approved_wsda_materials.add(mat)
        entry = PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Tiger 90CR",
            listing_basis=PlanMaterialEntry.BASIS_WSDA,
            wsda_material=mat,
            status=PlanMaterialEntry.STATUS_IN_USE,
        )
        rows = [r for r in plan_materials(self.osp) if r.name == "Tiger 90CR"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].identifier, "WSDA Product #1123")
        self.assertEqual(rows[0].manufacturer, "Tiger-Sul")
        self.assertEqual(rows[0].source, "WSDA")
        self.assertEqual(rows[0].entry_id, entry.pk)

    def test_a_name_match_alone_never_borrows_a_registration(self):
        """⛔ The identifier is inherited only when the entry's own FK points at that catalog row.

        An operator row whose basis is "no third-party listing" that happens to share a name with
        an attachment must not print that attachment's registration number. That is the claim
        inflation `PlanMaterialEntry` exists to prevent, reached sideways through the fold.
        """
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Serenade ASO",
            listing_basis=PlanMaterialEntry.BASIS_NONE,
        )
        row = next(r for r in plan_materials(self.osp) if r.name == "Serenade ASO")
        self.assertEqual(row.identifier, "no third-party listing on file")
        self.assertEqual(row.source, "Operator-entered")
        self.assertEqual(row.manufacturer, "Bayer", "the maker is a fact, not a claim, and only it has one")

    def test_a_prohibited_substance_is_never_folded_out_of_sight(self):
        """⛔ The § 205.602 [REVIEW] marker lives on the catalog row and nowhere else.

        Folding it into a same-named operator row would delete the one line telling a reviewer to
        take the material off the plan. Printing it twice is the lesser failure by a wide margin.
        """
        from certifications.models import NationalListSubstance

        sub = NationalListSubstance.objects.create(
            substance_name="Strychnine", cfr_section="205.602", status="prohibited"
        )
        self.osp.approved_national_list_substances.add(sub)
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Strychnine",
            listing_basis=PlanMaterialEntry.BASIS_NONE,
        )
        rows = [r for r in plan_materials(self.osp) if r.name == "Strychnine"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("PROHIBITED" in r.display() for r in rows))

    def test_the_narrative_names_the_material_the_moment_it_is_answered(self):
        """🔴 The viewset PREFETCHES `plan_material_entries`, and a prefetch cache survives a write.

        `_recompile_after_materials_change` read the instance the request started with, so the
        § 205.201(a) narrative it rebuilt was the one WITHOUT the material just added — the exact
        prose this call exists to refresh. It only caught up at some later, unrelated save.
        """
        self.client.post(
            self.answer_url,
            {"name": "Home-made compost tea", "status": "planned"},
            format="json",
        )
        self.osp.refresh_from_db()
        prose = " ".join(str(v) for v in (self.osp.sections or {}).values())
        self.assertIn("Home-made compost tea", prose)

    def test_the_plans_list_prints_one_row_not_two(self):
        """The M2M attachment and the operator's entry are two objects and ONE material.

        Nothing prevented this before the fold: the serializer's duplicate check compares entry
        against entry, and `add_approved_input` does not look at the entries at all. Printed
        unfolded, a certifier reads the same product on two lines of a regulatory list — and the
        two disagree, because only the entry carries the reason and the in-use answer.
        """
        self.client.post(self.answer_url, {"name": "Serenade ASO", "status": "in_use"}, format="json")
        rows = [row for row in plan_materials(self.osp) if row.name == "Serenade ASO"]
        self.assertEqual(len(rows), 1, [r.source for r in rows])
        self.assertEqual(rows[0].status, "in_use", "the operator's answer is the half only they have")

    def test_a_second_answer_corrects_the_first_rather_than_adding_a_row(self):
        self.client.post(self.answer_url, {"name": "Serenade ASO", "status": "planned"}, format="json")
        response = self.client.post(self.answer_url, {"name": "Serenade ASO", "status": "in_use"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.osp.plan_material_entries.count(), 1)
        self.assertEqual(self.osp.plan_material_entries.get().status, "in_use")

    def test_the_name_is_matched_the_way_the_list_folds_it(self):
        """A name pasted off a label arrives with a double space.

        `product_name__iexact` in the database would not match it, so the answer would save, come
        back 201, create a SECOND entry — and then the fold would hide it behind the first. The
        operator's answer would silently never appear.
        """
        self.client.post(self.answer_url, {"name": "Serenade ASO", "status": "planned"}, format="json")
        response = self.client.post(self.answer_url, {"name": "Serenade  ASO ", "status": "in_use"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.osp.plan_material_entries.count(), 1)
        self.assertEqual(self.osp.plan_material_entries.get().status, "in_use")

    # -- guards ------------------------------------------------------------

    def test_an_answer_needs_something_to_record(self):
        response = self.client.post(self.answer_url, {"name": "Serenade ASO"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_an_answer_needs_a_material(self):
        response = self.client.post(self.answer_url, {"status": "in_use"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.data)

    def test_a_locked_plan_refuses_the_answer(self):
        self.osp.status = "submitted"
        self.osp.save(update_fields=["status"])
        response = self.client.post(self.answer_url, {"name": "Serenade ASO", "status": "in_use"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)

    def test_one_packet_describes_one_plan(self):
        """🔴 The Materials List used to resolve the plan itself — active first — while every
        module PDF beside it described the plan the packet was generated FOR.

        So a packet built from a draft under revision shipped a materials list belonging to the
        plan that draft replaces. One packet, two plans: the exact failure `plan_materials`
        exists to end, reached through the attachment instead of the renderer. Both the editor
        and the generated sheet now state the plan they were asked about.
        """
        active = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="active", created_by=self.user
        )
        other = OMRIProduct.objects.create(product_name="Regalia CG", omri_id="mar-77")
        active.approved_omri_products.add(other)

        draft_names = {row["name"] for row in materials_list_rows(self.osp)}
        self.assertIn("Serenade ASO", draft_names)
        self.assertNotIn("Regalia CG", draft_names)

        spec = WORKBOOKS_BY_KEY["materials_list"]
        self.assertEqual(
            {r.name for r in spec.rows(self.est, self.osp)},
            {"Serenade ASO"},
            "the draft's own workbook must not list the active plan's materials",
        )
        self.assertEqual(
            {r.name for r in spec.rows(self.est, active)},
            {"Regalia CG"},
        )

    def test_a_caller_with_no_plan_in_hand_still_gets_the_active_one(self):
        """The download button has an establishment and no plan; nothing about it changed."""
        active = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="active", created_by=self.user
        )
        active.approved_omri_products.add(OMRIProduct.objects.create(product_name="Regalia CG", omri_id="mar-77"))
        spec = WORKBOOKS_BY_KEY["materials_list"]
        self.assertEqual({r.name for r in spec.rows(self.est, None)}, {"Regalia CG"})

    def test_the_attachment_counter_stops_asking_for_what_was_answered(self):
        before = next(w for w in workbook_summary(self.est) if w["key"] == "materials_list")
        self.client.post(
            self.answer_url,
            {"name": "Serenade ASO", "status": "in_use", "reason_for_use": "Fire blight"},
            format="json",
        )
        after = next(w for w in workbook_summary(self.est) if w["key"] == "materials_list")
        self.assertLess(after["missing_from_records"], before["missing_from_records"])

    def test_every_blank_the_counter_reports_names_where_it_is_answered(self):
        """The whole point of the count. A blank with no destination is the defect, not a row."""
        for entry in workbook_summary(self.est):
            for blank in entry["blanks"]:
                if blank["kind"] == "record":
                    self.assertTrue(
                        blank["fix"],
                        f"{entry['key']}: {blank['header']!r} is counted as fillable in Trazo "
                        "and names no screen that fills it",
                    )
