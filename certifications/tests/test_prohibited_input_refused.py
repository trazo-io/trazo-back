"""A § 205.602 PROHIBITED substance may not be added to an organic system plan.

WHY THIS EXISTS
---------------
Found 2026-08-28 by an adversarial review of the certifier conformance register — not by the
register itself. The approved-inputs panel searches `NationalListSubstance`, and that catalogue
holds § 205.601 allowed substances and § 205.602 PROHIBITED ones in the same table: a search for
"manure" returns "Ash from manure burning", prohibited. The search endpoint has always served each
row's `national_list_status`; the panel never read it, and `add_approved_input` never checked it.

The consequence is the class this codebase keeps closing: the packet would print a prohibited
substance under the operation's approved inputs — the plan asserting, over the producer's name,
that a substance banned in organic production is part of it.

Refused at the WRITE, not only in the panel, for the same reason the § 11 attestation gate lives
on the server: a disabled button is a UI courtesy, not an access rule.

REMOVAL IS NOT GATED, DELIBERATELY. The first cut of this fix pasted the refusal into
`remove_approved_input` as well (one blind replace, two matching call sites), which would have
trapped a prohibited row on any plan that acquired one before the guard existed. A guard against
asserting something untrue must never block the correction of it.
"""

from rest_framework.test import APITestCase

from certifications.models import ApprovedInputChangeLog, NationalListSubstance, OrganicSystemPlan
from company.models import Company, Establishment
from users.models import User, WorksIn


class ProhibitedInputRefusedTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="prohibited@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Prohibited Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.user
        )
        self.client.force_authenticate(user=self.user)
        self.base = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}/"

        self.prohibited = NationalListSubstance.objects.create(
            substance_name="Ash from manure burning",
            substance_name_normalized="ash from manure burning",
            cfr_section="205.602",
            status="prohibited",
        )
        self.allowed = NationalListSubstance.objects.create(
            substance_name="Elemental sulfur",
            substance_name_normalized="elemental sulfur",
            cfr_section="205.601",
            subsection="i",
            status="allowed",
        )

    def _add(self, substance):
        return self.client.post(
            self.base + "add-approved-input/",
            {"kind": "national_list", "id": substance.pk},
            format="json",
        )

    def _remove(self, substance):
        return self.client.post(
            self.base + "remove-approved-input/",
            {"kind": "national_list", "id": substance.pk},
            format="json",
        )

    # -- the refusal -------------------------------------------------------

    def test_a_prohibited_substance_is_refused(self):
        res = self._add(self.prohibited)
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("prohibited", str(res.data).lower())

    def test_it_never_reaches_the_list_the_packet_prints(self):
        self._add(self.prohibited)
        self.assertNotIn(self.prohibited, self.osp.approved_national_list_substances.all())

    def test_the_refusal_names_the_substance_and_its_citation(self):
        # "Not allowed" alone leaves the operator guessing which of several search results was
        # refused, and why — and gives them nothing to look up.
        res = self._add(self.prohibited)
        self.assertEqual(res.status_code, 400, res.data)  # without this the body passes on a 200
        body = str(res.data)
        self.assertIn("Ash from manure burning", body)
        self.assertIn("\u00a7 205.602", body)  # the symbol, printed, not just the digits

    def test_the_refusal_leaves_no_change_log_row(self):
        # The log is the plan's audit trail. A refused write must not appear in it as a change.
        self._add(self.prohibited)
        self.assertEqual(ApprovedInputChangeLog.objects.filter(osp=self.osp).count(), 0)

    # -- what must still work ---------------------------------------------

    def test_an_allowed_substance_is_still_accepted(self):
        # Anti-overreach: the guard must not become "no National List substance may be added".
        res = self._add(self.allowed)
        self.assertIn(res.status_code, (200, 201), res.data)
        self.assertIn(self.allowed, self.osp.approved_national_list_substances.all())

    def test_a_prohibited_substance_already_on_a_plan_can_still_be_removed(self):
        # Plans that acquired one before this guard existed must be correctable. This is the test
        # that fails if the refusal is ever pasted into remove_approved_input.
        self.osp.approved_national_list_substances.add(self.prohibited)
        res = self._remove(self.prohibited)
        self.assertIn(res.status_code, (200, 201, 204), res.data)
        self.assertNotIn(self.prohibited, self.osp.approved_national_list_substances.all())

    # -- defence in depth --------------------------------------------------

    def test_a_prohibited_row_already_on_a_plan_is_not_printed_as_ordinary(self):
        """The write path refuses one. A row that predates that guard must still not read as an
        ordinary input on the plan — the packet would then assert that a substance banned in
        organic production is part of this operation's approved materials.

        Attached through the ORM deliberately, because that is the only way one can now arrive.
        """
        from certifications.services.plan_materials import plan_materials

        self.osp.approved_national_list_substances.add(self.prohibited)
        rows = {row.name: row for row in plan_materials(self.osp)}
        self.assertIn("Ash from manure burning", rows)
        self.assertTrue(rows["Ash from manure burning"].prohibited)
        self.assertIn("PROHIBITED", rows["Ash from manure burning"].display())

    def test_an_allowed_row_carries_no_prohibited_qualifier(self):
        from certifications.services.plan_materials import plan_materials

        self.osp.approved_national_list_substances.add(self.allowed)
        row = next(r for r in plan_materials(self.osp) if r.name == "Elemental sulfur")
        self.assertFalse(row.prohibited)
        self.assertNotIn("PROHIBITED", row.display())

    def test_the_narrative_qualifies_it_too(self):
        # The (a)(2) narrative states the same list from a different code path, so it needs the
        # same qualifier or the packet contradicts itself page to page.
        from certifications.services.osp_module_compiler import compile_module_contributions

        self.osp.approved_national_list_substances.add(self.prohibited)
        text = "\n".join(compile_module_contributions(self.osp).get("inputs_list", []))
        self.assertIn("Ash from manure burning", text)
        self.assertIn("PROHIBITED", text)

    # -- anti-vacuity ------------------------------------------------------

    def test_the_shipped_catalogue_really_holds_prohibited_rows(self):
        # If § 205.602 substances were never seeded alongside the allowed ones, every test above
        # would pass against a hazard that does not exist. The seeder is the reason it does:
        # `cfr_section` choices include 205.602, and the National List loader writes both.
        self.assertIn(
            "205.602",
            dict(NationalListSubstance.CFR_SECTION_CHOICES),
            "prohibited-substance sections must remain part of the catalogue this endpoint searches",
        )
