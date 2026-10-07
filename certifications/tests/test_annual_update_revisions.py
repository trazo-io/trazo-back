"""A filed § 205.406(a) update is the document the agent received, and it stays that document.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10, finding T20 (`documentation/audits/OSP-ALIGNMENT-2026-10/`). Before
2026-10-01:

  * a filed update stayed editable until the certifier acknowledged it, and nothing in the
    product ever recorded an acknowledgement;
  * document 02 was rendered from the live row on every download, so the packet could not show
    what had actually been filed;
  * uniqueness was per plan VERSION, so a year could hold two filings against two versions;
  * there was no signature, no (a)(3) changes field and no (a)(4) at all.

The cases below are the acceptance list from the Phase 3 plan: edits after signing, corrected
submissions, legacy filings without a frozen copy, a new draft beside a filed year, and
signatures that cannot come from the payload.
"""

import hashlib
import importlib
import io
import zipfile
from datetime import datetime
from datetime import timezone as dt_tz

from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase

from pdfminer.high_level import extract_text
from rest_framework import status
from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.osp_module_pdf import generate_osp_packet, render_filing_pdf
from company.models import Company, Establishment
from users.models import User, WorksIn


def _pdf_text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Renewal(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="rev@test.com", password="x", is_verified=True, first_name="Laurel", last_name="Brandt"
        )
        self.company = Company.objects.create(name="Revision Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Revision Farm", company=self.company)
        self.v1 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", created_by=self.user
        )
        self.client.force_authenticate(user=self.user)

    def _base(self):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osp-annual-updates/"

    def _create(self, year=2026, **content):
        payload = {
            "prior_osp": self.v1.pk,
            "reporting_year": year,
            "changes_summary": "Hedgerow planted on the north line.",
            **content,
        }
        res = self.client.post(self._base(), payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:400])
        return OSPAnnualUpdate.objects.get(pk=res.json()["id"])

    def _sign(self, filing, **extra):
        res = self.client.post(f"{self._base()}{filing.pk}/sign/", {"signer_title": "Owner", **extra}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:400])
        filing.refresh_from_db()
        return filing

    def _file(self, filing, method="agent_web_form", when="2026-08-21"):
        res = self.client.post(
            f"{self._base()}{filing.pk}/file/", {"filing_method": method, "submitted_at": when}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:400])
        filing.refresh_from_db()
        return filing

    def _filed(self, year=2026, **content):
        return self._file(self._sign(self._create(year=year, **content)))


