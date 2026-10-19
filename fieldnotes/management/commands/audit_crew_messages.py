"""Score the field-note pipeline against a labelled corpus of crew messages.

WHY THIS IS A COMMAND AND NOT A TEST. Every entry costs an OpenAI call, so in CI this would
bill on each push and fail on model drift rather than on a regression. The corpus's SHAPE is
guarded for free by `fieldnotes/tests/test_crew_message_corpus.py`, which runs in CI; the
measurement is opt-in and run by a person.

WHY IT POSTS TO THE WEBHOOK instead of calling the extractor. Calling
`process_voice_with_ai` directly would score the model and prove nothing about the product: the
signature check, the roster lookup, the idempotency key, the STOP branch and the refusal paths
all live in the view. The Django test client runs the real urlconf, so this exercises every one
of them. `FIELD_NOTES_WEBHOOK_URL` is pinned to the test client's own URL because Twilio signs
the exact URL it called.

TWO KINDS OF RESULT, NEVER MIXED:

  * INVARIANTS are pass/fail and a failure is a defect. No note may become a record on its own;
    no date may be invented; an unrostered number writes nothing; a duplicate id yields one row.
  * ACCURACY is a rate. The extractor is a language model, so the same message can parse two
    ways, and "87/100 blocks correct" is a measurement rather than a verdict. Every miss is
    printed with the message so a human can judge it.

Usage:
    DATABASE_NAME=trazo_fnaudit_test poetry run python manage.py audit_crew_messages \
        --seed --out /path/to/report.md
"""

import json
import re
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.utils import timezone

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "crew_messages.json"

# The test client's own origin. Twilio HMACs the exact URL it called, so the signature this
# command computes and the URL the view reconstructs have to agree on one string.
WEBHOOK_PATH = "/api/field-notes/inbound/twilio/"
WEBHOOK_URL = "http://testserver" + WEBHOOK_PATH

# Local only, and it never leaves this process. The real token is a production secret; what
# matters here is that BOTH sides use the same one, so the signature path runs for real.
AUDIT_TOKEN = "audit-local-token-not-a-secret"


#: Keys and values that mean "a day". A parse may put one under a key that is not called a date,
#: so both are checked.
_DATE_KEY = re.compile(r"(date|fecha|day|dia|when)", re.I)
_DATE_VALUE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})")


def _walk(node, path="$"):
    """Every (path, scalar) in a nested structure.

    `activity_fields` is a dict, so a top-level key scan reads none of it, and that is exactly
    where a stray date or a name would sit.
    """
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            out.extend(_walk(value, "%s.%s" % (path, key)))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            out.extend(_walk(value, "%s[%d]" % (path, index)))
    elif node not in (None, "", [], {}):
        out.append((path, node))
    return out


def _looks_like_a_date(path, value):
    """A date by the name of its field, or by the shape of its value."""
    if _DATE_KEY.search(path):
        return True
    return bool(_DATE_VALUE.search(str(value)))


def sign(token, url, params):
    import base64
    import hashlib
    import hmac

    payload = url + "".join("%s%s" % (k, params[k]) for k in sorted(params))
    digest = hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


