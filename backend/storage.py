"""One answer to "are we writing to S3?".

WHY THIS EXISTS (2026-09-07, Django 5.2 upgrade — ADR-010)
----------------------------------------------------------
Four call sites decided whether to hand out an S3 presigned URL or a local media path by
string-comparing a settings attribute:

    if settings.DEFAULT_FILE_STORAGE == "storages.backends.s3boto3.S3Boto3Storage":

`DEFAULT_FILE_STORAGE` was removed in Django 5.1. Under 5.2 it is not deprecated, it is
IGNORED — Django never reads it, so the attribute can say S3 while the actual default
storage is the local filesystem, or vice versa. Every one of those four comparisons was
therefore reading a value that no longer decides anything.

The fix is one function, and it reads the setting Django actually uses. Callers ask a
question about behaviour; they do not reimplement the lookup.
"""

from django.conf import settings

#: The django-storages S3 backend path, as written in every STORAGES dict in settings/.
S3_BACKEND = "storages.backends.s3boto3.S3Boto3Storage"


def using_s3_storage() -> bool:
    """True when default file storage is the S3 backend.

    Reads ``settings.STORAGES``, which is the only source Django consults from 5.1 onward.
    Falls back to False rather than raising if STORAGES is somehow absent — a wrong answer
    here should degrade to "serve a local path", never to a 500 on a page that only wanted
    to build an image URL.
    """
    try:
        return settings.STORAGES["default"]["BACKEND"] == S3_BACKEND
    except (AttributeError, KeyError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Private records (2026-10-01)
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS
# ---------------
# The `trazo-media` bucket policy granted anonymous `s3:GetObject` on every object, and with
# `AWS_QUERYSTRING_AUTH = False` every stored file's URL was a permanent, unauthenticated link.
# That was right for the consumer QR page's photos and wrong for everything else in the bucket:
# certifier packets carrying the signed annual-update filing, affidavits, certificates, OSP PDFs,
# the fraud-prevention plan, support attachments. Verified by an anonymous GET returning 200 on an
# uploaded document; the keys are guessable (`documents/YYYY/MM/<original name>`).
#
# Two halves, and both are needed:
#   * private FileFields use `private_records_storage`, so the URL any serializer returns for them
#     is signed and expires (PRIVATE_URL_EXPIRE_SECONDS);
#   * the bucket policy grants anonymous reads ONLY under PUBLIC_MEDIA_PREFIXES
#     (`infra/s3/trazo-media-bucket-policy.json`, checked by a test against this list). Anything
#     else, including a prefix nobody has invented yet, is private.

#: The only key prefixes anonymous readers may fetch. Consumer-facing images and nothing else.
#: Adding one is a privacy decision: the bucket policy JSON and its test must change with it.
PUBLIC_MEDIA_PREFIXES = (
    "media/",
    "gallery_images/",
    "qr_codes/",
    "company_logos/",
    "product_images/",
    "user_images/",
    "badges/",
)

#: Lifetime of a signed link to a private record. Long enough to open a page and click; short
#: enough that a forwarded or logged link stops working the same day.
PRIVATE_URL_EXPIRE_SECONDS = 900


def private_records_storage():
    """Storage for operator records: signed, expiring URLs on S3; the default storage elsewhere.

    A callable, so migrations record the reference rather than a configured instance, and dev and
    tests (FileSystemStorage) keep working without S3 settings.
    """
    from django.core.files.storage import default_storage

    if not using_s3_storage():
        return default_storage
    from storages.backends.s3boto3 import S3Boto3Storage

    return S3Boto3Storage(
        querystring_auth=True,
        querystring_expire=PRIVATE_URL_EXPIRE_SECONDS,
        default_acl=None,
        file_overwrite=False,
    )


def is_public_media_key(key: str) -> bool:
    """True when `key` sits under a prefix anonymous readers may fetch."""
    key = (key or "").lstrip("/")
    return bool(key) and ".." not in key and key.startswith(PUBLIC_MEDIA_PREFIXES)
