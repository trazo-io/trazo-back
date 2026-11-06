"""A § 205.602 row the rule allows for one stated use may go on a plan, with that use printed.

WHY THIS EXISTS (2026-11-06)
----------------------------
Three § 205.602 rows carry a condition of use, typed `annotation_kind="condition_of_use"`
(migration 0039, eCFR text): (c) calcium chloride, brine process, "prohibited for use except as a
foliar spray to treat a physiological disorder associated with calcium uptake"; (e) potassium
chloride, unless mined and applied so chloride does not accumulate; (h) sodium nitrate, up to 20%
of the crop's nitrogen. The audit export already printed them as "Restricted use". The plan did
not: `add_approved_input` and the materials-entry serializer refused every prohibited row, so a
Honeycrisp grower could not list calcium chloride for bitter pit, and a row that got there printed
"PROHIBITED in organic production, remove from this plan".

The typed flag decides, never the note's prose: a § 205.105 rationale note grants nothing. The
absolute § 205.602 rows (ash from manure burning) stay refused; `test_prohibited_input_refused`
pins that and is unchanged.
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APITestCase

from certifications.models import NationalListSubstance, OrganicSystemPlan, PlanMaterialEntry
from certifications.services.plan_materials import plan_materials
from company.models import Company, Establishment
from users.models import User, WorksIn

CALCIUM_NOTE = (
    "Prohibited for use except as a foliar spray to treat a physiological disorder associated with calcium uptake."
)


def _calcium_chloride():
    return NationalListSubstance.objects.create(
        substance_name="Calcium chloride (brine process)",
        substance_name_normalized="calcium chloride (brine process)",
        cfr_section="205.602",
        subsection="c",
        status="prohibited",
        restriction_notes=CALCIUM_NOTE,
        annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
    )


def _ash():
    return NationalListSubstance.objects.create(
        substance_name="Ash from manure burning",
        substance_name_normalized="ash from manure burning",
        cfr_section="205.602",
        subsection="a",
        status="prohibited",
    )


class _PlanSetup:
    def _plan(self):
        self.user = User.objects.create_user(email="conditional@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Conditional Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Honeycrisp Block", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", created_by=self.user
        )
        self.base = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.osp.pk}/"


class ConditionalRowOnThePlanTests(_PlanSetup, APITestCase):
    def setUp(self):
        self._plan()
        self.client.force_authenticate(user=self.user)
        self.calcium = _calcium_chloride()
        self.ash = _ash()

    def _add(self, substance):
        return self.client.post(
            self.base + "add-approved-input/", {"kind": "national_list", "id": substance.pk}, format="json"
        )

    def test_the_approved_inputs_endpoint_accepts_a_conditional_row(self):
        res = self._add(self.calcium)
        self.assertIn(res.status_code, (200, 201), res.data)
        self.assertIn(self.calcium, self.osp.approved_national_list_substances.all())

    def test_an_absolute_602_row_is_still_refused(self):
        # Anti-overreach: the change is the three conditional rows, not "§ 205.602 is now addable".
        res = self._add(self.ash)
        self.assertEqual(res.status_code, 400, res.data)
        self.assertNotIn(self.ash, self.osp.approved_national_list_substances.all())

    def test_a_note_without_the_typed_kind_softens_nothing(self):
        # The prose is never the test. A prohibited row with a note but no condition_of_use kind
        # (a § 205.105 rationale, or a row edited by hand) stays refused.
        noted = NationalListSubstance.objects.create(
            substance_name="Glyphosate",
            substance_name_normalized="glyphosate",
            cfr_section="205.602",
            status="prohibited",
            restriction_notes="Synthetic herbicide; not on § 205.601.",
            annotation_kind=NationalListSubstance.ANNOTATION_RATIONALE,
        )
        res = self._add(noted)
        self.assertEqual(res.status_code, 400, res.data)

    def test_the_materials_entry_door_accepts_it_too(self):
        res = self.client.post(
            self.base + "plan-materials/",
            {
                "product_name": "Calcium chloride (brine process)",
                "manufacturer": "Tetra",
                "category": "fertilizer_amendment",
                "reason_for_use": "Bitter pit, foliar",
                "listing_basis": "national_list",
                "national_list_substance": self.calcium.pk,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)

    def test_the_approved_list_api_says_the_row_is_conditional(self):
        self.osp.approved_national_list_substances.add(self.calcium)
        res = self.client.get(self.base)
        self.assertEqual(res.status_code, 200, res.data)
        row = next(r for r in res.data["approved_national_list_substances"] if r["id"] == self.calcium.pk)
        self.assertIs(row["is_conditionally_permitted"], True)
        self.assertEqual(row["subsection"], "c")
        self.assertEqual(row["restriction_notes"], CALCIUM_NOTE)


class ConditionalRowPrintsItsConditionTests(_PlanSetup, TestCase):
    def setUp(self):
        self._plan()
        self.calcium = _calcium_chloride()

    def _line(self, name="Calcium chloride (brine process)"):
        row = next(r for r in plan_materials(self.osp) if r.name == name)
        return row, row.display(stated_absences=True)

    def test_the_line_states_the_condition_and_never_prohibited(self):
        self.osp.approved_national_list_substances.add(self.calcium)
        row, line = self._line()
        self.assertFalse(row.prohibited)
        self.assertNotIn("PROHIBITED", line)
        self.assertIn(f"[REVIEW] restricted use: {CALCIUM_NOTE}", line)

    def test_the_condition_survives_the_fold_into_the_operator_entry(self):
        # The operator lists the product with its own reason; the catalogue row folds into it. The
        # condition is the one thing the reviewer must see, so it travels with the fold.
        self.osp.approved_national_list_substances.add(self.calcium)
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Calcium chloride (brine process)",
            listing_basis="national_list",
            national_list_substance=self.calcium,
            reason_for_use="Bitter pit, foliar",
        )
        rows = [r for r in plan_materials(self.osp) if "calcium chloride" in r.name.lower()]
        self.assertEqual(len(rows), 1, [r.display() for r in rows])
        self.assertIn(f"[REVIEW] restricted use: {CALCIUM_NOTE}", rows[0].display(stated_absences=True))

    def test_the_condition_survives_a_fold_by_name_alone(self):
        # An entry with no catalogue key folds the approved row by its name; the condition comes
        # from that row, since the entry links no substance of its own.
        self.osp.approved_national_list_substances.add(self.calcium)
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Calcium chloride (brine process)",
            listing_basis=PlanMaterialEntry.BASIS_NONE,
            reason_for_use="Bitter pit, foliar",
        )
        rows = [r for r in plan_materials(self.osp) if "calcium chloride" in r.name.lower()]
        self.assertEqual(len(rows), 1, [r.display() for r in rows])
        self.assertIn(f"[REVIEW] restricted use: {CALCIUM_NOTE}", rows[0].display(stated_absences=True))

    def test_an_entry_linked_by_its_own_key_carries_the_condition(self):
        # Not on the approved list at all, only on the operator's entry: the substance is still
        # the conditional one, so its line still states the use.
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="CalciMax foliar",
            listing_basis="national_list",
            national_list_substance=self.calcium,
            reason_for_use="Bitter pit",
        )
        _, line = self._line("CalciMax foliar")
        self.assertIn(f"[REVIEW] restricted use: {CALCIUM_NOTE}", line)

    def test_the_narrative_states_it_too(self):
        from certifications.services.osp_module_compiler import compile_module_contributions

        self.osp.approved_national_list_substances.add(self.calcium)
        text = "\n".join(compile_module_contributions(self.osp).get("inputs_list", []))
        self.assertIn("Calcium chloride (brine process)", text)
        self.assertIn("restricted use", text)
        self.assertNotIn("PROHIBITED", text)

    def test_an_allowed_row_gains_no_condition(self):
        sulfur = NationalListSubstance.objects.create(
            substance_name="Elemental sulfur",
            substance_name_normalized="elemental sulfur",
            cfr_section="205.601",
            status="allowed",
            restriction_notes="Descriptive note.",
            annotation_kind=NationalListSubstance.ANNOTATION_CONDITION,
        )
        self.osp.approved_national_list_substances.add(sulfur)
        _, line = self._line("Elemental sulfur")
        self.assertNotIn("restricted use", line)


class VerifyInputSaysConditionalTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="lookup@test.com", password="x")
        self.client.force_authenticate(user=self.user)
        self.calcium = _calcium_chloride()
        self.ash = _ash()

    def test_the_lookup_marks_the_conditional_match(self):
        body = self.client.get("/api/certifications/verify-input/", {"name": "calcium chloride"}).json()
        self.assertEqual(body["national_list_substance_pk"], self.calcium.pk)
        self.assertIs(body["national_list_conditional"], True)
        self.assertEqual(body["national_list_subsection"], "c")
        self.assertEqual(body["national_list_restriction_notes"], CALCIUM_NOTE)
        candidate = next(c for c in body["national_list_candidates"] if c["pk"] == self.calcium.pk)
        self.assertIs(candidate["is_conditionally_permitted"], True)

    def test_an_absolute_match_is_not_conditional(self):
        body = self.client.get("/api/certifications/verify-input/", {"name": "ash from manure burning"}).json()
        self.assertEqual(body["national_list_substance_pk"], self.ash.pk)
        self.assertIs(body["national_list_conditional"], False)


class AuditExportListsTheConditionTests(TestCase):
    def test_the_approved_substance_list_prints_the_condition(self):
        from history.models import History
        from history.services.audit_export_service import AuditExportService
        from product.models import Parcel

        company = Company.objects.create(name="Audit Co")
        est = Establishment.objects.create(name="Main", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        history = History.objects.create(name="Prod", start_date=timezone.now(), parcel=parcel)
        osp = OrganicSystemPlan.objects.create(
            establishment=est, version_number=1, status="active", effective_date=timezone.now().date()
        )
        calcium = _calcium_chloride()
        osp.approved_national_list_substances.add(calcium)

        els = AuditExportService(history, certification_type="organic")._build_osp_reference_section()
        text = " ".join(getattr(e, "text", "") for e in els if hasattr(e, "text"))
        self.assertIn("Calcium chloride (brine process)", text)
        self.assertIn("restricted use: Prohibited for use except as a foliar spray", text)