class EditsAfterSigningTests(_Renewal):
    HASHED_EDITS = {
        "changes_summary": "Rewritten after signing.",
        "additions": ["North block, 4.0 ac"],
        "deletions": ["South block, 2.0 ac"],
        "sections_unchanged_attestation": {"practices_procedures": True},
        "application_info_changes": "New phone number.",
        "agent_requested_info": "Updated water test.",
        "agent_requested_info_none": True,
        "reporting_year": 2027,
        "prior_osp": None,  # filled in setUp-dependent below
    }

    def test_every_signed_field_is_refused_after_signing(self):
        filing = self._sign(self._create())
        signed_hash = filing.signed_content_sha256
        self.assertEqual(signed_hash, filing.content_sha256())
        v2 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=2, status="draft")
        edits = dict(self.HASHED_EDITS, prior_osp=v2.pk)
        for field, value in edits.items():
            with self.subTest(field=field):
                res = self.client.patch(f"{self._base()}{filing.pk}/", {field: value}, format="json")
                self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, (field, res.content[:300]))
        filing.refresh_from_db()
        self.assertEqual(filing.content_sha256(), signed_hash, "signed content changed")

    def test_filing_and_withdrawal_leave_the_signed_content_alone(self):
        """Status fields live outside the hash. Recording that it was filed, and later that it
        was withdrawn, changes no signed field."""
        filing = self._sign(self._create())
        signed_hash = filing.signed_content_sha256
        filing = self._file(filing)
        res = self.client.post(f"{self._base()}{filing.pk}/withdraw/", {"reason": "Filed in error."}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        filing.refresh_from_db()
        self.assertIsNotNone(filing.withdrawn_at)
        self.assertEqual(filing.content_sha256(), signed_hash)

    def test_filing_needs_a_signature(self):
        filing = self._create()
        res = self.client.post(f"{self._base()}{filing.pk}/file/", {"filing_method": "email"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        filing.refresh_from_db()
        self.assertIsNone(filing.submitted_at)

    def test_the_filing_date_is_set_once(self):
        filing = self._filed()
        res = self.client.post(
            f"{self._base()}{filing.pk}/file/", {"filing_method": "email", "submitted_at": "2026-01-02"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        filing.refresh_from_db()
        self.assertEqual(filing.submitted_at.date().isoformat(), "2026-08-21")
        self.assertEqual(filing.filing_method, "agent_web_form")


class SignerComesFromTheRequestTests(_Renewal):
    def test_the_payload_cannot_name_the_signer(self):
        other = User.objects.create_user(email="other@test.com", password="x", first_name="Not", last_name="Me")
        filing = self._sign(
            self._create(),
            signer_name="Someone Else",
            signed_by=other.pk,
            signed_at="2020-01-01T00:00:00Z",
        )
        self.assertEqual(filing.signed_by_id, self.user.pk)
        self.assertEqual(filing.signer_name, "Laurel Brandt")
        self.assertEqual(filing.signer_title, "Owner")
        self.assertNotEqual(filing.signed_at.year, 2020)

    def test_an_edit_cannot_set_signature_fields(self):
        filing = self._create()
        res = self.client.patch(f"{self._base()}{filing.pk}/", {"signer_name": "Someone Else"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        filing.refresh_from_db()
        self.assertEqual(filing.signer_name, "")


class CorrectedSubmissionTests(_Renewal):
    def test_a_correction_is_the_next_revision_and_the_original_keeps_its_bytes(self):
        first = self._filed()
        original_bytes = bytes(first.filed_pdf)
        self.assertEqual(hashlib.sha256(original_bytes).hexdigest(), first.filed_sha256)

        res = self.client.post(f"{self._base()}{first.pk}/correct/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:300])
        second = OSPAnnualUpdate.objects.get(pk=res.json()["id"])
        self.assertEqual(second.revision_number, 2)
        self.assertEqual(second.corrects_id, first.pk)
        self.assertIsNone(second.signed_at)

        edit = self.client.patch(
            f"{self._base()}{second.pk}/", {"changes_summary": "Hedgerow planted on the east line."}, format="json"
        )
        self.assertEqual(edit.status_code, status.HTTP_200_OK, edit.content[:300])
        second = self._file(self._sign(second), method="email", when="2026-09-02")

        first.refresh_from_db()
        self.assertEqual(bytes(first.filed_pdf), original_bytes, "the corrected revision's document changed")
        self.assertEqual(first.filed_sha256, hashlib.sha256(original_bytes).hexdigest())
        self.assertIsNotNone(first.superseded_at)

        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1)))
        self.assertEqual(zf.read("02-annual-update.pdf"), bytes(second.filed_pdf))
        self.assertEqual(zf.read("annual-update/2026-revision-1.pdf"), original_bytes)
        self.assertEqual(zf.read("annual-update/2026-revision-2.pdf"), bytes(second.filed_pdf))
        status_page = _pdf_text(zf.read("02s-renewal-status-and-routing.pdf"))
        self.assertIn("Revision 1: corrected", status_page)
        self.assertIn("Revision 2: the current filing", status_page)
        self.assertIn("north line", _pdf_text(original_bytes))
        self.assertNotIn("east line", _pdf_text(original_bytes))

    def test_a_year_never_holds_two_current_filings(self):
        self._filed()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OSPAnnualUpdate.objects.create(
                prior_osp=self.v1,
                reporting_year=2026,
                revision_number=2,
                submitted_at=datetime(2026, 9, 1, tzinfo=dt_tz.utc),
            )

    def test_a_second_update_for_the_year_is_refused_not_added(self):
        self._filed()
        self.client.raise_request_exception = False
        res = self.client.post(
            self._base(), {"prior_osp": self.v1.pk, "reporting_year": 2026, "changes_summary": "again"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(OSPAnnualUpdate.objects.filter(reporting_year=2026).count(), 1)

    def test_a_withdrawn_correction_does_not_bring_back_the_revision_it_replaced(self):
        """Revision 1 was replaced when revision 2 was filed. Withdrawing revision 2 leaves the
        year with no current filing; it does not make revision 1 current again."""
        first = self._filed()
        res = self.client.post(f"{self._base()}{first.pk}/correct/")
        second = self._file(self._sign(OSPAnnualUpdate.objects.get(pk=res.json()["id"])), when="2026-09-02")
        self.client.post(f"{self._base()}{second.pk}/withdraw/", {"reason": "Sent to the wrong agent."})
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1)))
        self.assertNotEqual(zf.read("02-annual-update.pdf"), bytes(first.filed_pdf))
        self.assertIn("No § 205.406(a) annual update is on file", _pdf_text(zf.read("02-annual-update.pdf")))
        status_page = _pdf_text(zf.read("02s-renewal-status-and-routing.pdf"))
        self.assertIn("Revision 1: corrected", status_page)
        self.assertIn("Revision 2: withdrawn", status_page)
        self.assertIn("Sent to the wrong agent.", status_page)

    def test_only_the_newest_revision_is_corrected(self):
        first = self._filed()
        self.assertEqual(self.client.post(f"{self._base()}{first.pk}/correct/").status_code, 201)
        self.assertEqual(self.client.post(f"{self._base()}{first.pk}/correct/").status_code, 409)


class FiledDocumentIsStableTests(_Renewal):
    def test_02_is_the_filed_bytes_after_the_records_change(self):
        filing = self._filed()
        frozen = bytes(filing.filed_pdf)
        # Things 02 renders from live records: the farm's name, the plan, the year's content.
        self.est.name = "Renamed Farm"
        self.est.save(update_fields=["name"])
        self.v1.sections = {"practices_procedures": {"narrative": "Changed later."}}
        self.v1.save(update_fields=["sections"])
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1)))
        self.assertEqual(packet.read("02-annual-update.pdf"), frozen)
        self.assertNotIn("Renamed Farm", _pdf_text(packet.read("02-annual-update.pdf")))

    def test_a_new_draft_and_a_next_year_draft_leave_the_filed_year_alone(self):
        filing = self._filed()
        frozen, sha, content = bytes(filing.filed_pdf), filing.filed_sha256, filing.content_sha256()
        res = self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{self.v1.pk}/new-version/",
            {},
            format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        v2 = OrganicSystemPlan.objects.get(establishment=self.est, version_number=2)
        nxt = self._create(year=2027)
        nxt.refresh_from_db()
        self.assertEqual(nxt.new_osp_id, v2.pk)

        filing.refresh_from_db()
        self.assertEqual(bytes(filing.filed_pdf), frozen)
        self.assertEqual(filing.filed_sha256, sha)
        self.assertEqual(filing.content_sha256(), content)
        self.assertEqual(filing.prior_osp_id, self.v1.pk)
        self.assertEqual(filing.revision_number, 1)
        self.assertIsNone(filing.superseded_at)

    def test_a_filed_revision_cannot_be_deleted(self):
        filing = self._filed()
        self.assertEqual(self.client.delete(f"{self._base()}{filing.pk}/").status_code, status.HTTP_423_LOCKED)
        self.assertTrue(OSPAnnualUpdate.objects.filter(pk=filing.pk).exists())


class LegacyFilingTests(_Renewal):
    def _backfill(self):
        module = importlib.import_module("certifications.migrations.0044_annual_update_revisions_backfill")
        module.preflight_and_backfill(django_apps, None)

    def test_a_legacy_filing_is_disclosed_never_frozen_or_signed(self):
        legacy = OSPAnnualUpdate.objects.create(
            prior_osp=self.v1,
            reporting_year=2025,
            changes_summary="Filed the old way.",
            submitted_at=datetime(2025, 3, 1, tzinfo=dt_tz.utc),
        )
        OSPAnnualUpdate.objects.filter(pk=legacy.pk).update(establishment=None, revision_number=1, snapshot_state="")
        self._backfill()
        legacy.refresh_from_db()
        self.assertEqual(legacy.snapshot_state, OSPAnnualUpdate.SNAPSHOT_LEGACY_NONE)
        self.assertEqual(legacy.establishment_id, self.est.pk)
        self.assertIsNone(legacy.filed_pdf)
        self.assertIsNone(legacy.signed_at)
        self.assertEqual(legacy.signer_name, "")

        page = _pdf_text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1))).read("02-annual-update.pdf"))
        self.assertIn("Filed before Trazo kept a frozen copy", page)
        self.assertIn("No signature was recorded in Trazo", page)
        self.assertNotIn("Signed in Trazo", page)
        status_page = _pdf_text(
            zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1))).read("02s-renewal-status-and-routing.pdf")
        )
        self.assertIn("rendered from current records, not the filed document", status_page)

    def test_a_legacy_filing_is_corrected_not_edited(self):
        legacy = OSPAnnualUpdate.objects.create(
            prior_osp=self.v1, reporting_year=2025, submitted_at=datetime(2025, 3, 1, tzinfo=dt_tz.utc)
        )
        self.assertEqual(
            self.client.patch(f"{self._base()}{legacy.pk}/", {"changes_summary": "x"}, format="json").status_code,
            status.HTTP_409_CONFLICT,
        )
        self.assertEqual(self.client.post(f"{self._base()}{legacy.pk}/sign/").status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self.client.post(f"{self._base()}{legacy.pk}/correct/").status_code, status.HTTP_201_CREATED)

    def test_the_preflight_names_duplicate_years_and_picks_no_winner(self):
        v2 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=2, status="active")
        a = OSPAnnualUpdate.objects.create(prior_osp=self.v1, reporting_year=2025, revision_number=1)
        b = OSPAnnualUpdate.objects.create(prior_osp=v2, reporting_year=2025, revision_number=2)
        # The shape the old per-version constraint allowed: same year, two versions, no revisions.
        OSPAnnualUpdate.objects.filter(pk__in=[a.pk, b.pk]).update(establishment=None, revision_number=1)
        raised = None
        try:
            with transaction.atomic():
                self._backfill()
        except Exception as exc:  # noqa: BLE001 — the TYPE is the assertion
            raised = exc
        self.assertIsInstance(raised, RuntimeError, "the preflight must refuse by name, not hit the constraint")
        self.assertIn(str(a.pk), str(raised))
        self.assertIn(str(b.pk), str(raised))
        self.assertEqual(
            OSPAnnualUpdate.objects.filter(pk__in=[a.pk, b.pk], establishment__isnull=True).count(),
            2,
            "the preflight changed rows before refusing",
        )


