"""The seeded Calapooia Bend farm shows a filed renewal end to end (OSP alignment audit 2026-10, S6).

WHY THIS EXISTS
---------------
Phase 3 made a § 205.406(a) filing a chain of signed revisions with a frozen copy (S1), routed
each agent's own renewal forms (S2), attached label and sale files by requirement (S3), stated
land history from evidence (S4) and scoped the records statement to what the plan requires
(S5). Each slice was proven on purpose-built rows. The depth demo is what a certifier is
actually shown, and until this slice it carried one 2026 filing that the fresh seed left in no
snapshot state at all, no signature, no attachments and two self-contradictions (T28).

These tests seed the farm once through `seed_calapooia_bend` and read the result the way a
reviewer does: the rows, then the packet. The seeder drives the product's own services
(`correct_filing`, `sign_filing`, `file_filing`, `fork_plan`), so a pass here is also a pass of
those paths on real data.

WHAT THE RE-SEED TEST DOES NOT CLAIM
------------------------------------
`--rebuild` deletes the demo farm and seeds it again. That is a demo reset, not product
behaviour, and nothing here claims a filing "survives" it. The test asserts only that seeding
is deterministic: the same revisions, years, links and content. It does not compare PDF bytes,
which carry timestamps. Survival is asserted where it is product behaviour: a new draft and a
new filing made through the API leave both 2026 revisions untouched.
"""

import hashlib
import io
import zipfile

from django.core.management import call_command
from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.required_records import NOT_CONFIRMED, required_records
from users.models import User

OWNER = "calapooia-s6@test.com"


def _seed(rebuild=False):
    call_command("seed_calapooia_bend", owner_email=OWNER, rebuild=rebuild, stdout=io.StringIO())


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Seeded(TestCase):
    @classmethod
    def setUpTestData(cls):
        quiet = io.StringIO()
        call_command("populate_usda_crop_types", crops_only=True, stdout=quiet)
        call_command("seed_national_list", stdout=quiet)
        call_command("create_plans", stdout=quiet)
        cls.owner = User.objects.create_user(
            email=OWNER, password="unused-Pw-2026", first_name="Seed", last_name="Runner"
        )
        _seed()

    def _year(self, year, expected=None):
        revisions = list(OSPAnnualUpdate.objects.filter(reporting_year=year).order_by("revision_number"))
        if expected is not None:
            self.assertEqual(len(revisions), expected, f"{year}: {[r.revision_number for r in revisions]}")
        return revisions

    def _plan(self, status):
        plan = OrganicSystemPlan.objects.filter(status=status).order_by("-version_number").first()
        self.assertIsNotNone(plan, f"no {status} plan was seeded")
        return plan

    def _packet(self, osp):
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))


