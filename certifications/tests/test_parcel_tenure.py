"""Who holds the parcel, and whether the whole certified site is applied for (2026-11-06).

WSDA AGR 2264 (R 05/26) ref 7 "Do you own this site?", 7a the land owner's name, email, phone and
address, 7b "the details of the lease and who is responsible for day-to-day management"; OTCO C2
(2024/06/05) 2.1-6 "Do you: Own / Lease/Rent / Manage this parcel? Other". No parcel question asked
any of it, so a leased orchard's packet said nothing about whose land it was. WSDA ref 6b asks
whether the whole previously or currently certified site is applied for or only a portion.

Today's tenure is not `LandownerAffidavit`: that names whoever attests to a past period of land
use. The answers live in `Parcel.application_answers`, which no serializer exposes, so a landowner's
contact details reach the certifier's parcel page and nothing public.
"""

import io

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from product.models import Parcel

WSDA = "Washington State Department of Agriculture (WSDA)"

LEASED = {
    "currently_certified": "no",
    "site_tenure": "lease_rent",
    "landowner_name": "Ruth Okafor",
    "landowner_email": "ruth@okafor-orchards.example",
    "landowner_phone": "509-555-0142",
    "landowner_address": "88 Canal Rd, Wenatchee WA",
    "lease_management_detail": "Ten-year written lease from 2024; we run every field operation.",
}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Parcel(TestCase):
    certifier = WSDA

    def setUp(self):
        self.est = Establishment.objects.create(
            name="Canal Block Farm", company=Company.objects.create(name="Canal Block LLC"), state="WA"
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=self.certifier
        )
        self.parcel = Parcel.objects.create(
            name="Canal Block",
            establishment=self.est,
            area=12.0,
            date_began_managing=timezone.now().date().replace(year=2024),
            application_answers=dict(LEASED),
        )

    def answer(self, **answers):
        self.parcel.application_answers = {**self.parcel.application_answers, **answers}
        self.parcel.save(update_fields=["application_answers"])

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))

    def row(self, agent, document_id, ref):
        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)


class TenurePrintsOnTheParcelPage(_Parcel):
    def test_a_leased_parcel_names_its_owner_and_the_lease(self):
        page = self.page()
        self.assertIn("Do you own, lease or manage this parcel? Lease or rent", page)
        self.assertIn("Ruth Okafor", page)
        self.assertIn("ruth@okafor-orchards.example", page)
        self.assertIn("509-555-0142", page)
        self.assertIn("88 Canal Rd, Wenatchee WA", page)
        self.assertIn("Ten-year written lease from 2024; we run every field operation.", page)

    def test_an_owned_parcel_asks_for_no_landowner(self):
        # The landowner fields are WSDA's "If no": an owner is not asked who owns the land, and a
        # stale name typed before the answer changed must not print beside "Own".
        self.answer(site_tenure="own")
        page = self.page()
        self.assertIn("Do you own, lease or manage this parcel? Own", page)
        self.assertNotIn("Ruth Okafor", page)
        self.assertNotIn("Landowner's name", page)

    def test_the_whole_or_portion_question_follows_a_certified_parcel(self):
        self.assertNotIn("entire area of that certified site", self.page())
        self.answer(currently_certified="previously", full_prior_site_area="portion")
        self.assertIn(
            "Are you applying for the entire area of that certified site? No, only a portion of it", self.page()
        )


class TheRegisterReadsTheAnswers(_Parcel):
    def test_wsda_7_7a_7b_are_answered_by_a_leased_parcel(self):
        for ref in ("7", "7a", "7b"):
            self.assertEqual(self.row("wsda", "AGR 2264", ref).state, "answered", ref)

    def test_wsda_7_is_open_until_tenure_is_stated(self):
        # Open, never closed: "unresolved" because the "other" text hangs on the tenure nobody stated.
        self.answer(site_tenure=None)
        self.assertNotIn(self.row("wsda", "AGR 2264", "7").state, ("answered", "not_applicable"))

    def test_otco_2_1_6_is_answered(self):
        self.osp.certifier_name = "Oregon Tilth Certified Organic (OTCO)"
        self.osp.save(update_fields=["certifier_name"])
        self.assertEqual(self.row("otco", "C2", "2.1-6").state, "answered")