class Command(BaseCommand):
    help = "Score the field-note pipeline against the labelled crew-message corpus."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed", action="store_true", help="Create the audit company, farm, blocks and roster row."
        )
        parser.add_argument("--limit", type=int, default=0, help="Run only the first N entries.")
        parser.add_argument("--category", default="", help="Run only one category.")
        parser.add_argument("--out", default="", help="Write the report here instead of stdout.")
        parser.add_argument(
            "--voice-base",
            default="",
            help=(
                "Base https URL of a media host serving the synthesised notes, e.g. "
                "https://localhost:8443. Without it the voice entries are skipped and the run "
                "says so rather than reporting a voice result it did not measure."
            ),
        )
        parser.add_argument(
            "--make-audio",
            default="",
            help="Synthesise the voice corpus into this directory first (macOS `say` + ffmpeg).",
        )

    # -- seeding -------------------------------------------------------------------------------

    def _seed(self):
        from django.contrib.auth import get_user_model

        from company.models import Company, Establishment
        from fieldnotes.models import CrewSender
        from product.models import Parcel

        User = get_user_model()
        user, _ = User.objects.get_or_create(
            email="audit-supervisor@trazo.test",
            defaults={"first_name": "Audit", "last_name": "Supervisor", "is_active": True},
        )
        company, _ = Company.objects.get_or_create(name="Field Note Audit Co")
        farm, _ = Establishment.objects.get_or_create(
            company=company, name="Audit Ranch", defaults={"country": "US", "state": "California"}
        )
        # Named to match the corpus so "block 4" can resolve and "Sunset Block" cannot. A corpus
        # where every block is unknown would not test resolution at all.
        for name in [
            "River Block",
            "block 1",
            "block 2",
            "block 3",
            "block 4",
            "block 5",
            "bloque 1",
            "bloque 2",
            "bloque 3",
            "bloque 4",
            "bloque 5",
            "north block",
        ]:
            Parcel.objects.get_or_create(establishment=farm, name=name, defaults={"area": 4.0})

        # THE PARSE ENDPOINT IS PLAN-GATED on `company.has_feature("voice_recording")`, so without
        # a plan every entry would 403 and the run would measure the gate instead of the parser.
        #
        # Seeded as STARTER, not as a special audit tier, because that is the real answer:
        # `voice_recording` is inside `starter_features` in `create_plans`, so the free tier
        # carries it and a company with no subscription row falls back to Starter
        # (`Company.subscription_plan`). Inventing a privileged plan here would have hidden the
        # one gate a free farm actually meets.
        #
        # NOTE: this row is an audit fixture and never a lineup fact. `create_plans` remains the
        # only thing that creates the real lineup; this carries one feature and no price.
        from subscriptions.models import Plan

        starter, _ = Plan.objects.get_or_create(
            slug="starter",
            defaults={
                "name": "Starter",
                "features": {"voice_recording": True, "is_starter": True},
                "price": 0,
                "is_active": True,
            },
        )
        # `Company.subscription_plan` answers None when there is no subscription row at all, and
        # calls that state "a data anomaly, not a customer" because every real company gets one at
        # creation. So the fixture creates one rather than leaning on a fallback that does not
        # exist for this shape.
        from subscriptions.models import Subscription

        Subscription.objects.get_or_create(company=company, defaults={"plan": starter, "status": "active"})

        # `request.user.companies` is a through-model m2m, so the membership row is what makes
        # the note visible to the confirmer and what `get_active_company()` resolves.
        from users.models import WorksIn

        supervisor_membership, _ = WorksIn.objects.get_or_create(
            user=user, company=company, defaults={"role": WorksIn.COMPANY_ADMIN}
        )
        if supervisor_membership.role != WorksIn.COMPANY_ADMIN:
            supervisor_membership.role = WorksIn.COMPANY_ADMIN
            supervisor_membership.save(update_fields=["role"])

        # A SECOND FARM WITH NO BLOCKS, on purpose. The paired UI suite asserts the dead end a
        # farm with no parcels hits, and against a farm that HAS blocks that assertion can only be
        # written as "if the text happens to be there", which passes whatever the product does
        # (review of app #150). A farm that really has none makes it a real test.
        Establishment.objects.get_or_create(
            company=company,
            name="Audit Ranch (no blocks)",
            defaults={"country": "US", "state": "California"},
        )

        sender, _ = CrewSender.objects.get_or_create(
            company=company,
            phone_e164="+15095550123",
            defaults={
                "establishment": farm,
                "display_name": "Audit Crew",
                "language": "es",
                "is_active": True,
            },
        )
        # `may_send()` needs all three, and a roster row without attested consent is correctly
        # refused, which would make every entry fail for the same uninteresting reason.
        # UNCONDITIONAL, and that is the point. `may_send()` wants all three of is_active,
        # consent_attested_at and no stopped_at, and the corpus itself sends STOP, which clears
        # the first and sets the last. Reseeding only when consent was missing left the row
        # stopped, so a second run reported every message as "unrostered" and looked like a
        # broken harness rather than the opt-out working.
        sender.consent_attested_at = sender.consent_attested_at or timezone.now()
        sender.stopped_at = None
        sender.is_active = True
        sender.save()
        # THE UI RUN NEEDS TWO MORE THINGS the webhook audit does not.
        #
        # A SIGNED-IN USER WITH A PASSWORD, because auth is httpOnly-cookie JWT and the e2e suite
        # signs in through the real form (minting cookies was tried and is less faithful). The
        # credentials match `e2e/auth.setup.ts` defaults so the spec needs no new variables.
        # `user_type` MUST be PRODUCER. It defaults to CONSUMER, and `users/views.py` refuses a
        # consumer on the `app` subdomain with a bare "Access denied" that looks like a password
        # problem. A seeded operator who cannot sign in would fail the whole UI suite for a
        # reason that has nothing to do with field notes.
        from users.constants import PRODUCER

        e2e_user, created = User.objects.get_or_create(
            email="e2e@trazo.test",
            defaults={
                "first_name": "E2E",
                "last_name": "Operator",
                "is_active": True,
                "user_type": PRODUCER,
            },
        )
        if e2e_user.user_type != PRODUCER:
            e2e_user.user_type = PRODUCER
            e2e_user.save(update_fields=["user_type"])
        if created or not e2e_user.has_usable_password():
            e2e_user.set_password("E2Epass!2026")
            e2e_user.is_active = True
            e2e_user.save()
        # ROLE IS REQUIRED, and a membership without one renders "Restricted Access" rather than
        # an auth error, so the page looks broken instead of unauthorised. COMPANY_ADMIN because
        # the confirm flow writes: `ReadOnlyForViewersGlobal` lets any member read the inbox and
        # only CA/FM log a record from it.
        works_in, _ = WorksIn.objects.get_or_create(
            user=e2e_user, company=company, defaults={"role": WorksIn.COMPANY_ADMIN}
        )
        if works_in.role != WorksIn.COMPANY_ADMIN:
            works_in.role = WorksIn.COMPANY_ADMIN
            works_in.save(update_fields=["role"])

        # AN OPEN SEASON, because `EventViewSet.perform_create` writes against a parcel's current
        # history and refuses without one. A farm with blocks but no season would stop the confirm
        # flow before it reached the assertions this audit is for.
        from django.utils import timezone as _tz

        from history.models import History

        first_block = Parcel.objects.filter(establishment=farm).order_by("id").first()
        if first_block and first_block.current_history is None:
            history = History.objects.create(
                parcel=first_block,
                start_date=_tz.now(),
                expected_harvest=_tz.now() + __import__("datetime").timedelta(days=120),
                production_method="organic",
                production_unit="lb",
            )
            first_block.current_history = history
            first_block.save(update_fields=["current_history"])
            self.stdout.write("seeded season %s on %s" % (history.id, first_block.name))

        self.stdout.write("seeded company=%s farm=%s sender=%s user=%s" % (company.id, farm.id, sender.id, user.id))
        return company, farm, sender, user

    def _make_audio(self, entries, out_dir):
        """Synthesise every `spoken` line into OGG/Opus, the container WhatsApp actually sends.

        macOS-only, and deliberately not a dependency of the run: the corpus carries `spoken`, so
        any TTS can regenerate these, and a recording made on a real phone can be dropped into the
        same directory under the same name.

        ⛔ SYNTHETIC SPEECH IS NOT FIELD SPEECH. No tractor, no wind, no accent range, nobody
        talking over anybody. What this measures is that the PATH works and that specific words
        survive it, never how well transcription performs for a crew. A rate from these files
        would flatter the product and is not reported.
        """
        import subprocess

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        made = 0
        for entry in entries:
            if entry.get("kind") != "voice":
                continue
            target = out / ("%s.ogg" % entry["id"])
            if target.exists():
                continue
            aiff = out / ("%s.aiff" % entry["id"])
            subprocess.run(
                ["say", "-v", entry.get("voice", "Paulina"), "-o", str(aiff), entry["spoken"]],
                check=True,
            )
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(aiff), "-c:a", "libopus", "-b:a", "24k", str(target)],
                check=True,
                capture_output=True,
            )
            aiff.unlink(missing_ok=True)
            made += 1
        self.stdout.write("synthesised %d voice notes into %s" % (made, out))

    # -- driving -------------------------------------------------------------------------------

    def _post(self, client, body, message_id, from_number="+15095550123", media_url=""):
        params = {
            "From": "whatsapp:" + from_number,
            "To": "whatsapp:+15092045054",
            "Body": body,
            "MessageSid": message_id,
            "NumMedia": "1" if media_url else "0",
        }
        if media_url:
            # The shape Twilio actually posts for a voice note. The URL is fetched for real by
            # `fetch_media`, over TLS, with Basic auth, against the allowlisted host.
            params["MediaUrl0"] = media_url
            params["MediaContentType0"] = "audio/ogg"
            params["Body"] = ""
        return client.post(
            WEBHOOK_PATH,
            data=params,
            HTTP_X_TWILIO_SIGNATURE=sign(AUDIT_TOKEN, WEBHOOK_URL, params),
        )

    def _parse(self, client, note, language):
        """Ask for the suggestion exactly as the wizard does.

        THE INBOUND PATH DOES NO PARSING. `FieldNoteExtraction` is written in one place,
        `carbon/views.py::_keep_field_note_extraction`, which runs inside this endpoint. So a note
        sits as raw words until a supervisor opens it, and scoring the webhook alone would measure
        a stage that does not exist. This is the client's own call, with the note's public id, so
        the stored reading is produced the same way a real review produces it.
        """
        response = client.post(
            "/api/carbon/process-voice-event/",
            {
                # A voice note carries no `body_text`: `intake` writes Deepgram's output to
                # `transcript`, and that is what the wizard sends to be parsed.
                "transcript": note.body_text or note.transcript,
                "language": language,
                "field_note": str(note.public_id),
                # REQUIRED by the endpoint, and fixed for the whole corpus on purpose. The crop
                # steers the prompt, so varying it per entry would mix two variables and make a
                # miss unattributable. Every message in the corpus is orchard work.
                "crop_type": "walnut",
            },
            format="json",
        )
        body = {}
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - a non-JSON body is itself the finding
            pass
        return response.status_code, body

    def _refuse_outside_a_disposable_database(self):
        """Both guards from `ensure_e2e_user`, reused rather than restated.

        THIS COMMAND CREATES A CREDENTIAL WHOSE PASSWORD IS IN THE REPOSITORY, grants it
        COMPANY_ADMIN, and writes a hundred notes. `users/management/commands/ensure_e2e_user.py`
        already refuses to do the first of those outside a throwaway database, and says why: "An
        E2E convenience that can be pointed at production is a backdoor with a friendly name."
        This duplicated the account and none of the guard (review of back #185).

        Guarding the COMMAND rather than the credential, because the rest of what it does is no
        safer: a hundred crew notes and an open season against a real farm is its own incident.

        `_looks_disposable` is IMPORTED, never copied. Its own comment records that an earlier
        substring version let `trazo_pacific` through on "ci", and a second implementation is how
        that lesson gets lost.
        """
        from django.conf import settings

        from users.management.commands.ensure_e2e_user import _looks_disposable

        if not settings.DEBUG:
            raise CommandError("refusing to run with DEBUG off: this seeds a known-password admin")
        name = settings.DATABASES["default"]["NAME"]
        if not _looks_disposable(name):
            raise CommandError(
                "refusing to run against %r: the database name does not look disposable. "
                "A token of the name has to say so: trazo_fnaudit_test, trazo_iso7, trazo_dev." % name
            )

    def handle(self, *args, **options):
        from django.test import override_settings

        self._refuse_outside_a_disposable_database()

        from fieldnotes.models import CrewSender, FieldNote

        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        # Kept before any filter: synthesis is a SETUP step over the whole corpus, so
        # `--make-audio --category plain` must still produce every voice file rather than the two
        # that happen to be in that category.
        all_entries = corpus["entries"]
        entries = all_entries
        if options["category"]:
            entries = [e for e in entries if e["category"] == options["category"]]
        if options["limit"]:
            entries = entries[: options["limit"]]

        overrides = dict(
            TWILIO_AUTH_TOKEN=AUDIT_TOKEN,
            FIELD_NOTES_WEBHOOK_URL=WEBHOOK_URL,
            FIELD_NOTE_RUNNER="eager",
            FIELD_NOTES_WHATSAPP_FROM="",
        )
        voice_base = (options.get("voice_base") or "").rstrip("/")
        if voice_base:
            from urllib.parse import urlparse

            host = urlparse(voice_base).hostname
            # ⛔ EXTENDING THE MEDIA ALLOWLIST IS A SECURITY DECISION, and it is scoped to this
            # process only: `allowed_media_hosts` is what stands between a provider payload and a
            # server-side fetch with credentials attached. Overridden here, never in settings.
            overrides["FIELD_NOTE_MEDIA_HOSTS"] = (host,)
            # `fetch_media` requires both halves of the Basic-auth pair and names their absence as
            # a configuration failure rather than unreadable audio. The local host ignores them.
            overrides["TWILIO_ACCOUNT_SID"] = "ACaudit"
        if options.get("make_audio"):
            self._make_audio(all_entries, options["make_audio"])

        with override_settings(**overrides):
            supervisor = None
            if options["seed"]:
                _, _, _, supervisor = self._seed()
            else:
                from django.contrib.auth import get_user_model

                supervisor = get_user_model().objects.filter(email="audit-supervisor@trazo.test").first()
            # TWO CLIENTS, on purpose. The webhook is deliberately NOT a DRF view, so it takes
            # the plain client and its real HMAC header. The parse endpoint is DRF behind
            # httpOnly-cookie JWT, which a session login cannot satisfy, so it takes an
            # APIClient with the user forced on. Auth is not what this audit measures; the
            # signature path on the anonymous route is, and that one runs for real.
            from rest_framework.test import APIClient

            client = Client()
            api = APIClient()
            if supervisor is not None:
                api.force_authenticate(user=supervisor)
            self._api = api
            results = []
            skipped_voice = []
            started = time.time()

            for i, entry in enumerate(entries, 1):
                before = FieldNote.objects.count()
                msg_id = "AUDIT-%s" % entry["id"]
                # The opt-out is delivered from its OWN number. STOP deactivates every roster row
                # for the sender it came from, so running it on the shared number would silently
                # unroster the rest of the corpus. It is the last entry today, which means the
                # ordering is load-bearing unless the number is separated. It is separated here.
                from_number = "+15095550199" if entry["category"] == "optout" else "+15095550123"
                media_url = ""
                if entry.get("kind") == "voice":
                    if not voice_base:
                        # SAID OUT LOUD, not silently skipped. A run that quietly drops the voice
                        # entries would report a text result under a heading that claims both.
                        skipped_voice.append(entry["id"])
                        continue
                    media_url = "%s/%s.ogg" % (voice_base, entry["id"])
                response = self._post(client, entry["text"], msg_id, from_number=from_number, media_url=media_url)

                # The duplicate category is the point of the category: same id twice.
                dup_status = None
                if entry["expect"].get("send_twice"):
                    dup_status = self._post(client, entry["text"], msg_id).status_code
                if entry["expect"].get("resend_new_id"):
                    dup_status = self._post(client, entry["text"], msg_id + "-RESEND").status_code

                note = FieldNote.objects.filter(provider_message_id=msg_id).first()
                parse_status, parse_body = (None, {})
                # A VOICE NOTE HAS NO `body_text`. Its words are the TRANSCRIPT, written by
                # `intake` after Deepgram answers, and that is what the wizard parses.
                if note and note.kind == "voice":
                    note.refresh_from_db()
                if note and (note.body_text or note.transcript):
                    parse_status, parse_body = self._parse(self._api, note, entry["lang"])
                note.refresh_from_db() if note else None
                extraction = note.extractions.first() if note else None
                results.append(
                    {
                        "entry": entry,
                        "http": response.status_code,
                        "dup_http": dup_status,
                        "notes_created": FieldNote.objects.count() - before,
                        "note_status": note.status if note else None,
                        "refusal_reason": getattr(note, "refusal_reason", "") if note else "",
                        "body_text": note.body_text if note else "",
                        "transcript": note.transcript if note else "",
                        "transcript_language": note.transcript_language if note else "",
                        "kind": note.kind if note else entry.get("kind", "text"),
                        "parse_http": parse_status,
                        "parsed": parse_body,
                        "offered": extraction.offered if extraction else None,
                        "ex_language": extraction.language if extraction else None,
                        "ex_negation": extraction.negation if extraction else None,
                    }
                )
                self.stdout.write("  %3d/%d %-14s %s" % (i, len(entries), entry["id"], response.status_code))

            elapsed = time.time() - started

        report = self._report(results, elapsed)
        if options["out"]:
            Path(options["out"]).write_text(report, encoding="utf-8")
            self.stdout.write("report written to %s" % options["out"])
        else:
            self.stdout.write(report)

    # -- scoring -------------------------------------------------------------------------------

    def _report(self, results, elapsed):
        import collections

        lines = []
        w = lines.append
        w("# Crew message audit")
        w("")
        w("%d messages through the signed webhook in %.0fs." % (len(results), elapsed))
        w("")

        # INVARIANTS. A failure here is a defect, not a measurement.
        inv = collections.OrderedDict()

        def check(name, ok, detail=""):
            inv.setdefault(name, {"pass": 0, "fail": 0, "details": []})
            inv[name]["pass" if ok else "fail"] += 1
            if not ok and detail:
                inv[name]["details"].append(detail)

        for r in results:
            e = r["entry"]
            ident = e["id"]
            # 1. The webhook never 500s. A 500 makes the provider retry forever.
            check("webhook answers without a 500", r["http"] < 500, "%s -> %s" % (ident, r["http"]))
            # 2. The crew's words are stored verbatim. A record quoting altered words is evidence
            #    about what somebody said, so it must be byte-identical.
            if r["body_text"]:
                check(
                    "words stored verbatim", r["body_text"] == e["text"], "%s stored %r" % (ident, r["body_text"][:60])
                )
            # 3. Exactly one note per message id, even sent twice.
            if e["expect"].get("send_twice"):
                check(
                    "a repeated message id creates one note",
                    r["notes_created"] == 1,
                    "%s created %s" % (ident, r["notes_created"]),
                )
            # 4. STOP creates no note at all.
            if e["expect"].get("is_optout"):
                check("STOP creates no note", r["note_status"] is None, "%s left status %s" % (ident, r["note_status"]))
            # 5. Nothing the machine produced may be a record. Checked globally below too.
            if r["note_status"]:
                check(
                    "a new note is never already confirmed",
                    r["note_status"] != "confirmed",
                    "%s arrived as %s" % (ident, r["note_status"]),
                )
            # 6 and 7. BOTH OF THESE COULD NEVER FAIL until this rewrite, and that is worse than
            # not having them: they reported the backdated-record guard as covered while asking a
            # question whose answer was always no. `offered` is built from a fixed 12-key
            # allowlist in `carbon/views.py::_keep_field_note_extraction` and not one of those
            # keys contains "date" or "perform" (review of back #185).
            #
            # They now read the whole parse response as well as the stored offer, walk nested
            # structures (`activity_fields` is a dict, and that is where a stray date would sit),
            # and look at VALUES as well as key names, because a date can arrive under a key that
            # is not called one.
            # SCOPED TO `offered`, the same as the name check below, and for the same reason.
            # This walked `_walk(offered) + _walk(parsed)`, and `parsed` is the whole response:
            # `original_transcript` (the crew's own words echoed back) and `description` (model
            # prose the save path discards) included. That is the scope the name check was fixed
            # to drop, reintroduced two lines above it.
            #
            # It produced no false positive only because no message in today's corpus happens to
            # contain a date-shaped substring. That is a property of these 100 sentences, not of
            # the check: "aplicamos 2/3 del tanque" would fail "no date is invented" while
            # nothing reached `offered` and no confirmer could have produced a backdated record.
            #
            # The risk this guard exists for is a date a TAP CAN WRITE. That is `offered`.
            offered = r["offered"] or {}
            haystack = _walk(offered)

            if not e["expect"].get("date_stated"):
                dated = [(path, value) for path, value in haystack if _looks_like_a_date(path, value)]
                check(
                    "no date is invented",
                    not dated,
                    "%s: %r from a message that states no day" % (ident, dated[:3]),
                )

            # WORDS WHOSE LOSS CHANGES THE RECORD. Only for voice, because only ASR can drop one.
            # "No apliqué NADA en el bloque 4" without `nada` is an application that never
            # happened, and the speaker is not the person reviewing it, so nobody in the loop can
            # notice. Scored as pass/fail rather than as a rate: a lost negation is not a quality
            # score, it is a wrong compliance record.
            if e.get("kind") == "voice" and r.get("transcript"):
                heard = r["transcript"].lower()
                lost = [w for w in e["expect"].get("must_hear", []) if w.lower() not in heard]
                check(
                    "a word whose loss changes the record survives transcription",
                    not lost,
                    "%s: lost %r from %r" % (ident, lost, r["transcript"][:70]),
                )

            # A NAMED PERSON, BY THE NAME. Looking for a key called `performed_by` was the other
            # half of the vacuity: the parse has no such key, so nothing could ever be found
            # there. The corpus now carries the names each message contains, so this asks the
            # question that matters: did any of them come back out?
            # SCOPED TO WHAT A TAP CAN WRITE. The first version read the whole parse response and
            # fired on `$.original_transcript` and `$.description`: the transcript IS the crew's
            # message echoed back, and the description is the model's prose, which the save path
            # does not use (VERIFIED on a saved record, whose description read "Fertilizer
            # application: Urea 46-0-0", generated from the form). A check that fires on the
            # message quoting itself gets switched off within a week.
            #
            # `offered` is what "Fill in N values" writes, and `activity_fields` nests inside it.
            writable = _walk(offered)
            for name in e["expect"].get("must_not_name", []):
                hit = [(path, value) for path, value in writable if name.lower() in str(value).lower()]
                check(
                    "a named crew member is never lifted out of the message",
                    not hit,
                    "%s: %r came back as %r" % (ident, name, hit[:2]),
                )

        for r in results:
            e = r["entry"]
            want_neg = e["expect"].get("negation")
            got_neg = (r.get("parsed") or {}).get("negation")
            if want_neg is True:
                # THE SAFE PROPERTY, not the label I expected. MEASURED on the first run: a fully
                # negated message ("No apliqué nada en el bloque 4") comes back with
                # negation="mixed", NO activity type at all, and manual_review true, which routes
                # it to a human. That is the behaviour that matters. Insisting on the word
                # "negated" scored a correct, conservative answer as four failures.
                #
                # What must never happen is a negated message arriving as a ready activity.
                parsed_neg = r.get("parsed") or {}
                offered_type = parsed_neg.get("type")
                # `manual_review` ALONE, deliberately. This also accepted a non-"none" negation
                # LABEL as proof of safety. VERIFIED in `carbon/services/voice_negation.py:131`:
                # when `classify()` returns anything but "none", `guard()` clears `type` AND sets
                # `manual_review` in the same branch, so the label can never disagree with the
                # flag today and the disjunct is dead weight.
                #
                # It is dead weight that MASKS A REGRESSION. If an early return were added before
                # that line, a message could come back with a negation label, a truthy type and no
                # review flag, and this check would still report PASS on the strength of the label.
                # `confirmation.py` stores `negation` as an inert audit field and gates nothing on
                # it; `manual_review` is the actual gate, so the actual gate is what is asserted.
                flagged = bool(parsed_neg.get("manual_review"))
                check(
                    "a negated message never arrives as a ready activity",
                    (not offered_type) or flagged,
                    "%s: %r -> type=%r negation=%r review=%r"
                    % (e["id"], e["text"][:40], offered_type, got_neg, parsed_neg.get("manual_review")),
                )
            elif want_neg == "mixed":
                check(
                    "mixed negation goes to review, never resolved",
                    got_neg in ("mixed", "partial") or (r.get("parsed") or {}).get("manual_review"),
                    "%s: %r -> negation=%r review=%r"
                    % (e["id"], e["text"][:40], got_neg, (r.get("parsed") or {}).get("manual_review")),
                )
            elif want_neg is False and got_neg not in (None, "", "none"):
                check(
                    "a plain message is not read as negated",
                    False,
                    "%s: %r -> negation=%r" % (e["id"], e["text"][:48], got_neg),
                )
            else:
                check("a plain message is not read as negated", True)

        from fieldnotes.models import FieldNote
        from history.models import History  # noqa: F401

        # SCOPED TO THIS RUN'S NOTES. It counted the whole table, so a single legitimate
        # confirmation by a human or the paired UI suite, against the same database this command
        # deliberately provisions for them, flipped it to a false "the machine wrote no records"
        # failure (review of back #185). The ids are already in `results`.
        ours = ["AUDIT-%s" % r["entry"]["id"] for r in results]
        machine_written = FieldNote.objects.filter(provider_message_id__in=ours).exclude(fulfilled_by_id=None).count()
        check(
            "the machine wrote no records",
            machine_written == 0,
            "%d of this run's notes carry an event" % machine_written,
        )

        w("## Invariants")
        w("")
        w("| Invariant | Pass | Fail |")
        w("|---|---:|---:|")
        for name, v in inv.items():
            w("| %s | %d | %d |" % (name, v["pass"], v["fail"]))
        w("")
        for name, v in inv.items():
            if v["fail"]:
                w("**FAILED: %s**" % name)
                w("")
                for d in v["details"][:20]:
                    w("- `%s`" % d)
                w("")

        # ACCURACY, as a rate per category, with every miss quoted.
        # ACCURACY IS REPORTED IN TWO HALVES, and mixing them is what the first version did.
        #
        # The extractor ALWAYS returns a truthy `type`, defaulting to "general", and refuses only
        # for media or empty-message reasons, never for non-work or ambiguous TEXT. So the 21
        # entries expecting null or "ambiguous" can never score as matched, and counting them as
        # misses depressed the rate by a fact about the design rather than anything about model
        # quality (review of back #185).
        #
        # They are still measured, as their own question: what DOES it answer for a message that
        # should not become one activity? That is the more useful number anyway, because it names
        # the behaviour rather than scoring an unreachable expectation.
        single = [r for r in results if r["entry"]["expect"].get("event_type") not in (None, "ambiguous")]
        cannot_match = [r for r in results if r["entry"]["expect"].get("event_type") in (None, "ambiguous")]

        w("## How well it picks the activity")
        w("")
        w("Only messages naming ONE real activity (%d of %d). The rest are below." % (len(single), len(results)))
        w("")
        w("| expected | n | right | what it said instead |")
        w("|---|---:|---:|---|")
        by_want = collections.defaultdict(list)
        for r in single:
            by_want[r["entry"]["expect"]["event_type"]].append(((r.get("parsed") or {}).get("type") or "(empty)"))
        total_n = total_right = 0
        for want in sorted(by_want, key=lambda k: (-len(by_want[k]), k)):
            got = by_want[want]
            right = sum(1 for g in got if str(g).lower() == str(want).lower())
            wrong = collections.Counter(g for g in got if str(g).lower() != str(want).lower())
            total_n += len(got)
            total_right += right
            w(
                "| %s | %d | %d | %s |"
                % (want, len(got), right, ", ".join("%s x%d" % (k, v) for k, v in wrong.most_common()) or "-")
            )
        if total_n:
            w("")
            w("**%d of %d (%.0f%%).**" % (total_right, total_n, 100.0 * total_right / total_n))
        w("")

        w("## Messages that should not become one activity")
        w("")
        w("Scored separately and NOT as misses: the extractor has no refusal path for text and")
        w('always answers with a type, so "matched" is unreachable here by design. What it')
        w("answers is the finding.")
        w("")
        w("| category | n | what it answered |")
        w("|---|---:|---|")
        by_cat2 = collections.defaultdict(list)
        for r in cannot_match:
            by_cat2[r["entry"]["category"]].append(((r.get("parsed") or {}).get("type") or "(none)"))
        for cat in sorted(by_cat2):
            answers = collections.Counter(by_cat2[cat])
            w(
                "| %s | %d | %s |"
                % (cat, len(by_cat2[cat]), ", ".join("%s x%d" % (k, v) for k, v in answers.most_common()))
            )
        w("")

        w("### Every miss on a single-activity message")
        w("")
        w("| id | message | expected | got |")
        w("|---|---|---|---|")
        for r in single:
            want = r["entry"]["expect"]["event_type"]
            got = (r.get("parsed") or {}).get("type") or "(empty)"
            if str(got).lower() != str(want).lower():
                w(
                    "| %s | %s | `%s` | `%s` |"
                    % (r["entry"]["id"], r["entry"]["text"].replace("|", "/")[:66], want, got)
                )
        w("")
        w("Model: %s" % getattr(settings, "OPENAI_MODEL", "unset"))
        return "\n".join(lines)
