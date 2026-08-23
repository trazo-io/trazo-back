"""The renewal packet must carry the documents a renewal IS, and must tell the truth about
what the records did after the plan was written.

WHY THIS EXISTS
---------------
Read as a certifier, a pilot's generated 2028 renewal had these holes:

  * the ZIP named "renewal packet" did not contain the § 205.406(a) annual update — the one
    document the rule requires each year — nor the § 205.400(f) notices that support it;
  * the cover was four lines: operation, version, today's date, a contents list. No
    certificate number, no certifier, no reporting year, no § 205.401(b) responsible person;
  * every narrative had been cloned verbatim from a version written eighteen months earlier
    and still said "six parcels" / "86.9 acres" with seven and 96.7 on file, and nothing in the
    product pointed that out before the packet left;
  * the Parcel Application for a block that took drift on 11 May 2027 said nothing about it,
    and its "F. Land history" stopped two years short of the seasons actually logged.

Each test below renders the real artifact and reads the text back — the failure mode was a
document that looked complete.
"""

import io
import zipfile
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text

from carbon.models import CropType
from certifications.models import (
    AdjoiningLandAffidavit,
    Certification,
    OrganicSystemPlan,
    OSPAnnualUpdate,
    OSPChangeNotification,
)
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from certifications.services.plan_review import plan_review
from company.models import Company, Establishment
from history.models import GeneralEvent, History
from product.models import Parcel, ParcelCropHistory, Product
from users.models import User


def _pdf_text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="renew@test.com", password="x", first_name="Laurel", last_name="Brandt"
        )
        self.company = Company.objects.create(name="Brandt Family Farms LLC")
        self.est = Establishment.objects.create(
            name="Calapooia Test Farm",
            company=self.company,
            state="OR",
            city="Tangent",
            address="31480 Calapooia Rd",
            zip_code="97389",
            contact_person="Laurel Brandt",
        )
        self.parcel = Parcel.objects.create(name="Home Field West", establishment=self.est, area=5.67)
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="COC-1463",
            certifier_name="Cascadia Organic Certifiers",
            effective_date=date(2006, 5, 15),
        )
        # Plan answered in August 2026 ...
        answered = "2026-08-21T11:00:00+00:00"
        self.v1 = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            created_by=self.user,
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    "g4_0_rotation_soil": {
                        "status": "completed",
                        "answers": {"rotation_plan": {"at": answered, "value": "Home Field West in blueberries."}},
                    },
                },
            },
        )
        # ... cloned into v2 and submitted eighteen months later.
        self.v2 = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=2,
            status="submitted",
            created_by=self.user,
            previous_version=self.v1,
            module_responses=self.v1.module_responses,
            submitted_at=datetime(2028, 2, 7, 9, tzinfo=dt_tz.utc),
        )


