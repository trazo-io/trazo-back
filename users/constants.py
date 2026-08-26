SUPERUSER = 1
STAFF = 2
CONSUMER = 3
PRODUCER = 4
CERTIFIER = 5

USER_TYPE_CHOICES = (
    (SUPERUSER, "Superuser"),
    (STAFF, "Staff"),
    (CONSUMER, "Consumer"),
    (PRODUCER, "Producer"),
    (CERTIFIER, "Certifier"),
)

# ── Auth error codes ────────────────────────────────────────────────────────────────────
#
# Stable machine codes the API returns alongside a human sentence, so the client picks the
# RECOVERY ACTION without parsing English. Named here rather than inline in the serializer
# because three parties have to agree on the literal: the serializer that raises it, the
# guard that asserts it, and `trazo-app/src/views/Authentication/authErrors.ts`, which maps
# it to a translated message. A typo in any one of them silently degrades to the generic
# fallback, which is exactly the failure a shared constant prevents on this side of the wire.
EMAIL_EXISTS_VERIFIED = "email_exists_verified"
EMAIL_EXISTS_UNVERIFIED = "email_exists_unverified"
