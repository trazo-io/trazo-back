import uuid

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from backend.storage import private_records_storage

# The slug of the free-forever tier. Every company that is not currently entitled to a paid
# plan falls back to this one — see `Company.subscription_plan`.
STARTER_PLAN_SLUG = "starter"

# Subscription statuses in which the company is entitled to the plan it SUBSCRIBED to.
#
# `past_due` is IN this list DELIBERATELY (2026-08-22). Stripe's Smart Retries run for three to
# four weeks after a card fails, and for that whole window the customer is still contracted and
# still counted in MRR (`subscriptions.models.MRR_STATUSES` says so). Dropping their plan on the
# FIRST failed charge turned the largest source of involuntary churn in SaaS into a hard outage:
# the farm could not log a harvest, upload a photo or add a parcel, and the message it got was
# "Your subscription plan does not allow creating more parcels" — false, unactionable, and
# impossible for the farmer to connect to an expired card. An expired card is a billing problem.
# It is answered with a banner and an email, never by locking a farm out of its own records in
# the middle of a season.
#
# `unpaid` is NOT here: it means Stripe stopped trying to collect. Neither are `canceled` and
# `incomplete`. None of those lock a company out either — they fall back to Starter below.
PAID_PLAN_STATUSES = ("active", "trialing", "past_due")


