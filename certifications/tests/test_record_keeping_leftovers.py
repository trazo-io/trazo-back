"""Record keeping leftovers across CCOF G8.0 and WSDA AGR 2121 H, O and AGR 2264 (content 2026.12.21).

CCOF G8.0 A1 asks whether the operation keeps every record its activities need; the records attestation now also
requires storage records, invoices and bills of lading when the plan stores crops, sells as organic, or has the crop
moved by anyone other than a buyer picking up. B1's upload asks for the operator's own marked-up sample. C1's fourth
box (sell identical organic and non-organic, including sourced) is asked of bought-in product. G5.0 asks the disease
prevention records (H 4), G8.0 has an optional notes field (O 9), and the Parcel Application asks the number and issue
date of a certificate another operation held (AGR 2264 6a). Every new question is optional.
"""

import io
from pathlib import Path

from django.test import SimpleTestCase, TestCase

import yaml
from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.attestation_gates import blocked_attestations
from certifications.services.common_osp_records import confirm
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.required_records import NOT_CONFIRMED, UNRESOLVED, required_records
from company.models import Company, Establishment
from product.models import Parcel

G5 = MODULES_BY_KEY["g5_0_pest"]
G6 = MODULES_BY_KEY["g6_0_production"]
G8 = MODULES_BY_KEY["g8_0_record_keeping"]
NEW = {
    "g5_0_pest": {"disease_prevention_records"},
    "g6_0_production": {"bought_in_identical_to_organic"},
    "g8_0_record_keeping": {"records_additional_notes"},
    "parcel_application": {"prior_certificate_number", "prior_certificate_issue_date"},
}
BOUGHT_IN = {"split_operation": True, "nonorganic_product_source": ["bought_in_nonorganic"]}
TAKEN_OVER = {"currently_certified": "yes", "certified_operation_name": "Ruiz Orchards"}


