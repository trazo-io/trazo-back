"""Producer-facing dry run of the buyer-page input claim (see services/claim_preview.py)."""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .services.claim_preview import preview_input_status

#: The wizard fields that can change what a shopper is told about an input. Everything else on
#: the draft is irrelevant to the claim and is not read — an allow-list rather than a passthrough,
#: so this endpoint cannot grow into a general "evaluate arbitrary event data" surface.
_DRAFT_KEYS = (
    "commercial_name",
    "active_ingredient",
    "organic_approved",
    "restricted_use_pesticide",
    "omri_product",
    "wsda_material",
)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def input_status_preview(request):
    """Answer, for an UNSAVED chemical event, exactly what the buyer page will say about it.

    Reads nothing from the database except the two input catalogs, writes nothing, and belongs
    to no farm — the draft is the whole input. Authenticated because it is a producer tool and
    the catalogs are licensed reference data, not because it exposes tenant records.

    Response is the same ``{"status", "label"}`` object the public serializer puts on every
    chemical event, so ``ConsumerEventCard`` renders the preview through its existing map.
    """
    payload = request.data if isinstance(request.data, dict) else {}
    draft = {key: payload.get(key) for key in _DRAFT_KEYS}
    return Response(preview_input_status(draft), status=status.HTTP_200_OK)
