"""Seeds and planting stock across CCOF G3.0, OTCO C3 and WSDA AGR 2121 A/C (content 2026.12.16).

Four things the registers held open:

* A planting record of a tree, vine or berry plant fed G3.0 "Seeds", so an orchard that logged its
  replant trees as certified organic was offered "Seeds: Organic, untreated". Those records now feed
  "Planting stock"; seed records still feed "Seeds", and a transplant is never seed (CCOF A1, OTCO 3.1-1,
  WSDA A2/A3).
* G3.0 and G3.0b both state the organic status of planting stock and nothing compared them (CCOF A3,
  OTCO 3.1-3, WSDA C2/C3); G3.0 now also asks OTCO 3.1-4's other planting stock.
* "All seed treatment materials are on the inputs list" and "treated, materials on our inputs list" were
  read against nothing, and their No had no consequence (CCOF D2, OTCO 3.5-2, WSDA A2b/A3c/C3c).
* Grafting and stock treatments had no true answer for materials not listed yet (CCOF E1, WSDA C3c), and
  WSDA C4's "purchase and resell nonorganic planting stock" was not asked.
"""

import io

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from carbon.models import CropType
from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.services.attestation_gates import blocked_attestations
from certifications.services.common_osp_records import EvidenceBundle
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.osp_prefill import is_planting_stock_record, resolve_suggestions
from certifications.services.plan_review import plan_review
from company.models import Company, Establishment
from history.models import Production, ProductionEvent
from product.models import Parcel
from users.models import User, WorksIn

