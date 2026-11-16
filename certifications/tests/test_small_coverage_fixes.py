"""Seven register rows closed in one pass (content 2026.11.24).

WSDA AGR 2121 P 4a/4b: the residue screening performed and the response when a residue is detected.
OTCO C4 4.4-3: compost temperature is asked of the thermophilic methods only.
CCOF G4.0 B2: test results "must be available at inspection", so the logged tests are counted.
CCOF G4.2 A1/B1: a description of the natural resources, and three monitoring options.
CCOF Parcel Application §C and WSDA AGR 2121 E 12: livestock kept, pastured or grazed, as a completion check.
"""

import io

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.osp_modules.schema import serialize_module
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import Production, SoilManagementEvent
from product.models import Parcel
from product.services.parcel_application_status import parcel_application_status

AT = "2026-11-08T12:00:00Z"


def _visible(module_key, answers):
    return {q.key for _p, q in visible_questions(MODULES_BY_KEY[module_key], answers)}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class ResidueQuestions(SimpleTestCase):
    def test_asked_only_of_an_operation_that_tests_product(self):
        shown = _visible("g2_0_fraud_prevention", {"fraud_mitigation_practices": ["product_testing"]})
        self.assertTrue({"residue_screening_method", "residue_detection_response"} <= shown)
        hidden = _visible("g2_0_fraud_prevention", {"fraud_mitigation_practices": ["verify_certificates"]})
        self.assertFalse({"residue_screening_method", "residue_detection_response"} & hidden)

    def test_optional(self):
        module = MODULES_BY_KEY["g2_0_fraud_prevention"]
        missing = set(missing_required(module, {"fraud_mitigation_practices": ["product_testing"]}))
        self.assertFalse({"residue_screening_method", "residue_detection_response"} & missing)


class CompostTemperatureByMethod(SimpleTestCase):
    def test_asked_of_the_thermophilic_methods(self):
        for method in ("windrow", "static_aerated", "in_vessel"):
            answers = {"materials_applied": ["on_farm_compost"], "compost_method": method}
            self.assertIn("compost_temp_and_days", _visible("g4_1_compost_manure", answers), method)

    def test_not_asked_of_vermicompost_or_a_process_meeting_no_standard(self):
        for method in ("vermicompost", "does_not_meet"):
            answers = {"materials_applied": ["vermicompost"], "compost_method": method}
            self.assertNotIn("compost_temp_and_days", _visible("g4_1_compost_manure", answers), method)
            module = MODULES_BY_KEY["g4_1_compost_manure"]
            self.assertNotIn("compost_temp_and_days", missing_required(module, answers), method)

    def test_a_windrow_without_a_temperature_is_still_missing_it(self):
        module = MODULES_BY_KEY["g4_1_compost_manure"]
        answers = {"materials_applied": ["on_farm_compost"], "compost_method": "windrow"}
        self.assertIn("compost_temp_and_days", missing_required(module, answers))


class NaturalResources(SimpleTestCase):
    def test_page_a_opens_on_the_description(self):
        module = MODULES_BY_KEY["g4_2_natural_resources"]
        first = module.pages[0].questions[0]
        self.assertEqual(first.key, "natural_resources_description")
        self.assertFalse(first.required)

    def test_monitoring_offers_ccof_s_three_missing_options(self):
        module = MODULES_BY_KEY["g4_2_natural_resources"]
        question = next(q for p in module.pages for q in p.questions if q.key == "monitoring_method")
        self.assertTrue({"cost_trends", "water_use_trends", "water_testing"} <= {o.value for o in question.options})


class LivestockQuestion(SimpleTestCase):
    def question(self, key):
        return next(q for p in PARCEL_APPLICATION.pages for q in p.questions if q.key == key)

    def test_none_says_kept_pastured_and_grazed(self):
        none = next(o for o in self.question("livestock_present").options if o.value == "none")
        self.assertIn("not used for livestock", none.label["en"])
        self.assertIn("pastured", none.label["en"])

    def test_the_kept_only_no_is_retired_with_its_review(self):
        no = next(o for o in self.question("livestock_present").options if o.value == "no")
        self.assertTrue(no.retired)
        self.assertIn("does not say whether livestock pasture or graze", no.review)
        payload = {q["key"]: q for p in serialize_module(PARCEL_APPLICATION)["pages"] for q in p["questions"]}
        served = {o["value"]: o for o in payload["livestock_present"]["options"]}
        self.assertTrue(served["no"]["retired"])

    def test_grazing_is_asked_when_livestock_are_there(self):
        self.assertIn("livestock_pastured", self._visible({"livestock_present": "yes"}))
        self.assertNotIn("livestock_pastured", self._visible({"livestock_present": "none"}))

    def _visible(self, answers):
        return {q.key for _p, q in visible_questions(PARCEL_APPLICATION, answers)}


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Small Fixes LLC")
        self.est = Establishment.objects.create(name="Ridge Farm", company=self.company)
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)

    def plan(self, modules=None):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    key: {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}
                    for key, answers in (modules or {}).items()
                },
            },
        )


