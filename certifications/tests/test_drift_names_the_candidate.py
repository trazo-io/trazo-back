"""A drift finding names the listing it found and says what is not confirmed.

Recordkeeping review, 2026-10-07 (F-01). On the Calapooia specimen every one of the 81 chemical
events carried an unresolved finding because the records log the jug name ("Serenade Opti") and
the plan lists the OMRI name ("Bayer Serenade Opti A Wettable Powder Biofungicide"). The detector
had already found that candidate and stored it in `reason_params.possibleMatches`; the prose
called it "not matched to any approved OSP input. Possible match, not confirmed", the farm card
called it "not matched to the plan's approved inputs", the packet "[REVIEW] N product name(s)
… do not match", and the certifier page "a plan change to notify". None of them said the one
thing the grower can act on: confirm the name's identity on the plan.

Each test here went red on the code before the fix, on an assertion.
"""

import io
import zipfile

from django.utils import timezone

import pdfplumber
from rest_framework.test import APITestCase

from certifications.models import OMRIProduct, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel, Product
from users.models import User, WorksIn


def _text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return " ".join((page.extract_text() or "") for page in pdf.pages).replace("\n", " ")


class DriftNamesTheCandidateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="drift-candidate@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Candidate Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Candidate Farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Home Field", establishment=self.est, area=5.0)
        self.product = Product.objects.create(name="Blueberries")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=3, status="active", created_by=self.user
        )
        self.omri = OMRIProduct.objects.create(
            omri_id="OMRI-SER-1", product_name="Bayer Serenade Opti A Wettable Powder Biofungicide"
        )
        self.osp.approved_omri_products.add(self.omri)
        self.history = Production.objects.create(
            name="Duke 2026",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=False,
        )

    def _spray(self, name="Serenade Opti"):
        with self.captureOnCommitCallbacks(execute=True):
            event = ChemicalEvent.objects.create(
                history=self.history,
                date=timezone.now(),
                description="bloom spray",
                commercial_name=name,
                organic_approved="omri_listed",
                created_by=self.user,
            )
        event.refresh_from_db()
        return event

    # -- the reason names the candidate and what is not confirmed --------------

    def test_the_reason_names_the_closest_listing_and_calls_it_unconfirmed(self):
        event = self._spray()
        self.assertEqual(event.drift_warning["reason_code"], "unresolved")
        reason = event.drift_warning["reason"]
        self.assertIn("'Serenade Opti' is not confirmed against the plan's inputs list.", reason)
        self.assertIn(
            "Closest listing, not confirmed as the same product: "
            "Bayer Serenade Opti A Wettable Powder Biofungicide (OMRI).",
            reason,
        )
        self.assertNotIn("not matched to any approved", reason)
        self.assertNotIn("Possible match", reason)
        self.assertEqual(
            event.drift_warning["reason_params"]["possibleMatches"],
            ["Bayer Serenade Opti A Wettable Powder Biofungicide"],
        )

    def test_a_name_with_no_candidate_says_so_without_inventing_one(self):
        event = self._spray(name="Producto Desconocido 77")
        reason = event.drift_warning["reason"]
        self.assertIn("'Producto Desconocido 77' is not confirmed against the plan's inputs list.", reason)
        self.assertNotIn("Closest listing", reason)
        self.assertEqual(event.drift_warning["reason_params"]["possibleMatches"], [])

    # -- the readiness row: key, wording, and the count as data -----------------

    def test_the_readiness_row_says_not_confirmed_and_carries_its_count(self):
        from history.services.audit_export_service import AuditExportService

        self._spray()
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        row = next(r for r in rows if "§ 205.400(f)(2)" in r["label"])
        self.assertEqual(row["label"], "Inputs not confirmed against the plan's inputs list (§ 205.400(f)(2))")
        self.assertEqual(row["row_key"], "inputs_not_confirmed_against_the_plan_s_inputs_list")
        self.assertEqual(row["status"], "REVIEW")
        self.assertIn("1 input record(s) not confirmed against the plan's inputs list", row["detail"])
        self.assertEqual(row["params"], {"count": 1})
        self.assertNotIn("approved", (row["label"] + row["detail"]).lower())

    def test_the_farm_card_endpoint_serves_the_count(self):
        self._spray()
        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/certifier-readiness/"
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        findings = response.json()["findings"]
        finding = next((f for f in findings if (f.get("row_key") or "").startswith("inputs_not_confirmed")), None)
        self.assertIsNotNone(finding, [f.get("row_key") for f in findings])
        self.assertEqual(finding.get("params"), {"count": 1})

    # -- the documents ---------------------------------------------------------

    def test_the_packet_materials_note_points_at_the_identity_panel(self):
        from certifications.services.osp_module_pdf import generate_osp_packet

        self._spray()
        with zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))) as zf:
            module = _text(zf.read("modules/materials_application.pdf"))
        self.assertIn("1 logged product name(s) are not confirmed against an entry above: Serenade Opti", module)
        self.assertIn("Logged names not on the plan", module)
        self.assertNotIn("do not match an entry above", module)

    def test_the_dossier_section_explains_identity_before_change_notification(self):
        from history.services.audit_export_service import AuditExportService

        self._spray()
        service = AuditExportService(self.history, certification_type="organic")
        text = " ".join(str(getattr(el, "text", "")) for el in service._build_drift_findings_section())
        self.assertIn("Inputs Not Confirmed Against the Plan's Inputs List (7 CFR 205.400(f)(2))", text)
        self.assertIn("Logged names not on the plan", text)
        self.assertNotIn("OSP Practice Change", text)
        self.assertNotIn("the producer must notify the certifier of any change", text)

    def test_the_whole_operation_fix_line_names_the_identity_panel(self):
        from history.services.operation_readiness_service import OperationReadinessService

        self._spray()
        result = OperationReadinessService(self.est, "organic").evaluate()
        item = next(i for i in result["warnings"] if i["key"] == "unmatched_materials")
        self.assertEqual(item["code"], "unmatched_materials.unlisted")
        self.assertIn("Logged names not on the plan", item["fix"])
