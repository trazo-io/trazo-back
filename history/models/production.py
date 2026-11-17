"""A production season on a parcel, and its post-harvest facility link."""

import logging
import os
import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg

import qrcode
from PIL import Image
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

from backend.storage import private_records_storage
from common.models import Gallery
from history.harvest_grades import MAX_GRADE_LENGTH
from product.models import Parcel

logger = logging.getLogger(__name__)


#: The three labeling categories of 7 CFR § 205.301, which § 205.103(b)(3) requires records to
#: identify products by — records must "identify agricultural products on these records as
#: '100% organic,' 'organic,' or 'made with organic (specified ingredients or food group(s)).'"
#:
#: This exists because `organic_on_invoice` is a BOOLEAN and cannot express the requirement: it
#: says *whether* the product was identified as organic, never *as which category*. The 2026-08
#: USDA alignment audit recorded that as the one confirmed GAP in Baseline B.
#:
#: ⛔ Operator-set, never derived. It is tempting to infer "100 percent organic" for raw
#: single-ingredient produce, and it is usually right — but the label category is the
#: operation's own labeling decision and a wrong inference in a certifier packet is a
#: fabricated claim. Same rule the PUR export follows: parse what the operator wrote.
#:
#: Blank means NOT DOCUMENTED, deliberately — following `SalesRecord.clean_transport_method`,
#: because a defaulted value would read as an affirmative answer in evidence derivation.
ORGANIC_LABEL_CATEGORY_CHOICES = [
    ("100_percent_organic", "100 percent organic"),
    ("organic", "Organic"),
    ("made_with_organic", "Made with organic (specified ingredients or food group(s))"),
]


# Branded QR code configuration
TRAZO_GREEN = (46, 125, 50)


TRAZO_LEAF_LOGO = os.path.join(settings.BASE_DIR, "static", "img", "trazo-leaf.png")


def compute_retention_until(finish_date, years=5):
    """The § 205.103(b)(4) retention floor: five CALENDAR years past the finish date.

    `years` serves a longer state floor with the same calendar arithmetic: Washington keeps a
    pesticide application record seven years from the application (WAC 16-228-1320(3)), see
    `history.retention.state_spray_retention_floor`.

    Was `finish + timedelta(days=5 * 365)` = 1825 days, which is 1-2 days short of five
    calendar years because the window always contains at least one leap day. Measured on
    live data 2026-08-10: a production finishing 2026-08-08 was stamped 2031-08-07. The
    regulation says "not less than 5 years", and the deletion guard on this model enforces
    the stored date literally, so an off-by-one here is an off-by-one in the wrong direction.

    A module-level function rather than inline in `finalize()` so the arithmetic can be
    tested without building and finalizing a production — the first version of the test
    re-implemented this logic instead, which meant it passed against the broken code too.
    """
    if hasattr(finish_date, "date"):
        finish_date = finish_date.date()
    try:
        return finish_date.replace(year=finish_date.year + years)
    except ValueError:
        # 29 February has no counterpart five years later. Round FORWARD to 1 March:
        # a day extra satisfies "not less than", where 28 February would be a day short.
        return finish_date.replace(year=finish_date.year + years, month=3, day=1)


# Strings the finish form can send for "do not publish". The value reaches
# History.finish() through a multipart QueryDict, so it is a STRING — and
# bool("false") is True, which would publish the buyer page while the farmer
# was looking at an unchecked box.
_FALSEY_PUBLISH_VALUES = {"false", "0", "off", "no", ""}


def _parse_publish_flag(raw):
    """Whether finishing should publish the buyer page. Absent key => True.

    Publishing is the default: every caller predating the finish-dialog checkbox
    (and any direct API finish) must keep publishing. Only an explicit negative
    withholds it, and only a recognised one — an unparseable value publishes,
    matching the historical behaviour rather than silently hiding the season.
    """
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in _FALSEY_PUBLISH_VALUES


