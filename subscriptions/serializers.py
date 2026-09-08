import logging
from decimal import Decimal

from django.utils import timezone

from rest_framework import serializers

from company.models import PAID_PLAN_STATUSES, STARTER_PLAN_SLUG

from .models import AddOn, Invoice, PaymentMethod, Plan, Subscription, SubscriptionAddOn

logger = logging.getLogger(__name__)


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "name", "slug", "description", "price", "interval", "features", "is_active"]


class AddOnSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddOn
        # `interval` is not decoration: the UI printed a bare "$30.00" beside a plan labelled
        # "/Yearly", so nothing on screen distinguished $30 a month from $30 a year. It has to
        # reach the client for the price to mean anything.
        fields = ["id", "name", "slug", "description", "price", "interval", "is_active"]


class SubscriptionAddOnSerializer(serializers.ModelSerializer):
    addon = AddOnSerializer(read_only=True)

    class Meta:
        model = SubscriptionAddOn
        fields = ["id", "addon", "quantity"]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    pending_plan = PlanSerializer(read_only=True)
    addons = SubscriptionAddOnSerializer(many=True, read_only=True)

    # Dynamic calculations instead of cached fields
    used_productions = serializers.SerializerMethodField()
    used_storage_gb = serializers.SerializerMethodField()
    # Storage is one number to the quota and two things to the farmer. A meter that reads
    # "18 of 25 GB" without saying what filled it is unactionable: photos can be pruned,
    # generated documents cannot be deleted at all. Every consumer storage product worth
    # copying (Drive, Dropbox, iCloud) breaks the bar down by category for exactly this
    # reason — the breakdown is what turns a number into a decision.
    storage_breakdown = serializers.SerializerMethodField()
    scan_count = serializers.SerializerMethodField()
    usage_warnings = serializers.SerializerMethodField()
    effective_limits = serializers.SerializerMethodField()
    downgrade_preview = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan",
            "pending_plan",
            "status",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            # Read-only on the wire. The client needs to know a cancellation is pending and
            # when it was asked for; it must never be able to rewrite the churn reason with a
            # PATCH, which would corrupt the only answer we will ever get from that customer.
            # The write path is the `cancel` action, which validates against the model choices.
            "cancellation_reason",
            "cancellation_requested_at",
            "used_productions",
            "used_storage_gb",
            "storage_breakdown",
            "scan_count",
            "trial_end",
            "addons",
            "usage_warnings",
            "effective_limits",
            "downgrade_preview",
        ]
        read_only_fields = ["cancellation_reason", "cancellation_requested_at"]

    def _get_cached_usage(self, obj):
        """Compute all usage metrics once per serialization and cache on the instance."""
        cache_attr = f"_usage_cache_{obj.pk}"
        if hasattr(self, cache_attr):
            return getattr(self, cache_attr)

        productions = self._compute_used_productions(obj)
        storage = self._compute_storage_breakdown(obj)
        scans = self._compute_scan_count(obj)

        try:
            est_count = obj.company.establishment_set.count() if obj.company else 0
        except Exception:
            est_count = 0

        result = {
            "productions": productions,
            # `storage` stays the TOTAL so every existing reader keeps meaning what it
            # meant. It just stopped under-reporting: before the DMS was summed, the
            # October pivot's entire document shelf was invisible to this number.
            "storage": storage["total_gb"],
            "storage_breakdown": storage,
            "scans": scans,
            "establishments": est_count,
        }
        setattr(self, cache_attr, result)
        return result

    def _compute_used_productions(self, obj):
        """The number the METER shows — and it must be the number the GATE enforces.

        🔴 This ran its own query on `start_date__gte`, while `Company.can_create_production`
        counts `created_at` (and documents at length why `start_date` cannot gate billing). So the
        meter and the limit disagreed by construction: a season dated to last December did not
        show here but did count against the cap, and a season with no `start_date` showed nowhere
        while counting. The farmer sees "3 of 5" and is refused at 5, with no way to reconcile it.
        Delegating removes the possibility rather than re-syncing two copies.
        """
        try:
            company = obj.company
            if not company:
                return 0
            return company.productions_created_this_year()
        except Exception:
            return 0

    def _compute_storage_breakdown(self, obj):
        """Media + documents + total, in GB.

        The accounting itself lives in `subscriptions.storage_accounting` — the serializer
        renders it, it does not own it. That split exists because the ENFORCEMENT path
        (`storage_utils.check_storage_quota`) needs the media figure ALONE, and it used to
        get it by reaching into this class for a private method that only ever returned the
        gallery total. See that module for why documents are counted but never blocked.
        """
        from subscriptions.storage_accounting import storage_breakdown

        try:
            return storage_breakdown(obj.company)
        except Exception:
            zero = Decimal("0.00")
            return {
                "media_gb": zero,
                "documents_gb": zero,
                "total_gb": zero,
                "media_bytes": 0,
                "documents_bytes": 0,
                "total_bytes": 0,
            }

    def _compute_scan_count(self, obj):
        try:
            from history.models import HistoryScan

            company = obj.company
            if not company:
                return 0

            if obj.current_period_start:
                period_start = obj.current_period_start
            else:
                now = timezone.now()
                period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            return (
                HistoryScan.objects.counted()
                .filter(
                    history__parcel__establishment__company=company,
                    date__gte=period_start,
                )
                .count()
            )
        except Exception:
            return 0

    def get_used_productions(self, obj):
        return self._get_cached_usage(obj)["productions"]

    def get_used_storage_gb(self, obj):
        return self._get_cached_usage(obj)["storage"]

    def get_storage_breakdown(self, obj):
        breakdown = self._get_cached_usage(obj)["storage_breakdown"]
        # `enforced` is not decoration — it is the contract the UI has to render. Media is
        # refused at the ceiling; documents are counted and let through. A meter that shows
        # both under one bar without saying which one bites teaches the farmer the wrong
        # thing about what happens when the bar fills.
        return {
            "media_gb": float(breakdown["media_gb"]),
            "documents_gb": float(breakdown["documents_gb"]),
            "total_gb": float(breakdown["total_gb"]),
            # Raw bytes so the client can pick a unit per line. A document shelf of 21 real
            # certifier artifacts weighs under a megabyte; "0.00 GB" beside a list of 21
            # files reads as a broken meter, and rounding to GB here would make the honest
            # rendering impossible downstream.
            "media_bytes": int(breakdown["media_bytes"]),
            "documents_bytes": int(breakdown["documents_bytes"]),
            "total_bytes": int(breakdown["total_bytes"]),
            "enforced_category": "media",
        }

    def get_scan_count(self, obj):
        return self._get_cached_usage(obj)["scans"]

    def _starter_plan(self):
        """The free tier, looked up ONCE per serializer instance.

        Two paths need it — the entitlement fallback below and `get_downgrade_preview` — and
        both run per row. On a list endpoint that was one `Plan` query per subscription for a
        row that is identical every time.
        """
        if not hasattr(self, "_starter_plan_cache"):
            self._starter_plan_cache = Plan.objects.filter(slug=STARTER_PLAN_SLUG, is_active=True).first()
        return self._starter_plan_cache

    def _get_effective_limits(self, obj):
        """
        Compute effective limits = ENTITLED plan limits + purchased add-ons.

        ENTITLED, not subscribed (2026-08-22). This read `obj.plan.features` with no regard for
        `obj.status`, so a lapsed Compliance subscription kept reporting `compliance_exports:
        True` long after the backend had stopped honouring it. `ComplianceExportsGuard` reads
        exactly this field to decide whether to render the export buttons, so the farmer was
        shown a working Download Packet button that answered 403 — the render gate and the
        enforcement gate disagreeing about the same fact, which is the whole point of shipping
        the flag to the client in the first place.

        The rule is stated here rather than delegated to `Company.subscription_plan` — which is
        the authority everywhere else — for one reason: `obj.addons` and `obj.plan` are already
        prefetched by the dashboard query, and reaching the same answer via
        `obj.company.subscription` would drop that prefetch and cost a round trip per row on a
        page that renders one per company. Both paths key off the SAME constant,
        `company.models.PAID_PLAN_STATUSES`, so they cannot disagree about which statuses are
        paid; what is duplicated is the lookup, not the policy.
        """
        cache_attr = f"_effective_limits_cache_{obj.pk}"
        if hasattr(self, cache_attr):
            return getattr(self, cache_attr)

        if obj.status in PAID_PLAN_STATUSES:
            entitled_plan = obj.plan
        else:
            entitled_plan = self._starter_plan()
        features = entitled_plan.features if entitled_plan else {}

        def base(key, default=0):
            return features.get(key, default)

        def addon_qty(slug):
            # Zero once the subscription stops being paid for — an Extra Farm that Stripe no
            # longer charges for must not keep showing as headroom. Same rule as the enforcement
            # side in `Company._addon_quantity`, but asked of `obj.status` directly rather than
            # through the company: `obj.addons` is prefetched by the dashboard query and going
            # back via `obj.company.subscription` would be a fresh round trip per row.
            if obj.status not in PAID_PLAN_STATUSES:
                return 0
            try:
                # .all() + Python filter to leverage prefetch_related
                # (.filter() would bypass the prefetch and hit the DB)
                return sum(a.quantity for a in obj.addons.all() if a.addon and a.addon.slug == slug)
            except Exception:
                return 0

        def add_if_not_unlimited(base_val, extra):
            if base_val == -1:
                return -1
            return max(0, base_val) + extra

        result = {
            "max_establishments": add_if_not_unlimited(
                base("max_establishments", 0),
                addon_qty("extra-establishment"),
            ),
            "max_parcels_per_establishment": add_if_not_unlimited(
                base("max_parcels_per_establishment", 0),
                addon_qty("extra-parcel"),
            ),
            "max_productions_per_year": add_if_not_unlimited(
                base("max_productions_per_year", 0),
                addon_qty("extra-production") * 10,
            ),
            "storage_limit_gb": add_if_not_unlimited(
                base("storage_limit_gb", 0),
                addon_qty("extra-storage"),
            ),
            "support_response_time": base("support_response_time", 48),
            "priority_support": base("priority_support", False),
            "voice_recording": base("voice_recording", False),
            "ai_event_templates": base("ai_event_templates", True),
            # What the app needs to know BEFORE offering an export button. Without it the only
            # way a farmer learns their plan cannot produce the packet is by clicking Download
            # and receiving a 403 — the gate has to be visible ahead of the click, not just
            # enforced behind it. Default False matches `Company.has_feature`, so a plan that
            # predates the key reads the same here as it does at the gate.
            "compliance_exports": base("compliance_exports", False),
        }
        setattr(self, cache_attr, result)
        return result

    def get_effective_limits(self, obj):
        if not obj.plan:
            return {}
        return self._get_effective_limits(obj)

    def get_downgrade_preview(self, obj):
        """What this company would be OVER if the paid plan ended today.

        A downgrade never deletes anything: existing farms, parcels, productions and photos all
        survive `land_on_free_tier`. What changes is the CEILING, and a farm that is already
        above the new one finds additions refused the moment the subscription ends — a farm on
        Operation with five farms and 42 GB of photos lands on Starter's one farm and 10 GB and
        cannot upload another photo, with nothing on screen having warned them.

        That gap was not merely unkind, it made the cancel screen inaccurate: its "what you keep"
        panel lists "10 GB of photo storage", which reads as a promise to somebody currently
        using four times that. Misstating the consequences of cancelling is exactly what FTC
        §5 / ROSCA scrutiny of negative-option flows is about, and it is also just wrong.

        Computed from `_get_cached_usage`, which the serializer already builds for the meters —
        so this costs no extra query for the two limits that can actually bite today. The two
        that cannot (parcels, productions: Starter is unlimited on both since migration 0014) are
        checked generically off the plan's own features and skipped while the limit is -1, so a
        future tier that DOES bound them is covered without anyone remembering to come back here.

        `None` when there is nothing to say: no plan, already on a free plan, or nothing over.
        """
        plan = obj.plan
        if plan is None or plan.price == 0 or plan.slug == STARTER_PLAN_SLUG:
            return None

        target = self._starter_plan()
        if target is None:
            return None

        limits = target.features or {}
        usage = self._get_cached_usage(obj)
        exceeds = []

        def check(metric, limit_key, used):
            limit = limits.get(limit_key, -1)
            # -1 is unlimited; a missing key is treated the same rather than as zero, because
            # reading an absent key as "0 allowed" here would warn every customer that
            # everything they own is over the limit.
            if limit is None or limit < 0:
                return
            if used > limit:
                exceeds.append({"metric": metric, "used": used, "limit": limit})

        check("establishments", "max_establishments", usage["establishments"])

        # MEDIA, not the total: photos are the hard-limited category, so photo usage is what
        # actually gets refused. Scoring the total would warn about a document shelf that is
        # counted but never blocked. Mirrors `storage_utils.check_storage_quota`.
        check("media_storage_gb", "storage_limit_gb", float(usage["storage_breakdown"]["media_gb"]))

        check("productions", "max_productions_per_year", usage["productions"])

        # Per-establishment, so this needs its own query — only run when the target plan
        # actually bounds it. Starter does not, so today this costs nothing.
        parcel_limit = limits.get("max_parcels_per_establishment", -1)
        if parcel_limit is not None and parcel_limit >= 0:
            try:
                from django.db.models import Count, Max

                busiest = obj.company.establishment_set.annotate(n=Count("parcels")).aggregate(m=Max("n"))["m"] or 0
                check("parcels_per_farm", "max_parcels_per_establishment", busiest)
            except Exception:
                logger.exception("Could not compute parcel downgrade preview for company %s", obj.company_id)

        if not exceeds:
            return None

        return {
            "target_plan_slug": target.slug,
            "target_plan_name": target.name,
            "exceeds": exceeds,
        }

    def get_usage_warnings(self, obj):
        """
        Return warnings for resources approaching plan limits.
        Uses effective limits (base + add-ons) and cached usage values.
        """
        warnings = []
        if not obj.plan or not obj.plan.features:
            return warnings

        limits = self._get_effective_limits(obj)
        usage = self._get_cached_usage(obj)

        def check_limit(metric_name, used, limit, label):
            if limit == -1:  # unlimited
                return
            if limit <= 0:
                return
            pct = (used / limit) * 100
            if pct >= 95:
                warnings.append(
                    {
                        "metric": metric_name,
                        "label": label,
                        "used": used,
                        "limit": limit,
                        "percentage": round(pct, 1),
                        "level": "critical",
                    }
                )
            elif pct >= 80:
                warnings.append(
                    {
                        "metric": metric_name,
                        "label": label,
                        "used": used,
                        "limit": limit,
                        "percentage": round(pct, 1),
                        "level": "warning",
                    }
                )

        check_limit(
            "productions",
            usage["productions"],
            limits.get("max_productions_per_year", 0),
            "Productions this year",
        )
        # Scored on the ENFORCED half, not the total.
        #
        # A warning says "act now or something stops working". Only media can stop working:
        # photo uploads are refused at the ceiling, documents never are. Scoring the total
        # would fire "95% used — upgrade to avoid service interruption" at a farm whose
        # document shelf happens to be large, about an interruption that cannot happen and
        # in response to files they are not allowed to delete. The meter still SHOWS the
        # total (`storage_breakdown`); the alarm is wired to the half that can ring.
        check_limit(
            "storage",
            float(usage["storage_breakdown"]["media_gb"]),
            limits.get("storage_limit_gb", 0),
            "Photo storage (GB)",
        )
        # UI naming rule: an Establishment is a "Farm" everywhere a farmer reads it.
        #
        # Skipped entirely for pilots: a pilot is capped at one farm BY AGREEMENT, so
        # "100% used — upgrade to avoid service interruption" would sit permanently on
        # every pilot's subscription page, warning about a ceiling they chose. Storage
        # stays warned for everyone, pilots included: photo uploads ARE refused at the
        # ceiling, so the farmer has to see it coming.
        if not obj.plan.features.get("is_pilot"):
            check_limit(
                "establishments",
                usage["establishments"],
                limits.get("max_establishments", 0),
                "Farms",
            )

        return warnings


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id", "card_brand", "last_4", "exp_month", "exp_year", "is_default"]


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "number", "amount", "status", "invoice_date", "due_date", "invoice_pdf", "created_at"]
