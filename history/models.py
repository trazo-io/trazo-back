import decimal
import logging
import os
import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
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
from carbon.choices import FUEL_TYPES
from common.field_registry import (
    AMOUNT_DETERMINATION,
    APPLICATION_METHOD,
    APPLIED_SCOPE,
    BUFFER_DISPOSITION,
    CHEMICAL_SUBTYPE,
    CLEANING_ASSET_CLASS,
    ELECTRICITY_SOURCE,
    EQUIPMENT_OPERATION_TYPE,
    EQUIPMENT_TYPE,
    GROWTH_STAGE,
    HARVEST_DESTINATION,
    IRRIGATION_METHOD,
    NON_ORGANIC_SEED_STATUSES,
    ORGANIC_APPROVED,
    PRODUCTION_EFFICIENCY,
    SEED_CERTIFICATION_STATUS,
    SEED_NON_GMO_STATUS,
    SEED_SOURCED_SUBTYPES,
    SEEDS_SOURCE,
    UNIT_AMENDMENT,
    UNIT_APPLICATION_RATE,
    UNIT_AREA,
    UNIT_DEPTH,
    UNIT_DISTANCE,
    UNIT_FUEL,
    UNIT_VOLUME,
    UNIT_YIELD,
    WATER_SOURCE,
)
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


