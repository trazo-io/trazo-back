"""The parcel's borders, as the three agents ask them (2026-11-06).

CCOF ORGB49 D1 asks per border whether the adjoining land is organic (Y/N) and whether a crop is
grown in the buffer (Y/N); OTCO C2 2.2 asks the same crop column; WSDA AGR 2264 ref 14 asks the
"distance from prohibited material applications". A "no" to the first printed nothing, the second
could only be said by naming a crop, and the third had no field. CCOF F8/F8a ask whether, since the
DLPM, prohibited materials went onto the parcel's borders or onto ground on the same APN or CA PUR
site ID that is not submitted, which nothing captured. The wizard rendered the headings of §D's
change notifications and contamination incidents over nothing.
"""

import io
import re

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, OSPChangeNotification
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from history.models import GeneralEvent, Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel
from product.services.buffer_zones import BufferZoneError, normalize_buffer_row
from users.models import User, WorksIn

CCOF = "California Certified Organic Farmers (CCOF)"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class BufferRowNormalizes(TestCase):
    def test_no_crop_is_an_answer_of_its_own(self):
        row = normalize_buffer_row({"direction": "North", "buffer_crop_grown": False})
        self.assertIs(row["buffer_crop_grown"], False)

    def test_unanswered_stays_unanswered(self):
        row = normalize_buffer_row({"direction": "North", "adjoining_land_use": "Conventional apples"})
        self.assertIsNone(row["buffer_crop_grown"])
        self.assertIsNone(row["prohibited_use_distance_ft"])

    def test_a_named_crop_with_a_no_is_refused(self):
        with self.assertRaises(BufferZoneError):
            normalize_buffer_row({"direction": "North", "buffer_crop_grown": False, "crop_grown_in_buffer": "Alfalfa"})

    def test_distance_is_a_non_negative_number(self):
        self.assertEqual(
            normalize_buffer_row({"direction": "East", "prohibited_use_distance_ft": "60"})[
                "prohibited_use_distance_ft"
            ],
            60.0,
        )
        for bad in ("-5", "far"):
            with self.assertRaises(BufferZoneError):
                normalize_buffer_row({"direction": "East", "prohibited_use_distance_ft": bad})


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Border Farms LLC")
        self.est = Establishment.objects.create(name="Border Farm", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=CCOF
        )
        self.parcel = Parcel.objects.create(
            name="North Block",
            establishment=self.est,
            area=8.0,
            application_answers={"currently_certified": "no"},
            buffer_zones=[
                normalize_buffer_row(
                    {
                        "direction": "North",
                        "adjoining_land_use": "Conventional apples",
                        "adjacent_is_organic": False,
                        "buffer_type": "farm road",
                        "buffer_width_ft": 30,
                        "buffer_crop_grown": False,
                        "prohibited_use_distance_ft": 60,
                    }
                ),
                normalize_buffer_row({"direction": "South", "adjoining_land_use": "Native oak woodland"}),
            ],
        )

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))

    def answer(self, **answers):
        self.parcel.application_answers = {**self.parcel.application_answers, **answers}
        self.parcel.save(update_fields=["application_answers"])