G3 = MODULES_BY_KEY["g3_0_seeds"]
G3B = MODULES_BY_KEY["g3_2_planting_stock"]


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _crop(name, category):
    return CropType.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        category=category,
        description="d",
        emissions_per_hectare=0.0,
        industry_average=0.0,
        best_practice=0.0,
        carbon_credit_potential=0.0,
        typical_cost_per_hectare=0.0,
    )


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Seed Stock Farms LLC")
        self.user = User.objects.create_user(email="seedstock@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Seed Stock Farm", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.apples = _crop("Test Apples", "tree_fruit")
        self.lettuce = _crop("Test Lettuce", "vegetable")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def production(self, crop, name=None):
        return Production.objects.create(
            name=name or f"{crop.name} 2026", start_date=timezone.now(), parcel=self.parcel, crop_type=crop
        )

    def record(self, production, type_code="PL", **fields):
        return ProductionEvent.objects.create(
            history=production, date=timezone.now(), description="planting", type=type_code, **fields
        )

    def store(self, module_key, answers, not_applicable=False):
        responses = self.osp.module_responses or {"schema_version": 1, "modules": {}}
        entry = {"answers": {k: {"at": "2026-11-17T10:00:00Z", "value": v} for k, v in answers.items()}}
        if not_applicable:
            entry.update({"not_applicable": True, "na_attestation": {"by": None, "at": "2026-11-17"}})
        responses.setdefault("modules", {})[module_key] = entry
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def put(self, module_key, answers):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/modules/{module_key}/"
        return self.client.put(url, {"answers": answers}, format="json")

    def suggestions(self):
        return resolve_suggestions(G3, self.est, osp=self.osp)

    def review_codes(self):
        return {f.code: f for f in plan_review(self.osp, reference=timezone.now()).findings}


class StockRecordsAreNotSeedTests(_Farm):
    def test_an_orchard_replant_suggests_planting_stock_and_never_seed(self):
        self.record(self.production(self.apples), seed_certification_status="certified_organic")
        out = self.suggestions()
        self.assertNotIn("seeds_used", out)
        self.assertEqual(out["planting_stock_used"]["value"], ["organic"])
        self.assertIn("1 planting or transplanting record of trees", out["planting_stock_used"]["basis"])

    def test_a_named_rootstock_is_planting_stock_on_any_crop(self):
        greens = self.production(self.lettuce)
        self.record(greens, "TR", seed_certification_status="transitional", rootstock="Maxifort")
        out = self.suggestions()
        self.assertEqual(out["planting_stock_used"]["value"], ["non_organic"])
        self.assertNotIn("seeds_used", out)

    def test_seed_sown_on_a_vegetable_still_suggests_seed_and_a_transplant_never_does(self):
        greens = self.production(self.lettuce)
        self.record(greens, seed_certification_status="certified_organic", seed_treatment="Clay pelleting")
        self.record(greens, "TR", seed_certification_status="non_organic_untreated")
        out = self.suggestions()
        self.assertEqual(out["seeds_used"]["value"], ["organic_treated"])
        self.assertIn("1 planting event", out["seeds_used"]["basis"])
        self.assertNotIn("planting_stock_used", out)

    def test_telling_stock_from_seed_costs_no_query_per_production(self):
        self.record(self.production(self.apples, "Block 1"), seed_certification_status="certified_organic")
        for n in (2, 3, 4):
            self.record(self.production(self.lettuce, f"Block {n}"), seed_certification_status="certified_organic")
        bundle = EvidenceBundle(self.est)
        with CaptureQueriesContext(connection) as ctx:
            kinds = [is_planting_stock_record(e) for e in bundle.production_events]
        self.assertEqual(kinds.count(True), 1)
        self.assertEqual(len(ctx.captured_queries), 0, [q["sql"] for q in ctx.captured_queries])


class TreatmentStatementsReadTheRecordsTests(_Farm):
    def setUp(self):
        super().setUp()
        self.record(
            self.production(self.lettuce),
            seed_certification_status="certified_organic",
            seed_treatment="Rhizobium inoculant XL",
            seed_treatment_allowed_basis="omri_listed",
        )
        self.record(
            self.production(self.apples),
            seed_certification_status="non_organic_untreated",
            seed_treatment="Captan root dip",
            seed_treatment_allowed_basis="omri_listed",
            seed_search_attempts=[{"supplier_name": "Nursery A"}],
        )

    def test_the_seed_statement_is_refused_until_the_seed_treatment_is_listed(self):
        answers = {"seeds_used": ["organic_treated"], "treatments_on_inputs_list": True}
        response = self.put("g3_0_seeds", answers)
        self.assertEqual(response.status_code, 400, response.content)
        message = str(response.json())
        self.assertIn("treatments_on_inputs_list", message)
        self.assertIn("Rhizobium inoculant XL", message)
        # The stock's root dip is not a seed treatment, so it never holds this statement open.
        self.assertNotIn("Captan root dip", message)
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="Rhizobium inoculant XL", category="production_aid")
        self.assertEqual(self.put("g3_0_seeds", answers).status_code, 200)

    def test_the_stock_statement_is_refused_until_the_stock_treatment_is_listed(self):
        answers = {"stock_organic_status": "all_nonorganic", "stock_treatments": "treated_listed"}
        response = self.put("g3_2_planting_stock", answers)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("Captan root dip", str(response.json()))
        self.assertNotIn("Rhizobium", str(response.json()))
        # "Not every material is listed yet" is a true answer and is never refused.
        answers["stock_treatments"] = "treated_not_listed"
        self.assertEqual(self.put("g3_2_planting_stock", answers).status_code, 200)

    def test_a_statement_under_a_closed_page_does_not_hold_the_module_open(self):
        stored = {
            "seeds_used": {"value": ["organic_untreated"]},
            "treatments_on_inputs_list": {"value": True},
        }
        self.assertEqual(blocked_attestations(G3, stored, self.osp), {})
        stored["seeds_used"] = {"value": ["organic_treated"]}
        self.assertEqual(set(blocked_attestations(G3, stored, self.osp)), {"treatments_on_inputs_list"})

    def test_a_no_prints_why_and_names_the_unlisted_seed_treatment(self):
        self.store("g3_0_seeds", {"seeds_used": ["organic_treated"], "treatments_on_inputs_list": False})
        page = _text(generate_module_pdf(self.osp, "g3_0_seeds"))
        self.assertIn("[REVIEW] The answer is No: not every seed treatment material is on this plan's", page)
        self.assertIn("§ 205.201(a)(2) asks the plan to list each substance used in organic production.", page)
        self.assertIn("The records name 1 seed treatment product(s)", page)
        self.assertIn("Rhizobium inoculant XL", page)
        self.assertNotIn("Captan root dip", page)

    def test_a_stored_listed_stock_answer_says_it_no_longer_stands_and_names_the_treatment(self):
        self.store(
            "g3_2_planting_stock", {"stock_organic_status": "all_nonorganic", "stock_treatments": "treated_listed"}
        )
        page = _text(generate_module_pdf(self.osp, "g3_2_planting_stock"))
        self.assertIn("as answered before the records showed otherwise", page)
        self.assertIn("The records name 1 nonorganic planting stock treatment product(s)", page)
        self.assertIn("Captan root dip", page)

    def test_the_new_answers_print_their_review_line(self):
        self.store("g3_0_seeds", {"planting_stock_used": ["non_organic"], "grafts_stock": "yes_not_listed"})
        self.store("g3_2_planting_stock", {"stock_organic_status": "all_nonorganic", "stock_treatments": "unknown"})
        g3 = _text(generate_module_pdf(self.osp, "g3_0_seeds"))
        self.assertIn("Yes, and not every grafting material is on the OSP inputs list yet", g3)
        self.assertIn("[REVIEW] The operation grafts planting stock, and the plan says not every grafting", g3)
        g3b = _text(generate_module_pdf(self.osp, "g3_2_planting_stock"))
        self.assertIn(
            "[REVIEW] Whether the nonorganic planting stock was treated is not yet confirmed with the nursery.", g3b
        )


