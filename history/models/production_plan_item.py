"""A season plan's checklist items."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .production import Production


class ProductionPlanItem(models.Model):
    """One SUGGESTED activity on a production's season plan. Never a record.

    ⛔ A plan item is not an event, and the two must never be conflated again.

    WHY (2026-08-19): until this model existed, picking a crop template at production
    start wrote real ``CommonEvent`` rows — dated, attributed to the grower by name,
    printed into the certifier audit packet indistinguishable from something the grower
    actually observed. The date was invented outright: the frontend parsed a template's
    prose window ("December - February") and emitted **the 15th of that month**, off the
    season start, so the rows were routinely backdated. That is the defect class behind
    the 2026-08-02 Smart Setup incident (a backdated glyphosate application written into
    a certified-organic farm's own audit trail).

    Content fixes — organic-first template ordering, ``ORGANIC_OVERRIDES``,
    ``isTemplateEventProhibited`` — closed the glyphosate instance and left the class
    open: software still authored dated assertions of fact on the operator's behalf.

    § 205.201(a) makes the PRODUCER the author of the plan, and § 205.103(b)(2) requires
    records that "fully disclose all activities and transactions ... in sufficient detail
    as to be readily understood and audited." A row nobody performed fails both, and it
    fails them at the inspector's trace-back, where the unit of audit is a crop cycle.

    So a template now produces a PLAN. The plan carries a window, never a day. The record
    is authored when the operator logs the activity, supplies the real date, and saves —
    at which point ``fulfilled_by`` links the two and the item's status becomes ``logged``.

    This is the same suggest→confirm red line already honoured by the OSP § 11 panel
    (derived checkboxes render as *suggested* until the operator confirms each one) and by
    the event-wizard template accelerators (``config/events/templateAccelerators.ts``).
    """

    PENDING = "pending"
    LOGGED = "logged"
    SKIPPED = "skipped"
    STATUS_CHOICES = [
        (PENDING, "Planned"),
        (LOGGED, "Logged"),
        (SKIPPED, "Not applicable"),
    ]

    history = models.ForeignKey(
        Production,
        on_delete=models.CASCADE,
        related_name="plan_items",
        help_text="The production season this plan belongs to.",
    )

    # Provenance. SET_NULL rather than CASCADE: re-seeding the template catalogue must not
    # silently delete a grower's season plan, and an item whose template is gone is still a
    # legitimate plan item — it just no longer points at a catalogue row.
    source_template = models.ForeignKey(
        "carbon.EventTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plan_items",
        help_text="Catalogue template this suggestion came from, when it came from one.",
    )

    # Run 8: which wording of the template this item was built from. The item keeps its own copy
    # of name and description; a later template update never edits it.
    source_template_version = models.PositiveIntegerField(null=True, blank=True)
    name = models.CharField(max_length=150, help_text="e.g. Winter Pruning")
    description = models.TextField(blank=True, help_text="What the practice involves. Advisory text.")

    # Routing for the add-activity wizard: which event model and subtype the operator will
    # be dropped into when they act on this item.
    event_type = models.IntegerField(
        help_text="Backend event type (0 weather, 1 production, 2 chemical, 3 general, "
        "4 equipment, 5 soil, 6 pest, 7 business).",
    )
    event_subtype = models.CharField(
        max_length=20,
        blank=True,
        help_text="Subtype code within the event type, when the template names one.",
    )

    # ⛔ A WINDOW, never a date. Storing a DateField here would re-open the whole defect:
    # any concrete day on a plan item is a day somebody invented.
    planned_window = models.CharField(
        max_length=100,
        blank=True,
        help_text='Agronomic window as written by the template, e.g. "December - February".',
    )
    # Parsed first month of the window, 1-12, for ordering and "what is coming up" views.
    # A month is an attribute of a PLAN and states no fact about what was done; a day would.
    planned_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="First month of planned_window (1-12), when it could be parsed.",
    )
    order_sequence = models.IntegerField(default=0, help_text="Typical order within the season.")

    # ⛔ NO VALUES. A plan item says WHICH practice and roughly WHEN. It does not carry the
    # catalogue's field values, and it must not start to.
    #
    # A `prefill` JSONField was written here first and removed before it shipped. The wizard's
    # `cleanEventData` is a PASSTHROUGH — it copies every key it is handed onto the payload,
    # with no allowlist — so a merged catalogue field set reaches the record whether or not
    # the form renders it. `build_soil_event_fields` alone emits `soil_ph: 6.5`,
    # `organic_matter_percentage: 3.0`, `fuel_consumed`, `equipment_hours` and
    # `amendment_type: "Crimson Clover + White Mustard seed mix"`. Silently writing those is a
    # fabricated MEASUREMENT and a fabricated INPUT IDENTITY — the same class as the backdated
    # record this model was built to stop, and a direct breach of the mutation-payload rule
    # (a payload sends only fields its UI renders) and of the never-auto-populate-a-product
    # rule that came out of the OMRI listing leak.
    #
    # The sanctioned way to prefill VALUES already exists and is render-verified: the wizard's
    # own template accelerators (`config/events/templateAccelerators.ts` over
    # `quickEventFields`), which the operator picks explicitly. If plan items should ever
    # prefill, the route is to map an item to one of those — not to widen this model.

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    # Set when the operator logs a real activity against this item.
    #
    # This is a LOOSE reference, not an FK, so nothing in the database maintains it: when the
    # record is deleted, `EventViewSet.destroy` puts the item back on the plan explicitly. It
    # has to, because an item reading "logged" while the record it names is gone is exactly
    # the assertion-with-nothing-behind-it this model exists to prevent.
    # Keyed (event_type, event_id) rather than a GenericForeignKey, matching EventAmendment
    # and the rest of the codebase — history.constants.EVENT_TYPE_TO_MODEL is already how the
    # 8 concrete event models are addressed everywhere else.
    fulfilled_by_event_type = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="EVENT_TYPE_TO_MODEL key of the record that fulfilled this item.",
    )
    fulfilled_by_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Primary key of the record that fulfilled this item.",
    )
    #: The fulfilling record's identity (history.Activity), written with the pair above.
    fulfilled_by_activity = models.ForeignKey(
        "history.Activity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="fulfilled_plan_items",
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    skipped_reason = models.CharField(
        max_length=255,
        blank=True,
        help_text="Why the operator marked this practice not applicable this season.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "history_production_plan_item"
        ordering = ["order_sequence", "planned_month", "id"]
        verbose_name = "Production plan item"
        verbose_name_plural = "Production plan items"
        indexes = [
            models.Index(fields=["history", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status == self.PENDING
