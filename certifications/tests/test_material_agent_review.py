"""
A material's review by the certifying agent, as the operator records it from the agent's own list.

CCOF: "CCOF will review all materials listed and provide you with a copy of your OSP Materials
List listing approved materials." OTCO: "If approved, your material will be added to your MyOTCO
approved materials list." WSDA AGR 2196: "renewing operations do not need to list materials
approved for them in the previous year." (All read live 2026-11-04.) Trazo stored that approval as a
kind of LISTING ("certifier_letter"), which could not sit beside an OMRI listing and which the app
never set. It is its own record now: the operator's statement about the agent's document, blank
until recorded, the agent set by the server, never inferred and never worded as Trazo's approval.
"""

import io
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.serializers import PlanMaterialEntrySerializer
from certifications.services.osp_fork import fork_plan
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import materials_list_rows, plan_materials
from company.models import Company, Establishment
from users.models import User, WorksIn

WSDA = "Washington State Department of Agriculture"


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="review@test.com", password="x", is_verified=True, first_name="Mo")
        self.company = Company.objects.create(name="Review Orchards LLC")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Review Orchard", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name=WSDA
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _answer(self, **body):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/materials-list/answer/"
        return self.client.post(url, body, format="json")

    def _entry(self, **fields):
        return PlanMaterialEntry.objects.create(
            osp=self.osp, product_name="Rexius Organic Compost", listing_basis=PlanMaterialEntry.BASIS_NONE, **fields
        )


