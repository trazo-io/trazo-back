"""What counts against a farm's storage, and which half of it is enforced.

## Why this module exists

Storage accounting lived inside `SubscriptionSerializer._compute_used_storage_gb`, and
`storage_utils.check_storage_quota` reached across to call that private method just to
find out how full a farm was. That put the accounting rules in the presentation layer
and gave the enforcement path no way to ask a different question than the meter asked.

It had to ask a different question. The October pivot shipped the DMS
(`documents.GeneratedDocument`) — the farm's document shelf, and the single largest
structural addition to what Trazo stores. The gallery-only sum could not see it, so the
usage meter under-reported by the whole shelf and the quota gate metered one door while
the new one had no lock at all.

## The two categories, and why they are enforced differently

**Media (photo evidence).** Unbounded in volume, farmer-controlled, and the thing a
storage tier is actually sizing. HARD limit: `check_storage_quota` refuses the upload
once projected media usage passes the plan's ceiling. Unchanged behaviour.

**Documents (the DMS).** Certificates, lab results, the OSP renewal packet, the audit
dossier, the CA PUR export. COUNTED but never refused. Three reasons, in order:

1. The product's promise is that everything a certifier asks for lands in one place. A
   refused certificate upload during renewal week is precisely the failure the paid tier
   exists to prevent — it is a worse outcome for Trazo than a farm sitting over quota.
2. Generated documents are immutable dated history (`GeneratedDocument.is_deletable` is
   False for everything the system produced). A farmer who hits a hard ceiling made of
   documents cannot delete their way out of it, and there is no storage add-on to sell
   them — `extra-storage` was retired in migration 0006 and is not coming back at
   $10/month for 1 GB. A hard limit with no exit is a dead end, not a tier.
3. The economics do not support the wall. S3 standard is ~$0.023/GB/month, so the
   entire 25 GB Compliance ceiling costs about $0.58 a month against $20.75 of monthly
   revenue. Storage is not a cost driver at Trazo's scale; it is a shape signal.

The per-file cap and content-type allowlist on `documents.serializers.DocumentUploadSerializer`
are what bound the pathological case instead. A soft category still needs a ceiling on any
SINGLE object.

## Consequence for the block calculation

The hard block measures MEDIA usage against the limit, not total usage. Measuring the
total would reintroduce the dead end one level up: a farm whose documents alone exceed
the plan would find its photo uploads refused with no action available to fix it.

## Known under-count, deliberate

The legacy per-model FileFields (`certifications.OrganicSystemPlan.submission_pdf`,
`cert_document`, `signed_document`, `registration_document`,
`history.transport_affidavit_document`, `company.fraud_prevention_plan_document`, logos,
avatars, support attachments) are NOT summed here. At least one of them is stored twice
on purpose — `certifications/views.py` writes the OSP snapshot to `submission_pdf` AND
files the same bytes into the DMS — so adding both sides would double-count the artifact
rather than fix the gap. The DMS is the unified shelf those fields are migrating toward
(see `documents/models.py`); when a field moves, it starts counting here automatically.
"""

from decimal import Decimal

from django.db.models import Count, Q, Sum

BYTES_PER_GB = Decimal(1024 * 1024 * 1024)

# Fallback for a remote image row whose `file_size` was never populated. Kept at the value
# the gallery sum has always used so the meter does not jump when accounting moves modules.
ESTIMATED_IMAGE_SIZE = 3 * 1024 * 1024


def _bytes_to_gb(total_bytes) -> Decimal:
    return round(Decimal(int(total_bytes)) / BYTES_PER_GB, 2)