class Company(models.Model):
    name = models.CharField(max_length=150, help_text="Company name")
    tradename = models.CharField(max_length=150, blank=True, null=True, help_text="Trade name or DBA")
    address = models.CharField(max_length=200, blank=True, default="", help_text="Street address")
    city = models.CharField(max_length=100, blank=True, default="", help_text="City name")
    state = models.CharField(max_length=100, blank=True, default="", help_text="State or province")
    country = models.CharField(max_length=100, blank=True, null=True, help_text="Country name")
    fiscal_id = models.CharField(max_length=50, help_text="Tax ID, RUT, or EIN", blank=True, null=True)
    logo = models.ImageField(upload_to="company_logos", blank=True)
    description = models.TextField(blank=True, null=True)
    invitation_code = models.CharField(max_length=50, blank=True, null=True, help_text="Invitation code for new users")
    contact_email = models.EmailField(max_length=254, blank=True, null=True, help_text="Primary contact email")
    contact_phone = models.CharField(max_length=20, blank=True, null=True, help_text="Primary contact phone")
    website = models.URLField(max_length=200, blank=True, null=True)
    facebook = models.URLField(max_length=200, blank=True, null=True)
    instagram = models.URLField(max_length=200, blank=True, null=True)
    certifications = models.TextField(blank=True, null=True)

    # Additional business fields
    zip_code = models.CharField(max_length=20, blank=True, null=True, help_text="Postal/ZIP code")
    employee_count = models.PositiveIntegerField(blank=True, null=True, help_text="Number of employees")
    industry = models.CharField(max_length=100, blank=True, null=True, help_text="Primary agricultural industry")
    is_active = models.BooleanField(default=True, help_text="Whether the company is active")

    # New agricultural compliance fields
    legal_structure = models.CharField(max_length=50, blank=True, null=True, help_text="Business legal structure")
    primary_commodities = models.CharField(
        max_length=100, blank=True, null=True, help_text="Main agricultural commodities"
    )
    sustainability_commitment = models.CharField(
        max_length=100, blank=True, null=True, help_text="Sustainability approach"
    )

    # Sustainability and carbon tracking metadata
    sustainability_metadata = models.JSONField(
        blank=True,
        null=True,
        help_text="JSON data containing crop selection, sustainability goals, and carbon benchmarks",
    )

    # Blockchain subscription status
    blockchain_subscription_status = models.BooleanField(
        default=False, help_text="Whether company has active blockchain verification subscription"
    )

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("company-detail", kwargs={"id": self.id})

    def save(self, *args, **kwargs):
        # Generate invitation code if not provided
        if not self.invitation_code:
            self.invitation_code = self.generate_invitation_code()
        super().save(*args, **kwargs)

    def generate_invitation_code(self):
        """Generate a unique company invitation code"""
        import secrets
        import string

        while True:
            # Generate a readable code (6 characters, uppercase + digits)
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            if not Company.objects.filter(invitation_code=code).exists():
                return code

    # Subscription-related methods
    @property
    def subscription_plan(self):
        """The plan whose features this company may use RIGHT NOW.

        Not the same question as "what is this company subscribed to" — `self.subscription.plan`
        answers that. This answers "what is it entitled to", which differs the moment a payment
        fails or a subscription ends.

        A COMPANY WITH A SUBSCRIPTION ROW ALWAYS RESOLVES TO A PLAN (2026-08-22).

        This used to return None for every status except active/trialing, and None cascades:
        `has_feature` answers False, `get_feature_limit` falls back to 0, `can_create_parcel` /
        `can_create_establishment` / `can_create_production` all answer False, photo and document
        uploads are refused with NO_SUBSCRIPTION, voice input switches off and all seven
        compliance-export doors 403. In other words a farmer who paid $249 and then chose not to
        renew was left strictly WORSE off than a stranger signing up that morning, who lands on
        Starter — free forever, unlimited parcels and productions, 10 GB. That contradicted the
        one promise the October plan repeats in four places, and it aimed the damage squarely at
        the COG Pro refugees whose entire reason for trusting Trazo is "Starter is free
        permanently, not a trial".

        So the end of a paid subscription is a DOWNGRADE, never a deletion:

          * paid statuses (`PAID_PLAN_STATUSES`)  -> the subscribed plan
          * anything else, with a subscription    -> Starter
          * no subscription row at all            -> None

        The last case is a data anomaly, not a customer, and it still fails closed.

        `subscriptions.views.handle_customer_subscription_deleted` ALSO re-points the row at
        Starter, so this fallback is not the primary mechanism — it is the safety net. The two
        answer different failure modes: the webhook makes the DATA right (the billing page reads
        "Starter", the event log books the churn, MRR drops), while this makes the SYSTEM safe
        when a webhook is missed, delayed, replayed out of order, or carries a status nobody
        anticipated. A status this code has never heard of now degrades to the free tier instead
        of locking a farm out.
        """
        try:
            subscription = self.subscription
        except Exception:
            # No subscription row (or no reverse accessor at all). Fails closed, deliberately:
            # every real company gets one at creation (`company.views.CompanyViewSet.create`),
            # so its absence is corruption rather than a tier.
            return None

        if subscription is None:
            return None

        if subscription.status in PAID_PLAN_STATUSES:
            return subscription.plan

        return self._free_fallback_plan()

    @staticmethod
    def _free_fallback_plan():
        """The free-forever plan a lapsed subscription falls back to.

        None when Starter is not seeded — `create_plans` is the ONLY thing that creates plan
        rows, so a database that has only been migrated has no Starter to fall back to. That is
        a broken install, and it fails closed rather than inventing an allowance.
        """
        from subscriptions.models import Plan

        return Plan.objects.filter(slug=STARTER_PLAN_SLUG, is_active=True).first()

    def _addon_quantity(self, slug):
        """Total quantity of a purchased add-on — ZERO unless the subscription is being paid for.

        Add-on rows outlive the subscription that bought them: cancelling in Stripe removes the
        recurring charge but leaves `SubscriptionAddOn` in place. Counting them after the plan
        has fallen back to Starter would hand a farm that once bought three Extra Farms a
        permanent free allowance of four (1 + 3) — the exact cap Extra Farm at $149/yr and the
        Operation tier exist to sell. The entitlement has to end when the payment does.
        """
        if not hasattr(self, "subscription"):
            return 0
        subscription = self.subscription
        if subscription.status not in PAID_PLAN_STATUSES:
            return 0
        # Iterating rather than .filter() so a prefetched `addons` is not thrown away.
        return sum(a.quantity for a in subscription.addons.all() if a.addon and a.addon.slug == slug)

    def get_feature_limit(self, feature_name, default=0):
        """Get limit for a specific feature from subscription plan"""
        if not self.subscription_plan:
            return default

        features = self.subscription_plan.features
        return features.get(feature_name, default)

    def has_feature(self, feature_name):
        """Check if company has access to a specific feature"""
        if not self.subscription_plan:
            return False

        features = self.subscription_plan.features
        return features.get(feature_name, False)

    def can_create_establishment(self):
        """Check if company can create more establishments"""
        max_allowed = self.get_feature_limit("max_establishments", 0)
        if max_allowed == -1:
            return True
        current_count = self.establishment_set.count()

        # Add purchased add-ons. `_addon_quantity` returns 0 once the subscription stops being
        # paid for, so a lapsed farm keeps every farm it already has but buys no new headroom.
        max_allowed += self._addon_quantity("extra-establishment")

        return current_count < max_allowed

    def can_create_parcel(self, establishment=None):
        """Check if company can create more parcels within their plan limit."""
        plan = self.subscription_plan
        if not plan:
            return False

        features = plan.features
        max_per_establishment = features.get("max_parcels_per_establishment", 0)

        # Unlimited parcels (-1)
        if max_per_establishment == -1:
            return True

        if max_per_establishment > 0 and establishment:
            current_count = establishment.parcels.count()
            max_allowed = max_per_establishment

            # Add purchased add-ons (zero once the subscription lapses — see `_addon_quantity`).
            max_allowed += self._addon_quantity("extra-parcel")

            return current_count < max_allowed

        return False

    def productions_created_this_year(self):
        """Productions this company created in the current calendar year.

        ONE authority, because there were two. The quota gate below counted `created_at`, for the
        reasons below; the usage METER on the subscription payload counted `start_date__gte`, the
        very field those reasons rule out. A farmer therefore read "3 of 5 used" on the billing
        page and was refused at 5 — and a production with a NULL `start_date` was invisible to the
        meter while the gate counted it. Two numbers under one label, and the one on screen was
        the wrong one.

        Counted by `created_at`, NOT by `start_date`. `start_date` is when the farmer says the
        season began: user-supplied and editable, so a limit keyed on it was defeated simply by
        dating a production to 31 December, and a NULL `start_date` escaped `start_date__gte`
        entirely. Neither is acceptable for something that gates billing. `created_at` is
        `auto_now_add` and is exposed for editing nowhere.

        The WINDOW is the calendar year. An earlier version used the subscription's
        `current_period_start`, which is wrong: that is the BILLING period, so on a monthly plan it
        is ~30 days and a limit named `max_productions_per_year` would reset every month, turning
        3/year into 36/year.

        Known limitation, deliberately not addressed: a customer who subscribes in December gets a
        full allowance that resets a few weeks later. That is generous rather than harmful, and
        fixing it properly needs a subscription-anniversary concept, not a different date field.
        """
        from history.models import History

        start_of_year = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return History.objects.filter(
            parcel__establishment__company=self,
            created_at__gte=start_of_year,
        ).count()

    def can_create_production(self):
        """Check if company can create more productions this year."""
        if not self.subscription_plan:
            return False

        # Unlimited productions (-1)
        max_productions = self.get_feature_limit("max_productions_per_year", 0)
        if max_productions == -1:
            return True

        productions_this_year = self.productions_created_this_year()

        # Add purchased add-ons (zero once the subscription lapses — see `_addon_quantity`).
        max_productions += self._addon_quantity("extra-production") * 10

        return productions_this_year < max_productions

    def get_storage_limit_gb(self):
        """Get storage limit in GB"""
        if not self.subscription_plan:
            return 0

        base_limit = self.get_feature_limit("storage_limit_gb", 10)
        if base_limit == -1:
            return -1  # Unlimited

        # Add purchased storage add-ons
        if hasattr(self, "subscription"):
            extra_storage = sum(
                addon.quantity for addon in self.subscription.addons.filter(addon__slug="extra-storage")
            )
            base_limit += extra_storage

        return base_limit


