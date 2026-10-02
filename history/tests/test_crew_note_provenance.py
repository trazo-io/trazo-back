"""A record confirmed from a crew message says where it came from, and the channel keeps its boundary.

OSP alignment audit 2026-10, T29, with Oscar's Phase 4 rules (2026-10-01):
  * sender, performer and confirmer stay distinct; the sender is never taken for the performer;
  * stated occurrence, message receipt and confirmation are three times, printed apart;
  * missing performer stays "not recorded"; review is never implied by a confirmation;
  * an application (chemical, soil amendment, beneficial release) may come from a message only with
    the input details typed by the confirmer: a save that applied machine values to those is refused,
    whatever the inbox hint said, and the note stays waiting;
  * confirmation is atomic (a second save of the same note writes nothing and answers 409) and its
    history is append-only (deleting the record voids it; nothing clears it);
  * provenance is private: the buyer page never carries it; another company never reads it.
"""

import csv
import io
import threading
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.db.models import RestrictedError
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote, FieldNoteConfirmation
from fieldnotes.services.routing import APPLICATION, suggested_route
from history.models import ChemicalEvent, GeneralEvent, History, PestManagementEvent, SoilManagementEvent
from history.services.crew_note_provenance import event_type_of, provenance_for
from product.models import Establishment, Parcel

WORDS = "regamos el bloque 4 esta mañana, dos horas"


def _build(prefix, words=WORDS, kind=FieldNote.TEXT):
    user = get_user_model().objects.create_user(
        email=f"{prefix}-cp@example.com", password="pw-for-tests-only", first_name="Laurel", last_name=prefix
    )
    company = Company.objects.create(name=f"{prefix} CP Co")
    user.companies.add(company)
    est = Establishment.objects.create(name=f"{prefix} CP Farm", company=company)
    parcel = Parcel.objects.create(name=f"{prefix} CP Parcel", establishment=est, area=1)
    history = History.objects.create(parcel=parcel, name=f"{prefix} CP Season")
    parcel.current_history = history
    parcel.save(update_fields=["current_history"])
    sender = CrewSender.objects.create(
        company=company,
        establishment=est,
        phone_e164=f"+1415555{abs(hash(prefix)) % 10000:04d}",
        display_name="Miguel",
        consent_attested_at=timezone.now(),
        consent_attested_by=user,
    )
    note = FieldNote.objects.create(
        company=company,
        establishment=est,
        sender=sender,
        sender_phone=sender.phone_e164,
        sender_display_name="Miguel",
        provider=FieldNote.TWILIO,
        provider_message_id=f"SM-{prefix}",
        kind=kind,
        body_text=words if kind == FieldNote.TEXT else "",
        transcript=words if kind == FieldNote.VOICE else "",
        transcript_language="es-419" if kind == FieldNote.VOICE else "",
        received_at=timezone.now() - timedelta(days=1),
    )
    return user, company, parcel, history, note


class _Crew(APITestCase):
    def setUp(self):
        self.owner, self.company, self.parcel, self.history, self.note = _build("owner")
        self.client.force_authenticate(user=self.owner)

    def post(self, event_type=3, note=None, **extra):
        body = {
            "event_type": event_type,
            "parcels": [self.parcel.pk],
            "name": "irrigation",
            "description": "irrigation",
            "date": (timezone.now() - timedelta(days=3)).isoformat(),
            "field_note": str((note or self.note).public_id),
        }
        body.update(extra)
        return self.client.post(reverse("events-list"), body, format="json")


