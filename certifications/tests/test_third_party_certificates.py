"""Third-party certificates: what CCOF, OTCO and WSDA ask about the operations a farm relies on (2026.11.04).

WHY THIS EXISTS
---------------
* A handler's certificate copy was uploadable on the facility record and never left Trazo: the
  module PDF said "not embedded", while CCOF G6.1 C3 and OTCO C7 7.10-3 ask for it attached.
* Nothing asked how, or how often, the operation checks that a handler stays certified (OTCO C7
  7.10-5, WSDA L1a/L1b), or how often a supplier's certificate is reviewed (CCOF G8.0 D2).
* OTCO's fraud prevention plan (2-2) and WSDA P5 ask how suppliers are approved and followed;
  seven of OTCO's eleven controls had no answer.
* OTCO C12 12.2-4b asks whether a bought-in product's paperwork names it organic.
* An uncertified storage facility's signed statement (CCOF's affidavit, OTCO's sheet) had no slot.
"""

import io
import zipfile

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase

from certifications.models import OrganicSystemPlan, PostHarvestFacility
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.services.osp_module_pdf import generate_osp_packet
from company.models import Company, Establishment

from .test_renewal_packet_contents import _pdf_text


def _envelope(value):
    return {"at": "2026-08-21T11:28:46+00:00", "value": value}


def _visible(module_key, **answers):
    return {
        q.key
        for _page, q in visible_questions(MODULES_BY_KEY[module_key], {k: _envelope(v) for k, v in answers.items()})
    }


class HandlerCheckTests(SimpleTestCase):
    def test_a_certified_handler_opens_how_and_how_often_it_is_checked(self):
        keys = _visible("g6_1_harvest_transport", handled_by_another_operation="yes_certified")
        self.assertIn("handler_cert_verification_method", keys)
        self.assertIn("handler_cert_verification_frequency", keys)

    def test_an_uncertified_handler_or_a_title_transfer_asks_neither(self):
        for routing in ("yes_uncertified", "yes_ownership_transfers", "no"):
            keys = _visible("g6_1_harvest_transport", handled_by_another_operation=routing)
            self.assertNotIn("handler_cert_verification_method", keys, routing)
            self.assertNotIn("handler_cert_verification_frequency", keys, routing)

    def test_each_other_opens_its_description(self):
        keys = _visible(
            "g6_1_harvest_transport",
            handled_by_another_operation="yes_certified",
            handler_cert_verification_method=["other"],
            handler_cert_verification_frequency="other",
        )
        self.assertIn("handler_cert_verification_method_other", keys)
        self.assertIn("handler_cert_verification_frequency_other", keys)


class SupplierTests(SimpleTestCase):
    def test_the_review_frequency_follows_a_certificate_check(self):
        self.assertIn(
            "supplier_certificate_review_frequency",
            _visible("g2_0_fraud_prevention", fraud_mitigation_practices=["organic_integrity_database"]),
        )
        self.assertNotIn(
            "supplier_certificate_review_frequency",
            _visible("g2_0_fraud_prevention", fraud_mitigation_practices=["employee_training"]),
        )

    def test_the_approval_controls_cover_what_otco_asks(self):
        options = {
            o.value
            for page in MODULES_BY_KEY["g2_0_fraud_prevention"].pages
            for q in page.questions
            if q.key == "supplier_approval_controls"
            for o in q.options
        }
        self.assertTrue(
            {
                "approval_program",
                "annual_certificate_refresh",
                "product_specifications",
                "food_safety_audit",
                "capacity_check",
                "supplier_residue_results",
                "residue_notice",
            }
            <= options
        )

    def test_a_no_on_bought_in_paperwork_asks_why(self):
        keys = _visible(
            "g6_5_sales_soe", sales_soe_supplier_verification="yes", sourced_products_identified_organic=False
        )
        self.assertIn("sourced_products_identification_detail", keys)
        self.assertNotIn(
            "sourced_products_identified_organic", _visible("g6_5_sales_soe", sales_soe_supplier_verification="no")
        )

    def test_an_uncertified_storage_facility_takes_its_signed_statement(self):
        keys = _visible("g6_2_storage", storage_locations=["uncertified_facility"])
        self.assertIn("uncertified_facility_statement_upload", keys)
        self.assertNotIn(
            "uncertified_facility_statement_upload", _visible("g6_2_storage", storage_locations=["on_farm_cold"])
        )


class HandlerCertificateRidesInThePacketTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Handler Co")
        self.est = Establishment.objects.create(name="Handler Farm", company=company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name="WSDA"
        )
        self.facility = PostHarvestFacility.objects.create(
            establishment=self.est,
            name="Valley Packers",
            facility_type="packer",
            role="handling",
            certification_number="WA-123",
            certifier_name="Example Certifier",
        )
        self.facility.cert_document.save("valley.pdf", ContentFile(b"%PDF-1.4 certificate"), save=True)

    def _answer(self, routing):
        self.osp.module_responses = {
            "modules": {"g6_1_harvest_transport": {"answers": {"handled_by_another_operation": _envelope(routing)}}}
        }
        self.osp.save(update_fields=["module_responses"])
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))

    def test_the_copy_ships_under_handlers_and_the_facility_line_names_it(self):
        zf = self._answer("yes_certified")
        paths = [n for n in zf.namelist() if n.startswith("handlers/")]
        self.assertEqual(paths, [f"handlers/{self.facility.pk}-Valley Packers.pdf"])
        self.assertEqual(zf.read(paths[0]), b"%PDF-1.4 certificate")
        module = _pdf_text(zf.read("modules/G6_1.pdf"))
        self.assertIn(f"Organic certificate of Valley Packers: {paths[0]}", module)
        self.assertNotIn("not embedded", module)

    def test_no_copy_ships_when_the_plan_names_no_facility(self):
        # The crop changes hands at delivery: the plan shows no facility table, so a certificate
        # in the ZIP would be a file nothing names.
        zf = self._answer("yes_ownership_transfers")
        self.assertFalse([n for n in zf.namelist() if n.startswith("handlers/")])