class PacketCarriesTheFilingTests(_Farm):
    def test_packet_has_annual_update_and_change_notifications_documents(self):
        OSPAnnualUpdate.objects.create(
            prior_osp=self.v1,
            new_osp=self.v2,
            reporting_year=2028,
            submitted_at=datetime(2028, 2, 9, 9, tzinfo=dt_tz.utc),
            changes_summary="Nine point eight acres leased at Muddy Creek; buffer widened to 45 ft.",
            additions=["Muddy Creek Lease — 9.80 ac"],
            deletions=["None."],
        )
        OSPChangeNotification.objects.create(
            osp=self.v1,
            change_category="acreage_field_addition",
            description="Added 9.80 acres.",
            date_notified=date(2027, 1, 22),
            method="written",
            documentation_timing="submitted_at_notification",
        )
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v2)))
        names = zf.namelist()
        self.assertIn("02-annual-update.pdf", names)
        self.assertIn("03-change-notifications.pdf", names)
        filing = _pdf_text(zf.read("02-annual-update.pdf"))
        self.assertIn("reporting year 2028", filing)
        self.assertIn("Muddy Creek", filing)
        self.assertIn("buffer widened to 45 ft", filing)
        self.assertIn("v1 to v2", filing)
        notices = _pdf_text(zf.read("03-change-notifications.pdf"))
        self.assertIn("2027-01-22", notices)
        self.assertIn("Added 9.80 acres", notices)
        # Each addition is ONE bullet. The first cut of this document joined the list into one
        # string and then iterated it, so a packet the operator downloaded printed
        # "• G • r • a • n • d • e • v • o" — one character per bullet, down the page.
        self.assertIn("• Muddy Creek Lease — 9.80 ac", filing.replace("(cid:127)", "•"))
        self.assertNotRegex(filing, r"\(cid:127\) \S \(cid:127\) \S \(cid:127\) \S")

    def test_packet_says_so_when_no_filing_exists(self):
        """A renewal with no § 205.406 filing must say so, not print an empty page."""
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v2)))
        filing = _pdf_text(zf.read("02-annual-update.pdf"))
        self.assertIn("No § 205.406(a) annual update is on file", filing)
        cover = _pdf_text(zf.read("00-cover.pdf"))
        self.assertIn("No annual update is on file for this plan version", cover)

    def test_cover_identifies_the_operation_the_way_a_certifier_files_it(self):
        OSPAnnualUpdate.objects.create(
            prior_osp=self.v1,
            new_osp=self.v2,
            reporting_year=2028,
            submitted_at=datetime(2028, 2, 9, 9, tzinfo=dt_tz.utc),
            changes_summary="x" * 50,
        )
        cover = _pdf_text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v2))).read("00-cover.pdf"))
        for needle in (
            "COC-1463",
            "Cascadia Organic Certifiers",
            "Brandt Family Farms LLC",
            "Laurel Brandt",
            "Continuation for 2028",
            "Reporting year: 2028",
            "Plan version: v1 to v2",
            "31480 Calapooia Rd",
        ):
            self.assertIn(needle, cover, needle)
        # and the arrow that Helvetica cannot draw never reaches the page
        self.assertNotIn("\\u2192", cover)
        self.assertNotIn("\\ufb01", cover)  # the "fi" ligature it used to become

    def test_cover_names_the_missing_responsible_person(self):
        self.est.contact_person = ""
        self.est.save(update_fields=["contact_person"])
        cover = _pdf_text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v2))).read("00-cover.pdf"))
        self.assertIn("no contact person on its farm profile", cover)


