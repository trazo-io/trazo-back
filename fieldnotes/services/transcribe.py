"""Bytes to text, for a voice note that arrived over WhatsApp.

WHY THIS EXISTS WHEN THE APP ALREADY TRANSCRIBES SPEECH. The in-app voice flow mints a 60-second
Deepgram key and the BROWSER streams straight to Deepgram (`carbon/views.py::deepgram_token`), so
Trazo never receives audio at all and needs no server-side path. There is no browser in the loop
here: the recording sits at the provider, so the server fetches it and posts it itself.

THE BYTES ARE NEVER WRITTEN TO DISK. They are fetched into memory, posted to Deepgram, and dropped.
The recording stays at the provider, which enforces Basic auth on its media URLs, and confirm or
discard deletes it there. Writing them to Trazo's default storage would publish them: the bucket
policy on `trazo-media` grants public `s3:GetObject` with `AWS_QUERYSTRING_AUTH = False`.

TWO DEEPGRAM SETTINGS ARE NOT NEGOTIABLE HERE:

  * ⛔ NEVER `smart_format`. On this project it DELETES WORDS from finals, which was measured
    2026-09-10. `numerals=true` is the replacement for the part of it that was wanted.
  * `detect_language=true`, because a WhatsApp message carries no language tag. The result is mapped
    to a family the parser actually serves and REFUSED otherwise, rather than parsed as English:
    `prompt_key_for` silently falls back to the English prompt, English keywords and an English
    numeral table for anything it does not know, so a Spanish note read as English is a wrong parse
    presented with full confidence.
"""

import logging

from django.conf import settings

import requests

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

# Hosts a media reference may point at.
#
# The URL is written from the provider's own webhook payload, and only the provider can sign a
# request, so this is defence behind the signature rather than instead of it. It matters because the
# consequence of trusting that payload is SSRF: a media reference is fetched SERVER-SIDE with
# credentials attached, so a URL naming an internal address would make this function a way to read
# the metadata service or a private port and hand the body to whoever can reach the playback view.
# A signature check answers "did Twilio send this", not "is this URL safe to fetch".
ALLOWED_MEDIA_HOSTS = (
    "api.twilio.com",
    "media.twiliocdn.com",
    "mcs.us1.twilio.com",
)

# The families `carbon/services/ai_voice_processor.py::prompt_key_for` actually serves. Deepgram
# returns a bare language code ("es", "en", "pt-BR"); the prefix is what decides the prompt.
SUPPORTED_LANGUAGES = {
    "en": "en-US",
    "es": "es-419",
    "pt": "pt-BR",
}


class TranscriptionRefused(Exception):
    """Carries the farmer-readable reason, which is the only thing the inbox shows."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def language_for(detected):
    """Deepgram's code to a locale the parser serves, or None.

    None means refuse. ⛔ Deepgram's `multi` is NOT a parser language and must never be passed
    through: it means "several", and the parser needs one.
    """
    if not detected:
        return None
    code = str(detected).strip().lower()
    if code == "multi":
        return None
    return SUPPORTED_LANGUAGES.get(code.split("-")[0])


def unconfigured_reason():
    """Why this pipeline cannot run at all, or None. Checked BEFORE the budget is charged.

    FROM REVIEW OF #54, and it is a repeat of a bug already fixed once. `carbon/views.py` moved its
    own charge below the key check with the note "charging above it meant a server with no Deepgram
    key burned a farm's daily budget on requests that returned an error and cost nothing". The same
    ordering was reintroduced here, outside the reach of the guard in `carbon/tests/test_voice_budget`.

    It matters more here than there, because this is the SAME `VoiceUsageDay` row the in-app voice
    flow spends: a deployment with no Deepgram key would let inbound WhatsApp notes exhaust the
    company's daily units on work that cannot succeed, and take in-app voice logging down with it. A
    deployment without a Deepgram key is an explicitly supported shape.
    """
    if not getattr(settings, "TWILIO_ACCOUNT_SID", "") or not getattr(settings, "TWILIO_AUTH_TOKEN", ""):
        return "media_auth_unconfigured"
    if not getattr(settings, "DEEPGRAM_API_KEY", ""):
        return "voice_not_enabled"
    return None


def media_host_allowed(url):
    """Is this a provider media host? Compared on the PARSED host, never with a substring test.

    `"api.twilio.com" in url` would accept `https://evil.test/?x=api.twilio.com` and
    `https://api.twilio.com.evil.test/`, which is the whole family of mistakes this kind of check
    exists to make and then makes anyway.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    return parsed.hostname in ALLOWED_MEDIA_HOSTS