class Production(models.Model):
    # Schema remodel Phase 3 (2026-11-14): the model was `History`. It is a production season; the
    # name `History` described the table, not the thing. Renamed in Django state only:
    # `Meta.db_table` pins the table name, the app label stays `history`, and the ContentType row
    # is renamed in place by the migration (same id, so the audit trail is untouched). The alias
    # `History = Production` kept old imports working while code moved over; it was deleted on
    # 2026-11-16. Comments, docstrings and migrations written before the rename still say History.
    ORCHARD = "OR"
    GARDEN = "GA"

    HISTORY_TYPES = (
        (ORCHARD, "Orchard"),
        (GARDEN, "Garden"),
    )

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Production name")
    type = models.CharField(max_length=2, choices=HISTORY_TYPES, blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)
    # When the record was created in Trazo — distinct from `start_date`, which is when the SEASON
    # began and is supplied (and editable) by the farmer.
    #
    # Added because the subscription production quota counted `start_date` over a calendar year,
    # which made it trivially gameable: backdate a production to 31 December and it fell outside
    # the window, and a NULL `start_date` was never counted at all. A quota has to key off
    # something the customer cannot edit.
    #
    # Nullable for rows that predate the field; those are historical and correctly fall outside
    # any current billing period.
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, db_index=True)
    start_date = models.DateTimeField(null=True, blank=True)
    expected_harvest = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Planned/estimated harvest date",
    )
    finish_date = models.DateTimeField(null=True, blank=True)
    published = models.BooleanField(default=False, blank=True)
    earning = models.FloatField(default=0)
    lot_id = models.CharField(max_length=50, blank=True, null=True, help_text="Lot identifier")
    description = models.TextField(blank=True, null=True)
    production_amount = models.FloatField(default=0)

    PRODUCTION_METHOD_CHOICES = [
        ("conventional", "Conventional"),
        ("organic", "Organic"),
        ("regenerative", "Regenerative"),
        ("integrated", "Integrated Pest Management"),
        ("biodynamic", "Biodynamic"),
        ("hydroponic", "Hydroponic"),
        ("no_till", "No-Till"),
    ]
    # No default (2026-11-13). The value prints on certifier records: the renewal land table lists a
    # certified parcel's "conventional" years, and land history carries it per year. A default made
    # every season created without a stated method read as conventional there. Unstated is NULL.
    production_method = models.CharField(
        max_length=30,
        choices=PRODUCTION_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text="Farming method used for this production",
    )

    # Harvest details for transparency
    # Must cover every harvest unit (common.field_registry.UNIT_YIELD, after the audit export's
    # synonym fold "lbs" -> "lb"). Until 2026-10-17 it did not offer "bins", so a harvest of
    # 40 bins could only be finished as kg or units, and the sale seeded from this unit
    # inherited the wrong one: harvest, season and sale could not share a unit, and the packet
    # could not reconcile them (pilot rehearsal). Guard: history/tests/test_rehearsal_quantities.
    UNIT_CHOICES = [
        ("kg", "Kilograms"),
        ("lb", "Pounds"),
        ("boxes", "Boxes"),
        ("bins", "Bins"),
        ("crates", "Crates"),
        ("tons", "Tons"),
        ("bushels", "Bushels"),
        ("units", "Units"),
        ("plants", "Plants"),
        ("seeds", "Seeds"),
    ]
    production_unit = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        blank=True,
        null=True,
        help_text="Unit of measurement for production amount",
    )

    # 🔴 F5 (2026-08-21) — this used to be its OWN list (Premium / Grade A / Grade B /
    # Standard / Processing) while `ProductionEvent.harvest_quality_grade` offered a DIFFERENT
    # one (Export Quality / Grade A / B / C / Domestic / Processing). One fact, two
    # vocabularies: a lot header and the picks underneath it could not agree, the packet
    # printed both, and neither carried a grade a certifier can match to a packing record
    # ("Grade A is not an apple grade" — a certifier reviewer, verbatim). Both columns now
    # draw on `history/harvest_grades.py`, which is crop-aware and carries the USDA families.
    # ⛔ NO `choices`, deliberately — and that is the second half of the F5 fix.
    #
    # The catalogue in `history/harvest_grades.py` is what the FORMS offer, crop by crop, and
    # it always ends in "Other — as stated on the packing record" because private buyer grades
    # and state marks are real. Declaring the catalogue as `choices` here made DRF generate a
    # ChoiceField on every serializer that exposes this column, so the escape hatch answered
    # **400 "…is not a valid choice"**: the UI rendered a text box the API refused to accept.
    # That is the render-gate-without-a-payload-path shape this rehearsal keeps finding, and I
    # shipped it once before catching it.
    #
    # `choices` also broke the packet in the other direction: `get_quality_grade_display()`
    # would have printed a row written before this change as **"Grade A (legacy)"** — the
    # word "legacy" is a note to us, not something a certifier should read. The packet renders
    # this column through `_humanize_enum` instead, which reproduces a real grade verbatim and
    # still turns an old `grade_a` slug into "Grade A".
    quality_grade = models.CharField(
        max_length=MAX_GRADE_LENGTH,
        blank=True,
        null=True,
        help_text=(
            "Grade this lot was packed to, as stated on the packing record. Free text: the "
            "crop-aware suggestions live in history/harvest_grades.py."
        ),
    )

    HARVEST_METHOD_CHOICES = [
        ("manual", "Manual Harvest"),
        ("mechanical", "Mechanical Harvest"),
        ("mixed", "Mixed (Manual + Mechanical)"),
    ]
    harvest_method = models.CharField(
        max_length=20,
        choices=HARVEST_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text="Method used for harvesting",
    )
    qr_code = models.ImageField(upload_to="qr_codes", blank=True)
    # The reverse names are pinned to what the model name gave them before the rename.
    album = models.ForeignKey(
        "common.Gallery",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="history_set",
        related_query_name="history",
    )
    # Off-farm post-harvest handlers (huller / dryer / cold storage / packer) this
    # lot was sent to. CCOF G6.1 / 7 CFR 205.272 — each handler's organic certificate
    # is surfaced in the audit export's Post-Harvest section.
    #
    # 🔴 2026-08-21 — this was a single ForeignKey, and one lot routinely has MORE THAN
    # ONE handler: Calapooia Bend ships each blueberry season's fresh grade to Organically
    # Grown Company and its process grade to Willamette Valley Fruit, two certified
    # operations, on separate loads. Five of that farm's nine shipped lots did exactly
    # that, so the operator could record at most half the § 205.272 requirement — and the
    # packet's "no handler certificate on file" warning cleared as soon as ONE was linked,
    # which is worse than the warning: the second handler's certificate silently stopped
    # being asked for. M2M, so the record can hold what actually happened.
    post_harvest_facilities = models.ManyToManyField(
        "certifications.PostHarvestFacility",
        blank=True,
        related_name="productions",
        through="ProductionPostHarvestFacility",
    )
    cover_image_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        help_text=(
            "Optional hero/cover photo for the public consumer QR page. When set, this image is "
            "shown first (the hero background) and leads the photo gallery, overriding the "
            "auto-picked first timeline photo. Leave blank to auto-pick. Must be a publicly "
            "readable URL (the admin upload widget stores one in the media bucket)."
        ),
    )
    reputation = models.FloatField(default=0, validators=[MinValueValidator(0), MaxValueValidator(5)])

    # Trust metrics for enhanced transparency
    confidence_score = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Statistical confidence in carbon calculations (0-100%)",
    )
    # NEVER a transparency score column. The field declaration went 2026-09-30 (history
    # migration 0237, state-only); the column itself is dropped a deploy later. 0237's
    # docstring says why the two cannot ship together.
    #
    # It was a FloatField validated 0 to 100, help_text "Overall transparency rating",
    # rewritten on every event create, edit and delete. The score was retired as a CONCEPT
    # on 2026-09-08 (`transparency-first.md`): the producer dashboard shows COUNTS, and there
    # is no total, percentage or grade anywhere. The readers came out on 2026-09-30 (#70) and
    # this is the storage.
    #
    # `confidence_score` above is NOT the same thing and stays: it reports how complete the
    # inputs to a carbon calculation are, it is not a sustainability grade, and it is
    # rendered only in the Django admin.
    public_views = models.PositiveIntegerField(default=0, help_text="Total public page views (QR + direct + search)")
    unique_visitors = models.PositiveIntegerField(
        default=0, help_text="Estimated unique visitors (session-based tracking)"
    )
    updated_at = models.DateTimeField(auto_now=True, help_text="Last time production data was updated")
    product = models.ForeignKey(
        "product.Product",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="histories",
    )
    parcel = models.ForeignKey(
        Parcel,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="histories",
    )
    is_outdoor = models.BooleanField(default=True)
    age_of_plants = models.CharField(max_length=50, blank=True, null=True, help_text="Age of plants/trees")
    number_of_plants = models.CharField(max_length=50, blank=True, null=True, help_text="Number of plants")
    soil_ph = models.CharField(max_length=20, blank=True, null=True, help_text="Soil pH level")
    operator = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, blank=True, null=True, related_name="productions_operated"
    )

    # Crop type for this production (migrated from Parcel)
    crop_type = models.ForeignKey(
        "carbon.CropType",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="productions",
        help_text="Crop type for this production",
    )

    # `events_status` was removed 2026-08-19. It tracked a background thread that created
    # event rows from a crop template — a flow that no longer exists (see ProductionPlanItem),
    # and a status NO client ever read: the frontend was supposed to poll it for "progressive
    # event loading" and never did, in either repo. Building the season plan is one
    # bulk_create, so there is nothing left to wait for.

    # NOP Compliance: Post-Harvest Sales & Traceability (7 CFR 205.103)
    # These fields are filled AFTER production is finalized (post-finish).
    # NOT part of blockchain hash — hash is computed at finish time, sales happen after.
    sold_to = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Buyer/recipient name (for trace-back audit)",
    )
    sale_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date of sale or delivery",
    )
    quantity_sold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Quantity sold to buyer",
    )
    quantity_sold_unit = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        blank=True,
        null=True,
        help_text="Unit for quantity sold",
    )
    # Box-to-pound conversion for mass-balance reconciliation (§ 205.103(b)(2)
    # one-step traceability). Optional: when null, the audit export falls back
    # to a crop-specific industry default (CROP_DEFAULT_BOX_WEIGHTS in
    # audit_export_service.py). Standard Hass avocado carton = 25 lb per USDA-
    # AMS Marketing Order 915.
    box_weight_lb = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Weight in pounds of one sales box / carton / lug. Used for mass-"
            "balance reconciliation between boxes shipped and harvest weight."
        ),
    )
    organic_on_invoice = models.BooleanField(
        default=False,
        help_text="Whether organic status is identified on sales documents (SOE requirement)",
    )
    organic_label_category = models.CharField(
        max_length=24,
        choices=ORGANIC_LABEL_CATEGORY_CHOICES,
        blank=True,
        default="",
        help_text=(
            "Which § 205.301 labeling category this product is sold under. "
            "Legacy single-sale path; SalesRecord carries the same field per sale."
        ),
    )
    transport_method = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Transportation method (truck, rail, etc.)",
    )
    destination = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Delivery destination/receiving location",
    )
    # NOP Compliance: Clean-transport record for bins moved to an off-farm handler
    # (CCOF G6.1 / 7 CFR 205.272 / 205.307). When organic product travels in a shared
    # truck/container, the operation must document the vehicle and that a clean-transport
    # affidavit is on file. Audit-only; never surfaced to consumers.
    transport_vehicle_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Vehicle / container / trailer identifier for the off-farm transfer",
    )
    transport_affidavit_on_file = models.BooleanField(
        default=False,
        help_text="Whether a clean-transport affidavit is on file for the shared vehicle (CCOF G6.1)",
    )
    transport_affidavit_document = models.FileField(
        upload_to="transport_affidavits/",
        storage=private_records_storage,
        blank=True,
        null=True,
        help_text="Scanned clean-transport affidavit for the off-farm transfer",
    )

    # NOP Compliance: Record Retention (7 CFR 205.103(b)(4))
    # Auto-set to finish_date + 5 years. Prevents deletion within retention period.
    retention_until = models.DateField(
        blank=True,
        null=True,
        help_text="Records retained until this date (auto-set: finish_date + 5 years per NOP)",
    )

    def delete(self, *args, **kwargs):
        """Prevent deletion of productions within their retention period: NOP's five years, or a
        Washington farm's seven for a season holding a spray (`effective_retention_until`)."""
        from django.utils import timezone

        from history.retention import effective_retention_until

        until = effective_retention_until(self)
        if until and until > timezone.now().date():
            from django.core.exceptions import ValidationError

            from history.retention import state_retention_sentence

            raise ValidationError(
                # "Records must be kept", not "NOP requires": when the Washington floor is the
                # later date, the date is the state's (named by the sentence below), not NOP's.
                f"Cannot delete: records must be kept until {until}. "
                # (b)(4) is the retention clause under the CURRENT rule: the Strengthening
                # Organic Enforcement rule restructured 205.103(b) into five subsections,
                # inserting audit-trail documentation as (b)(3) and pushing "maintained for
                # not less than 5 years beyond their creation" from (b)(3) to (b)(4).
                # Pre-SOE texts (and most search results) still show the four-item list —
                # verify against eCFR before "correcting" this citation.
                f"Records must be maintained for 5 years per 7 CFR 205.103(b)(4)."
                + state_retention_sentence(self)
            )
        if self.pk is not None:
            # OV-ST-C02 (2026-11-13): a season still being logged has no retention date, and that
            # used to make it deletable with every activity in it. See history/retention.py.
            from django.core.exceptions import ValidationError

            from history.retention import unfinished_histories_holding_records, unfinished_season_refusal

            if unfinished_histories_holding_records(pk=self.pk).exists():
                raise ValidationError(unfinished_season_refusal(self))
        super().delete(*args, **kwargs)

    def __str__(self) -> str:
        """Two defects fixed 2026-08-18; both were reachable from an ordinary save.

        1. `start_date` is nullable (`DateTimeField(null=True, blank=True)`) and this called
           `.strftime()` on it unconditionally. Any History without a start date raised
           `AttributeError: 'NoneType' object has no attribute 'strftime'` — and because
           django-auditlog's `log_create` calls `smart_str(instance)` to build `object_repr`,
           the crash happened on SAVE, not merely on display. White-glove / COG Pro import
           targets are created by hand without every field set, which is exactly this path.

        2. Operator precedence. `+` binds tighter than a conditional expression, so
           `... + self.product.name if self.product else ""` applied the guard to the WHOLE
           concatenation rather than to the product name. A production with no product
           therefore stringified to "" — an empty object_repr in the audit log, on records
           whose audit trail is the thing being sold.
        """

        # Format defensively: these may still be STRINGS here. Django does not coerce a
        # `start_date="2026-01-01"` kwarg until the instance is reloaded, and django-auditlog
        # stringifies the instance from a post_save receiver on every create — so a caller
        # passing an ISO string (a fixture, a management command, an importer) crashed the
        # save itself with "'str' object has no attribute 'strftime'", not the display.
        def _fmt(value, empty):
            if not value:
                return empty
            return value.strftime("%m/%d/%Y") if hasattr(value, "strftime") else str(value)

        start = _fmt(self.start_date, "?")
        finish = _fmt(self.finish_date, "present")
        label = f"[ {start} - {finish} ]"
        product_name = self.product.name if self.product else ""
        return f"{label} - {product_name}" if product_name else label

    def get_involved_users(self):
        users = (
            self.history_weatherevent_events.all()
            .values_list("created_by", flat=True)
            .union(self.history_chemicalevent_events.all().values_list("created_by", flat=True))
            .union(self.history_productionevent_events.all().values_list("created_by", flat=True))
            .union(self.history_generalevent_events.all().values_list("created_by", flat=True))
            .union(self.history_equipmentevent_events.all().values_list("created_by", flat=True))
            .union(self.history_soilmanagementevent_events.all().values_list("created_by", flat=True))
            .union(self.history_pestmanagementevent_events.all().values_list("created_by", flat=True))
            .union(self.history_businessevent_events.all().values_list("created_by", flat=True))
        )
        return users

    def update_reputation(self):
        average_reputation = self.reviews.aggregate(Avg("rating"))["rating__avg"]
        if average_reputation is not None:
            self.reputation = round(average_reputation, 2)
        else:
            # If there are no reviews, the default reputation is 0
            self.reputation = 0.00
        self.save()

    def calculate_confidence_score(self):
        """
        Calculate statistical confidence in carbon calculations (0-100%)
        Based on data completeness, measurement precision, verification status

        ⚡ OPTIMIZATION: Uses prefetched event data when available (no queries),
        falls back to .count() only when necessary.
        """
        score = 0

        # Data completeness (40 points)
        required_fields = ["start_date", "finish_date", "production_amount", "parcel", "product"]
        completed_fields = sum(1 for field in required_fields if getattr(self, field))
        score += (completed_fields / len(required_fields)) * 40

        # Events documentation (30 points)
        # ⚡ OPTIMIZATION: Use prefetched data if available, avoid COUNT queries
        total_events = 0
        try:
            # Check if events are prefetched (from view's prefetch_related)
            # Access the prefetch cache directly to avoid .count() queries
            prefetch_cache = getattr(self, "_prefetched_objects_cache", {})

            # Map relationship names to their prefetch cache keys
            event_relations = [
                "history_productionevent_events",
                "history_chemicalevent_events",
                "history_weatherevent_events",
                "history_generalevent_events",
                "history_equipmentevent_events",
                "history_soilmanagementevent_events",
                "history_pestmanagementevent_events",
                "history_businessevent_events",
            ]

            # Try to use prefetched data, fall back to .count() if not available
            if prefetch_cache:
                # Events are prefetched, use cached list lengths (no queries)
                for relation_name in event_relations:
                    if relation_name in prefetch_cache:
                        total_events += len(prefetch_cache[relation_name])
                    else:
                        # Fallback for this specific relation
                        total_events += getattr(self, relation_name).count()
            else:
                # Not prefetched, use .count() (triggers queries)
                for relation_name in event_relations:
                    total_events += getattr(self, relation_name).count()
        except Exception:
            # Fallback for any edge cases - use .count()
            total_events = (
                self.history_productionevent_events.count()
                + self.history_chemicalevent_events.count()
                + self.history_weatherevent_events.count()
                + self.history_generalevent_events.count()
                + self.history_equipmentevent_events.count()
                + self.history_soilmanagementevent_events.count()
                + self.history_pestmanagementevent_events.count()
                + self.history_businessevent_events.count()
            )
        if total_events > 0:
            score += min(total_events * 3, 30)  # 3 points per event, max 30

        # USDA factors usage (20 points)
        if hasattr(self, "carbon_entries") and self.carbon_entries.filter(usda_factors_based=True).exists():
            score += 20

        # Recent updates (10 points)
        from django.utils import timezone

        if self.updated_at and (timezone.now() - self.updated_at).days < 30:
            score += 10

        return min(round(score, 1), 100.0)

    # NEVER: no `calculate_transparency_score()`. The 0-100 production transparency score was
    # retired as a concept, not hidden (`transparency-first.md`, 2026-09-08), and this method
    # was the write-path entry that kept it alive: `update_trust_metrics()` called it on every
    # event create, edit and delete, so the column was refreshed long after the last reader of
    # it was removed.
    #
    # It also carried a silent second formula. Its own `except Exception` fallback graded
    # 30 points for a name plus a description, 40 for ten events, 20 for being published and 10
    # for any carbon entry, with no photo verification and no category weighting, so a
    # calculator failure did not surface as an error: it quietly swapped in a different,
    # more generous grade.
    #
    # `TransparencyCalculator` itself stays. The consumer QR endpoint reads it for FACTS
    # (event count per category, photo counts, farming approach), which is what the page
    # renders. Its graded outputs have no callers left.

    def get_farm_history_years(self):
        """
        Calculate years the farm has been operating based on establishment year
        """
        if self.parcel and self.parcel.establishment and self.parcel.establishment.year_established:
            from datetime import datetime

            current_year = datetime.now().year
            return max(0, current_year - self.parcel.establishment.year_established)
        return 0

    def update_trust_metrics(self):
        """Refresh `confidence_score` after a production's data changes.

        NOTE: it used to write `transparency_score` too, a retired 0-100 self-grade. The
        field left this model in history migration 0237 (state-only, so the COLUMN is still
        there for one deploy; 0237's docstring says why). `confidence_score` stays because
        it is not a sustainability grade: it reports how complete the inputs to a carbon
        calculation are, and it is rendered nowhere outside the Django admin.
        """
        self.confidence_score = self.calculate_confidence_score()
        # Note: public_views is updated separately via view tracking
        self.save(update_fields=["confidence_score"])

    def increment_public_views(self, request=None, skip_bot_check=False):
        """
        Increment public view counter (separate from QR scans)
        with bot filtering and unique visitor tracking

        Args:
            request: Django request object for user agent analysis
            skip_bot_check: Skip bot detection (for testing)
        """
        import logging

        from django.db.models import F

        logger = logging.getLogger(__name__)

        # Bot detection - skip if likely a bot/crawler
        if request and not skip_bot_check:
            user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
            bot_indicators = [
                "bot",
                "crawler",
                "spider",
                "scraper",
                "facebook",
                "twitter",
                "linkedinbot",
                "whatsapp",
                "telegram",
                "googlebot",
                "bingbot",
                "slackbot",
                "discordbot",
                "applebot",
                "yandexbot",
                "baiduspider",
            ]

            if any(indicator in user_agent for indicator in bot_indicators):
                logger.info(f"Skipping view increment for bot: {user_agent[:100]}")
                return {"views_incremented": False, "unique_visitor": False, "reason": "bot_detected"}

        try:
            # Check if this is a unique visitor (session-based)
            is_unique_visitor = False
            if request and hasattr(request, "session"):
                session_key = f"viewed_production_{self.id}"
                if not request.session.get(session_key):
                    is_unique_visitor = True
                    request.session[session_key] = True
                    request.session.save()

            # Atomic increment to prevent race conditions
            update_fields = {"public_views": F("public_views") + 1}
            if is_unique_visitor:
                update_fields["unique_visitors"] = F("unique_visitors") + 1

            Production.objects.filter(id=self.id).update(**update_fields)
            self.refresh_from_db(fields=["public_views", "unique_visitors"])

            logger.debug(
                f"Incremented public views for production {self.id} to {self.public_views}"
                f"{' (unique visitor)' if is_unique_visitor else ''}"
            )

            return {
                "views_incremented": True,
                "unique_visitor": is_unique_visitor,
                "total_views": self.public_views,
                "unique_visitors": self.unique_visitors,
            }

        except Exception as e:
            logger.error(f"Error incrementing public views for production {self.id}: {str(e)}")
            return {"views_incremented": False, "unique_visitor": False, "reason": "error", "error": str(e)}

    def save(self, *args, **kwargs):
        # Check if this is a new object
        is_new = not self.id

        # Ensure public_id is set before first save
        if not self.public_id:
            self.public_id = uuid.uuid4()

        # Allow callers to skip QR generation for speed (e.g., start_production
        # defers it to a background thread).
        skip_qr = kwargs.pop("skip_qr", False)

        # Save first to get ID if this is a new object
        if is_new:
            super().save(*args, **kwargs)

        if not skip_qr and is_new:
            self.generate_qr_code(is_new=is_new, save_args=args, save_kwargs=kwargs)
        elif not is_new:
            super().save(*args, **kwargs)

    def generate_qr_code(self, is_new=False, save_args=None, save_kwargs=None):
        """Generate branded QR code and save it. Can be called separately for deferred generation."""
        # Clean consumer URL - UUID public_id is unguessable, no HMAC needed
        consumer_url = f"{settings.BASE_CONSUMER_URL}production/{self.public_id}"

        # Generate branded Trazo QR code
        qr_image = self._generate_branded_qr(consumer_url)

        buf = BytesIO()
        qr_image.save(buf, format="PNG")

        self.qr_code.save(
            f"{self.name}-{self.start_date}.png",
            ContentFile(buf.getvalue()),
            save=False,
        )

        # Only save again if this was a new object (to update the QR code field)
        # For existing objects, the save will happen normally
        if is_new:
            super().save(update_fields=["qr_code"])
        else:
            super().save(*(save_args or ()), **(save_kwargs or {}))

    @staticmethod
    def _generate_branded_qr(data_url):
        """Generate a branded Trazo QR code with leaf logo, green styling, and CTA frame."""
        # Step 1: Generate styled QR with green rounded modules
        # box_size=20 produces ~660px output for high-quality print (300 DPI at 2.2")
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=20,
            border=4,
        )
        qr.add_data(data_url)
        qr.make(fit=True)

        styled_img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=RoundedModuleDrawer(),
            color_mask=SolidFillColorMask(
                back_color=(255, 255, 255),
                front_color=TRAZO_GREEN,
            ),
        )

        qr_img = styled_img.get_image().convert("RGBA")
        qr_width, qr_height = qr_img.size

        # Step 2: Overlay leaf logo in center (if available)
        # 25% of QR width = ~6.25% of total area, safe with ERROR_CORRECT_H (30%)
        if os.path.exists(TRAZO_LEAF_LOGO):
            try:
                logo_src = Image.open(TRAZO_LEAF_LOGO).convert("RGBA")
                logo_target_size = int(qr_width * 0.25)

                logo_resized = logo_src.resize((logo_target_size, logo_target_size), Image.LANCZOS)
                logo_x = (qr_width - logo_target_size) // 2
                logo_y = (qr_height - logo_target_size) // 2
                qr_img.paste(logo_resized, (logo_x, logo_y), logo_resized)
            except Exception as e:
                logger.warning(f"Could not embed logo in QR code: {e}")

        return qr_img.convert("RGB")

    @property
    def certificate_percentage(self):
        # Certificate percentage calculation removed as part of simplification
        return 0

    def finish(self, history_data, images):
        from datetime import datetime

        from django.utils import timezone

        if images:
            gallery = Gallery.objects.create()
            for image_data in images:
                # Pre-uploaded photos arrive as S3 URL strings (store on image_url so the
                # consumer serializer reads them directly); raw file uploads go on the
                # ImageField. Mixed lists are handled per item.
                if isinstance(image_data, str):
                    gallery.images.create(image_url=image_data)
                else:
                    gallery.images.create(image=image_data)
            self.album = gallery
            # The first photo is the cover. Persist it as the explicit hero override
            # (PublicHistorySerializer.get_images surfaces cover_image_url at images[0])
            # so the consumer hero is deterministic instead of relying on array order.
            # Don't clobber a cover an admin set earlier.
            if not self.cover_image_url:
                first_image = gallery.images.first()
                if first_image:
                    self.cover_image_url = first_image.image_url or (
                        first_image.image.url if first_image.image else None
                    )

        # Handle finish_date with timezone awareness
        finish_date = history_data["finish_date"]
        if isinstance(finish_date, str):
            # Parse string datetime and make it timezone-aware
            finish_date = datetime.fromisoformat(finish_date.replace("Z", "+00:00"))
            if finish_date.tzinfo is None:
                finish_date = timezone.make_aware(finish_date)
        elif isinstance(finish_date, datetime) and finish_date.tzinfo is None:
            # Make naive datetime timezone-aware
            finish_date = timezone.make_aware(finish_date)

        self.finish_date = finish_date
        # Finalization NOTES are aliased onto `description`, which is the season header the
        # farmer typed on the Start Production form and which ships on the consumer QR payload
        # (PublicHistorySerializer). This used to assign unconditionally, so a blank
        # Observations box — the field is OPTIONAL and the form never pre-loads the existing
        # text — overwrote the description with "" on EVERY finish. Only write what the
        # operator actually wrote; silence is not an instruction to erase.
        observation = str(history_data.get("observation") or "").strip()
        if observation:
            self.description = observation
        # Publishing the buyer page is the DEFAULT at finish, but it is the farmer's
        # call — the finish dialog ships a checked-by-default checkbox. Absent key
        # means publish (every caller that predates the checkbox, and the mobile/API
        # path, keeps the old behaviour). Only an explicit negative withholds it.
        # NOTE: this arrives from a multipart QueryDict, so it is the STRING "false",
        # not the bool — bool("false") is True and would silently publish anyway.
        self.published = _parse_publish_flag(history_data.get("published"))
        self.production_amount = history_data["production_amount"]
        self.lot_id = history_data["lot_id"]

        # Harvest details for consumer transparency (Sprint 3)
        self.production_unit = history_data.get("production_unit")
        self.quality_grade = history_data.get("quality_grade")
        self.harvest_method = history_data.get("harvest_method")

        if self.finish_date:
            from history.retention import retention_floor

            # Run 7 (R7-10): never earlier than five years after the newest record's creation.
            self.retention_until = retention_floor(self)

        self.save()

    def compute_finalization_hash(self):
        """Compute keccak256 hash of all event data for integrity verification.

        Single source of truth for finalization hashing. Used by:
        - product/views.py _store_finalization_hash() — at finish time
        - history/transparency_views.py — at verification time

        Returns (hash_hex, event_count) tuple.
        """
        import hashlib
        import json

        from history.models import (
            BusinessEvent,
            ChemicalEvent,
            EquipmentEvent,
            GeneralEvent,
            PestManagementEvent,
            ProductionEvent,
            SoilManagementEvent,
            WeatherEvent,
        )

        event_models = [
            WeatherEvent,
            ChemicalEvent,
            ProductionEvent,
            GeneralEvent,
            EquipmentEvent,
            SoilManagementEvent,
            PestManagementEvent,
            BusinessEvent,
        ]

        all_events = []
        for model in event_models:
            qs = model.objects.filter(history=self).values("id", "index", "date", "description")
            for row in qs:
                row["event_type"] = model.__name__
                all_events.append(row)

        all_events.sort(key=lambda e: e["index"])
        event_data = json.dumps(all_events, sort_keys=True, default=str, separators=(",", ":"))

        try:
            from web3 import Web3

            raw_hex = Web3.keccak(text=event_data).hex()
            return raw_hex.removeprefix("0x"), len(all_events)
        except ImportError:
            return hashlib.sha256(event_data.encode()).hexdigest(), len(all_events)

    def get_events(self):
        from history.serializers import (
            BusinessEventSerializer,
            ChemicalEventSerializer,
            EquipmentEventSerializer,
            GeneralEventSerializer,
            PestManagementEventSerializer,
            ProductionEventSerializer,
            SoilManagementEventSerializer,
            WeatherEventSerializer,
        )

        events = (
            WeatherEventSerializer(self.history_weatherevent_events.all(), many=True).data
            + ChemicalEventSerializer(self.history_chemicalevent_events.all(), many=True).data
            + ProductionEventSerializer(self.history_productionevent_events.all(), many=True).data
            + GeneralEventSerializer(self.history_generalevent_events.all(), many=True).data
            + EquipmentEventSerializer(self.history_equipmentevent_events.all(), many=True).data
            + SoilManagementEventSerializer(self.history_soilmanagementevent_events.all(), many=True).data
            + PestManagementEventSerializer(self.history_pestmanagementevent_events.all(), many=True).data
            + BusinessEventSerializer(self.history_businessevent_events.all(), many=True).data
        )
        # Drop null fields. Every event type serializes ~88 keys and, MEASURED on a live season
        # (21 events, 2026-09-06), 59 % of the values were null: 64 KB of JSON became 37 KB with
        # nothing removed but nulls. Every reader of this list treats a missing key and null the
        # same way (`eventDataNormalizer` checks `=== undefined || === null` / `!= null`; nothing
        # tests key presence). `date` and `index` are never null, so the sort below is unaffected.
        events = [{key: value for key, value in event.items() if value is not None} for event in events]
        return sorted(events, key=lambda event: (event["date"], event["index"]))

    class Meta:
        db_table = "history_history"


class ProductionPostHarvestFacility(models.Model):
    """The link table behind `Production.post_harvest_facilities`, made explicit (2026-11-14).

    Django created it automatically, and an automatic link table names its columns after the model:
    renaming `History` to `Production` would have renamed `history_id` to `production_id` while the
    previous release, still serving during the deploy, read the old name. Declared here with the
    table, columns and uniqueness it already has, so the rename changes nothing in the database.
    The field keeps the name `history` for the same reason: `crops_by_facility` filters on it.
    """

    id = models.BigAutoField(primary_key=True)
    history = models.ForeignKey(Production, on_delete=models.CASCADE, db_column="history_id")
    postharvestfacility = models.ForeignKey("certifications.PostHarvestFacility", on_delete=models.CASCADE)

    class Meta:
        db_table = "history_history_post_harvest_facilities"
        unique_together = [("history", "postharvestfacility")]
