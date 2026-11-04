"""The materials list must be able to hold a material.

WHY THIS EXISTS
---------------
The last register defect that made the packet LIE (4 blocker rows: CCOF G4.0 A3, ORGB41 §A and
§B, WSDA AGR 2196). The only path onto an OSP's materials list was a catalog match against
Trazo's OMRI subset, the WSDA Brand Name list or the seeded National List — so CCOF ORGB41 §A's
own prompt ("fertilizers, compost, manure, gypsum, limestone…") named materials the product could
not accept, the pilot's Rexius Organic Compost and Douglas-fir sawdust dead-ended at "No match",
and WSDA AGR 2196 — one undifferentiated table — was blocked at its first column.

Underneath, the module printed five attestations that every material in use was "entered in the
materials list on this plan" while the same packet's workbook carried the products that could not
be entered. § 205.201(a) makes the producer the author of the plan; a catalog is a shortcut.

THE CLAIM RULE. An operator-authored row states the OPERATOR'S basis and never more. "No
third-party listing" must render as exactly that — never as listed, approved or verified — and a
catalog basis must point at the catalog row it claims. Otherwise this fix would replace a list
that could not hold a material with one that lets an operator type "OMRI listed" onto anything.
"""

from rest_framework.test import APITestCase

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry
from certifications.services.plan_materials import plan_materials, unmatched_logged_materials
from company.models import Company, Establishment
from users.models import User, WorksIn


class PlanMaterialEntryTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="materials@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Materials Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.user
        )
        self.client.force_authenticate(user=self.user)
        self.url = (
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}" f"/osps/{self.osp.pk}/plan-materials/"
        )

    def _post(self, **overrides):
        payload = {
            "product_name": "Rexius Organic Compost",
            "manufacturer": "Rexius",
            "category": "fertilizer_amendment",
            "reason_for_use": "Soil organic matter on the blueberry beds",
            "listing_basis": "none_unlisted",
        }
        payload.update(overrides)
        return self.client.post(self.url, payload, format="json")

    # -- the defect itself -------------------------------------------------

    def test_a_material_with_no_catalog_match_can_be_added(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.osp.plan_material_entries.count(), 1)

    def test_it_reaches_the_one_reading_of_the_plans_materials(self):
        # `plan_materials()` is what the module PDF, the narrative and the reconciliation all
        # read. A row that does not reach it is a row that exists nowhere a certifier looks.
        self._post()
        names = {row.name for row in plan_materials(self.osp)}
        self.assertIn("Rexius Organic Compost", names)

    def test_adding_it_clears_the_unmatched_finding(self):
        # The packet used to state "N product name(s) in the logged applications do not match an
        # entry above" with no way to close the gap. Adding the material is that way.
        self._post()
        self.assertNotIn("Rexius Organic Compost", unmatched_logged_materials(self.osp))

    def test_it_can_be_corrected_and_removed(self):
        entry_id = self._post().data["id"]
        detail = f"{self.url}{entry_id}/"
        patched = self.client.patch(detail, {"manufacturer": "Rexius Forest By-Products"}, format="json")
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(patched.data["manufacturer"], "Rexius Forest By-Products")
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertEqual(self.osp.plan_material_entries.count(), 0)

    # -- the claim rule ----------------------------------------------------

    def test_an_unlisted_row_never_reads_as_listed_or_approved(self):
        self._post()
        row = next(r for r in plan_materials(self.osp) if r.name == "Rexius Organic Compost")
        rendered = row.display().lower()
        self.assertIn("no third-party listing", rendered)
        for forbidden in ("omri listed", "wsda", "national list", "approved", "verified"):
            self.assertNotIn(forbidden, rendered, f"an unlisted row must not read as {forbidden!r}")

    def test_a_certifier_approval_is_no_longer_a_listing_basis(self):
        # 2026-11-04: an agent's approval is its own record (`agent_review`, with the list or letter
        # and its date), so a new certifier-letter basis is refused even with a reference, and the
        # refusal says where the approval goes.
        for extra in ({}, {"certifier_letter_reference": "CCOF letter 2026-03-15"}):
            with self.subTest(extra=extra):
                response = self._post(listing_basis="certifier_letter", **extra)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("agent's review", str(response.data["listing_basis"]))

    def test_claiming_a_catalog_listing_requires_the_catalog_row(self):
        # Otherwise "OMRI listed" is free text an operator can type onto anything — the defect
        # this fix replaces, inverted.
        response = self._post(listing_basis="omri")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("omri_product", response.data)

    def test_a_real_catalog_row_is_accepted_and_states_its_listing(self):
        product = OMRIProduct.objects.create(omri_id="OMRI-1", product_name="Kocide 3000", manufacturer="Certis")
        response = self._post(product_name="Kocide 3000", listing_basis="omri", omri_product=product.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["listing_statement"], "OMRI listed")

    def test_a_prohibited_substance_cannot_arrive_this_way_either(self):
        # The approved-inputs endpoint refuses one; a second door onto the same list must too.
        prohibited = NationalListSubstance.objects.create(
            substance_name="Ash from manure burning",
            substance_name_normalized="ash from manure burning",
            cfr_section="205.602",
            status="prohibited",
        )
        response = self._post(
            product_name="Ash from manure burning",
            listing_basis="national_list",
            national_list_substance=prohibited.pk,
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("prohibited", str(response.data).lower())

    def test_the_same_material_cannot_be_added_twice(self):
        # A double-click, or a slow network and a second press, would otherwise put the same
        # product on a regulatory list twice.
        self.assertEqual(self._post().status_code, 201)
        again = self._post()
        self.assertEqual(again.status_code, 400, again.data)
        self.assertEqual(self.osp.plan_material_entries.count(), 1)

    def test_editing_a_row_does_not_collide_with_itself(self):
        # Anti-overreach on the duplicate check: PATCHing a row must not read that row as its
        # own duplicate.
        entry_id = self._post().data["id"]
        response = self.client.patch(f"{self.url}{entry_id}/", {"reason_for_use": "Bed mulch"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_a_nameless_material_is_refused(self):
        response = self._post(product_name="   ")
        self.assertEqual(response.status_code, 400, response.data)

    # -- one packet, one answer -------------------------------------------

    def test_the_packet_narrative_names_a_material_added_after_the_last_module_save(self):
        """🔴 Found 2026-08-28 by generating the pilot's real packet and reading it.

        The same ZIP listed "Rexius Organic Compost" in `modules/materials_application.pdf` and
        omitted it from the (a)(2) narrative two files away. One packet, two answers — the exact
        defect `plan_materials()` exists to end, arriving through a door nobody had closed.

        `osp.sections` is STORED prose, and only writers that change module ANSWERS recompiled
        it. The compiler also reads three catalogue M2Ms, this table, and the establishment's
        post-harvest facilities — none of which are module answers, and two of which are edited
        on different screens entirely. `generate_osp_packet` now recompiles for editable plans,
        which covers every writer including the next one.
        """
        import io
        import zipfile

        import pdfplumber

        from certifications.services.osp_module_pdf import generate_osp_packet

        self._post()  # the ONLY write — no module save follows it
        with zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))) as zf:
            with zf.open("01-organic-system-plan.pdf") as fh, pdfplumber.open(io.BytesIO(fh.read())) as pdf:
                narrative = " ".join(page.extract_text() or "" for page in pdf.pages)
        self.assertIn("Rexius Organic Compost", narrative.replace("\n", " "))

    def test_a_submitted_plans_filed_narrative_is_never_rewritten(self):
        """The other side of that fix, and the more dangerous one.

        A submitted plan's sections are the text that was FILED; its frozen snapshot is "the
        exact content the certifier receives". Recompiling those at packet time would rewrite
        history to match what the operation looks like today.
        """
        from certifications.services.osp_module_pdf import _refresh_narratives_if_editable

        self.osp.status = "submitted"
        self.osp.sections = {"inputs_list": {"narrative": "AS FILED", "last_updated": None}}
        self.osp.save(update_fields=["status", "sections"])
        self._post()
        _refresh_narratives_if_editable(self.osp)
        self.osp.refresh_from_db()
        self.assertEqual(self.osp.sections["inputs_list"]["narrative"], "AS FILED")

    # -- anti-vacuity ------------------------------------------------------

    def test_the_listing_statement_differs_by_basis(self):
        # If every basis rendered the same string, every assertion above would pass while the
        # packet said the same thing about a catalog listing and an unlisted material.
        entry = PlanMaterialEntry(product_name="x", listing_basis=PlanMaterialEntry.BASIS_NONE)
        unlisted = entry.listing_statement
        entry.listing_basis = PlanMaterialEntry.BASIS_OMRI
        self.assertNotEqual(unlisted, entry.listing_statement)
        entry.listing_basis = PlanMaterialEntry.BASIS_CERTIFIER_LETTER
        entry.certifier_letter_reference = "CCOF letter 2026-03-11"
        self.assertIn("2026-03-11", entry.listing_statement)