def media_storage_bytes(company) -> int:
    """Photo/media evidence across every gallery the company owns. ENFORCED half."""
    if not company:
        return 0

    from common.models import GalleryImage
    from history.models import Production
    from product.models import Parcel

    # Every gallery the company owns — farm, parcel, season and the eight event tables — as ONE
    # UNION round trip. Until 2026-09-06 this was twelve queries (one per source plus a
    # history-id list fed into eight `history_id__in` filters), on every company fetch.
    scoped = {"parcel__establishment__company": company, "album__isnull": False}
    sources = [
        company.establishment_set.exclude(album__isnull=True).values_list("album_id", flat=True),
        Parcel.objects.filter(establishment__company=company, album__isnull=False).values_list("album_id", flat=True),
        Production.objects.filter(**scoped).values_list("album_id", flat=True),
    ]
    for related_name in (
        "history_productionevent_events",
        "history_chemicalevent_events",
        "history_weatherevent_events",
        "history_generalevent_events",
        "history_equipmentevent_events",
        "history_soilmanagementevent_events",
        "history_pestmanagementevent_events",
        "history_businessevent_events",
    ):
        manager = getattr(Production, related_name, None)
        if manager is None:
            continue
        related_model = manager.rel.related_model
        sources.append(
            related_model.objects.filter(
                history__parcel__establishment__company=company, album__isnull=False
            ).values_list("album_id", flat=True)
        )
    all_gallery_ids = list(sources[0].union(*sources[1:]))
    if not all_gallery_ids:
        return 0

    all_images_qs = GalleryImage.objects.filter(gallery_id__in=all_gallery_ids)

    # One aggregate for both the summed known sizes and the count of remote images with no
    # recorded size (was two queries).
    #
    # A remote image is counted once per URL, not once per gallery row: one application logged on
    # several parcels gives every record its own gallery holding the SAME uploaded photos
    # (`EventViewSet._album_from_prepared`), and the upload exists once in the bucket. Counting
    # rows would charge a three-block spray's two photos as six against the hard photo limit.
    unknown = Q(file_size__isnull=True)
    has_url = Q(image_url__isnull=False) & ~Q(image_url="")
    totals = all_images_qs.aggregate(
        known=Sum("file_size", filter=Q(file_size__isnull=False)),
        remote_by_url=Count("image_url", distinct=True, filter=unknown & has_url),
        # Rows with no usable URL keep the old per-row count (an s3_key alone, or a blank URL).
        remote_other=Count("id", filter=unknown & ~has_url & (Q(s3_key__isnull=False) | Q(image_url__isnull=False))),
    )
    known_bytes = totals["known"] or 0
    remote_unknown_count = (totals["remote_by_url"] or 0) + (totals["remote_other"] or 0)

    local_images = list(
        all_images_qs.filter(file_size__isnull=True)
        .exclude(Q(s3_key__isnull=False) | Q(image_url__isnull=False))
        .exclude(image="")
        .only("id", "image")
    )

    local_bytes = 0
    for img in local_images:
        try:
            local_bytes += img.image.size
        except Exception:
            local_bytes += ESTIMATED_IMAGE_SIZE

    return int(known_bytes) + (remote_unknown_count * ESTIMATED_IMAGE_SIZE) + local_bytes


def document_storage_bytes(company) -> int:
    """The DMS shelf across every farm the company owns. COUNTED, never enforced.

    Reads the stored `size_bytes` rather than the storage backend: `file_document()`
    records the exact byte length at filing time, so this is one aggregate query and no
    round trip to S3 per row.
    """
    if not company:
        return 0

    from documents.models import GeneratedDocument

    total = GeneratedDocument.objects.filter(establishment__company=company).aggregate(total=Sum("size_bytes"))["total"]
    return int(total or 0)


def storage_breakdown(company) -> dict:
    """Both categories plus their total, in GB **and in raw bytes**.

    ## Why bytes are in here as well

    GB to 2dp is the right unit for the METER — the limit is expressed in GB and the bar is
    drawn against it — and the wrong unit for the DOCUMENTS line. The two categories live at
    different scales: photo evidence runs to gigabytes, while a certifier document shelf is
    kilobytes to megabytes. MEASURED on the Blue Oak Orchards demo farm: 21 real documents —
    audit dossier, PUR export, two OSP packets, module PDFs, workbook, snapshot, lot tags —
    total 0.95 MB, which is 0.00095 GB and prints as **"Documents 0.00 GB"** next to a list
    of 21 files. Arithmetically correct, and it reads as a broken meter.

    Rounding to GB in the API would destroy the precision needed to say "0.95 MB", so the
    byte counts travel too and the client picks the unit per line. Same lesson as the
    total-vs-parts rounding below: the number has to be true AND legible, and when those
    pull apart the fix is more information, not a different rounding.

    ## The TOTAL IS THE SUM OF THE PARTS

    Not `round(media_bytes + document_bytes)`, which is the more accurate number and the
    wrong one to publish. Both figures are rendered side by side in the usage meter, so
    rounding the total independently produces a card that reads "0.12 GB used · Photos
    0.12 · Documents 0.01" — arithmetic that does not add up, on the farmer's own bill.
    MEASURED on the demo farm: 0.1155 GB of photos and 0.0051 of documents give a true
    total of 0.12 while the displayed halves sum to 0.13.

    The cost of deriving the total from the rounded parts is at most 0.01 GB — ten
    megabytes against a ten-gigabyte floor, invisible in every use this number has
    (a percentage bar, an 80%/95% warning threshold). Visible arithmetic that does not
    add up is not invisible. Consistency wins.
    """
    try:
        media = media_storage_bytes(company)
    except Exception:
        media = 0
    try:
        documents = document_storage_bytes(company)
    except Exception:
        documents = 0

    media_gb = _bytes_to_gb(media)
    documents_gb = _bytes_to_gb(documents)
    return {
        "media_gb": media_gb,
        "documents_gb": documents_gb,
        "total_gb": media_gb + documents_gb,
        # Unrounded, so the client can render each line at its own scale (KB/MB/GB).
        "media_bytes": int(media),
        "documents_bytes": int(documents),
        "total_bytes": int(media) + int(documents),
    }