class ApplicationAndAgentInfoStatesTests(_Renewal):
    def _render(self, **content):
        filing = OSPAnnualUpdate.objects.create(prior_osp=self.v1, reporting_year=2026, **content)
        return _pdf_text(render_filing_pdf(filing))

    def test_a3_and_a4_print_three_distinct_states(self):
        unanswered = self._render()
        a3 = unanswered[unanswered.index("(a)(3)") :]
        a4 = unanswered[unanswered.index("(a)(4)") :]
        self.assertIn("Not stated on this filing", a3[:300])
        self.assertIn("Not stated on this filing", a4[:200])
        self.assertNotIn("No changes", a3[:300])
        self.assertNotIn("asked for no further", a4[:200])
        OSPAnnualUpdate.objects.all().delete()

        stated_none = self._render(
            sections_unchanged_attestation={"application_information": True}, agent_requested_info_none=True
        )
        self.assertIn("No changes. The operator attests", stated_none)
        self.assertIn("asked for no further information", stated_none)
        OSPAnnualUpdate.objects.all().delete()

        changed = self._render(application_info_changes="New mailing address.", agent_requested_info="Water test.")
        self.assertIn("New mailing address.", changed)
        self.assertIn("Water test.", changed)
        self.assertNotIn("No changes. The operator attests", changed)


