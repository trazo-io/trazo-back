"""The fields and behaviour every activity table shares."""

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction

from common.field_registry import GROWTH_STAGE

from .activity import Activity
from .production import Production


class CommonEvent(models.Model):
    description = models.TextField()
    date = models.DateTimeField()
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    history = models.ForeignKey(
        Production,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_events",
    )
    index = models.IntegerField(default=0)
    created_by = models.ForeignKey("users.User", on_delete=models.CASCADE, blank=True, null=True)
    # Sprint 1 Epic 1.4: USDA GAP Traceability - Who performed this agricultural activity
    performed_by = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Name of person who performed this agricultural activity (USDA GAP traceability)",
    )

    # Phase 2: Agronomy context fields shared across all event types
    variety = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Crop variety (e.g., Nonpareil almonds, Hass avocados)",
    )
    block_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Farm block or section identifier",
    )
    growth_stage = models.CharField(
        max_length=30,
        choices=GROWTH_STAGE,
        blank=True,
        null=True,
        help_text="Crop growth stage at time of event",
    )

    # F21 (2026-06): supervisor review / sign-off. FSMA Produce Safety Rule
    # § 112.161(b) requires review-required records (training, agricultural water,
    # biological soil amendments, equipment/tool cleaning) to be reviewed "within a
    # reasonable time" by a supervisor, with the reviewer's name and the review date.
    # Universal on CommonEvent so any event type can carry a sign-off; the certifier
    # PDF surfaces it. (NOT codified as "7 working days" — that figure is not in the
    # regulation; see research-fsma-sgma.md.)
    reviewed = models.BooleanField(
        default=False,
        help_text="Whether a supervisor has reviewed this record (FSMA PSR § 112.161(b)).",
    )
    reviewer_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Name of the supervisor who reviewed the record (FSMA PSR § 112.161(b)).",
    )
    review_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the record was reviewed/signed off.",
    )

    # The PRIVATE half of the pair whose public half is `observation`.
    #
    # `observation` publishes: it is the one box of farmer prose that reaches the buyer page, in
    # the grower's own words, and its label says so. Before this field there was nowhere else to
    # put a note, so the only place to record "rang the neighbour about spray drift" or "Maria
    # thinks the north block is two weeks behind" was the box that publishes it — and the
    # write-time nudge added on 2026-09-08 could warn about a supplier name but not about a note
    # that simply was not meant for a shopper.
    #
    # ⛔ Declared ONCE here, on the abstract base, unlike `observation`, which is re-declared in
    # all eight concrete models. One declaration is one contract: eight copies is how a field
    # ends up on seven tables, and `observation` already differs between them (EquipmentEvent
    # carries its own help_text). The migration still writes eight columns.
    #
    # Never public: it is in `PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS`, so it is
    # popped for every non-owner AND for the owner previewing the consumer view. It does reach
    # the certifier, in the packet and in the free records export, because § 205.103(b)(2) is
    # satisfied by what the operation actually recorded, not by the subset it chose to publish.
    private_note = models.TextField(
        blank=True,
        default="",
        help_text="Private note for the certifier and the farm team. Never shown on a buyer or consumer page.",
    )

    # One application logged on several parcels at once (a tank mix sprayed over three blocks)
    # is written as ONE RECORD PER PARCEL, because a record belongs to a season and the
    # § 205.103(b)(2) trace-back runs field by field. This UUID is what says those records were
    # one application. The client mints it once per wizard session and the create path treats
    # it as an idempotency key, so a retry after a lost response returns the records it already
    # wrote instead of writing them again (`history/services/multi_target.py`).
    #
    # `editable=False` is load-bearing: it keeps the field out of every ModelSerializer's
    # writable fields and out of `amendable_fields`, so a correction to one record can never
    # move it into, or out of, its group.
    application_group = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
        db_index=True,
        help_text="Shared by the records of one application logged on several parcels at once.",
    )

    # The record's identity across the eight event tables (see `Activity`). Created by `save()` on
    # insert, so every creation path gets one, seeders and services included (no event model is
    # bulk-created). `editable=False` keeps it out of every ModelSerializer's writable fields and
    # out of `amendable_fields`. PROTECT: an Activity outlives its event as a tombstone, it is never
    # deleted under one. Nullable until the backfill (migration 0251) has run everywhere.
    activity = models.OneToOneField(
        "history.Activity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="%(app_label)s_%(class)s",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.activity_id is None:
            from history.taxonomy import kind_of

            # An existing row saved with `update_fields` (one written before the backfill) must
            # store its new identity too, or every such save would mint an Activity nobody holds.
            # `update_fields` can arrive positionally (Model.save's 4th argument), as
            # ProductionEvent.save already handles (review of back #303).
            if len(args) > 3:
                update_fields = args[3]
                if update_fields is not None and "activity" not in update_fields:
                    args = args[:3] + (list(update_fields) + ["activity"],) + args[4:]
            else:
                update_fields = kwargs.get("update_fields")
                if update_fields is not None and "activity" not in update_fields:
                    kwargs["update_fields"] = list(update_fields) + ["activity"]
            # One transaction: a save that fails must not leave an Activity behind.
            with transaction.atomic():
                self.activity = Activity.objects.create(kind=kind_of(self).code)
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        # django-auditlog's post_delete receiver calls smart_str(instance) — i.e. this
        # method — while a cascade delete is already in flight, at which point the parent
        # History (or its Parcel/Establishment) row can be gone while this instance is
        # still in memory. The FK descriptor then raises History.DoesNotExist instead of
        # returning None, and because it fires inside a signal handler the exception
        # aborts the entire delete. That is what broke `--reset` on the demo seeders.
        # __str__ must never raise.
        try:
            history = self.history
            if history is None:
                return "-"
            parcel = history.parcel
            if parcel is not None:
                return parcel.name + " - " + parcel.establishment.name
            return history.name
        except ObjectDoesNotExist:
            return "-"
