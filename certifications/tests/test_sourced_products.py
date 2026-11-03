"""Bought-in organic product on the plan's G6.5 (2026.11.08).

CCOF G6.5 A1-A4 and OTCO C12 12.2-4a ask what the operation sources from other operations, from whom,
each supplier's certificate (current within 15 months), and for an uncertified broker the certified
operation it buys from and its Exempt Handler Affidavit. G6.5 used to ask only whether product is
bought in and how certificates are checked, in prose.
"""

import io
import zipfile
from datetime import date, timedelta

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan, Supplier
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from certifications.services.packet_answers import form_answer_states
from certifications.tests.test_supplier_register import _Base
from documents.models import GeneratedDocument

AT = "2026-11-08T10:00:00+00:00"
CCOF = "CCOF Certification Services, LLC"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(_Base):
    def plan(self, buys="yes", extra=None):
        answers = {
            "sales_soe_channels": {"at": AT, "value": "Wholesale to a packer."},
            "sales_soe_supplier_verification": {"at": AT, "value": buys},
            "sales_soe_verification_method": {"at": AT, "value": "Certificate checked at each order."},
            "sales_soe_lot_linkage": {"at": AT, "value": "Lot code on every invoice."},
            **(extra or {}),
        }
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=CCOF,
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {"g6_5_sales_soe": {"answers": answers}},
            },
        )

    def sourcing(self, name="Valley Organic Co-op", status="certified", **patch):
        supplier = self.supplier(name=name, organic_status=status)
        r = self.client.patch(
            self.url(suffix=f"{supplier.id}/"),
            {"sourced_products": "Blueberries, fresh: for our CSA boxes", **patch},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        supplier.refresh_from_db()
        return supplier

    def g6_5(self, osp) -> str:
        return _text(generate_module_pdf(osp, "g6_5_sales_soe"))

    def ccof_row(self, osp, ref):
        form = next(f for f in load_forms("ccof") if f.code == "G6.5")
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class PanelTests(_Plan):
    def test_the_panel_is_asked_only_of_an_operation_that_buys_in(self):
        self.sourcing()
        text = self.g6_5(self.plan(buys="no"))
        self.assertNotIn("Valley Organic Co-op", text)
        self.assertNotIn("Suppliers of bought-in organic product", text)

    def test_a_certified_supplier_with_a_current_copy(self):
        supplier = self.sourcing(certifier_name="CCOF Certification Services, LLC")
        self.certificate(supplier, date.today() - timedelta(days=40))
        text = self.g6_5(self.plan())
        self.assertIn("Valley Organic Co-op Bought in: Blueberries, fresh: for our CSA boxes.", text)
        self.assertIn("Certified organic operation (CCOF Certification Services, LLC).", text)
        self.assertIn("is on file.", text)
        self.assertIn("A copy is held in Trazo; it is not included in this document.", text)
        self.assertNotIn("[REVIEW]", text)
        self.assertNotIn("verified", text.lower())

    def test_a_missing_or_old_copy_is_flagged(self):
        supplier = self.sourcing()
        self.assertIn("[REVIEW] No copy of this supplier's organic certificate", self.g6_5(self.plan()))
        old = date.today() - timedelta(days=500)
        self.certificate(supplier, old)
        self.assertIn(
            f"[REVIEW] The newest certificate copy on file was issued {old.isoformat()}, more than 15 months ago.",
            self.g6_5(self.plan()),
        )

    def test_an_uncertified_broker_needs_its_source_and_affidavit(self):
        self.sourcing(name="Harbor Produce Brokers", status="not_certified")
        text = self.g6_5(self.plan())
        self.assertIn("Not a certified organic operation (a broker or distributor).", text)
        self.assertIn("[REVIEW] The certified operation this supplier sources from is not named.", text)
        self.assertIn("[REVIEW] No Exempt Handler Affidavit from this supplier is on file in Trazo.", text)

    def test_a_broker_with_its_source_and_affidavit_reads_clean(self):
        eha = self.upload(title="Exempt Handler Affidavit, Harbor Produce Brokers")
        self.sourcing(
            name="Harbor Produce Brokers",
            status="not_certified",
            source_operation="Valley Organic Co-op",
            exempt_handler_affidavit=eha.id,
        )
        text = self.g6_5(self.plan())
        self.assertIn("Sources from: Valley Organic Co-op.", text)
        self.assertIn("Its Exempt Handler Affidavit is on file.", text)
        self.assertNotIn("[REVIEW]", text)

    def test_no_sourcing_supplier_and_an_unstated_status_are_flagged(self):
        self.assertIn(
            "[REVIEW] The plan says the operation buys in or co-markets organic product", self.g6_5(self.plan())
        )
        Supplier.objects.all().delete()
        self.sourcing(status="unknown")
        self.assertIn(
            "[REVIEW] Whether this supplier is a certified organic operation is not stated.", self.g6_5(self.plan())
        )

    def test_a_seed_supplier_that_supplies_no_bought_in_product_is_not_listed(self):
        self.supplier(name="Columbia Nursery")
        self.sourcing()
        text = self.g6_5(self.plan())
        self.assertIn("Valley Organic Co-op", text)
        self.assertNotIn("Columbia Nursery", text)


class ApiTests(_Plan):
    def test_the_register_states_what_g6_5_says(self):
        self.sourcing(name="A")
        self.supplier(name="Seed House")
        rows = {r["name"]: r for r in self.client.get(self.url()).json()}
        self.assertEqual(rows["A"]["sourcing_state"], "certificate_missing")
        self.assertIsNone(rows["Seed House"]["sourcing_state"])
        self.assertIn("exempt_handler_affidavit_title", rows["A"])
        self.assertIsNone(rows["A"]["exempt_handler_affidavit_title"])
        self.assertIsNone(rows["A"]["sourcing_certificate_issued_on"])

    def test_the_date_is_the_newest_copys_whatever_order_they_were_filed_in(self):
        """Review of app #241: the app took certificates[0] as the newest."""
        supplier = self.sourcing(name="Two Copies Co")
        newer = date.today() - timedelta(days=20)
        self.certificate(supplier, newer)
        self.certificate(supplier, date.today() - timedelta(days=600))
        row = next(r for r in self.client.get(self.url()).json() if r["name"] == "Two Copies Co")
        self.assertEqual(row["sourcing_certificate_issued_on"], newer.isoformat())
        self.assertEqual(row["sourcing_state"], "on_file")

    def test_another_farms_affidavit_fails_like_a_missing_one(self):
        supplier = self.supplier(name="Broker", organic_status="not_certified")
        theirs = self.upload(est=self.other_est)
        foreign = self.client.patch(
            self.url(suffix=f"{supplier.id}/"), {"exempt_handler_affidavit": theirs.id}, format="json"
        )
        missing = self.client.patch(
            self.url(suffix=f"{supplier.id}/"), {"exempt_handler_affidavit": 999999}, format="json"
        )
        self.assertEqual(foreign.status_code, 400)
        self.assertEqual(
            str(foreign.json()).replace(str(theirs.id), "<id>"), str(missing.json()).replace("999999", "<id>")
        )

    def test_an_affidavit_a_supplier_names_cannot_be_deleted(self):
        eha = self.upload(title="EHA")
        self.sourcing(status="not_certified", exempt_handler_affidavit=eha.id)
        r = self.client.delete(f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/{eha.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "supplier_affidavit_in_use")
        self.assertTrue(GeneratedDocument.objects.filter(pk=eha.pk).exists())


class PacketAndCoverageTests(_Plan):
    def test_the_certificate_and_the_affidavit_ride_under_suppliers(self):
        certified = self.sourcing()
        self.certificate(certified, date.today() - timedelta(days=10))
        eha = self.upload(title="EHA")
        broker = self.sourcing(
            name="Harbor Produce Brokers",
            status="not_certified",
            source_operation="Valley",
            exempt_handler_affidavit=eha.id,
        )
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.plan())))
        names = packet.namelist()
        cert_path = f"suppliers/{certified.pk}-Valley Organic Co-op-certificate.pdf"
        eha_path = f"suppliers/{broker.pk}-Harbor Produce Brokers-exempt-handler-affidavit.pdf"
        self.assertIn(cert_path, names)
        self.assertIn(eha_path, names)
        g6_5 = _text(packet.read("modules/G6_5.pdf"))
        self.assertIn(f"Copy in this packet: {cert_path}", g6_5)
        self.assertIn(f"Copy in this packet: {eha_path}", g6_5)

    def test_nothing_ships_when_nothing_is_bought_in(self):
        supplier = self.sourcing()
        self.certificate(supplier, date.today())
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.plan(buys="no"))))
        self.assertFalse([n for n in packet.namelist() if n.startswith("suppliers/")])

    def test_ccof_a2_is_answered_only_with_a_current_copy(self):
        supplier = self.sourcing()
        osp = self.plan()
        self.assertEqual(self.ccof_row(osp, "A2").state, "attachment_missing")
        self.certificate(supplier, date.today() - timedelta(days=500))
        self.assertEqual(self.ccof_row(osp, "A2").state, "attachment_missing")
        self.certificate(supplier, date.today() - timedelta(days=5))
        self.assertEqual(self.ccof_row(osp, "A2").state, "answered")

    def test_the_rows_do_not_apply_when_nothing_is_bought_in(self):
        osp = self.plan(buys="no")
        self.assertEqual(self.ccof_row(osp, "A2").state, "not_applicable")
        self.assertEqual(self.ccof_row(osp, "A4").state, "not_applicable")

    def test_an_other_box_under_a_question_that_does_not_apply_reads_as_words(self):
        """Review of #270: the question index printed "... does not apply (sales_soe_supplier_verification
        answered no')" for the "other" box under a hidden question."""
        from certifications.osp_modules import MODULES_BY_KEY
        from certifications.services.packet_answers import question_state
        from certifications.services.question_index import _trigger_words

        answers = self.plan(buys="no").module_responses["modules"]["g6_5_sales_soe"]["answers"]
        state, detail = question_state(
            MODULES_BY_KEY["g6_5_sales_soe"],
            "sourcing_transport_commingling_other",
            answers,
            na_attested=False,
            section_uploads=0,
        )
        self.assertEqual(state, "not_applicable")
        self.assertEqual(detail, "sales_soe_supplier_verification = 'no'")
        words = _trigger_words("g6_5_sales_soe.sourcing_transport_commingling_other", detail)
        self.assertIn('"Do you buy or resell organic product from anyone else?" answered', words)
        self.assertNotIn("sales_soe_supplier_verification", words)

    def test_ccof_a3_and_a4_read_their_questions(self):
        osp = self.plan(
            extra={
                "sourcing_transport_verification": {"at": AT, "value": ["certified_supplier_documentation"]},
                "sourcing_transport_commingling": {"at": AT, "value": ["only_certified"]},
            }
        )
        self.assertEqual(self.ccof_row(osp, "A3").state, "answered")
        self.assertEqual(self.ccof_row(osp, "A4").state, "answered")
