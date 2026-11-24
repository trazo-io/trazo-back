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
from users.constants import PRODUCER
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
            email=OWNER,
            password="unused-Pw-2026",
            first_name="Seed",
            last_name="Runner",
            # The seeder refuses an owner who could not sign in to the app (VID-15).
            user_type=PRODUCER,
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
    # -- The seal on a seeded closed season ---------------------------------------------------
    def test_every_sealed_season_verifies_over_the_rows_the_seeder_created(self):
        """The fixture carries the source database's finalization_hash, computed over ITS ids.
        Copied as is, no seeded seal could match, and the QR page read the specimen as tampered
        (diagnose_seals on production, 2026-11-04). The seeder reseals over what it wrote."""
        from history.models import Production
        from history.seals import CURRENT_VERSION, INTACT, verify

        sealed = list(Production.objects.filter(extra_data__has_key="finalization_hash"))
        self.assertGreaterEqual(len(sealed), 2, "the fixture has closed, sealed seasons")
        for history in sealed:
            with self.subTest(season=history.name):
                self.assertEqual(history.extra_data["finalization_hash_version"], CURRENT_VERSION)
                self.assertEqual(verify(history).status, INTACT)

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
        # The signed hash is the one the frozen copy states (run 7c, R7-02), never a re-hash of
        # this database's row ids.
        self.assertIn(f"Signed content: sha256 {current.signed_content_sha256}.", _text(bytes(current.filed_pdf)))
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
        for borrowed in ("ORGB88", "AGR 2521", "OSP Update"):
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

    def test_every_required_record_is_confirmed(self):
        # The compost record was left open on purpose to show the G8.0 attestation gate; the demo now
        # reads clean (2026-10-31), and the gate is tested on its own rows in
        # `certifications.tests.test_required_records_attestation`.
        active = self._plan("active")
        self.assertEqual([r.key for r in required_records(active) if r.state == NOT_CONFIRMED], [])
        g8 = _text(self._packet(active).read("modules/G8_0.pdf"))
        self.assertNotIn(": not confirmed", g8)

    def test_the_active_plan_answers_every_question_its_modules_show(self):
        # Production packet, 2026-10-29: questions added after the August rehearsal left G6.0, G6.1,
        # G6.4 and G8.0 unfinished on the demo.
        from certifications.osp_modules import MODULE_REGISTRY
        from certifications.osp_modules.conditions import answer_value, visible_questions

        active = self._plan("active")
        modules = active.module_responses["modules"]
        open_ = []
        for module in MODULE_REGISTRY:
            entry = modules.get(module.key) or {}
            if entry.get("not_applicable"):
                continue
            answers = entry.get("answers") or {}
            for _page, q in visible_questions(module, answers):
                if q.embed or q.parcel_field or q.kind in ("info", "upload"):
                    continue
                if answer_value(answers, q.key) in (None, "", []):
                    open_.append(f"{module.key}.{q.key}")
        self.assertEqual(open_, [])
        packet = self._packet(active)
        for name in packet.namelist():
            if name.startswith("modules/"):
                self.assertNotIn("Not yet answered", _text(packet.read(name)), name)

    def test_module_attestations_are_credited_to_the_seeding_owner(self):
        # The fixture carries the rehearsal database's user id; elsewhere it is nobody, or a stranger
        # whose name the N/A stamp would print.
        for plan in OrganicSystemPlan.objects.all():
            for key, entry in plan.module_responses["modules"].items():
                if entry.get("completed_by") is not None:
                    self.assertEqual(entry["completed_by"], self.owner.pk, key)
                if entry.get("na_attestation"):
                    self.assertEqual(entry["na_attestation"]["by"], self.owner.pk, key)
        w2 = _text(self._packet(self._plan("active")).read("modules/W2_0.pdf"))
        self.assertIn("attested by Seed Runner on 2026-08-21", w2)

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
        parcels = [n for n in packet.namelist() if n.startswith("parcels/parcel-application")]
        self.assertEqual(len(parcels), 6)
        for name in parcels:
            page = _text(packet.read(name))
            self.assertIn("did not state that no input materials have been applied", page, name)
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
#: The signed-content hashes those copies print. The signed content holds two row ids
#: (prior_osp_id, corrects_id); these were signed with the plan at id 1 and the corrected
#: revision at id 1 (revision 2) and 2 (revision 3). A re-seed gives the rows new ids, so the
#: database's own re-hash differs while every signed field is unchanged (run 7c, R7-02).
REVISION_2_SIGNED = "1eb204103b5e634263819131b4c8cf0350692cf225a2a3fea47b2a2780d616f0"
REVISION_3_SIGNED = "da2ebd6ba4a802e9afc4ca240dd4bfbe456ff7941d0e1954143e312a56242b92"