class ProvenanceTests(_Crew):
    def test_the_three_roles_and_three_times_print_apart(self):
        res = self.post()
        self.assertEqual(res.status_code, 201, res.data)
        event = GeneralEvent.objects.get(history=self.history)
        prov = provenance_for([event])[(event_type_of(event), event.pk)]
        self.assertEqual(prov.sender_name, "Miguel")
        self.assertEqual(prov.words, WORDS)
        self.assertIn("Laurel", prov.confirmer_name)
        from history.services.crew_note_provenance import lines

        text = " ".join(lines(prov, event))
        self.assertIn("sent by Miguel (number ending", text)
        self.assertIn("Stated occurrence:", text)
        self.assertIn("Message received:", text)
        self.assertIn("Confirmed into this record:", text)
        self.assertIn("confirmed 3 day(s) after the stated occurrence", text)
        self.assertIn("Performer: not recorded. The sender is not assumed to be the performer.", text)
        self.assertIn("Review (§ 112.161(b)): no review recorded.", text)
        self.assertNotIn("not a contemporaneous", text, "no legal verdict, only facts about this record")

    def test_a_performer_entered_by_the_confirmer_is_printed_as_entered(self):
        self.post(performed_by="Rosa Díaz")
        event = GeneralEvent.objects.get(history=self.history)
        from history.services.crew_note_provenance import lines

        text = " ".join(lines(provenance_for([event])[(3, event.pk)], event))
        self.assertIn("Performer: Rosa Díaz (as entered by the confirmer; not inferred from the sender)", text)

    def test_confirming_never_sets_review(self):
        self.post()
        event = GeneralEvent.objects.get(history=self.history)
        self.assertFalse(event.reviewed)
        self.assertFalse(event.reviewer_name)
        self.assertIsNone(event.review_date)

    def test_the_dossier_and_csv_carry_it(self):
        from history.services.audit_export_service import AuditExportService

        self.post(performed_by="Rosa Díaz")
        service = AuditExportService(self.history)
        rows = list(csv.reader(io.StringIO(service.generate_csv().getvalue().decode("utf-8-sig"))))
        flat = [r for r in rows if r]
        header_at = next(i for i, r in enumerate(flat) if r[0] == "=== RECORDS CONFIRMED FROM CREW MESSAGES ===")
        header, row = flat[header_at + 1], flat[header_at + 2]
        record = dict(zip(header, row))
        self.assertEqual(record["Sender"], "Miguel")
        self.assertEqual(record["Message As Received"], WORDS)
        self.assertEqual(record["Performer (as entered)"], "Rosa Díaz")
        self.assertIn("Laurel", record["Confirmed By"])
        pdf_bytes = service.generate_pdf(strict_photos=False, strict_ofpp=False)
        pdf_bytes = pdf_bytes.getvalue() if hasattr(pdf_bytes, "getvalue") else pdf_bytes
        pdf = " ".join(extract_text(io.BytesIO(pdf_bytes)).split())
        self.assertIn("Records Confirmed From Crew Messages", pdf)
        self.assertIn("sent by Miguel", pdf)

    def test_a_formula_in_the_message_is_neutralised_in_the_csv(self):
        _u, _c, _p, _h, note = _build("formula", words="=HYPERLINK(1)")
        note.company = self.company
        note.establishment = self.parcel.establishment
        note.save()
        self.post(note=note)
        from history.services.audit_export_service import AuditExportService

        text = AuditExportService(self.history).generate_csv().getvalue().decode("utf-8-sig")
        self.assertIn("'=HYPERLINK(1)", text)

    def test_the_buyer_page_never_carries_it(self):
        self.post()
        History.objects.filter(pk=self.history.pk).update(published=True, is_outdoor=True)
        self.history.refresh_from_db()
        res = APIClient().get(
            reverse("production-transparency-detail", kwargs={"production_public_id": str(self.history.public_id)})
        )
        self.assertEqual(res.status_code, 200, res.content[:300])
        body = res.content.decode()
        self.assertIn('"timeline"', body, "the payload read nothing, so the absence below proves nothing")
        self.assertIn("irrigation", body, "the confirmed record is not on the page, so its absence proves nothing")
        for leaked in ("Miguel", "regamos", self.note.sender_phone[-4:]):
            self.assertNotIn(leaked, body)

    def test_the_private_endpoint_serves_it_to_the_company_and_not_to_another(self):
        self.post()
        event = GeneralEvent.objects.get(history=self.history)
        url = f"{reverse('events-detail', kwargs={'pk': event.pk})}crew-note/?event_type=3"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(res.json()["crew_note"]["sender"]["display_name"], "Miguel")
        stranger, *_ = _build("stranger")
        other = APIClient()
        other.force_authenticate(stranger)
        self.assertEqual(other.get(url).status_code, 404)


class ApplicationBoundaryTests(_Crew):
    def test_the_routing_hint_reads_english_spanish_and_portuguese(self):
        for words in ("sprayed the north block", "apliqué cobre en el bloque 2", "pulverizamos ontem"):
            self.assertEqual(suggested_route(words), APPLICATION, words)
        for words in ("picked limes in block 3", "rocío fuerte esta mañana", "regamos dos horas"):
            self.assertEqual(suggested_route(words), "", words)

    def test_an_application_with_machine_input_values_is_refused_and_the_note_waits(self):
        res = self.post(
            event_type=2,
            type="FE",
            commercial_name="Feather meal",
            field_note_proposal={"offered": {"commercial_name": "Feather meal"}, "applied": ["commercial_name"]},
        )
        self.assertEqual(res.status_code, 400, res.data)
        self.assertEqual(str(res.data.get("code")), "application_values_from_message")
        self.assertFalse(ChemicalEvent.objects.filter(history=self.history).exists())
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FieldNote.PENDING)

    def test_an_application_typed_by_the_confirmer_links_the_note(self):
        res = self.post(event_type=2, type="FE", commercial_name="Feather meal", field_note_proposal={"applied": []})
        self.assertEqual(res.status_code, 201, res.data)
        event = ChemicalEvent.objects.get(history=self.history)
        self.note.refresh_from_db()
        self.assertEqual((self.note.status, self.note.fulfilled_by_id), (FieldNote.CONFIRMED, event.pk))

    def test_the_rule_follows_the_type_not_the_hint(self):
        """Soil amendments and beneficial releases are applications too, with words that match no hint."""
        for event_type, extra in (
            (5, {"type": "OM", "amendment_product_name": "Compost"}),
            (6, {"type": "BR", "beneficial_species": "Aphidius"}),
        ):
            res = self.post(
                event_type=event_type,
                field_note_proposal={"applied": ["amendment_amount", "release_quantity"]},
                **extra,
            )
            self.assertEqual(res.status_code, 400, (event_type, res.data))
        self.assertFalse(SoilManagementEvent.objects.filter(history=self.history).exists())
        self.assertFalse(PestManagementEvent.objects.filter(history=self.history).exists())

    def test_a_non_application_may_keep_machine_values(self):
        res = self.post(field_note_proposal={"offered": {"duration": "2 h"}, "applied": ["duration"]})
        self.assertEqual(res.status_code, 201, res.data)
        row = FieldNoteConfirmation.objects.get()
        self.assertEqual(row.proposal["applied"], ["duration"])


