"""Lines of the renewal packet that said something other than what the record says.

WHY THIS EXISTS
---------------
A page-by-page read of the production specimen packet (2026-10-29) found sentences a certifier
would read as statements the operation never made, or as gaps that are not gaps:

  * a No to "No fertilizer or soil amendment materials are used or planned" compiled to "The
    operator states that no fertilizer or soil amendment materials are used or planned (No).";
  * every certified parcel listed "Expected first organic harvest (if in transition)" as an
    unanswered question, and the "kept elsewhere, say where" references the certified-parcel card
    already reports;
  * the prior-manager table printed "Not answered" for a declaration a certified parcel is never
    asked, and feather meal and fish emulsion printed as "chemical application";
  * the fallback question index pointed at "the form order below" with no forms below it.
"""

import io
from datetime import date, datetime
from datetime import timezone as dt_tz

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import Certification, OrganicSystemPlan
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_compiler import compile_module_contributions
from certifications.services.osp_module_pdf import _packet_cover_pdf, generate_module_pdf
from certifications.services.parcel_land_history import current_manager_row
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel
from product.services.input_evidence import parcel_inputs
from users.models import User

AT = "2026-08-21T11:00:00+00:00"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="as-written@test.com", password="x", first_name="Ana", last_name="Ruiz"
        )
        company = Company.objects.create(name="As Written LLC")
        self.est = Establishment.objects.create(name="As Written Farm", company=company, state="OR")
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="X-1",
            certifier_name="Cascadia Organic Certifiers",
            effective_date=date(2010, 1, 1),
        )
        self.parcel = Parcel.objects.create(
            name="North Block",
            establishment=self.est,
            area=4.0,
            date_began_managing=date(2010, 1, 1),
            application_answers={"currently_certified": "yes", "no_lapse_attested": True},
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            created_by=self.user,
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    "materials_application": {
                        "status": "in_progress",
                        "answers": {
                            "fertilizers_none_used": {"at": AT, "value": False},
                            "pest_disease_weed_none_used": {"at": AT, "value": True},
                        },
                    }
                },
            },
        )


class CompiledStatementsTests(_Farm):
    def test_a_no_compiles_to_its_own_sentence_never_the_yes_statement(self):
        text = " ".join(" ".join(v) for v in compile_module_contributions(self.osp).values())
        # A No declines the "none used" declaration; it never says materials are used (review of #250).
        self.assertIn(
            "The operator has not declared that no fertilizer or soil amendment materials are used or planned.", text
        )
        self.assertNotIn("states that fertilizer or soil amendment materials are used", text)
        self.assertNotIn("no fertilizer or soil amendment materials are used or planned (No)", text)

    def test_a_yes_still_compiles_to_the_statement(self):
        text = " ".join(" ".join(v) for v in compile_module_contributions(self.osp).values())
        self.assertIn("no pest, disease or weed-control materials are used or planned (Yes)", text)


class CertifiedParcelPageTests(_Farm):
    def test_the_transition_harvest_question_is_not_asked_of_a_certified_parcel(self):
        keys = {q.key for _p, q in visible_questions(PARCEL_APPLICATION, {"currently_certified": "yes"})}
        self.assertNotIn("expected_first_organic_harvest", keys)
        keys = {q.key for _p, q in visible_questions(PARCEL_APPLICATION, {"currently_certified": "no"})}
        self.assertIn("expected_first_organic_harvest", keys)
        # The deciding question is on a later page: unanswered, the question stays asked (review of #250).
        keys = {q.key for _p, q in visible_questions(PARCEL_APPLICATION, {})}
        self.assertIn("expected_first_organic_harvest", keys)

    def test_the_parcel_page_lists_neither_it_nor_the_file_references_as_open(self):
        page = _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))
        self.assertIn("Is livestock kept on this parcel? Not answered (optional).", page)
        for label in (
            "Expected first organic harvest",
            "If the certificate copy is kept elsewhere, say where Not answered",
            "is kept elsewhere, say where Not answered",
        ):
            self.assertNotIn(label, page)

    def test_the_manager_row_says_the_declaration_is_not_asked_of_a_certified_parcel(self):
        row = current_manager_row(self.parcel, self.parcel.application_answers)
        self.assertEqual(row.declared, "Not asked: parcel stated certified")

    def test_a_fertilizer_is_named_by_its_event_type(self):
        season = History.objects.create(
            name="Season", parcel=self.parcel, start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc)
        )
        ChemicalEvent.objects.create(
            history=season,
            date=datetime(2026, 4, 9, tzinfo=dt_tz.utc),
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Feather Meal 12-0-0",
            organic_approved="yes",
        )
        [record] = [r for r in parcel_inputs(self.parcel) if r.product == "Feather Meal 12-0-0"]
        self.assertEqual(record.kind, "fertilizer application")


