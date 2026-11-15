"""The plan names each seedling supplier and the certificate copy behind it (2026.11.05).

CCOF G3.0 A2, OTCO C3 3.1-2 and WSDA 2121-B 1/1a ask for the organic certificate of EACH supplier of
purchased seedlings. Until this slice a certificate was a plan-level upload tied to no supplier, so
the packet could not say whose certificate it was, and the "certificate kept for each supplier"
answer printed with nothing behind it.

G3.0a now prints a panel read from the transplant records and the supplier register: each supplier
a transplant purchase names, and whether a copy covers its latest purchase. The copy the panel names
rides in the ZIP under suppliers/. The coverage page holds the four rows open until every such
supplier has a covering copy, and inside a packet build until that copy is in the ZIP.
"""

import io
import zipfile
from datetime import date

from django.test import override_settings

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from certifications.services.packet_answers import form_answer_states
from certifications.tests.test_supplier_register import _Base
from company.models import Company
from history.models import Production
from product.models import Parcel
from users.models import User, WorksIn

AT = "2026-11-05T10:00:00+00:00"
CCOF = "CCOF Certification Services, LLC"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(_Base):
    def plan(self, seedlings_used=("purchased_organic",), g3_1=None, certifier=CCOF):
        modules = {
            "g3_0_seeds": {"answers": {"seedlings_used": {"at": AT, "value": list(seedlings_used)}}},
            "g3_1_seedlings": g3_1
            or {"answers": {"seedlings_description": {"at": AT, "value": "Bought from Columbia Nursery."}}},
        }
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules},
        )

    def g3_0a(self, osp) -> str:
        return _text(generate_module_pdf(osp, "g3_1_seedlings"))

    def packet(self, osp) -> zipfile.ZipFile:
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))

    def ccof_row(self, osp, ref="A2"):
        form = next(f for f in load_forms("ccof") if f.code == "G3.0")
        return next(row for row in form_answer_states(osp, [form])[id(form)] if row.ref == ref)


class PanelTests(_Plan):
    def test_a_covering_copy_is_named_beside_its_supplier(self):
        supplier = self.supplier(certifier_name="WSDA", nop_operation_id="8150001234")
        self.certificate(supplier, date(2025, 1, 15))
        self.planting()
        text = self.g3_0a(self.plan())
        self.assertIn("Seedling suppliers on the transplant records", text)
        self.assertIn(
            "Columbia Nursery 1 transplant purchase recorded, latest 2025-04-02. WSDA, NOP ID 8150001234.", text
        )
        self.assertIn("Organic certificate issued 2025-01-15 covers the latest purchase.", text)
        self.assertIn("A copy is held in Trazo; it is not included in this document.", text)
        self.assertIn("not a check against the USDA Organic Integrity Database", text)
        self.assertNotIn("verified", text.lower())

    def test_a_supplier_with_no_copy_is_flagged_for_review(self):
        self.supplier()
        self.planting()
        text = self.g3_0a(self.plan())
        self.assertIn("[REVIEW] No copy of this supplier's organic certificate is on file in Trazo.", text)

    def test_a_name_the_register_does_not_hold_is_listed_not_guessed(self):
        self.supplier()
        self.planting(supplier="Columbia Nursery Inc")
        text = self.g3_0a(self.plan())
        self.assertIn("Columbia Nursery Inc", text)
        self.assertIn("[REVIEW] This name is not in the operation's supplier register", text)

    def test_an_earlier_purchase_the_copy_does_not_cover_is_counted(self):
        supplier = self.supplier()
        self.certificate(supplier, date(2025, 1, 15))
        self.planting(on=date(2022, 4, 2))
        self.planting(on=date(2025, 4, 2))
        text = self.g3_0a(self.plan())
        self.assertIn("2 transplant purchases recorded, latest 2025-04-02.", text)
        self.assertIn(
            "[REVIEW] 1 earlier purchase from this supplier is not covered by a certificate copy on file.", text
        )

    def test_only_this_farms_bought_transplants_are_listed(self):
        self.planting(supplier="Saved Stock Farm", seeds_source="farm_saved")
        other_parcel = Parcel.objects.create(name="North 1", establishment=self.other_est, area=3.0)
        other_season = Production.objects.create(
            name="North 2025", start_date=self.season.start_date, parcel=other_parcel
        )
        self.planting(supplier="Elsewhere Nursery", history=other_season)
        text = self.g3_0a(self.plan())
        self.assertIn("No transplant purchase naming a supplier is recorded in Trazo.", text)
        self.assertNotIn("Elsewhere Nursery", text)
        self.assertNotIn("Saved Stock Farm", text)


