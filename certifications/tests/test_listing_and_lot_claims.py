"""
Two statements the packet made that the records did not support (2026-11-04).

1. Materials listing. OTCO C5 5.1-6 reads "I have listed all substances on my OSP Materials List
   section C11. Yes". The Materials Application rows that answer it were prefilled "Suggested
   from your records: Yes" whenever anything had been applied in the category, without reading
   the list. A product used and never listed produced the suggestion that it was listed.
   Now the suggestion is Yes only when every application names its product and every product is
   on the plan's list, by exact name or by a current identity decision. Beside a stored Yes the
   module PDF names the logged products the list does not hold.

2. Lot numbering. `lot_numbering = trazo_lots` printed "Yes — Trazo lot IDs (printed on lot tags
   and carried on harvest, storage, and sales records)". Trazo issues no lot numbers
   (`History.lot_id` is free text the operator types) and carries none on storage or sales
   records. The option is retired: a stored answer of it reads as unanswered and asks the
   operator to describe the numbering as their own, which is what CCOF G8.0 B2 asks.
"""

import io

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from certifications.models import MaterialIdentityDecision as MID
from certifications.models import OMRIProduct, OrganicSystemPlan, PlanMaterialEntry
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import effective_value, is_answered
from certifications.osp_modules.materials_application import MATERIALS_APPLICATION
from certifications.services.material_identity import record_decision
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.osp_prefill import resolve_suggestions
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel
from users.models import User, WorksIn

PEST = "pest_disease_weed_listed"
FERT = "fertilizers_listed"


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


def _question(module_key, question_key):
    for page in MODULES_BY_KEY[module_key].pages:
        for q in page.questions:
            if q.key == question_key:
                return q
    raise AssertionError(f"{module_key} has no question {question_key}")


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="listing@test.com", password="x", is_verified=True, first_name="Rowan"
        )
        company = Company.objects.create(name="Listing Farms")
        WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home Orchard", company=company, state="OR")
        parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.history = History.objects.create(
            name="Pears 2026", start_date=timezone.now(), parcel=parcel, operator=self.user
        )
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")

    def _apply(self, name, type_code="PE"):
        with self.captureOnCommitCallbacks(execute=True):
            return ChemicalEvent.objects.create(
                history=self.history, date=timezone.now(), description="spray", type=type_code, commercial_name=name
            )

    def _list(self, name, category="pest_disease_weed"):
        return PlanMaterialEntry.objects.create(
            osp=self.osp, product_name=name, category=category, listing_basis=PlanMaterialEntry.BASIS_NONE
        )

    def _suggestions(self):
        return resolve_suggestions(MATERIALS_APPLICATION, self.est, osp=self.osp)

    def _answer(self, module, **answers):
        responses = self.osp.module_responses or {"schema_version": 1, "modules": {}}
        responses.setdefault("modules", {})[module] = {"answers": {k: {"value": v} for k, v in answers.items()}}
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])