def fetch_media(url, *, timeout=None):
    """The audio bytes, from the provider, with Basic auth.

    Twilio enforces HTTP Basic authentication on every media URL, which is exactly why the recording
    can stay there instead of being copied somewhere public. Account SID as the username, auth token
    as the password: the token is already required for signature verification, so no second
    credential has to be rotated.
    """
    account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    if not media_host_allowed(url):
        logger.warning("field-notes: refusing to fetch media from an unexpected host")
        raise TranscriptionRefused("media_unavailable")

    if not account_sid or not auth_token:
        # A configuration failure, named as one. Without this the request 401s and the note would be
        # refused as unreadable audio, which sends the operator to ask the crew to re-record
        # something that was never the problem.
        raise TranscriptionRefused("media_auth_unconfigured")

    response = requests.get(
        url,
        auth=(account_sid, auth_token),
        timeout=timeout or getattr(settings, "DEEPGRAM_TIMEOUT_SECONDS", 30.0),
        # Twilio 307s media URLs to the storage host. Redirects are followed, and the auth header is
        # not carried across hosts by `requests`, which is correct: the redirect target is presigned.
        allow_redirects=True,
    )
    if response.status_code != 200:
        logger.warning("field-notes: media fetch returned %s", response.status_code)
        raise TranscriptionRefused("media_unavailable")
    return response.content


def transcribe(audio, *, content_type="audio/ogg"):
    """`(transcript, locale)` for these bytes, or raise TranscriptionRefused.

    An empty transcript is a refusal rather than an empty note: Deepgram answering with silence means
    nobody can review anything, and a blank card in the queue says less than "we could not read it".
    """
    api_key = getattr(settings, "DEEPGRAM_API_KEY", "")
    if not api_key:
        raise TranscriptionRefused("voice_not_enabled")

    try:
        response = requests.post(
            DEEPGRAM_URL,
            params={
                "model": "nova-3",
                # See the module docstring. `smart_format` deletes words on this project.
                "numerals": "true",
                "detect_language": "true",
            },
            headers={"Authorization": f"Token {api_key}", "Content-Type": content_type or "audio/ogg"},
            data=audio,
            timeout=getattr(settings, "DEEPGRAM_TIMEOUT_SECONDS", 30.0),
        )
    except requests.RequestException:
        logger.exception("field-notes: Deepgram request failed")
        raise TranscriptionRefused("transcription_failed")

    if response.status_code != 200:
        logger.warning("field-notes: Deepgram returned %s", response.status_code)
        raise TranscriptionRefused("transcription_failed")

    try:
        payload = response.json()
        channel = payload["results"]["channels"][0]
        alternative = channel["alternatives"][0]
        transcript = (alternative.get("transcript") or "").strip()
        detected = channel.get("detected_language") or payload["results"].get("detected_language")
    except (KeyError, IndexError, ValueError, TypeError):
        logger.exception("field-notes: could not read the Deepgram response")
        raise TranscriptionRefused("transcription_failed")

    if not transcript:
        raise TranscriptionRefused("nothing_heard")

    locale = language_for(detected)
    if not locale:
        # Refusing beats guessing. The supervisor is told the language was not one Trazo reads, which
        # is a thing they can act on, rather than being handed a confident wrong parse.
        logger.info("field-notes: refusing a transcript in an unsupported language %r", detected)
        raise TranscriptionRefused("language_not_supported")

    return transcript, locale


def stream_media(url, *, timeout=None):
    """A streaming response for these bytes, for the authenticated playback proxy.

    Streamed rather than loaded, because a WhatsApp voice note runs to 16MB and holding one per
    concurrent listener in a gthread worker is how a 2x4 web process falls over.
    """
    if not media_host_allowed(url):
        logger.warning("field-notes: refusing to stream media from an unexpected host")
        raise TranscriptionRefused("media_unavailable")

    account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    if not account_sid or not auth_token:
        raise TranscriptionRefused("media_auth_unconfigured")

    response = requests.get(
        url,
        auth=(account_sid, auth_token),
        timeout=timeout or getattr(settings, "DEEPGRAM_TIMEOUT_SECONDS", 30.0),
        stream=True,
        allow_redirects=True,
    )
    if response.status_code != 200:
        raise TranscriptionRefused("media_unavailable")
    return response


def delete_media(url):
    """Delete the recording at the provider. Returns True when it is gone (or already was).

    This is what makes "the audio is kept only while the note is pending" a fact rather than an
    intention. Twilio keeps media until it is deleted through the API, so a note that is confirmed or
    discarded and never cleaned up leaves the recording there indefinitely.

    404 counts as deleted: the goal is that it is not there, and a retry after a partial failure must
    not report failure forever.
    """
    if not media_host_allowed(url):
        return False
    account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    if not account_sid or not auth_token:
        return False
    try:
        response = requests.delete(
            url,
            auth=(account_sid, auth_token),
            timeout=getattr(settings, "DEEPGRAM_TIMEOUT_SECONDS", 30.0),
        )
    except requests.RequestException:
        logger.exception("field-notes: could not delete provider media")
        return False
    if response.status_code in (204, 200, 404):
        return True
    logger.warning("field-notes: provider refused the media delete with %s", response.status_code)
    return False
