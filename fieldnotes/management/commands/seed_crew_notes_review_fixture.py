"""Seed (or remove) a small, clearly fictional set of crew field notes for a review of the inbox.

A reviewer auditing the crew notes screen (the inbox, confirming a note into a record, the refused
list, provenance on the confirmed record) needs notes to look at, and the only way a note arrives in
production is a signed WhatsApp delivery from a rostered phone. This command writes the rows that
delivery would have written, for ONE disposable test company, and nothing more.

What it writes, in one transaction (every name, phone and message is marked "ASTRA TEST"):

  * two `CrewSender` roster rows on the company's single farm, with phones from the NANP fictional
    range (+1 509 555 0101 and 0102). Consent is stamped the way the roster API stamps it
    (`consent_attested_at` now, `consent_attested_by` and `added_by` the attesting member). The
    attestation is about fictional people and says so by their names.
    `first_contact_at` and `consented_at` stay empty: those record a notice actually sent to the
    phone, and nothing is sent.
  * five `FieldNote` rows, text only, in the shape the webhook writes them (provider `twilio`,
    message ids `ASTRATEST-CREWNOTE-01` to `05`):
      01 pending   "Sprayed Entrust 6 fl oz per acre on South Block for codling moth (ASTRA TEST)"
      02 pending   "Cosechamos 30 bins de Gala en el bloque sur (ASTRA TEST)"
      03 pending   "No fumigamos hoy, mucho viento (ASTRA TEST)"
      04 pending   "Fixed the leak in the drip line (ASTRA TEST)"   (no date, no block)
      05 refused   empty message, `refusal_reason="empty_message"` (what the webhook writes for a
                   rostered sender whose message had no words)
  * one `DataOperationLog` row.

Why the refused note comes from a consented sender: an unrostered, unconsented or STOP'd number
gets silence at the webhook and NO row at all, on purpose (a reply or a row would confirm the line
is live). A refusal row only exists for a rostered sender whose message could not be read, so that
is the state seeded here.

What it never does: audio (a voice note needs a real provider media reference, and playback would
call the provider), confirmations or records (the reviewer confirms), outbound replies, the
first-contact notice, arrival notifications, email, review links, publications, or any call to the
provider API. Rows are created directly, so the webhook's `on_commit` hooks never run.

Refusals (nothing is written):
  * no such company, or its name does not start with "ASTRA" and contain "test"
  * its plan is not `pilot` or `starter`
  * it does not have exactly one farm
  * no attesting member: `--attested-by` must be a Company Admin or Farm Manager of the company;
    without it the company must have exactly one such member
  * any fixture row (fixture phone or message id) already exists and is not exactly what this
    command writes, in this company. An identical rerun is a no-op that prints the ids and runs the
    checks again.

`--remove` deletes only the fixture rows (the notes, any machine parses the wizard stored for them,
and the two roster rows). It refuses while any fixture note was confirmed into a record, or while a
fixture phone has notes this command did not write.

Usage:

    poetry run python manage.py seed_crew_notes_review_fixture --company-id 17
    poetry run python manage.py seed_crew_notes_review_fixture --company-id 17 --commit --run-by oscar
    poetry run python manage.py seed_crew_notes_review_fixture --company-id 17 --remove
    poetry run python manage.py seed_crew_notes_review_fixture --company-id 17 --remove --commit --run-by oscar
"""

import hashlib
import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

MARKER = "ASTRA TEST"
OPERATION = "seed_crew_notes_review_fixture"
REMOVE_OPERATION = "remove_crew_notes_review_fixture"
ALLOWED_PLANS = ("pilot", "starter")
MESSAGE_ID_PREFIX = "ASTRATEST-CREWNOTE-"

# 555-0100 to 555-0199 is the NANP range reserved for fiction; 509 is central Washington.
SENDERS = (
    {"key": "en", "phone": "+15095550101", "name": "ASTRA TEST Sam (fictional crew)", "language": "en-US"},
    {"key": "es", "phone": "+15095550102", "name": "ASTRA TEST Lupe (cuadrilla ficticia)", "language": "es-419"},
)
SENDER_PHONES = tuple(s["phone"] for s in SENDERS)