def _hash_with_ids(filing, prior_osp_id, corrects_id):
    import json

    content = {**filing.signed_content(), "prior_osp_id": prior_osp_id, "corrects_id": corrects_id}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class Run3SpecimenTests(_Seeded):
    """Run 3 (2026-10-02): R3-01, R3-07 and R3-08 corrected without rewriting history."""

    def _current_02(self):
        """Revision 3 rendered NOW, not its pinned filed bytes: these tests check the renderer, and the
        packet serves the frozen copy (review of back #94). The pin is checked on its own."""
        from certifications.services.osp_module_pdf import render_filing_pdf

        _original, _revision_2, current = self._year(2026, expected=3)
        return _text(render_filing_pdf(current))

    def test_revision_2_keeps_the_bytes_it_was_filed_with(self):
        _original, revision_2, _current = self._year(2026, expected=3)
        self.assertEqual(revision_2.filed_sha256, REVISION_2_SHA256)
        self.assertEqual(hashlib.sha256(bytes(revision_2.filed_pdf)).hexdigest(), REVISION_2_SHA256)
        # The signed hash is the one its frozen copy prints, and the content held here reproduces it
        # once the row ids it was signed under are restored: only the ids differ. The note field
        # joins the hash only when set.
        self.assertEqual(revision_2.correction_note, "")
        self.assertEqual(revision_2.signed_content_sha256, REVISION_2_SIGNED)
        self.assertIn(f"Signed content: sha256 {REVISION_2_SIGNED}", _text(bytes(revision_2.filed_pdf)))
        self.assertEqual(_hash_with_ids(revision_2, 1, 1), REVISION_2_SIGNED)
        # And the hash is over exactly the fields signed before the note existed, so no revision
        # signed earlier moves: the empty note is not in the content at all.
        self.assertNotIn("correction_note", revision_2.signed_content())
        self.assertEqual(set(revision_2.signed_content()), set(OSPAnnualUpdate.SIGNED_FIELDS))
        self.assertIsNotNone(revision_2.superseded_at)

    def test_revision_3_keeps_the_bytes_sent_for_review(self):
        _original, _revision_2, current = self._year(2026, expected=3)
        self.assertEqual(current.filed_sha256, REVISION_3_SHA256)
        self.assertEqual(hashlib.sha256(bytes(current.filed_pdf)).hexdigest(), REVISION_3_SHA256)
        self.assertEqual(current.signed_content_sha256, REVISION_3_SIGNED)
        self.assertIn(f"Signed content: sha256 {REVISION_3_SIGNED}", _text(bytes(current.filed_pdf)))
        self.assertEqual(_hash_with_ids(current, 1, 2), REVISION_3_SIGNED)

    def test_freeze_evidence_passes_on_the_seeded_revisions_and_reports_the_held_payload(self):
        """Review of back #117: the evidence command required the held payload to re-hash to the signed
        hash, so it refused the seeded revisions once the seeder restored the filed signature."""
        import json
        import tempfile

        from django.core.management.base import CommandError

        _original, revision_2, current = self._year(2026, expected=3)
        for filing, signed in ((revision_2, REVISION_2_SIGNED), (current, REVISION_3_SIGNED)):
            with tempfile.NamedTemporaryFile(suffix=".json") as out:
                try:
                    call_command(
                        "osp_freeze_evidence",
                        filing=filing.pk,
                        user_email=OWNER,
                        out=out.name,
                        stdout=io.StringIO(),
                    )
                except CommandError as exc:
                    self.fail(f"revision {filing.revision_number}: {exc}")
                evidence = json.loads(open(out.name).read())
            self.assertTrue(evidence["checks"]["signed_hash_stated_in_filed_copy"])
            self.assertEqual(evidence["before"]["signed_content_sha256_column"], signed)
            held = evidence["held_payload"]
            self.assertEqual(held["recomputes_to_the_signed_hash"], filing.content_sha256() == signed)
            if not held["recomputes_to_the_signed_hash"]:
                self.assertIn("not shown to be the signed content", held["note"])

    def test_the_dossier_prints_the_filed_signed_hash_and_labels_the_held_one_apart(self):
        """Run 7c, R7-02: the dossier printed a re-hash of this database as revision 3's signed hash."""
        from history.models import Production
        from history.services.audit_export_service import AuditExportService
        from history.tests.test_pdf_field_coverage import flowable_text

        _original, _revision_2, current = self._year(2026, expected=3)
        history = (
            Production.objects.filter(parcel__establishment_id=current.establishment_id, name__contains="2026")
            .order_by("pk")
            .first()
        )
        text = flowable_text(AuditExportService(history, certification_type="organic")._build_osp_reference_section())
        self.assertIn(REVISION_3_SIGNED, text)
        held = current.content_sha256()
        if held != REVISION_3_SIGNED:
            self.assertIn(f"sha256 {held}, recomputed from this database. It differs from the signed", text)

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
        # The coming year IS the continuation year (recordkeeping review F-07, 2026-10-07): a
        # 2026 continuation's additions are intended for 2026. The frozen revisions 2 and 3 in
        # the packet still print "(2027)", as filed; this is the re-rendered filing.
        filing = self._current_02()
        self.assertIn("(a)(2) Additions intended for the coming year (2026)", filing)
        self.assertIn("(a)(2) Deletions intended for the coming year (2026)", filing)
        self.assertEqual(filing.count("None stated."), 2)

    def test_the_grandevo_acknowledgment_is_the_operators_account_never_a_record(self):
        packet = self._packet(self._plan("active"))
        notices = _text(packet.read("03-change-notifications.pdf"))
        self.assertIn("no acknowledgment recorded in Trazo", notices)
        self.assertNotIn("not yet acknowledged", notices)
        self.assertIn("that acknowledgment is not recorded with the notification in Trazo", self._current_02())
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