class PlantingStockAnswersAgreeTests(_Farm):
    def review(self, g3, g3b, g3b_na=False):
        self.store("g3_0_seeds", g3)
        self.store("g3_2_planting_stock", g3b, not_applicable=g3b_na)
        return self.review_codes().get("planting_stock_answers_disagree")

    def test_established_only_beside_stock_established_this_period_is_flagged_on_both_pages(self):
        finding = self.review(
            {"planting_stock_used": ["established_in_place"]}, {"stock_organic_status": "all_nonorganic"}
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.module_key, "g3_0_seeds")
        sentence = (
            'G3.0 answers planting stock "Established perennials only — none planted or replaced this plan period", '
            'and G3.0b states the perennial planting stock established this plan period is "All nonorganic". The '
            "two answers disagree."
        )
        self.assertEqual(finding.details, [sentence])
        for module_key in ("g3_0_seeds", "g3_2_planting_stock"):
            self.assertIn(f"[REVIEW] {sentence}", _text(generate_module_pdf(self.osp, module_key)))

    def test_g3_0b_may_name_less_than_g3_0_never_more(self):
        self.assertIsNotNone(self.review({"planting_stock_used": ["organic"]}, {"stock_organic_status": "mixed"}))
        self.assertIsNotNone(self.review({"planting_stock_used": ["none"]}, {"stock_organic_status": "all_organic"}))
        # G3.0 covers annual vegetative stock too: organic trees beside nonorganic potato seed pieces.
        self.assertIsNone(
            self.review({"planting_stock_used": ["organic", "non_organic"]}, {"stock_organic_status": "all_organic"})
        )
        self.assertIsNone(
            self.review({"planting_stock_used": ["non_organic"]}, {"stock_organic_status": "all_nonorganic"})
        )

    def test_a_g3_0b_marked_not_applicable_is_not_read(self):
        self.assertIsNone(
            self.review(
                {"planting_stock_used": ["established_in_place"]}, {"stock_organic_status": "mixed"}, g3b_na=True
            )
        )

    def test_other_planting_stock_is_read_against_all_planting_stock(self):
        self.store("g3_0_seeds", {"planting_stock_used": ["organic"], "other_planting_stock_used": ["non_organic"]})
        finding = self.review_codes()["planting_stock_answers_disagree"]
        self.assertIn('other than perennial nursery stock "Non-organic", which its answer', finding.details[0])
        page = _text(generate_module_pdf(self.osp, "g3_0_seeds"))
        self.assertIn(
            "Planting stock other than perennial nursery stock: rhizomes, shoots, tubers, cuttings, clones", page
        )
        self.assertIn('[REVIEW] G3.0 answers planting stock other than perennial nursery stock "Non-organic"', page)
        # Closed by a "None used" stock answer, a stored answer there is not read.
        self.store("g3_0_seeds", {"planting_stock_used": ["none"], "other_planting_stock_used": ["non_organic"]})
        self.assertNotIn("planting_stock_answers_disagree", self.review_codes())