def _visible(module, answers) -> set:
    return {q.key for _page, q in visible_questions(module, answers)}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Wenatchee Heights LLC")
        self.est = Establishment.objects.create(name="Wenatchee Heights", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _answer(self, module, **values):
        responses = dict(self.osp.module_responses or {})
        modules = dict(responses.get("modules") or {})
        entry = dict(modules.get(module) or {})
        entry["answers"] = {**(entry.get("answers") or {}), **values}
        modules[module] = entry
        responses["modules"] = modules
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _states(self) -> dict:
        self.osp.refresh_from_db()
        return {r.key: (r.state, r.because) for r in required_records(self.osp)}

    def _state(self, key):
        return (self._states().get(key) or (None, ""))[0]


class TheNewRecordTriggersReadOneAnswerEach(_Plan):
    def test_named_storage_requires_storage_records(self):
        self._answer("g6_2_storage", storage_locations=["certified_handler"])
        self.assertEqual(
            self._states().get("storage_records"),
            (NOT_CONFIRMED, "the storage section names where crops are stored"),
        )

    def test_selling_as_organic_requires_invoices_and_not_selling_requires_none(self):
        self._answer("g8_0_record_keeping", sells_as_organic=True)
        self.assertEqual(self._state("invoices"), NOT_CONFIRMED)
        self._answer("g8_0_record_keeping", sells_as_organic=False)
        self.assertNotIn("invoices", self._states())

    def test_an_unanswered_sales_answer_leaves_invoices_unresolved_until_confirmed(self):
        self.assertEqual(self._state("invoices"), UNRESOLVED)
        confirm(self.osp, ["invoices"], user=None)
        self.assertNotIn("invoices", self._states())

    def test_a_buyer_picking_up_requires_no_bill_of_lading_and_anyone_else_does(self):
        self._answer("g6_1_harvest_transport", who_transports=["buyer_pickup"])
        self.assertNotIn("bill_of_lading", self._states())
        self._answer("g6_1_harvest_transport", who_transports=["buyer_pickup", "warehouse_packer"])
        self.assertEqual(self._state("bill_of_lading"), NOT_CONFIRMED)

    def test_a_single_stored_transport_answer_still_fires(self):
        # A plan written before who_transports took several answers holds one value, not a list.
        self._answer("g6_1_harvest_transport", who_transports="own_vehicles")
        self.assertEqual(self._state("bill_of_lading"), NOT_CONFIRMED)
        self._answer("g6_1_harvest_transport", who_transports="buyer_pickup")
        self.assertNotIn("bill_of_lading", self._states())

    def test_the_attestation_is_refused_while_a_bill_of_lading_is_unconfirmed(self):
        self._answer("g6_1_harvest_transport", who_transports=["commercial_carrier"])
        # One record type confirmed, so the refusal is about the missing one and not the empty list.
        confirm(self.osp, ["harvest_records"], user=None)
        self.osp.refresh_from_db()
        blocked = blocked_attestations(G8, {"records_retention_attestation": True}, self.osp)
        self.assertIn("Bill of Lading", blocked["records_retention_attestation"])


class TheQuestionsOpenWhereTheFormsAskThem(SimpleTestCase):
    def test_the_identical_product_question_is_asked_only_of_bought_in_product(self):
        self.assertIn("bought_in_identical_to_organic", _visible(G6, BOUGHT_IN))
        self.assertNotIn(
            "bought_in_identical_to_organic",
            _visible(G6, {"split_operation": True, "nonorganic_product_source": ["buffer_zone_crop"]}),
        )
        self.assertNotIn("bought_in_identical_to_organic", _visible(G6, {**BOUGHT_IN, "split_operation": False}))

    def test_the_prior_certificate_is_asked_only_once_another_operation_is_named(self):
        self.assertTrue(NEW["parcel_application"] <= _visible(PARCEL_APPLICATION, TAKEN_OVER))
        self.assertFalse(NEW["parcel_application"] & _visible(PARCEL_APPLICATION, {"currently_certified": "yes"}))
        self.assertFalse(
            NEW["parcel_application"] & _visible(PARCEL_APPLICATION, {**TAKEN_OVER, "currently_certified": "no"})
        )

    def test_no_new_question_reopens_a_finished_plan(self):
        for module, answers in ((G5, {}), (G6, BOUGHT_IN), (G8, {}), (PARCEL_APPLICATION, TAKEN_OVER)):
            self.assertEqual(set(missing_required(module, answers)) & NEW[module.key], set(), module.key)

    def test_the_audit_trail_upload_asks_for_the_operators_own_sample(self):
        upload = next(q for page in G8.pages for q in page.questions if q.key == "audit_trail_exhibit")
        self.assertEqual(upload.kind, "upload")
        self.assertFalse(upload.required)
        self.assertTrue(upload.label["en"].startswith("Attach your own sample audit trail"), upload.label["en"])
        self.assertIn("highlighted", upload.label["en"])
        self.assertIn("resaltados", upload.label["es"])


class TheGoldenCasesReachTheirGates(SimpleTestCase):
    def test_the_bought_in_case_shows_the_identical_question_and_the_buffer_case_does_not(self):
        from certifications.management.commands.export_osp_module_fixture import GOLDEN_ANSWER_CASES

        cases = GOLDEN_ANSWER_CASES["g6_0_production"]
        self.assertIn("bought_in_identical_to_organic", _visible(G6, cases["bought_in_nonorganic"]))
        self.assertNotIn("bought_in_identical_to_organic", _visible(G6, cases["buffer_only_nonorganic"]))


class TheAnswersPrint(_Plan):
    def test_the_disease_prevention_records_print_in_g5_0(self):
        self._answer("g5_0_pest", disease_prevention_records="Pruning log with the date each block was cleaned.")
        text = _text(generate_module_pdf(self.osp, "g5_0_pest"))
        self.assertIn(
            "Describe the records you keep of your preventive disease management. Pruning log with the date each "
            "block was cleaned.",
            text,
        )

    def test_the_record_keeping_notes_print_in_g8_0(self):
        self._answer("g8_0_record_keeping", records_additional_notes="Bin tickets are filed by week.")
        text = _text(generate_module_pdf(self.osp, "g8_0_record_keeping"))
        self.assertIn("Anything else about your record keeping (optional) Bin tickets are filed by week.", text)

    def test_the_identical_product_answer_prints_in_g6_0(self):
        self._answer("g6_0_production", **BOUGHT_IN, bought_in_identical_to_organic=True)
        text = _text(generate_module_pdf(self.osp, "g6_0_production"))
        self.assertIn(
            "Is any of the non-organic product you buy in the same crop or product as an organic one you sell? Yes",
            text,
        )

    def test_the_prior_certificate_prints_on_the_parcel_page(self):
        parcel = Parcel.objects.create(
            name="Fuji Blocks",
            establishment=self.est,
            area=6.0,
            application_answers={
                **TAKEN_OVER,
                "prior_certifier_name": "WSDA",
                "prior_certificate_number": "WSDA-2187",
                "prior_certificate_issue_date": "2025-03-14",
            },
        )
        text = _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=parcel))
        self.assertIn("Certificate number on that certificate", text)
        self.assertIn("WSDA-2187", text)
        self.assertIn("Issue date on that certificate", text)
        self.assertIn("2025", text.split("Issue date on that certificate", 1)[1][:60])


class TheRegisterRowsAreClosed(SimpleTestCase):
    ROWS = {
        "ccof/forms/G8.0-record-keeping.yaml": ("A1", "B1", "C1"),
        "wsda/forms/2121-H-disease.yaml": ("4",),
        "wsda/forms/2121-O-recordkeeping.yaml": ("9",),
        "wsda/forms/2264-site-application.yaml": ("6a",),
    }

    def test_every_row_is_covered_and_cites_questions_that_exist(self):
        root = Path(__file__).resolve().parents[2] / "documentation/compliance/certifiers"
        modules = [*MODULES_BY_KEY.values(), PARCEL_APPLICATION]
        keys = {f"{m.key}.{q.key}" for m in modules for page in m.pages for q in page.questions}
        for path, refs in self.ROWS.items():
            items = yaml.safe_load((root / path).read_text())["items"]
            for ref in refs:
                row = next(i for i in items if str(i["ref"]) == ref)
                self.assertEqual(row["status"], "covered", f"{path} {ref}")
                for cited in row["trazo"]["questions"]:
                    self.assertIn(cited, keys, f"{path} {ref}")