class SectionDSaysTheNoAnswers(_Farm):
    def test_a_no_prints_and_an_unanswered_border_does_not(self):
        page = self.page()
        self.assertIn("adjoining land is not certified organic", page)
        self.assertIn("no crop grown in the buffer", page)
        self.assertIn("60 ft from prohibited-material applications", page)
        # The south border answered neither question: it states neither answer.
        self.assertEqual(page.count("adjoining land is not certified organic"), 1)
        self.assertEqual(page.count("no crop grown in the buffer"), 1)

    def test_the_audit_export_says_the_same(self):
        history = Production.objects.create(name="2026", start_date=timezone.now(), parcel=self.parcel)
        els = AuditExportService(history, certification_type="organic")._build_buffer_zone_section()
        text = " ".join(getattr(e, "text", "") for e in els if hasattr(e, "text"))
        self.assertIn("adjoining land is not certified organic", text)
        self.assertIn("no crop grown in the buffer", text)
        self.assertIn("60 ft from prohibited-material applications", text)

    def test_a_yes_without_a_crop_name_reaches_both_documents(self):
        # Review of back #322: the parcel page printed it and the audit export dropped the border.
        self.parcel.buffer_zones = [normalize_buffer_row({"direction": "West", "buffer_crop_grown": True})]
        self.parcel.save(update_fields=["buffer_zones"])
        self.assertIn("a crop is grown in the buffer (crop not named)", self.page())
        history = Production.objects.create(name="2026", start_date=timezone.now(), parcel=self.parcel)
        els = AuditExportService(history, certification_type="organic")._build_buffer_zone_section()
        text = " ".join(getattr(e, "text", "") for e in els if hasattr(e, "text"))
        self.assertIn("a crop is grown in the buffer (crop not named)", text)


class ExcludedGroundF8(_Farm):
    def test_asked_of_a_parcel_not_currently_certified_and_printed(self):
        self.answer(
            prohibited_on_excluded_ground=True,
            prohibited_on_excluded_ground_detail="Glyphosate on the conventional east rows, 2025-04-12.",
        )
        page = self.page()
        self.assertIn("have prohibited materials been applied to its borders", page)
        self.assertIn("Glyphosate on the conventional east rows, 2025-04-12.", page)

    def test_not_asked_of_a_currently_certified_parcel(self):
        # CCOF F2: "Yes. Skip to section G."
        self.answer(currently_certified="yes", prohibited_on_excluded_ground=True)
        self.assertNotIn("have prohibited materials been applied to its borders", self.page())

    def test_the_ccof_rows_read_the_answer(self):
        form = next(f for f in load_forms("ccof") if f.document_id == "ORGB49")
        rows = {r.ref: r for r in form_answer_states(self.osp, [form])[id(form)]}
        self.assertNotIn(rows["F8"].state, ("answered", "not_applicable"))
        self.answer(prohibited_on_excluded_ground=False)
        rows = {r.ref: r for r in form_answer_states(self.osp, [form])[id(form)]}
        self.assertEqual(rows["F8"].state, "answered")


class WizardShowsWhatSectionDPrints(_Farm):
    def test_the_payload_carries_both_lists_as_codes(self):
        user = User.objects.create_user(email="borders@test.com", password="x")
        WorksIn.objects.create(user=user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        history = Production.objects.create(name="2026", start_date=timezone.now(), parcel=self.parcel)
        OSPChangeNotification.objects.create(
            osp=self.osp,
            parcel=self.parcel,
            change_category=OSPChangeNotification.CATEGORY_PROHIBITED_SUBSTANCE,
            description="Neighbour's herbicide drifted onto the north rows.",
            date_notified=timezone.now().date(),
        )
        GeneralEvent.objects.create(
            history=history,
            date=timezone.now(),
            is_contamination_incident=True,
            contamination_source="spray_drift",
            description="Drift on rows 1-4.",
            certifier_notified=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        data = client.get(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/parcels/{self.parcel.id}/application/"
        ).json()
        self.assertEqual(
            [n["category"] for n in data.get("change_notifications", [])], ["prohibited_substance_application"]
        )
        self.assertEqual([i["source"] for i in data.get("contamination_incidents", [])], ["spray_drift"])
        self.assertIs(data["contamination_incidents"][0]["certifier_notified"], True)
        # Plain dates, never timestamps (review of app #292): the wizard formats them with
        # formatDateOnly, which is timezone-safe only for YYYY-MM-DD.
        day = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        notice = data["change_notifications"][0]
        self.assertRegex(notice["date_notified"], day)
        self.assertRegex(notice["recorded"], day)
        self.assertRegex(data["contamination_incidents"][0]["date"], day)
