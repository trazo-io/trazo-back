"""Corrections to an activity record."""

from django.db import models


class EventAmendment(models.Model):
    """A correction to an event on a CLOSED season, recorded the way paper does it.

    Events on a finished production are locked (EventViewSet answers 423/403) because a
    filed record must not be quietly rewritten. But a farmer who typed 200 lb instead of
    2,000 lb, or fat-fingered a lot number, still has to be able to fix it — and until
    this model existed the answer was "you cannot", which is worse for an audit than the
    correction would have been. An uncorrectable wrong record is still a wrong record.

    Nothing here is a new idea. Paper organic records are corrected with a single
    strikethrough, the new value beside it, initialled and dated; the original stays
    legible. This is that, in a table:

        - the event carries the CURRENT (corrected) value, so exports, the QR page and
          the certifier packet all read the truth without special-casing;
        - the amendment carries the ORIGINAL, who changed it, when, and WHY.

    `reason` is mandatory on purpose. A correction with a reason answers an inspector's
    question; a correction without one raises it. That is also the line NOP enforcement
    draws — the violation category is falsification or CONCEALMENT of records (NOP 4002),
    and an unexplained post-hoc rewrite is the shape that resembles concealment. Recording
    the original and the reason is what makes this a correction rather than a rewrite.

    Regulatory hook: 7 CFR 205.103(b)(3) requires records to "include audit trail
    documentation", and (b)(2) requires them to be "readily understood and audited".

    Keyed by (event_type, event_id) rather than a GenericForeignKey because there are 8
    concrete event models and the whole codebase already addresses them that way
    (history.constants.EVENT_TYPE_TO_MODEL). A contenttypes FK would add a second,
    competing convention for the same job.

    ## Two kinds of target (2026-08-21, F7)

    An amendment corrects EITHER one event (`event_type` + `event_id` set) OR the SEASON
    HEADER itself (`event_type` and `event_id` both NULL — `history` is the target). The
    header — `production_amount`, `lot_id`, `quality_grade`, `harvest_method` — is frozen
    by the closed-record guard once a season is finished, correctly: it is the traceability
    spine § 205.103(b)(2) asks to be auditable. But it had no correction path AT ALL, while
    the events underneath it did. A farmer who finished a season with the wrong yield — and
    the Finish form used to prefill that number from the wrong event, so it happened — could
    neither edit it (423) nor amend it. The only way out was a developer with ORM access,
    which is not an audit trail; it is the absence of one.

    ONE table, deliberately, rather than a `HistoryAmendment` twin: the packet's "Documented
    Corrections" section is what a certifier reads, and a header correction belongs in the
    same chronological list as an event correction, not in a second table beside it.
    """

    # NULL on both = this amendment corrects the season header (`history`) itself.
    # The CheckConstraint below makes "half a target" impossible.
    event_type = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "history.constants EVENT_TYPE_TO_MODEL key identifying the concrete event model. "
            "NULL together with event_id when the correction targets the season header."
        ),
    )
    event_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    # The corrected record's identity (history.Activity), next to the loose pair above. Written
    # with the pair; NULL for a season-header correction (no event) and for a pair whose event no
    # longer existed when identities were introduced. Readers move to it in a later slice.
    activity = models.ForeignKey(
        "history.Activity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="amendments",
    )

    # The season this correction belongs to. For an event amendment this is denormalised so
    # the amendment survives its event being deleted and the certifier packet can gather a
    # season's corrections in one query rather than eight; for a header amendment it IS the
    # corrected record.
    history = models.ForeignKey("history.Production", on_delete=models.CASCADE, related_name="amendments")

    field_name = models.CharField(max_length=100)
    field_label = models.CharField(
        max_length=200,
        blank=True,
        help_text="Human-readable field name as shown to the farmer, captured at amendment time "
        "so the packet does not depend on today's UI labels to explain an old correction.",
    )
    # TEXT, not the field's own type: this table spans 8 models and every column type on
    # them. The rendered value is what an inspector reads, and storing it as written means
    # a later schema change cannot silently reinterpret a historical record.
    original_value = models.TextField(blank=True)
    corrected_value = models.TextField(blank=True)

    reason = models.TextField(help_text="Why the record was corrected. Required — see class docstring.")

    amended_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_amendments",
    )
    # Captured as text as well as by FK: SET_NULL keeps the amendment when a user is
    # deleted, but an audit trail that reads "amended by (nobody)" is not an audit trail.
    amended_by_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "event_id"]),
            models.Index(fields=["history", "-created_at"]),
        ]
        constraints = [
            # Exactly one kind of target. A row with an event_type but no event_id (or the
            # reverse) points at nothing an inspector can look up, and the packet would print
            # a correction against a record that cannot be found.
            models.CheckConstraint(
                check=(
                    models.Q(event_type__isnull=False, event_id__isnull=False)
                    | models.Q(event_type__isnull=True, event_id__isnull=True)
                ),
                name="amendment_targets_an_event_or_the_header",
            ),
        ]

    def save(self, *args, **kwargs):
        # The identity follows the pair, so a writer holding only the pair (or one that changes
        # it) cannot leave the two disagreeing; a link to a deleted event's tombstone is kept.
        from history.activity_ref import sync_activity_link

        sync_activity_link(self, "event_type", "event_id", "activity_id")
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "activity" not in update_fields:
            kwargs["update_fields"] = list(update_fields) + ["activity"]
        super().save(*args, **kwargs)

    @property
    def targets_the_season_header(self) -> bool:
        """True when this corrects the lot header rather than one event on the season."""
        return self.event_type is None and self.event_id is None

    def __str__(self) -> str:
        if self.targets_the_season_header:
            return f"Amendment: {self.field_name} on season header {self.history_id}"
        return f"Amendment: {self.field_name} on event {self.event_type}/{self.event_id}"
