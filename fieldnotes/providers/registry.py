"""Slug to adapter. One route, one view, a provider per entry."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404

from fieldnotes.providers.twilio import TwilioWhatsAppAdapter

ADAPTERS = {TwilioWhatsAppAdapter.slug: TwilioWhatsAppAdapter}


def adapter_for(slug):
    """The adapter for `slug`, or 404. An unknown provider is not a route we serve."""
    try:
        return ADAPTERS[slug]
    except KeyError:
        raise Http404(f"Unknown field-notes provider {slug!r}")


def active_adapter():
    """The adapter this deployment is wired to, for the one question that has no provider in its URL.

    `settings.FIELD_NOTES_PROVIDER`, resolved through the same table as the webhook so the two can
    never name different adapters.

    RAISES rather than falling back. A slug naming no registered adapter is a deployment mistake, and
    the failure mode of a silent fallback is the one this whole feature keeps running into: the
    roster page would show a confident number from the wrong provider, or an empty one that reads as
    "the channel is not on yet", and nothing would say which. `ImproperlyConfigured` names the
    setting, which is the only thing that can fix it.
    """
    slug = getattr(settings, "FIELD_NOTES_PROVIDER", "")
    try:
        return ADAPTERS[slug]
    except KeyError:
        raise ImproperlyConfigured(
            f"FIELD_NOTES_PROVIDER is {slug!r}, which is not a registered field-notes provider. "
            f"Known providers: {sorted(ADAPTERS)}."
        )
