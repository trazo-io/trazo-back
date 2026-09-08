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
