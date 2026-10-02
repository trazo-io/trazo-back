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
        _original, revision_2, current = self._year(2026, expected=3)
        self.assertEqual(current.corrects_id, revision_2.pk)
        self.assertIsNone(current.superseded_at)
        # (a)(1) changes made. (a)(2) states no intention the fixture does not hold (run 3, R3-01):
        # the changes revision 2 listed as coming-year additions were already made, and moved.
        self.assertTrue(current.changes_summary.strip())
        self.assertEqual((current.additions, current.deletions), ([], []))
        self.assertTrue(current.correction_note.strip())
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
        original, _revision_2, _current = self._year(2026, expected=3)
        self.assertEqual(original.snapshot_state, OSPAnnualUpdate.SNAPSHOT_LEGACY_NONE)
        self.assertIsNone(original.signed_at)
        self.assertIsNone(original.filed_pdf)
        self.assertIsNotNone(original.superseded_at)
        status = _text(self._packet(self._plan("active")).read("02s-renewal-status-and-routing.pdf"))
        self.assertIn("Filed before Trazo kept a frozen copy", status)
        self.assertIn("Revision 3: the current filing for the year", status)
        # The demo names a fictional agent, so S2 routes it as a fallback: no borrowed form titles.
        self.assertIn("does not carry that agent's form numbering", status)
        for borrowed in ("NOPB88", "AGR 2521", "OSP Update"):
            self.assertNotIn(borrowed, status)

    def test_the_packet_carries_the_frozen_bytes_unchanged(self):
        _original, revision_2, current = self._year(2026, expected=3)
        packet = self._packet(self._plan("active"))
        self.assertEqual(
            hashlib.sha256(packet.read("annual-update/2026-revision-3.pdf")).hexdigest(), current.filed_sha256
        )
        self.assertEqual(hashlib.sha256(packet.read("02-annual-update.pdf")).hexdigest(), current.filed_sha256)
        self.assertEqual(
            hashlib.sha256(packet.read("annual-update/2026-revision-2.pdf")).hexdigest(), revision_2.filed_sha256
        )

    def test_next_years_draft_is_open_and_linked(self):
        draft_plan = self._plan("draft")
        (draft,) = self._year(2027, expected=1)
        self.assertEqual(draft_plan.version_number, 4)
        self.assertEqual(draft.new_osp_id, draft_plan.pk)
        self.assertIsNone(draft.signed_at)

    def test_a_new_draft_and_filing_through_the_api_leave_every_2026_revision_untouched(self):
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
                for r in self._year(2026, expected=3)
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

    def test_record_type_confirmations_come_from_the_fixture_not_the_seed_run(self):
        """`confirm()` is the operator's attestation and never runs from a seeder (review of #85).

        A seeded confirmation would be credited to whoever ran the command, dated the day it ran.
        """
        from certifications.services.common_osp_records import _confirmations

        confirmations = _confirmations(self._plan("active"))
        self.assertGreater(len(confirmations), 0, "no confirmation was read")
        for key, entry in confirmations.items():
            self.assertIsNone(entry.get("confirmed_by"), key)
            self.assertTrue(entry.get("confirmed_at", "").startswith("2026-08-21"), (key, entry.get("confirmed_at")))

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
                r.correction_note,
                # Revision 2's bytes are a record: pinned, so a rebuild restores them exactly.
                r.filed_sha256 if r.revision_number == 2 else None,
            )
            for r in OSPAnnualUpdate.objects.select_related("prior_osp", "new_osp", "corrects").order_by(
                "reporting_year", "revision_number"
            )
        ]

    def test_rebuilding_produces_the_same_revisions_years_links_and_content(self):
        before = self._snapshot()
        self.assertEqual(len(before), 4)
        try:
            _seed(rebuild=True)
        except Exception as exc:  # noqa: BLE001 - a failed reset is the defect; fail as an assertion
            self.fail(f"--rebuild could not reset the demo farm: {exc!r}")
        self.assertEqual(self._snapshot(), before)


#: Revision 2 as filed on 2026-10-01, the bytes the run-3 reviewer hashed. Never re-rendered.
REVISION_2_SHA256 = "e20e05678556cc1e3c22a802defd7442ed2a19daa21a125a91359f70d92761b7"
#: Revision 3 as filed on 2026-10-02, the bytes sent for the run-4 review. Never re-rendered.
REVISION_3_SHA256 = "4cd62bbfb9367fd8287c9e7fb56abfb9cc777802935abff96b6aea5e79dbe3bb"


