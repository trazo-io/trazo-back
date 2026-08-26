from django.conf import settings
from django.core.management.base import BaseCommand

import stripe

from subscriptions.models import AddOn, Plan

stripe.api_key = settings.STRIPE_SECRET_KEY


# The add-on catalogue, at module scope so it can be READ without running the command.
#
# It lived inside `create_addons` as a local. That made it untestable: migrations never
# INSERT add-on rows (0006/0010/0013/0014/0016 only update existing ones), so a freshly
# migrated database has an empty AddOn table and every guard written against the table
# passed by iterating nothing. The definitions here are what a fresh environment actually
# gets, so they are what the guards have to read.
#
# `interval` is in the STRIPE shape ("month"/"year") because that is the value that must be
# exact for billing; `_db_interval` maps it to the model shape.
ADDON_DEFINITIONS = [
    {
        # DISPLAY name only — the slug is an identifier referenced elsewhere and must
        # not change. "Establishment" is the model name; a farmer buys a FARM
        # (UI naming rule: Establishment = Farm everywhere a farmer reads it).
        "name": "Extra Farm",
        "slug": "extra-establishment",
        "description": "Add an additional farm to your Compliance plan, billed yearly alongside it",
        # $149/YEAR, not $30/month.
        #
        # 2026-08-14: at $30/mo this add-on cost $360/yr — 45% MORE than the $249/yr plan
        # it extends. Farm #2 was dearer than farm #1, so the marginal price went UP with
        # volume, and the operator it penalised hardest was the multi-farm grower, i.e.
        # the largest and best-funded customer in the pipeline. It also mixed billing
        # periods on a single invoice: an annual plan with a monthly rider.
        #
        # $149 is 60% of base — enough to reflect that a second farm is a second
        # certificate, a second OSP and a second renewal, while keeping the marginal
        # price below the first unit, which is the direction it has to run.
        "price": 149.00,
        "interval": "year",
    },
    {
        "name": "Extra Production",
        "slug": "extra-production",
        "description": "Add 10 extra productions per year beyond your plan limit with full transparency tracking and QR codes",
        "price": 20.00,
        "interval": "month",
        # SUPERSEDED 2026-08-07 by migration 0010. Compliance grants unlimited
        # productions, so this sells capacity the plan already includes. Seeded inactive
        # so a reseed cannot resurrect the offer — the flag has to live HERE, not only in
        # the migration, because create_plans is what runs on a fresh environment.
        "is_active": False,
    },
    {
        "name": "Extra Parcel",
        "slug": "extra-parcel",
        "description": "Add an additional parcel per establishment",
        "price": 25.00,
        "interval": "month",
        # SUPERSEDED 2026-08-07 by migration 0010. BOTH live tiers now grant unlimited
        # parcels. Charging per parcel also priced farm geometry rather than value: a
        # parcel is a block, so a 20-block orchard paid 5x a 4-block one of the same
        # acreage for identical output.
        "is_active": False,
    },
    {
        # DISPLAY name only — the slug is an identifier referenced elsewhere and must
        # not change. Renamed from "Blockchain Verification" (2026-08-03): compliance.md
        # lists "blockchain-verified" as UNSAFE. Blockchain shows a record was not
        # altered after submission; it attests nothing about the farming itself, and
        # the rest of the product already says "Blockchain Recording"
        # (`app.blockchainAddon`).
        "name": "Blockchain Recording",
        "slug": "blockchain-verification",
        "description": "Write finished productions to the Polygon blockchain so the record cannot be altered afterwards",
        "price": 15.00,
        "interval": "month",
        # WITHDRAWN 2026-08-03, not deleted. The consumer-facing blockchain surface was
        # removed: the only claim the chain honestly supports ("unchanged since
        # sealing") does not answer what a shopper or a wholesale buyer asks, it was
        # not among the real competitive gaps vs COG Pro / Quick Organics, and it was
        # the single largest source of claim-safety defects in the codebase.
        # Seeded inactive so it stays out of pricing until a real buyer asks for it;
        # the row is kept so existing references and Stripe IDs do not dangle.
        "is_active": False,
    },
]


