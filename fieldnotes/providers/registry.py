"""Slug to adapter. One route, one view, a provider per entry."""

from django.http import Http404

from fieldnotes.providers.twilio import TwilioWhatsAppAdapter

ADAPTERS = {TwilioWhatsAppAdapter.slug: TwilioWhatsAppAdapter}


def adapter_for(slug):
    """The adapter for `slug`, or 404. An unknown provider is not a route we serve."""
    try:
        return ADAPTERS[slug]
    except KeyError:
        raise Http404(f"Unknown field-notes provider {slug!r}")
