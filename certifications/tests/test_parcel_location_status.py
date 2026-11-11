"""Where the parcel is, what status it is applied for, and the treated seed planted on it (2026-11-10).

CCOF ORGB49 (R11 3/14/2022) A2 block/lot numbering, A3 city/state/country, A5 coordinates or a cross street,
A6 "when do you expect to begin harvesting crops that you wish to market as organic", A9 "Yes. Complete or
update G3.1". WSDA AGR 2264 (R 05/26) ref 2 city/state/ZIP/GPS, ref 4 "Which certification status are you
applying for?", 4a "do you need a transitional certificate before harvest?", ref 9 export to Canada (asked
per site), ref 11/11a treated seed planted on the site. OTCO C2 (2024/06/05) 2.1 alternative location
information, 3) city, 4) state/ZIP/country, 8) planned organic harvest.

Before this, city, state, ZIP and country lived only on the operation, a coordinate reached the page only in
the §E map caption, and nothing asked the status applied for or the seed planted on the site.
"""

import io
from datetime import date
from unittest import mock

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from product.models import Parcel
from product.services.transition_status_service import TransitionStatus

WSDA = "Washington State Department of Agriculture (WSDA)"
CCOF = "California Certified Organic Farmers (CCOF)"
OTCO = "Oregon Tilth Certified Organic (OTCO)"

BOUNDARY = [
    {"lat": 47.40, "lng": -120.30},
    {"lat": 47.40, "lng": -120.20},
    {"lat": 47.42, "lng": -120.20},
    {"lat": 47.42, "lng": -120.30},
]


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _status(last_prohibited):
    return TransitionStatus(
        parcel_id=0,
        parcel_name="",
        is_eligible=False,
        transition_complete_date=None,
        days_remaining=None,
        last_prohibited_date=last_prohibited,
    )


class _Parcel(TestCase):
    certifier = WSDA

    def setUp(self):
        self.est = Establishment.objects.create(
            name="Squilchuck Farm",
            company=Company.objects.create(name="Squilchuck LLC"),
            city="Wenatchee",
            state="WA",
            zip_code="98801",
            country="United States",
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=self.certifier
        )
        self.parcel = Parcel.objects.create(
            name="Upper Bench",
            establishment=self.est,
            area=8.0,
            address="4100 Squilchuck Rd",
            application_answers={"currently_certified": "no"},
        )

    def answer(self, **answers):
        self.parcel.application_answers = {**self.parcel.application_answers, **answers}
        self.parcel.save(update_fields=["application_answers"])

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))

    def row(self, agent, document_id, ref):
        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)

    def shown(self, **answers) -> set:
        values = {**self.parcel.application_answers, **answers}
        return {q.key for _p, q in visible_questions(PARCEL_APPLICATION, values)}


class TheQuestionsShowWhenTheyApply(_Parcel):
    def test_the_parcel_s_own_city_is_asked_only_when_it_is_elsewhere(self):
        own = {"location_city", "location_state", "location_zip", "location_country"}
        self.assertFalse(own & self.shown())
        self.assertFalse(own & self.shown(location_same_as_operation="yes"))
        self.assertEqual(own & self.shown(location_same_as_operation="no"), own)

    def test_the_status_questions_skip_a_certified_parcel(self):
        self.assertIn("certification_status_requested", self.shown())
        self.assertNotIn("transitional_certificate_before_harvest", self.shown())
        self.assertIn(
            "transitional_certificate_before_harvest", self.shown(certification_status_requested="transitional")
        )
        certified = self.shown(currently_certified="yes", certification_status_requested="transitional")
        self.assertNotIn("certification_status_requested", certified)
        self.assertNotIn("transitional_certificate_before_harvest", certified)

    def test_the_seed_detail_follows_a_yes(self):
        self.assertNotIn("treated_seed_detail", self.shown(treated_seed_planted="no"))
        self.assertIn("treated_seed_detail", self.shown(treated_seed_planted="yes"))

    def test_the_harvest_date_is_asked_in_the_forms_terms(self):
        question = next(
            q for p in PARCEL_APPLICATION.pages for q in p.questions if q.key == "expected_first_organic_harvest"
        )
        self.assertNotIn("if in transition", question.label["en"])
        self.assertIn("sell as organic", question.label["en"])


class LocationPrintsInSectionA(_Parcel):
    def test_block_numbers_print(self):
        self.answer(block_identifiers="Blocks 28-35")
        self.assertIn("Blocks 28-35", self.page())

    def test_same_as_the_operation_prints_the_operation_s_address(self):
        self.answer(location_same_as_operation="yes")
        page = self.page()
        self.assertIn("The operation's address on file: Wenatchee, WA 98801, United States.", page)
        self.assertNotIn("[REVIEW] The operation's address on file has no", page)

    def test_a_blank_part_of_the_operation_s_address_is_named(self):
        self.est.zip_code = ""
        self.est.country = ""
        self.est.save(update_fields=["zip_code", "country"])
        self.answer(location_same_as_operation="yes")
        self.assertIn(
            "[REVIEW] The operation's address on file has no ZIP code or country, so this parcel's ZIP code and "
            "country are not stated anywhere.",
            self.page(),
        )

    def test_a_parcel_elsewhere_prints_its_own_town(self):
        self.answer(
            location_same_as_operation="no",
            location_city="Cashmere",
            location_state="WA",
            location_zip="98815",
            location_country="United States",
        )
        page = self.page()
        self.assertIn("Cashmere", page)
        self.assertIn("98815", page)
        self.assertNotIn("The operation's address on file", page)

    def test_the_boundary_centre_prints_in_section_a(self):
        self.parcel.polygon = BOUNDARY
        self.parcel.save(update_fields=["polygon"])
        page = self.page()
        self.assertIn("Boundary centre: 47.410000, -120.250000", page)
        # The same figure as the §E caption: one computation.
        self.assertIn("center 47.410000, -120.250000", page)

    def test_no_boundary_is_said_not_left_blank(self):
        self.assertIn("No boundary is drawn on the parcel map, so no coordinates are computed", self.page())

    def test_location_notes_print(self):
        self.answer(location_notes="North side of Squilchuck Rd, 0.4 mi past the Mission Ridge turnoff")
        self.assertIn("0.4 mi past the Mission Ridge turnoff", self.page())

    def test_container_production_names_g3_1_and_its_state(self):
        self.parcel.container_production = True
        self.parcel.save(update_fields=["container_production"])
        self.assertIn(
            "Container and greenhouse production (containers, growing media, structures and their materials) is "
            "asked in G3.1 Container & Greenhouse/Shadehouse Production; it is not answered yet.",
            self.page(),
        )
        self.osp.module_responses = {"modules": {"g3_1_container_greenhouse": {"not_applicable": True}}}
        self.osp.save(update_fields=["module_responses"])
        self.assertIn("which the operation marks not applicable.", self.page())