class ReviewOfBack79Tests(_Renewal):
    """Defects the review of back #79 found, each one reproduced before it was fixed."""

    def test_a_new_filing_is_frozen_without_the_legacy_heading(self):
        """The copy is rendered while the row is filed and has no bytes yet, which is what a legacy
        row looks like. It was frozen with "not signed in Trazo" above its own signature."""
        text = _pdf_text(bytes(self._filed().filed_pdf))
        self.assertNotIn("Filed before Trazo kept a frozen copy", text)
        self.assertNotIn("No signature was recorded in Trazo", text)
        self.assertIn("Signed in Trazo by Laurel Brandt", text)

    def test_a_revision_with_a_correction_cannot_be_filed_after_it(self):
        """Sign r1, correct it, file r2, then file r1: a 409, never a second current filing (500)."""
        first = self._sign(self._create())
        res = self.client.post(f"{self._base()}{first.pk}/correct/")
        second = self._file(self._sign(OSPAnnualUpdate.objects.get(pk=res.json()["id"])))
        self.client.raise_request_exception = False
        late = self.client.post(f"{self._base()}{first.pk}/file/", {"filing_method": "email"}, format="json")
        self.assertEqual(late.status_code, status.HTTP_409_CONFLICT, late.content[:300])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNone(first.submitted_at)
        self.assertIsNotNone(first.superseded_at)
        self.assertIsNone(second.superseded_at)

    def test_the_year_of_a_draft_cannot_be_moved(self):
        """Was a 500: the update path skipped the duplicate-year check and hit the constraint."""
        self._filed(year=2026)
        draft = self._create(year=2027)
        self.client.raise_request_exception = False
        res = self.client.patch(f"{self._base()}{draft.pk}/", {"reporting_year": 2026}, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content[:300])
        self.assertIn("reporting_year", res.json())

    def test_a_year_whose_filing_was_withdrawn_can_be_filed_again(self):
        """Withdrawn, then a new update for the same year: the next revision, not a dead end."""
        filed = self._filed()
        self.client.post(f"{self._base()}{filed.pk}/withdraw/", {"reason": "Filed for the wrong farm."})
        again = self._create()
        self.assertEqual(again.revision_number, 2)
        self.assertIsNone(again.corrects_id)
        self._file(self._sign(again), when="2026-09-03")

    def test_todays_date_is_not_in_the_future_in_the_morning(self):
        from unittest.mock import patch

        from django.utils import timezone

        filing = self._sign(self._create())
        morning = datetime(2026, 9, 3, 8, 0, tzinfo=dt_tz.utc)
        with patch.object(timezone, "now", return_value=morning):
            res = self.client.post(
                f"{self._base()}{filing.pk}/file/",
                {"filing_method": "email", "submitted_at": "2026-09-03"},
                format="json",
            )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])

    def test_a_withdrawn_only_year_is_still_the_year_the_packet_reports(self):
        """2025 filed cleanly; 2026 filed, then withdrawn. The packet must not fall back to 2025 as
        if 2026 had never happened."""
        old = self._filed(year=2025)
        newer = self._filed(year=2026)
        self.client.post(f"{self._base()}{newer.pk}/withdraw/", {"reason": "Sent to the wrong agent."})
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1)))
        self.assertNotEqual(zf.read("02-annual-update.pdf"), bytes(old.filed_pdf))
        status_page = _pdf_text(zf.read("02s-renewal-status-and-routing.pdf"))
        self.assertIn("2026 annual update", status_page)
        self.assertIn("Revision 1: withdrawn", status_page)