class MaterialsSuggestionTests(_Farm):
    def test_a_product_used_and_not_listed_suggests_nothing(self):
        self._list("Entrust SC")
        self._apply("Entrust SC")
        self._apply("Kocide 3000", type_code="FU")
        self.assertNotIn(PEST, self._suggestions())

    def test_every_product_listed_by_name_suggests_yes_and_says_why(self):
        self._list("Entrust SC")
        self._list("kocide  3000")  # case and spacing are the only differences the match forgives
        self._apply("Entrust SC")
        self._apply("Kocide 3000", type_code="FU")
        suggestions = self._suggestions()
        self.assertIn(PEST, suggestions)
        hit = suggestions[PEST]
        self.assertIs(hit["value"], True)
        self.assertIn("Entrust SC, Kocide 3000", hit["basis"])
        self.assertIn("Each one is on this plan's materials list.", hit["basis"])

    def test_an_unnamed_application_suggests_nothing(self):
        self._list("Entrust SC")
        self._apply("Entrust SC")
        self._apply("")
        self.assertNotIn(PEST, self._suggestions())

    def test_an_identity_decision_onto_a_listed_product_counts_as_listed(self):
        planned = "Neptune's Harvest Organic Fish Fertilizer 2-4-1"
        logged = "Neptune's Harvest Fish Fertilizer 2-3-1"
        omri = OMRIProduct.objects.create(omri_id="nhf-0644", product_name=planned, category="fertilizer")
        self.osp.approved_omri_products.add(omri)
        events = [self._apply(logged, type_code="FE") for _ in range(2)]
        self.assertNotIn(FERT, self._suggestions())
        record_decision(
            self.osp,
            self.user,
            {
                "source": "chemical",
                "logged_name": logged,
                "decision": MID.SAME_AS,
                "target_kind": MID.TARGET_OMRI,
                "target_id": omri.pk,
                "event_ids": [e.pk for e in events],
                "formulation_difference_acknowledged": True,
                "formulation_note": "Same product; the label analysis was updated.",
            },
        )
        suggestions = self._suggestions()
        self.assertIn(FERT, suggestions)
        self.assertIs(suggestions[FERT]["value"], True)

    def test_without_the_plan_there_is_nothing_to_compare_and_nothing_is_suggested(self):
        self._list("Entrust SC")
        self._apply("Entrust SC")
        self.assertNotIn(PEST, resolve_suggestions(MATERIALS_APPLICATION, self.est))

    def test_the_module_get_compares_against_its_own_plan(self):
        from rest_framework.test import APIClient

        self._list("Entrust SC")
        self._apply("Entrust SC")
        client = APIClient()
        client.force_authenticate(self.user)
        url = (
            f"/api/companies/{self.est.company_id}/establishments/{self.est.pk}/osps/{self.osp.pk}"
            "/modules/materials_application/"
        )
        response = client.get(url)
        self.assertEqual(response.status_code, 200, response.content[:300])
        suggestions = response.json()["suggestions"]
        self.assertIn(PEST, suggestions)
        self.assertIs(suggestions[PEST]["value"], True)


class MaterialsReviewLineTests(_Farm):
    def _text(self):
        return _pdf_text(generate_module_pdf(self.osp, "materials_application"))

    def test_a_yes_over_an_unlisted_product_is_printed_with_the_product_named(self):
        self._list("Entrust SC")
        self._apply("Entrust SC")
        self._apply("Kocide 3000", type_code="FU")
        self._apply("Fish Emulsion 5-1-1", type_code="FE")  # another row's product
        self._answer("materials_application", **{PEST: True})
        text = self._text()
        self.assertIn(
            "[REVIEW] The records name 1 pest, weed or disease product(s) that this plan's materials list "
            "does not hold by name, and that no current decision on the plan ties to a listed product: "
            "Kocide 3000.",
            text,
        )
        self.assertNotIn("product: Fish Emulsion", text)

    def test_a_yes_over_listed_products_prints_no_review_line(self):
        self._list("Entrust SC")
        self._apply("Entrust SC")
        self._answer("materials_application", **{PEST: True})
        self.assertNotIn("that this plan's materials list does not hold by name", self._text())


class RetiredLotOptionTests(SimpleTestCase):
    def test_the_trazo_lots_option_is_retired_and_claims_nothing_trazo_does_not_do(self):
        question = _question("g8_0_record_keeping", "lot_numbering")
        option = next(o for o in question.options if o.value == "trazo_lots")
        self.assertTrue(option.retired)
        for words in (option.label["en"], option.label["es"]):
            self.assertNotIn("lot tag", words.lower())
            self.assertNotIn("etiqueta", words.lower())
        self.assertFalse(is_answered(effective_value(question, "trazo_lots")))
        offered = [o.value for o in question.options if not o.retired]
        self.assertEqual(offered, ["own_system", "none"])

    def test_the_lot_tag_coaching_says_what_the_tag_prints(self):
        coaching = _question("g6_1_harvest_transport", "lot_identification_on_every_load").coaching
        self.assertNotIn("carry the parcel", coaching["en"])
        self.assertIn("prints the lot ID and harvest date", coaching["en"])
        self.assertIn("imprime el ID de lote y la fecha de cosecha", coaching["es"])


class RetiredLotOptionPrintTests(_Farm):
    def test_a_stored_trazo_lots_answer_prints_as_chosen_with_the_retired_note(self):
        self._answer("g8_0_record_keeping", lot_numbering="trazo_lots")
        text = _pdf_text(generate_module_pdf(self.osp, "g8_0_record_keeping"))
        self.assertIn("the lot IDs recorded in Trazo", text)
        self.assertIn("[REVIEW] Answered with an option this question no longer offers.", text)
        self.assertNotIn("printed on lot tags", text)