class Run3SpecimenTests(_Seeded):
    """Run 3 (2026-10-02): R3-01, R3-07 and R3-08 corrected without rewriting history."""

    def _current_02(self):
        return _text(self._packet(self._plan("active")).read("02-annual-update.pdf"))

    def test_revision_2_keeps_the_bytes_it_was_filed_with(self):
        _original, revision_2, _current = self._year(2026, expected=3)
        self.assertEqual(revision_2.filed_sha256, REVISION_2_SHA256)
        self.assertEqual(hashlib.sha256(bytes(revision_2.filed_pdf)).hexdigest(), REVISION_2_SHA256)
        # Its signature still matches its content: the note field joins the hash only when set.
        self.assertEqual(revision_2.correction_note, "")
        self.assertEqual(revision_2.signed_content_sha256, revision_2.content_sha256())
        # And the hash is over exactly the fields signed before the note existed, so no revision
        # signed earlier moves: the empty note is not in the content at all.
        self.assertNotIn("correction_note", revision_2.signed_content())
        self.assertEqual(set(revision_2.signed_content()), set(OSPAnnualUpdate.SIGNED_FIELDS))
        self.assertIsNotNone(revision_2.superseded_at)

    def test_revision_3_keeps_the_bytes_sent_for_review(self):
        _original, _revision_2, current = self._year(2026, expected=3)
        self.assertEqual(current.filed_sha256, REVISION_3_SHA256)
        self.assertEqual(hashlib.sha256(bytes(current.filed_pdf)).hexdigest(), REVISION_3_SHA256)
        self.assertEqual(current.signed_content_sha256, current.content_sha256())

    def test_revision_3_says_what_it_corrects(self):
        filing = self._current_02()
        self.assertIn("What revision 3 corrects in revision 2", filing)
        for point in ("no split or parallel production", "already made in 2026", "No acknowledgment is recorded"):
            self.assertIn(point, filing)
        self.assertIn("Revision 2 is kept as filed", filing)

    def test_the_current_filing_agrees_with_its_plan_on_split_and_parallel_production(self):
        _original, _revision_2, current = self._year(2026, expected=3)
        self.assertNotIn("no split or parallel production", current.changes_summary.lower())
        self.assertIn("split operation with parallel production", current.changes_summary)
        g6 = _text(self._packet(self._plan("active")).read("modules/G6_0.pdf"))
        self.assertIn("Yes", g6)

    def test_coming_year_lists_carry_no_past_change_and_no_invented_intention(self):
        filing = self._current_02()
        self.assertIn("(a)(2) Additions intended for the coming year (2027)", filing)
        self.assertIn("(a)(2) Deletions intended for the coming year (2027)", filing)
        self.assertEqual(filing.count("None stated."), 2)

    def test_the_grandevo_acknowledgment_is_the_operators_account_never_a_record(self):
        packet = self._packet(self._plan("active"))
        notices = _text(packet.read("03-change-notifications.pdf"))
        self.assertIn("no acknowledgment recorded in Trazo", notices)
        self.assertNotIn("not yet acknowledged", notices)
        filing = _text(packet.read("02-annual-update.pdf"))
        self.assertIn("that acknowledgment is not recorded with the notification in Trazo", filing)
        from certifications.models import OSPChangeNotification

        self.assertFalse(
            OSPChangeNotification.objects.filter(certifier_acknowledged_at__isnull=False).exists(),
            "no acknowledgment is invented",
        )

    def test_the_buffer_rows_are_harvested_on_every_page_that_names_them(self):
        packet = self._packet(self._plan("active"))
        for name in packet.namelist():
            if name.startswith("parcels/parcel-application-Home Field"):
                page = _text(packet.read(name))
                self.assertNotIn("unharvested", page, name)
                self.assertIn("picked separately", page, name)

    def test_the_cover_names_frozen_and_reconstructed_documents_and_counts_entries(self):
        cover = _text(self._packet(self._plan("active")).read("00-cover.pdf"))
        self.assertNotIn("Every document is generated from the operation's live records", cover)
        self.assertIn("is the document as signed and filed, unchanged since", cover)
        self.assertIn("Entries under (a)(2): no addition entries, no deletion entries", cover)
        self.assertNotIn("1 deletion", cover)