class LivestockCompletion(_Farm):
    def answer(self, value):
        self.parcel.application_answers = {"livestock_present": value}
        self.parcel.save(update_fields=["application_answers"])
        return parcel_application_status(self.parcel)["missing"]

    def test_unanswered_is_missing(self):
        self.assertIn("livestock", parcel_application_status(self.parcel)["missing"])

    def test_none_and_yes_complete_it(self):
        self.assertNotIn("livestock", self.answer("none"))
        self.assertNotIn("livestock", self.answer("yes"))

    def test_the_retired_no_does_not(self):
        self.assertIn("livestock", self.answer("no"))

    def test_the_parcel_page_prints_the_answer_and_counts_the_check(self):
        self.answer("none")
        text = _text(generate_module_pdf(self.plan(), PARCEL_APPLICATION.key, parcel=self.parcel))
        self.assertIn("No: not used for livestock (none kept, pastured or grazed)", text)
        self.assertRegex(text, r"\(\d of 6\)")

    def test_a_retired_no_prints_its_review(self):
        self.answer("no")
        text = _text(generate_module_pdf(self.plan(), PARCEL_APPLICATION.key, parcel=self.parcel))
        self.assertIn("No livestock kept", text)
        self.assertIn("[REVIEW] This answer was given when the question asked only whether livestock are kept", text)


class OnTheModulePages(_Farm):
    def test_residue_answers_print(self):
        osp = self.plan(
            {
                "g2_0_fraud_prevention": {
                    "fraud_mitigation_practices": ["product_testing"],
                    "residue_screening_method": "Multi-residue panel, accredited lab",
                    "residue_detection_response": "Hold the lot, notify the certifier, trace the source",
                }
            }
        )
        text = _text(generate_module_pdf(osp, "g2_0_fraud_prevention"))
        self.assertIn("Multi-residue panel, accredited lab", text)
        self.assertIn("Hold the lot, notify the certifier, trace the source", text)

    def test_soil_and_tissue_tests_are_counted_under_the_answer(self):
        history = Production.objects.create(name="Block 2026", start_date=timezone.now(), parcel=self.parcel)
        SoilManagementEvent.objects.create(history=history, type="ST", date=timezone.now(), description="soil test")
        SoilManagementEvent.objects.create(
            history=history, type="LA", sample_matrix="soil", date=timezone.now(), description="soil lab"
        )
        SoilManagementEvent.objects.create(
            history=history, type="LA", sample_matrix="leaf", date=timezone.now(), description="leaf lab"
        )
        SoilManagementEvent.objects.create(
            history=history, type="LA", sample_matrix="water", date=timezone.now(), description="water lab"
        )
        SoilManagementEvent.objects.create(
            history=history, type="LA", sample_matrix="hull", date=timezone.now(), description="hull boron"
        )
        osp = self.plan({"g4_0_rotation_soil": {"fertility_monitoring": ["soil_tests", "tissue_tests"]}})
        text = _text(generate_module_pdf(osp, "g4_0_rotation_soil"))
        self.assertIn("In Trazo: 2 soil test records logged.", text)
        self.assertIn("In Trazo: 2 leaf, petiole or hull analyses logged.", text)

    def test_no_tests_logged_says_so_without_claiming_none_exist(self):
        osp = self.plan({"g4_0_rotation_soil": {"fertility_monitoring": ["soil_tests"]}})
        text = _text(generate_module_pdf(osp, "g4_0_rotation_soil"))
        self.assertIn("In Trazo: no soil test records logged. Records kept outside Trazo are not counted here.", text)

    def test_the_natural_resources_description_prints(self):
        osp = self.plan(
            {"g4_2_natural_resources": {"natural_resources_description": "Silt loam; Calapooia River on the east"}}
        )
        self.assertIn(
            "Silt loam; Calapooia River on the east", _text(generate_module_pdf(osp, "g4_2_natural_resources"))
        )


class RegisterRows(SimpleTestCase):
    def row(self, agent, code, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if code in (f.code, f.document_id))
        return next(i for i in form.items if i.ref == ref)

    def test_the_rows_are_covered_and_cite_their_questions(self):
        for agent, code, ref, key in (
            ("wsda", "P", "4a", "g2_0_fraud_prevention.residue_screening_method"),
            ("wsda", "P", "4b", "g2_0_fraud_prevention.residue_detection_response"),
            ("otco", "C4", "4.4-3", "g4_1_compost_manure.compost_temp_and_days"),
            ("ccof", "G4.0", "B2", "g4_0_rotation_soil.fertility_monitoring"),
            ("ccof", "G4.2", "A1", "g4_2_natural_resources.natural_resources_description"),
            ("ccof", "G4.2", "B1", "g4_2_natural_resources.monitoring_method"),
            ("ccof", "ORGB49", "C (not used for livestock)", "parcel_application.livestock_present"),
            ("wsda", "E", "12", "parcel_application.livestock_pastured"),
        ):
            row = self.row(agent, code, ref)
            self.assertEqual(row.status, "covered", (agent, ref))
            self.assertIn(key, row.questions, (agent, ref))
