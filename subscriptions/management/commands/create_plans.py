from django.conf import settings
from django.core.management.base import BaseCommand

import stripe

from subscriptions.models import AddOn, Plan

stripe.api_key = settings.STRIPE_SECRET_KEY


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

        self.stdout.write(self.style.SUCCESS("Setup completed successfully!"))

    def create_plans(self):
        # Starter (Free Trial) - 14-day trial, no credit card required
        starter_features = {
            "max_establishments": 1,
            # Unlimited parcels, deliberately. A Parcel IS a block, so a one-parcel free tier
            # cannot demonstrate anything to a 20-block orchard — the trial was structurally
            # incapable of showing value to the exact ICP it exists to attract. The limit that
            # makes Starter a trial is one PRODUCTION per year, not one block.
            "max_parcels_per_establishment": -1,
            "max_productions_per_year": 1,
            "establishment_full_description": False,
            "monthly_scan_limit": 1000,
            "storage_limit_gb": 2,
            "support_response_time": 72,
            "trial_no_card_days": 14,
            "trial_with_card_days": 14,
            "priority_support": False,
            "dedicated_support": False,
            "is_starter": True,
            "voice_recording": False,
            "ai_event_templates": True,
        }

        # Pilot — hand-provisioned, never self-served, never billed.
        #
        # Exists because no other plan shape can host an October pilot. A real mid-size CA orchard
        # maps one block to one Parcel, so it needs 15-25 parcels and ~20 productions a year,
        # against Starter's 1/1. Enforcement is a hard 403 (subscriptions/permissions.py), so a
        # Starter pilot dies at parcel #2 and again at production #2.
        #
        # Three properties are load-bearing and must not be "simplified":
        #   price = 0        -> mrr_for() returns 0 even on status="active", so pilots never book
        #                       phantom revenue. Putting a pilot on Enterprise/active instead
        #                       would report $299/mo of MRR that does not exist.
        #   slug != "starter" -> expire_trials filters plan__slug="starter"; a Starter-based pilot
        #                       flips to "canceled" at day 14, which nulls Company.subscription_plan
        #                       and 403s every creation across the app.
        #   status "active"   -> subscription_plan resolves only for active/trialing.
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
            "monthly_scan_limit": -1,
            "storage_limit_gb": 25,
            "support_response_time": 24,
            "trial_no_card_days": 14,
            "trial_with_card_days": 14,
            "priority_support": True,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
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

        # Base feature sets for each tier (shared between monthly and yearly)
        basic_features = {
            "max_establishments": 1,
            "max_parcels_per_establishment": 2,
            "max_productions_per_year": 3,
            "establishment_full_description": True,
            "monthly_scan_limit": 5000,
            "storage_limit_gb": 10,
            "support_response_time": 48,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": False,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
        }

        standard_features = {
            "max_establishments": 2,
            "max_parcels_per_establishment": 2,
            "max_productions_per_year": 4,
            "establishment_full_description": True,
            "monthly_scan_limit": 10000,
            "storage_limit_gb": 25,
            "support_response_time": 24,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": False,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
        }

        corporate_features = {
            "max_establishments": 4,
            "max_parcels_per_establishment": 4,
            "max_productions_per_year": 6,
            "establishment_full_description": True,
            "monthly_scan_limit": 20000,
            "storage_limit_gb": 50,
            "support_response_time": 12,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": True,
            "dedicated_support": False,
            "voice_recording": True,
            "ai_event_templates": True,
        }

        enterprise_features = {
            "max_establishments": -1,
            "max_parcels_per_establishment": -1,
            "max_productions_per_year": -1,
            "establishment_full_description": True,
            "monthly_scan_limit": -1,
            "storage_limit_gb": -1,
            "support_response_time": 4,
            "trial_no_card_days": 7,
            "trial_with_card_days": 14,
            "priority_support": True,
            "dedicated_support": True,
            "voice_recording": True,
            "ai_event_templates": True,
        }

        # Annual discount: 2 months free (pay for 10, get 12) = 16.7% savings
        ANNUAL_MULTIPLIER = 10  # monthly_price * 10 = annual price

        plans = [
            # Starter - 14-day free trial
            {
                "name": "Starter",
                "slug": "starter",
                "description": "Free Trial - Try Trazo free for 14 days with core transparency features",
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
                    "Everything one certified farm needs for renewal season: unlimited parcels "
                    "and productions, the certifier packet, CA PUR export and the buyer page."
                ),
                "price": 249.00,
                "interval": "yearly",
                "features": compliance_features,
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
            # Enterprise Monthly
            {
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
            # Enterprise Annual (2 months free)
            {
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

            # Check if we already have this plan
            existing_plan = Plan.objects.filter(slug=plan_data["slug"]).first()
            if existing_plan and not self.force:
                # For free plans, check if DB record exists; for paid, check stripe_price_id
                if plan_data["price"] == 0 or existing_plan.stripe_price_id:
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
                        "is_active": True,
                    },
                )

                self.stdout.write(self.style.SUCCESS(f"✓ Created plan: {product_name}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Error creating plan {product_name}: {str(e)}"))

    def create_addons(self):
        addons = [
            {
                "name": "Extra Establishment",
                "slug": "extra-establishment",
                "description": "Add an additional farm beyond your plan limit",
                "price": 30.00,
                "interval": "month",
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

        self.stdout.write(self.style.SUCCESS(f"Creating {len(addons)} add-ons..."))

        for addon_data in addons:
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
                        "is_active": False,
                    },
                )
                self.stdout.write(
                    self.style.WARNING(
                        f'⊘ Skipped Stripe for withdrawn add-on: {addon_data["name"]} ' f"(local row seeded inactive)"
                    )
                )
                continue

            # Check if we already have this add-on
            existing_addon = AddOn.objects.filter(slug=addon_data["slug"]).first()
            if existing_addon and existing_addon.stripe_price_id and not self.force:
                self.stdout.write(self.style.WARNING(f'Add-on already exists: {addon_data["name"]}'))
                continue

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
                        "stripe_price_id": price.id,
                        # Honour the definition instead of hardcoding True — a withdrawn add-on
                        # (see "Blockchain Recording") must not be re-activated by a reseed.
                        "is_active": addon_data.get("is_active", True),
                    },
                )

                self.stdout.write(self.style.SUCCESS(f'✓ Created add-on: {addon_data["name"]}'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ Error creating add-on {addon_data["name"]}: {str(e)}'))
