"""CCOF G6.5 B and C, direct marketing (content 2026.12.18).

`sales_soe_channels` was free text: an operation could name a farmers' market there, but nothing asked whether it
sells directly to consumers, nothing listed the venues in CCOF's columns, and nothing asked how organic is told
apart from non-organic at them. G6.5 now asks each, as the form asks it (ORGB35 V2, 12/31/2023):

* B1: direct sales yes or no (the no is the form's "not applicable, stop"), and the venues;
* B1a and B1b: each farmers' market, and each other venue, in the form's columns;
* C1: whether non-organic products are sold too, and how the two are told apart; the sample and photo options
  name the samples upload, so one chosen with nothing attached prints a [REVIEW] line.
"""

import io
from pathlib import Path

from django.test import SimpleTestCase, TestCase

import yaml

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

G65 = MODULES_BY_KEY["g6_5_sales_soe"]
BASE = {
    "sales_soe_channels": "Farmers' markets and a farm stand.",
    "sales_soe_supplier_verification": "no",
    "sales_soe_lot_linkage": "Each sale names the harvest lot.",
}


def _visible(answers) -> set:
    return {q.key for _page, q in visible_questions(G65, answers)}


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class TheQuestionsOpenAsTheFormAsksThem(SimpleTestCase):
    def test_no_direct_sales_ends_the_section(self):
        visible = _visible({**BASE, "direct_sales": "no"})
        self.assertNotIn("direct_sales_venues", visible)
        self.assertNotIn("direct_sales_nonorganic", visible)

    def test_each_venue_kind_opens_its_own_list(self):
        markets = _visible({**BASE, "direct_sales": "yes", "direct_sales_venues": ["farmers_market"]})
        self.assertIn("farmers_markets_detail", markets)
        self.assertNotIn("other_venues_detail", markets)
        stand = _visible({**BASE, "direct_sales": "yes", "direct_sales_venues": ["farm_stand"]})
        self.assertIn("other_venues_detail", stand)
        self.assertNotIn("farmers_markets_detail", stand)

    def test_signage_is_asked_only_where_non_organic_is_sold_too(self):
        only = _visible({**BASE, "direct_sales": "yes", "direct_sales_nonorganic": "only_organic"})
        self.assertNotIn("direct_sales_differentiation", only)
        both = _visible({**BASE, "direct_sales": "yes", "direct_sales_nonorganic": "also_nonorganic"})
        self.assertIn("direct_sales_differentiation", both)

    def test_a_plan_finished_before_these_questions_stays_finished(self):
        self.assertEqual(missing_required(G65, BASE), [])

    def test_a_direct_seller_is_asked_its_venues_and_whether_non_organic_is_sold(self):
        missing = set(missing_required(G65, {**BASE, "direct_sales": "yes"}))
        self.assertEqual(missing, {"direct_sales_venues", "direct_sales_nonorganic"})


class TheModulePdfPrintsWhatTheFormAsks(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Farmtown Greens LLC")
        self.est = Establishment.objects.create(name="Farmtown Greens", company=company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _store(self, **answers):
        self.osp.module_responses = {
            "schema_version": 1,
            "modules": {
                "g6_5_sales_soe": {
                    "answers": {k: {"at": "2026-11-17T10:00:00Z", "value": v} for k, v in {**BASE, **answers}.items()}
                }
            },
        }
        self.osp.save(update_fields=["module_responses"])

    def _pdf(self):
        return _pdf_text(generate_module_pdf(self.osp, "g6_5_sales_soe"))

    def test_the_markets_and_the_signage_print(self):
        self._store(
            direct_sales="yes",
            direct_sales_venues=["farmers_market", "farm_stand"],
            farmers_markets_detail="Farmtown Farmers' Market Association, 123 Main St, Farmtown; Mon and Sat; no",
            other_venues_detail="Farm stand, 4 Ridge Rd, Farmtown; yes",
            direct_sales_nonorganic="also_nonorganic",
            direct_sales_differentiation=["separate_areas"],
            direct_sales_separate_areas_detail="Organic on the left table, conventional on the right, signed.",
        )
        text = self._pdf()
        for phrase in (
            "B. Direct marketing",
            "Yes, we sell directly to consumers",
            "Farmers' markets; Farm stand",
            "Farmtown Farmers' Market Association, 123 Main St, Farmtown; Mon and Sat; no",
            "Farm stand, 4 Ridge Rd, Farmtown; yes",
            "Yes, we also sell non-organic products",
            "Separate sales areas for organic and non-organic",
            "Organic on the left table, conventional on the right, signed.",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("[REVIEW] The answer says it is attached", text)

    def test_signage_said_attached_with_no_photo_prints_a_review_line(self):
        self._store(
            direct_sales="yes", direct_sales_nonorganic="also_nonorganic", direct_sales_differentiation=["signage"]
        )
        self.assertIn(
            '[REVIEW] The answer says it is attached (Clear "organic" and "nonorganic" signage (photo attached)), '
            "but no file is attached to this plan for it.",
            self._pdf(),
        )


class TheRegisterRowsAreClosed(SimpleTestCase):
    def test_ccof_g6_5_direct_marketing_rows_are_covered_and_cite_questions_that_exist(self):
        root = Path(__file__).resolve().parents[2] / "documentation/compliance/certifiers"
        items = yaml.safe_load((root / "ccof/forms/G6.5-sourcing-direct-marketing.yaml").read_text())["items"]
        keys = {q.key for page in G65.pages for q in page.questions}
        for ref in ("Preamble (applicability)", "B1", "B1a", "B1b", "C1"):
            row = next(i for i in items if i["ref"] == ref)
            self.assertEqual(row["status"], "covered", ref)
            for cited in row["trazo"]["questions"]:
                self.assertIn(cited.split(".", 1)[1], keys, ref)
