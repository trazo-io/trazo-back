"""Business activities."""

from django.core.exceptions import ValidationError
from django.db import models

from .common_event import CommonEvent


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
