"""Replying to the crew member who sent a note.

WHAT WAS MISSING. Nothing in this app ever sent a message back. A crew member whose recording could
not be read got silence, and `CrewSender.first_contact_at` and `consented_at` were columns with no
writer: the notice they exist to record had no sender behind it. The operator attested to consent on
the roster page and the person it was about was never actually told anything.

WHY IT CAN BE BUILT NOW, when the model comment said it could not. That comment read "the automated
first-contact notice needs outbound sending, which needs template approval outside Twilio's
sandbox". VERIFIED against Twilio's WhatsApp documentation on 2026-09-29: an inbound message opens a
24-hour customer service window, and inside it "text and media messages require no templates and no
WhatsApp approval". Every message in this module is a reply to something that just arrived, so every
one of them is inside that window by construction. Templates are for business-INITIATED messages,
and this app sends none. See the note on `OutboundAdapter`.

FOUR RULES.

1. NEVER RAISE. The caller chain starts at an anonymous webhook where an uncaught exception is a
   500, and a 500 makes the provider redeliver. Same rule as `services/arrival.py`.

2. NEVER REPLY TO A STRANGER. An unrostered number gets silence, for the reason written at that
   branch in `views.py`: a reply would confirm to anyone who found the number that it is a live
   Trazo line, and would make this endpoint a way to send messages to arbitrary phones. Everything
   here takes a `CrewSender` or a number that was just proven to be on a roster.

3. NEVER STATE THE PRACTICE BACK. A reply says a message arrived or could not be read. It never
   repeats what the person reported and never says what Trazo made of it, for the reason in
   `services/arrival.py`: a machine echoing "you sprayed block 4" is an assertion about a farming
   event that no human has confirmed, and it would turn the supervisor's confirm into a rubber
   stamp on something already read back as fact.

4. ONLY WHERE RESENDING HELPS. A refusal caused by Trazo's own configuration
   (`media_auth_unconfigured`) is never sent to the crew member. Asking somebody to send a recording
   again because a key is missing on our side wastes their time and hides our fault.

THE COPY LIVES HERE, NOT IN A LOCALE FILE. `USE_I18N` is on but this project has no `LOCALE_PATHS`
and no compiled catalogues, so `gettext` in the backend returns English and nothing else. The three
languages below are the three `CrewSender.LANGUAGE_CHOICES` serves, and a test pins them to that
list so a fourth language cannot be added to the roster without copy to go with it.
"""

import logging

from django.db import transaction
from django.utils import timezone

from fieldnotes.models import CrewSender, FieldNote
from fieldnotes.providers.registry import adapter_for

logger = logging.getLogger(__name__)

EN = "en-US"
ES = "es-419"
PT = "pt-BR"

# es-419 is NEUTRAL TUTEO, never voseo, and the farm word is "finca" rather than "granja": the same
# register the app's own Spanish is held to, guarded on the frontend by `spanishRegister.test.ts`.
FIRST_CONTACT = {
    EN: (
        "This is Trazo, the record book {farm} keeps. What you send to this number is written "
        "down automatically and read by someone at the farm, who decides what becomes a record. "
        "Voice notes are transcribed by Deepgram and read by OpenAI to suggest one; the recording "
        "is deleted once it has been reviewed. You are not recorded as the person who did the "
        "work. Reply STOP to end this at any time."
    ),
    ES: (
        "Soy Trazo, el cuaderno de registros que lleva {farm}. Lo que envíes a este número se "
        "escribe automáticamente y lo lee una persona de la finca, que decide qué se registra. "
        "Las notas de voz las transcribe Deepgram y las lee OpenAI para sugerir un registro; la "
        "grabación se borra una vez revisada. No quedas registrado como la persona que hizo el "
        "trabajo. Responde STOP para terminar cuando quieras."
    ),
    PT: (
        "Aqui é o Trazo, o caderno de registros que {farm} mantém. O que você enviar para este "
        "número é escrito automaticamente e lido por alguém da fazenda, que decide o que vira "
        "registro. As notas de voz são transcritas pelo Deepgram e lidas pela OpenAI para sugerir "
        "um registro; a gravação é apagada depois da revisão. Você não fica registrado como a "
        "pessoa que fez o trabalho. Responda STOP para encerrar quando quiser."
    ),
}

STOP_CONFIRMED = {
    EN: "Stopped. Trazo will not read anything else you send to this number. Tell your supervisor if that was a mistake.",
    ES: "Listo. Trazo ya no va a leer nada más de lo que envíes a este número. Avísale a tu supervisor si fue un error.",
    PT: "Pronto. O Trazo não vai mais ler nada que você enviar para este número. Avise seu supervisor se foi um engano.",
}

# Refusal buckets. Several server-side reasons want the same thing from the sender, and a message
# per reason would be nine strings in three languages saying four things.
RESEND = "resend"
IN_WORDS = "in_words"
LANGUAGE = "language"
LIMIT = "limit"

# ⛔ `media_auth_unconfigured` is deliberately absent: see rule 4 above. A reason that is not in this
# map sends nothing, which is the safe default for a reason added server-side before its copy.
REFUSAL_BUCKET = {
    "media_unavailable": RESEND,
    "transcription_failed": RESEND,
    "nothing_heard": RESEND,
    "unsupported_media": IN_WORDS,
    "empty_message": IN_WORDS,
    "language_not_supported": LANGUAGE,
    "voice_daily_limit": LIMIT,
}

