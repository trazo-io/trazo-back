"""
Storage quota enforcement utilities.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


def check_storage_quota(user, upload_size_bytes):
    """
    Check whether a user's company has sufficient storage quota for an upload.

    Args:
        user: The authenticated Django user.
        upload_size_bytes: Total size of files being uploaded, in bytes.

    Returns:
        tuple: (allowed: bool, error_detail: dict | None)
    """
    try:
        company = user.get_active_company()
        if not company:
            return False, {
                "error": "No active subscription found. Please subscribe to upload files.",
                "code": "NO_SUBSCRIPTION",
            }

        storage_limit_gb = company.get_storage_limit_gb()

        # Unlimited storage (-1) = always allow
        if storage_limit_gb == -1:
            return True, None

        # No plan or zero limit = block
        if storage_limit_gb <= 0:
            return False, {
                "error": "Your plan does not include file storage. Please upgrade your plan.",
                "code": "NO_STORAGE_ALLOWANCE",
            }

        if not hasattr(company, "subscription"):
            return False, {
                "error": "No active subscription found.",
                "code": "NO_SUBSCRIPTION",
            }

        # Compute real-time usage for accuracy
        from subscriptions.serializers import SubscriptionSerializer

        serializer = SubscriptionSerializer()
        used_gb = serializer._compute_used_storage_gb(company.subscription)

        upload_size_gb = Decimal(upload_size_bytes) / Decimal(1024 * 1024 * 1024)
        projected_usage = used_gb + upload_size_gb

        if projected_usage > Decimal(str(storage_limit_gb)):
            remaining_gb = max(Decimal("0"), Decimal(str(storage_limit_gb)) - used_gb)
            return False, {
                "error": (
                    f"Storage limit exceeded. "
                    f"You have {float(remaining_gb):.2f} GB remaining "
                    f"out of {storage_limit_gb} GB."
                ),
                "code": "STORAGE_QUOTA_EXCEEDED",
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
