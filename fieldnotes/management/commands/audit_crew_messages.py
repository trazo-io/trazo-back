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
    DATABASE_NAME=trazo_fnaudit poetry run python manage.py audit_crew_messages \
        --seed --out /path/to/report.md
"""

import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
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

    # -- driving -------------------------------------------------------------------------------

    def _post(self, client, body, message_id, from_number="+15095550123"):
        params = {
            "From": "whatsapp:" + from_number,
            "To": "whatsapp:+15092045054",
            "Body": body,
            "MessageSid": message_id,
            "NumMedia": "0",
        }
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
                "transcript": note.body_text,
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

    def handle(self, *args, **options):
        from django.test import override_settings

        from fieldnotes.models import CrewSender, FieldNote

        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        entries = corpus["entries"]
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
            started = time.time()

            for i, entry in enumerate(entries, 1):
                before = FieldNote.objects.count()
                msg_id = "AUDIT-%s" % entry["id"]
                # The opt-out is delivered from its OWN number. STOP deactivates every roster row
                # for the sender it came from, so running it on the shared number would silently
                # unroster the rest of the corpus. It is the last entry today, which means the
                # ordering is load-bearing unless the number is separated. It is separated here.
                from_number = "+15095550199" if entry["category"] == "optout" else "+15095550123"
                response = self._post(client, entry["text"], msg_id, from_number=from_number)

                # The duplicate category is the point of the category: same id twice.
                dup_status = None
                if entry["expect"].get("send_twice"):
                    dup_status = self._post(client, entry["text"], msg_id).status_code
                if entry["expect"].get("resend_new_id"):
                    dup_status = self._post(client, entry["text"], msg_id + "-RESEND").status_code

                note = FieldNote.objects.filter(provider_message_id=msg_id).first()
                parse_status, parse_body = (None, {})
                if note and note.body_text:
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
            # 6. No invented date. The offer may carry a date ONLY when the message stated one.
            offered = r["offered"] or {}
            has_date = any(k for k in offered if "date" in str(k).lower() and offered[k])
            if not e["expect"].get("date_stated"):
                check("no date is invented", not has_date, "%s offered %r" % (ident, offered))
            # 7. A named worker never reaches performed_by.
            if e["expect"].get("must_not_set") == "performed_by":
                leaked = any("perform" in str(k).lower() and offered[k] for k in offered)
                check("a named worker never fills performed_by", not leaked, "%s offered %r" % (ident, offered))

        for r in results:
            e = r["entry"]
            want_neg = e["expect"].get("negation")
            got_neg = (r.get("parsed") or {}).get("negation")
            if want_neg is True:
                check(
                    "a negated message is read as negated",
                    got_neg in ("negated", "full", "all", "yes"),
                    "%s: %r -> negation=%r" % (e["id"], e["text"][:48], got_neg),
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

        machine_written = FieldNote.objects.exclude(fulfilled_by_id=None).count()
        check("the machine wrote no records", machine_written == 0, "%d notes carry an event" % machine_written)

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
        w("## Extraction, by category")
        w("")
        w("| Category | n | parsed | refused | event type matched |")
        w("|---|---:|---:|---:|---:|")
        by_cat = collections.defaultdict(list)
        for r in results:
            by_cat[r["entry"]["category"]].append(r)
        misses = []
        for cat in sorted(by_cat):
            rows = by_cat[cat]
            parsed = sum(1 for r in rows if (r.get("parsed") or {}).get("type"))
            refused = sum(1 for r in rows if r["note_status"] == "refused")
            matched = 0
            for r in rows:
                want = r["entry"]["expect"].get("event_type")
                parse_body = r.get("parsed") or {}
                got = parse_body.get("type")
                if want in (None, "ambiguous"):
                    ok = not got or r["note_status"] == "refused"
                else:
                    ok = str(got or "").lower() == str(want).lower()
                matched += 1 if ok else 0
                if not ok:
                    misses.append((r["entry"]["id"], cat, r["entry"]["text"], want, got))
            w("| %s | %d | %d | %d | %d |" % (cat, len(rows), parsed, refused, matched))
        w("")
        if misses:
            w("### Every event-type miss")
            w("")
            w("| id | category | message | expected | got |")
            w("|---|---|---|---|---|")
            for mid, cat, text, want, got in misses:
                w("| %s | %s | %s | `%s` | `%s` |" % (mid, cat, text.replace("|", "/")[:70], want, got))
            w("")
        w("Model: %s" % getattr(settings, "OPENAI_MODEL", "unset"))
        return "\n".join(lines)
