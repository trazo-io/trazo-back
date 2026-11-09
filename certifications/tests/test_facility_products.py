"""A facility's product rows: CCOF G6.1 C2 and OTCO C7 7.10-2 (2026-11-08).

CCOF asks, per finished product: category, detail, packaging form, the certified operation where it is
handled or processed, and the manufacturer's ingredient statement of each multi-ingredient product. OTCO
asks: type, detail, organic label claim, label or brand name, the operation doing the processing and its
certifier. Until this slice a facility held one free-text line for all of that.
"""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import FacilityProduct, OrganicSystemPlan, PostHarvestFacility
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn

AT = "2026-11-08T10:00:00+00:00"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Processed Elsewhere")
        self.user = User.objects.create_user(email="products@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        grant_compliance_exports(self.company)
        self.est = Establishment.objects.create(name="Home Orchard", company=self.company, state="CA")
        self.other_est = Establishment.objects.create(name="North Orchard", company=self.company, state="CA")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.facility = PostHarvestFacility.objects.create(
            establishment=self.est,
            name="ABC Hulling & Shelling",
            facility_type="huller",
            certification_number="CCOF-123",
            certifier_name="CCOF Certification Services, LLC",
        )

    def url(self, suffix="", est=None):
        est = est or self.est
        return f"/api/companies/{self.company.id}/establishments/{est.id}/facility-products/{suffix}"

    def upload(self, est=None, title="Ingredient statement"):
        est = est or self.est
        r = self.client.post(
            f"/api/companies/{self.company.id}/establishments/{est.id}/documents/",
            {
                "file": SimpleUploadedFile("statement.pdf", b"%PDF-1.4 ingredients", content_type="application/pdf"),
                "title": title,
                "folder": "certifications",
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        return GeneratedDocument.objects.get(pk=r.json()["id"])

    def product(self, facility=None, **fields):
        data = {"facility": (facility or self.facility).id, "category": "Almonds", **fields}
        r = self.client.post(self.url(), data, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return FacilityProduct.objects.get(pk=r.json()["id"])

    def plan(self, gate="yes_certified"):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name="CCOF Certification Services, LLC",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    "g6_1_harvest_transport": {"answers": {"handled_by_another_operation": {"at": AT, "value": gate}}}
                },
            },
        )

    def g6_1(self, osp) -> str:
        return _text(generate_module_pdf(osp, "g6_1_harvest_transport"))


class WritePathTests(_Farm):
    def test_a_row_in_ccofs_and_otcos_columns_round_trips(self):
        self.product(
            detail="Shelled",
            packaging_form="retail",
            label_claim="organic",
            brand_name="Valley Gold",
            multi_ingredient="no",
        )
        row = self.client.get(f"/api/companies/{self.company.id}/establishments/{self.est.id}/post-harvest-facilities/")
        products = row.json()[0]["products"] if isinstance(row.json(), list) else row.json()["results"][0]["products"]
        self.assertEqual(
            {k: products[0][k] for k in ("category", "detail", "packaging_form", "label_claim", "brand_name")},
            {
                "category": "Almonds",
                "detail": "Shelled",
                "packaging_form": "retail",
                "label_claim": "organic",
                "brand_name": "Valley Gold",
            },
        )

    def test_a_blank_category_is_refused(self):
        r = self.client.post(self.url(), {"facility": self.facility.id, "category": "   "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("category", r.json())

    def test_an_ingredient_statement_is_refused_on_a_single_ingredient_product(self):
        doc = self.upload()
        r = self.client.post(
            self.url(),
            {
                "facility": self.facility.id,
                "category": "Almonds",
                "multi_ingredient": "no",
                "ingredient_statement_document": doc.id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("ingredient_statement_document", r.json())

    def test_switching_away_from_multi_ingredient_unlinks_the_statement(self):
        doc = self.upload()
        product = self.product(multi_ingredient="yes", ingredient_statement_document=doc.id)
        r = self.client.patch(self.url(f"{product.id}/"), {"multi_ingredient": "no"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        product.refresh_from_db()
        self.assertIsNone(product.ingredient_statement_document_id)
        self.assertTrue(GeneratedDocument.objects.filter(pk=doc.pk).exists())

    def test_a_statement_a_product_names_cannot_be_deleted_from_documents(self):
        doc = self.upload()
        self.product(multi_ingredient="yes", ingredient_statement_document=doc.id)
        r = self.client.delete(f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/{doc.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "ingredient_statement_in_use")

    def test_the_list_narrows_to_one_facility(self):
        cooler = PostHarvestFacility.objects.create(establishment=self.est, name="Cooler", facility_type="cold_storage")
        self.product()
        self.product(facility=cooler, category="Walnuts")
        r = self.client.get(self.url(), {"facility": cooler.id})
        rows = r.json() if isinstance(r.json(), list) else r.json()["results"]
        self.assertEqual([x["category"] for x in rows], ["Walnuts"])


class FacilityProductTenancyTests(_Farm):
    def test_another_company_reaches_nothing(self):
        product = self.product()
        outsider = User.objects.create_user(email="other@products.test", password="x")
        other = Company.objects.create(name="Elsewhere")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(outsider)
        self.assertIn(self.client.get(self.url()).status_code, (403, 404))
        self.assertIn(self.client.get(self.url(f"{product.id}/")).status_code, (403, 404))
        r = self.client.patch(self.url(f"{product.id}/"), {"category": "Mine now"}, format="json")
        self.assertIn(r.status_code, (403, 404))
        product.refresh_from_db()
        self.assertEqual(product.category, "Almonds")

    def test_another_farms_facility_or_document_fails_like_a_missing_one(self):
        theirs = PostHarvestFacility.objects.create(establishment=self.other_est, name="Theirs", facility_type="dryer")
        foreign = self.client.post(self.url(), {"facility": theirs.id, "category": "X"}, format="json")
        missing = self.client.post(self.url(), {"facility": 999999, "category": "X"}, format="json")
        self.assertEqual(foreign.status_code, 400)
        self.assertEqual(
            str(foreign.json()).replace(str(theirs.id), "<id>"), str(missing.json()).replace("999999", "<id>")
        )
        doc = self.upload(est=self.other_est)
        foreign = self.client.post(
            self.url(),
            {
                "facility": self.facility.id,
                "category": "X",
                "multi_ingredient": "yes",
                "ingredient_statement_document": doc.id,
            },
            format="json",
        )
        missing = self.client.post(
            self.url(),
            {
                "facility": self.facility.id,
                "category": "X",
                "multi_ingredient": "yes",
                "ingredient_statement_document": 999999,
            },
            format="json",
        )
        self.assertEqual(foreign.status_code, 400)
        self.assertEqual(
            str(foreign.json()).replace(str(doc.id), "<id>"), str(missing.json()).replace("999999", "<id>")
        )
        self.assertFalse(FacilityProduct.objects.exists())


class OnThePageTests(_Farm):
    def test_each_column_prints_under_its_handler(self):
        self.product(
            detail="Shelled",
            packaging_form="nonretail",
            label_claim="100_percent_organic",
            brand_name="Valley Gold",
            multi_ingredient="no",
        )
        page = self.g6_1(self.plan())
        for words in (
            "Packaging form",
            "Organic label claim",
            "Label or brand",
            "Almonds Shelled",
            "Nonretail",
            "100% Organic",
            "Valley Gold",
            "Single ingredient",
        ):
            self.assertIn(words, page)

    def test_an_empty_column_prints_not_stated_never_a_default(self):
        self.product()
        page = self.g6_1(self.plan())
        table = page[page.index("Product Almonds") : page.index("How do you make sure")]
        self.assertEqual(table.count("Not stated"), 4, table)

    def test_a_multi_ingredient_product_with_no_statement_prints_a_review(self):
        self.product(category="Almond butter", multi_ingredient="yes")
        self.assertIn(
            "[REVIEW] Multi-ingredient product with no manufacturer's ingredient statement on file in Trazo.",
            self.g6_1(self.plan()),
        )

    def test_the_statement_ships_under_handlers_and_the_row_names_its_path(self):
        doc = self.upload()
        product = self.product(category="Almond butter", multi_ingredient="yes", ingredient_statement_document=doc.id)
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.plan())))
        path = f"handlers/{self.facility.pk}-ABC Hulling & Shelling-ingredients-Almond butter-{product.pk}.pdf"
        self.assertIn(path, packet.namelist())
        self.assertEqual(packet.read(path), b"%PDF-1.4 ingredients")
        self.assertIn(path, _text(packet.read("modules/G6_1.pdf")))

    def test_nothing_ships_when_the_plan_does_not_print_the_handler_table(self):
        doc = self.upload()
        self.product(category="Almond butter", multi_ingredient="yes", ingredient_statement_document=doc.id)
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.plan(gate="no"))))
        self.assertFalse([n for n in packet.namelist() if "-ingredients-" in n])

    def test_a_product_row_alone_answers_which_products_the_handler_takes(self):
        self.product()
        self.assertNotIn("no products are described", self.g6_1(self.plan()))


class RegisterRowsTests(TestCase):
    def test_the_rows_are_covered(self):
        for agent, code, ref in (("ccof", "G6.1", "C2"), ("otco", "C7", "7.10-2"), ("ccof", "G8.0", "D2")):
            form = next(f for f in load_forms(agent) if code in (f.code, f.document_id))
            row = next(i for i in form.items if i.ref == ref)
            self.assertEqual(row.status, "covered", (agent, ref))