# (number, sender key, words, status, refusal reason, minutes before the run)
NOTES = (
    ("01", "en", "Sprayed Entrust 6 fl oz per acre on South Block for codling moth (ASTRA TEST)", "pending", "", 190),
    ("02", "es", "Cosechamos 30 bins de Gala en el bloque sur (ASTRA TEST)", "pending", "", 150),
    ("03", "es", "No fumigamos hoy, mucho viento (ASTRA TEST)", "pending", "", 110),
    ("04", "en", "Fixed the leak in the drip line (ASTRA TEST)", "pending", "", 70),
    ("05", "en", "", "refused", "empty_message", 30),
)


def _message_id(number):
    return f"{MESSAGE_ID_PREFIX}{number}"


EXPECTED_MESSAGE_IDS = frozenset(_message_id(n[0]) for n in NOTES)


class Command(BaseCommand):
    help = "Seed or remove fictional crew field notes in one ASTRA test company (dry run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, required=True, help="The disposable ASTRA test company.")
        parser.add_argument(
            "--attested-by",
            default="",
            help="Email of the Company Admin or Farm Manager recorded as attesting consent "
            "(optional when the company has exactly one).",
        )
        parser.add_argument("--remove", action="store_true", help="Remove the fixture instead of seeding it.")
        parser.add_argument("--commit", action="store_true", help="Actually write. Without it nothing is saved.")
        parser.add_argument("--run-by", default="", help="Who ran it (stored on the DataOperationLog row).")

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        from company.models import Company

        company = Company.objects.filter(pk=options["company_id"]).first()
        if company is None:
            raise CommandError(f"No company with id {options['company_id']}. Nothing written.")
        self._refuse_unless_test_company(company)

        if options["remove"]:
            return self._remove(company, options)
        return self._seed(company, options)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def _refuse_unless_test_company(company):
        name = company.name or ""
        if not name.startswith("ASTRA") or "test" not in name.lower():
            raise CommandError(
                f"Company {company.pk} '{name}' is not an ASTRA test company (the name must start with "
                "'ASTRA' and contain 'Test'). This command never touches a grower. Nothing written."
            )
        subscription = getattr(company, "subscription", None)
        slug = subscription.plan.slug if subscription is not None and subscription.plan_id else None
        if slug not in ALLOWED_PLANS:
            raise CommandError(
                f"Company {company.pk} '{name}' is on plan {slug!r}, not one of {', '.join(ALLOWED_PLANS)}. "
                "Nothing written."
            )

    @staticmethod
    def _single_farm(company):
        from company.models import Establishment

        farms = list(Establishment.objects.filter(company=company))
        if len(farms) != 1:
            raise CommandError(
                f"Company {company.pk} '{company.name}' has {len(farms)} farms; the fixture needs exactly 1. "
                "Nothing written."
            )
        return farms[0]

    @staticmethod
    def _attester(company, email):
        from users.models import WorksIn

        writers = WorksIn.objects.filter(
            company=company, role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER]
        ).select_related("user")
        if email:
            row = writers.filter(user__email__iexact=email.strip()).first()
            if row is None:
                raise CommandError(
                    f"{email} is not a Company Admin or Farm Manager of company {company.pk}, so it cannot be "
                    "recorded as attesting consent. Nothing written."
                )
            return row.user
        users = {row.user_id: row.user for row in writers}
        if len(users) != 1:
            emails = ", ".join(sorted(u.email for u in users.values())) or "none"
            raise CommandError(
                f"Company {company.pk} has {len(users)} Company Admins / Farm Managers ({emails}). "
                "Pass --attested-by <email> to say who attests consent. Nothing written."
            )
        return next(iter(users.values()))

    # ------------------------------------------------------------------
    # Seed
    # ------------------------------------------------------------------

    def _seed(self, company, options):
        farm = self._single_farm(company)
        attester = self._attester(company, options["attested_by"])

        existing = self._existing_fixture(company, farm)
        if existing is not None:
            senders, notes = existing
            self.stdout.write(self.style.SUCCESS("Fixture already in place; nothing written."))
            self._print_ids(company, farm, senders, notes)
            self._verify(company, attester)
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"Crew notes review fixture for {company.name} (id {company.pk})"))
        self.stdout.write(f"  Farm        : {farm.name} (id {farm.pk})")
        self.stdout.write(f"  Consent by  : {attester.email}")
        for sender in SENDERS:
            self.stdout.write(f"  Roster      : {sender['name']}  {sender['phone']}  {sender['language']}")
        for number, key, words, status, reason, _minutes in NOTES:
            text = words or "(empty message)"
            suffix = f" [{reason}]" if reason else ""
            self.stdout.write(f"  Note {number}     : {status:<8} {key}  {text}{suffix}")
        self.stdout.write("  Not created : audio, confirmations, records, replies, notifications, email, review links")

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN: nothing written. Re-run with --commit."))
            return

        senders, notes = self._create(company, farm, attester, options["run_by"])
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Fixture seeded."))
        self._print_ids(company, farm, senders, notes)
        self._verify(company, attester)

    def _create(self, company, farm, attester, run_by):
        from common.models import DataOperationLog
        from company.models import Company
        from fieldnotes.models import CrewSender, FieldNote

        now = timezone.now()
        with transaction.atomic():
            # Serialise concurrent runs on the company row, then re-read the state under the lock.
            Company.objects.select_for_update().get(pk=company.pk)
            if self._fixture_rows_anywhere():
                raise CommandError("Fixture rows appeared while this ran. Nothing written; re-run.")

            latest = {}
            for number, key, _words, _status, _reason, minutes in NOTES:
                at = now - timedelta(minutes=minutes)
                latest[key] = max(latest.get(key, at), at)

            senders = {}
            for spec in SENDERS:
                # The same stamps CrewSenderSerializer.create writes. `first_contact_at` and
                # `consented_at` are left empty: they record a notice sent to the phone.
                senders[spec["key"]] = CrewSender.objects.create(
                    company=company,
                    establishment=farm,
                    phone_e164=spec["phone"],
                    display_name=spec["name"],
                    language=spec["language"],
                    is_active=True,
                    consent_attested_at=now,
                    consent_attested_by=attester,
                    added_by=attester,
                    last_note_at=latest.get(spec["key"]),
                )

            notes = []
            for number, key, words, status, reason, minutes in NOTES:
                sender = senders[key]
                # The fields the webhook writes, and no others.
                notes.append(
                    FieldNote.objects.create(
                        company=company,
                        establishment=sender.filing_establishment,
                        sender=sender,
                        sender_phone=sender.phone_e164,
                        sender_display_name=sender.display_name,
                        provider=FieldNote.TWILIO,
                        provider_message_id=_message_id(number),
                        kind=FieldNote.TEXT,
                        body_text=words,
                        status=status,
                        refusal_reason=reason,
                        received_at=now - timedelta(minutes=minutes),
                    )
                )

            record = {
                "company": company.pk,
                "establishment": farm.pk,
                "attested_by": attester.pk,
                "crew_senders": sorted(s.pk for s in senders.values()),
                "field_notes": sorted(n.pk for n in notes),
            }
            DataOperationLog.objects.create(
                operation=OPERATION,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=self._sha(record),
                counts={"crew_sender": len(senders), "field_note": len(notes), "ids": record},
                run_by=run_by,
            )
        return list(senders.values()), notes

    @staticmethod
    def _fixture_rows_anywhere():
        from fieldnotes.models import CrewSender, FieldNote

        return (
            CrewSender.objects.filter(phone_e164__in=SENDER_PHONES).exists()
            or FieldNote.objects.filter(provider_message_id__startswith=MESSAGE_ID_PREFIX).exists()
        )

    def _existing_fixture(self, company, farm):
        """(senders, notes) when exactly this fixture is in place; None when no fixture row exists.

        Anything in between refuses: a partial fixture, a fixture someone has acted on (a discarded,
        acknowledged or confirmed note), or fixture phones or message ids in another company.
        """
        from fieldnotes.models import CrewSender, FieldNote

        senders = list(CrewSender.objects.filter(phone_e164__in=SENDER_PHONES).order_by("phone_e164"))
        notes = list(
            FieldNote.objects.filter(provider_message_id__startswith=MESSAGE_ID_PREFIX).order_by("provider_message_id")
        )
        if not senders and not notes:
            return None

        problems = []
        if any(s.company_id != company.pk for s in senders) or any(n.company_id != company.pk for n in notes):
            problems.append("fixture phones or message ids exist in another company")

        by_phone = {s.phone_e164: s for s in senders}
        spec_by_key = {}
        for spec in SENDERS:
            row = by_phone.get(spec["phone"])
            spec_by_key[spec["key"]] = row
            if row is None:
                problems.append(f"roster row {spec['phone']} is missing")
                continue
            if (
                row.display_name != spec["name"]
                or row.language != spec["language"]
                or row.establishment_id != farm.pk
                or not row.may_send
                or row.first_contact_at is not None
                or row.consented_at is not None
            ):
                problems.append(f"roster row {spec['phone']} (id {row.pk}) was changed")

        by_id = {n.provider_message_id: n for n in notes}
        if set(by_id) != EXPECTED_MESSAGE_IDS:
            problems.append(f"fixture notes are {sorted(by_id)}, expected {sorted(EXPECTED_MESSAGE_IDS)}")
        for number, key, words, status, reason, _minutes in NOTES:
            note = by_id.get(_message_id(number))
            if note is None:
                continue
            sender = spec_by_key.get(key)
            if (
                note.body_text != words
                or note.status != status
                or note.refusal_reason != reason
                or note.kind != FieldNote.TEXT
                or sender is None
                or note.sender_id != sender.pk
            ):
                problems.append(f"note {note.provider_message_id} (id {note.pk}) is now '{note.status}' or was changed")

        if problems:
            raise CommandError(
                "Crew notes fixture rows already exist and are not exactly what this command writes: "
                + "; ".join(problems)
                + ". Nothing written. Run with --remove first if they should be replaced."
            )
        return senders, notes

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    def _remove(self, company, options):
        from common.models import DataOperationLog
        from fieldnotes.models import CrewSender, FieldNote, FieldNoteConfirmation, FieldNoteExtraction

        notes = list(
            FieldNote.objects.filter(company=company, provider_message_id__startswith=MESSAGE_ID_PREFIX).order_by(
                "provider_message_id"
            )
        )
        senders = list(CrewSender.objects.filter(company=company, phone_e164__in=SENDER_PHONES))
        if not notes and not senders:
            self.stdout.write(f"No crew notes fixture rows in company {company.pk}. Nothing to remove.")
            return

        problems = []
        # A confirmed note is the provenance of a record: the record's dossier and the append-only
        # confirmation history both name it. Deleting it would orphan that trail, so refuse and list.
        for confirmation in FieldNoteConfirmation.objects.filter(note__in=notes).select_related("note"):
            state = "voided" if confirmation.voided_at else "current"
            problems.append(
                f"note {confirmation.note.provider_message_id} was confirmed into record "
                f"{confirmation.event_type}:{confirmation.event_id} ({state})"
            )
        for note in notes:
            if note.status == FieldNote.CONFIRMED or note.fulfilled_by_id is not None:
                problems.append(
                    f"note {note.provider_message_id} is '{note.status}' and links record "
                    f"{note.fulfilled_by_event_type}:{note.fulfilled_by_id}"
                )
        foreign = FieldNote.objects.filter(sender__in=senders).exclude(
            provider_message_id__startswith=MESSAGE_ID_PREFIX
        )
        if foreign.exists():
            problems.append(f"the fixture phones have {foreign.count()} notes this command did not write")
        if problems:
            raise CommandError(
                "The crew notes fixture is referenced by real records or messages: "
                + "; ".join(dict.fromkeys(problems))
                + ". Nothing removed. Delete those records in the app first (that requeues the note)."
            )

        extractions = FieldNoteExtraction.objects.filter(note__in=notes).count()
        self.stdout.write(f"Would remove from company {company.pk} '{company.name}':")
        for note in notes:
            self.stdout.write(f"  note   {note.provider_message_id} (id {note.pk}, {note.status})")
        for sender in senders:
            self.stdout.write(f"  roster {sender.display_name} {sender.phone_e164} (id {sender.pk})")
        self.stdout.write(f"  stored machine parses of those notes: {extractions}")
        if not options["commit"]:
            self.stdout.write(self.style.WARNING("DRY RUN: nothing removed. Re-run with --commit."))
            return

        with transaction.atomic():
            record = {
                "company": company.pk,
                "field_notes": sorted(n.pk for n in notes),
                "crew_senders": sorted(s.pk for s in senders),
            }
            _, deleted_notes = FieldNote.objects.filter(pk__in=record["field_notes"]).delete()
            _, deleted_senders = CrewSender.objects.filter(pk__in=record["crew_senders"]).delete()
            deleted = {**deleted_notes, **deleted_senders}
            DataOperationLog.objects.create(
                operation=REMOVE_OPERATION,
                action=DataOperationLog.ACTION_APPLY,
                report_sha256=self._sha(record),
                counts={"deleted": deleted, "ids": record},
                run_by=options["run_by"],
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {len(record['field_notes'])} notes and {len(record['crew_senders'])} roster rows."
            )
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _sha(record):
        return hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest()

    def _print_ids(self, company, farm, senders, notes):
        self.stdout.write(f"  company id  : {company.pk}")
        self.stdout.write(f"  farm id     : {farm.pk}")
        for sender in senders:
            self.stdout.write(f"  roster id   : {sender.pk}  {sender.phone_e164}")
        for note in notes:
            self.stdout.write(f"  note        : {note.provider_message_id}  {note.public_id}  {note.status}")

    def _inbox(self, user, status):
        """The inbox list exactly as the app asks for it: the real viewset, as a company member."""
        from django.conf import settings

        from rest_framework.test import APIRequestFactory, force_authenticate

        from fieldnotes.views import FieldNoteViewSet

        hosts = [h for h in settings.ALLOWED_HOSTS if h and h != "*" and not h.startswith(".")]
        factory = APIRequestFactory(HTTP_HOST=hosts[0]) if hosts else APIRequestFactory()
        request = factory.get("/api/field-notes/", {"status": status})
        force_authenticate(request, user=user)
        response = FieldNoteViewSet.as_view({"get": "list"})(request)
        rows = response.data if response.status_code == 200 else []
        if isinstance(rows, dict) and "results" in rows:
            rows = rows["results"]
        return response.status_code, {row["public_id"]: row for row in rows}

    def _verify(self, company, attester):
        """PASS/FAIL for each fact the review depends on."""
        from fieldnotes.models import CrewSender, FieldNote, FieldNoteConfirmation
        from notifications.models import Notification

        notes = {
            n.provider_message_id: n
            for n in FieldNote.objects.filter(company=company, provider_message_id__startswith=MESSAGE_ID_PREFIX)
        }
        senders = list(CrewSender.objects.filter(company=company, phone_e164__in=SENDER_PHONES))
        expected_status = {_message_id(n[0]): n[3] for n in NOTES}
        pending_ids = {str(notes[m].public_id) for m, s in expected_status.items() if s == "pending" and m in notes}
        refused_ids = {str(notes[m].public_id) for m, s in expected_status.items() if s == "refused" and m in notes}

        pending_code, pending_rows = self._inbox(attester, FieldNote.PENDING)
        refused_code, refused_rows = self._inbox(attester, FieldNote.REFUSED)
        entrust = notes.get(_message_id("01"))
        entrust_row = pending_rows.get(str(entrust.public_id)) if entrust else None
        public_ids = [str(n.public_id) for n in notes.values()]

        checks = [
            ("all 5 fixture notes exist", set(notes) == EXPECTED_MESSAGE_IDS),
            (
                "each note is in its seeded state (4 pending, 1 refused)",
                all(notes[m].status == s for m, s in expected_status.items() if m in notes),
            ),
            ("2 roster rows, both may send", len(senders) == len(SENDERS) and all(s.may_send for s in senders)),
            (
                f"inbox (status=pending) as {attester.email} returns the 4 waiting notes",
                pending_code == 200 and len(pending_ids) == 4 and pending_ids <= set(pending_rows),
            ),
            (
                "inbox shows the sender's words and the marked name",
                all(
                    pending_rows[pid]["words"].endswith(f"({MARKER})")
                    and pending_rows[pid]["sender"]["display_name"].startswith(MARKER)
                    for pid in pending_ids
                    if pid in pending_rows
                ),
            ),
            (
                "the Entrust note is offered as an application",
                entrust_row is not None and entrust_row.get("suggested_route") == "application",
            ),
            (
                "refused list (status=refused) returns the refused note",
                refused_code == 200 and len(refused_ids) == 1 and refused_ids <= set(refused_rows),
            ),
            (
                "no note confirmed into a record",
                not FieldNoteConfirmation.objects.filter(note__in=notes.values()).exists(),
            ),
            (
                "no outbound reply recorded (no first-contact notice, no consent stamp)",
                all(s.first_contact_at is None and s.consented_at is None for s in senders),
            ),
            (
                "no arrival notification for a fixture note",
                not Notification.objects.filter(
                    extra_data__kind="field_note", extra_data__note__in=public_ids
                ).exists(),
            ),
        ]
        self.stdout.write("")
        self.stdout.write("  Post-seed checks:")
        for name, ok in checks:
            self.stdout.write(f"    {'PASS' if ok else 'FAIL'}  {name}")
        failed = [name for name, ok in checks if not ok]
        if failed:
            raise CommandError("The fixture does not show the intended review state: " + ", ".join(failed))
