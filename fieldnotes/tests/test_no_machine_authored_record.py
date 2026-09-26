"""This app suggests. It never authors a record (2026-09-26).

7 CFR 205.201(a) makes the producer the author of the plan, and 205.103(b)(2) needs records that
survive an inspector's trace-back. `EventViewSet.perform_create` is the only place an event is
created and it forces `created_by = request.user`, so the person who confirms is the author.

THE LIVE COUNTER-PRECEDENT, and the reason this file is a source walk rather than a comment:
`IoTDeviceViewSet.pending_events` (carbon/views.py) holds machine proposals on `IoTDataPoint` in
almost exactly this app's shape, and then calls `_auto_approve_event`, which writes a `CarbonEntry`
with no human in the loop. Somebody arriving at this app with that file in mind would find the
shapes familiar and the auto-approve missing, and could reasonably "finish" it. These tests make that
fail instead.
"""

import io
import tokenize
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote
from history.models import ChemicalEvent, GeneralEvent, History, ProductionEvent
from product.models import Establishment, Parcel

APP = Path(__file__).resolve().parent.parent
SOURCES = sorted(p for p in APP.rglob("*.py") if "migrations" not in p.parts and p.parent.name != "tests")


def code_only(path):
    """The file with comments and string literals removed.

    These guards ask "does this app USE an event model", and prose must not answer for it. The
    comments in this app deliberately NAME the things it must not do, including the counter-precedent
    and `EVENT_TYPE_TO_MODEL` itself, because explaining the rule is how the rule survives. A
    substring search over raw text fails on its own explanation, which is exactly how a guard gets
    weakened into uselessness by the first person it inconveniences.
    """
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return "\n".join(kept)


class NoModuleInThisAppWritesAnEvent(TestCase):
    def test_the_walk_actually_found_the_app(self):
        # Guard-the-guard. Every assertion below is "no file contains X", which passes vacuously
        # over an empty file list, and a moved package would empty it silently.
        self.assertGreaterEqual(len(SOURCES), 5, f"expected to walk this app, found {SOURCES}")
        self.assertIn("models.py", [p.name for p in SOURCES])
        self.assertIn("views.py", [p.name for p in SOURCES])

    def test_no_event_model_is_named_anywhere_in_this_app(self):
        # Breaking edit: add an `_auto_log_high_confidence_note()` helper that imports an event model.
        forbidden = (
            "EVENT_TYPE_TO_MODEL",
            "GeneralEvent",
            "ChemicalEvent",
            "ProductionEvent",
            "SoilManagementEvent",
            "PestManagementEvent",
            "BusinessEvent",
            "WeatherEvent",
            "EquipmentMaintenanceEvent",
        )
        for path in SOURCES:
            text = code_only(path)
            for name in forbidden:
                self.assertNotIn(name, text, f"{path.name} names the event model {name}")

    def test_nothing_in_this_app_auto_approves(self):
        # Breaking edit: copy `should_auto_approve_event` across from carbon/views.py.
        for path in SOURCES:
            text = code_only(path).lower()
            for phrase in ("auto_approve", "auto_confirm", "should_auto", "autolog", "auto_log"):
                self.assertNotIn(phrase, text, f"{path.name} contains {phrase}")

    def test_no_field_on_the_note_carries_a_date_somebody_could_mistake_for_the_activity_date(self):
        # A machine never authors the day a record carries. `carbon/tests/test_voice_suggestion_has_no_date`
        # pins the same rule on the extractor's response. `received_at` is when the MESSAGE arrived and
        # is named for that; a field called `date` or `activity_date` would invite the wizard to use it.
        names = {f.name for f in FieldNote._meta.get_fields() if hasattr(f, "attname")}
        for forbidden in ("date", "event_date", "activity_date", "performed_at", "suggested_date"):
            self.assertNotIn(forbidden, names, f"FieldNote.{forbidden} would be a machine-authored date")


class APendingNoteProducesNoRecord(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="sup2@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Rule Co")
        self.user.companies.add(self.company)
        self.establishment = Establishment.objects.create(name="Rule Farm", company=self.company)
        self.parcel = Parcel.objects.create(name="Block 4", establishment=self.establishment, area=2)
        self.history = History.objects.create(parcel=self.parcel, name="2026 season")
        self.sender = CrewSender.objects.create(
            company=self.company,
            establishment=self.establishment,
            phone_e164="+14155559999",
            consent_attested_at=timezone.now(),
            consent_attested_by=self.user,
        )

    def test_a_note_arriving_writes_no_event_of_any_type(self):
        before = (GeneralEvent.objects.count(), ChemicalEvent.objects.count(), ProductionEvent.objects.count())
        FieldNote.objects.create(
            company=self.company,
            establishment=self.establishment,
            sender=self.sender,
            sender_phone=self.sender.phone_e164,
            provider=FieldNote.TWILIO,
            provider_message_id="SMruleA",
            kind=FieldNote.TEXT,
            body_text="sprayed sulfur on block 4, 40 gallons",
        )
        after = (GeneralEvent.objects.count(), ChemicalEvent.objects.count(), ProductionEvent.objects.count())
        self.assertEqual(before, after, "a field note created an event by itself")

    def test_a_note_holds_its_words_and_claims_no_record(self):
        note = FieldNote.objects.create(
            company=self.company,
            sender=self.sender,
            sender_phone=self.sender.phone_e164,
            provider=FieldNote.TWILIO,
            provider_message_id="SMruleB",
            kind=FieldNote.TEXT,
            body_text="mowed the orchard floor",
        )
        self.assertEqual(note.status, FieldNote.PENDING)
        self.assertIsNone(note.fulfilled_by_id)
        self.assertIsNone(note.fulfilled_by_event_type)
        self.assertIsNone(note.confirmed_by)
        self.assertIsNone(note.confirmed_at)
        self.assertEqual(note.words, "mowed the orchard floor")
