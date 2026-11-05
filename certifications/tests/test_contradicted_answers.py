"""
A Yes stored before the write-time gates existed, printed as it stands.

The write path refuses a Yes the records contradict (`attestation_gates`): the Materials Application
"listed" statements while the records name products the list does not hold (back #284), and the
G8.0 records statement over a list nobody confirmed. A plan answered before those gates keeps its
Yes, and the module page printed it bare beside the note that disproves it: the CCOF, WSDA and OTCO
reviewer reads (2026-11-04) all found "Yes" to "every input material I use is entered in this list"
on the page that named products it does not hold.

Pinned here:
  * a refused Yes prints as the operator's answer that no longer stands, never bare;
  * the whole-list statement, which has no category line of its own, names the products;
  * a Yes the records support prints plain;
  * the G8.0 records statement over an empty list is qualified the same way.
"""

import io

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel
from users.models import User

QUALIFIED = "Yes, as answered before the records showed otherwise; it is not supported by the plan as it stands."


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="stands@test.com", password="x")
        self.company = Company.objects.create(name="Stands Orchards LLC")
        self.est = Establishment.objects.create(name="Stands Orchard", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.history = History.objects.create(name="Pears 2026", start_date=timezone.now(), parcel=parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")

    def _store(self, module, **answers):
        """As a plan answered before the gate: the stored value, written past the API."""
        responses = self.osp.module_responses or {"schema_version": 1, "modules": {}}
        responses.setdefault("modules", {})[module] = {"answers": {k: {"value": v} for k, v in answers.items()}}
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _apply(self, name, type_code="PE"):
        with self.captureOnCommitCallbacks(execute=True):
            ChemicalEvent.objects.create(
                history=self.history, date=timezone.now(), description="spray", type=type_code, commercial_name=name
            )


class MaterialsStatementsTests(_Farm):
    def setUp(self):
        super().setUp()
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="Entrust SC", category="pest_disease_weed")
        self._apply("Entrust SC")
        self._apply("Kocide 3000", type_code="FU")
        self._store("materials_application", materials_list_complete=True, pest_disease_weed_listed=True)

    def test_a_refused_yes_says_it_no_longer_stands_and_the_whole_list_one_names_the_products(self):
        page = _pdf_text(generate_module_pdf(self.osp, "materials_application"))
        self.assertEqual(page.count(QUALIFIED), 2, page[:3000])
        self.assertIn(
            "The records name 1 product(s) that this plan's materials list does not hold by name, and that no "
            "current decision on the plan ties to a listed product: Kocide 3000.",
            page,
        )

    def test_a_yes_the_records_support_prints_plain(self):
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="Kocide 3000", category="pest_disease_weed")
        page = _pdf_text(generate_module_pdf(self.osp, "materials_application"))
        self.assertNotIn("as answered before the records showed otherwise", page)
        self.assertNotIn("The records name 1 product(s)", page)


class RecordsStatementTests(_Farm):
    def test_the_records_statement_over_an_empty_list_is_qualified(self):
        self._store("g8_0_record_keeping", records_retention_attestation=True)
        page = _pdf_text(generate_module_pdf(self.osp, "g8_0_record_keeping"))
        self.assertIn(QUALIFIED, page)