class FoldingTheOldBasisTests(_Farm):
    def test_a_certifier_letter_row_becomes_an_approved_review_with_its_reference(self):
        import importlib

        from django.apps import apps

        entry = self._entry()
        PlanMaterialEntry.objects.filter(pk=entry.pk).update(
            listing_basis="certifier_letter", certifier_letter_reference="CCOF letter 2026-03-15"
        )
        migration = importlib.import_module("certifications.migrations.0068_plan_material_agent_review")
        migration.fold_certifier_letter_into_agent_review(apps, None)
        entry.refresh_from_db()
        self.assertEqual(
            (entry.agent_review, entry.agent_review_reference, entry.listing_basis),
            ("approved", "CCOF letter 2026-03-15", "none_unlisted"),
        )
        self.assertEqual(
            entry.agent_review_statement,
            "on the certifying agent's approved materials list (CCOF letter 2026-03-15), as recorded by the operator",
        )

    def test_a_letter_with_no_name_is_not_minted_into_an_approval_and_the_row_stays_editable(self):
        """Review of back #285: an approval with nothing behind it would refuse every later edit."""
        import importlib

        from django.apps import apps

        entry = self._entry(notes="Bought from the co-op.")
        PlanMaterialEntry.objects.filter(pk=entry.pk).update(
            listing_basis="certifier_letter", certifier_letter_reference=" "
        )
        migration = importlib.import_module("certifications.migrations.0068_plan_material_agent_review")
        migration.fold_certifier_letter_into_agent_review(apps, None)
        entry.refresh_from_db()
        self.assertEqual((entry.agent_review, entry.listing_basis), ("", "none_unlisted"))
        self.assertEqual(entry.notes, "Bought from the co-op.\n\n" + migration.UNNAMED_LETTER_NOTE)
        self.assertEqual(entry.agent_review_statement, "")
        res = self._answer(name="Rexius Organic Compost", manufacturer="Rexius")
        self.assertIn(res.status_code, (200, 201), res.content[:300])

    def test_a_new_certifier_letter_basis_is_refused_with_where_the_approval_goes(self):
        serializer = PlanMaterialEntrySerializer(
            data={"product_name": "Lime", "listing_basis": "certifier_letter", "certifier_letter_reference": "x"},
            context={"osp": self.osp},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("agent's review", str(serializer.errors["listing_basis"]))


class RecordingTheReviewTests(_Farm):
    def test_the_agent_is_the_plans_and_the_client_cannot_name_another(self):
        res = self._answer(
            name="Rexius Organic Compost",
            agent_review="approved",
            agent_review_date="2026-03-15",
            agent_review_reference="WSDA approval email",
            agent_review_agent="ccof",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        entry = PlanMaterialEntry.objects.get(osp=self.osp)
        self.assertEqual(entry.agent_review_agent, "wsda")
        self.assertEqual(
            entry.agent_review_statement,
            "on WSDA's approved materials list dated 2026-03-15 (WSDA approval email), as recorded by the operator",
        )

    def test_an_agent_decision_needs_its_list_letter_or_date(self):
        res = self._answer(name="Rexius Organic Compost", agent_review="approved")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertIn("agent_review_reference", res.json())
        res = self._answer(name="Rexius Organic Compost", agent_review="requested")
        self.assertIn(res.status_code, (200, 201), res.content[:300])

    def test_a_future_date_is_refused_and_a_cleared_one_is_no_date(self):
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        res = self._answer(name="Rexius Organic Compost", agent_review="requested", agent_review_date=future)
        self.assertEqual(res.status_code, 400, res.content[:300])
        res = self._answer(name="Rexius Organic Compost", agent_review="requested", agent_review_date="")
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.assertIsNone(PlanMaterialEntry.objects.get(osp=self.osp).agent_review_date)

    def test_category_and_no_longer_used_can_be_set(self):
        self._answer(name="SaniDate 5.0", category="post_harvest", status="discontinued")
        entry = PlanMaterialEntry.objects.get(osp=self.osp, product_name="SaniDate 5.0")
        self.assertEqual((entry.category, entry.status), ("post_harvest", "discontinued"))

    def test_clearing_the_review_clears_its_agent(self):
        self._answer(name="Rexius Organic Compost", agent_review="requested")
        self._answer(name="Rexius Organic Compost", agent_review="")
        entry = PlanMaterialEntry.objects.get(osp=self.osp)
        self.assertEqual((entry.agent_review, entry.agent_review_agent, entry.agent_review_statement), ("", "", ""))

    def test_a_use_reviewed_for_differs_from_the_reason_says_so(self):
        entry = self._entry(
            reason_for_use="Mulch",
            agent_review="approved",
            agent_review_reference="2026 list",
            agent_review_agent="wsda",
            agent_review_use="Soil amendment",
        )
        self.assertIn("reviewed for: Soil amendment", entry.agent_review_statement)


class PrintingTheReviewTests(_Farm):
    def test_the_module_line_states_use_and_review_and_a_catalog_only_row_states_neither_as_given(self):
        self._entry(
            reason_for_use="Soil fertility",
            status="in_use",
            agent_review="approved",
            agent_review_date=date(2026, 3, 15),
            agent_review_agent="wsda",
        )
        lines = [m.display(stated_absences=True) for m in plan_materials(self.osp)]
        self.assertIn(
            "Rexius Organic Compost — manufacturer not stated — no third-party listing on file — reason for use: "
            "Soil fertility — in use — on WSDA's approved materials list dated 2026-03-15, as recorded by the "
            "operator",
            lines,
        )
        text = _pdf_text(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("as recorded by the operator", text)
        self.assertNotIn("approved by Trazo", text)

    def test_an_unrecorded_review_prints_nothing_rather_than_not_approved(self):
        self._entry(status="planned")
        line = plan_materials(self.osp)[0].display(stated_absences=True)
        self.assertTrue(line.endswith("intended for use"), line)
        self.assertNotIn("approved", line)

    def test_the_workbook_comment_carries_the_review_and_a_material_no_longer_used(self):
        from certifications.services.common_osp_workbooks import _material_comments, _material_rows

        self._entry(status="discontinued", agent_review="requested", agent_review_agent="wsda")
        row = next(r for r in _material_rows(self.est, osp=self.osp) if r.name == "Rexius Organic Compost")
        comment = _material_comments(row, self.osp)
        self.assertTrue(
            comment.startswith("No longer used. Submitted to WSDA for review, as recorded by the operator.")
        )

    def test_a_stated_use_leaves_no_use_cell_counted_as_missing(self):
        """Review of back #285: "no longer used" fits neither USDA checkbox, and a material in use
        leaves "Intended for use" blank. Neither blank is work; a row with no use stated is."""
        from certifications.services.common_osp_workbooks import workbook_summary

        def use_blanks():
            summary = next(w for w in workbook_summary(self.est, osp=self.osp) if w["key"] == "materials_list")
            return {b["header"]: b["count"] for b in summary["blanks"] if b["header"] in USE_HEADERS}

        USE_HEADERS = {"In use", "Intended for use"}
        entry = self._entry(status="discontinued")
        self.assertEqual(use_blanks(), {})
        entry.status = "in_use"
        entry.save(update_fields=["status"])
        self.assertEqual(use_blanks(), {})
        PlanMaterialEntry.objects.filter(pk=entry.pk).update(status="")
        self.assertEqual(use_blanks(), {"In use": 1, "Intended for use": 1})

    def test_the_editor_rows_carry_the_answers(self):
        self._entry(category="fertilizer_amendment", agent_review="requested", agent_review_agent="wsda")
        row = next(r for r in materials_list_rows(self.osp) if r["name"] == "Rexius Organic Compost")
        self.assertEqual((row["category"], row["agent_review"]), ("fertilizer_amendment", "requested"))
        self.assertEqual(row["agent_review_statement"], "submitted to WSDA for review, as recorded by the operator")


class RenewalCarriesTheReviewTests(_Farm):
    def test_next_years_plan_starts_from_last_years_approved_list(self):
        self.osp.status = "active"
        self.osp.save(update_fields=["status"])
        self._entry(
            agent_review="approved",
            agent_review_date=date(2026, 3, 15),
            agent_review_reference="2026 list",
            agent_review_agent="wsda",
            agent_review_use="Soil amendment",
        )
        clone = fork_plan(self.osp, self.user)
        entry = clone.plan_material_entries.get()
        self.assertEqual(
            (entry.agent_review, entry.agent_review_date, entry.agent_review_reference, entry.agent_review_agent),
            ("approved", date(2026, 3, 15), "2026 list", "wsda"),
        )
        self.assertEqual(entry.agent_review_use, "Soil amendment")