class CalapooiaRenewalSpecimenTests(_Seeded):
    # -- S1: the filed renewal ------------------------------------------------------------
    def test_each_406a_item_is_populated_on_the_current_revision(self):
        original, current = self._year(2026, expected=2)
        self.assertEqual(current.corrects_id, original.pk)
        self.assertIsNone(current.superseded_at)
        # (a)(1) changes made, (a)(2) additions and deletions
        self.assertTrue(current.changes_summary.strip())
        self.assertTrue(current.additions)
        self.assertTrue(current.deletions)
        # (a)(3) stated unchanged, never inferred from an empty box
        self.assertIs(current.sections_unchanged_attestation.get("application_information"), True)
        # (a)(4) what the agent asked for, in the operator's words
        self.assertTrue(current.agent_requested_info.strip())
        # signed, filed, frozen
        self.assertEqual(current.signer_name, "Laurel Brandt")
        self.assertEqual(current.signer_title, "Member-manager")
        self.assertEqual(current.signed_content_sha256, current.content_sha256())
        self.assertEqual(current.filing_method, "email")
        self.assertEqual(current.snapshot_state, OSPAnnualUpdate.SNAPSHOT_FROZEN)
        self.assertEqual(hashlib.sha256(bytes(current.filed_pdf)).hexdigest(), current.filed_sha256)

    def test_the_august_filing_is_kept_as_a_legacy_revision_and_disclosed(self):
        original, _current = self._year(2026, expected=2)
        self.assertEqual(original.snapshot_state, OSPAnnualUpdate.SNAPSHOT_LEGACY_NONE)
        self.assertIsNone(original.signed_at)
        self.assertIsNone(original.filed_pdf)
        self.assertIsNotNone(original.superseded_at)
        status = _text(self._packet(self._plan("active")).read("02s-renewal-status-and-routing.pdf"))
        self.assertIn("Filed before Trazo kept a frozen copy", status)
        self.assertIn("Revision 2: the current filing for the year", status)
        # The demo names a fictional agent, so S2 routes it as a fallback: no borrowed form titles.
        self.assertIn("does not carry that agent's form numbering", status)
        for borrowed in ("NOPB88", "AGR 2521", "OSP Update"):
            self.assertNotIn(borrowed, status)

    def test_the_packet_carries_the_frozen_bytes_unchanged(self):
        _original, current = self._year(2026, expected=2)
        packet = self._packet(self._plan("active"))
        shipped = packet.read("annual-update/2026-revision-2.pdf")
        self.assertEqual(hashlib.sha256(shipped).hexdigest(), current.filed_sha256)

    def test_next_years_draft_is_open_and_linked(self):
        draft_plan = self._plan("draft")
        (draft,) = self._year(2027, expected=1)
        self.assertEqual(draft_plan.version_number, 4)
        self.assertEqual(draft.new_osp_id, draft_plan.pk)
        self.assertIsNone(draft.signed_at)

    def test_a_new_draft_and_filing_through_the_api_leave_both_2026_revisions_untouched(self):
        def state():
            return [
                (
                    r.pk,
                    r.revision_number,
                    r.prior_osp_id,
                    r.new_osp_id,
                    r.signed_content_sha256,
                    r.filed_sha256,
                    hashlib.sha256(bytes(r.filed_pdf or b"")).hexdigest(),
                    r.submitted_at,
                )
                for r in self._year(2026, expected=2)
            ]

        before = state()
        draft_plan = self._plan("draft")
        est = draft_plan.establishment
        client = APIClient()
        client.force_authenticate(self.owner)
        base = f"/api/companies/{est.company_id}/establishments/{est.pk}"
        res = client.post(f"{base}/osps/{draft_plan.pk}/new-version/")
        self.assertEqual(res.status_code, 201, res.content[:300])
        res = client.post(
            f"{base}/osp-annual-updates/",
            # An update continues the plan the certifier holds (the active one), never a draft.
            {
                "prior_osp": self._plan("active").pk,
                "reporting_year": 2028,
                "changes_summary": "Draft.",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content[:300])
        self.assertEqual(state(), before)

    # -- S3, S4, S5: attachments, land history, required records --------------------------
    def test_the_label_file_answers_its_requirement_and_ships(self):
        packet = self._packet(self._plan("active"))
        labels = [n for n in packet.namelist() if n.startswith("labels/")]
        self.assertEqual(len(labels), 1, labels)
        self.assertIn(labels[0], _text(packet.read("modules/G7_0.pdf")))

    def test_the_exhibit_shows_an_attached_sale_beside_one_recorded_as_text(self):
        packet = self._packet(self._plan("active"))
        sale_files = [n for n in packet.namelist() if n.startswith("audit-trail/sale-")]
        self.assertEqual(len(sale_files), 1, sale_files)
        exhibit = _text(packet.read("05-audit-trail-exhibit.pdf"))
        self.assertIn(sale_files[0], exhibit)
        self.assertIn("recorded as text; no source document is attached", exhibit)

    def test_one_required_record_is_left_unconfirmed_and_named(self):
        active = self._plan("active")
        open_ = [r.key for r in required_records(active) if r.state != "confirmed"]
        self.assertEqual(open_, ["compost_production"])
        self.assertEqual(
            next(r.state for r in required_records(active) if r.key == "compost_production"), NOT_CONFIRMED
        )
        g8 = _text(self._packet(active).read("modules/G8_0.pdf"))
        self.assertIn("Compost production records: not confirmed", g8)

    def test_each_parcel_states_inputs_were_applied_and_prints_them_dated(self):
        packet = self._packet(self._plan("active"))
        parcels = [n for n in packet.namelist() if n.startswith("parcels/")]
        self.assertEqual(len(parcels), 6)
        for name in parcels:
            page = _text(packet.read(name))
            self.assertIn("answered No to the statement that no input materials", page, name)
            self.assertNotIn("Eligible", page, name)

    # -- demo reset ------------------------------------------------------------------------
    @staticmethod
    def _snapshot():
        return [
            (
                r.reporting_year,
                r.revision_number,
                r.snapshot_state,
                r.prior_osp.version_number,
                r.new_osp.version_number if r.new_osp else None,
                r.corrects.revision_number if r.corrects else None,
                r.changes_summary,
                r.additions,
                r.deletions,
                r.sections_unchanged_attestation,
                r.application_info_changes,
                r.agent_requested_info,
                r.signer_name,
                r.signer_title,
                r.filing_method,
                r.submitted_at,
                r.signed_content_sha256 != "",
                bool(r.superseded_at),
            )
            for r in OSPAnnualUpdate.objects.select_related("prior_osp", "new_osp", "corrects").order_by(
                "reporting_year", "revision_number"
            )
        ]

    def test_rebuilding_produces_the_same_revisions_years_links_and_content(self):
        before = self._snapshot()
        self.assertEqual(len(before), 3)
        try:
            _seed(rebuild=True)
        except Exception as exc:  # noqa: BLE001 - a failed reset is the defect; fail as an assertion
            self.fail(f"--rebuild could not reset the demo farm: {exc!r}")
        self.assertEqual(self._snapshot(), before)
