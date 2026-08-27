"""Per-company daily ceiling on billable voice sessions.

Answers the question "what happens if a farmer makes a lot of voice requests?" — which,
before 2026-08-26, was: nothing stops them. The two voice endpoints that cost money
(`deepgram-token`, which mints a Deepgram key and opens a metered stream, and
`process-voice-event`, which calls OpenAI) inherited only DRF's global ``user: 500/hour``
throttle, and that throttle is inert whenever the cache is DummyCache — the deploy shape
this project falls back to when REDIS_URL is unset.

Design notes, and why it is not simply a DRF throttle:

* **Durable.** Counted in Postgres, so it holds with or without Redis and survives restarts.
* **Per company, not per user.** The bill is per operation; a farm with six accounts should
  not get six budgets.
* **A ceiling, not a rate.** Bursts are normal — a farmer walks a block logging ten things
  in five minutes. Runaway cost is not. This is the shape Otter/Granola/Fathom use (monthly
  minutes per plan) reduced to its cheapest useful form.
* **Fails OPEN on an internal error.** A farmer must never lose the ability to log a record
  because a counter table misbehaved; the events are the product. Cost control is worth a
  ceiling, not an outage.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Sessions per company per UTC day. Generous against real use — a heavy logging day is
#: tens of entries, not hundreds — and a hard stop on a loop. Override per environment.
DEFAULT_DAILY_VOICE_SESSIONS = 200


def daily_limit() -> int:
    return int(getattr(settings, "VOICE_DAILY_SESSION_LIMIT", DEFAULT_DAILY_VOICE_SESSIONS))


def consume_voice_session(company) -> tuple[bool, int, int]:
    """Count one billable voice session against ``company``'s day.

    Returns ``(allowed, used, limit)``. ``used`` is the count INCLUDING this session when
    allowed, so a caller can surface "12 of 200".
    """
    from carbon.models import VoiceUsageDay

    limit = daily_limit()
    if limit <= 0:  # 0 or negative disables the ceiling entirely
        return True, 0, limit

    today = timezone.now().date()
    try:
        with transaction.atomic():
            row, _ = VoiceUsageDay.objects.select_for_update().get_or_create(
                company=company, day=today, defaults={"session_count": 0}
            )
            if row.session_count >= limit:
                return False, row.session_count, limit
            # F() rather than row.session_count + 1: two tabs starting a recording at the
            # same moment would otherwise both read N and both write N+1.
            VoiceUsageDay.objects.filter(pk=row.pk).update(session_count=F("session_count") + 1)
            return True, row.session_count + 1, limit
    except Exception:
        # See the module docstring: never block a farmer from logging because of this.
        logger.exception("Voice budget accounting failed for company=%s; allowing the session", company.pk)
        return True, 0, limit
