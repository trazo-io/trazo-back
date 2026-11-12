"""Close a company's account: export everything, then delete everything (OV-CLM-C06, 2026-11-11).

WHAT THE PRIVACY POLICY PROMISES, AND WHAT THIS MODULE MAKES TRUE
-----------------------------------------------------------------
On an emailed request (privacy policy 7.1, terms 13): confirm the request, send the farm an export
of its records and its uploaded files, take published consumer pages down at once, and delete the
account and its data within 30 days. The five-year record keeping of 7 CFR 205.103(b)(4) is the
certified OPERATION's duty, not Trazo's, so after the export it is theirs to keep.

Until this existed the promise had nothing behind it, and the obvious tool would have done it
wrong: `Company.delete()` cascades in bulk, which (a) leaves every uploaded file in S3, because
Django never deletes storage objects with rows, (b) leaves event photo albums behind, because the
FK points FROM the record TO `common.Gallery`, so deleting the record does not reach the album,
(c) leaves voice recordings at Twilio, and (d) leaves the audit log, which stores the actor's email
and IP address, describing rows that no longer exist.

THE FLOW, IN THE ORDER THE COMMAND ENFORCES IT
----------------------------------------------
1. `plan(company)` is read-only: what would go, counted per table, plus files and people.
2. `export(company)` writes ONE ZIP (each farm's records as CSV, every uploaded file, a manifest) to
   private storage under `account-closures/`, and returns its key.
3. `apply(company, ...)` refuses unless that export exists. Then it unpublishes, releases the crew
   recordings, deletes the rows in one transaction, and only after the commit deletes the files.
   The export itself is removed 30 days later by `purge_closure_exports` (daily maintenance).

WHO IS DELETED. Users whose only membership is this company. A user who also works for another
company keeps their account and loses only this membership, because their account is not this
company's data.

NEVER: bypass `export()`. A closure without an export destroys the only copy of records the farm is
legally required to keep, and that cannot be undone.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Set, Tuple

from django.db import router, transaction
from django.db.models import FileField
from django.db.models.deletion import Collector
from django.utils import timezone

logger = logging.getLogger(__name__)

EXPORT_PREFIX = "account-closures/"
#: How long a closure export stays in storage after it is written (privacy policy 7.1).
EXPORT_RETENTION_DAYS = 30
#: A signed link to the export, for the farm to download. S3 caps SigV4 presigned URLs at 7 days.
EXPORT_LINK_SECONDS = 7 * 24 * 3600


class ClosureRefused(Exception):
    """The closure cannot go ahead as asked; nothing has been changed."""


@dataclass
class ClosurePlan:
    company_id: int
    company_name: str
    rows: Dict[str, int]
    files: List[Tuple[str, str]]  # (storage label, name)
    deleted_users: List[int]
    kept_users: List[int]
    published_seasons: int
    recordings_at_provider: int
    collector: Collector = field(repr=False, default=None)
    galleries: Set[int] = field(default_factory=set)
    #: Rows a PROTECT reference held back, by table, deleted on purpose (see `_collect`).
    protected: Dict[str, int] = field(default_factory=dict)

    def counts(self) -> dict:
        """Counts only. NEVER a name, email, phone or file name: this is what gets logged."""
        return {
            "company_id": self.company_id,
            "rows": dict(sorted(self.rows.items())),
            "row_total": sum(self.rows.values()),
            "files": len(self.files),
            "deleted_users": len(self.deleted_users),
            "kept_users": len(self.kept_users),
            "published_seasons": self.published_seasons,
            "recordings_at_provider": self.recordings_at_provider,
            "protected_rows_included": dict(sorted(self.protected.items())),
        }


def _exclusive_users(company):
    from users.models import User, WorksIn

    member_ids = set(WorksIn.objects.filter(company=company).values_list("user_id", flat=True))
    elsewhere = set(
        WorksIn.objects.filter(user_id__in=member_ids).exclude(company=company).values_list("user_id", flat=True)
    )
    deleted = User.objects.filter(pk__in=member_ids - elsewhere)
    return deleted, sorted(elsewhere)


def _gallery_ids(instances_by_model) -> Set[int]:
    """Albums referenced FROM rows that will be deleted. The FK points outward, so the cascade
    does not reach them, and without this every event photo would outlive its record."""
    ids = set()
    for model, instances in instances_by_model.items():
        for f in model._meta.concrete_fields:
            if f.is_relation and f.related_model is not None and f.related_model._meta.label == "common.Gallery":
                ids.update(getattr(obj, f.attname) for obj in instances if getattr(obj, f.attname))
    return ids


@contextmanager
def _protect_cascades(counter: Counter):
    """While collecting a closure, follow PROTECT and RESTRICT like CASCADE, counting what each
    one reaches.

    PROTECT is how this codebase marks a filed record (an annual update revision, a signed
    affidavit) so that no ordinary delete can erase it. A closure is the one delete that should:
    those rows are this company's own, each points at a row in its cascade, and their PDFs are in
    the export. Django raises ProtectedError even when the protecting row is itself being deleted,
    so retrying cannot help; the handler has to change for the duration of the collect.

    NEVER call this from a request or any threaded code: it swaps `on_delete` on the model fields
    for the whole process. `close_account` is a single-threaded management command, and the
    original handlers are restored in `finally`.
    """
    from django.apps import apps
    from django.db.models import CASCADE, PROTECT, RESTRICT

    def _counting_cascade(collector, field, sub_objs, using):
        counter[field.model._meta.label] += len(sub_objs)
        CASCADE(collector, field, sub_objs, using)

    swapped = []
    for model in apps.get_models(include_auto_created=True):
        for f in model._meta.concrete_fields:
            remote = getattr(f, "remote_field", None)
            if remote is not None and getattr(remote, "on_delete", None) in (PROTECT, RESTRICT):
                swapped.append((remote, remote.on_delete))
                remote.on_delete = _counting_cascade
    try:
        yield
    finally:
        for remote, original in swapped:
            remote.on_delete = original


def _collect(company):
    """Everything to delete, as one Collector: the company, the users who belong only to it, the
    photo albums its rows point at, and the filed rows a PROTECT would have held back."""
    from common.models import Gallery

    users, kept = _exclusive_users(company)
    users = list(users)
    using = router.db_for_write(type(company))
    protected = Counter()
    gallery_ids = set()
    while True:
        collector = Collector(using=using)
        protected.clear()
        with _protect_cascades(protected):
            collector.collect([company])
            if users:
                collector.collect(users)
            if gallery_ids:
                collector.collect(list(Gallery.objects.filter(pk__in=gallery_ids)))
        found = _gallery_ids(collector.data) - gallery_ids
        if not found:
            return collector, users, kept, gallery_ids, dict(protected)
        gallery_ids |= found


def _rows(collector) -> Counter:
    rows = Counter()
    for model, instances in collector.data.items():
        rows[model._meta.label] += len(instances)
    for qs in collector.fast_deletes:
        rows[qs.model._meta.label] += qs.count()
    return rows


def _instances(collector):
    for model, instances in collector.data.items():
        yield model, instances
    for qs in collector.fast_deletes:
        yield qs.model, list(qs)


def _files(collector) -> List[Tuple[object, str]]:
    """Every stored file the deleted rows point at, with the storage that holds it."""
    from django.core.files.storage import default_storage

    found = []
    seen = set()
    for model, instances in _instances(collector):
        file_fields = [f for f in model._meta.concrete_fields if isinstance(f, FileField)]
        for obj in instances:
            for f in file_fields:
                value = getattr(obj, f.attname)
                if value and (f.storage, value) not in seen:
                    seen.add((f.storage, value))
                    found.append((f.storage, str(value)))
            # Photos uploaded to S3 first and recorded by key or by URL (common.GalleryImage).
            if model._meta.label == "common.GalleryImage":
                for key in _gallery_image_keys(obj):
                    if (default_storage, key) not in seen:
                        seen.add((default_storage, key))
                        found.append((default_storage, key))
    return found


def _gallery_image_keys(image) -> List[str]:
    """Storage keys a gallery image holds outside its ImageField: the uploaded key, thumbnail
    keys, and an `image_url` on Trazo's own bucket. A URL on any other host is not ours to delete."""
    from urllib.parse import urlparse

    from django.conf import settings

    keys = [image.s3_key] if image.s3_key else []
    if isinstance(image.thumbnails, dict):
        keys += [k for k in image.thumbnails.values() if isinstance(k, str) and k]
    if image.image_url:
        parsed = urlparse(image.image_url)
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or ""
        if bucket and parsed.netloc.startswith(f"{bucket}.s3"):
            keys.append(parsed.path.lstrip("/"))
    return keys