class PreviousYearBaselineTests(_Renewal):
    """A synthetic prior-year filing beside this year's renewal (kept out of the demo farm on
    purpose: Calapooia carries no 2025 filing because its content would have to be invented)."""

    def test_the_prior_year_stays_as_filed_when_this_years_renewal_is_filed(self):
        baseline = self._file(self._sign(self._create(year=2025)), when="2025-08-20")
        baseline_bytes, baseline_sha = bytes(baseline.filed_pdf), baseline.filed_sha256
        renewal = self._file(
            self._sign(self._create(year=2026, changes_summary="Second carrot planting added.")), when="2026-08-21"
        )

        baseline.refresh_from_db()
        self.assertEqual(bytes(baseline.filed_pdf), baseline_bytes)
        self.assertEqual(baseline.filed_sha256, baseline_sha)
        self.assertIsNone(baseline.superseded_at, "a new year never supersedes the previous one")
        self.assertIsNone(renewal.corrects_id)

        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1)))
        shipped = packet.read("annual-update/2026-revision-1.pdf")
        self.assertEqual(hashlib.sha256(shipped).hexdigest(), renewal.filed_sha256)
        self.assertIn("Second carrot planting added.", _pdf_text(shipped))
        self.assertNotIn("annual-update/2025-revision-1.pdf", packet.namelist(), "the packet reports the newest year")