class PlanReviewTests(_Farm):
    def _season(self, name, start, finish=None, parcel=None):
        return History.objects.create(name=name, parcel=parcel or self.parcel, start_date=start, finish_date=finish)

    def test_review_lists_what_the_records_did_after_the_answers(self):
        answers = datetime(2026, 8, 21, 11, tzinfo=dt_tz.utc)
        Parcel.objects.create(
            name="Muddy Creek Lease", establishment=self.est, area=3.97, date_began_managing=date(2027, 1, 15)
        )
        OSPChangeNotification.objects.create(
            osp=self.v1,
            change_category="prohibited_substance_application",
            description="Drift.",
            date_notified=date(2027, 5, 11),
            method="written",
            documentation_timing="submitted_at_notification",
        )
        s = self._season("Draper 2027 — Home Field West", answers + timedelta(days=200), answers + timedelta(days=340))
        GeneralEvent.objects.create(
            history=s,
            date=answers + timedelta(days=263),
            name="Drift",
            is_contamination_incident=True,
            contamination_source="spray_drift",
        )
        AdjoiningLandAffidavit.objects.create(
            parcel=self.parcel, neighbor_name="M. Ruiz-Delgado", border_side="W", neighbor_signed_date=date(2027, 1, 20)
        )
        review = plan_review(self.v2)
        codes = {f.code: f for f in review.findings}
        self.assertEqual(review.answers_as_of, "2026-08-21")
        self.assertIn("new_ground", codes)
        self.assertIn("Muddy Creek Lease — began 2027-01-15", codes["new_ground"].details)
        self.assertIn("change_notifications", codes)
        self.assertIn("seasons_started", codes)
        self.assertIn("seasons_closed", codes)
        self.assertIn("contamination_incidents", codes)
        self.assertIn("affidavits_added", codes)
        self.assertEqual(review.parcels_not_named, ["Muddy Creek Lease"])
        self.assertEqual([m["module_key"] for m in review.stale_modules], ["g4_0_rotation_soil"])
        self.assertGreater(review.stale_modules[0]["days_before_submission"], 365)
        self.assertFalse(review.is_clean)

    def test_review_is_clean_when_nothing_happened_after_the_answers(self):
        # answered yesterday, submitted today, nothing in between
        # answered now (after setUp's certificate row was written), submitted now, nothing between
        now = timezone.now()
        self.v2.module_responses = {
            "modules": {
                "g4_0_rotation_soil": {
                    "status": "completed",
                    "answers": {"rotation_plan": {"at": now.isoformat(), "value": "Home Field West in blueberries."}},
                }
            }
        }
        self.v2.submitted_at = now
        self.v2.save()
        review = plan_review(self.v2)
        self.assertTrue(review.is_clean, review.as_dict())

    def test_review_does_not_count_events_from_before_the_answers(self):
        """Only what came AFTER the newest answer is a reason to revisit it."""
        self._season("Duke 2025", datetime(2025, 3, 1, tzinfo=dt_tz.utc), datetime(2025, 7, 14, tzinfo=dt_tz.utc))
        codes = {f.code for f in plan_review(self.v2).findings}
        self.assertNotIn("seasons_closed", codes)
        self.assertNotIn("seasons_started", codes)

    def test_review_of_a_filed_plan_stops_at_its_filing_date(self):
        """A 2027 packet regenerated in 2028 must not list 2028 events as things to revisit.

        The review is "what the operator could have known when they filed". Unbounded, the
        2027 renewal's cover listed a January 2028 notification and the 2027 harvests — the
        NEXT year's review, printed on the wrong year's packet.
        """
        # v2 was filed 2028-02-07; the drift happened after that
        OSPChangeNotification.objects.create(
            osp=self.v2,
            change_category="prohibited_substance_application",
            description="Later drift.",
            date_notified=date(2028, 5, 11),
            method="written",
            documentation_timing="submitted_at_notification",
        )
        self._season("Duke 2028", datetime(2028, 3, 1, tzinfo=dt_tz.utc), datetime(2028, 7, 13, tzinfo=dt_tz.utc))
        codes = {f.code for f in plan_review(self.v2).findings}
        self.assertNotIn("change_notifications", codes)
        self.assertNotIn("seasons_started", codes)
        self.assertNotIn("seasons_closed", codes)

    def test_review_names_an_unnamed_responsible_person(self):
        self.est.contact_person = None
        self.est.save(update_fields=["contact_person"])
        self.assertIn("responsible_person_missing", {f.code for f in plan_review(self.v2).findings})

    def test_review_endpoint_and_submit_echo(self):
        from rest_framework.test import APIClient

        from certifications.models import OSP_SECTION_KEYS
        from users.models import WorksIn

        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        client.force_authenticate(user=self.user)
        base = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/"
        res = client.get(f"{base}{self.v2.pk}/review/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("findings", res.data)
        self.assertIn("stale_modules", res.data)

        draft = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=3,
            status="draft",
            created_by=self.user,
            previous_version=self.v2,
            module_responses=self.v1.module_responses,
            sections={
                k: {
                    "narrative_manual": (
                        f"Section {k}: the three blueberry blocks are on raised beds with sawdust mulch and "
                        "drip; the vegetable ground runs a four-year rotation with a winter cover of cereal "
                        "rye, hairy vetch and crimson clover drilled behind the harvester in October and "
                        "terminated in March. Inputs come only from the approved materials list, each "
                        "delivery checked against it when it lands. Records are kept in Trazo as the work "
                        "happens and reviewed before the renewal packet goes to the certifier each winter."
                    )
                }
                for k in OSP_SECTION_KEYS
            },
        )
        res = client.post(f"{base}{draft.pk}/submit/", {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("review", res.data)
        # The draft is submitted "today" against answers two days old, so nothing is stale;
        # what matters is that the review rode back with the submission at all.
        self.assertEqual(res.data["review"]["answers_as_of"], "2026-08-21")
        self.assertIn("findings", res.data["review"])


class ParcelApplicationEvidenceTests(_Farm):
    def test_contamination_incident_prints_on_the_parcel_application(self):
        s = History.objects.create(
            name="Draper 2027",
            parcel=self.parcel,
            production_method="organic",
            start_date=datetime(2027, 3, 1, tzinfo=dt_tz.utc),
        )
        GeneralEvent.objects.create(
            history=s,
            date=datetime(2027, 5, 11, 14, tzinfo=dt_tz.utc),
            name="Drift from adjoining seed farm",
            description="Palisade EC drifted across the west boundary in a wind shift.",
            is_contamination_incident=True,
            contamination_source="spray_drift",
            contamination_affected_area=0.6,
            corrective_action_taken="Rows 1-3 excluded from organic sale.",
            corrective_action_date=date(2027, 5, 12),
            certifier_notified=True,
            certifier_notification_date=date(2027, 5, 11),
        )
        text = _pdf_text(generate_module_pdf(self.v2, "parcel_application", parcel=self.parcel))
        self.assertIn("2027-05-11 — spray drift — 0.6 ac affected", text)
        self.assertIn("Palisade EC", text)
        self.assertIn("Rows 1-3 excluded", text)
        self.assertIn("Certifier notified 2027-05-11", text)

    def test_unnotified_incident_is_called_out(self):
        s = History.objects.create(
            name="Draper 2027", parcel=self.parcel, start_date=datetime(2027, 3, 1, tzinfo=dt_tz.utc)
        )
        GeneralEvent.objects.create(
            history=s,
            date=datetime(2027, 5, 11, tzinfo=dt_tz.utc),
            name="Drift",
            is_contamination_incident=True,
            contamination_source="spray_drift",
            certifier_notified=False,
        )
        text = _pdf_text(generate_module_pdf(self.v2, "parcel_application", parcel=self.parcel))
        self.assertIn("Certifier notification not recorded", text)

    def test_adjoining_land_affidavit_is_counted_on_the_parcel_application(self):
        AdjoiningLandAffidavit.objects.create(
            parcel=self.parcel,
            neighbor_name="Marta Ruiz-Delgado",
            neighbor_farm_name="Muddy Creek home place",
            border_side="W",
            neighbor_signed_date=date(2027, 1, 20),
            agrees_to_notify=True,
        )
        text = _pdf_text(generate_module_pdf(self.v2, "parcel_application", parcel=self.parcel))
        self.assertIn("West: Marta Ruiz-Delgado (Muddy Creek home place) — signed 2027-01-20", text)

    def test_land_history_includes_the_logged_seasons(self):
        """The typed years AND the years Trazo recorded, with the inputs applied."""
        from history.models import ChemicalEvent

        carrots = Product.objects.create(name="Carrots")
        for y in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(parcel=self.parcel, year=y, crop_grown="Blueberries ('Draper')")
        s = History.objects.create(
            name="Draper 2027",
            parcel=self.parcel,
            product=carrots,
            production_method="organic",
            start_date=datetime(2027, 3, 1, tzinfo=dt_tz.utc),
            finish_date=datetime(2027, 7, 28, tzinfo=dt_tz.utc),
        )
        ChemicalEvent.objects.create(
            history=s, date=datetime(2027, 4, 27, tzinfo=dt_tz.utc), type="FU", commercial_name="Serenade Opti"
        )
        text = _pdf_text(generate_module_pdf(self.v2, "parcel_application", parcel=self.parcel))
        self.assertIn("2027 · Carrots · organic", text)
        self.assertIn("inputs applied: Serenade Opti", text)
        self.assertIn("from season records", text)
        self.assertIn("2025 · Blueberries", text)


class NotificationNamesItsParcelTests(_Farm):
    """A § 205.400(f) notice about a field prints on that field's application.

    The 14 Jan 2028 notice "west buffer on Home Field West widened from 30 ft to 45 ft" was
    filed on the OSP screen; the Parcel Application for Home Field West went on printing
    "buffer width 30.0 ft" and the two statements never met on one page. A notice may now name
    its parcel (optional — a new buyer is not about a field), and that parcel's application
    prints it in section D beside the buffer rows, with the reminder that the rows must say the
    same thing. The product does not rewrite the buffer row from the notice — § 205.201(a)
    keeps the producer the author — it puts the two statements where a gap is visible.
    """

    def _base(self):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.v1.pk}/change-notifications/"

    def _client(self):
        from rest_framework.test import APIClient

        from users.models import WorksIn

        WorksIn.objects.get_or_create(user=self.user, company=self.company, defaults={"role": WorksIn.COMPANY_ADMIN})
        c = APIClient()
        c.force_authenticate(user=self.user)
        return c

    def test_notice_can_name_a_parcel_of_its_own_operation(self):
        res = self._client().post(
            self._base(),
            {
                "change_category": "practice_input_procedure_change",
                "description": "West buffer on Home Field West widened from 30 ft to 45 ft.",
                "date_notified": "2026-01-14",
                "method": "written",
                "documentation_timing": "submitted_at_notification",
                "parcel": self.parcel.id,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["parcel"], self.parcel.id)
        self.assertEqual(res.data["parcel_name"], "Home Field West")

    def test_notice_cannot_name_another_operations_parcel(self):
        other_co = Company.objects.create(name="Other Co")
        other_est = Establishment.objects.create(name="Other Farm", company=other_co)
        foreign = Parcel.objects.create(name="Their Block", establishment=other_est, area=1.0)
        res = self._client().post(
            self._base(),
            {
                "change_category": "practice_input_procedure_change",
                "description": "x" * 20,
                "date_notified": "2026-01-14",
                "method": "written",
                "documentation_timing": "submitted_at_notification",
                "parcel": foreign.id,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("parcel", res.data)

    def test_notice_prints_on_its_parcels_application_and_on_no_other(self):
        other = Parcel.objects.create(name="River Block", establishment=self.est, area=4.5)
        self.parcel.buffer_zones = [
            {
                "direction": "West",
                "adjoining_land_use": "Conventional grass seed",
                "buffer_width_ft": 30.0,
                "buffer_type": "30 ft mowed grass strip",
            }
        ]
        self.parcel.save(update_fields=["buffer_zones"])
        OSPChangeNotification.objects.create(
            osp=self.v1,
            parcel=self.parcel,
            change_category="practice_input_procedure_change",
            description="West buffer on Home Field West widened from 30 ft to 45 ft for 2028.",
            date_notified=date(2028, 1, 14),
            method="written",
            documentation_timing="submitted_at_notification",
        )
        hfw = _pdf_text(generate_module_pdf(self.v2, "parcel_application", parcel=self.parcel))
        # both statements now sit on one page
        self.assertIn("buffer width 30.0 ft", hfw)
        self.assertIn("2028-01-14 — Practice / input / procedure change", hfw)
        self.assertIn("widened from 30 ft to 45 ft", hfw)
        self.assertIn("must say the same thing", hfw)
        river = _pdf_text(generate_module_pdf(self.v2, "parcel_application", parcel=other))
        self.assertIn("No change notification names this parcel", river)
        self.assertNotIn("widened from 30 ft", river)

    def test_an_undated_notice_renders_and_is_reviewed_by_the_day_it_was_recorded(self):
        """`date_notified` is nullable — a (f)(2) notice may be recorded before the letter goes.

        Three render sites called `.isoformat()` on it unguarded, and the review's date window
        silently dropped undated notices through a NULL comparison. Found re-reading the code.
        """
        n = OSPChangeNotification.objects.create(
            osp=self.v1,
            parcel=self.parcel,
            change_category="practice_input_procedure_change",
            description="Buffer widened; letter to follow.",
            method="written",
            documentation_timing="deferred_to_annual_update",
        )
        self.assertIsNone(n.date_notified)
        hfw = _pdf_text(generate_module_pdf(self.v2, "parcel_application", parcel=self.parcel))
        self.assertIn("(recorded) — Practice / input / procedure change", hfw)
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v2)))
        self.assertIn(
            "(recorded) — Practice / input / procedure change", _pdf_text(zf.read("03-change-notifications.pdf"))
        )
        review = plan_review(self.v2, reference=timezone.now())
        notice = next(f for f in review.findings if f.code == "change_notifications")
        self.assertTrue(any("(recorded)" in d for d in notice.details), notice.details)

    def test_document_03_and_the_review_name_the_parcel(self):
        OSPChangeNotification.objects.create(
            osp=self.v1,
            parcel=self.parcel,
            change_category="practice_input_procedure_change",
            description="Buffer widened.",
            date_notified=date(2027, 1, 14),
            method="written",
            documentation_timing="submitted_at_notification",
        )
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v2)))
        self.assertIn(
            "Practice / input / procedure change — § 205.400(f)(2) — Home Field West",
            _pdf_text(zf.read("03-change-notifications.pdf")),
        )
        review = plan_review(self.v2)
        notice = next(f for f in review.findings if f.code == "change_notifications")
        self.assertIn(
            "2027-01-14 — Practice / input / procedure change — § 205.400(f)(2) — Home Field West", notice.details
        )