def plan(company) -> ClosurePlan:
    from history.models import History

    collector, users, kept, gallery_ids, protected = _collect(company)
    files = _files(collector)
    return ClosurePlan(
        company_id=company.pk,
        company_name=company.name,
        rows=dict(_rows(collector)),
        files=[(type(storage).__name__, name) for storage, name in files],
        deleted_users=[u.pk for u in users],
        kept_users=kept,
        published_seasons=History.objects.filter(parcel__establishment__company=company, published=True).count(),
        recordings_at_provider=_recordings(company).count(),
        collector=collector,
        galleries=gallery_ids,
        protected=protected,
    )


def _recordings(company):
    from fieldnotes.models import FieldNote

    return FieldNote.objects.filter(company=company, kind=FieldNote.VOICE, audio_deleted_at__isnull=True).exclude(
        provider_media_ref=""
    )


def export_key(company, day=None) -> str:
    day = day or timezone.now().date()
    return f"{EXPORT_PREFIX}company-{company.pk}-{day:%Y%m%d}.zip"


def find_export(company):
    """The newest closure export for this company still in storage, or None."""
    from backend.storage import private_records_storage

    storage = private_records_storage()
    try:
        _dirs, names = storage.listdir(EXPORT_PREFIX.rstrip("/"))
    except FileNotFoundError:
        return None
    mine = sorted(n for n in names if n.startswith(f"company-{company.pk}-") and n.endswith(".zip"))
    return f"{EXPORT_PREFIX}{mine[-1]}" if mine else None