class StatusAppliedFor(_Parcel):
    def test_the_status_and_the_certificate_answer_print(self):
        self.answer(certification_status_requested="transitional", transitional_certificate_before_harvest="yes")
        page = self.page()
        self.assertIn("Transitional: the last prohibited substance was applied at least 12 months", page)
        self.assertIn("Yes: crops from this parcel will be sold with a transitional claim", page)

    def test_a_window_ending_after_the_harvest_is_stated(self):
        self.answer(certification_status_requested="organic", expected_first_organic_harvest="2027-08-01")
        with mock.patch(
            "product.services.transition_status_service.compute_transition_status",
            return_value=_status(date(2025, 4, 10)),
        ):
            page = self.page()
        self.assertIn(
            "[REVIEW] The records date the last prohibited application on this parcel 2025-04-10; 36 months from it "
            "is 2028-04-10, after the expected first harvest (2027-08-01).",
            page,
        )

    def test_the_same_records_fit_a_transitional_application(self):
        self.answer(certification_status_requested="transitional", expected_first_organic_harvest="2027-08-01")
        with mock.patch(
            "product.services.transition_status_service.compute_transition_status",
            return_value=_status(date(2025, 4, 10)),
        ):
            self.assertNotIn("[REVIEW] The records date the last prohibited application", self.page())


class TreatedSeed(_Parcel):
    def test_a_yes_prints_the_detail_and_a_review(self):
        self.answer(treated_seed_planted="yes", treated_seed_detail="Apron XL on sweet corn, planted 2025-05-02")
        page = self.page()
        self.assertIn("Apron XL on sweet corn, planted 2025-05-02", page)
        self.assertIn("the certifying agent checks each treatment named here against the National List", page)
        self.assertNotIn("No treatment brand or planting date is given", page)

    def test_a_yes_with_no_detail_says_so(self):
        self.answer(treated_seed_planted="yes")
        self.assertIn("[REVIEW] No treatment brand or planting date is given.", self.page())

    def test_a_no_prints_no_review(self):
        self.answer(treated_seed_planted="no")
        self.assertNotIn("the certifying agent checks each treatment", self.page())


class ExportPrintsOnEveryParcel(_Parcel):
    def set_g8(self, **answers):
        self.osp.module_responses = {"modules": {"g8_0_record_keeping": {"answers": answers}}}
        self.osp.save(update_fields=["module_responses"])

    def test_unanswered_says_where_it_is_asked(self):
        self.assertIn(
            "Export is asked once for the operation, in G8.0 Record Keeping; it is not answered yet.", self.page()
        )

    def test_the_operation_s_answer_and_countries_print(self):
        self.set_g8(import_export_activity=["indirect_export"], export_destinations="Canada, Taiwan")
        page = self.page()
        self.assertIn("The operation's answer: Our product is exported, or will be, by a buyer, broker or trader", page)
        self.assertIn("Countries named: Canada, Taiwan.", page)

    def test_the_retired_neither_is_not_an_answer_to_indirect_export(self):
        self.set_g8(import_export_activity=["none"])
        self.assertIn("[REVIEW] That answer predates the question about export by a buyer", self.page())


class TheRegisterReadsTheAnswers(_Parcel):
    def test_wsda_rows_are_answered(self):
        self.answer(
            location_same_as_operation="yes",
            certification_status_requested="transitional",
            transitional_certificate_before_harvest="no",
            treated_seed_planted="yes",
            treated_seed_detail="Apron XL, 2025-05-02",
        )
        for ref in ("4", "4a", "11", "11a"):
            self.assertEqual(self.row("wsda", "AGR 2264", ref).state, "answered", ref)

    def test_wsda_4_is_open_until_stated(self):
        self.assertNotIn(self.row("wsda", "AGR 2264", "4").state, ("answered", "not_applicable"))

    def test_ccof_a2_is_answered(self):
        self.osp.certifier_name = CCOF
        self.osp.save(update_fields=["certifier_name"])
        self.answer(block_identifiers="House 2")
        self.assertEqual(self.row("ccof", "ORGB49", "A2").state, "answered")

    def test_otco_2_1_4_is_answered_by_a_parcel_elsewhere(self):
        self.osp.certifier_name = OTCO
        self.osp.save(update_fields=["certifier_name"])
        self.answer(location_same_as_operation="no", location_state="OR", location_zip="97330", location_country="US")
        self.assertEqual(self.row("otco", "C2", "2.1-4").state, "answered")