class CertifiedParcelWindowTests(_Farm):
    """A currently certified parcel is not asked the tenure declaration, so its 36-month window read
    "[REVIEW] not accounted for" even with the agent's verification of no lapse attached (2026-10-31)."""

    def _attach_verification(self):
        from certifications.services.certified_parcel_branch import CONTINUITY_SECTION
        from documents.services.filing import file_document

        file_document(
            establishment=self.est,
            source="upload",
            folder="organic_system_plan",
            title="Verification of no lapse, North Block",
            filename="no-lapse.pdf",
            content=b"%PDF-1.4 no lapse",
            content_type="application/pdf",
            linked_section=CONTINUITY_SECTION,
            parcel=self.parcel,
        )

    def test_without_a_verification_the_window_stays_open(self):
        from certifications.services.parcel_land_history import coverage

        account = coverage(self.parcel, [], today=date(2026, 10, 31))
        self.assertFalse(account.complete)
        self.assertIn("[REVIEW] not accounted for", account.text)

    def test_an_attached_verification_accounts_for_the_window(self):
        from certifications.services.parcel_land_history import coverage

        self._attach_verification()
        account = coverage(self.parcel, [], today=date(2026, 10, 31))
        self.assertTrue(account.complete, account.text)
        self.assertIn("no lapse in organic management (verification attached at parcels/continuity/", account.text)

    def test_a_no_to_the_no_lapse_statement_is_never_overridden_by_a_file(self):
        from certifications.services.parcel_land_history import coverage

        self._attach_verification()
        self.parcel.application_answers = {"currently_certified": "yes", "no_lapse_attested": False}
        self.parcel.save()
        account = coverage(self.parcel, [], today=date(2026, 10, 31))
        self.assertFalse(account.complete)

    def test_a_reference_alone_does_not_account_for_it(self):
        from certifications.services.parcel_land_history import coverage

        self.parcel.application_answers = {
            "currently_certified": "yes",
            "no_lapse_attested": True,
            "continuity_reference": "Letter in the farm office binder",
        }
        self.parcel.save()
        self.assertFalse(coverage(self.parcel, [], today=date(2026, 10, 31)).complete)


class MaterialsListFoldsByLinkTests(_Farm):
    """An operator entry linked to a National List row IS that listing: the bare substance printed again
    beside it as "brand and formulation not stated" put a phantom material on the list (2026-10-31)."""

    def _substance(self, name):
        from certifications.models import NationalListSubstance

        return NationalListSubstance.objects.create(
            substance_name=name,
            substance_name_normalized=name.lower(),
            cfr_section="205.601",
            subsection="e",
            category="insecticide",
            status="allowed",
        )

    def test_a_linked_substance_folds_into_its_entry_and_an_unlinked_one_stays(self):
        from certifications.models import PlanMaterialEntry
        from certifications.services.plan_materials import plan_materials

        linked, unlinked = self._substance("Test lime sulfur"), self._substance("Test elemental sulfur")
        self.osp.approved_national_list_substances.add(linked, unlinked)
        PlanMaterialEntry.objects.create(
            osp=self.osp,
            product_name="Rex Lime Sulfur",
            category="pest_disease_weed",
            reason_for_use="Dormant spray for mummy berry",
            listing_basis=PlanMaterialEntry.BASIS_NATIONAL_LIST,
            national_list_substance=linked,
        )
        rows = {r.name: r for r in plan_materials(self.osp)}
        self.assertNotIn("Test lime sulfur", rows)
        self.assertIn("Test elemental sulfur", rows)
        rex = rows["Rex Lime Sulfur"]
        self.assertEqual(rex.identifier, "§ 205.601")
        self.assertIn("reason for use: Dormant spray for mummy berry", rex.display(stated_absences=True))


class ZipFilenameTests(TestCase):
    def test_a_long_title_is_cut_at_a_word_and_never_ends_in_a_space(self):
        from certifications.services.packet_attachments import safe_title

        cut = safe_title("Verification of no lapse in organic management, River Block (specimen)", "file")
        self.assertEqual(cut, "Verification of no lapse in organic management, River Block")
        cut = safe_title("Verification of no lapse in organic management, Bottom Ground A (specimen)", "file")
        self.assertEqual(cut, "Verification of no lapse in organic management, Bottom")
        self.assertEqual(safe_title("", "map"), "map")
        self.assertEqual(safe_title("a/b", "x"), "a-b")


class FallbackIndexAndCoverTests(_Farm):
    def test_the_cover_names_one_exception_and_the_index_lines(self):
        text = _text(_packet_cover_pdf(self.osp))
        self.assertIn("with one exception: a filed annual update", text)
        self.assertNotIn("with two exceptions", text)

    def test_a_module_page_with_every_question_open_still_prints_its_letters(self):
        text = _text(generate_module_pdf(self.osp, "g4_1_compost_manure"))
        self.assertIn("A. What you apply", text)
        self.assertIn("B. Raw manure", text)
        self.assertIn("C. Compost practice", text)
        self.assertIn("Not shown until “", text)
