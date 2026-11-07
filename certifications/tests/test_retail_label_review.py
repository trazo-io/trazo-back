"""Retail labels: the certifier statement's place, review by the certifying agent, unpackaged labels.

CCOF G7.0 B1: "Packaged retail product labels must state 'Certified Organic by CCOF' (or similar), located
below the information identifying your operation or the handler/distributor." (§ 205.303(b)(2)).
CCOF G7.0 B2: "Do you use any retail labels for unpackaged organic products (PLU stickers/tags, twist ties,
plant tags, etc.) that include the USDA seal, CCOF name/seal, or an ingredient statement?"
WSDA AGR 2121 §N 5a: "have you submitted a copy of all current retail labels making organic claims to WSDA
Organic Program for approval? Yes, all current labels have been approved / No, attached are new or updated
retail labels for review." OTCO C8 8.2-1 adds "no labels are currently in use but they will be submitted to
OTCO for review and approval before printing".
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment

AT = "2026-11-07T12:00:00Z"
CCOF = "California Certified Organic Farmers (CCOF)"
OTCO = "Oregon Tilth Certified Organic (OTCO)"
WSDA = "Washington State Department of Agriculture (WSDA)"
RETAIL = {"product_leaves_as": ["consumer_packaging"], "label_states_certifier": True}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    def plan(self, g7_0=None, certifier=CCOF, na=False):
        est = Establishment.objects.create(
            name="Label Farm", company=Company.objects.create(name="Label Farm LLC"), state="WA"
        )
        entry = {"answers": {k: {"at": AT, "value": v} for k, v in (g7_0 or {}).items()}}
        if na:
            entry["not_applicable"] = True
        return OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": {"g7_0_labeling": entry}},
        )

    def page(self, osp):
        return _text(generate_module_pdf(osp, "g7_0_labeling"))

    def row(self, osp, agent, match, ref):
        form = next(f for f in load_forms(agent) if match(f))
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class StatementPlacement(_Plan):
    def test_asked_and_printed_when_the_label_states_the_certifier(self):
        page = self.page(self.plan({**RETAIL, "certifier_statement_below_operation": True}))
        self.assertIn('is the "Certified organic by" statement below the name of the operation', page)

    def test_hidden_when_the_label_does_not_state_the_certifier(self):
        osp = self.plan(
            {
                "product_leaves_as": ["consumer_packaging"],
                "label_states_certifier": False,
                "certifier_statement_below_operation": True,
            }
        )
        self.assertNotIn('"Certified organic by" statement below', self.page(osp))


class CertifierReview(_Plan):
    def test_each_answer_prints(self):
        page = self.page(self.plan({**RETAIL, "retail_labels_certifier_review": "all_approved"}))
        self.assertIn("Yes, every current label has been approved", page)
        page = self.page(self.plan({**RETAIL, "retail_labels_certifier_review": "submitted_before_printing"}))
        self.assertIn("each will be submitted for review before it is printed", page)

    def test_labels_in_use_not_submitted_is_flagged(self):
        page = self.page(self.plan({**RETAIL, "retail_labels_certifier_review": "not_submitted"}))
        self.assertIn("[REVIEW] Retail labels in use have not been submitted to the certifying agent", page)

    def test_attached_with_no_file_is_flagged(self):
        page = self.page(self.plan({**RETAIL, "retail_labels_certifier_review": "new_or_updated_attached"}))
        self.assertIn("[REVIEW] The answer says it is attached", page)

    def test_hidden_for_bulk_only_product(self):
        osp = self.plan({"product_leaves_as": ["bulk_bins_marked"], "retail_labels_certifier_review": "not_submitted"})
        self.assertNotIn("Retail labels in use have not been submitted", self.page(osp))


class UnpackagedLabels(_Plan):
    def _visible(self, answers):
        from certifications.osp_modules.conditions import visible_questions
        from certifications.osp_modules.g7_0_labeling import G7_0_LABELING

        return {q.key for _page, q in visible_questions(G7_0_LABELING, answers)}

    def test_asked_of_every_operation_and_printed(self):
        page = self.page(self.plan({"product_leaves_as": ["bulk_bins_marked"], "unpackaged_retail_labels": True}))
        self.assertIn("Do you put retail labels on unpackaged product (PLU stickers, tags, twist ties)", page)
        self.assertIn("unpackaged_retail_labels", self._visible({"product_leaves_as": ["bulk_bins_marked"]}))

    def test_the_upload_shows_only_on_yes(self):
        self.assertIn("unpackaged_label_upload", self._visible({"unpackaged_retail_labels": True}))
        self.assertNotIn("unpackaged_label_upload", self._visible({"unpackaged_retail_labels": False}))


class NotApplicable(_Plan):
    def test_the_attestation_prints_a_review(self):
        page = self.page(self.plan(na=True))
        self.assertIn("Not applicable", page)
        self.assertIn("[REVIEW] Product leaves in nonretail containers that carry no organic identification", page)
        self.assertIn("§ 205.307(a)(1)", page)

    def test_an_answered_module_prints_no_such_line(self):
        self.assertNotIn("carry no organic identification. Nonretail", self.page(self.plan(RETAIL)))


class Optional(TestCase):
    def test_the_new_questions_are_optional(self):
        from certifications.osp_modules.g7_0_labeling import G7_0_LABELING

        questions = {q.key: q for p in G7_0_LABELING.pages for q in p.questions}
        for key in (
            "certifier_statement_below_operation",
            "retail_labels_certifier_review",
            "unpackaged_retail_labels",
            "unpackaged_label_upload",
        ):
            self.assertFalse(questions[key].required, key)


class RegisterRows(_Plan):
    def test_wsda_n_5a_reads_answered(self):
        osp = self.plan({**RETAIL, "retail_labels_certifier_review": "all_approved"}, certifier=WSDA)
        row = self.row(osp, "wsda", lambda f: f.code == "N", "5a")
        self.assertNotIn(row.state, ("unanswered", "unresolved"))

    def test_otco_8_3_1_reads_answered(self):
        osp = self.plan(
            {**RETAIL, "retail_labels_certifier_review": "all_approved", "label_claim_review_process": "I do."},
            certifier=OTCO,
        )
        self.assertEqual(self.row(osp, "otco", lambda f: f.document_id == "C8", "8.3-1").state, "answered")

    def test_ccof_b1_reads_answered_once_the_placement_is_given(self):
        base = {**RETAIL, "label_has_usda_seal": True}
        osp = self.plan(base)
        self.assertNotEqual(self.row(osp, "ccof", lambda f: f.document_id == "ORGB34", "B1").state, "answered")
        osp = self.plan({**base, "certifier_statement_below_operation": True})
        self.assertNotIn(
            self.row(osp, "ccof", lambda f: f.document_id == "ORGB34", "B1").state, ("unanswered", "unresolved")
        )
