"""What the operator's parcel map shows (CCOF ORGB49 §E and A10, WSDA AGR 2264 Map, OTCO C2 2.3).

Trazo ships the operator's own map and cannot read it. The Parcel Application asks which elements it
shows, one list for the three agents; the parcel PDF prints the answer and names, as a [REVIEW], what
the plan's agent asks for that is not ticked. Conditional elements are named only when they apply.
Treated lumber touching neither crops nor soil is asked apart from the contact question, whose stored
answers keep their meaning.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.parcel_map_elements import (
    MAP_ELEMENTS,
    MAP_ELEMENTS_BY_VALUE,
    PIPING_DIAGRAM_REQUIREMENT,
    unmarked_elements,
)
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from product.models import Parcel

WSDA = "Washington State Department of Agriculture"
CCOF = "CCOF Certification Services, LLC"
OTCO = "Oregon Tilth Certified Organic"
OCI = "Organic Certifiers, Inc."


def _values(elements):
    return [e.value for e in elements]


class TheList(SimpleTestCase):
    def test_each_agent_s_list_is_on_it(self):
        by_agent = {a: {e.value for e in MAP_ELEMENTS if a in e.agents} for a in ("ccof", "wsda", "otco")}
        # CCOF ORGB49 §E names eleven elements.
        self.assertEqual(
            by_agent["ccof"],
            {
                "north_arrow",
                "boundaries",
                "total_acreage",
                "block_identifiers",
                "roads_landmarks",
                "buildings_operation_areas",
                "adjacent_land_uses",
                "buffer_zones",
                "natural_resources",
                "livestock",
                "treated_lumber",
            },
        )
        self.assertEqual(
            by_agent["wsda"],
            {
                "operation_name",
                "parcel_name",
                "boundaries",
                "buffer_zones",
                "crop_locations",
                "adjacent_land_uses",
                "livestock",
            },
        )
        self.assertEqual(
            by_agent["otco"],
            {
                "parcel_name",
                "north_arrow",
                "boundaries",
                "buffer_zones",
                "roads_landmarks",
                "buildings_operation_areas",
                "organic_nonorganic_areas",
                "treated_lumber",
                "irrigation_piping",
            },
        )

    def test_the_question_offers_every_element_in_both_languages(self):
        question = next(q for p in PARCEL_APPLICATION.pages for q in p.questions if q.key == "map_elements_shown")
        self.assertEqual([o.value for o in question.options], _values(MAP_ELEMENTS))
        self.assertTrue(all(o.label["es"] and o.label["en"] for o in question.options))
        self.assertFalse(question.required)

    def test_unmarked_names_only_the_agent_s_own_unconditional_elements(self):
        wsda = _values(unmarked_elements([], {}, None, "wsda"))
        self.assertIn("operation_name", wsda)
        self.assertNotIn("north_arrow", wsda)
        ccof = _values(unmarked_elements([], {}, None, "ccof"))
        self.assertIn("total_acreage", ccof)
        self.assertNotIn("operation_name", ccof)
        self.assertNotIn("livestock", ccof)
        self.assertNotIn("treated_lumber", ccof)

    def test_an_agent_without_a_register_is_named_every_unconditional_element(self):
        unconditional = [e.value for e in MAP_ELEMENTS if e.applies is None]
        self.assertEqual(_values(unmarked_elements([], {}, None, None)), unconditional)

    def test_a_ticked_element_is_never_named(self):
        self.assertNotIn("boundaries", _values(unmarked_elements(["boundaries"], {}, None, "ccof")))

    def test_livestock_and_treated_lumber_apply_only_when_the_parcel_says_so(self):
        self.assertIn("livestock", _values(unmarked_elements([], {"livestock_present": "yes"}, None, "wsda")))
        self.assertIn(
            "treated_lumber",
            # Under an answered No, where the installation question is asked (null until answered since 2026-11-21).
            _values(
                unmarked_elements(
                    [], {"treated_lumber_present": False, "treated_lumber_noncontact_present": True}, None, "ccof"
                )
            ),
        )
        self.assertIn("treated_lumber", _values(unmarked_elements([], {"treated_lumber_present": True}, None, "otco")))


class _Parcel(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Map Elements LLC")
        self.est = Establishment.objects.create(name="Ridge Orchard", company=self.company)
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)

    def plan(self, certifier=WSDA, modules=None):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules or {}},
        )

    def answer(self, **answers):
        self.parcel.application_answers = {**(self.parcel.application_answers or {}), **answers}
        self.parcel.save(update_fields=["application_answers"])

    def page(self, osp):
        data = generate_module_pdf(osp, PARCEL_APPLICATION.key, parcel=self.parcel)
        return " ".join(extract_text(io.BytesIO(data)).split())


class OnTheParcelPage(_Parcel):
    def test_the_operator_s_list_prints_with_what_the_agent_asks_and_is_not_ticked(self):
        self.answer(map_elements_shown=["boundaries", "buffer_zones", "adjacent_land_uses"])
        text = self.page(self.plan(WSDA))
        self.assertIn("Which of these does your parcel map show?", text)
        self.assertIn("The parcel's boundaries", text)
        self.assertIn("[REVIEW] The operator does not mark these as shown on the parcel map:", text)
        self.assertIn("the operation's name, printed on the map", text)
        self.assertIn("where each crop grows", text)
        self.assertNotIn("total acreage", text.split("[REVIEW] The operator does not mark")[1])

    def test_a_ccof_plan_is_not_told_its_map_lacks_the_operation_name(self):
        self.answer(map_elements_shown=["boundaries"])
        review = self.page(self.plan(CCOF)).split("[REVIEW] The operator does not mark these")[1]
        self.assertIn("total acreage", review)
        self.assertNotIn("operation's name", review)

    def test_an_agent_without_a_register_is_named_the_union(self):
        self.answer(map_elements_shown=["boundaries"])
        review = self.page(self.plan(OCI)).split("[REVIEW] The operator does not mark these")[1]
        self.assertIn("total acreage", review)
        self.assertIn("operation's name", review)

    def test_a_map_showing_everything_the_agent_asks_prints_no_review(self):
        wsda = [e.value for e in MAP_ELEMENTS if "wsda" in e.agents]
        self.answer(map_elements_shown=wsda, livestock_present="yes")
        self.assertNotIn("[REVIEW] The operator does not mark", self.page(self.plan(WSDA)))

    def test_nothing_on_the_page_says_the_map_meets_a_list(self):
        self.answer(map_elements_shown=[e.value for e in MAP_ELEMENTS])
        text = self.page(self.plan(CCOF)).lower()
        for word in ("verified", "compliant", "meets", "approved"):
            self.assertNotIn(word, text.split("which of these does your parcel map show?")[1][:1200], word)

    def test_a_list_with_no_operator_map_in_the_packet_says_so(self):
        from certifications.services.osp_module_pdf import PARCEL_MAP_SECTION

        self.answer(map_elements_shown=["boundaries"])
        missing = "No operator-supplied map is in this packet, so this list describes a map the reviewer does not hold."
        self.assertIn(missing, self.page(self.plan(WSDA)))
        GeneratedDocument.objects.create(
            establishment=self.est,
            parcel=self.parcel,
            folder="organic_system_plan",
            source="upload",
            title="North Block map",
            file=SimpleUploadedFile("map.png", b"not-a-real-png", content_type="image/png"),
            linked_section=PARCEL_MAP_SECTION,
        )
        self.assertNotIn(missing, self.page(self.plan(WSDA)))


class ConditionalElements(_Parcel):
    def test_organic_and_non_organic_areas_only_for_a_split_operation(self):
        self.answer(map_elements_shown=["boundaries"])
        self.assertNotIn("organic and non-organic production", self.page(self.plan(OTCO)))
        split = {"g6_0_production": {"answers": {"split_operation": {"value": True}}}}
        self.assertIn("organic and non-organic production", self.page(self.plan(OTCO, split)))

    def test_irrigation_valves_only_when_shared_irrigation_and_no_separate_diagram(self):
        self.answer(map_elements_shown=["boundaries"])
        shared = {"g4_2_natural_resources": {"answers": {"shared_irrigation_with_prohibited": {"value": True}}}}
        osp = self.plan(OTCO, shared)
        self.assertIn("irrigation valves and backflow prevention devices", self.page(osp))
        GeneratedDocument.objects.create(
            establishment=self.est,
            folder="uploads",
            source="upload",
            title="Piping diagram",
            file=SimpleUploadedFile("piping.pdf", b"%PDF-1.4 piping"),
            requirement=PIPING_DIAGRAM_REQUIREMENT,
        )
        self.assertNotIn("irrigation valves and backflow prevention devices", self.page(osp))

    def test_livestock_is_named_when_the_parcel_has_livestock(self):
        self.answer(map_elements_shown=["boundaries"])
        self.assertNotIn("for livestock: fences", self.page(self.plan(WSDA)))
        self.answer(livestock_present="yes")
        self.assertIn("for livestock: fences, shade and water", self.page(self.plan(WSDA)))


class TreatedLumberAwayFromCrops(_Parcel):
    def visible(self):
        from product.services.parcel_application_status import parcel_application_values

        answers = {k: {"value": v} for k, v in parcel_application_values(self.parcel).items()}
        return {q.key for _p, q in visible_questions(PARCEL_APPLICATION, answers)}

    def test_asked_when_the_contact_question_is_no(self):
        self.parcel.treated_lumber_present = False
        self.parcel.save()
        self.assertIn("treated_lumber_noncontact_present", self.visible())
        self.assertNotIn("treated_lumber_noncontact_description", self.visible())
        self.answer(treated_lumber_noncontact_present=True)
        self.assertIn("treated_lumber_noncontact_description", self.visible())

    def test_not_asked_when_lumber_touches_crops_or_soil(self):
        self.parcel.treated_lumber_present = True
        self.parcel.save()
        self.assertNotIn("treated_lumber_noncontact_present", self.visible())

    def test_the_contact_question_keeps_its_words(self):
        question = next(q for p in PARCEL_APPLICATION.pages for q in p.questions if q.key == "treated_lumber_present")
        self.assertEqual(question.label["en"], "Is treated lumber in contact with crops or soil?")

    def test_a_plan_saying_none_beside_a_parcel_with_an_installation_prints_a_review(self):
        from certifications.osp_modules import MODULES_BY_KEY

        # The installation question is asked only under an answered No; since 2026-11-21 a new parcel holds no
        # answer to the contact question instead of a default False.
        self.parcel.treated_lumber_present = False
        self.parcel.save(update_fields=["treated_lumber_present"])
        self.answer(treated_lumber_noncontact_present=True)
        osp = self.plan(CCOF, {"g6_0_production": {"answers": {"treated_lumber_any": {"value": False}}}})
        data = generate_module_pdf(osp, MODULES_BY_KEY["g6_0_production"].key)
        text = " ".join(extract_text(io.BytesIO(data)).split())
        self.assertIn(
            "[REVIEW] The parcel application for North Block says a treated-lumber installation is within the "
            "parcel's boundaries.",
            text,
        )
        self.assertNotIn("says treated lumber is in contact", text)

    def test_the_noncontact_answer_prints_on_the_parcel_page(self):
        self.parcel.treated_lumber_present = False
        self.parcel.save()
        self.answer(
            treated_lumber_noncontact_present=True,
            treated_lumber_noncontact_description="Two CCA end posts in concrete, 2012",
        )
        text = self.page(self.plan(CCOF))
        self.assertIn("touches neither crops nor soil", text)
        self.assertIn("Two CCA end posts in concrete, 2012", text)


class RegisterRows(SimpleTestCase):
    def rows(self, agent, code):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if code in (f.code, f.document_id))
        return {r.ref: r for r in form.items}

    def test_the_map_rows_cite_the_element_list(self):
        for agent, code, ref in (
            ("ccof", "ORGB49", "E"),
            ("wsda", "AGR 2264", "Map"),
            ("otco", "C2", "2.3"),
        ):
            row = self.rows(agent, code)[ref]
            self.assertEqual(row.status, "covered", (agent, ref))
            self.assertIn("parcel_application.map_elements_shown", row.questions, (agent, ref))

    def test_every_element_is_named_by_at_least_one_agent(self):
        self.assertTrue(all(MAP_ELEMENTS_BY_VALUE[v].agents for v in MAP_ELEMENTS_BY_VALUE))