class FreezeEvidenceCommandTests(_Renewal):
    """Run 3, R3-09: the freeze is shown by a command anyone can replay, not by a log of strings."""

    def _run(self, filing):
        import json
        import tempfile

        from django.core.management import CommandError, call_command

        with tempfile.NamedTemporaryFile("r", suffix=".json") as out:
            try:
                call_command(
                    "osp_freeze_evidence",
                    filing=filing.pk,
                    user_email=self.user.email,
                    out=out.name,
                    stdout=io.StringIO(),
                )
            except CommandError:
                pass  # the evidence is written before a failed check raises; the assertions read it
            return json.loads(open(out.name).read())

    def test_the_evidence_carries_payload_ids_values_and_the_refusal(self):
        import hashlib

        filing = self._filed()
        evidence = self._run(filing)
        self.assertTrue(evidence["unchanged"], evidence["checks"])
        before = evidence["before"]
        # The payload recomputes the signed hash on its own.
        self.assertEqual(
            hashlib.sha256(before["canonical_payload"].encode("utf-8")).hexdigest(), filing.signed_content_sha256
        )
        self.assertIn("sort_keys=True", evidence["hash_method"])
        patch = evidence["edits"][0]
        self.assertEqual(patch["response"]["status"], 409)
        self.assertTrue(patch["response"]["body"], "the refusal's body is kept")
        rename = next(e for e in evidence["edits"] if e.get("field") == "name")
        self.assertEqual(rename["id"], self.est.pk)
        self.assertNotEqual(rename["before"], rename["after"])
        self.assertEqual(evidence["after_edits"]["filed_bytes_sha256"], filing.filed_sha256)

    def test_nothing_it_does_is_kept(self):
        from certifications.models import OSPChangeNotification

        filing = self._filed()
        self._run(filing)
        self.est.refresh_from_db()
        self.assertEqual(self.est.name, "Revision Farm")
        self.assertFalse(OSPChangeNotification.objects.exists())
        self.v1.refresh_from_db()
        self.assertNotIn("edited_after_filing", self.v1.sections or {})