class PacketTests(_Plan):
    def test_the_copy_rides_under_suppliers_and_the_panel_names_its_path(self):
        supplier = self.supplier()
        self.certificate(supplier, date(2025, 1, 15))
        self.planting()
        packet = self.packet(self.plan())
        path = f"suppliers/{supplier.pk}-Columbia Nursery-2025-01-15.pdf"
        self.assertIn(path, packet.namelist())
        self.assertEqual(packet.read(path), b"%PDF-1.4 certificate")
        self.assertIn(f"Copy in this packet: {path}", _text(packet.read("modules/G3_0a.pdf")))

    def test_nothing_ships_when_the_section_is_attested_not_applicable(self):
        supplier = self.supplier()
        self.certificate(supplier, date(2025, 1, 15))
        self.planting()
        osp = self.plan(g3_1={"not_applicable": True, "na_attestation": {"by": self.user.pk, "at": AT}, "answers": {}})
        self.assertFalse([n for n in self.packet(osp).namelist() if n.startswith("suppliers/")])

    @override_settings(PACKET_ATTACHMENT_BUDGET_BYTES=1)
    def test_a_copy_held_outside_the_packet_says_so_and_keeps_the_row_open(self):
        supplier = self.supplier()
        self.certificate(supplier, date(2025, 1, 15))
        self.planting()
        packet = self.packet(self.plan())
        self.assertFalse([n for n in packet.namelist() if n.startswith("suppliers/")])
        self.assertIn(
            "Copy not in this packet (kept in Trazo's document store", _text(packet.read("modules/G3_0a.pdf"))
        )


class CoverageStateTests(_Plan):
    def test_a2_is_answered_only_when_every_supplier_has_a_covering_copy(self):
        supplier = self.supplier()
        self.planting()
        osp = self.plan()
        row = self.ccof_row(osp)
        self.assertEqual(row.state, "attachment_missing")
        self.assertIn("Columbia Nursery", row.detail)
        self.certificate(supplier, date(2025, 1, 15))
        self.assertEqual(self.ccof_row(osp).state, "answered")

    def test_a2_stays_open_with_no_transplant_purchase_on_record(self):
        row = self.ccof_row(self.plan())
        self.assertEqual(row.state, "attachment_missing")
        self.assertIn("no transplant purchase", row.detail)

    def test_a_plan_that_buys_no_seedlings_is_not_held_open_by_the_panel(self):
        self.assertEqual(self.ccof_row(self.plan(seedlings_used=("own_organic",))).state, "answered")

    def test_a_certified_purchase_on_record_holds_it_open_whatever_g3_0_says(self):
        """Review of back #265: the typed answer closed the row before the records were read."""
        self.supplier()
        self.planting()
        row = self.ccof_row(self.plan(seedlings_used=("own_organic",)))
        self.assertEqual(row.state, "attachment_missing")
        self.assertIn("Columbia Nursery", row.detail)

    def test_the_panel_flags_exactly_the_suppliers_the_coverage_page_holds_open(self):
        """Review of back #265: a purchase with no organic status stated, on a plan that buys certified
        organic seedlings, owes a copy on both, and on neither when the plan buys none."""
        self.supplier()
        self.planting(status="")
        buying = self.plan()
        self.assertEqual(self.ccof_row(buying).state, "attachment_missing")
        self.assertIn("[REVIEW] No copy of this supplier's organic certificate", self.g3_0a(buying))
        not_buying = self.plan(seedlings_used=("own_organic",))
        self.assertEqual(self.ccof_row(not_buying).state, "answered")
        text = self.g3_0a(not_buying)
        self.assertIn("No copy of this supplier's organic certificate", text)
        self.assertNotIn("[REVIEW]", text)

    def test_an_unanswered_seedling_question_leaves_it_unresolved(self):
        osp = self.plan()
        osp.module_responses["modules"]["g3_0_seeds"]["answers"] = {}
        osp.save(update_fields=["module_responses"])
        self.assertIn(self.ccof_row(osp).state, ("unanswered", "unresolved"))


class EndpointTests(_Plan):
    def endpoint(self, osp):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp.id}/seedling-suppliers/"

    def test_an_admin_reads_the_rows_the_plan_prints(self):
        supplier = self.supplier()
        self.certificate(supplier, date(2025, 1, 15))
        self.planting()
        r = self.client.get(self.endpoint(self.plan()))
        self.assertEqual(r.status_code, 200, r.content)
        (row,) = r.json()["suppliers"]
        self.assertEqual(row["name"], "Columbia Nursery")
        self.assertEqual(row["supplier_id"], supplier.pk)
        self.assertEqual(row["status"], "covering")
        self.assertEqual(row["certificate_issued_on"], "2025-01-15")
        self.assertEqual(row["latest"], "2025-04-02")
        self.assertTrue(row["needs_certificate"])

    def test_another_company_reads_nothing(self):
        osp = self.plan()
        self.supplier()
        self.planting()
        outsider = User.objects.create_user(email="outsider@suppliers.test", password="x")
        other = Company.objects.create(name="Elsewhere Farms")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(outsider)
        r = self.client.get(self.endpoint(osp))
        self.assertIn(r.status_code, (403, 404))
        self.assertNotIn(b"Columbia Nursery", r.content)

    def test_a_viewer_is_refused_like_the_register(self):
        osp = self.plan()
        viewer = User.objects.create_user(email="viewer@suppliers.test", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.endpoint(osp)).status_code, 403)