class SpecimenReadsCleanTests(_Seeded):
    """The demo is the packet a certifier is shown, so it carries no contradiction of its own
    (page review of 2026-10-29: the plan named Tsunami 100 while the records logged SaniDate, the
    records logged a 2-3-1 fish fertilizer against a 2-4-1 listing, and every certified parcel read
    "[REVIEW] not accounted for"). The identity-review suggestions those names used to exercise are
    tested on purpose-built rows in `certifications.tests.test_material_identity`."""

    def test_the_packet_prints_no_review_line(self):
        packet = self._packet(self._plan("active"))
        flagged = {
            name: [line for line in _text(packet.read(name)).split("[REVIEW]")[1:]]
            for name in packet.namelist()
            if name.endswith(".pdf") and not name.startswith("annual-update/")
        }
        self.assertEqual({k: v for k, v in flagged.items() if v}, {})

    def test_every_logged_material_is_on_the_plan_with_a_reason(self):
        from certifications.services.plan_materials import plan_materials, unmatched_logged_materials

        plan = self._plan("active")
        self.assertEqual(unmatched_logged_materials(plan), [])
        rows = plan_materials(plan)
        operator_rows = [r for r in rows if r.entry_id is not None]
        self.assertTrue(operator_rows)
        self.assertEqual([r.name for r in operator_rows if not r.reason], [])
        # A listed product the operator entered folds into its listing: never printed twice.
        names = [r.name.lower() for r in rows]
        self.assertEqual(len(names), len(set(names)), names)

    def test_every_certified_parcel_window_is_accounted_for(self):
        from certifications.services.parcel_land_history import coverage, prior_manager_rows
        from product.models import Parcel

        for parcel in Parcel.objects.filter(establishment__name="Calapooia Bend Farm"):
            with self.subTest(parcel=parcel.name):
                self.assertTrue(coverage(parcel, prior_manager_rows(parcel)).complete)

    def test_nothing_is_decided_for_the_operator(self):
        from certifications.models import MaterialIdentityDecision
        from certifications.services.material_identity import identities

        identities(self._plan("active"))
        self.assertFalse(MaterialIdentityDecision.objects.exists())