class FreezeEvidenceCommitsNothingTests(TransactionTestCase):
    """Outside a test transaction, as `manage.py` runs it: nothing the command touches is kept, and
    the evidence says so from the records themselves (review of back #93)."""

    def test_no_write_survives_the_command(self):
        import json
        import tempfile

        from django.core.management import CommandError, call_command

        from certifications.models import OSPChangeNotification
        from certifications.services.annual_update_filing import file_filing, sign_filing

        user = User.objects.create_user(email="tx@test.com", password="x", is_verified=True, first_name="T")
        company = Company.objects.create(name="Tx Co")
        WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Tx Farm", company=company)
        # Active, with an answer its stored sections do not carry yet: building its packet compiles the
        # narrative in memory and, since the recordkeeping review (F-06, 2026-10-07), does NOT save it.
        # The command's own edit below is the only write the evidence must show rolled back.
        plan = OrganicSystemPlan.objects.create(
            establishment=est,
            version_number=1,
            status="active",
            created_by=user,
            module_responses={"modules": {"g6_0_production": {"answers": {"split_operation": {"value": False}}}}},
        )
        filing = OSPAnnualUpdate.objects.create(prior_osp=plan, reporting_year=2026, changes_summary="Hedgerow.")
        filing = sign_filing(filing, user, signer_title="Owner")
        filing = file_filing(filing, filing_method="email")
        plan.refresh_from_db()
        before = (plan.sections, plan.updated_at)

        with tempfile.NamedTemporaryFile("r", suffix=".json") as out:
            try:
                call_command(
                    "osp_freeze_evidence", filing=filing.pk, user_email=user.email, out=out.name, stdout=io.StringIO()
                )
            except CommandError:
                pass  # a failed check still writes the evidence; the assertions below read it
            evidence = json.loads(open(out.name).read())

        plan.refresh_from_db()
        self.assertEqual((plan.sections, plan.updated_at), before, "the packet build's narrative save was kept")
        est.refresh_from_db()
        self.assertEqual(est.name, "Tx Farm")
        self.assertFalse(OSPChangeNotification.objects.exists())
        self.assertTrue(evidence["checks"]["edited_records_rolled_back"], evidence["records_after_rollback"])
        # Run 4, R4-03: every plan-section digest is placed at a named stage and reconciles.
        import hashlib as _h

        stages = evidence["plan_sections_stages"]
        edit = next(e for e in evidence["edits"] if e.get("field") == "sections")
        self.assertEqual(edit["stage_of_before"], "2_after_the_packet_build_recompiled_narratives")
        self.assertEqual(edit["before_sha256"], stages["2_after_the_packet_build_recompiled_narratives"])
        # Recordkeeping review F-06: the packet build no longer writes an active plan, so the digest
        # after the build equals the digest before it. (It used to differ, and that difference was
        # the defect: a download rewrote the on-file narrative.)
        self.assertEqual(stages["1_before_the_command"], stages["2_after_the_packet_build_recompiled_narratives"])
        self.assertEqual(stages["1_before_the_command"], stages["3_after_the_rollback"])
        self.assertEqual(stages["1_before_the_command"], evidence["records_before"]["plan_sections_sha256"])
        for side in ("before", "after"):
            self.assertEqual(_h.sha256(edit[f"{side}_canonical"].encode("utf-8")).hexdigest(), edit[f"{side}_sha256"])
        notice = next(e for e in evidence["edits"] if e["kind"] == "record_created")
        self.assertEqual(notice["values"]["description"], "Change notified after the filing.")


class ReplacementHistoryTests(_Renewal):
    """Run 4, R4-02: each revision keeps the day its own successor was filed, through later corrections."""

    def _correct_and_file(self, filing, when):
        res = self.client.post(f"{self._base()}{filing.pk}/correct/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:300])
        nxt = OSPAnnualUpdate.objects.get(pk=res.json()["id"])
        return self._file(self._sign(nxt), method="email", when=when)

    def test_a_three_revision_chain_keeps_each_replacement_date(self):
        first = self._filed()  # filed 2026-08-21
        second = self._correct_and_file(first, "2026-09-01")
        third = self._correct_and_file(second, "2026-09-15")
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.superseded_at.date().isoformat(), "2026-09-01")
        self.assertEqual(second.superseded_at.date().isoformat(), "2026-09-15")
        self.assertIsNone(third.superseded_at)
        status_page = _pdf_text(
            zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1))).read("02s-renewal-status-and-routing.pdf")
        )
        self.assertIn("replaced as the year's filing on 2026-09-01", status_page)
        self.assertIn("replaced as the year's filing on 2026-09-15", status_page)