class Establishment(models.Model):
    #: True when this farm's records are FABRICATED — a seeded showcase, a rehearsal farm, a
    #: demo handed to a prospect. Default False, and the default is the load-bearing part: a
    #: certifier packet is a 7 CFR 205.103 compliance record, and stamping a REAL operation's
    #: packet "SPECIMEN" would invite a certifier to reject it. So the flag is opt-IN, and a
    #: farm that never heard of it exports exactly as before.
    #:
    #: Why it exists (2026-08-21): the audit packet carried NO marking of any kind, so a PDF
    #: generated from an invented farm — Calapooia Bend, the pilot-rehearsal operation — was
    #: byte-for-byte the same KIND of document as a real grower's organic records: same cover,
    #: same CFR citations, same handler certificates, same § 205.103 audit trail. Those get
    #: forwarded, excerpted and filed. An unmarked synthetic one is a document that can be
    #: mistaken for a real operation's legal records, and we intend to hand these to
    #: inspectors and certifier reviewers.
    is_demo = models.BooleanField(
        default=False,
        help_text=(
            "Records for this farm are fabricated (seeded/demo/rehearsal). Marks every page of "
            "exported certifier packets as a specimen. Never set this on a real operation."
        ),
    )
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    name = models.CharField(max_length=150, help_text="Establishment name")
    address = models.CharField(max_length=200, blank=True, default="", help_text="Street address")
    city = models.CharField(max_length=100, blank=True, null=True, help_text="City name")
    zone = models.CharField(max_length=100, blank=True, null=True, help_text="Zone or region")
    state = models.CharField(max_length=100, blank=True, default="", help_text="State or province")
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True, help_text="Country name")
    type = models.CharField(max_length=100, blank=True, null=True, help_text="Establishment type")
    latitude = models.FloatField(blank=True, null=True, help_text="GPS latitude")
    longitude = models.FloatField(blank=True, null=True, help_text="GPS longitude")
    contact_person = models.CharField(max_length=100, blank=True, null=True, help_text="Contact person name")
    contact_phone = models.CharField(max_length=20, blank=True, null=True, help_text="Contact phone number")
    contact_email = models.EmailField(max_length=254, blank=True, null=True)
    certifications = models.TextField(blank=True, null=True)
    about = models.TextField(blank=True, null=True)
    main_activities = models.TextField(blank=True, null=True)
    location_highlights = models.TextField(blank=True, null=True)
    custom_message = models.TextField(blank=True, null=True)

    # New valuable fields
    email = models.EmailField(max_length=254, blank=True, null=True, help_text="Main establishment email")
    phone = models.CharField(max_length=20, blank=True, null=True, help_text="Main establishment phone")
    zip_code = models.CharField(max_length=20, blank=True, null=True, help_text="Postal/ZIP code")
    # CA DPR Operator Identification Number / restricted-materials permit number, issued by the
    # County Agricultural Commissioner to the OPERATOR (3 CCR 6622; valid up to 36 months). It is
    # PUR box 3 on every line the farm files, so it belongs on the farm, not on each spray: the
    # PUR export reads the event's own value first and falls back to this. California only.
    ca_operator_id = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text="CA DPR Operator ID / restricted-materials permit number (PUR box 3). California farms only.",
    )
    # The identifier the certifying agent gives this operation (Oregon Tilth's "Client ID", CCOF's
    # "Client Code"). Not the certificate number, which the plan's activation records. Kept with
    # the agent that issued it, so an operation that moves agent never shows one agent's ID on
    # another's form. Owner-only: never on a public serializer.
    certifier_client_id = models.CharField(max_length=64, blank=True, default="")
    certifier_client_id_agent = models.CharField(
        max_length=32, blank=True, default="", help_text="certifying_agents slug of the agent that issued it"
    )
    # The renewal date the certifying agent assigned this operation, "MM-DD", for an agent that assigns
    # one of several (Oregon Tilth: January 1 or April 1, whatever the certificate's issue date). It
    # decides which 12 months of sales the agent asks for. Kept with the agent that assigned it, like
    # the Client ID. Never inferred: blank until the operator records it from the agent's letters.
    certifier_renewal_date = models.CharField(max_length=5, blank=True, default="")
    certifier_renewal_date_agent = models.CharField(
        max_length=32, blank=True, default="", help_text="certifying_agents slug of the agent that assigned it"
    )
    is_active = models.BooleanField(default=True, help_text="Whether the establishment is active")
    crops_grown = models.JSONField(default=list, blank=True, help_text="List of crops grown at this establishment")
    sustainability_practices = models.JSONField(default=list, blank=True, help_text="List of sustainability practices")
    employee_count = models.PositiveIntegerField(blank=True, null=True, help_text="Number of employees")
    total_acreage = models.FloatField(blank=True, null=True, help_text="Total land area in acres")
    year_established = models.PositiveIntegerField(
        blank=True, null=True, help_text="Year the establishment was founded"
    )
    establishment_type = models.CharField(
        max_length=50, blank=True, null=True, help_text="Type of agricultural operation"
    )
    farming_method = models.CharField(max_length=50, blank=True, null=True, help_text="Primary farming approach")

    # Operational agricultural fields
    water_sources = models.JSONField(
        default=list, blank=True, help_text="Primary water sources (well, surface water, irrigation district, etc.)"
    )
    climate_zone = models.CharField(
        max_length=50, blank=True, null=True, help_text="Climate zone or growing region classification"
    )
    soil_types = models.JSONField(default=list, blank=True, help_text="Primary soil types present on the establishment")
    conservation_practices = models.JSONField(
        default=list, blank=True, help_text="Conservation practices implemented (cover crops, buffer strips, etc.)"
    )
    irrigation_methods = models.JSONField(
        default=list, blank=True, help_text="Irrigation methods used (drip, sprinkler, flood, etc.)"
    )

    # SOE Compliance: Organic Fraud Prevention Plan (7 CFR 205.201(a)(3))
    # Required since March 19, 2024 for all certified organic operations
    fraud_prevention_plan_uploaded = models.BooleanField(
        default=False,
        help_text="Whether an Organic Fraud Prevention Plan has been uploaded",
    )
    fraud_prevention_plan_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the fraud prevention plan was last updated",
    )
    fraud_prevention_plan_document = models.FileField(
        upload_to="ofpp/",
        storage=private_records_storage,
        blank=True,
        null=True,
        help_text="Uploaded Organic Fraud Prevention Plan document",
    )
    ofpp_responsible_person = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Person responsible for fraud prevention oversight",
    )

    # One OFPP truth (2026-08-10). Three surfaces used to answer "is a fraud
    # prevention plan on file?" differently: the readiness service accepted OSP
    # module G2.0, the audit-export gate accepted only the upload flag, and the
    # frontend checklist only knew the upload flag. Everything now asks HERE.
    _OFPP_SUSPICIOUS_FILENAME_PATTERNS = ("factura", "invoice", "receipt", "comprobante", "recibo")

    @property
    def ofpp_filename_suspicious(self) -> bool:
        """Uploaded OFPP filename matches the misfiled-invoice heuristic —
        the audit export refuses such a file, so surfaces must not show it
        as a clean 'Plan Uploaded'."""
        doc = self.fraud_prevention_plan_document
        if not (doc and doc.name):
            return False
        import os

        lowered = os.path.basename(doc.name).lower()
        return any(p in lowered for p in self._OFPP_SUSPICIOUS_FILENAME_PATTERNS)

    def ofpp_authored_via_module(self) -> bool:
        """True when OSP module G2.0 (Monitoring & Organic Fraud Prevention)
        is completed on any of this establishment's plans — its questions ARE
        the written plan."""
        from certifications.models import OrganicSystemPlan

        for plan in OrganicSystemPlan.objects.filter(establishment=self):
            entry = ((plan.module_responses or {}).get("modules") or {}).get("g2_0_fraud_prevention") or {}
            if entry.get("completed_at"):
                return True
        return False

    @property
    def ofpp_on_file(self) -> bool:
        """A valid OFPP exists by EITHER route: a clean upload, or module G2.0."""
        if self.fraud_prevention_plan_uploaded and not self.ofpp_filename_suspicious:
            return True
        return self.ofpp_authored_via_module()

    # NOP Compliance: Split Operation Tracking (7 CFR 205.201(a)(5), 7 CFR 205.272)
    has_split_operation = models.BooleanField(
        default=False,
        help_text=(
            "Whether this establishment operates both organic and conventional production "
            "(7 CFR 205.201(a)(5) — requires commingling prevention documentation)"
        ),
    )
    split_operation_plan = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Description of measures to prevent commingling of organic and conventional products "
            "(labeling, storage separation, equipment cleaning protocols per 7 CFR 205.272)"
        ),
    )

    # Phase 3 consumer-QR privacy: worker full names on the public page are a
    # CCPA exposure and a doxing vector (name + farm geolocation). Default OFF;
    # the public serializer masks performed_by to "Farm team (A.T.)" unless the
    # establishment explicitly opts in (with worker consent collected offline).
    show_full_performer_names = models.BooleanField(
        default=False,
        help_text=(
            "Display workers' full names on the public consumer page. Requires the "
            "workers' consent — when off, names are masked to initials (e.g. 'Farm team (A.T.)')"
        ),
    )

    class Meta:
        verbose_name = _("Establishment")
        verbose_name_plural = _("Establishments")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("establishment-detail", kwargs={"id": self.id})

    def get_location(self) -> str:
        # Recordkeeping review F-25 (2026-10-07): this printed "Tangent, -" on the production
        # page for every operation with no country stored. Only recorded parts, no placeholder.
        from common.location import joined_parts

        return joined_parts(self, ("city", "state", "country")) or ""