def compute_retention_until(finish_date):
    """The § 205.103(b)(4) retention floor: five CALENDAR years past the finish date.

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
        return finish_date.replace(year=finish_date.year + 5)
    except ValueError:
        # 29 February has no counterpart five years later. Round FORWARD to 1 March:
        # a day extra satisfies "not less than", where 28 February would be a day short.
        return finish_date.replace(year=finish_date.year + 5, month=3, day=1)


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


class History(models.Model):
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
    production_method = models.CharField(
        max_length=30,
        choices=PRODUCTION_METHOD_CHOICES,
        blank=True,
        null=True,
        default="conventional",
        help_text="Farming method used for this production",
    )

    # Harvest details for transparency
    UNIT_CHOICES = [
        ("kg", "Kilograms"),
        ("lb", "Pounds"),
        ("boxes", "Boxes"),
        ("crates", "Crates"),
        ("tons", "Tons"),
        ("bushels", "Bushels"),
        ("units", "Units"),
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
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
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
        """Prevent deletion of productions within NOP 5-year retention period."""
        from django.utils import timezone

        if self.retention_until and self.retention_until > timezone.now().date():
            from django.core.exceptions import ValidationError

            raise ValidationError(
                f"Cannot delete: NOP requires record retention until {self.retention_until}. "
                # (b)(4) is the retention clause under the CURRENT rule: the Strengthening
                # Organic Enforcement rule restructured 205.103(b) into five subsections,
                # inserting audit-trail documentation as (b)(3) and pushing "maintained for
                # not less than 5 years beyond their creation" from (b)(3) to (b)(4).
                # Pre-SOE texts (and most search results) still show the four-item list —
                # verify against eCFR before "correcting" this citation.
                f"Records must be maintained for 5 years per 7 CFR 205.103(b)(4)."
            )
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

            History.objects.filter(id=self.id).update(**update_fields)
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
        from .serializers import (
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


class CommonEvent(models.Model):
    description = models.TextField()
    date = models.DateTimeField()
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    history = models.ForeignKey(
        History,
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

    class Meta:
        abstract = True

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


class WeatherEvent(CommonEvent):
    FROST = "FR"
    DROUGHT = "DR"
    HAILSTORM = "HL"
    HIGH_TEMPERATURE = "HT"
    TROPICAL_STORM = "TS"
    HIGH_WINDS = "HW"
    HIGH_HUMIDITY = "HH"
    LOW_HUMIDITY = "LH"

    WEATHER_EVENTS = (
        (FROST, "Frost"),
        (DROUGHT, "Drought"),
        (HAILSTORM, "Hailstorm"),
        (HIGH_TEMPERATURE, "High Temperature"),
        (TROPICAL_STORM, "Tropical Storm"),
        (HIGH_WINDS, "High Winds"),
        (HIGH_HUMIDITY, "High Humidity"),
        (LOW_HUMIDITY, "Low Humidity"),
    )

    type = models.CharField(
        max_length=2,
        choices=WEATHER_EVENTS,
    )
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Plausibility ranges for meteorological magnitudes. These are NOT
    # regulatory thresholds — they're sanity bounds to catch unit-of-measure
    # mistakes (e.g. °C entered in a °F field, kph in an mph field) before the
    # value ships in an inspector-facing PDF. An entry like 140°F on a
    # California farm is instantly implausible (world-record high is ~134°F,
    # Death Valley 1913) and undermines credibility of the rest of the data.
    _PLAUSIBILITY_BOUNDS = {
        # temperature in °F / °C (evaluated against both, narrower of the two)
        "temperature_f": (-40, 135),  # world record high ~134°F
        "temperature_c": (-40, 57),  # world record high ~56.7°C
        # F12 fix (2026-06): the WeatherTab form collects wind in km/h and
        # precipitation in mm (metric), so the stored extra_data values are metric.
        # Bounds were imperial (mph / inches), so a legitimate 150 mm storm or a
        # 300 km/h gust failed the (0,50)/(0,250) checks with a 400. Bounds are now
        # metric to match the form's units.
        "wind_speed_kmh": (0, 410),  # world record gust 253 mph ≈ 407 km/h (Barrow Island)
        "precipitation_mm": (0, 1200),  # single-event max ~43 in ≈ 1092 mm (TC Denise, 1966)
        "humidity_pct": (0, 100),
        "hail_size_in": (0, 8),  # largest verified ~8 in (Vivian, SD 2010)
    }

    def _plausibility_check(self, unit: str, value, low: float, high: float, field: str):
        """Return a ValidationError-style message if the magnitude is outside
        plausible meteorological bounds, else None. Used by clean() and by
        the serializer's pre-save validation so both the admin and the API
        catch unit-of-measure typos."""
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None  # non-numeric handled elsewhere
        if numeric < low or numeric > high:
            return (
                f"{field} {numeric}{unit} is outside the plausible range "
                f"[{low}, {high}]{unit}. Check that the value was entered in "
                "the correct unit — e.g. °C in a °F field will trigger this."
            )
        return None

    def clean(self):
        """
        Validate that numeric meteorological magnitudes are within plausible
        ranges. Catches °C-in-°F and kph-in-mph typos at save-time so they
        never ship in an inspector-facing PDF.
        """
        from django.core.exceptions import ValidationError

        super().clean()
        extra = self.extra_data or {}
        issues = {}

        # Temperature — unit-aware; extra_data.temperature_unit in {"F", "C"}.
        temp_unit = (extra.get("temperature_unit") or "F").upper()
        temp_bounds_key = "temperature_c" if temp_unit == "C" else "temperature_f"
        low, high = self._PLAUSIBILITY_BOUNDS[temp_bounds_key]
        unit_sym = "°C" if temp_unit == "C" else "°F"
        for key in ("highest_temperature", "lowest_temperature", "temperature", "lower_temperature"):
            msg = self._plausibility_check(unit_sym, extra.get(key), low, high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        wind_low, wind_high = self._PLAUSIBILITY_BOUNDS["wind_speed_kmh"]
        msg = self._plausibility_check(" km/h", extra.get("wind_speed"), wind_low, wind_high, "wind_speed")
        if msg:
            issues.setdefault("extra_data", []).append(msg)

        precip_low, precip_high = self._PLAUSIBILITY_BOUNDS["precipitation_mm"]
        for key in ("precipitation", "precipitation_amount"):
            msg = self._plausibility_check(" mm", extra.get(key), precip_low, precip_high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        hum_low, hum_high = self._PLAUSIBILITY_BOUNDS["humidity_pct"]
        # Check both humidity key variants separately — using ``or`` to pick
        # between them treats 0% (a valid low-humidity reading) as falsy
        # and silently swaps it for humidity_level, masking a real value.
        for key in ("humidity", "humidity_level"):
            msg = self._plausibility_check("%", extra.get(key), hum_low, hum_high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        hail_low, hail_high = self._PLAUSIBILITY_BOUNDS["hail_size_in"]
        msg = self._plausibility_check(" in", extra.get("hail_size"), hail_low, hail_high, "hail_size")
        if msg:
            issues.setdefault("extra_data", []).append(msg)

        if issues:
            raise ValidationError(issues)


class ChemicalEvent(CommonEvent):
    FERTILIZER = "FE"
    PESTICIDE = "PE"
    FUNGICIDE = "FU"
    HERBICIDE = "HE"

    CHEMICAL_EVENTS = (
        (FERTILIZER, "Fertilizer"),
        (PESTICIDE, "Pesticide"),
        (FUNGICIDE, "Fungicide"),
        (HERBICIDE, "Herbicide"),
    )

    # Chemical subtype choices - used for accurate carbon emission factor selection
    # These subtypes have different manufacturing emission factors
    HERBICIDE_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic (Glyphosate, 2,4-D, Atrazine, etc.)"),
        ("organic", "Organic/Natural (Vinegar, Acetic Acid, Clove Oil, etc.)"),
    ]

    FUNGICIDE_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic (Chlorothalonil, Mancozeb, etc.)"),
        ("organic", "Organic/Natural (Neem Oil, Potassium Bicarbonate, etc.)"),
        ("copper", "Copper-Based (Bordeaux Mix, Copper Sulfate, Kocide, etc.)"),
        ("sulfur", "Sulfur-Based"),
        ("biological", "Biological (Bacillus, Trichoderma, etc.)"),
    ]

    PESTICIDE_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic (Conventional)"),
        ("organic", "Organic/Natural (Neem, Pyrethrin, etc.)"),
        ("biological", "Biological (Bt, Spinosad, etc.)"),
    ]

    FERTILIZER_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic/Chemical (Urea, Ammonium Nitrate, etc.)"),
        ("organic", "Organic (Compost, Manure, etc.)"),
        ("slow_release", "Slow-Release/Controlled"),
    ]

    # Combined choices imported from common/field_registry.py (SSOT)
    CHEMICAL_SUBTYPE_CHOICES = CHEMICAL_SUBTYPE

    type = models.CharField(max_length=2, choices=CHEMICAL_EVENTS, blank=True, null=True)

    # Chemical subtype for accurate carbon emission factor selection
    # This field determines which emission factor to use in carbon calculations
    chemical_subtype = models.CharField(
        max_length=30,
        choices=CHEMICAL_SUBTYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Specific subtype of chemical for accurate carbon emission calculations. "
        "Different subtypes have different manufacturing emission factors.",
    )
    commercial_name = models.CharField(max_length=60, blank=True, null=True)
    volume = models.CharField(max_length=60, blank=True, null=True)
    concentration = models.CharField(max_length=60, blank=True, null=True)
    area = models.CharField(max_length=60, blank=True, null=True)
    way_of_application = models.CharField(max_length=60, blank=True, null=True)
    time_period = models.CharField(max_length=60, blank=True, null=True)
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # New structured fields for better carbon calculations
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    nitrogen_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Nitrogen content percentage"
    )
    phosphorus_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Phosphorus content percentage"
    )
    potassium_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Potassium content percentage"
    )
    # NOP 5012 — Approval of Liquid Fertilizers. Certifiers must verify that
    # liquid/soluble fertilizers are not adulterated with prohibited synthetic
    # nitrogen (sodium nitrate is capped at 20% of the crop's N need; synthetic
    # N sources are prohibited under § 205.105(a)). Capturing the nitrogen source
    # lets the audit export flag an unverified or synthetic N source for review.
    NITROGEN_SOURCE_CHOICES = [
        ("organic", "Organic (plant / animal / approved natural source)"),
        ("mined_natural", "Mined / natural — restricted (e.g., sodium (Chilean) nitrate, ≤20% of N need)"),
        ("synthetic_prohibited", "Synthetic — prohibited under § 205.105(a)"),
        ("unknown", "Unknown / not verified"),
    ]
    nitrogen_source = models.CharField(
        max_length=24,
        choices=NITROGEN_SOURCE_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Nitrogen source for a liquid/soluble fertilizer (NOP 5012). Synthetic N is "
            "prohibited (§ 205.105(a)); sodium nitrate is restricted to 20% of the crop's "
            "N requirement (§ 205.602 annotation)."
        ),
    )
    # §E-3 — Micronutrients (FE subtype). NOP § 205.601(j)(7) allows synthetic micronutrients
    # ONLY where a documented soil/plant-tissue deficiency exists, and prohibits their use as a
    # defoliant, herbicide or desiccant. Recording WHICH micronutrient and at what rate is what
    # lets the audit export pair the application with its deficiency record (a soil `ST` or
    # lab-analysis `LA` event) — without both halves the application reads as unsupported at
    # inspection. UC Davis 2024 organic-almond study: zinc sulfate 10 lb/ac and 20% boron at
    # 2 lb/ac foliar post-harvest, plus fertigated boron.
    MICRONUTRIENT_CHOICES = [
        ("zinc", "Zinc (Zn)"),
        ("boron", "Boron (B)"),
        ("manganese", "Manganese (Mn)"),
        ("iron", "Iron (Fe)"),
        ("copper", "Copper (Cu)"),
        ("calcium", "Calcium (Ca)"),
        ("magnesium", "Magnesium (Mg)"),
        ("sulfur", "Sulfur (S)"),
        ("other", "Other"),
    ]
    micronutrient_type = models.CharField(
        max_length=20,
        choices=MICRONUTRIENT_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Micronutrient applied (FE subtype). Permitted under § 205.601(j)(7) only with a "
            "documented deficiency — log the soil OR tissue test that shows it, or the other "
            "verifiable method your certifier approved."
        ),
    )
    micronutrient_rate = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Rate of the micronutrient applied, in micronutrient_rate_unit.",
    )
    micronutrient_rate_unit = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Unit for micronutrient_rate, e.g. lb/ac, kg/ha, gal/ac, ppm.",
    )

    application_method_structured = models.CharField(
        max_length=20,
        choices=APPLICATION_METHOD,
        null=True,
        blank=True,
        help_text="Structured application method",
    )

    # Sprint 3 Epic 3.3: Application Fuel Tracking
    # Tracks fuel consumed by application equipment (sprayers, spreaders, etc.)
    # Important for accurate carbon emissions: application fuel often equals/exceeds manufacturing emissions
    application_fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for application equipment (EPA emission factor selection)",
    )
    application_fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed by application equipment (sprayer, spreader, etc.)",
    )
    application_fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit for application equipment",
    )

    # Environmental context fields for transparency
    weather_conditions = models.CharField(
        max_length=100, blank=True, null=True, help_text="Weather conditions during application for transparency"
    )
    application_timing = models.CharField(
        max_length=100, blank=True, null=True, help_text="When the application was made for consumer understanding"
    )
    target_pest_disease = models.CharField(
        max_length=200, blank=True, null=True, help_text="What problem this application addresses for transparency"
    )
    # USDA's Input Material Application Record has a "Purpose / Reason for Use" column, and its
    # footnote 5 states the reason it matters: "Some materials, for example, are allowed for pest
    # management but not as a soil amendment." § 205.601 lists synthetics BY USE, so the same
    # substance can be allowed for one purpose and prohibited for another — which makes purpose
    # part of the allowability record, not a nicety.
    #
    # `target_pest_disease` already covers the pest-targeting subtypes (PE/FU/HE) and
    # `record_completeness` requires it there. FERTILIZER had no purpose field at all: the event
    # `type` says "a fertilizer went on" and nothing says why, so a micronutrient applied to
    # correct a documented deficiency — the § 205.601(j)(1) condition — was indistinguishable
    # from routine feeding.
    APPLICATION_PURPOSE_CHOICES = [
        ("soil_fertility", "Soil fertility / crop nutrition"),
        ("micronutrient_deficiency", "Correcting a documented micronutrient deficiency"),
        ("soil_amendment", "Soil amendment / organic matter"),
        ("ph_adjustment", "pH adjustment"),
        ("pest_management", "Pest management"),
        ("disease_management", "Disease management"),
        ("weed_management", "Weed management"),
        ("plant_growth", "Plant growth regulation"),
        ("other", "Other (describe in notes)"),
    ]
    application_purpose = models.CharField(
        max_length=32,
        choices=APPLICATION_PURPOSE_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Why this input was applied (USDA Input Material Application Record, "
            "'Purpose / Reason for Use'). Allowability under § 205.601 can depend on the use."
        ),
    )

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    # Sprint 6 Fix: Expanded choices to match frontend organic certification options
    # These detailed options provide better transparency for consumers about organic certification types
    organic_approved = models.CharField(
        max_length=20,
        choices=ORGANIC_APPROVED,
        blank=True,
        null=True,
        help_text="Whether this chemical is approved for organic farming",
    )
    buffer_zone_meters = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Buffer zone maintained near water sources or sensitive habitats (meters)",
    )

    # WS-4 (2026-08) — § 205.103(b)(2): records must be auditable, which for an application
    # means identifying WHERE it went.
    #
    # Corrected 2026-08-15: this cited (b)(1), which reads "Be adapted to the particular
    # business that the certified operation is conducting" and says nothing about location.
    # The location expectation is (b)(2) audit sufficiency plus USDA's Input Material
    # Application Record, whose column 2 is "Location and Crop".
    # Whole planting vs part; the detail names the part (rows/blocks/area).
    applied_scope = models.CharField(
        max_length=10,
        choices=APPLIED_SCOPE,
        blank=True,
        null=True,
        help_text="Whether this application covered the entire planting or part of it",
    )
    applied_scope_detail = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Which rows/blocks/area were treated, when applied_scope is 'part'",
    )

    # EPA Worker Protection Standard (WPS) Compliance Fields - 40 CFR 170.309
    applicator_name = models.CharField(
        max_length=150, blank=True, null=True, help_text="Name of the certified applicator who applied the chemical"
    )
    epa_registration_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="EPA registration number from the product label (e.g., 12345-67)",
    )
    restricted_use_pesticide = models.BooleanField(
        default=False, help_text="Whether this is a Restricted Use Pesticide (RUP) requiring certified applicator"
    )
    applicator_certification = models.CharField(
        max_length=100, blank=True, null=True, help_text="Applicator certification/license number (required for RUPs)"
    )
    # F21 (2026-06): GLOBALG.A.P. IFA v6 FV-GFS 32.02.01 #10 — the technically
    # responsible person who AUTHORIZED the plant-protection-product application
    # (often the grower or PCA), distinct from the applicator who applied it.
    authorizer_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Technically-responsible person who authorized the application (GLOBALG.A.P. FV-GFS 32.02.01 #10).",
    )
    rei_hours = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Restricted Entry Interval in hours (worker safety)",
    )
    phi_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Pre-Harvest Interval in days (consumer safety)",
    )

    # Item #8: Numeric volume and area fields for accurate carbon calculations
    # The legacy string fields (volume, area) are kept for backward compatibility with existing data.
    # New events should populate these numeric fields instead.
    volume_numeric = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Volume applied (numeric value)",
    )
    volume_unit = models.CharField(
        max_length=20,
        choices=UNIT_VOLUME,
        default="gal",
        blank=True,
        help_text="Volume unit",
    )
    area_numeric = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Area treated (numeric value)",
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )

    # The rate — what the grower says, and what the label is written in.
    #
    # MEASURED 2026-09-02 across two real dictations: "six fluid ounces an acre" and "three and
    # a half pounds an acre". Both are RATES. `volume_numeric` above is a TOTAL ("Total volume of
    # product applied"), so before this column existed the number either landed there — wrong by
    # the whole acreage, on the value the certifier packet, the carbon calculation and CA PUR all
    # read — or was dropped so the record simply lost it.
    #
    # This does NOT replace the total. § 205.103(b)(2) mass balance reconciles what was PURCHASED
    # against what was APPLIED, and a rate alone cannot close that; a certifier wants the rate
    # (is it within the label?) AND the total (does it match the invoice?). The two answer
    # different questions, so both columns exist and neither is derived from the other:
    # multiplying rate x area to fabricate a total would assert a number nobody stated.
    application_rate = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Amount of product applied PER unit of land — the label rate, not the total.",
    )
    application_rate_unit = models.CharField(
        max_length=12,
        choices=UNIT_APPLICATION_RATE,
        blank=True,
        default="",
        help_text="Unit for application_rate (e.g. fl oz/acre).",
    )

    # Item #14: Fertigation flag — fertilizer injected through irrigation system.
    # When True, application fuel is skipped to avoid double-counting with the irrigation event.
    is_fertigation = models.BooleanField(
        default=False,
        help_text="Fertigation — fertilizer injected through irrigation system. "
        "Skips application fuel to avoid double-counting with irrigation events.",
    )

    # NOP Compliance: Supplier & Purchase Tracking (7 CFR 205.103)
    # Required for mass-balance audits — purchased inputs must match applied inputs
    supplier_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Input supplier/vendor name for audit trail",
    )
    purchase_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date input was purchased",
    )
    receipt_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chemical_receipts",
        help_text=(
            "The uploaded purchase receipt/invoice FILE behind purchase_invoice. "
            "2026-08-25: the record said 'INV-123' but the packet could not show the "
            "receipt — the farmer was the courier between Trazo's two halves. "
            "Same-establishment enforced in the serializer; embedded in the audit "
            "PDF and copied into the packet ZIP."
        ),
    )
    purchase_invoice = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Purchase invoice or receipt reference number",
    )
    quantity_purchased = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total quantity purchased (for mass-balance audit reconciliation)",
    )
    quantity_purchased_unit = models.CharField(
        max_length=10,
        choices=UNIT_VOLUME,
        blank=True,
        null=True,
        help_text="Unit for quantity purchased",
    )
    chemical_lot_number = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        help_text=(
            "Manufacturer/supplier lot or batch number of the purchased input — an "
            "explicitly required NOP purchase-record field (CCOF G8.0, Oregon Tilth) for "
            "input traceability and mass-balance. Audit-only; never surfaced to consumers."
        ),
    )

    # Sprint 3 — OMRI / National List cross-reference (7 CFR 205.601/602)
    # Farmer-confirmed OMRI ID (nullable) and auto-suggested National List match (nullable).
    # See certifications.services.omri_verifier for the matching logic.
    wsda_material = models.ForeignKey(
        "certifications.WSDAMaterial",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chemical_events",
        help_text=(
            "WSDA Materials List row the operator attached in the input lookup. Co-equal with "
            "OMRI for CCOF, and for 23 of the 42 seeded WSDA brands (Feather Meal 13-0-0, "
            "AzaMax, Kaligreen, Madex HP …) it is the ONLY third-party listing that exists — "
            "so without this field those inputs could never be more than grower-reported, no "
            "matter what the catalogue held. Written only by the operator's tap, never by the "
            "fuzzy name matcher: see consumer-omri-listing-leak-2026-08-09."
        ),
    )
    omri_product = models.ForeignKey(
        "certifications.OMRIProduct",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="chemical_events",
        help_text="Farmer-confirmed OMRI product ID (reported, not Trazo-verified)",
    )
    national_list_substance = models.ForeignKey(
        "certifications.NationalListSubstance",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="chemical_events",
        help_text="Matched National List entry (7 CFR 205.601/602). Read it through "
        "`confirmed_national_list_substance`: only an exact, alias or operator basis is a classification.",
    )
    # OSP alignment audit, Phase 5 slice 1 (2026-10-02): how the classification above was made. Until
    # now every match, from an exact name to a substring guess, landed in the one FK and the packet
    # cited a § listing for each. Rows classified before this field existed carry `legacy_unverified`:
    # their method is not inferred from today's rules.
    NL_BASIS_EXACT = "exact"
    NL_BASIS_ALIAS = "alias"
    NL_BASIS_OPERATOR = "operator"
    NL_BASIS_LEGACY = "legacy_unverified"
    NL_BASIS_CHOICES = [
        (NL_BASIS_EXACT, "Exact name match"),
        (NL_BASIS_ALIAS, "Curated alias"),
        (NL_BASIS_OPERATOR, "Set by the operator"),
        (NL_BASIS_LEGACY, "Recorded before the basis was kept; not verified"),
    ]
    #: The bases that make the FK a classification a document may cite.
    NL_CONFIRMED_BASES = frozenset({NL_BASIS_EXACT, NL_BASIS_ALIAS, NL_BASIS_OPERATOR})
    national_list_basis = models.CharField(max_length=20, choices=NL_BASIS_CHOICES, blank=True, default="")
    #: A substring or container match: a possible listing, never a classification, never cited.
    national_list_suggestion = models.ForeignKey(
        "certifications.NationalListSubstance",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
        help_text="Possible National List entry from a partial name match. Not a classification.",
    )

    @property
    def confirmed_national_list_substance(self):
        """The National List classification a document or a claim may use, or None.

        Only an exact or curated-alias match, or one the operator set, qualifies. A legacy row whose
        basis was never recorded, and a partial-name suggestion, are not classifications.
        """
        if self.national_list_substance_id and self.national_list_basis in self.NL_CONFIRMED_BASES:
            return self.national_list_substance
        return None

    # Sprint 5.1 — Drift detector. Populated by post_save signal when the input
    # used on this event is not in the establishment's active OSP.approved_*.
    # Null = no drift (either input is approved or no active OSP to compare to).
    # Shape: see certifications.services.drift_detector.build_drift_warning().
    drift_warning = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Drift detector payload (7 CFR 205.400(f)(2)). Non-null when this "
            "event's input is not in the active OSP's approved_inputs — treated "
            "as an operation change requiring certifier notification."
        ),
    )

    # P0-3 — CA DPR Restricted Materials Permit (California state law).
    # Required for county-restricted materials (copper hydroxide, sulfur,
    # pyrethrin, spinosad, rotenone) even when NOP-allowed under § 205.601.
    # Enforcement is county Ag Commissioner — permit # + county + expiry
    # are surfaced to the inspector via the drift-finding sub-badge.
    ca_dpr_permit_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="CA DPR Restricted Materials Permit # issued by the county Ag Commissioner",
    )
    ca_dpr_permit_county = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="CA county that issued the permit (e.g., 'San Diego', 'Fresno')",
    )
    ca_dpr_permit_expires = models.DateField(
        blank=True,
        null=True,
        help_text="Expiration date of the CA DPR restricted-materials permit",
    )

    # ------------------------------------------------------------------
    # F20 (2026-06): Legal spray-record completeness.
    # Lets one Trazo chemical event double as (a) the CA legal pesticide-use
    # record / monthly PUR (DPR-PML-017C) and (b) a GLOBALG.A.P. IFA v6
    # FV-GFS 32.02.01 PPP application record. All nullable — only the CA fields
    # matter for a CA establishment; GG needs manufacturer + start/end + dose.
    # ------------------------------------------------------------------
    # Universal (GLOBALG.A.P. + DPR box 28 + traceability)
    manufacturer = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Product manufacturer/registrant (GLOBALG.A.P. FV-GFS 32.02.01; DPR-PML-017C box 28). "
        "commercial_name holds the brand/trade name.",
    )
    # ⏱️ WALL CLOCK, not an instant (convention, verified 2026-08-31).
    #
    # These are filled from `datetime-local` inputs, which carry no offset. With
    # TIME_ZONE="UTC" and USE_TZ=True, DRF makes the naive value aware AS UTC, so a Ventura
    # grower typing 14:30 gets 14:30Z stored -- seven hours off as an instant, and exactly
    # right as the wall clock they wrote down. Every reader honours that: the frontend
    # `formatDateTime` renders in UTC and `pur_export_service` prints boxes 17/18 verbatim
    # (DPR wants local time) -- those two are the ONLY consumers of these columns.
    # `cogpro_import._as_event_datetime` encodes imported dates to match. Nothing computes an
    # interval from them: § 205.203(c)'s safe-harvest date is derived from
    # `manure_application_date` (a DateField) and REI/PHI are stored durations.
    #
    # So do not "correct" this one field, or one form, to send a real offset: a half-migration
    # shifts printed compliance times by the offset while the rest of the system still reads
    # UTC. Doing it properly means a per-establishment timezone column (none exists today), a
    # data migration for stored rows, and farm-local rendering on every surface.
    application_start = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Date/time the application started (3 CCR 6624(c)(2) / DPR box 17).",
    )
    application_end = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Date/time the application completed (3 CCR 6624(c)(2) / DPR box 18).",
    )
    # CA requires BOTH total planted acreage (box 9) AND acreage treated (the
    # existing `area` field / box 19). They differ for band/spot/strip treatments.
    planted_area = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Total planted acres/units at the site (DPR-PML-017C box 9). Distinct from `area` (acreage treated).",
    )
    planted_area_unit = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Unit for planted_area (acres, ha, sq_ft, units).",
    )
    # CA Pesticide Use Report identity (only relevant for CA establishments).
    operator_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Operator ID / permit number issued by the county Ag Commissioner (DPR box 3). "
        "Required for ALL CA ag pesticide use, not only restricted materials.",
    )
    site_id = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="County-issued site identification number, 1-8 chars (DPR box 8).",
    )
    application_county = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="County where the application was performed (DPR box 10).",
    )
    mtrs_section = models.CharField(max_length=20, blank=True, null=True, help_text="Legal section (DPR box 11).")
    mtrs_township = models.CharField(max_length=20, blank=True, null=True, help_text="Township N/S (DPR box 12).")
    mtrs_range = models.CharField(max_length=20, blank=True, null=True, help_text="Range E/W (DPR box 13).")
    mtrs_base_meridian = models.CharField(
        max_length=20, blank=True, null=True, help_text="Base & Meridian: H/M/S (DPR box 14)."
    )
    ffm_code = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text=(
            "DPR method code (PUR box 21). Two rules feed this ONE field. (1) Fumigation: the "
            "4-digit field fumigation method code, 3 CCR 6624(c)(8). (2) Schoolsites: any method "
            "on ground within 1/4 mile of a schoolsite, 3 CCR 6691 via 6434(6)(A) and 6626(c) — "
            "DPR ENF 25-16, effective 2026-01-01 under AB 1864, which REPURPOSED this same "
            "4-digit field rather than adding a box. NEVER scope this to fumigation alone: a "
            "ground rig (5101), airblast (5102) or drip line (5162) near a school owes a code too. "
            "Aircraft is the one method that owes none, 3 CCR 6691(a)(1)."
        ),
    )
    # Who made the application: the operation itself, or a licensed pest control business
    # hired for the pass. This is the switch the CA monthly PUR is keyed on. 3 CCR 6626(b)
    # makes the BUSINESS the reporter for its own applications (within 7 days, with a copy
    # to the grower within 30), and CDPR's PUE Compendium Vol. 1 Ch. 4 p. 4-8 is explicit:
    # "The grower or property operator should not include applications made by pest control
    # businesses on his/her use report to the county." Without this flag every spray on the
    # farm was exported as the grower's own, so a hired application was reported twice —
    # once by the business, once by us. The grower still KEEPS the record (3 CCR 6624(d)),
    # so the event stays; only the PUR export treats it differently.
    applied_by_pcb = models.BooleanField(
        default=False,
        help_text=(
            "Applied by a licensed pest control business (for hire), not by the operation. "
            "Excluded from the grower's CA PUR — the business files its own (3 CCR 6626(b))."
        ),
    )
    pcb_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Name of the pest control business that made the application (3 CCR 6626(c); PUE Compendium 4-7).",
    )
    # Tank-mix partners (adjuvants / spreader-stickers) applied together with the
    # primary product. CA-registered adjuvants ARE reportable to the PUR and each
    # needs its OWN DPR-PML-017C line (boxes 23/24), so this is a structured list —
    # each partner emits a separate PUR row. Shape (per item):
    #   {"commercial_name": str, "manufacturer": str, "epa_registration_number": str,
    #    "volume": str, "volume_unit": str, "organic_approved": bool}
    # Audit/compliance field; never surfaced to consumers.
    tank_mix_partners = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Tank-mix partners (adjuvants/spreader-stickers) applied with the primary "
            "product. Each CA-registered partner is reportable on its own PUR line "
            "(boxes 23/24). List of {commercial_name, manufacturer, "
            "epa_registration_number, volume, volume_unit, organic_approved}."
        ),
    )

    def clean(self):
        """
        Model-level validation for NPK percentages, EPA compliance, and business logic
        """
        from django.core.exceptions import ValidationError

        errors = {}

        # Validate individual NPK percentages are within range
        for field_name, percentage in [
            ("nitrogen_percentage", self.nitrogen_percentage),
            ("phosphorus_percentage", self.phosphorus_percentage),
            ("potassium_percentage", self.potassium_percentage),
        ]:
            if percentage is not None:
                if percentage < 0:
                    errors[field_name] = f'{field_name.replace("_", " ").title()} cannot be negative'
                if percentage > 100:
                    errors[field_name] = f'{field_name.replace("_", " ").title()} cannot exceed 100%'

        # Validate total NPK doesn't exceed 100%
        if (
            self.nitrogen_percentage is not None
            and self.phosphorus_percentage is not None
            and self.potassium_percentage is not None
        ):
            # These are DecimalFields, so a value loaded from the database is a Decimal —
            # but a value assigned in Python (a float off deserialised JSON, a template
            # default, a management command) stays a float until it round-trips. Summing a
            # mix raises `TypeError: unsupported operand type(s) for +: 'decimal.Decimal'
            # and 'float'`, which is an unhandled 500 out of clean()/full_clean() rather
            # than a validation error. Reproduced 2026-08-10 on a bare instance with N as
            # Decimal and P as float — no database or fixture involved.
            #
            # Decimal(str(x)) rather than Decimal(x): the latter converts a float's binary
            # representation exactly, so 10.5 would become 10.5000000000000017763568394...
            # and leak into the error message the grower reads.
            def _as_decimal(value):
                return value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))

            total_npk = (
                _as_decimal(self.nitrogen_percentage)
                + _as_decimal(self.phosphorus_percentage)
                + _as_decimal(self.potassium_percentage)
            )
            if total_npk > 100:
                errors["__all__"] = (
                    f"Total NPK percentages cannot exceed 100%. "
                    f"Current total: {total_npk}% "
                    f"(N: {self.nitrogen_percentage}%, "
                    f"P: {self.phosphorus_percentage}%, "
                    f"K: {self.potassium_percentage}%)"
                )

        # EPA WPS Compliance Validation - 40 CFR 170.309
        # Restricted Use Pesticides (RUPs) require certified applicator
        if self.restricted_use_pesticide and not self.applicator_certification:
            errors["applicator_certification"] = (
                "Applicator certification is required for Restricted Use Pesticides (RUPs) "
                "per EPA Worker Protection Standard 40 CFR 170.309"
            )

        # REI validation - must be non-negative
        if self.rei_hours is not None and self.rei_hours < 0:
            errors["rei_hours"] = "Restricted Entry Interval (REI) cannot be negative"

        # PHI validation - must be non-negative
        if self.phi_days is not None and self.phi_days < 0:
            errors["phi_days"] = "Pre-Harvest Interval (PHI) cannot be negative"

        # REI reasonableness check (typical range 4-48 hours)
        if self.rei_hours is not None and self.rei_hours > 168:  # More than 7 days
            errors["rei_hours"] = (
                f"REI of {self.rei_hours} hours seems unusually high. " "Please verify against product label."
            )

        # PHI reasonableness check (typical range 0-120 days)
        if self.phi_days is not None and self.phi_days > 365:  # More than 1 year
            errors["phi_days"] = (
                f"PHI of {self.phi_days} days seems unusually high. " "Please verify against product label."
            )

        if errors:
            raise ValidationError(errors)

        super().clean()


class ProductionEvent(CommonEvent):
    PLANTING = "PL"
    HARVESTING = "HA"
    IRRIGATION = "IR"
    PRUNING = "PR"
    TRANSPLANTING = "TR"  # NEW - matches UI screenshot option "🌿 Transplanting - Plant relocation"
    # Sprint 2 Epic 2.1: Event Consolidation - Equipment merged into Production
    EQUIPMENT_MAINTENANCE = "EM"  # Merged from EquipmentEvent
    # Sprint 2 Epic 2.2: Missing USDA production types
    CULTIVATION = "CU"  # Mechanical weed removal, row cultivation
    THINNING = "TH"  # Plant density reduction

    # Phase 2 additions
    POLLINATION = "PO"  # Bee placement, pollinator management (almonds, tree fruit)
    POST_HARVEST_PROCESSING = "PH"  # Hulling, shelling, washing, sorting, packing
    CANOPY_MANAGEMENT = "CM"  # Leaf pulling, hedging, shoot positioning (distinct from Pruning)

    # Batch 3 (2026-06): Scope-1 fuel operations that previously had no structured
    # home — frost-fuel and orchard-floor mowing were either logged as Weather/General
    # (carbon-invisible: weather excluded, General flat 0.1) or miscategorized as CU
    # (tillage). Both route through the existing ProductionEvent fuel pipeline.
    FROST_PROTECTION = "FP"  # Wind machines / heaters / under-tree sprinklers on cold nights
    MOWING = "MO"  # Orchard-floor mowing / mulching / cover-crop or herbicide-strip management

    # Batch 4 (2026-08-19): parity with the activities Quick Organics offers a crop operation.
    # All three facts were already recordable — but only as FIELDS on some other event, which
    # is the wrong shape whenever the activity does not belong to that event:
    #   * a load leaves for the handler days after the harvest it came from, and one harvest
    #     can ship on several dates (§ 205.272 commingling turns on the LOAD, not the pick);
    #   * buffer-zone crop is disposed of on its own schedule and must never be sold as
    #     organic (§ 205.202(c));
    #   * an organic-seed search precedes planting and covers varieties that may never be
    #     planted — recording it only on a planting event loses the searches that succeeded.
    # They reuse the existing columns (handler/destination, buffer_disposition*,
    # seed_search_attempts), so this adds a shape, not a second home for the same fact.
    TRANSPORT = "TP"  # A load moving off-farm: destination, quantity, cleanout reference
    BUFFER_USE = "BU"  # Harvest or disposal from a § 205.202(c) buffer zone
    SEED_SEARCH = "SS"  # § 205.204(a)(1) organic-seed commercial-availability search

    PRODUCTION_EVENTS = (
        (PLANTING, "Planting"),
        (HARVESTING, "Harvesting"),
        (IRRIGATION, "Irrigation"),
        (PRUNING, "Pruning"),
        (TRANSPLANTING, "Transplanting"),  # NEW - enables complete transparency tracking
        # Sprint 2 additions
        (EQUIPMENT_MAINTENANCE, "Equipment Maintenance"),  # Merged from Equipment events
        (CULTIVATION, "Cultivation/Weed Control"),  # USDA aligned
        (THINNING, "Thinning"),  # USDA aligned
        # Phase 2 additions
        (POLLINATION, "Pollination"),  # Bee placement / pollinator management
        (POST_HARVEST_PROCESSING, "Post-Harvest Processing"),  # Hulling, shelling, washing, sorting, packing
        (CANOPY_MANAGEMENT, "Canopy Management"),  # Leaf pulling, hedging, shoot positioning
        # Batch 3 additions
        (FROST_PROTECTION, "Frost Protection"),  # Wind machines / heaters (Scope-1 fuel)
        (MOWING, "Mowing / Orchard-Floor"),  # Mowing, mulching, floor management
        # Batch 4 additions — see the note on the constants above
        (TRANSPORT, "Transport"),
        (BUFFER_USE, "Buffer Use"),
        (SEED_SEARCH, "Seed Search"),
    )

    type = models.CharField(max_length=2, choices=PRODUCTION_EVENTS)
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # New structured fields for better carbon calculations
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    area_covered = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Area covered in numeric format"
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    yield_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Quantity harvested or planted"
    )
    yield_unit = models.CharField(
        max_length=10,
        choices=UNIT_YIELD,
        default="lbs",
        blank=True,
        help_text="Yield unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Fuel consumed during production activity"
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
    )
    equipment_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Equipment operating hours"
    )
    transportation_distance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Transportation distance for logistics emissions",
    )
    transportation_unit = models.CharField(
        max_length=10,
        choices=UNIT_DISTANCE,
        default="miles",
        blank=True,
        help_text="Transportation unit",
    )
    production_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Production efficiency rating for carbon scoring",
    )

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    # Updated based on agricultural advisor + consumer trust analysis (2025-12-06)
    # Optimized for: farmer practicality, consumer trust, transparency-first approach
    seeds_source = models.CharField(
        max_length=50,
        choices=SEEDS_SOURCE,
        blank=True,
        null=True,
        help_text=(
            "Where the seed/planting stock came from (transparency field; does not affect carbon). "
            "For regulatory classification (organic/transitional/non-organic), use seed_certification_status."
        ),
    )
    # NOP Compliance: Seed Commercial Availability Search (NOP 5029)
    # When non-organic seed is used, NOP requires documentation of at least 3 supplier searches
    seed_search_attempts = models.JSONField(
        default=list,
        blank=True,
        help_text="Organic seed search documentation per NOP 5029. "
        "Format: [{supplier_name, date_contacted, result, notes}]",
    )
    # USDA's "Seed Records Part B" asks for the "Reason for Commercial Nonavailability: form,
    # quality, quantity". Those three words are not a UI convention — they are the statutory
    # test. § 205.2 defines "commercially available" as "the ability to obtain a production
    # input in an appropriate FORM, QUALITY, or QUANTITY to fulfil an essential function",
    # and § 205.204(a)(1) permits non-organic seed only when that test fails.
    #
    # `seed_search_attempts` records WHO was contacted and WHEN, with the outcome as free text
    # ("Available — certified organic Hass rootstock in stock"). Free text cannot be reviewed
    # against a three-part statutory test, so the ground for the exemption was unstructured.
    SEED_NONAVAILABILITY_REASON_CHOICES = [
        ("none_offered", "Not offered organically by any supplier contacted"),
        ("form", "Form — not available in the required form (§ 205.2)"),
        ("quality", "Quality — available stock did not meet quality requirements (§ 205.2)"),
        ("quantity", "Quantity — insufficient quantity available (§ 205.2)"),
        ("other", "Other (explain in the search notes)"),
    ]
    seed_nonavailability_reason = models.CharField(
        max_length=16,
        choices=SEED_NONAVAILABILITY_REASON_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Statutory ground for using non-organic seed (§ 205.204(a)(1); the form/quality/"
            "quantity test is § 205.2's definition of commercially available)."
        ),
    )
    # NOP Compliance: Seed Traceability (7 CFR 205.204 / NOP 5029)
    # Planting subtype (type="PL") only. Mirrors ChemicalEvent.supplier_name pattern (migration 0146).
    seed_supplier_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Name of the seed/planting stock supplier (NOP 7 CFR 205.204 traceability)",
    )
    seed_purchase_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date seed/planting stock was purchased (traceability to supplier invoice)",
    )
    seed_purchase_invoice = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Supplier invoice number for the seed/planting stock purchase",
    )
    seed_lot_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Supplier lot/batch identifier for the seed/planting stock",
    )
    seed_certification_status = models.CharField(
        max_length=30,
        choices=SEED_CERTIFICATION_STATUS,
        blank=True,
        null=True,
        help_text=(
            "Regulatory classification per NOP 7 CFR 205.204. "
            "Non-organic treated seed with prohibited substances disqualifies the crop."
        ),
    )
    seed_treatment = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Seed coatings, inoculants, or pelleting materials applied (NOP 7 CFR 205.204(a)(2))",
    )
    # USDA's "Seed Records Part C: Documentation of Allowability of Seed Treatments, Coatings,
    # or Inoculants" pairs every named treatment with a "Documentation of Allowed Status"
    # column. Trazo named the treatment and stopped there — the same "named but unjustified"
    # shape as the 2026-08-09 OMRI leak, where an input was labelled OMRI Listed with no
    # catalog row behind it.
    #
    # § 205.204(a)(2) permits untreated non-organic seed only when an equivalent organic
    # variety is not commercially available, and any treatment applied must itself be an
    # allowed substance (§ 205.601). "Neem oil coating" alone does not say which of those is
    # true, so the record cannot be reviewed.
    SEED_TREATMENT_BASIS_CHOICES = [
        ("untreated", "Untreated — no coating, inoculant or pelleting applied"),
        ("omri_listed", "OMRI-listed product (catalog entry on file)"),
        ("national_list", "Allowed under National List § 205.601"),
        ("certifier_approved", "Reviewed and approved by the certifying agent"),
        ("organic_seed", "Certified organic seed — treatment allowed for organic production"),
        ("not_documented", "Not documented yet"),
    ]
    seed_treatment_allowed_basis = models.CharField(
        max_length=24,
        choices=SEED_TREATMENT_BASIS_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Why this seed treatment is permitted (USDA Seed Records Part C, 'Documentation of "
            "Allowed Status'). A named treatment with no basis is unreviewable under "
            "§ 205.204(a)(2)."
        ),
    )
    # ---- Harvest lot identity (HA) — added 2026-08-15 -------------------------------
    #
    # 🔴 The § 205.103(b)(2) join key, and the largest gap the 2026-08-15 audit found.
    #
    # `lot_id` lives on History — the PRODUCTION header — and `SalesRecord` points at the
    # same header. So for a multi-pick operation, n harvest passes collapsed into one lot and
    # one sales pool, and the operation could not say which pick went to which buyer. For the
    # ICP — California wholesale avocado and citrus, picked over weeks — that is the normal
    # case, not an edge case.
    #
    # USDA's Guide is explicit: growers "with multiple fields of the same crop will need to
    # assign lot numbers to the crops harvested from different fields", and a lot links
    # "products to the fields of origin and the year or date". Both halves — field AND date —
    # are properties of the harvest pass, not of the season.
    #
    # Deliberately a free CharField, not a generated key: growers arrive with a lot scheme
    # their buyers already use, and overwriting it would break the trace it exists to support.
    # `suggest_harvest_lot_code()` offers one when the field is empty; it never overwrites.
    harvest_lot_code = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text=(
            "Lot identifier for THIS harvest pass (7 CFR 205.103(b)(2)). Links the pick to its "
            "block and date, and is what a sales record references. Leave blank to accept the "
            "suggested code."
        ),
    )

    # ---- Perennial planting stock (PL/TR) — added 2026-08-15 ------------------------
    #
    # 🔴 These three had NO home. `rootstock` in particular was written by three seeders and
    # sat on the consumer extra_data allow-list, so shoppers could be shown a rootstock the
    # grower had no field to enter — and the certifier packet carried a written disclosure
    # that "Trazo does not yet structure rootstock records in this export".
    #
    # For the ICP — California wholesale avocado, citrus and nut orchards — rootstock IS the
    # identity of a planting. "40 Hass on Duke 7" is the sentence a grower says out loud, and
    # the variety half of it was the only half that had a column. It also carries real
    # § 205.204 weight: rootstock is planting stock, so its organic status and, for perennials,
    # the (a)(4) twelve-month rule attach to it rather than to the scion variety.
    rootstock = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text=(
            "Rootstock the scion was grafted onto (e.g. 'Duke 7', 'Dusa clonal'). Planting "
            "stock under 7 CFR 205.2; its organic status is what § 205.204 tests."
        ),
    )
    plants_established = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=(
            "How many trees/plants went in. On a perennial replant this is the number a "
            "certifier reconciles against the nursery invoice — area alone does not say it."
        ),
    )
    plant_spacing = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text=(
            "Spacing or density as the grower records it (e.g. '27 ft x 22 ft', "
            "'73 trees/ac'). Free text on purpose: COG Pro's export carries both forms in two "
            "separate columns and growers use whichever their block plan uses."
        ),
    )

    # ---- § 205.105(e) excluded methods + § 205.204(a)(4) — added 2026-08-15 ------------
    #
    # Both were named as gaps by the Planting teardown and neither had a column anywhere.
    #
    # `seed_non_gmo_status` is the third leg of USDA Form 11's allowed-status triple. The
    # other two legs (on an allowed list / no prohibited treatment) are answered by
    # `seed_certification_status` and `seed_treatment_allowed_basis`; excluded methods had
    # no field, so the packet asserted an organic planting while saying nothing about the
    # one § 205.105 prohibition that is unconditional.
    seed_non_gmo_status = models.CharField(
        max_length=32,
        choices=SEED_NON_GMO_STATUS,
        blank=True,
        null=True,
        help_text=(
            "How the exclusion of GMO/excluded methods was established for this planting "
            "stock (7 CFR 205.105(e)). Blank means the question was not answered — which is "
            "NOT the same as 'not verified'."
        ),
    )
    stock_organic_management_start = models.DateField(
        blank=True,
        null=True,
        help_text=(
            "Date this planting stock came under continuous organic management. 7 CFR "
            "205.204(a)(4): PERENNIAL planting stock must be under organic management for at "
            "least ONE YEAR before the crop it produces may be sold as organic. Without this "
            "date the packet cannot show the year has elapsed — the grower's own nursery "
            "invoice date is the usual answer."
        ),
    )

    # Updated 2025-12-06: Aligned with transparency-first frontend choices
    water_source = models.CharField(
        max_length=50,
        choices=WATER_SOURCE,
        blank=True,
        null=True,
        help_text="Water source for irrigation - affects pump energy factor in carbon calculations (USDA NRCS)",
    )

    # USDA NASS 2023 Irrigation Fields - For Irrigation (IR) events
    # These fields enable accurate water usage estimation for transparency reporting
    irrigation_method = models.CharField(
        max_length=30,
        choices=IRRIGATION_METHOD,
        blank=True,
        null=True,
        help_text="Irrigation method used (USDA NASS 2023 categories for transparency)",
    )
    irrigation_depth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Irrigation depth applied (USDA NASS: ~27,154 gal/acre per inch)",
    )
    irrigation_depth_unit = models.CharField(
        max_length=10,
        choices=UNIT_DEPTH,
        default="inches",
        blank=True,
        null=True,
        help_text="Unit for irrigation depth measurement",
    )

    # Phase 2: Quality metric for harvest and post-harvest events
    brix_level = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(45)],
        help_text="Brix level (sugar content) - key quality metric for fruit crops",
    )

    # Sprint 2 Epic 2.1: Equipment Maintenance fields (merged from EquipmentEvent)
    # These fields are used when production_type = 'EM' (Equipment Maintenance)
    fuel_type = models.CharField(
        max_length=20,
        choices=FUEL_TYPES,
        blank=True,
        null=True,
        help_text="Fuel type for equipment (EPA emission factor selection)",
    )
    equipment_type = models.CharField(
        max_length=30,
        choices=EQUIPMENT_TYPE,
        blank=True,
        null=True,
        help_text="Type of equipment used (for carbon calculation accuracy)",
    )
    equipment_operation_type = models.CharField(
        max_length=2,
        choices=EQUIPMENT_OPERATION_TYPE,
        blank=True,
        null=True,
        help_text="Type of equipment operation (for Equipment Maintenance events)",
    )

    # 🔴 F5 (2026-08-21) — see `History.quality_grade` above. Both columns share one
    # crop-aware vocabulary now (`history/harvest_grades.py`); this one used to offer
    # Export Quality / Grade A / B / C / Domestic / Processing, which is not a grade family
    # any US packing record uses, and disagreed with the season header besides.
    harvest_quality_grade = models.CharField(
        max_length=MAX_GRADE_LENGTH,
        blank=True,
        null=True,
        help_text=(
            "Grade this pick was packed to, as stated on the packing record. Free text: the "
            "crop-aware suggestions live in history/harvest_grades.py. No `choices` — see "
            "History.quality_grade for why."
        ),
    )

    # Sprint 3.2 — Post-harvest storage traceability (NOP 205.272 commingling; FSMA 204 prep).
    # Used on Harvest (HA) events to connect harvested lot -> bin/cooler/warehouse -> sale.
    storage_location = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Post-harvest storage location (e.g., 'Cooler 3', 'Warehouse B-Bin-12') for lot traceback",
    )
    storage_temperature_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Storage temperature in °F (quality control + FSMA 204 KDE)",
    )

    # 2026-08 QO-parity — custom-harvest arrangements (§ 205.103(b)): ties the
    # harvest record to the harvest contract when an uncertified custom
    # harvester runs the pass (G6.1 module collects the standing arrangement;
    # this field ties the individual harvest event to it).
    harvest_contract_number = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        help_text="Custom-harvest contract or work-order reference for this pass",
    )
    # 2026-08 QO-parity — whole-vs-part parcel coverage on harvest (HA) and
    # planting (PL), mirroring ChemicalEvent.applied_scope. ProductionTab gates the
    # payload on HA or PL only — TR reuses the seed widget but not this pair, so do not
    # read this comment as evidence that a transplant carries a scope answer.
    # (§ 205.103(b)(2) audit sufficiency: records must identify WHERE the activity happened.
    # NOT (b)(1), which is "adapted to the particular business". Corrected 2026-08-15.)
    applied_scope = models.CharField(
        max_length=10,
        choices=APPLIED_SCOPE,
        blank=True,
        null=True,
        help_text="Whether this activity covered the entire parcel/planting or part of it",
    )
    applied_scope_detail = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Which rows/blocks/area, when applied_scope is 'part'",
    )
    grain_moisture = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Grain moisture percentage at harvest (Midwest corn/soy operations)",
    )
    # F43 (2026-06): tree-crop maturity metric — the correct vocabulary for the CA orchard ICP.
    # Avocado uses dry-matter % as the legal CA maturity standard (CDFA; Hass min ~20.8%); nuts use
    # kernel dry-matter at drydown. brix_level is for citrus/sugar fruit; grain_moisture is grain-only.
    dry_matter_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Dry matter % at harvest — avocado/nut maturity (CA Hass legal min ~20.8%)",
    )

    # WS-4 (2026-08) — harvest-record completeness for the HA subtype.
    # § 205.103(b)(2): records must track product from production to sale AND be accurate.
    amount_determination = models.CharField(
        max_length=20,
        choices=AMOUNT_DETERMINATION,
        blank=True,
        null=True,
        help_text="How the harvest quantity was determined — estimated or scale-verified (weigh ticket)",
    )
    harvest_date_end = models.DateField(
        blank=True,
        null=True,
        help_text="Last day of a multi-day harvest window (event date is the first day)",
    )
    harvest_destination = models.CharField(
        max_length=20,
        choices=HARVEST_DESTINATION,
        blank=True,
        null=True,
        help_text="First hop of the harvested lot — storage, off-farm handler, direct sale, feed, or other",
    )

    # --- Off-farm handling round trip (7 CFR 205.272 · CCOF G6.1) -------------------------
    #
    # 🔴 2026-08-16, CCOF grower-checklist audit. Item 6 asks for four facts about crop sent to
    # another certified operation: "what you sent, where you sent it, when you sent it, and what
    # you received as the outcome". Trazo could answer "where" (History.post_harvest_facilities)
    # and nothing else. The finished quantity was only ever INFERRED, as shrinkage between
    # harvest and sale at a ±10% tolerance — which is a plausibility check, not a record.
    #
    # These live on the harvest event rather than on History because a multi-pick season sends
    # several loads to the same huller on different dates, and the pack-out comes back per load.
    #
    # All optional: a grower who sells field-run answers none of them, and the packet says the
    # crop did not leave the farm for handling rather than printing a gap.
    sent_to_handler_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date this lot was delivered to the off-farm handler (CCOF: 'when you sent it').",
    )
    quantity_sent_to_handler = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="How much left the farm for handling (CCOF: 'what you sent').",
    )
    quantity_returned_from_handler = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Finished quantity received back — the pack-out / outturn figure (CCOF: 'what you "
            "received as the outcome'). For tree nuts this is normally a different unit from "
            "what was sent (in-shell in, shelled out), so the two carry separate units."
        ),
    )
    handler_quantity_unit = models.CharField(
        max_length=20,
        choices=UNIT_YIELD,
        blank=True,
        null=True,
        help_text="Unit for the quantity SENT to the handler.",
    )
    handler_return_unit = models.CharField(
        max_length=20,
        choices=UNIT_YIELD,
        blank=True,
        null=True,
        help_text=(
            "Unit for the quantity RECEIVED BACK. Separate from handler_quantity_unit on "
            "purpose — hulling changes the unit, and forcing one unit would invent a "
            "conversion nobody measured."
        ),
    )
    handler_document_reference = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text=(
            "Pack-out summary, settlement statement or receiving-document number from the "
            "handler — CCOF's 'invoices, pack-out summaries, or other final statements'."
        ),
    )
    # § 205.202(c): buffer-row crop may never be sold or represented as organic.
    # NULL means the question was not answered, NOT that no buffer exists.
    buffer_disposition = models.CharField(
        max_length=30,
        choices=BUFFER_DISPOSITION,
        blank=True,
        null=True,
        help_text="Disposition of crop from buffer rows for this harvest (7 CFR 205.202(c))",
    )
    #: Dispositions that put the buffer crop into commerce. USDA's Buffer Crop Disposition
    #: Record warns that these are the ones needing formal proof: "Commercial quantities of
    #: crops require more formal documentation (delivery tags and nonorganic sales records) to
    #: show that the buffer crop has not been represented as organic." A crop disked under or
    #: left in the field cannot be mis-sold, so demanding paperwork there would be Trazo
    #: inventing a requirement.
    BUFFER_DISPOSITIONS_ENTERING_COMMERCE = frozenset(
        {"sold_conventional", "fed_nonorganic_livestock", "given_away", "harvested_conventional"}
    )
    buffer_disposition_quantity = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text=(
            "How much buffer crop was removed, in the grower's own units — USDA's form gives "
            '"1 4x4 bin" as its example. Free text on purpose: buffer quantities are not '
            "mass-balanced anywhere, and a forced unit would invite a fabricated conversion."
        ),
    )
    buffer_disposition_evidence = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text=(
            "Documentation type and location proving the buffer crop was not represented as "
            'organic — USDA\'s "Documentation (type and location)" column, e.g. "Delivery tag '
            "and sales record, Apple Bob's, buffer-crop folder\" (7 CFR 205.202(c))."
        ),
    )

    def buffer_disposition_entered_commerce(self):
        """True when this harvest's buffer disposition put the crop into someone else's hands.

        The § 205.202(c) proof obligation attaches here and nowhere else — which is why the
        packet asks for evidence on these dispositions and stays silent on the rest.
        """
        return (self.buffer_disposition or "") in self.BUFFER_DISPOSITIONS_ENTERING_COMMERCE

    # Item #13: Pump depth and electricity source for irrigation (IR) events.
    # These fields enable accurate energy calculation per USDA NRCS pump curve methodology.
    pump_depth_ft = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Well pump depth in feet — affects irrigation energy calculation (USDA NRCS)",
    )
    electricity_source = models.CharField(
        max_length=20,
        choices=ELECTRICITY_SOURCE,
        blank=True,
        null=True,
        help_text="Electricity source for pump — affects CO2 emission factor",
    )

    # Irrigation/well water test — NOT a 7 CFR Part 205 requirement.
    #
    # 🔴 Corrected 2026-08-15. This block was headed "NOP Compliance" and cited § 205.272
    # (handler commingling) and § 205.671 (exclusion from sale on residue exceedance).
    # Neither requires a producer water test: § 205.670(b)-(c) puts residue testing on the
    # CERTIFYING AGENT, at the agent's own expense, and USDA's Guide for Organic Crop
    # Producers says plainly that "the USDA organic regulations have very little to say
    # about irrigation and irrigation water quality." Microbial ag-water testing is FDA
    # FSMA Produce Safety Rule (21 CFR 112), and some certifiers ask for it contractually.
    # The certifier packet already states this correctly; these comments did not.
    # For the Irrigation (IR) subtype. CCOF requires an annual water-source analysis
    # demonstrating no prohibited substances / contamination. Mirrors the SoilManagementEvent
    # ST test_results pattern. Audit-only; never surfaced to consumers.
    water_test_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the irrigation/well water sample was taken or analyzed",
    )
    water_test_lab = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Name of the laboratory that analyzed the water sample",
    )
    water_test_results = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "List of {parameter, value, unit, result} dicts from the water analysis "
            "(e.g. coliform, nitrate, pH). Backs the certifier Water Quality record."
        ),
    )

    # NOP Compliance: Equipment Cleaning Logs (7 CFR 205.272)
    # For Equipment Maintenance (EM) subtype — required when equipment shared with conventional
    cleaning_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date equipment was cleaned (for shared equipment compliance)",
    )
    # ---- Purge records (§ 205.272) — parity with Quick Organics' Cleanout activity ----
    #
    # A purge is how a shared line, auger or bin is cleared: you run material through it and
    # discard the first output. Trazo recorded the cleaning METHOD and MATERIALS but had no
    # concept of a purge, so the question § 205.272 actually turns on — what happened to the
    # purged material — had nowhere to go. QO asks all three (verified in their live form,
    # 2026-08-19), and the third is the one an inspector cares about: purge material fed to
    # livestock, sold as conventional or discarded are different compliance stories.
    purge_material = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Material run through the equipment to purge it (§ 205.272).",
    )
    purge_quantity = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Quantity of purge material used, including its unit (e.g. '200 lb').",
    )
    purge_material_end_use = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "What happened to the purge material afterwards — fed to livestock, sold as "
            "conventional, discarded. § 205.272 turns on this, not on the purge itself."
        ),
    )

    # ---- Transport endpoints (§ 205.272 / § 205.307) — parity with QO's Transport activity ----
    #
    # `harvest_destination` is a CATEGORY (stored / sold / handler / feed). It answers "what
    # kind of move" and not "to whom, where" — and for a load going to a custom huller there is
    # no sale, so no SalesRecord carries the counterparty either. QO asks for the name and
    # address of both endpoints, with an explicit "it is on other documentation" escape.
    transport_origin = models.TextField(
        blank=True,
        null=True,
        help_text="Name and address the load left from. Blank if recorded on other documentation.",
    )
    transport_destination_address = models.TextField(
        blank=True,
        null=True,
        help_text="Name and address the load went to. Blank if recorded on other documentation.",
    )

    cleaning_method = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Cleaning method used (pressure wash, manual scrub, steam, etc.)",
    )
    # 2026-08 QO-parity — WHAT was cleaned (§ 205.272(a) commingling prevention).
    cleaning_asset_class = models.CharField(
        max_length=20,
        choices=CLEANING_ASSET_CLASS,
        blank=True,
        null=True,
        help_text="Asset class this cleanout covers (equipment, bins, storage, transport)",
    )
    cleaning_materials_used = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Cleaning materials/agents used (must be NOP-approved for organic)",
    )
    cleaned_by = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Person who performed or verified the cleaning",
    )
    shared_with_conventional = models.BooleanField(
        default=False,
        help_text="Whether this equipment is shared between organic and conventional operations",
    )
    cleaning_protocol_reference = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Reference to cleaning SOP or protocol used (e.g., SOP-CLEAN-001)",
    )

    # §E-5 — Custom operators and the cleaning event that covers a shared-equipment operation.
    #
    # In the UC Davis 2024 organic-almond study, cover-crop seeding, flame weeding, brush
    # shredding, winter sanitation, harvest and hulling are all custom-hired, and custom harvest
    # equipment moves between conventional and organic orchards on the same day. That is exactly
    # the § 205.272 commingling exposure — but the operation had no way to say "this pass was run
    # by a contractor" or "this is the cleaning that preceded it".
    #
    # Deliberately NOT a Custom Operator entity: the operator's NAME already has a home in
    # `performed_by`, and a contact/rate/scheduling record would be farm-management drift.
    operator_is_custom = models.BooleanField(
        default=False,
        help_text=(
            "Whether a custom operator (contractor) performed this operation with their own "
            "equipment. Their name goes in performed_by."
        ),
    )
    equipment_cleaning_event = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operations_covered",
        help_text=(
            "The Equipment Maintenance (EM) cleaning event that covers this operation "
            "(7 CFR 205.272). Linking it turns the page-1 contamination-prevention row from an "
            "aggregate count into per-operation evidence."
        ),
    )

    # NOP Compliance: Post-Harvest Sanitizer Detail (7 CFR 205.272 + § 205.605)
    # Chlorine/peracetic/hydrogen peroxide etc. used in post-harvest brush
    # wash require concentration + rinse-step documentation + a § 205.605
    # reference so an inspector can confirm the sanitizer is on the National
    # List (allowed synthetics in organic crop handling).
    sanitizer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Sanitizer used (e.g., 'Chlorine (sodium hypochlorite)', 'Peracetic acid', 'Hydrogen peroxide')",
    )
    sanitizer_ppm = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Applied/wash sanitizer concentration in ppm (dose at point of use)",
    )
    # NOP 5026 — chlorine materials. § 205.605(b) caps the RESIDUAL chlorine in
    # water at the point of last crop contact / discharge at the Safe Drinking
    # Water Act MRDL (4 mg/L free chlorine or chloramine; 0.8 mg/L chlorine
    # dioxide). This is distinct from the applied wash dose above.
    sanitizer_residual_ppm_at_discharge = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Residual chlorine (ppm) measured in water at the point of last crop "
            "contact / discharge — must not exceed the SDWA MRDL (4 mg/L free "
            "chlorine/chloramine, 0.8 mg/L chlorine dioxide) per NOP 5026 / § 205.605(b)."
        ),
    )
    rinse_step_documented = models.BooleanField(
        default=False,
        help_text=(
            "Potable-water rinse step performed after sanitizer contact. Whether one is required depends "
            "on the material and its use (7 CFR 205.605(b) sets conditions per material)."
        ),
    )
    sanitizer_nop_reference = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="National List reference (e.g., '§ 205.605(b) - Hydrogen peroxide') or OMRI certificate # for sanitizer",
    )

    # Phase 2 — Seed source drift detector (§ 205.204 / NOP 5029).
    # Populated by post_save signal on Planting (type="PL") events when the
    # seed certification status documents a non-organic source without the
    # required commercial-availability search, or is missing outright.
    # Shape mirrors ChemicalEvent.drift_warning so the frontend banner and
    # audit PDF can handle all three event models uniformly.
    # Null = no finding (either organic seed or no active OSP to compare).
    drift_warning = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Seed source drift payload (§ 205.204 / NOP 5029). Non-null when "
            "a Planting event's seed certification or search documentation is "
            "incomplete or prohibited."
        ),
    )

    def suggest_harvest_lot_code(self):
        """A lot code for this harvest pass, in USDA's own shape: crop + place + date.

        The Guide's worked examples are `OC0603` (Organic Corn, bin 06, 2003) and `B041433`
        (Broccoli, field 04, Julian day 143, 2003) — both encode WHAT, WHERE and WHEN. This
        produces a readable equivalent, e.g. `HAS-BLOCK2-20260410`, because a code a grower
        cannot read is a code they will not use on a bin tag.

        Returns None when the inputs for a meaningful code are missing — a lot code built from
        nothing but a date would collide across blocks, which is the failure it exists to stop.

        Two rules learned from running this over the existing records:

        * Every token is stripped to alphanumerics, not just the block. A product named "QA "
          produced the lot code `QA -BLOCKCEA-20251011` — a space inside an identifier that
          gets typed onto a bin tag, read back off it, and matched against a sales record.
        * Same crop + same block + same DAY is a real pattern (a morning pick and an afternoon
          pick), and it was minting one code for both. A lot code that is not unique identifies
          nothing, so a second pass on the same day gets a -2 suffix, a third -3, ordered by
          creation so an existing pass never has its code change under it.
        """
        if self.type != "HA" or not self.date:
            return None

        def _token(value, length):
            return "".join(ch for ch in (value or "") if ch.isalnum())[:length].upper()

        crop = ""
        history = getattr(self, "history", None)
        if history is not None:
            product = getattr(history, "product", None)
            crop = _token(getattr(product, "name", ""), 3)
        what = crop or _token(self.variety, 3)
        where = _token(self.block_id, 8)
        when = self.date.strftime("%Y%m%d")

        if not what and not where:
            return None
        base = "-".join(part for part in (what, where, when) if part)

        # Ordinal within the day/block, so a same-day second pick is distinguishable.
        # Needs a saved row on both sides: an unsaved event cannot be ordered against its
        # siblings, and `history` without a pk cannot be used as a filter value at all.
        # (`exclude(pk=None)` is not a no-op — it becomes `pk IS NULL` and silently drops
        # every row, which would make the first pick of a day look like the second.)
        if history is None or not getattr(history, "pk", None) or not getattr(self, "pk", None):
            return base
        try:
            earlier = (
                type(self)
                .objects.filter(
                    history=history,
                    type="HA",
                    date__date=self.date.date(),
                    block_id=self.block_id,
                    id__lt=self.pk,
                )
                .count()
            )
        except Exception:
            return base
        return base if earlier == 0 else f"{base}-{earlier + 1}"

    def save(self, *args, **kwargs):
        """Assign a harvest lot code when the operator did not supply one.

        Done here rather than in the serializer because a lot code that only exists when the
        record arrived through the web form is not a traceability scheme — the same production
        also gets harvest passes from templates, the API and the COG Pro import, and a pick
        with no lot is exactly the row an inspector cannot follow to a sales record
        (7 CFR 205.103(b)(2)).

        Runs AFTER the insert on create: the same-day ordinal needs this row's own id to know
        how many picks preceded it, so the code is written back in a second, narrow UPDATE.
        Never overwrites a value already present — an operator's own scheme wins.
        """
        super().save(*args, **kwargs)

        if self.type != "HA" or self.harvest_lot_code:
            return

        # Django's signature is save(force_insert, force_update, using, update_fields), and
        # every one of those is legal POSITIONALLY. Reading only `kwargs` meant a caller
        # writing `obj.save(False, False, None, ["description"])` looked like a full save, so
        # the lot code got written on top of someone else's narrow update — the exact
        # widening this guard exists to prevent. Resolve from args first, then kwargs.
        using = args[2] if len(args) > 2 else kwargs.get("using")
        update_fields = args[3] if len(args) > 3 else kwargs.get("update_fields")

        # An explicit update_fields that does not mention the code means the caller is
        # touching something else; assigning here would widen their write unexpectedly.
        if update_fields is not None and "harvest_lot_code" not in update_fields:
            return

        suggested = self.suggest_harvest_lot_code()
        if not suggested:
            return
        self.harvest_lot_code = suggested
        # `using` is carried through so the write-back lands on the same connection as the
        # insert it belongs to, rather than silently defaulting.
        super().save(update_fields=["harvest_lot_code"], using=using)

    def clean(self):
        """Model-level validation for production event values and business logic"""
        errors = {}

        # Validate area_covered - must be positive for most operations
        # Equipment Maintenance (EM), Pollination (PO), and Post-Harvest Processing (PH)
        # can have area_covered=0 (facility/equipment-based, not field-based).
        if self.area_covered is not None and self.area_covered <= 0 and self.type not in ("EM", "PO", "PH"):
            errors["area_covered"] = "Area covered must be greater than 0"

        # Validate transportation_distance - cannot be negative
        if self.transportation_distance is not None and self.transportation_distance < 0:
            errors["transportation_distance"] = "Transportation distance cannot be negative"

        # Validate yield_quantity - cannot be negative
        if self.yield_quantity is not None and self.yield_quantity < 0:
            errors["yield_quantity"] = "Yield quantity cannot be negative"

        # Validate equipment_hours - cannot be negative
        if self.equipment_hours is not None and self.equipment_hours < 0:
            errors["equipment_hours"] = "Equipment hours cannot be negative"

        # WS-4: multi-day harvest window — end date cannot precede the start (event date)
        if self.harvest_date_end and self.date and self.harvest_date_end < self.date.date():
            errors["harvest_date_end"] = "Harvest end date cannot be before the harvest start date"

        # §E-5 — the cleaning link must be capable of being evidence.
        # A cleaning performed AFTER the organic pass does not protect that pass (§ 205.272), and
        # a link to a non-cleaning event or to another production's record is not a record of
        # this one. Better to refuse the link than to print a page-1 PASS that rests on it.
        cleaning = self.equipment_cleaning_event
        if cleaning is not None:
            if cleaning.pk == self.pk:
                errors["equipment_cleaning_event"] = "An operation cannot be its own cleaning record."
            elif cleaning.type != self.EQUIPMENT_MAINTENANCE:
                errors["equipment_cleaning_event"] = (
                    "The linked event must be an Equipment Maintenance (EM) cleaning event."
                )
            elif self.history_id and cleaning.history_id != self.history_id:
                errors["equipment_cleaning_event"] = (
                    "The cleaning event must belong to the same production as this operation."
                )
            elif self.date and cleaning.date and cleaning.date > self.date:
                errors["equipment_cleaning_event"] = (
                    "The cleaning event is dated after this operation, so it cannot be the "
                    "cleaning that protected it (§ 205.272). Link the cleaning that preceded it."
                )

        # Business logic validation: reasonable area coverage
        if self.area_covered and self.area_covered > 1000:  # More than 1000 hectares
            errors["area_covered"] = (
                f"Area coverage ({self.area_covered} {self.area_unit}) seems unusually large. Please verify."
            )

        # Business logic: yield efficiency checks
        if self.yield_quantity and self.area_covered and self.yield_quantity > 0 and self.area_covered > 0:
            yield_per_hectare = float(self.yield_quantity) / float(self.area_covered)
            # Example check for unreasonably high yields (varies by crop)
            if self.yield_unit in ["kg", "tons"] and yield_per_hectare > 100000:  # 100 tons per hectare
                errors["yield_quantity"] = (
                    f"Yield rate ({yield_per_hectare:.1f} {self.yield_unit}/ha) seems unreasonably high. Please verify."
                )

        # Transportation efficiency check
        if self.transportation_distance and self.transportation_distance > 500:
            errors["transportation_distance"] = (
                f"Transportation distance ({self.transportation_distance} {self.transportation_unit}) is very long. Consider local processing to reduce carbon footprint."
            )

        # 7 CFR 205.204(a)(1): non-organic seed or planting stock is permitted only when an
        # equivalent organic variety is not commercially available, so the record must show
        # the ground for that determination. Zero documented suppliers means no ground at all.
        #
        # ⚠️ Not "at least 3". § 205.204 sets no count; three is a certifier expectation from
        # USDA's optional Guide for Organic Crop Producers. Kept in step with the serializer
        # (which is what the API actually runs — DRF never calls clean()) so the two cannot
        # drift apart again. TR is included: transplanting non-organic nursery stock carries
        # the same obligation and, on a perennial orchard, is the more common record.
        if self.type in SEED_SOURCED_SUBTYPES and self.seed_certification_status in NON_ORGANIC_SEED_STATUSES:
            attempts = self.seed_search_attempts or []
            documented = [
                a
                for a in attempts
                if isinstance(a, dict) and str(a.get("supplier_name") or a.get("supplier") or "").strip()
            ]
            if not documented:
                errors["seed_search_attempts"] = (
                    "Non-organic seed or planting stock may only be used when an equivalent "
                    "organic variety is not commercially available (7 CFR 205.204(a)(1)). "
                    "Record at least one supplier contacted in seed_search_attempts; "
                    "certifiers typically look for three."
                )

        # NOP 7 CFR 205.203(c)(1): Raw manure harvest interval. Blocks harvest entries
        # scheduled inside the unsafe window (90 or 120 days, by crop soil-contact flag).
        # Composted events that meet 205.203(c)(2) (temp >=131F + turnings >=5) do not trigger.
        # Bypass with obj.skip_manure_validation = True for historical data imports.
        if self.type == "HA" and not getattr(self, "skip_manure_validation", False):
            manure_error = self._validate_raw_manure_harvest_interval()
            if manure_error:
                errors["date"] = manure_error

        if errors:
            raise ValidationError(errors)

    def _validate_raw_manure_harvest_interval(self):
        """
        NOP 7 CFR 205.203(c)(1) raw-manure harvest-interval validator.

        Returns an error message string if the harvest date violates the 90/120-day
        window after a raw manure application on the same parcel; None otherwise.

        "Raw" means the source SoilManagementEvent does NOT satisfy the 205.203(c)(2)
        compost exception (temp >=131F + turnings >=5). Once the most recent non-exempt
        manure event is found, no need to check older ones — they age, they don't get fresher.
        """
        from datetime import timedelta

        if not self.date or not self.history or not self.history.parcel:
            return None

        crop_type = getattr(self.history, "crop_type", None)
        soil_contact = True  # Conservative default (120-day window)
        if crop_type is not None and crop_type.has_soil_contact is not None:
            soil_contact = crop_type.has_soil_contact
        interval_days = 120 if soil_contact else 90

        # SoilManagementEvent is defined later in this module; by the time this method
        # runs the entire module is loaded, so direct reference works without import.
        parcel_id = self.history.parcel_id
        manure_events = SoilManagementEvent.objects.filter(
            history__parcel_id=parcel_id,
            manure_application_date__isnull=False,
            manure_application_date__lte=self.date.date(),
        ).order_by("-manure_application_date")

        for ev in manure_events:
            # Skip events that satisfy the 205.203(c)(2) compost exception.
            # (c)(2) requires: C:N 25:1–40:1 + 131–170°F + method-specific duration
            # (windrow: 15d @temp + 5 turnings; static/in-vessel: 3d @temp).
            peak_temp = ev.compost_peak_temp_f
            turnings = ev.compost_turning_count
            duration = ev.compost_duration_days_at_temp
            cn = ev.compost_initial_cn_ratio
            method = ev.compost_method
            cn_ok = cn is not None and 25.0 <= float(cn) <= 40.0
            temp_ok = peak_temp is not None and 131.0 <= float(peak_temp) <= 170.0
            if method == "windrow":
                duration_ok = (duration or 0) >= 15 and (turnings or 0) >= 5
            elif method in ("static_aerated", "in_vessel"):
                duration_ok = (duration or 0) >= 3
            else:
                duration_ok = False  # Missing method — (c)(2) cannot be asserted.
            compost_exempt = cn_ok and temp_ok and duration_ok
            if compost_exempt:
                continue

            # NOP 5006 processed-manure exemption: manure processed to reduce
            # pathogens is exempt from the (c)(1) interval when the processing is
            # documented (peak temperature and/or an OMRI/supplier attestation).
            # Undocumented "processed_5006" falls through and is treated as raw.
            processed_5006_exempt = ev.manure_treatment == "processed_5006" and (
                ev.processed_manure_temp_f is not None or bool((ev.processed_manure_attestation or "").strip())
            )
            if processed_5006_exempt:
                continue

            application_date = ev.manure_application_date
            safe_harvest_date = application_date + timedelta(days=interval_days)
            if self.date.date() < safe_harvest_date:
                days_remaining = (safe_harvest_date - self.date.date()).days
                return (
                    f"NOP 7 CFR 205.203(c)(1): Harvest date {self.date.date()} is inside the "
                    f"{interval_days}-day raw-manure safety window. Last raw manure applied on "
                    f"{application_date}; earliest organic-eligible harvest is "
                    f"{safe_harvest_date} ({days_remaining} days after this harvest). "
                    f"Adjust the harvest date or confirm the amendment met 7 CFR 205.203(c)(2) "
                    f"compost requirements: initial C:N 25:1–40:1, 131–170°F, plus "
                    f"method-specific duration (windrow 15+ days with 5+ turnings; "
                    f"static aerated / in-vessel 3+ days)."
                )

            # Most recent non-exempt event is outside the window; older events are
            # guaranteed to be even older. No need to scan further.
            return None

        return None


class GeneralEvent(CommonEvent):
    name = models.CharField(max_length=150, help_text="Event name")
    observation = models.TextField(blank=True, null=True)

    # Activity details for comprehensive farm transparency
    activity_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Type of activity performed (e.g., Farm Maintenance, Equipment Setup)",
    )
    activity_name = models.CharField(
        max_length=200, blank=True, null=True, help_text="Specific name or description of the activity"
    )
    duration = models.CharField(
        max_length=50, blank=True, null=True, help_text="Duration of the activity (e.g., '2 hours', '1 day')"
    )
    people_involved = models.PositiveIntegerField(
        blank=True, null=True, help_text="Number of people involved in the activity"
    )

    # Contamination incident reporting — § 205.400(f)(1) + § 205.272.
    #
    # 🔴 Corrected 2026-08-15. This cited § 205.201(b), which is the clause permitting a
    # producer to SUBSTITUTE another government programme's plan for the OSP — nothing to do
    # with contamination. The notification duty is § 205.400(f)(1) ("immediately notify the
    # certifying agent concerning any... application, including drift, of a prohibited
    # substance"); the prevention standard is § 205.272. The certifier packet already uses
    # both correctly; the model and the registry never followed.
    CONTAMINATION_SOURCE_CHOICES = [
        ("spray_drift", "Spray Drift from Adjacent Land"),
        ("equipment", "Equipment Contamination"),
        ("storage", "Storage Commingling"),
        ("water", "Water Contamination"),
        ("soil", "Soil Contamination"),
        ("other", "Other"),
    ]
    is_contamination_incident = models.BooleanField(
        default=False,
        help_text="Whether this event documents a contamination incident (7 CFR 205.400(f)(1) / § 205.272)",
    )
    contamination_source = models.CharField(
        max_length=30,
        choices=CONTAMINATION_SOURCE_CHOICES,
        blank=True,
        null=True,
        help_text="Source of contamination (spray drift, equipment, storage, etc.)",
    )
    contamination_affected_area = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Area affected by contamination in acres",
    )
    corrective_action_taken = models.TextField(
        blank=True,
        null=True,
        help_text="Corrective actions taken in response to contamination incident",
    )
    corrective_action_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date corrective action was completed",
    )
    certifier_notified = models.BooleanField(
        default=False,
        help_text="Whether the certifying agent was notified of the contamination incident",
    )
    certifier_notification_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date certifier was notified of contamination incident",
    )

    extra_data = models.JSONField(blank=True, null=True)


# Bot probability at or above which a scan is not counted as a person.
#
# Was written inline at two different values — 0.3 in `company/views.py`, 0.5 in
# `analytics_service.py` — so the same farm's scan total depended on which screen asked.
# 0.5 is the value the create path already uses to gate scan notifications and the one the
# analytics service applies in five places; it is also the more forgiving of the two, so
# unifying on it never silently drops borderline-human traffic from a farmer's own numbers.
COUNTED_SCAN_BOT_SCORE_MAX = 0.5


class HistoryScanQuerySet(models.QuerySet):
    """Queryset for HistoryScan, carrying the ONE definition of a countable scan."""

    def counted(self):
        """
        Scans that count as a visit — the single source of truth for every scan TOTAL.

        Excludes:
          - duplicates: another scan of the same production within
            `DeduplicationService.DEFAULT_TIMEFRAME_MINUTES` from the same session
            fingerprint (a reload or a re-scan, not a second person);
          - likely bots: `bot_score >= COUNTED_SCAN_BOT_SCORE_MAX`.

        Both fields are non-null with DB defaults (`is_duplicate=False`, `bot_score=0.0`), so
        this filter never silently drops rows written by a path that does not set them —
        `public_history` sets neither, and its scans still count.

        Use this for every count, chart, quota and stat. Do NOT use it for the machinery that
        has to see raw rows: deduplication lookups, GDPR retention cleanup, bot-detection
        pattern analysis.
        """
        return self.filter(is_duplicate=False, bot_score__lt=COUNTED_SCAN_BOT_SCORE_MAX)


class HistoryScan(models.Model):
    """
    Enhanced QR scan tracking with 2025 privacy, performance & security standards
    Supports dual functionality: page view analytics + consumer feedback collection
    """

    objects = HistoryScanQuerySet.as_manager()

    # EXISTING CORE FIELDS
    history = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        related_name="history_scans",
    )
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)
    comment = models.TextField(blank=True, null=True)

    # PRIVACY & GDPR COMPLIANCE (2025 Standard)
    ip_hash = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        null=True,
        help_text="SHA-256 hash of IP address for privacy-safe analytics",
    )
    consent_given = models.BooleanField(default=False, help_text="GDPR consent for analytics tracking")
    consent_timestamp = models.DateTimeField(null=True, blank=True, help_text="When consent was given")
    data_retention_until = models.DateTimeField(null=True, blank=True, help_text="Auto-cleanup date (GDPR compliance)")

    # ENHANCED GEOLOCATION (Privacy-safe)
    country_code = models.CharField(max_length=2, blank=True, help_text="ISO country code (privacy-safe)")
    region = models.CharField(max_length=100, blank=True, help_text="State/region only (no city for privacy)")

    # LEGACY FIELDS (Deprecated - use privacy-safe alternatives above)
    ip_address = models.CharField(max_length=45, blank=True, null=True, help_text="DEPRECATED: Use ip_hash instead")
    city = models.CharField(max_length=100, blank=True, null=True, help_text="DEPRECATED: Use region instead")
    country = models.CharField(max_length=100, blank=True, null=True, help_text="DEPRECATED: Use country_code instead")

    # SESSION & DEDUPLICATION
    session_hash = models.CharField(
        max_length=64, db_index=True, blank=True, help_text="Privacy-safe browser fingerprint for deduplication"
    )
    is_duplicate = models.BooleanField(default=False, help_text="Mark duplicate scans within timeframe")
    original_scan = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Link to original scan if this is a duplicate",
    )

    # BOT DETECTION & QUALITY CONTROL
    bot_score = models.FloatField(default=0.0, help_text="Bot probability (0.0=human, 1.0=bot)")
    is_verified_human = models.BooleanField(default=False, help_text="Passed human verification checks")
    user_agent_hash = models.CharField(max_length=64, blank=True, help_text="Hashed user agent for pattern analysis")

    # CLAIM TOKEN — opaque token returned to the client so anonymous scans can be
    # linked to an account after sign-in, without exposing sequential IDs (IDOR prevention).
    claim_token = models.CharField(
        max_length=43,
        unique=True,
        db_index=True,
        blank=True,
        help_text="Opaque token for anonymous scan claiming (prevents IDOR)",
    )

    # ENGAGEMENT & ANALYTICS
    scan_type = models.CharField(
        max_length=20,
        choices=[
            ("qr", "QR Code Scan"),
            ("feedback", "Feedback Only"),
            ("review", "Full Review"),
            ("share", "Social Share"),
        ],
        default="qr",
        help_text="Type of interaction",
    )
    engagement_score = models.FloatField(default=0.0, help_text="Engagement quality (time spent, interactions)")
    referrer_type = models.CharField(
        max_length=50,
        blank=True,
        choices=[
            ("qr", "QR Code"),
            ("direct", "Direct Link"),
            ("social", "Social Media"),
            ("search", "Search Engine"),
            ("email", "Email"),
            ("other", "Other"),
        ],
        default="qr",
        help_text="How user reached the page",
    )

    # PERFORMANCE INDEXES
    class Meta:
        indexes = [
            # Time-series queries for dashboard analytics
            models.Index(fields=["date", "history"], name="historyscan_date_history_idx"),
            # Session deduplication queries
            models.Index(fields=["session_hash", "date"], name="historyscan_session_date_idx"),
            # Rate limiting by IP hash
            models.Index(fields=["ip_hash", "date"], name="historyscan_ip_date_idx"),
            # GDPR cleanup queries
            models.Index(fields=["data_retention_until"], name="historyscan_retention_idx"),
            # Quality filtering (exclude bots/duplicates)
            models.Index(fields=["is_duplicate", "bot_score"], name="historyscan_quality_idx"),
            # Consent management
            models.Index(fields=["consent_given", "date"], name="historyscan_consent_idx"),
            # Analytics queries by scan type
            models.Index(fields=["scan_type", "date"], name="historyscan_type_date_idx"),
        ]
        verbose_name = "History Scan"
        verbose_name_plural = "History Scans"

    def save(self, *args, **kwargs):
        if not self.claim_token:
            import secrets

            self.claim_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Scan {self.id} - {self.history} - {self.date.strftime('%Y-%m-%d')}"

    def is_privacy_compliant(self):
        """Check if scan data follows privacy best practices"""
        return bool(
            self.ip_hash  # Uses hashed IP, not raw
            and not self.ip_address  # No raw IP stored
            and self.consent_given  # Has user consent
            and self.data_retention_until  # Has cleanup date
        )

    def is_high_quality(self):
        """Check if scan is high quality (human, not duplicate, engaged)"""
        return bool(not self.is_duplicate and self.bot_score < 0.3 and self.engagement_score > 0.1)

    def get_location_display(self):
        """Get privacy-safe location display"""
        # Skip placeholder/default values
        has_country = self.country_code and self.country_code != "XX"
        has_region = self.region and self.region != "Unknown"

        if has_country and has_region:
            return f"{self.region}, {self.country_code.upper()}"
        elif has_country:
            return self.country_code.upper()
        # Fallback to legacy data if new data not available
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return None


class EquipmentEvent(CommonEvent):
    """Events related to equipment maintenance, repairs, and fuel consumption"""

    # Equipment event types
    MAINTENANCE = "MN"
    REPAIR = "RE"
    CALIBRATION = "CA"
    FUEL_CONSUMPTION = "FC"
    BREAKDOWN = "BD"
    INSPECTION = "EI"

    EQUIPMENT_TYPE_CHOICES = [
        (MAINTENANCE, "Maintenance"),
        (REPAIR, "Repair"),
        (CALIBRATION, "Calibration"),
        (FUEL_CONSUMPTION, "Fuel Consumption"),
        (BREAKDOWN, "Breakdown"),
        (INSPECTION, "Inspection"),
    ]

    type = models.CharField(max_length=2, choices=EQUIPMENT_TYPE_CHOICES, default=MAINTENANCE)
    equipment_name = models.CharField(max_length=100, blank=True)
    fuel_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for EPA emission factor calculation",
    )
    maintenance_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hours_used = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    area_covered = models.CharField(max_length=100, blank=True)
    extra_data = models.JSONField(blank=True, null=True)

    # New structured fields for better carbon calculations
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    equipment_type_structured = models.CharField(
        max_length=30,
        choices=[
            ("tractor_small", "Small Tractor (<75 HP)"),
            ("tractor_medium", "Medium Tractor (75-150 HP)"),
            ("tractor_large", "Large Tractor (>150 HP)"),
            ("irrigation_pump", "Irrigation Pump"),
            ("harvester", "Combine Harvester"),
            ("sprayer", "Field Sprayer"),
            ("cultivator", "Cultivator/Plow"),
            ("transport", "Transport Vehicle"),
        ],
        null=True,
        blank=True,
        help_text="Structured equipment type for carbon calculations",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed (renamed from fuel_amount for clarity)",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
    )
    hours_operated = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Hours operated (renamed from hours_used for clarity)",
    )
    area_worked = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Area worked in numeric format"
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    operation_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Operation efficiency rating for carbon scoring",
    )
    observation = models.TextField(blank=True, null=True, help_text="Equipment event observations")

    def clean(self):
        """Model-level validation for equipment event values and business logic"""
        from django.core.exceptions import ValidationError

        errors = {}

        # Validate fuel_consumed is non-negative
        if self.fuel_consumed is not None and self.fuel_consumed < 0:
            errors["fuel_consumed"] = "Fuel consumed cannot be negative"

        # Validate hours_operated is non-negative
        if self.hours_operated is not None and self.hours_operated < 0:
            errors["hours_operated"] = "Hours operated cannot be negative"

        # Validate maintenance_cost is non-negative
        if self.maintenance_cost is not None and self.maintenance_cost < 0:
            errors["maintenance_cost"] = "Maintenance cost cannot be negative"

        # Validate area_worked is non-negative
        if self.area_worked is not None and self.area_worked < 0:
            errors["area_worked"] = "Area worked cannot be negative"

        # Business logic validations

        # If fuel consumption is provided, hours operated should also be provided for accuracy
        if self.fuel_consumed and self.fuel_consumed > 0 and not self.hours_operated:
            if "hours_operated" not in errors:
                errors["hours_operated"] = "Hours operated should be provided when fuel consumption is recorded"

        # Validate reasonable fuel efficiency (basic sanity check)
        if self.fuel_consumed and self.fuel_consumed > 0 and self.hours_operated and self.hours_operated > 0:
            fuel_per_hour = float(self.fuel_consumed) / float(self.hours_operated)

            # Reasonable fuel consumption: 0.5L/hr to 50L/hr (covers small pumps to large tractors)
            if fuel_per_hour > 50:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably high. Check values."
                )
            elif fuel_per_hour < 0.5:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably low. Check values."
                )

        # Validate reasonable operating hours (max 1000 hours for multi-day operations)
        if self.hours_operated and self.hours_operated > 1000:
            errors["hours_operated"] = "Hours operated cannot exceed 1000 hours per event"

        if errors:
            raise ValidationError(errors)

        super().clean()

    class Meta:
        verbose_name = "Equipment Event"
        verbose_name_plural = "Equipment Events"


class SoilManagementEvent(CommonEvent):
    """Events related to soil testing, amendments, and organic matter management"""

    # Soil management event types
    SOIL_TEST = "ST"
    PH_ADJUSTMENT = "PA"
    ORGANIC_MATTER = "OM"
    COVER_CROP = "CC"
    TILLAGE = "TI"
    COMPOSTING = "CO"
    GRAZING = "GR"
    # Biodiversity / habitat (GTM-v3): documented habitat PRACTICES — facts only, never a score.
    HABITAT_DEVELOPMENT = "HD"  # planted/established habitat (hedgerow, insectary, riparian, living floor)
    NESTING_SHELTER = "NS"  # installed wildlife structures (owl/raptor/bee/bat boxes, insect hotel)
    # §E-2 — Lab analysis of any sampled matrix. ONE subtype with a `sample_matrix` enum rather
    # than one subtype per matrix: the record a certifier reads is identical (lab, sample id,
    # report date, results); only what was sampled differs. UC Davis 2024 organic-almond study:
    # leaf samples in July at 1/20 ac, hull samples at harvest at 1/40 ac, four compost samples
    # per delivery, soil every other year at three depths.
    LAB_ANALYSIS = "LA"

    SOIL_TYPE_CHOICES = [
        (SOIL_TEST, "Soil Test"),
        (PH_ADJUSTMENT, "pH Adjustment"),
        (ORGANIC_MATTER, "Organic Matter Addition"),
        (COVER_CROP, "Cover Crop"),
        (TILLAGE, "Tillage"),
        (COMPOSTING, "Composting"),
        (GRAZING, "Grazing Management"),
        (HABITAT_DEVELOPMENT, "Habitat Development"),
        (NESTING_SHELTER, "Nesting / Shelter Structures"),
        (LAB_ANALYSIS, "Lab Analysis"),
    ]

    SAMPLE_MATRIX_CHOICES = [
        ("soil", "Soil"),
        ("leaf", "Leaf tissue"),
        ("petiole", "Petiole"),
        ("hull", "Hull"),
        ("compost", "Compost"),
        ("water", "Irrigation water"),
    ]

    type = models.CharField(max_length=2, choices=SOIL_TYPE_CHOICES, default=SOIL_TEST)
    soil_ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    organic_matter_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amendment_type = models.CharField(max_length=100, blank=True)
    amendment_amount = models.CharField(max_length=100, blank=True)
    # Specific product identity for the amendment. amendment_type is only a generic
    # category (compost/manure/gypsum/...); the NOP/CCOF input record (7 CFR 205.203 /
    # CCOF Input Record) needs the actual product + manufacturer.
    amendment_product_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Specific commercial product name of the amendment, e.g. Malibu Compost Bu's Blend.",
    )
    amendment_manufacturer = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Who MAKES the product (label attribution). Not who sold it — see amendment_supplier_name.",
    )

    # --- Amendment purchase traceability (7 CFR 205.103(b)(1)-(2)) -------------------------
    #
    # 🔴 2026-08-16, CCOF grower-checklist audit. CCOF item 1 names "fertilizer, compost, soil
    # amendments, planting mixes" in one breath and asks for receipts. `ChemicalEvent` has
    # carried supplier / purchase date / invoice / quantity / lot since Sprint 3; this model
    # carried a product name and a manufacturer and nothing else. On a certified organic
    # orchard compost is routinely the largest purchased input by tonnage AND by dollar, so
    # the one input a grower most needs to trace was the one input with no purchase record.
    #
    # The consequence was not theoretical: the packet's mass-balance section builds its
    # "Inputs Purchased" table from ChemicalEvent alone and prints
    # "[REVIEW] Mass balance cannot be reconciled" when it finds nothing — a flag a
    # compost-fed operation could not clear no matter how carefully it logged.
    #
    # Field names mirror ChemicalEvent's deliberately (`*_supplier_name`, `*_purchase_date`,
    # `*_purchase_invoice`, `*_lot_number`) so the export, the Supplier List workbook and the
    # § 11 evidence lambdas can treat the two models the same way.
    #
    # ⛔ Never seed these from a template. A template that fills in a supplier and an invoice
    # number writes a purchase that did not happen into an audit file (see the Smart Setup
    # backdated-glyphosate incident, 2026-08-02).
    amendment_supplier_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Who the amendment was BOUGHT from — the name on the receipt (CCOF Input Record).",
    )
    amendment_purchase_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date on the purchase receipt / invoice for this amendment.",
    )
    receipt_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="soil_receipts",
        help_text="Uploaded receipt file behind amendment_purchase_invoice (see ChemicalEvent.receipt_document).",
    )
    amendment_purchase_invoice = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Invoice or receipt number, so the packet points an inspector at the paper record.",
    )
    amendment_quantity_purchased = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total amount bought on this invoice (for the § 205.103(b)(2) mass balance).",
    )
    amendment_quantity_purchased_unit = models.CharField(
        max_length=20,
        choices=UNIT_AMENDMENT,
        blank=True,
        null=True,
        help_text="Unit for the purchased quantity. Same vocabulary as amendment_amount_unit.",
    )
    amendment_lot_number = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        help_text="Manufacturer lot / batch number from the bag, tote or delivery ticket.",
    )

    test_results = models.JSONField(null=True, blank=True)  # Store complex test data
    # §E-2 — WHAT was sampled. The results themselves stay in `test_results` (where the soil-test
    # form has always written them, so historical ST rows keep working); the read serializer
    # flattens that JSON into named fields so the display registry and the PDF can reach them.
    sample_matrix = models.CharField(
        max_length=20,
        choices=SAMPLE_MATRIX_CHOICES,
        blank=True,
        null=True,
        help_text="Material submitted to the lab (LA subtype): soil, leaf, petiole, hull, compost or water.",
    )
    carbon_sequestration_potential = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    # The farmer's own words, kept apart from `description`. `description` is NOT NULL and is
    # written by the 328+ AI templates as well as by hand, so it cannot be quoted to shoppers as
    # a grower's voice. Five of the seven event models already had this column; soil and pest did
    # not, which is why a cover-crop or trap-monitoring note could never reach the consumer card.
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Biodiversity / habitat fields (for HD / NS subtypes). Facts only — free-text species/notes
    # live in extra_data (mirrors cover_crop_species); the living-floor / bugs / birds proof rides
    # on the event photo album + an optional wildlife_observed note. No counts beyond structures, no score.
    habitat_type = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        help_text="Habitat practice (HD) or structure (NS) — e.g. hedgerow, insectary_strip, barn_owl_box",
    )
    habitat_structure_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of structures installed (NS subtype, e.g. 6 barn-owl boxes)",
    )
    habitat_install_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "When the habitat was established (HD) or the structures installed (NS). "
            "Drives the consumer maturity story (an 8-year-old hedgerow vs a new one) and "
            "gives a certifier a date for the practice."
        ),
    )

    # Grazing management fields (for GR subtype)
    animal_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Type of grazing animal (e.g., sheep, goats, cattle)",
    )
    animal_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of animals used for grazing",
    )
    grazing_duration_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration of grazing period in days",
    )
    grazing_purpose = models.CharField(
        max_length=50,
        choices=[
            ("weed_control", "Weed Control"),
            ("cover_crop", "Cover Crop Termination"),
            ("soil_health", "Soil Health"),
            ("vegetation_management", "Vegetation Management"),
        ],
        blank=True,
        null=True,
        help_text="Primary purpose of the grazing activity",
    )

    # Numeric amendment field to replace legacy string field
    amendment_amount_numeric = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amendment amount in numeric format (replaces legacy string field)",
    )
    amendment_amount_unit = models.CharField(
        max_length=10,
        choices=UNIT_AMENDMENT,
        default="kg",
        blank=True,
        help_text="Unit for amendment_amount_numeric",
    )

    # Standardized fields for carbon calculations (matching ProductionEvent pattern)
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    area_covered = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Area covered in numeric format"
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed during soil management activity",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
    )
    fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for EPA emission factor calculation",
    )
    equipment_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Equipment operating hours"
    )
    transportation_distance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Transportation distance for logistics emissions",
    )
    transportation_unit = models.CharField(
        max_length=10,
        choices=UNIT_DISTANCE,
        default="miles",
        blank=True,
        help_text="Transportation unit",
    )
    production_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Production efficiency rating for carbon scoring",
    )

    # Additional soil management fields for comprehensive data capture
    working_depth = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Working depth for tillage or soil operations"
    )
    depth_unit = models.CharField(
        max_length=10,
        choices=[
            ("cm", "Centimeters"),
            ("inches", "Inches"),
            ("m", "Meters"),
        ],
        default="cm",
        blank=True,
        help_text="Depth measurement unit",
    )
    soil_texture = models.CharField(
        max_length=50,
        choices=[
            ("clay", "Clay"),
            ("clay_loam", "Clay Loam"),
            ("loam", "Loam"),
            ("sandy_loam", "Sandy Loam"),
            ("sand", "Sand"),
            ("silt", "Silt"),
            ("silt_loam", "Silt Loam"),
        ],
        blank=True,
        null=True,
        help_text="Soil texture classification",
    )
    soil_moisture = models.CharField(
        max_length=20,
        choices=[
            ("dry", "Dry"),
            ("moderate", "Moderate"),
            ("moist", "Moist"),
            ("wet", "Wet"),
        ],
        blank=True,
        null=True,
        help_text="Soil moisture condition during operation",
    )
    weather_conditions = models.CharField(
        max_length=200, blank=True, null=True, help_text="Weather conditions during soil management"
    )
    temperature_range = models.CharField(
        max_length=50, blank=True, null=True, help_text="Temperature range during operation"
    )
    equipment_used = models.CharField(
        max_length=200, blank=True, null=True, help_text="Equipment used for soil management operation"
    )

    # NOP Compliance: Amendment Organic Approval (7 CFR 205.203(b))
    amendment_organic_approved = models.CharField(
        max_length=20,
        choices=ORGANIC_APPROVED,
        blank=True,
        null=True,
        help_text="Whether this amendment/input is approved for organic farming (7 CFR 205.203(b))",
    )

    # Nitrogen content of the amendment, % by weight AS APPLIED.
    #
    # Two things depend on this and both were silently incomplete without it:
    #
    #  1. CARBON. Post-application field N2O depends on the nitrogen applied, whatever
    #     carried it. ChemicalEvent fertilisers declare N via nitrogen_percentage, but soil
    #     amendments had no N field at all — so on an organic orchard, where compost is
    #     usually the LARGEST nitrogen source, the biggest contributor to field N2O was
    #     counted as zero. (Pilot: 170 t of compost at ~1% N is ~1,540 kg N, roughly 25x
    #     the nitrogen in the season's fertigation.)
    #
    #  2. CALIFORNIA ILRP. Every irrigated CA grower files an Irrigation & Nitrogen
    #     Management Plan summary reporting total nitrogen APPLIED from all sources and
    #     nitrogen REMOVED in the harvested crop. "All sources" includes compost and
    #     manure, so a total built only from ChemicalEvent under-reports the filing.
    #
    # BASIS MATTERS — read this before changing the help text.
    #
    # Compost analyses report N on BOTH an "as-is / as-received" basis and a "dry weight"
    # basis, and compost is typically 30-50% moisture, so the two differ by roughly 2x.
    # The amendment_amount a grower enters is the delivered (wet) tonnage off the weigh
    # ticket, so the N% must be on the SAME as-received basis or the computed kg of N is
    # out by that factor. The UI says so explicitly rather than leaving it to be guessed.
    #
    # Typical DRY-weight values (WSU Tree Fruit, "Compost Considerations"): green/yard
    # waste 0.8-2.0%, manure-based 1-3% (avg ~1.5%). At ~40% moisture those correspond to
    # roughly 0.5-1.2% and 0.6-1.8% AS RECEIVED, which is what the help text quotes.
    amendment_nitrogen_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Nitrogen content of the amendment, % by weight ON THE SAME AS-RECEIVED (wet) "
            "BASIS as the tonnage entered above — use the 'as is' column of the supplier's "
            "analysis, not the 'dry weight' column (they differ by ~2x). Drives field N2O "
            "and the CA ILRP total-nitrogen-applied figure."
        ),
    )

    # NOP Compliance: Compost Temperature Tracking (7 CFR 205.203(c)(2))
    # Required for on-farm composting: must reach 131-170°F; windrow 15+ days @temp,
    # static aerated / in-vessel 3+ days @temp.
    compost_peak_temp_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Peak temperature reached during composting in °F (must reach 131-170°F per 7 CFR 205.203(c)(2))",
    )
    compost_duration_days_at_temp = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=(
            "Number of days compost maintained required temperature "
            "(windrow: 15+ days; static aerated / in-vessel: 3+ days per 7 CFR 205.203(c)(2))"
        ),
    )
    compost_turning_count = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Number of times compost was turned (minimum 5 turnings for windrow per 7 CFR 205.203(c)(2))",
    )

    # NOP Compliance: Initial C:N ratio + method (7 CFR 205.203(c)(2))
    # Regulatory: a pile with C:N outside 25:1-40:1 at start of composting
    # does NOT satisfy § 205.203(c)(2) and must be treated as raw manure
    # under (c)(1) 90/120-day intervals.
    COMPOST_METHOD_WINDROW = "windrow"
    COMPOST_METHOD_STATIC_AERATED = "static_aerated"
    COMPOST_METHOD_IN_VESSEL = "in_vessel"
    COMPOST_METHOD_CHOICES = [
        (COMPOST_METHOD_WINDROW, "Windrow (turned, open air)"),
        (COMPOST_METHOD_STATIC_AERATED, "Static Aerated Pile"),
        (COMPOST_METHOD_IN_VESSEL, "In-Vessel"),
    ]
    compost_method = models.CharField(
        max_length=20,
        choices=COMPOST_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Compost method (7 CFR 205.203(c)(2)). Windrow requires 15+ days at "
            "131–170°F with 5+ turnings; static aerated / in-vessel require 3+ days "
            "at 131–170°F."
        ),
    )
    compost_initial_cn_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Initial carbon-to-nitrogen ratio (C:N) of the compost feedstock. "
            "7 CFR 205.203(c)(2) requires 25:1–40:1 at the start of composting. "
            "Outside this range, the pile must be handled as raw manure under (c)(1)."
        ),
    )
    # F24 (2026-06): complete the NOP 5021 compost record. A single peak temp + day count is not a
    # monitoring log — a certifier needs the feedstock and the actual temperature readings over time.
    compost_feedstock = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text="Feedstock composition/source (e.g., 'horse manure + straw + green waste') — NOP 5021",
    )
    compost_temperature_log = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Temperature-monitoring readings over the composting period (date · temp · turned?) — "
            "the NOP 5021 monitoring log. One reading per line."
        ),
    )
    # USDA's Compost Production Record heads every sheet with the batch identity and how the
    # temperature was taken. Without them a § 205.203(c)(2) log is unattributable: an inspector
    # holding two piles and one temperature series cannot tell which pile it describes, and a
    # reading with no stated depth or instrument cannot be reproduced.
    compost_unit_id = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Compost pile, windrow or unit ID this batch's readings belong to (NOP 5021).",
    )
    compost_temp_reading_method = models.CharField(
        max_length=160,
        blank=True,
        null=True,
        help_text=(
            "Where and how the temperature was taken — e.g. 'probe at 36 in depth, mid-windrow'. "
            "USDA's form asks for the location AND method because a surface reading and a core "
            "reading on the same pile disagree."
        ),
    )

    # NOP Compliance: Raw Manure Harvest Interval (7 CFR 205.203(c)(1))
    # (c)(1) governs raw animal manure pre-harvest intervals; composted materials
    # live under (c)(2). Do not confuse the citations — an inspector flags either.
    MANURE_INTERVAL_CHOICES = [
        ("120", "120 days — edible portion contacts soil (root crops, leafy greens)"),
        ("90", "90 days — edible portion does NOT contact soil (tree fruit, trellised crops)"),
        ("na", "N/A — composted manure or no manure applied"),
    ]
    manure_harvest_interval = models.CharField(
        max_length=5,
        choices=MANURE_INTERVAL_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Required harvest interval after raw manure application: "
            "120 days if crop contacts soil, 90 days otherwise (7 CFR 205.203(c)(1))"
        ),
    )
    manure_application_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date raw manure was applied (used to calculate earliest safe harvest date)",
    )
    manure_harvest_date_planned = models.DateField(
        blank=True,
        null=True,
        help_text=(
            "Harvest date the grower planned when the manure went on. USDA's crop "
            "documentation form records estimated AND actual harvest dates side by side; the "
            "actual date is the harvest event itself, so this is the estimate."
        ),
    )

    # NOP 5006 — Processed Animal Manures in Organic Crop Production.
    # A third manure class sits between raw (c)(1) and composted (c)(2):
    # manure PROCESSED to reduce human pathogens (heat-dried, pelletized,
    # thermophilic PFRP) that does NOT meet the (c)(2) compost definition is
    # still exempt from the (c)(1) 90/120-day raw interval. The exemption is
    # granted only when DOCUMENTED (processing temperature and/or an OMRI/
    # supplier attestation); undocumented "processed" manure is handled as raw.
    MANURE_TREATMENT_CHOICES = [
        ("raw", "Raw / uncomposted animal manure — 90/120-day interval applies (c)(1)"),
        ("composted", "Composted per 7 CFR 205.203(c)(2) — no interval"),
        ("processed_5006", "Processed to reduce pathogens per NOP 5006 — no interval"),
    ]
    manure_treatment = models.CharField(
        max_length=16,
        choices=MANURE_TREATMENT_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Animal-manure processing class. 'processed_5006' (heat-dried / "
            "pelletized / PFRP) exempts the crop from the raw-manure harvest "
            "interval when supported by a processing temperature or an OMRI / "
            "supplier attestation (NOP 5006)."
        ),
    )
    processed_manure_temp_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Peak processing temperature (°F) for NOP 5006 processed manure (pathogen reduction).",
    )
    processed_manure_attestation = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text=(
            "Supplier / OMRI attestation for NOP 5006 processed manure "
            "(e.g., 'OMRI-listed heat-processed poultry pellets, PFRP') — the "
            "documentation basis for the raw-interval exemption."
        ),
    )

    # ------------------------------------------------------------------
    # USDA Manure Application / Food Crop Harvest Interval Record (form #9)
    # ------------------------------------------------------------------
    # The published form carries two columns Trazo had no home for:
    #
    #   "How Applied / Incorporated"     e.g. "Manure spreader disk in"
    #   "Manure Type, Form and Source"   e.g. "Chicken, dry, on farm"
    #
    # USDA writes the second as ONE free-text column, but it is plainly three facets, and
    # storing three enums lets the packet reconstruct "Chicken, dry, on farm" while keeping
    # the data queryable. Splitting is safe here in a way it was NOT for
    # `buffer_disposition_quantity` (kept free text): a bin count has no closed vocabulary,
    # whereas the animal, the form and on/off-farm all do.
    #
    # None of these are added to `record_completeness`. The forms are OPTIONAL under
    # § 205.103 — an operation may keep records in any format — and no CFR paragraph
    # enumerates these facets. Requiring them would be Trazo inventing a rule, the same
    # call already made for #7 `application_purpose`.
    MANURE_APPLICATION_METHOD_CHOICES = [
        ("broadcast_incorporated", "Broadcast, incorporated (disked or tilled in)"),
        ("broadcast_surface", "Broadcast, left on the surface"),
        ("injected", "Injected below the surface"),
        ("banded", "Banded or side-dressed"),
        ("fertigation", "Applied through irrigation (fertigation)"),
        ("top_dressed", "Top-dressed / mulched around plantings"),
        ("other", "Other — described in the notes"),
    ]
    manure_application_method = models.CharField(
        max_length=32,
        choices=MANURE_APPLICATION_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "How the manure was applied and whether it was incorporated — USDA's "
            '"How Applied / Incorporated" column (example: "Manure spreader disk in"). '
            "Recorded because the form asks; it does NOT change the 90/120-day interval, "
            "which turns on edible-portion soil contact under § 205.203(c)(1)(ii)-(iii)."
        ),
    )
    MANURE_ANIMAL_SOURCE_CHOICES = [
        ("poultry", "Poultry (chicken, turkey, duck)"),
        ("cattle", "Cattle / dairy"),
        ("horse", "Horse"),
        ("sheep_goat", "Sheep or goat"),
        ("swine", "Swine"),
        ("rabbit", "Rabbit"),
        ("mixed", "Mixed livestock"),
        ("other", "Other — described in the notes"),
    ]
    manure_animal_source = models.CharField(
        max_length=16,
        choices=MANURE_ANIMAL_SOURCE_CHOICES,
        blank=True,
        null=True,
        help_text='Animal the manure came from — the "Chicken" in USDA\'s "Chicken, dry, on farm".',
    )
    MANURE_FORM_CHOICES = [
        ("dry", "Dry / solid"),
        ("bedded_pack", "Bedded pack (manure with bedding)"),
        ("slurry", "Slurry"),
        ("liquid", "Liquid"),
        ("pelletized", "Pelletized or granulated"),
    ]
    manure_form = models.CharField(
        max_length=16,
        choices=MANURE_FORM_CHOICES,
        blank=True,
        null=True,
        help_text='Physical form as applied — the "dry" in USDA\'s "Chicken, dry, on farm".',
    )
    MANURE_ORIGIN_CHOICES = [
        ("on_farm", "Produced on this operation"),
        ("off_farm", "Brought in from off the farm"),
    ]
    manure_origin = models.CharField(
        max_length=16,
        choices=MANURE_ORIGIN_CHOICES,
        blank=True,
        null=True,
        help_text=(
            'Where the manure came from — the "on farm" in USDA\'s "Chicken, dry, on farm". '
            "For off-farm manure the supplier goes in `amendment_manufacturer`; a second "
            "supplier field would be a second writer of one fact."
        ),
    )

    def manure_type_form_source_display(self):
        """USDA's single "Manure Type, Form and Source" column, rebuilt from the three facets.

        Returns "" when nothing is recorded — the caller decides whether an empty column is a
        gap, because these facets are form parity, not a § 205.103 requirement.
        """
        parts = [
            self.get_manure_animal_source_display() if self.manure_animal_source else "",
            self.get_manure_form_display() if self.manure_form else "",
            self.get_manure_origin_display() if self.manure_origin else "",
        ]
        return ", ".join(p for p in parts if p)

    # Sprint 5.1 — Drift detector (same contract as ChemicalEvent.drift_warning).
    # Populated when amendment_type does not resolve to an approved input on
    # the establishment's active OSP.
    drift_warning = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Drift detector payload (7 CFR 205.400(f)(2)). Non-null when this "
            "event's amendment is not in the active OSP's approved_inputs — "
            "treated as an operation change requiring certifier notification."
        ),
    )

    def clean(self):
        """Model-level validation for soil management event values and business logic"""
        errors = {}

        # Validate area_covered - must be positive for most operations
        if self.area_covered is not None and self.area_covered <= 0:
            errors["area_covered"] = "Area covered must be greater than 0"

        # Validate transportation_distance - cannot be negative
        if self.transportation_distance is not None and self.transportation_distance < 0:
            errors["transportation_distance"] = "Transportation distance cannot be negative"

        # Validate equipment_hours - cannot be negative
        if self.equipment_hours is not None and self.equipment_hours < 0:
            errors["equipment_hours"] = "Equipment hours cannot be negative"

        # Validate fuel_consumed is non-negative
        if self.fuel_consumed is not None and self.fuel_consumed < 0:
            errors["fuel_consumed"] = "Fuel consumed cannot be negative"

        # Business logic validation: reasonable area coverage
        if self.area_covered and self.area_covered > 1000:  # More than 1000 hectares
            errors["area_covered"] = (
                f"Area coverage ({self.area_covered} {self.area_unit}) seems unusually large. Please verify."
            )

        # If fuel consumption is provided, hours operated should also be provided for accuracy
        if self.fuel_consumed and self.fuel_consumed > 0 and not self.equipment_hours:
            if "equipment_hours" not in errors:
                errors["equipment_hours"] = (
                    "Equipment hours should be provided when fuel consumption is specified for accurate carbon calculations."
                )

        # Validate reasonable fuel efficiency (basic sanity check)
        if self.fuel_consumed and self.fuel_consumed > 0 and self.equipment_hours and self.equipment_hours > 0:
            fuel_per_hour = float(self.fuel_consumed) / float(self.equipment_hours)

            # Reasonable fuel consumption: 0.5L/hr to 50L/hr (covers small pumps to large tractors)
            if fuel_per_hour > 50:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably high. Check values."
                )
            elif fuel_per_hour < 0.5:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably low. Check values."
                )

        # Grazing event validation
        if self.type == self.GRAZING:
            if self.animal_type and not self.animal_count:
                errors["animal_count"] = "Number of animals is required when animal type is specified"
            if self.animal_count and self.animal_count > 10000:
                errors["animal_count"] = f"Animal count ({self.animal_count}) seems unusually high. Please verify."
            if self.grazing_duration_days and self.grazing_duration_days > 365:
                errors["grazing_duration_days"] = (
                    f"Grazing duration ({self.grazing_duration_days} days) exceeds one year. Please verify."
                )

        # §E-2 — Lab analysis validation. A lab record whose matrix is unknown cannot support
        # anything: a certifier reading a micronutrient application needs to know the deficiency
        # was shown in LEAF tissue or in SOIL, and the two are not interchangeable. The results
        # themselves are not forced — a farmer may log the sample on the day it ships and fill in
        # the numbers when the report arrives.
        if self.type == self.LAB_ANALYSIS and not self.sample_matrix:
            errors["sample_matrix"] = (
                "Select what was sampled (soil, leaf, petiole, hull, compost or water). "
                "A lab analysis without its matrix cannot support a deficiency claim."
            )

        # Transportation efficiency check
        if self.transportation_distance and self.transportation_distance > 500:
            errors["transportation_distance"] = (
                f"Transportation distance ({self.transportation_distance} {self.transportation_unit}) is very long. Consider local processing to reduce carbon footprint."
            )

        # NOP Manure validation (7 CFR 205.203(c)(1))
        # The 90/120-day interval only applies to RAW manure. Composted (c)(2)
        # and processed (NOP 5006) manure are interval-exempt, so don't force
        # an interval selection for them.
        if (
            self.manure_application_date
            and not self.manure_harvest_interval
            and self.manure_treatment not in ("composted", "processed_5006")
        ):
            errors["manure_harvest_interval"] = (
                "Harvest interval (90 or 120 days) is required when a raw manure application date is specified."
            )

        # NOP 5006 — processed-manure consistency. An interval-exempt class
        # (processed / composted) must NOT also carry a raw 90/120-day interval:
        # an event cannot be both raw-with-interval AND processed-exempt, and that
        # contradiction reads to a certifier as reclassifying to dodge a flag.
        if self.manure_treatment in ("processed_5006", "composted") and self.manure_harvest_interval in (
            "90",
            "120",
        ):
            errors["manure_harvest_interval"] = (
                "A processed (NOP 5006) or composted (§ 205.203(c)(2)) manure event is "
                "interval-exempt and cannot also carry a raw 90/120-day interval. Set the "
                "interval to N/A, or classify the event as raw manure."
            )
        # Claiming the NOP 5006 exemption requires documenting the processing.
        if (
            self.manure_treatment == "processed_5006"
            and self.processed_manure_temp_f is None
            and not (self.processed_manure_attestation or "").strip()
        ):
            errors["manure_treatment"] = (
                "NOP 5006 processed manure requires a processing temperature or an "
                "OMRI/supplier attestation to claim the raw-interval exemption. Without "
                "documentation, classify the event as raw manure."
            )

        # NOP Manure interval vs crop soil-contact classification.
        # Per 7 CFR 205.203(c)(1):
        #   (c)(1)(ii) — 120 days required when edible portion has direct
        #                soil contact (root crops, leafy greens).
        #   (c)(1)(iii) — 90 days required when edible portion does NOT
        #                 have direct soil contact (tree fruit, nuts,
        #                 elevated vine fruits).
        # A farmer selecting "120" for a canopy crop is factually wrong
        # even when the resulting harvest date would satisfy the stricter
        # rule: the choice wording includes "edible portion contacts
        # soil" which is false for avocados / apples / etc., and a CCOF
        # inspector reads that as a record-keeping failure under
        # § 205.103. Block the mismatch at save time so the log cannot
        # contain the wrong classification. We only BLOCK when the crop
        # has an authoritative ``has_soil_contact`` flag set — when the
        # crop type is unknown or the flag is None, we defer to the
        # PDF-side consistency linter rather than guessing.
        if self.manure_harvest_interval in ("90", "120"):
            crop_type = None
            try:
                crop_type = self.history.crop_type
            except Exception:  # noqa: BLE001 — FK not populated yet during form clean()
                crop_type = None
            if crop_type is not None and getattr(crop_type, "has_soil_contact", None) is not None:
                has_contact = bool(crop_type.has_soil_contact)
                selected = self.manure_harvest_interval
                if has_contact and selected == "90":
                    errors["manure_harvest_interval"] = (
                        f"Crop '{crop_type.name}' has direct soil contact for its "
                        "edible portion, so 7 CFR 205.203(c)(1)(ii) requires a "
                        "120-day pre-harvest interval. Selecting 90 days is a "
                        "record-keeping mismatch even if the harvest date would "
                        "satisfy the stricter rule."
                    )
                elif not has_contact and selected == "120":
                    errors["manure_harvest_interval"] = (
                        f"Crop '{crop_type.name}' does NOT have direct soil "
                        "contact for its edible portion (tree / canopy crop), "
                        "so 7 CFR 205.203(c)(1)(iii) applies — the required "
                        "interval is 90 days. The '120 days — edible portion "
                        "contacts soil' choice is for root crops and leafy "
                        "greens; using it here mis-classifies the crop and "
                        "creates an inspector-visible record-keeping conflict."
                    )

        # NOP Composting validation (7 CFR 205.203(c)(1)+(c)(2))
        if self.type == self.COMPOSTING:
            if self.compost_peak_temp_f is not None:
                temp = float(self.compost_peak_temp_f)
                if temp < 90 or temp > 200:
                    errors["compost_peak_temp_f"] = (
                        f"Temperature ({temp}°F) seems outside reasonable range (90-200°F). Please verify."
                    )
            if self.compost_duration_days_at_temp is not None and self.compost_duration_days_at_temp > 365:
                errors["compost_duration_days_at_temp"] = "Duration at temperature exceeds one year. Please verify."
            if self.compost_turning_count is not None and self.compost_turning_count > 100:
                errors["compost_turning_count"] = "Turning count seems unusually high. Please verify."
            # § 205.203(c)(2) initial C:N must fall in 25:1–40:1 at start of composting.
            if self.compost_initial_cn_ratio is not None:
                ratio = float(self.compost_initial_cn_ratio)
                if ratio < 5 or ratio > 100:
                    errors["compost_initial_cn_ratio"] = (
                        f"Initial C:N ratio ({ratio}:1) is outside plausible feedstock range (5:1–100:1). "
                        "Please verify — typical NOP-compliant composts start at 25:1–40:1."
                    )

        if errors:
            raise ValidationError(errors)

    class Meta:
        verbose_name = "Soil Management Event"
        verbose_name_plural = "Soil Management Events"


class PestManagementEvent(CommonEvent):
    """Events related to pest monitoring, beneficial insect releases, and IPM practices"""

    # Pest management event types
    SCOUTING = "SC"
    BENEFICIAL_RELEASE = "BR"
    TRAP_MONITORING = "TM"
    PEST_IDENTIFICATION = "PI"
    THRESHOLD_ASSESSMENT = "TA"
    IPM_IMPLEMENTATION = "IP"
    # §E-4 — Cultural / sanitation control. 7 CFR 205.206(a) requires PREVENTIVE practices first,
    # and § 205.206(e) allows a substance only after those practices prove insufficient. Winter
    # sanitation is the preventive practice for navel orangeworm in a California orchard — and it
    # had no home in the model, so the single most common non-spray control an organic grower
    # performs was invisible to both the certifier and the consumer. UC Davis 2024 organic-almond
    # study: December mummy shake, blow and shred, custom-hired except the shredding.
    CULTURAL_CONTROL = "CU"

    PEST_TYPE_CHOICES = [
        (SCOUTING, "Scouting"),
        (BENEFICIAL_RELEASE, "Beneficial Release"),
        (TRAP_MONITORING, "Trap Monitoring"),
        (PEST_IDENTIFICATION, "Pest Identification"),
        (THRESHOLD_ASSESSMENT, "Threshold Assessment"),
        (IPM_IMPLEMENTATION, "IPM Implementation"),
        (CULTURAL_CONTROL, "Cultural / Sanitation Control"),
    ]

    CULTURAL_PRACTICE_CHOICES = [
        ("mummy_removal", "Mummy nut removal (hand poling)"),
        ("sanitation_shake", "Sanitation shake"),
        ("brush_shred", "Brush / mummy shredding"),
        ("pruning_removal", "Pruning removal and destruction"),
        ("field_sanitation", "Field sanitation / debris removal"),
        ("trap_crop", "Trap crop"),
    ]

    type = models.CharField(max_length=2, choices=PEST_TYPE_CHOICES, default=SCOUTING)
    cultural_practice = models.CharField(
        max_length=30,
        choices=CULTURAL_PRACTICE_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Preventive cultural practice performed (CU subtype). Evidence for § 205.206(a); "
            "documenting it is what lets § 205.206(e) justify any later substance application."
        ),
    )
    pest_species = models.CharField(max_length=200, blank=True)
    pest_pressure_level = models.CharField(max_length=50, blank=True)  # Low, Medium, High
    # F44 (2026-06): quantitative UC-IPM monitoring count — the actual data behind a scouting/trap
    # decision (e.g. "5 mites/leaf", "12% fruit infested", "8 moths/trap"). pest_pressure_level is
    # the qualitative summary; this is the measured number a certifier/PCA expects.
    monitoring_count = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Measured monitoring count (e.g. 5 mites per leaf) — SC/TM/PI",
    )
    monitoring_unit = models.CharField(
        max_length=20,
        choices=[
            ("per_leaf", "per leaf"),
            ("per_trap", "per trap"),
            ("per_tree", "per tree"),
            ("per_100_fruit", "per 100 fruit"),
            ("percent_infested", "% infested"),
            ("per_sample", "per sample"),
        ],
        blank=True,
        null=True,
        help_text="Unit for monitoring_count (UC IPM monitoring form vocabulary)",
    )
    beneficial_species = models.CharField(max_length=200, blank=True)
    release_quantity = models.CharField(max_length=100, blank=True)
    trap_count = models.IntegerField(null=True, blank=True)
    damage_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # F17 fix (2026-06): nullable so "not assessed" (None) is distinct from "below threshold" (False).
    # An unanswered NOP 205.206(e) threshold question must NOT be fabricated into a definitive
    # "below threshold" record on the audit export.
    action_threshold_met = models.BooleanField(null=True, blank=True, default=None)
    ipm_strategy = models.TextField(blank=True)
    # The farmer's own words, kept apart from `description` — see the matching note on
    # SoilManagementEvent. Without this column a grower's trap-monitoring or beneficial-release
    # note had nowhere to live and never reached the consumer card.
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    beneficial_insects_used = models.CharField(
        max_length=20,
        choices=[
            ("yes", "Yes - Using Beneficial Insects"),
            ("no", "No"),
            ("planning", "Planning to Implement"),
        ],
        blank=True,
        null=True,
        help_text="Whether beneficial insects are used for pest control",
    )

    # Beneficial-release traceability (BR subtype) — NOP 7 CFR 205.206 requires the SOURCE of any
    # introduced biological control to be documented; reusing beneficial_species/release_quantity
    # above, these add supplier + lot + organic status so a certifier can trace the release.
    beneficial_supplier = models.CharField(
        max_length=200, blank=True, null=True, help_text="Insectary/supplier the beneficials came from (BR)"
    )
    beneficial_lot_number = models.CharField(
        max_length=100, blank=True, null=True, help_text="Supplier lot / batch number for the release (BR)"
    )
    beneficial_organic_approved = models.CharField(
        max_length=10,
        choices=[("yes", "Yes"), ("no", "No"), ("unknown", "Unknown")],
        blank=True,
        null=True,
        help_text="Whether the beneficial organism is approved for organic systems (BR)",
    )

    # Trap monitoring (TM subtype) — trap_count above is the NUMBER OF TRAPS; these capture the
    # trap kind and the actual catch so an auditor sees real IPM pressure data.
    trap_type = models.CharField(
        max_length=20,
        choices=[
            ("sticky", "Sticky card"),
            ("pheromone", "Pheromone lure"),
            ("delta", "Delta trap"),
            ("bucket_funnel", "Bucket / funnel"),
            # Vertebrate trapping (§E-7, 2026-07). The option list was insect-only, but the
            # UC Davis 2024 organic-almond cost study budgets gopher traps twice a year and
            # ground-squirrel traps six times (March-October) — routine orchard work with
            # nowhere to be recorded. Vertebrate control is also the practice most likely to
            # be questioned at inspection, since the alternative is a rodenticide.
            ("gopher_trap", "Gopher trap"),
            ("ground_squirrel_trap", "Ground squirrel trap"),
            ("other", "Other"),
        ],
        blank=True,
        null=True,
        help_text="Kind of trap deployed (TM)",
    )
    pest_catch_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Insects caught across the traps this monitoring (TM) — not the # of traps"
    )

    chemical_free_period_days = models.PositiveIntegerField(
        blank=True, null=True, help_text="Days since last synthetic chemical application"
    )

    # Sprint 3 Epic 3.1: Fuel/Equipment fields for carbon calculations (matching SoilManagementEvent)
    area_covered = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Area covered during pest management activity",
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed during pest management activity",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
    )
    fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for EPA emission factor calculation",
    )
    equipment_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Equipment operating hours"
    )
    production_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Equipment efficiency level for carbon calculations",
    )

    # NOP Compliance: Pest Identification Verification (7 CFR 205.206)
    IDENTIFIED_BY_CHOICES = [
        ("farmer", "Farmer / Farm Staff"),
        ("agronomist", "Licensed Agronomist"),
        ("entomologist", "Entomologist"),
        ("extension_service", "Extension Service Agent"),
        ("crop_consultant", "Crop Consultant"),
        ("lab", "Laboratory Analysis"),
    ]
    identified_by = models.CharField(
        max_length=30,
        choices=IDENTIFIED_BY_CHOICES,
        blank=True,
        null=True,
        help_text="Who identified the pest species (7 CFR 205.206 - pest management practice standard)",
    )
    identification_method = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Method used for pest identification (e.g., field guide, lab analysis, visual inspection)",
    )

    # NOP Compliance: Action Threshold Rationale (7 CFR 205.206(e))
    threshold_rationale = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Justification for why action threshold was/wasn't met "
            "(e.g., '5 trap catches/week per UC Davis IPM guidelines'). "
            "Required per 7 CFR 205.206(e) before applying any pest control material."
        ),
    )

    def clean(self):
        """§E-4 — a cultural-control event must name the practice it performed.

        § 205.206(a) is satisfied by the SPECIFIC preventive practice, not by the category. "We
        did cultural control" supports nothing at inspection; "December mummy shake" is the
        record that later justifies, under § 205.206(e), applying a substance when it proved
        insufficient. Anything else about the event (area, crew, fuel) is optional as before.
        """
        from django.core.exceptions import ValidationError

        if self.type == self.CULTURAL_CONTROL and not self.cultural_practice:
            raise ValidationError(
                {
                    "cultural_practice": (
                        "Select the preventive practice performed (mummy removal, sanitation "
                        "shake, shredding, pruning removal, field sanitation or trap crop). "
                        "§ 205.206(a) is documented by the specific practice, not the category."
                    )
                }
            )

    class Meta:
        verbose_name = "Pest Management Event"
        verbose_name_plural = "Pest Management Events"


class BusinessEvent(CommonEvent):
    """Carbon-focused business events for transparency and consumer value"""

    # Business event types (legacy compatibility)
    CERTIFICATION = "CE"
    COMPLIANCE = "CM"
    INSPECTION = "IN"

    BUSINESS_TYPE_CHOICES = [
        (CERTIFICATION, "Certification"),
        (COMPLIANCE, "Compliance"),
        (INSPECTION, "Inspection"),
    ]

    # Business activity types.
    #
    # "carbon_credits" was withdrawn (2026-08-18). The `carbon_credits_earned` / `_unit`
    # columns are kept so any historical row keeps its data, but the activity is no longer
    # offerable: Trazo's methodology is direct operational emissions (§ Scope 1 only, EPA/USDA
    # factors), not the credit-grade accounting a traded credit implies, and a credit figure
    # on a public product page is the self-created sustainability claim EU ECGT 2024/825
    # (live 2026-09-27) and FTC 16 CFR 260.6 both reach. Do not re-add.
    BUSINESS_ACTIVITY_CHOICES = [
        ("certification", "Certification Event (organic, food safety, trade)"),
        ("sustainability_audit", "Sustainability Audit/Assessment"),
        ("verification", "Third-Party Verification"),
        ("compliance", "Regulatory Compliance Activity"),
        ("transparency", "Consumer Transparency Initiative"),
    ]

    # Sprint 2 Epic 2.2: Expanded certification types with GlobalG.A.P., Non-GMO, CNG
    #
    # What a farmer may still CHOOSE. Every entry names an issuing body or programme a
    # shopper can go and check, which is the same line `claim_authority` draws — after the
    # 2026-08-27 retirement below, every offered type is publishable and none needs a
    # "this will not reach a buyer" caveat on the form.
    OFFERED_CERTIFICATION_TYPE_CHOICES = [
        # Organic & Food Safety Certifications
        ("organic_usda", "USDA Organic"),
        ("regenerative", "Regenerative Organic Certified (ROC)"),
        # 2026-08-21: the ROP add-on (on top of USDA Organic) — a pilot farm held it and had
        # nowhere to log its certificate or inspection.
        ("real_organic", "Real Organic Project (ROP)"),
        ("cng", "Certified Naturally Grown (CNG)"),
        ("non_gmo", "Non-GMO Project Verified"),
        # Environmental & Sustainability Certifications
        ("rainforest_alliance", "Rainforest Alliance"),
        ("water_stewardship", "Water Stewardship Certification"),
        # Global Food Safety & Trade Certifications
        ("global_gap", "GlobalG.A.P. Certified"),
        ("fair_trade", "Fair Trade Certified"),
        ("food_safety", "SQF / Food Safety Certified"),
        ("kosher", "Kosher Certified"),
    ]

    # Retired 2026-08-27. NOT deleted: § 205.103(b)(2) records have to survive an
    # inspector's trace-back, so a farmer who logged one of these still gets their own
    # words back and the packet still prints a label instead of a raw slug. They are
    # simply no longer OFFERED, and `BusinessEventSerializer` refuses them on write.
    #
    # Why these two and not the rest: both name a claim with no issuing body behind it.
    # `claim_authority._WITHHELD_CERTIFICATION_TYPES` already kept them off every consumer
    # surface — "Carbon Neutral" is a general environmental benefit claim (16 CFR 260.4)
    # that also contradicts Trazo's own direct-operational-emissions methodology, and
    # "Sustainable Agriculture Standard" is the self-created sustainability label ECGT
    # 2024/825 bans outright from 2026-09-27. Withholding the value while still offering
    # the menu item left the farmer making a claim the product silently declined to show.
    DEPRECATED_CERTIFICATION_TYPE_CHOICES = [
        ("carbon_neutral", "Carbon Neutral Certification"),
        ("sustainable_agriculture", "Sustainable Agriculture Standard"),
    ]

    # The DISPLAY vocabulary — offered plus retired. This is what the field stores and what
    # `get_certification_type_display()` reads.
    CERTIFICATION_TYPE_CHOICES = OFFERED_CERTIFICATION_TYPE_CHOICES + DEPRECATED_CERTIFICATION_TYPE_CHOICES

    DEPRECATED_CERTIFICATION_TYPES = frozenset(k for k, _ in DEPRECATED_CERTIFICATION_TYPE_CHOICES)

    CARBON_CREDIT_UNITS = [
        ("tCO2e", "tCO2e (tonnes CO2 equivalent)"),
        ("kgCO2e", "kgCO2e (kilograms CO2 equivalent)"),
        ("credits", "Carbon Credits (units)"),
    ]

    VERIFICATION_STATUS_CHOICES = [
        ("pending", "Pending Verification"),
        ("verified", "Verified"),
        ("in_progress", "Verification In Progress"),
        ("failed", "Verification Failed"),
        ("not_applicable", "Not Applicable"),
    ]

    SUSTAINABILITY_PRACTICE_CHOICES = [
        ("cover_cropping", "Cover Cropping Implementation"),
        ("no_till", "No-Till Farming Adoption"),
        ("integrated_pest", "Integrated Pest Management"),
        ("water_conservation", "Water Conservation Measures"),
        ("renewable_energy", "Renewable Energy Installation"),
        ("composting", "On-Farm Composting Program"),
        ("biodiversity", "Biodiversity Conservation"),
        ("soil_health", "Soil Health Improvement"),
    ]

    type = models.CharField(max_length=2, choices=BUSINESS_TYPE_CHOICES, default=CERTIFICATION)
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")

    # New carbon-focused fields
    # 🔴 2026-08-20 — this defaulted to "certification", and the consumer page keys its copy
    # off this column: `business_type: "certification"` renders as a 🏆 **"Certification
    # Achievement"** with the line "A third-party certification was recorded for this crop",
    # at HIGH impact.
    #
    # So an INSPECTION (`type="IN"`) or a CDFA registration renewal (`type="CM"`) saved
    # without an explicit business_type was announced to shoppers as a third-party
    # certification the crop had achieved. A database default manufacturing an unearned
    # certification claim is exactly what FTC 16 CFR 260.6 reaches, and it is the same class
    # as the withdrawn carbon-credits activity documented above.
    #
    # No default now: `save()` derives it from the event's own subtype, which is the fact the
    # farmer actually chose.
    business_type = models.CharField(
        max_length=30,
        choices=BUSINESS_ACTIVITY_CHOICES,
        blank=True,
        help_text="Type of business or compliance activity recorded for this production",
    )

    #: Event subtype -> the activity it IS. `type` is what the farmer picked in the wizard;
    #: `business_type` is what the consumer page and the packet describe it as. They must agree.
    SUBTYPE_TO_BUSINESS_ACTIVITY = {
        "CE": "certification",
        "IN": "verification",
        "CM": "compliance",
    }
    certification_type = models.CharField(
        max_length=50,
        choices=CERTIFICATION_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Type of certification obtained or renewed",
    )
    carbon_credits_earned = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True, help_text="Amount of carbon credits generated or traded"
    )
    carbon_credits_unit = models.CharField(
        max_length=10, choices=CARBON_CREDIT_UNITS, default="tCO2e", blank=True, help_text="Unit for carbon credits"
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default="pending",
        help_text="Status of verification for consumer transparency",
    )
    sustainability_practice = models.CharField(
        max_length=30,
        choices=SUSTAINABILITY_PRACTICE_CHOICES,
        blank=True,
        null=True,
        help_text="Sustainability practice implemented",
    )

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    verified_certifier_name = models.CharField(
        max_length=150, blank=True, null=True, help_text="Name of the certifying organization for consumer trust"
    )

    # MVP Target Market Fields - Export operations need certificate references
    certificate_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Certificate reference number (GlobalG.A.P., phytosanitary, USDA Organic)",
    )

    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    def save(self, *args, **kwargs):
        """Keep `business_type` honest about what the record actually is.

        The consumer page describes the event from this column, so a wrong value here is a
        wrong CLAIM on a public page — an inspection announced as a certification the crop
        achieved. Derive it from the subtype the farmer chose whenever the caller did not set
        it explicitly, rather than defaulting every unsaid case to the strongest claim.
        """
        if not (self.business_type or "").strip():
            self.business_type = self.SUBTYPE_TO_BUSINESS_ACTIVITY.get(self.type, "compliance")
        super().save(*args, **kwargs)

    def clean(self):
        """Model-level validation for business event values and business logic"""
        from django.core.exceptions import ValidationError

        errors = {}

        # Validate carbon_credits_earned - must be non-negative
        if self.carbon_credits_earned is not None and self.carbon_credits_earned < 0:
            errors["carbon_credits_earned"] = "Carbon credits earned cannot be negative"

        # Business logic validation: reasonable carbon credit amounts
        if self.carbon_credits_earned and self.carbon_credits_earned > 10000:
            errors["carbon_credits_earned"] = (
                f"Carbon credits amount ({self.carbon_credits_earned} {self.carbon_credits_unit}) seems unusually large. Please verify."
            )

        # Validate business_type is not empty
        if not self.business_type or len(self.business_type.strip()) == 0:
            errors["business_type"] = "Business type is required"

        # Business logic: certification events should have certification_type
        if self.business_type == "certification" and not self.certification_type:
            errors["certification_type"] = "Certification type is required for certification events"

        if errors:
            raise ValidationError(errors)

    class Meta:
        verbose_name = "Business Event"
        verbose_name_plural = "Business Events"


class BuyerDocRequest(models.Model):
    """
    Phase 4 — buyer documentation request from the consumer proof view.

    A retail/wholesale buyer scanning a product can request supplier
    documentation (certificates, audit packet) without calling anyone. Each
    request becomes a lead on the farmer's dashboard plus an in-app
    notification. Public endpoint is rate-limited and deduplicated (same
    email + production within 24h is idempotent).
    """

    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("closed", "Closed"),
    ]

    production = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        related_name="buyer_doc_requests",
    )
    requester_name = models.CharField(max_length=120)
    requester_email = models.EmailField()
    organization = models.CharField(max_length=160, blank=True, default="")
    message = models.TextField(blank=True, default="", max_length=1000)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", db_index=True)
    # SHA-256 like HistoryScan.ip_hash — rate limiting without storing raw IPs.
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Buyer Documentation Request"
        verbose_name_plural = "Buyer Documentation Requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["production", "-created_at"], name="buyerdocreq_prod_date_idx"),
            models.Index(fields=["requester_email", "created_at"], name="buyerdocreq_email_date_idx"),
        ]

    def __str__(self):
        return f"{self.requester_email} -> {self.production_id} ({self.status})"


class SalesRecordQuerySet(models.QuerySet):
    """`objects` deliberately returns VOIDED rows too.

    The default has to be "everything", because the two places that must never lose a voided
    row are the certifier dossier and the records export — § 205.103(b)(4) is the reason the
    row was kept instead of deleted, and a manager that hid it would re-create the deletion it
    replaced. Callers that mean "sales that happened" ask for `.live()`.
    """

    def live(self):
        """Sales that still count: not voided."""
        return self.filter(voided_at__isnull=True)

    def voided(self):
        return self.filter(voided_at__isnull=False)


class SalesRecord(models.Model):
    """
    Lightweight sales record per production lot — the SOE traceback unit.

    Inspectors verify "crop and quantity sold, date of sale, buyer" at every
    annual inspection, and mass-balance audits are mandatory under the
    Strengthening Organic Enforcement rule. The legacy single History.sold_to
    field can't represent multiple sales from one lot; these records feed the
    audit PDF's Traceability + Mass-Balance sections.

    NOT consumer-facing — buyer identity and quantities are commercially
    sensitive (same policy as ChemicalEvent supplier fields).
    """

    production = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        related_name="sales_records",
    )
    #: WHICH harvest pass(es) this sale drew from — the other half of the § 205.103(b)(2)
    #: trace, added 2026-08-15.
    #:
    #: The production FK above says which SEASON; on a multi-pick operation that is not enough
    #: to answer "which pick went to this buyer", which is exactly the question a trace-back
    #: exercise asks. Many-to-many rather than a FK because a real load routinely combines
    #: several picks — a packer takes a truckload, not a pass.
    #:
    #: Optional on purpose. A grower who sells one lot per season should not be forced to
    #: build a link that carries no information, and pre-existing records have none; the
    #: packet degrades to the production-level trace and says so, rather than printing a gap.
    harvest_events = models.ManyToManyField(
        "history.ProductionEvent",
        blank=True,
        related_name="sales_records",
        limit_choices_to={"type": "HA"},
        help_text=(
            "Harvest pass(es) this sale drew from. Links buyer → lot → harvest for the "
            "7 CFR 205.103(b)(2) trace-back."
        ),
    )
    sale_date = models.DateField()
    buyer_name = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    #: MUST share History.UNIT_CHOICES — the harvest amount and the sale quantity are the two
    #: halves of the mass balance, and the audit export only prints the Balance line and the
    #: "sold exceeds harvest" review flag when `harvest_unit == sold_unit` (see
    #: audit_export_service._build_mass_balance_section). This field was the one unit column in
    #: the schema with no `choices` — History.production_unit and History.quantity_sold_unit
    #: both had them — so the frontend drifted to its own vocabulary and offered `tonnes` where
    #: harvest offers `tons`. Same pounds, different string, and § 205.103(b)(2) reconciliation
    #: silently disappeared from the packet with no warning printed.
    #:
    #: `default="kg"` is deliberately left alone rather than flipped to "lb": the model cannot
    #: know the farm's country, and the US-first resolution belongs in the editor
    #: (useDefaultUnits, which now seeds this field from the production's own harvest unit).
    quantity_unit = models.CharField(max_length=20, choices=History.UNIT_CHOICES, default="kg")
    invoice_number = models.CharField(max_length=80, blank=True, default="")

    #: What the operation was PAID for this sale.
    #:
    #: 🔴 2026-08-16, CCOF grower-checklist audit. CCOF item 7 has four parts — "what you sell,
    #: how much you sell, who you sold it to, and how much money you received" — and this model
    #: answered the first three and had no column for the fourth. The itemized sales table in
    #: the certifier packet had no value column either, so an inspector could verify volume but
    #: not consideration, and the operation could not produce the "sales summaries" CCOF names
    #: as an acceptable record.
    #:
    #: NULL, not 0.00. A recorded zero (a donation, a rejected load taken at no charge) is a
    #: fact; "not entered" is the absence of one, and collapsing them is the same conflation
    #: that made `Boolean("not_organic")` read as True on the consumer page (2026-07-31) and
    #: that `BusinessEvent.clean` tests with `is None` for exactly this reason.
    #:
    #: No currency column: Trazo has one market (US) and inventing a per-row currency the UI
    #: never asks for would put an unattested "USD" on a regulatory document. When a second
    #: market arrives, currency belongs on the OPERATION, not on each sale.
    sale_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Amount received for this sale, in USD. Blank means not recorded, never zero.",
    )

    # § 205.307 — sales documents for organic product must identify it as organic.
    organic_on_invoice = models.BooleanField(default=False)
    # § 205.103(b)(3) — records must identify the product by its § 205.301 labeling category,
    # which the boolean above cannot express. Blank = not documented (see the note on
    # `clean_transport_method` below for why this is not a defaulted value).
    organic_label_category = models.CharField(
        max_length=24,
        choices=ORGANIC_LABEL_CATEGORY_CHOICES,
        blank=True,
        default="",
    )

    # --- Shipment / transport block (§ 205.272(a); § 205.103(b)(2)) ---
    # One row is one sale AND its shipment: in wholesale practice each load is
    # invoiced, so the BOL pairs 1:1 with the invoice. The per-production
    # History.transport_* fields remain as the single-shipment legacy path.
    CLEAN_TRANSPORT_CHOICES = [
        ("affidavit", "Clean-transport affidavit on file"),
        ("inspected", "Inspected clean before loading"),
        ("dedicated_organic", "Dedicated organic vehicle"),
    ]
    bill_of_lading = models.CharField(max_length=80, blank=True, default="")
    carrier_name = models.CharField(max_length=120, blank=True, default="")
    vehicle_id = models.CharField(max_length=60, blank=True, default="")
    destination = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Ship-to location when different from the buyer (packer, drop yard, port).",
    )
    # A set method IS the documentation that transport integrity was addressed;
    # blank means not documented. Deliberately no separate boolean — a
    # default=False bool reads as an explicit "no" in evidence derivation
    # (see certifications.services.common_osp_records._has_content).
    clean_transport_method = models.CharField(max_length=20, choices=CLEAN_TRANSPORT_CHOICES, blank=True, default="")

    # --- USDA Clean Transport Affidavit (form #22) content ---
    # `clean_transport_method` above answers "how do you know the unit was clean" (affidavit /
    # inspected / dedicated). USDA's affidavit asks what that affidavit SAYS, and until now
    # Trazo stored only the fact that a document existed — a certifier reading the packet
    # learned a file was attached, not what it attested to.
    TRANSPORT_CLEANING_CHOICES = [
        ("swept", "Swept"),
        ("vacuum", "Vacuum"),
        ("air_blown", "Air blown"),
        ("washed", "Washed"),
        ("other", "Other — described in the notes"),
        ("not_required", "Not required — dedicated organic unit"),
    ]
    transport_cleaning_method = models.CharField(
        max_length=20,
        choices=TRANSPORT_CLEANING_CHOICES,
        blank=True,
        default="",
        help_text=(
            "How the transport unit was cleaned before loading (USDA's Swept / Vacuum / Air "
            "blown / Washed checkboxes). Distinct from clean_transport_method, which records "
            "how transport INTEGRITY was assured rather than how the unit was cleaned. Blank "
            "means not documented, never 'no cleaning'."
        ),
    )
    #: USDA: "Only used for organic products? ☐ yes ☐ no — if no, state products transported
    #: prior to organic." This is the single most useful line on the form when the unit is not
    #: dedicated: it is what lets an inspector judge the contamination risk (grain vs treated
    #: seed vs conventional produce are not equivalent).
    prior_products_transported = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "What the transport unit carried immediately before this organic load, when it is "
            "not a dedicated organic unit (7 CFR 205.272). Blank means not documented — it "
            "does NOT mean the unit was dedicated; `clean_transport_method` records that."
        ),
    )
    #: USDA: "Inspected and found free of ☐ foreign odors ☐ residues ☐ conventional products
    #: ☐ other". Conjunctive and multi-valued, so a list rather than the single-choice enum
    #: used for disjunctive questions like seed nonavailability.
    #:
    #: An EMPTY list means no inspection findings were recorded. It must never be rendered as
    #: "inspected and found clean" — that is an attestation nobody made.
    TRANSPORT_INSPECTION_CODES = {
        "foreign_odors": "Free of foreign odors",
        "residues": "Free of residues",
        "conventional_products": "Free of conventional products",
        "other": "Other findings — see notes",
    }
    transport_inspected_free_of = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "What the pre-loading inspection found the unit free of — list of codes from "
            "TRANSPORT_INSPECTION_CODES. Empty means no inspection was recorded, NOT a clean "
            "finding."
        ),
    )
    #: The notes both "Other" options above promise. TRANSPORT_CLEANING_CHOICES renders "Other —
    #: described in the notes" and TRANSPORT_INSPECTION_CODES renders "Other findings — see
    #: notes", and the packet printed both strings verbatim while this model had no notes column
    #: at all: a certifier read a pointer to a document that could not exist. Either the labels
    #: stop promising a description or the description exists; a compliance record earns more
    #: from the second. `clean()` refuses "other" without it, so the pointer is never dangling.
    transport_notes = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text=(
            "What the 'Other' cleaning method or 'Other' inspection finding actually was. "
            "Required whenever either is selected; blank otherwise means nothing to add."
        ),
    )

    def transport_inspection_display(self):
        """USDA's "Inspected and found free of" line, or "" when nothing was recorded.

        Unknown codes are passed through rather than dropped: a value someone stored is
        evidence of something, and silently discarding it would be the packet editing the
        record. Returns "" for empty so the caller decides how absence reads.
        """
        codes = self.transport_inspected_free_of
        if not isinstance(codes, list):
            return ""
        labels = [self.TRANSPORT_INSPECTION_CODES.get(c, str(c)) for c in codes if c]
        return ", ".join(labels)

    created_at = models.DateTimeField(auto_now_add=True)

    # --- Void, not delete -------------------------------------------------------------
    # 🔴 2026-09-07. Deleting a sale on a closed season is refused (§ 205.103(b)(4), and the
    # sale is the far end of the (b)(2) trail). But there was no update path either, so a
    # mistyped sale had no correction route at all. Voiding is what a paper audit trail does:
    # the row STAYS, struck through, with a stated reason — the same shape events use, where
    # the original is kept alongside the correction.
    #
    # ⛔ A voided row is not a deleted row. It stays in the certifier dossier and the records
    # export, marked. What it must NOT do is keep counting as a sale: see `live()`.
    voided_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this sale was voided. The row is kept; it stops counting as a sale.",
    )
    void_reason = models.TextField(
        blank=True,
        default="",
        help_text="Why it was voided, in the operator's words — a void with no reason is a "
        "deletion with extra steps.",
    )
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Who voided it. Kept because § 205.103(b)(2) asks who the record's author is.",
    )

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    objects = SalesRecordQuerySet.as_manager()

    class Meta:
        verbose_name = "Sales Record"
        verbose_name_plural = "Sales Records"
        ordering = ["-sale_date", "-created_at"]
        indexes = [
            models.Index(fields=["production", "-sale_date"], name="salesrecord_prod_date_idx"),
        ]

    def clean(self):
        """A labeling category on a sale whose invoice does not identify it as organic is a
        contradictory record, and the packet would print both halves.

        Refuse rather than reconcile: which half is true is the operation's call, not ours.
        """
        from django.core.exceptions import ValidationError

        if self.organic_label_category and not self.organic_on_invoice:
            raise ValidationError(
                {
                    "organic_label_category": (
                        "This sale records a § 205.301 labeling category but is not marked as "
                        "identifying the product as organic on the invoice. Set "
                        "'organic on invoice', or clear the labeling category."
                    )
                }
            )

        # "Other" is the only answer on this form that carries no information by itself, and
        # both labels tell the certifier a description follows. Refuse the pointer without the
        # target rather than print "Other — described in the notes" over an empty column.
        # "Not required — dedicated organic unit" is an answer ABOUT the unit being dedicated.
        # Against an affidavit/inspected load it is self-contradictory, and the packet would
        # print both halves as fact. Same treatment as the labeling-category contradiction
        # above: refuse rather than reconcile — which half is true is the operation's call.
        if self.transport_cleaning_method == "not_required" and self.clean_transport_method in (
            "affidavit",
            "inspected",
        ):
            raise ValidationError(
                {
                    "transport_cleaning_method": (
                        "'Not required — dedicated organic unit' contradicts a clean-transport "
                        "method of affidavit or pre-load inspection, which both describe a "
                        "NON-dedicated unit. Record how this unit was actually cleaned, or set "
                        "clean transport to 'Dedicated organic vehicle'."
                    )
                }
            )

        codes = self.transport_inspected_free_of if isinstance(self.transport_inspected_free_of, list) else []
        needs_notes = self.transport_cleaning_method == "other" or "other" in codes
        if needs_notes and not (self.transport_notes or "").strip():
            raise ValidationError(
                {
                    "transport_notes": (
                        "'Other' was selected for the cleaning method or the pre-load "
                        "inspection, and both print as 'see notes' in the certifier packet. "
                        "Describe what it was, or choose a listed option."
                    )
                }
            )

    def __str__(self):
        return f"{self.sale_date} {self.buyer_name} {self.quantity} {self.quantity_unit}"


class LabelImage(models.Model):
    """
    A container-label artifact (retail / nonretail / unpackaged) for a production,
    surfaced in the audit export's Container Labeling block (CCOF G7.0 / NOPB34 /
    7 CFR 205.307). Reuses common.GalleryImage for the actual image (S3 +
    thumbnails + external-URL support); this model only adds labeling metadata.
    """

    LABEL_TYPE_CHOICES = [
        ("nonretail", "Nonretail container (shipping/storage)"),
        ("retail", "Retail package"),
        ("unpackaged", "Unpackaged / PLU tag"),
    ]
    CONTAINER_TYPE_CHOICES = [
        ("box", "Box"),
        ("bin", "Bin"),
        ("tote", "Tote"),
        ("bag", "Bag"),
        ("tag", "Tag / PLU"),
    ]

    history = models.ForeignKey("history.History", on_delete=models.CASCADE, related_name="label_images")
    label_type = models.CharField(max_length=20, choices=LABEL_TYPE_CHOICES, default="nonretail")
    container_type = models.CharField(max_length=20, choices=CONTAINER_TYPE_CHOICES, blank=True, null=True)
    gallery_image = models.ForeignKey(
        "common.GalleryImage",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="label_uses",
        help_text="The actual label image (reuses Gallery S3 + thumbnail infra).",
    )
    lot_link_note = models.TextField(
        blank=True,
        null=True,
        help_text="How this label links the container to the lot / traceback ID (SOE 205.307).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label_type", "created_at"]

    def __str__(self):
        return f"{self.get_label_type_display()} label for production {self.history_id}"


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

    # The season this correction belongs to. For an event amendment this is denormalised so
    # the amendment survives its event being deleted and the certifier packet can gather a
    # season's corrections in one query rather than eight; for a header amendment it IS the
    # corrected record.
    history = models.ForeignKey("history.History", on_delete=models.CASCADE, related_name="amendments")

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

    @property
    def targets_the_season_header(self) -> bool:
        """True when this corrects the lot header rather than one event on the season."""
        return self.event_type is None and self.event_id is None

    def __str__(self) -> str:
        if self.targets_the_season_header:
            return f"Amendment: {self.field_name} on season header {self.history_id}"
        return f"Amendment: {self.field_name} on event {self.event_type}/{self.event_id}"


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
        History,
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
