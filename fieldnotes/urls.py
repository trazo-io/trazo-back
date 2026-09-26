"""One anonymous webhook route, plus the authenticated inbox.

The provider is in the webhook path so a second provider is a new adapter, not a new view.
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from fieldnotes.views import FieldNoteViewSet, inbound_message_webhook

router = DefaultRouter()
router.register(r"field-notes", FieldNoteViewSet, basename="field-note")

urlpatterns = [
    # Anonymous, signature-authenticated. Listed in history/tests/test_anonymous_endpoint_inventory.
    # Declared BEFORE the router so the literal path is never shadowed by the viewset's
    # <public_id> lookup.
    path("field-notes/inbound/<slug:provider>/", inbound_message_webhook, name="fieldnotes_inbound"),
    path("", include(router.urls)),
]