class HistoryAndAtomicityTests(_Crew):
    def test_a_second_save_of_the_same_note_writes_nothing(self):
        self.assertEqual(self.post().status_code, 201)
        res = self.post(name="second")
        self.assertEqual(res.status_code, 409, res.data)
        self.assertEqual(GeneralEvent.objects.filter(history=self.history).count(), 1)

    def test_the_confirmation_keeps_source_proposal_and_values_as_first_saved(self):
        self.post(performed_by="Rosa", field_note_proposal={"offered": {"duration": "2 h"}, "applied": ["duration"]})
        self.assertEqual(FieldNoteConfirmation.objects.count(), 1, "no confirmation history row was written")
        row = FieldNoteConfirmation.objects.get()
        self.assertEqual(row.source["words"], WORDS)
        self.assertEqual(row.source["sender_phone_last4"], self.note.sender_phone[-4:])
        self.assertNotIn(self.note.sender_phone, str(row.source))
        self.assertEqual(row.confirmed_values["performed_by"], "Rosa")

    def test_a_confirmation_is_never_edited_or_deleted(self):
        self.post()
        row = FieldNoteConfirmation.objects.get()
        row.confirmed_by_name = "someone else"
        with self.assertRaises(DjangoValidationError):
            row.save()
        with self.assertRaises(DjangoValidationError):
            row.delete()
        with self.assertRaises(RestrictedError):
            FieldNote.objects.filter(pk=self.note.pk).delete()

    def test_deleting_the_record_voids_and_keeps_its_confirmation_and_requeues_the_note(self):
        self.post()
        event = GeneralEvent.objects.get(history=self.history)
        res = self.client.delete(f"{reverse('events-detail', kwargs={'pk': event.pk})}?event_type=3")
        self.assertIn(res.status_code, (200, 204), res.content[:300])
        row = FieldNoteConfirmation.objects.get()
        self.assertIsNotNone(row.voided_at)
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FieldNote.PENDING)
        self.assertEqual(self.post(name="again").status_code, 201)
        again = GeneralEvent.objects.get(history=self.history, name="again")
        prov = provenance_for([again])[(3, again.pk)]
        self.assertEqual(len(prov.earlier_confirmations), 1)

    def test_another_companys_confirmation_is_never_read(self):
        self.post()
        event = GeneralEvent.objects.get(history=self.history)
        row = FieldNoteConfirmation.objects.get()
        stranger_company = Company.objects.create(name="Elsewhere")
        FieldNoteConfirmation.objects.filter(pk=row.pk).update(company=stranger_company)
        FieldNote.objects.filter(pk=self.note.pk).update(company=stranger_company)
        self.assertEqual(provenance_for([event]), {})


class ConcurrentConfirmationTests(TransactionTestCase):
    def test_two_simultaneous_saves_make_one_record(self):
        owner, _company, parcel, history, note = _build("race")
        results = []
        barrier = threading.Barrier(2)

        def save(name):
            client = APIClient()
            client.force_authenticate(owner)
            barrier.wait()
            try:
                res = client.post(
                    reverse("events-list"),
                    {
                        "event_type": 3,
                        "parcels": [parcel.pk],
                        "name": name,
                        "description": name,
                        "date": timezone.now().isoformat(),
                        "field_note": str(note.public_id),
                    },
                    format="json",
                )
                results.append(res.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=save, args=(n,)) for n in ("first", "second")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [201, 409], results)
        self.assertEqual(GeneralEvent.objects.filter(history=history).count(), 1)
        self.assertEqual(FieldNoteConfirmation.objects.filter(note=note).count(), 1)
