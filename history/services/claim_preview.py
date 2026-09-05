"""Dry run of the buyer-page input claim, for a draft the grower has not saved yet.

🔴 2026-09-03, found on camera. The activity wizard's Preview ("How shoppers will see this
activity") renders ``ConsumerEventCard`` over the form's own values. The organic chip is the one
thing on that card the CLIENT is forbidden to decide: ``ORGANIC_STATUS_KEYS`` maps every
``organic_approved`` value to the grower-reported wording, because the browser cannot see the
OMRI or WSDA catalogs and a self-report must never be spoken in a third party's name
(``claim_authority.may_claim_input_listing``, 2026-08-09).

The consequence was a preview that could not tell the truth in either direction. A grower who
had just attached the OMRI listing for Entrust opened Preview and read
"Organic-approved · grower-reported" — a FALSE NEGATIVE, on the screen whose entire job is to
show what the saved page will show, and directly under a heading promising exactly that.

The fix is not to teach the client the rule (that re-opens the 2026-08-09 defect). It is to ask
the server the same question the saved record will be asked, before the record exists. Every
answer here comes from the same chokepoint the public payload uses:

  * ``auto_classify_chemical_against_national_list`` — the pre_save receiver that resolves a
    § 205.601/602 citation from the product name and active ingredient. It is a pure function of
    an UNSAVED instance, so running it here reproduces the saved record's National List match
    exactly rather than approximating it.
  * ``claim_resolver.resolve_input_status`` — which asks ``may_claim_input_listing`` and orders
    the severity tiers.

⛔ Nothing in this module decides a claim. If it ever starts to, the chokepoint has two doors.
"""

import logging

logger = logging.getLogger(__name__)


def _valid_catalog_id(model, value):
    """A catalog primary key the caller sent, or None.

    The draft payload is client-supplied, so an id is a CLAIM about a catalog row until the row
    is shown to exist. An unknown id resolves to None rather than to a listing: a bogus number
    must not earn "OMRI Listed" in the preview, or the preview becomes the easiest place in the
    product to manufacture a third-party claim.
    """
    # `isinstance(value, bool)` first: `True == 1`, so a client sending `omri_product: true`
    # would otherwise be read as a lookup of primary key 1.
    if isinstance(value, bool) or value in (None, "", 0):
        return None
    try:
        pk = int(value)
    except (TypeError, ValueError):
        return None
    return pk if model.objects.filter(pk=pk).exists() else None


def preview_input_status(draft):
    """The ``input_status`` the public serializer would emit for this draft chemical event.

    ``draft`` is a plain dict of the wizard's own field names. Returns the same
    ``{"status": ..., "label": ...}`` shape ``resolve_input_status`` returns for a saved event,
    so the preview card can render it through the existing status → i18n-key map with no second
    vocabulary.
    """
    from certifications.models import OMRIProduct, WSDAMaterial
    from history.models import ChemicalEvent
    from history.services.claim_resolver import resolve_input_status
    from history.signals import auto_classify_chemical_against_national_list

    commercial_name = str(draft.get("commercial_name") or "").strip()
    active_ingredient = str(draft.get("active_ingredient") or "").strip()

    event = ChemicalEvent(
        commercial_name=commercial_name,
        organic_approved=str(draft.get("organic_approved") or "").strip(),
        restricted_use_pesticide=bool(draft.get("restricted_use_pesticide")),
        omri_product_id=_valid_catalog_id(OMRIProduct, draft.get("omri_product")),
        wsda_material_id=_valid_catalog_id(WSDAMaterial, draft.get("wsda_material")),
        # The classifier reads the active ingredient out of extra_data, exactly as the saved
        # write path stores it. Same input, same match.
        extra_data={"active_ingredient": active_ingredient} if active_ingredient else {},
    )

    # The National List citation the record WILL carry. Advisory on save (the receiver swallows
    # its own errors); advisory here too, for the same reason — a catalog that is not seeded
    # must degrade the chip, never 500 the preview.
    try:
        auto_classify_chemical_against_national_list(ChemicalEvent, event)
    except Exception:  # noqa: BLE001
        logger.exception("Input-status preview could not classify %r against the National List", commercial_name)

    return resolve_input_status(event)