class Command(BaseCommand):
    help = "Creates initial subscription plans and add-ons in Stripe and syncs with the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force recreation of existing plans and add-ons",
        )
        parser.add_argument(
            "--environment",
            type=str,
            default="development",
            help="Environment (development, staging, production)",
        )

    def handle(self, *args, **options):
        self.force = options["force"]
        self.environment = options["environment"]

        # No Stripe key -> seed local rows only, never call Stripe.
        #
        # Trazo has no US entity yet and Stripe is disabled in production, so `STRIPE_SECRET_KEY`
        # is empty. Without this guard every paid plan would attempt `stripe.Product.create` and
        # fail inside the broad `except` below, leaving the run "successful" with plans that were
        # never written. Feature gating (parcel/production limits) lives in `Plan.features` and
        # works with no Stripe at all — billing is the only thing that needs it.
        self.stripe_enabled = bool(getattr(settings, "STRIPE_SECRET_KEY", ""))
        if not self.stripe_enabled:
            self.stdout.write(
                self.style.WARNING(
                    "STRIPE_SECRET_KEY is not set — seeding local plan rows only. Prices are "
                    "published for display and feature gating; no Stripe products or prices are "
                    "created and `stripe_price_id` stays NULL."
                )
            )

        self.stdout.write(self.style.SUCCESS(f"Setting up plans and add-ons for {self.environment} environment..."))

        # Create plans
        self.create_plans()
        # Create add-ons
        self.create_addons()
        # Strip retired feature keys from EVERY row, including legacy variant slugs this
        # command no longer writes (standard, compliance-yearly, ...). Deleting a key from
        # the dicts above only reaches the slugs update_or_create touches; without this
        # sweep the retired ladder keeps serving the key forever.
        self.strip_retired_feature_keys()

        self.stdout.write(self.style.SUCCESS("Setup completed successfully!"))

    #: Feature keys that no longer exist anywhere in the product. `monthly_scan_limit`
    #: (deleted 2026-08-25): never enforced — the tracking middleware only logged, the
    #: quota method had no callers — and the buyer page is deliberately unlimited on
    #: every plan, because it is the demonstration that sells the paid tier.
    RETIRED_FEATURE_KEYS = ("monthly_scan_limit",)

    def strip_retired_feature_keys(self):
        from subscriptions.models import Plan

        for plan in Plan.objects.all():
            features = plan.features or {}
            removed = [k for k in self.RETIRED_FEATURE_KEYS if k in features]
            if removed:
                for k in removed:
                    features.pop(k)
                plan.features = features
                plan.save(update_fields=["features"])
                self.stdout.write(f"  Stripped retired feature keys {removed} from plan '{plan.slug}'")

    def create_plans(self):
        # Starter — FREE FOREVER, no card, no clock.
        #
        # 2026-08-13: the trial keys are gone. Starter was created as a 14-day trial that
        # `expire_trials` canceled, contradicting the October plan in four places ("Actually
        # free. Starter free forever, pilot free, no card") and the COG Pro migration page, whose
        # anti-lock-in answer is "Starter is free permanently, not a trial" — the page aimed at
        # refugees from a product that shuts down 2026-12-31. A COG Pro migrant read that promise,
        # signed up, and was cut off on day 14.
        #
        # The tier is bounded by LIMITS, not time. `trial_*` keys are also what the pricing page
        # renders its "14-day free trial included" line from, so removing them removes the claim
        # at the same time.
        # Starter is bounded by what it can PRODUCE, not by how much it can log.
        #
        # 2026-08-14 (pricing research): the previous limiter was `max_productions_per_year: 1`.
        # A production is a crop cycle, and the ICP — a mid-size CA wholesale orchard — runs ~20
        # a year. So Starter let a farm model all 20 blocks (parcels are unlimited, deliberately)
        # and then 403'd at production #2: it blocked at the exact moment the farm began
        # generating the records the product exists to produce. Nobody can evaluate a
        # RECORDKEEPING tool on one crop cycle; a renewal needs a season.
        #
        # It also lost the free-tier comparison outright. Quick Organics gives 12 months of the
        # FULL product (live and uncapped on their pricing page as of 2026-08-14), farmOS is free,
        # and the CCOF Foundation writes California growers' OSPs for free. Against that, a
        # one-cycle cap is not a free tier, it is a demo.
        #
        # The wall moved to the OUTPUT. Log everything, all season, free. The certifier packet,
        # the audit export, the CA PUR export and the certifier review link are what Compliance
        # buys — see `compliance_exports` and `subscriptions/gating.py`. That puts the upgrade
        # prompt on the renewal deadline (a date the certifier sets, not a timer we invented) at
        # the moment a season of the farm's own records is already in the system.
        starter_features = {
            "max_establishments": 1,
            # Unlimited parcels, deliberately. A Parcel IS a block, so a one-parcel free tier
            # cannot demonstrate anything to a 20-block orchard — it would be structurally
            # incapable of showing value to the exact ICP it exists to attract.
            "max_parcels_per_establishment": -1,
            "max_productions_per_year": -1,
            "establishment_full_description": False,
            # 10 GB, not 2. A season of photo evidence does not fit in 2 GB, and `storage_utils`
            # REFUSES the upload once projected usage passes the limit — so a 2 GB Starter would
            # simply have re-imposed the removed wall as a storage failure mid-season.
            "storage_limit_gb": 10,
            "support_response_time": 72,
            "priority_support": False,
            "dedicated_support": False,
            "is_starter": True,
            # Voice is ON for free. Gating it was backwards: the measured barriers to farm
            # software adoption are lack of time/labour (63-65%) and insufficient training (53%)
            # ahead of price (44% cite up-front cost) — so crippling the fastest gloves-on input
            # path suppresses exactly the logging that creates the records that create the
            # upgrade. The paid tier sells the artifact, not the keyboard.
            "voice_recording": True,
            "ai_event_templates": True,
            # The gate. False here is what makes Starter a free tier rather than a free product.
            "compliance_exports": False,
        }

        # Pilot — hand-provisioned, never self-served, never billed.
        #
        # Exists because no other plan shape can host an October pilot. A pilot is a COMPED
        # Compliance customer: they get the certifier packet, the audit export, the PUR export and
        # the certifier link, which is precisely what Starter does not grant, and precisely what
        # the April conversion verdict has to be measuring.
        #
        # Two properties are load-bearing and must not be "simplified":
        #   price = 0       -> mrr_for() returns 0 even on status="active", so pilots never book
        #                      phantom revenue. Putting a pilot on Enterprise/active instead
        #                      would report $299/mo of MRR that does not exist.
        #   status "active" -> subscription_plan resolves only for active/trialing.
        #
        # (`slug != "starter"` used to be a third: expire_trials filtered plan__slug="starter" and
        # would have canceled a Starter-based pilot on day 14. That filter is gone — Starter is
        # free forever — so the slug no longer carries that meaning.)
        #
        # Compliance — the paid tier, and the only one offered.
        #
        # Priced ANNUALLY at $249 against a category that charges per year: COG Pro $99/$155/$179
        # (dying 2026-12-31), Quick Organics $150. The old $69-299/MONTH ladder was 5-8x the
        # category, and a refugee paying $155/yr was never going to sign for $828.
        #
        # Per-FARM, not per-parcel. A Parcel is a block, so parcel count prices farm geometry
        # rather than value — and "structuring your records properly costs more" is the same
        # perverse incentive the transparency-first pivot rejected for carbon scoring. What a farm
        # buys (certifier packet, PUR export, buyer page, Common OSP § 11) is per-farm: one
        # certificate, one OSP, one renewal.
        compliance_features = {
            "max_establishments": 1,
            "max_parcels_per_establishment": -1,
            "max_productions_per_year": -1,
            "establishment_full_description": True,
            "storage_limit_gb": 25,
            "support_response_time": 24,
            # No trial keys: Starter is the free path. Two 14-day offers on one page read as
            # the same thing twice, and the pricing page renders its trial line from these.
            "priority_support": True,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
            # What the $249 actually buys. Starter logs; Compliance produces the documents a
            # certifier, a county ag commissioner or a wholesale buyer asks for: the OSP renewal
            # packet, the audit export, the CA PUR export, and the tokenized certifier link.
            # Enforced in `subscriptions/gating.py`, not merely displayed.
            "compliance_exports": True,
        }

        # Operation — the ceiling. DERIVED from Compliance, one size up.
        #
        # 2026-08-17: the lineup had exactly ONE paid product, capped at one farm, with nothing
        # above it. The ladder therefore inverted at the top: farms #2 onward cost $149 each, so a
        # six-farm business paid $994 — against $4,250 that Quick Organics charges the same
        # operation, and $3,300 that Croptracker charges before it will talk to you at all.
        # Competitive at the bottom, giving the product away at the top.
        #
        # This is NOT a new value metric, which is what the 2026-08-14 memo was right to refuse
        # without usage data. It is the SAME metric — the operation buys certification paperwork
        # per farm — expressed per OPERATION at the size where counting farms stops making sense.
        #
        # $1,200 is set by two anchors, not by a margin target: it stays under QO's $4,250 top band
        # for the same customer, and it clears the $500–5,000 ACV churn band's floor rather than
        # sitting a fifth below it like $249 does.
        #
        # Extra Farm ($149/yr) STAYS. It is the right answer for 2–6 farms and the crossover lands
        # naturally at ~7 ($249 + 6 × $149 = $1,143), so the two prices select themselves and the
        # marginal farm never costs more than the first one.
        operation_features = {
            **compliance_features,
            # The one thing being bought. Everything else is inherited so the two tiers cannot
            # drift — a change to what Compliance includes is automatically in Operation.
            "max_establishments": -1,
            # 4x Compliance, not unlimited. Unlimited is Enterprise's line in the one-pager, and
            # a bounded number here keeps the storage meter meaningful (photo uploads are still
            # hard-limited; see `subscriptions/storage_accounting.py`).
            "storage_limit_gb": 100,
        }

        # Pilot — Compliance, comped. DERIVED, never hand-listed.
        #
        # It used to grant unlimited farms, 50 GB and 12hr support: entitlements no customer can
        # buy. That makes conversion a DOWNGRADE — at the moment you ask for money the product
        # gets worse — and the storage half was a hard blocker, not a feeling: `storage_utils`
        # refuses uploads over quota, so a pilot who logged 40 GB of photo evidence could not move
        # to Compliance's 25 GB without deleting their own records.
        #
        # It also broke the measurement. The Apr 30 conversion verdict is meant to test
        # willingness to pay for Trazo; if pilots ran on unlimited-everything it tested
        # willingness to pay for a tier that does not exist.
        #
        # Spreading compliance_features rather than repeating it means the two cannot drift: any
        # future change to what a customer buys is automatically what a pilot experiences.
        pilot_features = {
            **compliance_features,
            # Not a trial. A pilot ends by agreement on the grower's certifier renewal date (set
            # per-company by `provision_pilot`), not by a timer that silently cancels the account.
            "trial_no_card_days": 0,
            "trial_with_card_days": 0,
            "is_pilot": True,
        }

        # Base feature sets for each tier (shared between monthly and yearly).
        #
        # All four carry `compliance_exports: True`. They are RETIRED, not deleted, and every one
        # of them was a PAID tier — omitting the key would make `has_feature` return False and
        # silently strip the certifier packet, audit export, PUR export and certifier link from
        # anyone still on a legacy plan. There are no such subscribers today; that is a reason the
        # correction is cheap, not a reason to skip it.
        basic_features = {
            "max_establishments": 1,
            "max_parcels_per_establishment": 2,
            "max_productions_per_year": 3,
            "establishment_full_description": True,
            "storage_limit_gb": 10,
            "support_response_time": 48,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": False,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
            "compliance_exports": True,
        }

        standard_features = {
            "max_establishments": 2,
            "max_parcels_per_establishment": 2,
            "max_productions_per_year": 4,
            "establishment_full_description": True,
            "storage_limit_gb": 25,
            "support_response_time": 24,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": False,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
            "compliance_exports": True,
        }

        corporate_features = {
            "max_establishments": 4,
            "max_parcels_per_establishment": 4,
            "max_productions_per_year": 6,
            "establishment_full_description": True,
            "storage_limit_gb": 50,
            "support_response_time": 12,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": True,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
            "compliance_exports": True,
        }

        enterprise_features = {
            "max_establishments": -1,
            "max_parcels_per_establishment": -1,
            "max_productions_per_year": -1,
            "establishment_full_description": True,
            "storage_limit_gb": -1,
            "support_response_time": 4,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": True,
            "dedicated_support": True,
            "voice_recording": True,
            "ai_event_templates": True,
            "compliance_exports": True,
        }

        # Annual discount: 2 months free (pay for 10, get 12) = 16.7% savings
        ANNUAL_MULTIPLIER = 10  # monthly_price * 10 = annual price

        plans = [
            # Starter - free forever, no trial, no card (the "14-day free trial" this comment
            # once claimed is the phantom migration 0015 exists to kill; do not resurrect it)
            {
                "name": "Starter",
                "slug": "starter",
                "description": (
                    "Free forever. One farm, unlimited parcels, unlimited productions — log a "
                    "whole season with no card and no expiry. Certifier documents are Compliance."
                ),
                "price": 0.00,
                "interval": "monthly",
                "features": starter_features,
            },
            # Pilot - free, hand-assigned via Django admin, not offered in the pricing UI
            {
                "name": "Pilot",
                "slug": "pilot",
                "description": "Free pilot programme - unlimited farms, parcels and productions, white-glove onboarding",
                "price": 0.00,
                "interval": "monthly",
                "features": pilot_features,
            },
            # Compliance - the one paid tier
            {
                "name": "Compliance",
                "slug": "compliance-yearly",
                "description": (
                    "Everything one certified farm needs for renewal season: the OSP renewal "
                    "packet, the audit export, the CA PUR export, and the certifier and buyer "
                    "review links."
                ),
                "price": 249.00,
                "interval": "yearly",
                "features": compliance_features,
            },
            # Operation — every farm in the business, one price. See `operation_features` above
            # for why this tier exists and how $1,200 was set.
            {
                "name": "Operation",
                "slug": "operation-yearly",
                "description": (
                    "Every farm in your operation on one renewal: unlimited farms and "
                    "certifiers, the OSP renewal packet and audit export for each of them, the "
                    "CA PUR export per site, and a buyer page per production."
                ),
                "price": 1200.00,
                "interval": "yearly",
                "features": operation_features,
            },
            # ---- RETIRED 2026-08-07 (migration subscriptions/0009) -------------------------
            # The monthly ladder below is seeded INACTIVE so a fresh environment matches a
            # migrated one. Kept rather than deleted: Subscription.plan is PROTECT, and a plan
            # somebody references cannot be removed.
            # Basic Monthly
            {
                "is_active": False,
                "name": "Basic",
                "slug": "basic-monthly",
                "description": "Basic plan for small producers with transparency tracking",
                "price": 69.00,
                "interval": "monthly",
                "features": basic_features,
            },
            # Standard Monthly
            {
                "name": "Standard",
                "is_active": False,
                "slug": "standard-monthly",
                "description": "Standard plan for growing businesses with transparency tracking",
                "price": 119.00,
                "interval": "monthly",
                "features": standard_features,
            },
            # Corporate Monthly
            {
                "name": "Corporate",
                "is_active": False,
                "slug": "corporate-monthly",
                "description": "Corporate plan for larger operations with full transparency tracking and priority support",
                "price": 149.00,
                "interval": "monthly",
                "features": corporate_features,
            },
            # Enterprise Monthly — self-serve RETIRED 2026-08-12 (migration 0012). The lineup is
            # Starter + Compliance + "Enterprise: talk to us"; a public $299/mo offer beside a
            # $249/yr tier contradicted it. Row kept for provisioning, never listed.
            {
                "is_active": False,
                "name": "Enterprise",
                "slug": "enterprise-monthly",
                "description": "Enterprise plan for large-scale operations with unlimited transparency features",
                "price": 299.00,
                "interval": "monthly",
                "features": enterprise_features,
            },
            # Basic Annual (2 months free)
            {
                "name": "Basic",
                "is_active": False,
                "slug": "basic-yearly",
                "description": "Basic plan for small producers with transparency tracking (annual billing - 2 months free)",
                "price": 69.00 * ANNUAL_MULTIPLIER,
                "interval": "yearly",
                "features": basic_features,
            },
            # Standard Annual (2 months free)
            {
                "name": "Standard",
                "is_active": False,
                "slug": "standard-yearly",
                "description": "Standard plan for growing businesses with transparency tracking (annual billing - 2 months free)",
                "price": 119.00 * ANNUAL_MULTIPLIER,
                "interval": "yearly",
                "features": standard_features,
            },
            # Corporate Annual (2 months free)
            {
                "name": "Corporate",
                "is_active": False,
                "slug": "corporate-yearly",
                "description": "Corporate plan for larger operations with transparency tracking (annual billing - 2 months free)",
                "price": 149.00 * ANNUAL_MULTIPLIER,
                "interval": "yearly",
                "features": corporate_features,
            },
            # Enterprise Annual — self-serve RETIRED 2026-08-12 (migration 0012), same as monthly.
            {
                "is_active": False,
                "name": "Enterprise",
                "slug": "enterprise-yearly",
                "description": "Enterprise plan for large-scale operations with unlimited transparency features (annual billing - 2 months free)",
                "price": 299.00 * ANNUAL_MULTIPLIER,
                "interval": "yearly",
                "features": enterprise_features,
            },
        ]

        self.stdout.write(self.style.SUCCESS(f"Creating {len(plans)} plans..."))

        for plan_data in plans:
            product_name = f"Trazo {plan_data['name']} ({plan_data['interval'].title()})"

            # A RETIRED plan must never reach Stripe, and must never come back active.
            #
            # 2026-08-16: this guard did not exist and the Stripe branch below hardcoded
            # `is_active: True`, ignoring the definition. `create_addons` had the identical bug
            # and was fixed; `create_plans` was not. The consequence is dormant only while
            # STRIPE_SECRET_KEY is empty — the free/no-Stripe branch honours the flag — so it
            # detonates on the exact day Stripe is switched on:
            #
            #   * migrations 0009/0012 DEACTIVATE the retired ladder, but on a fresh database
            #     they run BEFORE any plan row exists and no-op. `create_plans` then creates all
            #     eleven, and with a key present every priced one came back `is_active=True`.
            #   * `PlanViewSet` is AllowAny and serves `self_serve_plans()`, so the public
            #     pricing API answered with TEN plans — Basic $69, Standard $119, Corporate $149,
            #     Enterprise $299 and their annual twins — beside the $249/yr Compliance tier the
            #     October pivot replaced them with. `enterprise-*` self-serve was retired BY NAME
            #     in migration 0012.
            #   * all eight carry `trial_no_card_days: 7` / `trial_with_card_days: 14`, so the
            #     pricing page renders "14-day free trial" again — the claim migration 0015
            #     exists to remove.
            #   * and it minted live Stripe products and prices for eight withdrawn products, in
            #     an account meant to have no such thing.
            #
            # MEASURED on a pristine `migrate` + `create_plans` database, 2026-08-16.
            #
            # It runs BEFORE the "already exists" skip below, and that order is the whole
            # remedy. Placed after it, the guard only protected databases that had never been
            # seeded — every environment ALREADY broken by the old behaviour hit
            # "Plan already exists" (the row has a stripe_price_id), skipped, and stayed on
            # sale forever. Re-running `create_plans` is the documented fix for a bad
            # environment, so it has to actually fix one.
            if not plan_data.get("is_active", True):
                Plan.objects.update_or_create(
                    slug=plan_data["slug"],
                    defaults={
                        "name": plan_data["name"],
                        "description": plan_data["description"],
                        "price": plan_data["price"],
                        "interval": plan_data["interval"],
                        "features": plan_data["features"],
                        "is_active": False,
                        # Detached, same reasoning as migration 0016 for the add-on side: a
                        # withdrawn product must not keep a billable price object pointed at
                        # it. Inactive already keeps it out of `self_serve_plans`, so this is
                        # belt and braces — but a repaired row should end up in the same state
                        # a fresh one does, or the two seeding paths disagree again.
                        "stripe_price_id": None,
                    },
                )
                self.stdout.write(
                    self.style.WARNING(f"⊘ Skipped Stripe for retired plan: {product_name} (local row seeded inactive)")
                )
                continue

            # Skip only what re-running would COST something to redo.
            #
            # The condition used to be `price == 0 or existing_plan.stripe_price_id`, so a FREE
            # plan was skipped for the sole reason that a row existed — meaning Starter and pilot
            # were written once, at first seed, and never updated again. Every later change to
            # their definition in this file silently failed to reach any environment that had
            # already been seeded. MEASURED 2026-08-17 on both the dev database and a
            # production-shaped simulation: `ai_event_templates` is set on Starter here, lives in
            # no migration, and was absent from both — so the app's pricing card quietly dropped
            # the templates row from the free tier.
            #
            # This file is the source of truth for what a plan grants. A seeder that declines to
            # apply its own definitions is not idempotent, it is write-once — and it produced
            # exactly the two-seeding-paths-disagree class that migrations 0015 and 0016 exist to
            # clean up after.
            #
            # A PAID plan with a `stripe_price_id` still short-circuits: re-running it would mean
            # re-verifying a live price against Stripe, which is what `--force` is for.
            existing_plan = Plan.objects.filter(slug=plan_data["slug"]).first()
            if existing_plan and not self.force and existing_plan.stripe_price_id:
                self.stdout.write(self.style.WARNING(f"Plan already exists: {product_name}"))
                continue

            try:
                # Free plans (Starter, Pilot) never need Stripe. Neither does anything else when
                # there is no key — see the guard in handle().
                if plan_data["price"] == 0 or not self.stripe_enabled:
                    Plan.objects.update_or_create(
                        slug=plan_data["slug"],
                        defaults={
                            "name": plan_data["name"],
                            "description": plan_data["description"],
                            "price": plan_data["price"],
                            "interval": plan_data["interval"],
                            "features": plan_data["features"],
                            "stripe_price_id": None,
                            "is_active": plan_data.get("is_active", True),
                        },
                    )
                    label = "free" if plan_data["price"] == 0 else "local-only (no Stripe)"
                    self.stdout.write(self.style.SUCCESS(f"✓ Created {label} plan: {product_name}"))
                    continue

                # Create product in Stripe
                product = stripe.Product.create(
                    name=product_name,
                    description=plan_data["description"],
                    metadata={"environment": self.environment, "plan_slug": plan_data["slug"]},
                )

                # Create price
                price = stripe.Price.create(
                    product=product.id,
                    unit_amount=int(plan_data["price"] * 100),  # Convert to cents
                    currency="usd",
                    recurring={
                        "interval": "month" if plan_data["interval"] == "monthly" else "year",
                    },
                    metadata={"plan_slug": plan_data["slug"], "environment": self.environment},
                )

                # Create or update plan in the database
                Plan.objects.update_or_create(
                    slug=plan_data["slug"],
                    defaults={
                        "name": plan_data["name"],
                        "description": plan_data["description"],
                        "price": plan_data["price"],
                        "interval": plan_data["interval"],
                        "features": plan_data["features"],
                        "stripe_price_id": price.id,
                        # Honour the definition, never hardcode True. Anything retired is already
                        # handled by the guard above and cannot reach here, so this is belt and
                        # braces — but it is the line that was wrong, and a reader who deletes
                        # the guard should not find a `True` waiting underneath it.
                        "is_active": plan_data.get("is_active", True),
                    },
                )

                self.stdout.write(self.style.SUCCESS(f"✓ Created plan: {product_name}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Error creating plan {product_name}: {str(e)}"))

    # `stripe.Price.create` wants "month"/"year"; `AddOn.interval` stores "monthly"/"yearly"
    # (same choices as `Plan.interval`, so the two can be rendered by one formatter). The
    # definitions below are written in the Stripe shape because that is the value that has to
    # be exact for billing; this maps it for storage.
    STRIPE_TO_DB_INTERVAL = {"month": "monthly", "year": "yearly"}

    def _db_interval(self, addon_data):
        """The model-side interval for one add-on definition, or a clear error.

        The first version read `addon_data["interval"]` inline at the three write sites. The
        WITHDRAWN branch sits OUTSIDE the try/except around the Stripe calls, so an add-on defined
        without an interval would abort the whole seeder after the plans were written but before
        the add-ons were — a half-seeded environment and a traceback naming neither the add-on nor
        the missing key. A price with no period must fail loudly and say which one.
        """
        raw = addon_data.get("interval")
        if raw not in self.STRIPE_TO_DB_INTERVAL:
            raise ValueError(
                f"Add-on {addon_data.get('slug')!r} has interval {raw!r}; expected one of "
                f"{sorted(self.STRIPE_TO_DB_INTERVAL)}. Every add-on must declare the period it "
                f"bills at — that omission is what let Extra Farm read as $30 with no period."
            )
        return self.STRIPE_TO_DB_INTERVAL[raw]

    def _addon_price_drift(self, existing_addon, addon_data):
        """Describe how the live Stripe price disagrees with this file, or None if it agrees.

        A Stripe price that cannot be read is treated as DRIFT, not as agreement. The whole
        point of this check is that an unverified id must not be trusted to bill; "the API
        call failed" is not evidence that the price is correct.
        """
        expected_cents = int(round(float(addon_data["price"]) * 100))
        expected_interval = addon_data["interval"]

        try:
            price = stripe.Price.retrieve(existing_addon.stripe_price_id)
        except Exception as e:
            return f"could not read Stripe price {existing_addon.stripe_price_id} ({e})"

        if getattr(price, "deleted", False) or not getattr(price, "active", True):
            return f"Stripe price {existing_addon.stripe_price_id} is archived"

        actual_cents = getattr(price, "unit_amount", None)
        recurring = getattr(price, "recurring", None) or {}
        actual_interval = recurring.get("interval") if hasattr(recurring, "get") else None

        problems = []
        if actual_cents != expected_cents:
            problems.append(f"amount {actual_cents} != {expected_cents} cents")
        if actual_interval != expected_interval:
            problems.append(f"interval {actual_interval!r} != {expected_interval!r}")
        return ", ".join(problems) or None

    def _reprice_addon(self, existing_addon, addon_data, db_interval):
        """Mint a replacement Stripe price on the existing product and repoint the row.

        Returns True on success. The old price is ARCHIVED rather than deleted — Stripe
        keeps it referenced by any subscription item already billing on it, and archiving is
        what stops it being attachable to a new one.
        """
        try:
            old_price = stripe.Price.retrieve(existing_addon.stripe_price_id)
            product_id = getattr(old_price, "product", None)
            if not product_id:
                return False

            new_price = stripe.Price.create(
                product=product_id,
                unit_amount=int(round(float(addon_data["price"]) * 100)),
                currency="usd",
                recurring={"interval": addon_data["interval"]},
                metadata={"addon_slug": addon_data["slug"], "environment": self.environment},
            )
            try:
                stripe.Price.modify(existing_addon.stripe_price_id, active=False)
            except Exception as e:
                # Non-fatal: the row already points at the correct price, so nothing can be
                # sold at the old one. Say so rather than fail the seed.
                self.stdout.write(self.style.WARNING(f"  could not archive old price: {e}"))

            AddOn.objects.filter(pk=existing_addon.pk).update(
                name=addon_data["name"],
                description=addon_data["description"],
                price=addon_data["price"],
                interval=db_interval,
                stripe_price_id=new_price.id,
                is_active=addon_data.get("is_active", True),
            )
            self.stdout.write(self.style.SUCCESS(f'✓ Repriced add-on: {addon_data["name"]} -> {new_price.id}'))
            return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Could not reprice {addon_data["name"]}: {e}'))
            return False

    def create_addons(self):
        addons = ADDON_DEFINITIONS

        self.stdout.write(self.style.SUCCESS(f"Creating {len(addons)} add-ons..."))

        for addon_data in addons:
            # Validate the period FIRST, before any branch and before Stripe is touched.
            #
            # Called lazily inside the three `update_or_create` blocks, a malformed definition
            # would still have run `stripe.Product.create` on the paid path — the KeyError lands
            # while building the Price kwargs, so the PRODUCT is already in Stripe and the price
            # never arrives. This file's whole theme is that a bad definition must not reach
            # Stripe (see the withdrawn-add-on guard below); the same applies to one that cannot
            # state what period it bills at.
            db_interval = self._db_interval(addon_data)

            # A WITHDRAWN add-on must never reach Stripe.
            #
            # The is_active flag used to be applied only at the update_or_create below — AFTER
            # stripe.Product.create and stripe.Price.create had already run. So every seed of a
            # fresh environment minted a live, recurring $15/mo price for the blockchain add-on
            # that was withdrawn on 2026-08-03, in a Stripe account that is meant to have no such
            # product. The local row is still written so existing references do not dangle.
            if not addon_data.get("is_active", True):
                AddOn.objects.update_or_create(
                    slug=addon_data["slug"],
                    defaults={
                        "name": addon_data["name"],
                        "description": addon_data["description"],
                        "price": addon_data["price"],
                        "interval": db_interval,
                        "is_active": False,
                    },
                )
                self.stdout.write(
                    self.style.WARNING(
                        f'⊘ Skipped Stripe for withdrawn add-on: {addon_data["name"]} ' f"(local row seeded inactive)"
                    )
                )
                continue

            # No Stripe key -> seed the local row only, same guard as create_plans. Without
            # this, a fresh no-Stripe environment raised inside stripe.Product.create for
            # every ACTIVE add-on, the broad except swallowed it, and the one add-on Trazo
            # actually sells was never written.
            #
            # This branch runs BEFORE the "already exists" check on purpose. With the old
            # order, an environment that once had Stripe keys and no longer does kept a
            # populated `stripe_price_id` forever — the row was skipped as "already exists"
            # and the id was never reconciled against anything. Seeding the local row first
            # means a no-Stripe environment always ends up with a NULL id, which is the only
            # honest value there: an id nothing can verify must not be allowed to bill.
            if not self.stripe_enabled:
                AddOn.objects.update_or_create(
                    slug=addon_data["slug"],
                    defaults={
                        "name": addon_data["name"],
                        "description": addon_data["description"],
                        "price": addon_data["price"],
                        "interval": db_interval,
                        "stripe_price_id": None,
                        "is_active": True,
                    },
                )
                self.stdout.write(self.style.SUCCESS(f'✓ Created local-only add-on (no Stripe): {addon_data["name"]}'))
                continue

            # Check if we already have this add-on — and whether its Stripe price still
            # matches what this file says it costs.
            #
            # 2026-08-16: "already exists -> skip" was a billing defect, not an optimisation.
            # A Stripe Price is IMMUTABLE: the amount and the recurring interval live on the
            # price object, not the product, so repricing means minting a new one. Migration
            # 0014 repriced Extra Farm from $30/MONTH to $149/YEAR by updating the local row,
            # and this branch then skipped the add-on on every subsequent seed because it
            # already had an id. The result was a row that displayed "$149.00 per year" while
            # its `stripe_price_id` still pointed at a live $30/month price — the exact defect
            # 0014 was written to remove, surviving in the payment rail where nobody reads it.
            #
            # So the check is no longer "is there an id" but "does the id still mean what we
            # publish". Drift mints a replacement price on the SAME product (the product is
            # the durable object; only the price changes) and repoints the row.
            existing_addon = AddOn.objects.filter(slug=addon_data["slug"]).first()
            if existing_addon and existing_addon.stripe_price_id and not self.force:
                drift = self._addon_price_drift(existing_addon, addon_data)
                if drift is None:
                    self.stdout.write(self.style.WARNING(f'Add-on already exists: {addon_data["name"]}'))
                    continue
                self.stdout.write(self.style.WARNING(f'↻ Repricing add-on {addon_data["name"]}: {drift}'))
                if self._reprice_addon(existing_addon, addon_data, db_interval):
                    continue
                # Repricing failed -> fall through and rebuild product + price from scratch.

            try:
                # Create product
                product = stripe.Product.create(
                    name=f"Trazo {addon_data['name']}",
                    description=addon_data["description"],
                    metadata={"environment": self.environment, "addon_slug": addon_data["slug"]},
                )

                # Create recurring price for add-ons
                price = stripe.Price.create(
                    product=product.id,
                    unit_amount=int(addon_data["price"] * 100),  # Convert to cents
                    currency="usd",
                    recurring={"interval": addon_data["interval"]},
                    metadata={"addon_slug": addon_data["slug"], "environment": self.environment},
                )

                # Create or update add-on in the database
                AddOn.objects.update_or_create(
                    slug=addon_data["slug"],
                    defaults={
                        "name": addon_data["name"],
                        "description": addon_data["description"],
                        "price": addon_data["price"],
                        "interval": db_interval,
                        "stripe_price_id": price.id,
                        # Honour the definition instead of hardcoding True — a withdrawn add-on
                        # (see "Blockchain Recording") must not be re-activated by a reseed.
                        "is_active": addon_data.get("is_active", True),
                    },
                )

                self.stdout.write(self.style.SUCCESS(f'✓ Created add-on: {addon_data["name"]}'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ Error creating add-on {addon_data["name"]}: {str(e)}'))
