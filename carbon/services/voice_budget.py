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

#: Sessions per company per UTC day when the plan does not name its own. Generous against real
#: use — a heavy logging day is tens of entries, not hundreds — and a hard stop on a loop.
DEFAULT_DAILY_VOICE_SESSIONS = 200

#: The plan feature that carries a tier's ceiling, alongside `max_establishments`,
#: `max_productions_per_year` and `storage_limit_gb`. Same conventions as those: `-1` is
#: unlimited, and a plan that does not name it falls back to the environment setting.
VOICE_LIMIT_FEATURE = "voice_daily_sessions"


def daily_limit(company=None) -> int:
    """The ceiling that applies to ``company``, or the environment default without one.

    WHY THIS IS PER PLAN. Voice is ON for the free tier, deliberately (see migration 0014: the
    measured barriers to farm software adoption are time and labour ahead of price, so gating the
    fastest gloves-on input path suppresses the logging that produces the records that produce the
    upgrade). But every tier shared ONE ceiling, so the bound on a company paying nothing was the
    same as the bound on one paying $1,200: a single Starter account sitting at 200 sessions a day
    is roughly $700 a year of metered audio against $0 of revenue. The ceiling is the only thing
    standing between the free tier and that number, so it belongs to the plan.

    Read through `get_feature_limit`, which returns the default when a company has no plan at all —
    a company in that state never reaches here anyway, because BOTH voice endpoints
    (`process_voice_event_ai` and `get_deepgram_token`) require `has_feature("voice_recording")`
    first.

    ⚠️ `VOICE_DAILY_SESSION_LIMIT` IS NOW A FALLBACK, NOT A LEVER. Before the plans named their
    own ceilings, lowering that variable capped every company immediately — the thing you reach
    for when a vendor bill spikes at 2am. A plan value now wins over it, so that lever would have
    quietly stopped working exactly when it was needed. `VOICE_DAILY_SESSION_HARD_CAP` restores
    it: unset by default (nothing changes), and when set it caps every company regardless of plan.
    """
    fallback = int(getattr(settings, "VOICE_DAILY_SESSION_LIMIT", DEFAULT_DAILY_VOICE_SESSIONS))
    hard_cap = getattr(settings, "VOICE_DAILY_SESSION_HARD_CAP", None)

    def _capped(value: int) -> int:
        # An emergency cap only ever LOWERS. A hard cap above a plan's ceiling would be someone
        # accidentally granting budget from an environment variable, which is the opposite of
        # what this exists for.
        if hard_cap is None or int(hard_cap) <= 0:
            return value
        # `-1` (unlimited) has to be capped too, or the one plan that most needs bounding in an
        # incident is the one the lever cannot touch.
        if value < 0:
            return int(hard_cap)
        return min(value, int(hard_cap))

    if company is None:
        return _capped(fallback)

    try:
        limit = company.get_feature_limit(VOICE_LIMIT_FEATURE, fallback)
        # ⛔ A BOOLEAN IS NOT A CEILING. `int(True)` is 1, and this dict is mostly booleans
        # (`voice_recording`, `priority_support`, `compliance_exports`…), so `True` pasted into
        # this key would silently hand a farm ONE voice session a day — a misconfiguration that
        # looks like a broken microphone from the field and like nothing at all from here.
        if isinstance(limit, bool):
            raise TypeError("boolean is not a session count")
        # A plan that stores the key as a string ("200") must not disable the ceiling by
        # arriving as something int() refuses; a bad value falls back rather than failing open.
        return _capped(int(limit))
    except (TypeError, ValueError, AttributeError):
        logger.warning(
            "Unreadable %s for company=%s; using the environment default",
            VOICE_LIMIT_FEATURE,
            getattr(company, "pk", None),
        )
        return _capped(fallback)


def consume_voice_session(company) -> tuple[bool, int, int]:
    """Count one billable voice session against ``company``'s day.

    Returns ``(allowed, used, limit)``. ``used`` is the count INCLUDING this session when
    allowed, so a caller can surface "12 of 50" against whichever ceiling the plan carries.
    """
    from carbon.models import VoiceUsageDay

    limit = daily_limit(company)
    # 0 or negative disables the ceiling entirely — which is also how `-1` (the codebase's
    # "unlimited" for every other plan limit) arrives here, so the two conventions agree.
    #
    # ⚠️ Disabled also means NOT COUNTED: no `VoiceUsageDay` row is written, so an unlimited plan
    # is invisible to anything reading that table to watch spend. No plan ships `-1` today
    # (Operation is 1,000, not unlimited) — but a future one that does would go dark rather than
    # merely uncapped, and that is a decision to make deliberately, not to discover.
    if limit <= 0:
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