REFUSAL_COPY = {
    RESEND: {
        EN: "That recording could not be read. Please send it again.",
        ES: "No se pudo leer esa grabación. Envíala de nuevo, por favor.",
        PT: "Não foi possível ler essa gravação. Envie de novo, por favor.",
    },
    IN_WORDS: {
        EN: "That arrived without a message. Please describe it in words.",
        ES: "Eso llegó sin mensaje. Descríbelo en palabras, por favor.",
        PT: "Isso chegou sem mensagem. Descreva em palavras, por favor.",
    },
    LANGUAGE: {
        EN: "That message was not in English, Spanish or Portuguese, so it could not be read. Please send it in one of those.",
        ES: "Ese mensaje no estaba en español, inglés ni portugués, así que no se pudo leer. Envíalo en uno de esos idiomas.",
        PT: "Essa mensagem não estava em português, inglês ou espanhol, então não pôde ser lida. Envie em um desses idiomas.",
    },
    LIMIT: {
        EN: "The farm has reached its voice notes for today. It resets tomorrow.",
        ES: "La finca ya alcanzó su límite de notas de voz por hoy. Se reinicia mañana.",
        PT: "A fazenda já atingiu o limite de notas de voz de hoje. Ele reinicia amanhã.",
    },
}


def _copy(table, language):
    """The string for this language, falling back to English.

    A fallback rather than a KeyError: a roster row carrying a language this module has no copy for
    should still get told something, and a webhook is the wrong place to raise. The test that pins
    these tables to `LANGUAGE_CHOICES` is what stops the fallback becoming the normal case.
    """
    return table.get(language) or table[EN]


def _send(provider, to_e164, body):
    """One message out. Returns whether the provider took it. Never raises."""
    try:
        adapter = adapter_for(provider)
        return bool(adapter.send_text(to_e164, body))
    except Exception:
        logger.exception("field-notes: reply failed")
        return False


def _farm_label(sender):
    """What to call the operation in the notice.

    The establishment when the roster row names one the company actually owns, otherwise the
    company. `filing_establishment` is used rather than `establishment` for the reason given at its
    definition: a roster row may name a farm belonging to another operation, and putting that name
    in a message would disclose one company's farm to another company's crew.
    """
    establishment = sender.filing_establishment
    if establishment is not None and getattr(establishment, "name", ""):
        return establishment.name
    return getattr(sender.company, "name", "") or "Trazo"


def notify_first_contact(sender, provider):
    """Tell this person, once, what happens to what they send. Returns True if a message went out.

    `provider` is passed in rather than read off the roster row, because a `CrewSender` has none:
    which provider to answer on is decided by the webhook that just received the message, and a
    stored preference would be a second source of truth that could disagree with it.

    CLAIMED BEFORE IT IS SENT, then released if the send fails. Two deliveries can arrive at once,
    and the alternative orderings are both worse: sending before stamping lets both of them send,
    and stamping without releasing on failure loses the notice permanently for somebody whose data
    is about to be processed. A conditional UPDATE is the claim, so only one caller can win it.
    """
    claimed = CrewSender.objects.filter(pk=sender.pk, first_contact_at__isnull=True).update(
        first_contact_at=timezone.now(), updated_at=timezone.now()
    )
    if not claimed:
        return False

    body = _copy(FIRST_CONTACT, sender.language).format(farm=_farm_label(sender))
    if _send(provider, sender.phone_e164, body):
        return True

    CrewSender.objects.filter(pk=sender.pk).update(first_contact_at=None, updated_at=timezone.now())
    return False


def record_consent(sender):
    """Stamp the message AFTER the notice as the unambiguous "I read it and kept going".

    Sends nothing. It is here rather than in the view because the meaning of the stamp is this
    module's subject, and because the two halves have to agree on the ordering: consent can only be
    recorded for somebody who was actually told, which is what the `first_contact_at` filter says.
    """
    return bool(
        CrewSender.objects.filter(pk=sender.pk, first_contact_at__isnull=False, consented_at__isnull=True).update(
            consented_at=timezone.now(), updated_at=timezone.now()
        )
    )


def confirm_stop(provider, phone_e164, language):
    """Acknowledge an opt-out.

    ⛔ ONLY CALL THIS WHEN A ROSTER ROW WAS ACTUALLY STOPPED. A stranger texting "stop" at this
    number must get silence like any other stranger, or the reply confirms the line is live. The
    caller proves it by passing the count of rows it just updated.
    """
    return _send(provider, phone_e164, _copy(STOP_CONFIRMED, language))


def notify_refusal(note):
    """Tell the sender their message could not be turned into anything, when resending would help.

    Silent for a reason with no bucket, which covers both Trazo's own misconfiguration and any
    reason added server-side before its copy lands.
    """
    if note.status != FieldNote.REFUSED:
        return False

    bucket = REFUSAL_BUCKET.get(note.refusal_reason or "")
    if bucket is None:
        return False

    sender = note.sender
    language = sender.language if sender is not None else EN
    return _send(note.provider, note.sender_phone, _copy(REFUSAL_COPY[bucket], language))


def on_commit(callable_):
    """Run after the write commits, never inside it.

    A reply about a row that a later IntegrityError rolls back is a lie, and this webhook has a real
    concurrent-duplicate path that raises exactly that.
    """
    transaction.on_commit(callable_)
