"""
Background document builds — enqueue, run, reuse, reap.

The shape (2026-09-05): a request creates an `ExportJob` row and returns immediately; a runner
builds the document, files it in the DMS through the same `file_document()` seam every
generator uses, marks the job succeeded and tells the requester (in-app notification plus an
email carrying a LINK — never the file: a whole-operation dossier can run to tens of MB, is
stale the moment the next event is logged, and an inbox copy of a revocable certifier artifact
is a copy nobody can revoke). Clients poll the job until it is terminal, then download the
document from the Documents shelf like any other filed artifact.

Three runners, one env var (`EXPORT_JOB_RUNNER`):
  * ``thread`` (default) — the web process starts a daemon thread after the enqueue commits.
    No extra infrastructure; the job row makes the build recoverable: if the process dies
    (gunicorn --max-requests, a deploy), the heartbeat goes stale and `reap_stale()` fails the
    job with a reason the farmer can read instead of a spinner that never ends.
  * ``worker`` — the web process only enqueues; `manage.py run_export_worker` claims jobs with
    SELECT … FOR UPDATE SKIP LOCKED. Postgres is the queue; no Redis, no Celery. This is the
    setting for a separate DO worker component.
  * ``eager`` — the build runs inside the enqueue call. Tests and one-off debugging only.

Reuse: `fresh_document()` returns the newest succeeded build whose fingerprint still matches
the establishment's records, so the certifier link opens instantly when nothing changed and
rebuilds when something did. "Always current" is preserved by construction.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from documents.models import ExportJob
from documents.services.filing import file_document

logger = logging.getLogger(__name__)

OPERATION_DOSSIER = "operation_dossier"

# Human titles for the shelf + notifications. Keyed by kind so a second job kind ships by
# adding a builder below and a row here, not by editing every call site.
KIND_TITLES = {
    OPERATION_DOSSIER: "Operation audit dossier",
}


def _runner_mode() -> str:
    return getattr(settings, "EXPORT_JOB_RUNNER", "thread")


def _stale_after() -> timedelta:
    return timedelta(minutes=int(getattr(settings, "EXPORT_JOB_STALE_MINUTES", 10)))


def job_key(*, kind=OPERATION_DOSSIER, certification_type="organic", period_start=None, period_end=None) -> dict:
    """Normalise the parameters that make two builds interchangeable."""
    return {
        "kind": kind,
        "certification_type": (certification_type or "organic").lower(),
        "period_start": period_start,
        "period_end": period_end,
    }


# ----------------------------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------------------------


def current_fingerprint(establishment) -> str:
    from history.services.records_fingerprint import records_fingerprint

    return records_fingerprint(establishment)


def fresh_document(establishment, **key):
    """The newest succeeded build for `key` whose fingerprint still matches the records, or
    None. A None means "rebuild" — never "serve a stale copy"."""
    key = job_key(**key)
    fingerprint = current_fingerprint(establishment)
    job = (
        ExportJob.objects.filter(
            establishment=establishment,
            status="succeeded",
            fingerprint=fingerprint,
            document__isnull=False,
            **key,
        )
        .select_related("document")
        .order_by("-finished_at")
        .first()
    )
    return job.document if job is not None else None


def active_job(establishment, **key):
    """A queued or running build for `key`, if one exists — so two clicks (or an anonymous
    link opened twice) share one build instead of starting two."""
    reap_stale(establishment)
    return (
        ExportJob.objects.filter(establishment=establishment, status__in=("queued", "running"), **job_key(**key))
        .order_by("created_at")
        .first()
    )


# ----------------------------------------------------------------------------------------------
# Enqueue + dispatch
# ----------------------------------------------------------------------------------------------


def enqueue(establishment, *, requested_by=None, audience="farmer", **key):
    """Create (or join) the build for `key`. Returns `(job, created)`."""
    existing = active_job(establishment, **key)
    if existing is not None:
        return existing, False
    job = ExportJob.objects.create(
        establishment=establishment,
        requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
        audience=audience,
        **job_key(**key),
    )
    return dispatch(job), True


def dispatch(job):
    """Hand the job to the configured runner. Returns the job — the FINISHED row under the
    eager runner, so a caller can stream the result in the same request."""
    mode = _runner_mode()
    if mode == "eager":
        return run_job(job.pk) or job
    if mode == "thread":
        # After commit, or a thread that starts inside the request's transaction cannot see
        # the row it was asked to run.
        transaction.on_commit(lambda: _start_thread(job.pk))
        return job
    if mode == "worker":
        return job  # run_export_worker will claim it
    raise ValueError(f"Unknown EXPORT_JOB_RUNNER {mode!r} (thread | worker | eager)")


def _start_thread(job_id):
    thread = threading.Thread(target=_thread_main, args=(job_id,), name=f"export-job-{job_id}", daemon=True)
    thread.start()
    return thread


def _thread_main(job_id):
    try:
        run_job(job_id)
    finally:
        # Django opens one connection per thread; a daemon thread that ends without closing
        # it leaks a server-side connection until GC. CONN_MAX_AGE makes that worse, not better.
        connections.close_all()


# ----------------------------------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------------------------------


def claim(job_id):
    """Atomically move ONE queued job to running. None when it was already taken or is not
    queued. SKIP LOCKED means two runners racing for the same row cannot both win it."""
    with transaction.atomic():
        job = (
            # `of=("self",)`: Postgres refuses FOR UPDATE on the nullable side of the outer
            # join that select_related("requested_by") adds; lock only the job row.
            ExportJob.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(pk=job_id, status="queued")
            .select_related("establishment", "requested_by")
            .first()
        )
        if job is None:
            return None
        now = timezone.now()
        job.status = "running"
        job.started_at = now
        job.heartbeat_at = now
        job.save(update_fields=["status", "started_at", "heartbeat_at"])
    return job


def run_job(job_id):
    """Build one job end to end. Never raises: the outcome lands on the row."""
    job = claim(job_id)
    if job is None:
        return ExportJob.objects.filter(pk=job_id).first()
    try:
        builder = BUILDERS[job.kind]
    except KeyError:
        return _fail(job, f"No builder registered for kind {job.kind!r}")
    try:
        # Fingerprint BEFORE the build: a record edited while the pages lay out invalidates
        # this build (the next open rebuilds), which is the safe direction to be wrong in.
        job.fingerprint = current_fingerprint(job.establishment)
        job.save(update_fields=["fingerprint"])
        content, filename, title = builder(job)
        document = file_document(
            establishment=job.establishment,
            source=job.kind,
            folder="exports",
            title=title,
            filename=filename,
            content=content,
            content_type="application/pdf",
            created_by=job.requested_by,
        )
        if document is None:
            raise RuntimeError("The finished document could not be filed in Documents.")
        now = timezone.now()
        job.document = document
        job.status = "succeeded"
        job.progress_current = job.progress_total
        job.progress_label = ""
        job.finished_at = now
        job.heartbeat_at = now
        job.error = ""
        job.save(
            update_fields=[
                "document",
                "status",
                "progress_current",
                "progress_label",
                "finished_at",
                "heartbeat_at",
                "error",
            ]
        )
    except Exception as exc:  # noqa: BLE001 — the outcome must reach the row, whatever it was
        logger.exception("Export job %s failed", job.pk)
        return _fail(job, str(exc) or exc.__class__.__name__)
    _notify(job)
    return job


def _fail(job, reason):
    now = timezone.now()
    job.status = "failed"
    job.error = (reason or "")[:2000]
    job.finished_at = now
    job.heartbeat_at = now
    job.save(update_fields=["status", "error", "finished_at", "heartbeat_at"])
    return job


def _progress_writer(job):
    def progress(current, total, label):
        job.progress_current = int(current)
        job.progress_total = int(total)
        job.progress_label = (label or "")[:200]
        job.heartbeat_at = timezone.now()
        job.save(update_fields=["progress_current", "progress_total", "progress_label", "heartbeat_at"])

    return progress


def _build_operation_dossier(job):
    from history.services.operation_audit_export_service import OperationAuditExportService

    service = OperationAuditExportService(
        job.establishment,
        certification_type=job.certification_type,
        start_date=job.period_start,
        end_date=job.period_end,
    )
    buffer = service.generate_pdf(progress=_progress_writer(job))
    filename = f"trazo-operation-audit-{job.establishment_id}.pdf"
    title = f"{KIND_TITLES[OPERATION_DOSSIER]} ({job.certification_type})"
    return buffer.getvalue(), filename, title


BUILDERS = {
    OPERATION_DOSSIER: _build_operation_dossier,
}


# ----------------------------------------------------------------------------------------------
# Tell the requester
# ----------------------------------------------------------------------------------------------


def documents_page_url(establishment) -> str:
    base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    return f"{base}/admin/dashboard/farm/{establishment.pk}/documents"


def _notify(job):
    """In-app notification + email with a link. Both best-effort: a notification failure must
    never turn a succeeded build into a failed one."""
    recipient = job.requested_by
    if recipient is None:
        return  # an anonymous certifier build; the reviewer is polling the link
    title = KIND_TITLES.get(job.kind, "Document")
    url = documents_page_url(job.establishment)
    try:
        from notifications.models import NotificationPriority, NotificationType
        from notifications.services import NotificationService

        NotificationService().create_notification(
            recipient=recipient,
            notification_type=NotificationType.SYSTEM_ALERT,
            title=f"{title} is ready",
            message=f"Your {title.lower()} for {job.establishment.name} is ready to download.",
            related_object=job.document,
            priority=NotificationPriority.MEDIUM,
            extra_data={
                "kind": "export_ready",
                "establishment_id": job.establishment_id,
                "document_id": job.document_id,
                "job_public_id": str(job.public_id),
                "url": url,
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Export job %s: in-app notification failed", job.pk)
    try:
        from django.core.mail import send_mail
        from django.template.loader import render_to_string

        context = {
            "title": title,
            "establishment": job.establishment,
            "url": url,
            "recipient": recipient,
            "size_mb": round((job.document.size_bytes or 0) / (1024 * 1024), 1) if job.document else None,
        }
        send_mail(
            f"{title} ready — {job.establishment.name}",
            render_to_string("emails/export_ready.txt", context),
            settings.DEFAULT_FROM_EMAIL,
            [recipient.email],
            html_message=render_to_string("emails/export_ready.html", context),
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Export job %s: ready email failed", job.pk)


# ----------------------------------------------------------------------------------------------
# Reaper + worker loop
# ----------------------------------------------------------------------------------------------

INTERRUPTED_MESSAGE = "The build was interrupted before it finished (the server restarted). Start it again."


def reap_stale(establishment=None):
    """Fail every running job whose heartbeat is older than EXPORT_JOB_STALE_MINUTES. Called
    on every status read and by the worker, so a dead build is reported within minutes even
    with no worker process at all."""
    cutoff = timezone.now() - _stale_after()
    qs = ExportJob.objects.filter(status="running", heartbeat_at__lt=cutoff)
    if establishment is not None:
        qs = qs.filter(establishment=establishment)
    return qs.update(status="failed", error=INTERRUPTED_MESSAGE, finished_at=timezone.now())


def next_queued_id():
    return ExportJob.objects.filter(status="queued").order_by("created_at").values_list("pk", flat=True).first()


def run_worker_loop(*, once=False, idle_seconds=2.0, stop=None):
    """Claim and run queued jobs until `stop()` is truthy (or forever). `once=True` drains what
    is queued right now and returns the number of jobs run."""
    ran = 0
    while True:
        reap_stale()
        job_id = next_queued_id()
        if job_id is not None:
            run_job(job_id)
            ran += 1
            continue
        if once or (stop is not None and stop()):
            return ran
        time.sleep(idle_seconds)


def parse_public_id(raw):
    """uuid or None — never a ValueError out of a query."""
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError, AttributeError):
        return None
