"""One route, with the provider in the path so a second provider is a new adapter, not a new view."""

from django.urls import path

from fieldnotes.views import inbound_message_webhook

urlpatterns = [
    path("field-notes/inbound/<slug:provider>/", inbound_message_webhook, name="fieldnotes_inbound"),
]
