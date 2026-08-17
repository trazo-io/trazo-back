"""Storage quota enforcement.

Two categories, two behaviours — the rationale for the split (and for which one is
enforced) lives in `subscriptions.storage_accounting`. In short:

* ``MEDIA`` — photo evidence. HARD limit; the upload is refused at the ceiling.
* ``DOCUMENTS`` — the DMS shelf. Counted toward the meter, never refused. Generated
  documents cannot be deleted, there is no storage add-on to sell, and a certificate
  upload that fails during renewal week is the exact failure the paid tier exists to
  prevent. The per-file cap in `documents.serializers` bounds the pathological case
  instead of a category-wide wall.

Both categories still require a subscription: no plan means no storage at all.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

CATEGORY_MEDIA = "media"
CATEGORY_DOCUMENTS = "documents"

# Categories whose usage is refused once it passes the plan ceiling. Membership of this
# set is the whole enforcement policy — adding a category here makes it blockable, and
# nothing else in the codebase has to change.
HARD_LIMITED_CATEGORIES = {CATEGORY_MEDIA}


def check_storage_quota(user, upload_size_bytes, category=CATEGORY_MEDIA, company=None):
    """Check whether a company may store `upload_size_bytes` more.

    Args:
        user: The authenticated Django user.
        upload_size_bytes: Total size of files being uploaded, in bytes.
        category: `CATEGORY_MEDIA` (hard limit) or `CATEGORY_DOCUMENTS` (soft, counted).
        company: The company the upload belongs to. Pass it whenever the caller knows —
            see below.

    Returns:
        tuple: (allowed: bool, error_detail: dict | None)
    """
    try:
        # Prefer the company the CALLER resolved.
        #
        # `get_active_company()` returns the first company the user belongs to that has an
        # active subscription — which for a multi-company user is not necessarily the one
        # this upload is for. That silently measured one farm's quota and charged it to
        # another. Any endpoint that already scopes to a company (the DMS is nested under
        # `/companies/{c}/…`) should say so rather than let the helper guess.
        company = company or user.get_active_company()
        if not company:
            return False, {
                "error": "No active subscription found. Please subscribe to upload files.",
                "code": "NO_SUBSCRIPTION",
            }

        # "No plan" is checked BEFORE the limit, not inferred from it.
        #
        # `get_storage_limit_gb()` returns 0 for a company with no plan AND for a plan that
        # grants no storage, so reading the limit first collapsed two different situations
        # into one message — a company whose subscription lapsed was told to "upgrade your
        # plan" for storage, which is not what went wrong and not what fixes it.
        # `subscription_plan` is None unless the subscription is active or trialing, so this
        # also catches a canceled row rather than trusting `hasattr`.
        if company.subscription_plan is None:
            return False, {
                "error": "No active subscription found.",
                "code": "NO_SUBSCRIPTION",
            }

        storage_limit_gb = company.get_storage_limit_gb()

        # Unlimited storage (-1) = always allow
        if storage_limit_gb == -1:
            return True, None

        # A live plan that grants no storage at all. No current plan is in this shape;
        # the branch exists so a future one cannot leak uploads by omitting the key.
        if storage_limit_gb <= 0:
            return False, {
                "error": "Your plan does not include file storage. Please upgrade your plan.",
                "code": "NO_STORAGE_ALLOWANCE",
            }

        # A soft category is let through here, AFTER the subscription checks above and
        # before any usage is computed. Computing it would be wasted work: no value of
        # `used_gb` changes the answer.
        if category not in HARD_LIMITED_CATEGORIES:
            return True, None

        from subscriptions.storage_accounting import media_storage_bytes

        # MEDIA usage only, not the total.
        #
        # Measuring the total here would move the dead end rather than remove it: a farm
        # whose DOCUMENTS alone exceed the plan would find its photo uploads refused, with
        # nothing it could delete to recover — generated documents are immutable dated
        # history. The hard ceiling has to be measured against the category that can
        # actually be pruned.
        used_gb = round(Decimal(media_storage_bytes(company)) / Decimal(1024 * 1024 * 1024), 2)

        upload_size_gb = Decimal(upload_size_bytes) / Decimal(1024 * 1024 * 1024)
        projected_usage = used_gb + upload_size_gb

        if projected_usage > Decimal(str(storage_limit_gb)):
            remaining_gb = max(Decimal("0"), Decimal(str(storage_limit_gb)) - used_gb)
            return False, {
                "error": (
                    f"Photo storage limit reached. "
                    f"You have {float(remaining_gb):.2f} GB remaining "
                    f"out of {storage_limit_gb} GB."
                ),
                "code": "STORAGE_QUOTA_EXCEEDED",
                "category": CATEGORY_MEDIA,
                "used_gb": float(used_gb),
                "limit_gb": float(storage_limit_gb),
                "remaining_gb": float(remaining_gb),
                "upload_size_gb": float(upload_size_gb),
            }

        return True, None

    except Exception as e:
        logger.error("Error checking storage quota: %s", str(e))
        # Fail open -- do not block uploads due to quota check errors
        return True, None
