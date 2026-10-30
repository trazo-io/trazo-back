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
        self.assertIn("The operator states that fertilizer or soil amendment materials are used or planned.", text)
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