class ListingGapsOnThePlanReviewTests(_Farm):
    def test_each_material_the_plan_says_is_not_listed_yet_is_on_the_review(self):
        self.store(
            "g3_0_seeds",
            {
                "seeds_used": ["non_organic_treated"],
                "treatments_on_inputs_list": False,
                "planting_stock_used": ["non_organic"],
                "grafts_stock": "yes_not_listed",
            },
        )
        self.store("g3_2_planting_stock", {"stock_organic_status": "mixed", "stock_treatments": "treated_not_listed"})
        finding = self.review_codes()["seed_stock_materials_not_listed"]
        self.assertEqual(finding.count, 3)
        self.assertEqual(
            finding.details,
            [
                "G3.0 Seed treatments: not every seed treatment material is on the OSP inputs list yet",
                "G3.0 Grafting: not every grafting material is on the OSP inputs list yet",
                "G3.0b Using nonorganic stock: not every treatment material on the nonorganic planting stock is on "
                "the OSP inputs list yet",
            ],
        )

    def test_a_no_under_a_closed_page_is_not_on_the_review(self):
        self.store("g3_0_seeds", {"seeds_used": ["organic_untreated"], "treatments_on_inputs_list": False})
        self.store(
            "g3_2_planting_stock", {"stock_organic_status": "all_organic", "stock_treatments": "treated_not_listed"}
        )
        self.assertNotIn("seed_stock_materials_not_listed", self.review_codes())


class NewQuestionsTests(_Farm):
    def shown(self, module, answers):
        return {q.key for _page, q in visible_questions(module, {k: {"value": v} for k, v in answers.items()})}

    def test_each_new_answer_opens_the_follow_up_its_yes_opens(self):
        self.assertIn(
            "grafting_practices", self.shown(G3, {"planting_stock_used": ["organic"], "grafts_stock": "yes_not_listed"})
        )
        self.assertNotIn(
            "grafting_practices", self.shown(G3, {"planting_stock_used": ["organic"], "grafts_stock": "no"})
        )
        opened = self.shown(G3B, {"stock_organic_status": "mixed", "stock_treatments": "treated_not_listed"})
        self.assertIn("stock_treatment_applied_by", opened)
        self.assertNotIn("other_planting_stock_used", self.shown(G3, {"planting_stock_used": ["established_in_place"]}))
        self.assertIn("other_planting_stock_used", self.shown(G3, {"planting_stock_used": ["non_organic"]}))

    def test_wsda_c4_is_asked_of_an_operation_that_sells_stock_as_organic_and_prints(self):
        self.assertNotIn("resold_stock_bought_nonorganic", self.shown(G3B, {"stock_sold_as_organic": "not_sold"}))
        self.store(
            "g3_2_planting_stock",
            {"stock_sold_as_organic": "sold_organic_stock", "resold_stock_bought_nonorganic": "yes"},
        )
        page = _text(generate_module_pdf(self.osp, "g3_2_planting_stock"))
        self.assertIn("Was any of the planting stock you sell as organic bought as nonorganic stock? Yes", page)
