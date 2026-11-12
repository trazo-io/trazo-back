"""The operation's own signed affidavit for its own period (2026-11-11).

OTCO C2 (2024/06/05) 2.5: "Every distinct party that has had management of the parcel during the past 36 months
is required to sign", with a signature line for the "Current Landowner/Manager(s) Requesting Certification".
CCOF ORGB49 (R11 3/14/2022) §G: the Affidavit of Land History "signed and dated by each person identified in
question F6". Only previous managers could sign one: the operation's row printed a dash, and its own period
counted only through an unsigned yes/no answer.

The operation's affidavit is the agent's form, signed and uploaded. It is never a previous party's.
"""

import io
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import LandownerAffidavit, OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.parcel_land_history import (
    coverage,
    current_manager_row,
    prior_manager_rows,
    tenure_declaration,
)
from company.models import Company, Establishment
from product.models import Parcel


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Parcel(TestCase):
    def setUp(self):
        self.est = Establishment.objects.create(
            name="Marys River Farm", company=Company.objects.create(name="Marys River LLC"), state="OR"
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name="Oregon Tilth Certified Organic (OTCO)",
        )
        self.parcel = Parcel.objects.create(
            name="North Bottom",
            establishment=self.est,
            area=5.0,
            date_began_managing=date.today() - timedelta(days=500),
            application_answers={"currently_certified": "no"},
        )

    def affidavit(self, signed=True, **kw):
        a = LandownerAffidavit.objects.create(parcel=self.parcel, **{"previous_manager_name": "Ann Vos", **kw})
        if signed:
            a.signed_document.save("signed.pdf", ContentFile(b"%PDF-1.4 signed"), save=True)
        return a

    def own(self, signed=True, **kw):
        fields = {
            "signer_role": "this_operation",
            "previous_manager_name": "Marys River Farm",
            "previous_manager_signed_date": date.today(),
            **kw,
        }
        return self.affidavit(signed=signed, **fields)

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))


class TheOperationsAffidavitIsItsOwn(_Parcel):
    def test_it_is_not_a_prior_party(self):
        self.own()
        self.affidavit(previous_manager_name="Ann Vos")
        self.assertEqual([r.name for r in prior_manager_rows(self.parcel)], ["Ann Vos"])

    def test_it_fills_the_current_managers_row(self):
        mine = self.own()
        row = current_manager_row(self.parcel, self.parcel.application_answers)
        self.assertEqual(row.signed, date.today())
        self.assertTrue(row.attachment.startswith(f"parcels/affidavits/{mine.pk}-"))
        self.assertEqual(row.affidavit, mine)

    def test_a_signed_copy_is_a_statement_for_the_operations_period_and_an_unsigned_row_is_not(self):
        began = self.parcel.date_began_managing
        self.own(signed=False, management_period_start=began)
        self.assertEqual(tenure_declaration(self.parcel), "")
        self.own(signed=True, management_period_start=began)
        self.assertEqual(tenure_declaration(self.parcel), "its own signed affidavit (attached)")
        account = coverage(self.parcel, prior_manager_rows(self.parcel))
        self.assertIn("the operation from", account.text)
        self.assertIn("its own signed affidavit (attached)", account.text)

    def test_an_explicit_declaration_still_comes_first(self):
        self.own()
        self.parcel.application_answers = {"currently_certified": "no", "no_inputs_within_tenure": True}
        self.parcel.save(update_fields=["application_answers"])
        self.assertEqual(tenure_declaration(self.parcel), "no input materials of any kind (declared)")


class TheParcelPageSaysIt(_Parcel):
    def test_a_missing_one_is_stated(self):
        self.assertIn("Marys River Farm has no signed affidavit of its own for its period on file.", self.page())

    def test_a_signed_one_prints_on_the_operations_row(self):
        self.own(signer_basis="managed")
        page = self.page()
        self.assertNotIn("has no signed affidavit of its own", page)
        self.assertIn(date.today().isoformat(), page)
        self.assertIn("Stated by Marys River Farm:", page)
        self.assertIn("signed affidavit attached at parcels/affidavits/", page)

    def test_an_unsigned_one_reads_unsigned_not_a_dash(self):
        self.own(signed=False, previous_manager_signed_date=None)
        page = self.page()
        self.assertIn("unsigned", page)
        self.assertIn("not attached", page)


class EveryPriorPartySignedIgnoresTheOperation(_Parcel):
    def test_the_operations_own_affidavit_is_not_a_prior_partys_signature(self):
        from certifications.services.certified_parcel_branch import MISSING, _prior_manager_item

        self.own()
        item = _prior_manager_item(self.parcel, "Previous manager's affirmation")
        self.assertEqual(item.state, MISSING)
        self.assertIn("none on file", item.text)


class TheSignedCopyUploads(_Parcel):
    """The app had no way to attach the signed copy; it uploads as a multipart PATCH on the row."""

    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient

        from users.models import User, WorksIn

        user = User.objects.create_user(email="signer@test.com", password="x")
        WorksIn.objects.create(user=user, company=self.est.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(user)

    def url(self, aff):
        return f"/api/companies/{self.est.company_id}/establishments/{self.est.id}/affidavits/{aff.pk}/"

    def test_a_pdf_attaches_and_reaches_the_operations_row(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        aff = self.own(signed=False)
        r = self.client.patch(
            self.url(aff),
            {"signed_document": SimpleUploadedFile("c2-signed.pdf", b"%PDF-1.4 signed", "application/pdf")},
            format="multipart",
        )
        self.assertEqual(r.status_code, 200, r.content)
        aff.refresh_from_db()
        self.assertTrue(aff.signed_document)
        self.assertTrue(current_manager_row(self.parcel, {}).attachment)

    def test_a_file_that_is_not_a_signed_copy_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        aff = self.own(signed=False)
        for name in ("macro.xlsx", "tool.exe"):
            r = self.client.patch(
                self.url(aff),
                {"signed_document": SimpleUploadedFile(name, b"x", "application/octet-stream")},
                format="multipart",
            )
            self.assertEqual(r.status_code, 400, name)
        aff.refresh_from_db()
        self.assertFalse(aff.signed_document)


class ReviewFindingsOn396(_Parcel):
    def test_a_signed_copy_stating_part_of_the_period_does_not_cover_it(self):
        # Six months stated, signed and attached: the operation's own period is still not accounted for.
        began = self.parcel.date_began_managing
        self.own(management_period_start=began, management_period_end=began + timedelta(days=180))
        self.assertEqual(tenure_declaration(self.parcel), "")
        self.assertIn("is not covered", coverage(self.parcel, prior_manager_rows(self.parcel)).text)

    def test_a_signed_copy_with_no_period_does_not_cover_it(self):
        self.own()
        self.assertEqual(tenure_declaration(self.parcel), "")

    def test_a_signed_copy_from_tenure_start_to_present_covers_it(self):
        self.own(management_period_start=self.parcel.date_began_managing)
        self.assertEqual(tenure_declaration(self.parcel), "its own signed affidavit (attached)")