def fingerprint(p: ClosurePlan) -> str:
    """What the export was taken from: every row to be deleted (table, id, last change) and every
    file. `apply` recomputes it and refuses on a difference, so a record added or edited between
    `--export` and `--apply` (the normal, human-paced gap) can never be deleted unexported."""
    import hashlib

    parts = []
    for model, instances in _instances(p.collector):
        stamp = "updated_at" if any(f.name == "updated_at" for f in model._meta.concrete_fields) else None
        for obj in instances:
            parts.append(f"{model._meta.label}:{obj.pk}:{getattr(obj, stamp, '') if stamp else ''}")
    parts += [f"file:{name}" for _storage, name in p.files]
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()


def read_manifest(key) -> dict:
    from backend.storage import private_records_storage

    with private_records_storage().open(key, "rb") as fh:
        with zipfile.ZipFile(io.BytesIO(fh.read())) as bundle:
            return json.loads(bundle.read("manifest.json"))


def export(company, allow_missing_files: bool = False) -> str:
    """Write the closure export and return its storage key. Records per farm, every file, a manifest.

    Refuses, writing nothing, when a file cannot be read from storage (review of #398: an S3 outage
    during the export would otherwise produce an export that `apply` accepts and a delete of files
    that were never captured). `allow_missing_files` is for a file already known to be gone, and the
    manifest records that the gap was accepted."""
    from django.core.files.base import ContentFile

    from backend.storage import private_records_storage
    from history.services.records_export import export_establishment_records_zip

    p = plan(company)
    buffer = io.BytesIO()
    missing = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for establishment in company.establishment_set.all().order_by("pk"):
            bundle.writestr(f"records/farm-{establishment.pk}.zip", export_establishment_records_zip(establishment))
        for storage, name in _files(p.collector):
            try:
                with storage.open(name, "rb") as fh:
                    bundle.writestr(f"files/{name.lstrip('/')}", fh.read())
            except Exception:  # noqa: BLE001 - collected, then refused below unless accepted
                missing.append(name)
        if missing and not allow_missing_files:
            raise ClosureRefused(
                f"{len(missing)} file(s) could not be read from storage, so nothing was written. Retry, "
                f"or pass --allow-missing-files if they are known to be gone: {missing[:5]}"
            )
        bundle.writestr(
            "manifest.json",
            json.dumps(
                {
                    "company": company.name,
                    "exported_at": timezone.now().isoformat(),
                    "farms": company.establishment_set.count(),
                    "files": len(p.files) - len(missing),
                    "files_missing_from_storage": missing,
                    "missing_files_accepted": bool(missing and allow_missing_files),
                    "fingerprint": fingerprint(p),
                    "note": (
                        "Your organic records and uploaded files from Trazo. The USDA organic "
                        "regulations require a certified operation to keep its records for five "
                        "years (7 CFR 205.103(b)(4)); keep this file for that period."
                    ),
                },
                indent=1,
            ),
        )
    storage = private_records_storage()
    key = export_key(company)
    if storage.exists(key):
        storage.delete(key)
    return storage.save(key, ContentFile(buffer.getvalue()))