class QuestionIndexSpecimenTests(_Seeded):
    """Phase 5 slice 4 (T24): 06-question-index.pdf, read back against the packet it indexes."""

    AGENTS = {
        "otco": "Oregon Tilth Certified Organic",
        "ccof": "CCOF",
        "wsda": "Washington State Department of Agriculture",
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from certifications.models import OrganicSystemPlan
        from certifications.services.osp_module_pdf import generate_osp_packet
        from certifications.services.packet_index_recorder import recording

        cls.osp = OrganicSystemPlan.objects.filter(status="active").order_by("-version_number").first()
        cls.original_agent = cls.osp.certifier_name
        cls.built = {}
        for slug, name in list(cls.AGENTS.items()) + [("fallback", cls.original_agent)]:
            cls.osp.certifier_name = name
            cls.osp.save(update_fields=["certifier_name"])
            with recording() as recorder:
                data = generate_osp_packet(cls.osp)
            cls.built[slug] = (data, recorder.index)
        cls.osp.certifier_name = cls.original_agent
        cls.osp.save(update_fields=["certifier_name"])

    _page_cache: dict = {}

    def _pages(self, data, path):
        """A packet file's page texts; `data` is the packet ZIP's bytes."""
        import zipfile

        from certifications.services.question_index import page_texts

        key = (hash(data), path)
        if key not in self._page_cache:
            self._page_cache[key] = page_texts(zipfile.ZipFile(io.BytesIO(data)).read(path))
        return self._page_cache[key]

    def _as(self, slug):
        self.osp.certifier_name = self.AGENTS[slug]
        return self.osp

    def _printed_check(self, data):
        """The check the packet build hands 04, read from the built ZIP (`printed_locations`)."""
        import types
        import zipfile

        from certifications.services.question_index import printed_locations

        archive = zipfile.ZipFile(io.BytesIO(data))
        recorder = types.SimpleNamespace(
            documents={name: archive.read(name) for name in archive.namelist() if name.endswith(".pdf")},
            filed=set(),
        )
        texts: dict = {}
        return lambda item: bool(printed_locations(item, recorder, texts))

    def test_every_answered_location_cites_a_page_carrying_its_label(self):
        checked = 0
        for slug in self.AGENTS:
            data, index = self.built[slug]
            for form in index.forms:
                for row in form.rows:
                    for loc in row.locations:
                        if loc.kind != "answer" or not (loc.page and loc.label):
                            continue
                        text = self._pages(data, loc.file)[loc.page - 1]
                        self.assertIn(" ".join(loc.label.split()).lower(), text, (slug, row.ref, loc))
                        checked += 1
        self.assertGreater(checked, 50, "too few located answers to mean anything")

    def test_cited_headings_resolve_to_the_page_carrying_them_including_filed_documents(self):
        from certifications.services.question_index import FILED_NOTE

        found, filed = 0, 0
        for slug in self.AGENTS:
            data, index = self.built[slug]
            for form in index.forms:
                for row in form.rows:
                    for loc in row.locations:
                        if loc.kind != "heading":
                            continue
                        text = self._pages(data, loc.file)[loc.page - 1]
                        self.assertIn(" ".join(loc.section.split()).lower(), text, (slug, row.ref, loc))
                        found += 1
                        if loc.note == FILED_NOTE:
                            self.assertTrue(loc.file.startswith("annual-update/") or loc.file == "02-annual-update.pdf")
                            filed += 1
        self.assertGreater(found, 0, "no cited heading was located")
        self.assertGreater(filed, 0, "no heading was located in a filed document")

    def test_each_parcel_is_named_with_its_location_or_open_state(self):
        """Every parcel in the packet is named on every per-parcel row, by its page or its open state;
        the parcel list comes from the packet, not from the states being checked."""
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
        from certifications.services.certifier_register import load_forms
        from certifications.services.osp_module_pdf import _packet_parcels
        from certifications.services.packet_answers import form_answer_states

        parcels = {p.name for p in _packet_parcels(self.osp.establishment)}
        self.assertGreater(len(parcels), 1, "the specimen has one parcel; this test needs several")
        prefix = PARCEL_APPLICATION.key + "."
        rows_checked = na_rows = 0
        for slug in self.AGENTS:
            _data, index = self.built[slug]
            forms = load_forms(slug)
            states = form_answer_states(self._as(slug), forms)
            by_ref = {(f.label, s.ref): s for f in forms for s in states.get(id(f), [])}
            for form in index.forms:
                for row in form.rows:
                    state = by_ref[(form.label, row.ref)]
                    parts = [p for p in state.parts if p[0].startswith(prefix)]
                    if not parts:
                        continue
                    na_rows += any(p[2] == "not_applicable" for p in parts)
                    rows_checked += 1
                    named = {loc.parcel for loc in row.locations} | {part.parcel for part in row.open_parts}
                    self.assertLessEqual(parcels, named, (slug, form.label, row.ref))
        self.assertGreater(rows_checked, 0, "no per-parcel row on the specimen")
        self.assertGreater(na_rows, 0, "no per-parcel row with a part that does not apply (run 6, R6-01)")

    def test_route_states_carry_their_reasons(self):
        for slug in self.AGENTS:
            _data, index = self.built[slug]
            for form in index.forms:
                for row in form.rows:
                    for part in row.open_parts:
                        if part.state in ("not_on_route", "route_unresolved"):
                            self.assertTrue(part.detail, (slug, row.ref, part))

    def test_open_rows_are_the_coverage_pages_open_rows(self):
        from certifications.services.packet_answers import CLOSED_STATES
        from certifications.services.packet_coverage import form_coverage

        compared = 0
        for slug in self.AGENTS:
            data, index = self.built[slug]
            coverage = {c.form: c for c in form_coverage(self._as(slug), slug, self._printed_check(data))}
            for form in index.forms:
                if form.label not in coverage:
                    continue
                entry = coverage[form.label]
                page04 = [r.ref for r in entry.open_rows + entry.optional_open_rows]
                # A covered row with no answering question that the register places in the packet is
                # not closed, and not open either: both pages name it apart (OV-PK-C04, O06, W06).
                printed04 = [ref for ref, _where in entry.printed_rows]
                ours = [r.ref for r in form.rows if r.state not in CLOSED_STATES and r.open_parts]
                printed_ours = [r.ref for r in form.rows if r.state not in CLOSED_STATES and not r.open_parts]
                self.assertEqual(sorted(ours), sorted(page04), (slug, form.label))
                self.assertEqual(sorted(printed_ours), sorted(printed04), (slug, form.label))
                compared += 1
        self.assertGreater(compared, 10)

    def test_a_row_the_packet_prints_is_named_apart_never_still_open(self):
        """OV-PK-C04, O06, W06: 04 listed these as "Still open ... not checked against this plan's
        answers", under a heading telling the grower the agent's own form was needed for them, and
        06 printed the same, while the packet printed them (the cover's legal name, address,
        certificate). A row is named printed only where every heading it cites is in the built bytes
        (review of back #518)."""
        from certifications.services.packet_answers import CLOSED_STATES, stated_in_packet
        from certifications.services.packet_coverage import form_coverage
        from certifications.services.question_index import _cited_headings

        printed_seen = 0
        for slug in self.AGENTS:
            data, index = self.built[slug]
            page04 = " ".join(self._pages(data, "04-coverage-and-scope.pdf"))
            rows06 = {(f.label, r.ref): r for f in index.forms for r in f.rows}
            coverage = form_coverage(self._as(slug), slug, self._printed_check(data))
            for entry in coverage:
                if not entry.printed_rows:
                    continue
                # Never closed, so never what makes a form answered (OSP alignment audit T15).
                self.assertNotEqual(entry.standing, "answered", (slug, entry.form))
                for ref, where in entry.printed_rows:
                    printed_seen += 1
                    self.assertNotIn(ref, [r.ref for r in entry.open_rows + entry.optional_open_rows])
                    row = rows06[(entry.form, ref)]
                    self.assertNotIn(row.state, CLOSED_STATES, (slug, ref))
                    self.assertEqual(row.open_parts, [], (slug, ref, row.open_parts))
                    self.assertTrue(row.locations, (slug, ref))
                    item = next(i for i in self._register_items(slug, entry.form) if i.ref == ref)
                    cited = _cited_headings(" ".join(str(getattr(item, "prints", "") or "").split()))
                    self.assertTrue(cited, (slug, ref, "named printed with no heading to find"))
                    for path, heading in cited:
                        pages = " ".join(self._pages(data, path))
                        self.assertIn(" ".join(heading.split()).lower(), pages, (slug, ref, path, heading))
            # 04 names rows only under forms it answers in part; a form filed with the agent lists none.
            if any(e.printed_rows for e in coverage if e.standing == "in_part"):
                self.assertIn("printed from your records, not checked against this plan's answers", page04, slug)
            # A stated location the packet does not show stays open: CCOF ORGB41 F and G name facility
            # pest tables this specimen has no rows for, and a register row citing no heading cannot be
            # read back at all (review of back #518).
            for entry in coverage:
                for row in entry.open_rows + entry.optional_open_rows:
                    item = next((i for i in self._register_items(slug, entry.form) if i.ref == row.ref), None)
                    if row.state == "not_assessed" and stated_in_packet(item):
                        unshown = not _cited_headings(" ".join(str(getattr(item, "prints", "") or "").split()))
                        self.assertIn((entry.form, row.ref), rows06, (slug, row.ref))
                        self.assertTrue(rows06[(entry.form, row.ref)].open_parts or not unshown, (slug, row.ref))
        self.assertGreater(printed_seen, 5, "too few printed rows on the specimen to mean anything")

    def _register_items(self, slug, form_label):
        from certifications.services.certifier_register import load_forms

        return next(f.items for f in load_forms(slug) if f.label == form_label)

    def test_facility_pest_rows_with_no_table_stay_open(self):
        """Review of back #518: ORGB41 F and G point at facility pest tables that print only when the
        farm has facility pest rows. The specimen has none, so they stay open on 04 and 06."""
        from certifications.services.packet_coverage import form_coverage

        data, index = self.built["ccof"]
        coverage = form_coverage(self._as("ccof"), "ccof", self._printed_check(data))
        orgb41 = next(e for e in coverage if e.document_id == "ORGB41")
        self.assertFalse({"F", "G"} & {ref for ref, _w in orgb41.printed_rows}, orgb41.printed_rows)
        open_refs = {r.ref for r in orgb41.open_rows + orgb41.optional_open_rows}
        self.assertTrue({"F", "G"} <= open_refs, open_refs)
        rows06 = {r.ref: r for f in index.forms if f.document_id == "ORGB41" for r in f.rows}
        self.assertTrue(rows06["F"].open_parts and rows06["G"].open_parts)

    def test_forms_follow_the_agents_order_and_rows_the_registers(self):
        from certifications.services.certifier_register import load_forms, load_published_inventory

        for slug in self.AGENTS:
            _data, index = self.built[slug]
            published = [f.document_id for f in load_published_inventory(slug)]
            positions = [published.index(f.document_id) for f in index.forms if f.document_id in published]
            self.assertEqual(positions, sorted(positions), slug)
            register = {f.label: [i.ref for i in f.items] for f in load_forms(slug)}
            self.assertEqual(sorted(f.label for f in index.forms), sorted(register), slug)
            for form in index.forms:
                refs = [r.ref for r in form.rows]
                self.assertEqual(refs, [r for r in register[form.label] if r in refs], (slug, form.label))
        otco = [f.document_id for f in self.built["otco"][1].forms]
        self.assertLess(otco.index("C2"), otco.index("C11"))

    def test_an_umbrella_form_precedes_its_sections_and_the_order_names_its_source(self):
        """Run 6, R6-04."""
        _data, index = self.built["wsda"]
        labels = [f.label for f in index.forms]
        umbrella = next(i for i, label in enumerate(labels) if "Crop Producer Organic System Plan" in label)
        section_a = next(i for i, label in enumerate(labels) if label.endswith("A Seeds") or " A Seeds" in label)
        self.assertLess(umbrella, section_a, labels[:6])
        for slug in self.AGENTS:
            data, _index = self.built[slug]
            first = self._pages(data, "06-question-index.pdf")[0]
            self.assertIn("forms are in trazo's registered order, taken from the agent's forms list at http", first)
            self.assertNotIn("the agent's order", first)

    def test_a_document_that_does_not_name_the_form_is_only_related(self):
        """Run 6, R6-04: "Form named in" only with a page whose text names the form."""
        seen_related = 0
        for slug in self.AGENTS:
            data, index = self.built[slug]
            text = " ".join(self._pages(data, "06-question-index.pdf"))
            for form in index.forms:
                for loc in form.locations:
                    if loc.page is None and not loc.file.startswith("workbooks/"):
                        seen_related += 1
            self.assertNotIn("form located in", text)
            if seen_related:
                self.assertIn("related packet document", text)
        self.assertGreater(seen_related, 0)

    def test_a_fallback_agent_gets_a_page_and_no_rows(self):
        from certifications.services.question_index import NO_REGISTER

        data, index = self.built["fallback"]
        self.assertFalse(index.has_register)
        self.assertEqual(index.forms, [])
        self.assertIn(" ".join(NO_REGISTER.split()).lower(), self._pages(data, "06-question-index.pdf")[0])

    def test_no_entry_says_a_question_is_met(self):
        """Trazo's own words in the index (everything but the forms' and register's quoted text) never
        say a question is met."""
        from certifications.services.question_index import _state_words

        words = ("compliant", "satisfied", "accepted", "verified", "approved", "complete")
        for slug in self.AGENTS:
            _data, index = self.built[slug]
            ours = [
                "Answered at",
                "Cited heading found at",
                "Form named in",
                "Related packet document",
                "No location recorded in this packet.",
            ]
            for form in index.forms:
                ours += [loc.note for loc in form.locations]
                for row in form.rows:
                    ours += [loc.note for loc in row.locations] + [_state_words(p.state) for p in row.open_parts]
            for text in ours:
                for word in words:
                    self.assertNotIn(word, (text or "").lower(), (slug, text))


class QuestionLabelPageBreakTests(TestCase):
    def test_a_label_pushed_to_the_next_page_records_that_page(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        from certifications.services.packet_index_recorder import QuestionLabel, document, recording
        from certifications.services.question_index import page_texts

        style = getSampleStyleSheet()["BodyText"]
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        # Fill page 1 so the label itself would still fit but its first answer line would not.
        story = [
            Spacer(1, doc.height - 30),
            QuestionLabel(
                "<b>Unique label for the page break</b>",
                style,
                anchor=("m", "q", "S", "Unique label for the page break"),
            ),
            Paragraph("The answer, long enough to need its own lines. " * 3, style),
        ]
        with recording() as recorder, document("x.pdf"):
            doc.build(story)
        texts = page_texts(buffer.getvalue())
        self.assertEqual([loc.page for loc in recorder.labels], [2])
        self.assertIn("unique label for the page break", texts[1])
        self.assertNotIn("unique label for the page break", texts[0])


class IndexRowMixedPartsTests(TestCase):
    """Run 6, R6-01: one row, three parcels, three states. Every parcel is named; the one that does not
    apply says why, in the reader's words; the register's placeholder does not stand in for them."""

    def test_answered_unresolved_and_not_applicable_parcels_are_all_named(self):
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
        from certifications.services.packet_answers import RowState
        from certifications.services.packet_index_recorder import LabelLocation, Recorder
        from certifications.services.question_index import index_row

        # The treated-lumber detail, which the row below (A10a) is about. "The first gated question" was a
        # proxy for it until page A gained radio-gated location questions, whose trigger is not a boolean.
        page, question = next(
            (p, q) for p in PARCEL_APPLICATION.pages for q in p.questions if q.key == "treated_lumber_description"
        )
        trigger = question.visible_when[0].question
        key = f"{PARCEL_APPLICATION.key}.{question.key}"
        recorder = Recorder()
        recorder.parcel_files = {"parcels/parcel-application-north.pdf": "North"}
        recorder.labels.append(
            LabelLocation("parcels/parcel-application-north.pdf", 2, PARCEL_APPLICATION.key, question.key, "S", "Label")
        )
        state = RowState(
            "A10a",
            "unresolved",
            parts=(
                (key, "North", "answered", ""),
                (
                    key,
                    "South",
                    "route_unresolved",
                    "the route is not determined: the parcel's prior certifying agent is not named",
                ),
                (key, "West", "not_applicable", f"{trigger} = {False!r}"),
            ),
        )
        item = type(
            "Item", (), {"asks": "Treated lumber details", "prints": "parcels/parcel-application-<name>.pdf §A"}
        )
        row = index_row(state, item, recorder, None, {})
        self.assertEqual([loc.parcel for loc in row.locations], ["North"])
        by_parcel = {p.parcel: p for p in row.open_parts}
        self.assertEqual(set(by_parcel), {"South", "West"})
        self.assertEqual(by_parcel["West"].state, "not_applicable")
        self.assertIn("answered No", by_parcel["West"].detail)
        self.assertNotIn(f"{trigger} =", by_parcel["West"].detail, "the trigger printed as a raw key")
        self.assertEqual(row.register_prints, "", "the register placeholder stood in for decided parcels")

    def test_identical_explanations_print_once_per_parcel(self):
        """Run 6b polish: two register questions decided by one trigger give one line per parcel."""
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
        from certifications.services.packet_answers import RowState
        from certifications.services.packet_index_recorder import Recorder
        from certifications.services.question_index import index_row

        questions = [q for p in PARCEL_APPLICATION.pages for q in p.questions if q.visible_when][:2]
        trigger = questions[0].visible_when[0].question
        parts = tuple(
            (f"{PARCEL_APPLICATION.key}.{q.key}", name, "not_applicable", f"{trigger} = {False!r}")
            for q in questions
            for name in ("North", "South")
        )
        row = index_row(RowState("12a", "not_applicable", parts=parts), None, Recorder(), None, {})
        self.assertEqual(sorted(p.parcel for p in row.open_parts), ["North", "South"])

    def test_a_row_that_applies_to_no_parcel_names_each_and_shows_no_placeholder(self):
        """The A10a case: every parcel answered the trigger No, so nothing is located anywhere."""
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
        from certifications.services.packet_answers import RowState
        from certifications.services.packet_index_recorder import Recorder
        from certifications.services.question_index import index_row

        question = next(q for p in PARCEL_APPLICATION.pages for q in p.questions if q.visible_when)
        key = f"{PARCEL_APPLICATION.key}.{question.key}"
        trigger = question.visible_when[0].question
        state = RowState(
            "A10a",
            "not_applicable",
            parts=tuple((key, name, "not_applicable", f"{trigger} = {False!r}") for name in ("North", "South")),
        )
        item = type(
            "Item", (), {"asks": "Treated lumber details", "prints": "parcels/parcel-application-<name>.pdf §A"}
        )
        row = index_row(state, item, Recorder(), None, {})
        self.assertEqual(row.locations, [])
        self.assertEqual({p.parcel for p in row.open_parts}, {"North", "South"})
        self.assertEqual(row.register_prints, "", "the register placeholder stood in for a decided question")

    def test_a_multi_choice_trigger_prints_its_option_labels(self):
        """Run 6b check: "answered ['on_farm_compost', ...]" printed stored keys; the reader gets the
        labels the module PDF prints."""
        from certifications.osp_modules import MODULE_REGISTRY
        from certifications.services.osp_module_pdf import _en
        from certifications.services.question_index import _trigger_words

        found = None
        for module in MODULE_REGISTRY:
            questions = {q.key: q for p in module.pages for q in p.questions}
            for q in questions.values():
                for cond in q.visible_when:
                    trigger = questions.get(cond.question)
                    options = getattr(trigger, "options", None) or ()
                    labelled = [o for o in options if o.value and o.value != _en(o.label)]
                    if trigger is not None and trigger.kind == "checkbox_group" and len(labelled) >= 2:
                        found = (module, q, trigger, labelled[:2])
                        break
                if found:
                    break
            if found:
                break
        self.assertIsNotNone(found, "no multi-choice trigger in the registry to test against")
        module, question, trigger, options = found
        detail = f"{trigger.key} = {[o.value for o in options]!r}"
        text = _trigger_words(f"{module.key}.{question.key}", detail)
        self.assertNotIn("[", text, text)
        for option in options:
            self.assertNotIn(f"'{option.value}'", text, text)
            self.assertIn(_en(option.label), text, "the option's label did not print")