def export_link(key) -> str:
    from backend.storage import private_records_storage

    storage = private_records_storage()
    try:
        return storage.url(key, expire=EXPORT_LINK_SECONDS)
    except TypeError:  # FileSystemStorage (dev, tests) takes no expiry
        return storage.url(key)


def apply(company, confirm_name: str, run_by: str = "") -> dict:
    """Delete the company and everything that is only its own. Refuses without an export."""
    from django.contrib.contenttypes.models import ContentType

    from auditlog.context import disable_auditlog
    from auditlog.models import LogEntry

    from common.models import DataOperationLog
    from history.models import History

    if confirm_name != company.name:
        raise ClosureRefused("The confirmation name does not match the company name exactly.")
    key = find_export(company)
    if not key:
        raise ClosureRefused("No closure export exists for this company. Run --export first and send it.")
    p = plan(company)
    manifest = read_manifest(key)
    if manifest.get("fingerprint") != fingerprint(p):
        raise ClosureRefused(
            "Records or files changed since the export was written, so the farm's copy is incomplete. "
            "Run --export again and send the new file before deleting."
        )
    if manifest.get("files_missing_from_storage") and not manifest.get("missing_files_accepted"):
        raise ClosureRefused("The export is missing files and that was never accepted. Run --export again.")

    # Public pages first and outside the transaction: if anything below fails, the pages are still
    # down, which is what the policy says happens "straight away". Unpublishing is reversible; the
    # recordings are not, so they are released only after the rows are gone (below).
    unpublished = History.objects.filter(parcel__establishment__company=company, published=True).update(published=False)
    recording_refs = list(_recordings(company).values_list("provider_media_ref", flat=True))

    files = _files(p.collector)
    audit_targets = []
    for model, instances in _instances(p.collector):
        ct = ContentType.objects.get_for_model(model, for_concrete_model=False)
        audit_targets.append((ct, [str(o.pk) for o in instances]))

    with transaction.atomic():
        deleted_audit = 0
        for ct, pks in audit_targets:
            for start in range(0, len(pks), 1000):
                deleted_audit += LogEntry.objects.filter(
                    content_type=ct, object_pk__in=pks[start : start + 1000]
                ).delete()[0]
        if p.deleted_users:
            deleted_audit += LogEntry.objects.filter(actor_id__in=p.deleted_users).delete()[0]
        # NEVER delete with the audit log on: it writes a DELETE entry per registered row, carrying
        # the row's serialised fields and the actor's email, which re-creates the personal data
        # this is removing.
        with disable_auditlog():
            p.collector.delete()
        counts = {
            **p.counts(),
            "published_seasons": unpublished,
            "audit_entries": deleted_audit,
        }
        DataOperationLog.objects.create(
            operation="close_account",
            action=DataOperationLog.ACTION_APPLY,
            report_sha256="",
            counts=counts,
            run_by=run_by,
        )

    # After the commit, like the files: a failed delete above must not have destroyed audio that
    # was never exported (review of #398).
    from fieldnotes.services.transcribe import delete_media

    released, recordings_failed = 0, []
    for ref in recording_refs:
        try:
            if delete_media(ref):
                released += 1
            else:
                recordings_failed.append(ref)
        except Exception:  # noqa: BLE001 - reported for a retry, the rows are already gone
            recordings_failed.append(ref)
    counts["recordings_released"] = released
    counts["recordings_not_released"] = len(recordings_failed)
    if recordings_failed:
        logger.error("close_account company=%s: %d recording(s) not released", p.company_id, len(recordings_failed))

    failed = []
    for storage, name in files:
        try:
            storage.delete(name)
        except Exception:  # noqa: BLE001 - reported for a retry, the rows are already gone
            failed.append(name)
    if failed:
        logger.error("close_account company=%s: %d file(s) not deleted from storage", p.company_id, len(failed))
    counts["files_not_deleted"] = failed
    return counts


def purge_old_exports(days: int = EXPORT_RETENTION_DAYS, dry_run: bool = False) -> List[str]:
    """Delete closure exports older than `days`. Returns the keys removed (or that would be)."""
    from backend.storage import private_records_storage

    storage = private_records_storage()
    try:
        _dirs, names = storage.listdir(EXPORT_PREFIX.rstrip("/"))
    except FileNotFoundError:
        return []
    cutoff = timezone.now() - timedelta(days=days)
    removed = []
    for name in names:
        key = f"{EXPORT_PREFIX}{name}"
        if storage.get_modified_time(key) < cutoff:
            if not dry_run:
                storage.delete(key)
            removed.append(key)
    return removed
