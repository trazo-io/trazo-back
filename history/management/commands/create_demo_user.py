"""
Create realistic demo farm data for investor/customer demos.

Usage:
    poetry run python manage.py create_demo_user demo@trazo.io
    poetry run python manage.py create_demo_user demo@trazo.io --reset

Creates:
    User (existing) -> Company -> Establishment -> 3 Parcels -> 6 Productions -> ~85 Events
    Coastal Valleys Ranch, California - Hass Avocado + Valencia Orange + Nonpareil Almond
    Events include photo albums (Unsplash) for 100% transparency scores.
"""

from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from carbon.models import CropType
from certifications.models import Certification
from common.models import Gallery, GalleryImage
from company.models import Company, Establishment
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from product.models import Parcel, Product
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn

from ._almond_demo_data import create_almond_current_events, create_almond_finished_events, create_almond_parcel

COMPANY_NAME = "Coastal Valleys Ranch (DEMO)"

# Free-to-use agricultural images from Unsplash (Unsplash License - free for commercial use)
# Used to provide photo verification for demo transparency scores
DEMO_IMAGES = {
    "soil_test": [
        # Hands holding dark soil, examining texture (soil analysis)
        "https://images.unsplash.com/photo-1492496913980-501348b61469?w=800&q=80",
    ],
    "cover_crop": [
        # Green agricultural rows (cover crop field)
        "https://images.unsplash.com/photo-1545309451-048d50bb3719?w=800&q=80",
    ],
    # Removed 2026-08-04: both images showed row-crop field machinery, used to
    # illustrate banded fertilizer in an avocado grove.
    "fertilizer": [],
    # Emptied 2026-08-15. The surviving entry was captioned "ground sprayer applying
    # treatment"; the image is a LIQUID-MANURE SLURRY TANKER with a trailing-hose disc
    # injector on a bare arable field — not a sprayer, not an orchard, and not a fungicide
    # application. It replaced the crop-duster in the 2026-08-04 prune and was never opened,
    # so a wrong photo was swapped for another wrong photo. It then became the hero image of
    # the consumer QR page, because ProductDetail takes the first production photo.
    # Removed, not replaced: see prune_misleading_demo_photos.
    "fungicide": [],
    "pesticide": [
        # Person in protective gear hand-spraying plants — plausible in an orchard.
        # The boom-sprayer-in-crop-field image was removed 2026-08-04.
        "https://images.unsplash.com/photo-1581578017093-cd30fce4eeb7?w=800&q=80",
    ],
    # Removed 2026-08-04: bare-field boom-sprayer imagery, used to illustrate weed
    # management between orchard rows.
    "herbicide": [],
    # Removed 2026-08-04: grass/grain field, used to illustrate scouting for avocado
    # lace bug in an orchard.
    "scouting": [],
    "pruning": [
        # Arborist pruning tree branches
        "https://images.unsplash.com/photo-1626828476637-5bd713ef9f22?w=800&q=80",
    ],
    "avocado_harvest": [
        # Avocados hanging on tree branch ready for harvest
        "https://images.unsplash.com/photo-1726177551991-270f9e79b65e?w=800&q=80",
    ],
    "orange_harvest": [
        # Hand picking orange from citrus tree
        "https://images.unsplash.com/photo-1528582654826-585a71fcf7f4?w=800&q=80",
    ],
    "planting": [
        # Hands holding soil with small seedling
        "https://images.unsplash.com/photo-1679110663825-c6ec1ad51884?w=800&q=80",
    ],
    "composting": [
        # Compost pile with organic waste in wooden bin
        "https://images.unsplash.com/photo-1587733761376-3f26fc81d17f?w=800&q=80",
    ],
    "organic_matter": [
        # Brown dried leaves/compost material in person's hand
        "https://images.unsplash.com/photo-1580974563942-76580268810f?w=800&q=80",
    ],
    "beneficial_insects": [
        # Ladybug on blade of grass (classic beneficial insect)
        "https://images.unsplash.com/photo-1528824620477-1cfafcb6d502?w=800&q=80",
    ],
    # Removed 2026-08-04: open field, not an orchard.
    "trap_monitoring": [],
    "ipm": [
        # Ladybug on grain head (biological pest control)
        "https://images.unsplash.com/photo-1745081154632-1a927ee0c847?w=800&q=80",
    ],
    # Removed 2026-08-04: open ploughed field with no trees, used to illustrate flame
    # weeding "in row middles between avocado rows".
    "cultivation": [],
    "drone_survey": [
        # Agricultural drone operating over farm field
        "https://images.unsplash.com/photo-1713952152768-5f28b8093166?w=800&q=80",
    ],
}


class Command(BaseCommand):
    help = "Create realistic demo farm data for a user"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="Email of existing user")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo data and recreate",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"]
        reset = options["reset"]

        # 1. Look up user
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f"User with email '{email}' not found. Create the user first.")

        self.stdout.write(f"User: {user.get_full_name()} ({email})")

        # 2. Idempotency check
        existing = Company.objects.filter(
            name=COMPANY_NAME,
            company_workers__user=user,
        ).first()

        if existing and not reset:
            self.stdout.write(
                self.style.WARNING(f"Demo data already exists (Company #{existing.id}). " f"Use --reset to recreate.")
            )
            return

        if existing and reset:
            self.stdout.write("Deleting existing demo data...")
            existing.delete()
            self.stdout.write(self.style.SUCCESS("Deleted."))

        # 3. Company
        company = Company.objects.create(
            name=COMPANY_NAME,
            tradename=COMPANY_NAME,
            address="4520 Foothill Rd",
            city="Ventura",
            state="California",
            country="United States",
            zip_code="93003",
            fiscal_id="87-1234567",
            description=(
                "DEMONSTRATION DATASET — this operation, its people, its certifiers, and "
                "every record shown are invented for product demonstration. "
                "Family-owned specialty agriculture operation in California. "
                "Growing premium Hass avocados and Valencia oranges on the "
                "Central Coast and Nonpareil almonds in the Central Valley "
                "since 1998 with a commitment to sustainable farming practices "
                "and full agricultural transparency."
            ),
            contact_email=email,
            contact_phone="+1-805-555-0142",
            employee_count=24,
            industry="Specialty Agriculture",
            is_active=True,
            legal_structure="Family LLC",
            primary_commodities="Hass Avocado, Valencia Orange, Nonpareil Almond",
            sustainability_commitment="GLOBALG.A.P. Certified, IPM Program",
            certifications="USDA Organic (PSOC), GLOBALG.A.P.",
            # Blockchain was withdrawn 2026-08-03 (BLOCKCHAIN_ENABLED defaults False); the demo
            # must not advertise a product that is no longer sold.
            blockchain_subscription_status=False,
        )
        self.stdout.write(f"  Company: {company.name} (#{company.id})")

        # WorksIn
        WorksIn.objects.create(
            user=user,
            company=company,
            role=WorksIn.COMPANY_ADMIN,
        )

        # 4. Subscription — Compliance, the one plan actually sold (2026-08-07 restructure).
        # The demo used to sit on "corporate-monthly", a ladder tier retired that day, so every
        # fresh seed showed prospects a plan and a price that no longer exist.
        try:
            plan = Plan.objects.get(slug="compliance-yearly")
        except Plan.DoesNotExist:
            raise CommandError("Compliance plan not found. Run 'python manage.py create_plans' first.")
        now = timezone.now()
        Subscription.objects.create(
            company=company,
            plan=plan,
            status="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=365),
        )

        # 5. Establishment
        establishment = Establishment.objects.create(
            name="Coastal Valleys Farm (DEMO)",
            address="4520 Foothill Rd",
            city="Ventura",
            state="California",
            country="United States",
            company=company,
            description=(
                "DEMONSTRATION DATASET — invented operation, people, certifiers, and records. "
                "150-acre specialty agriculture operation across California's "
                "Central Coast and Central Valley. Avocado and citrus on the "
                "coast, almonds in the valley. Drip, micro-sprinkler, and "
                "micro-jet irrigation fed by deep wells."
            ),
            latitude=34.3414,
            longitude=-119.1795,
            contact_person="Miguel Ramirez",
            contact_phone="+1-805-555-0143",
            zip_code="93003",
            is_active=True,
            crops_grown=["Hass Avocado", "Valencia Orange", "Nonpareil Almond"],
            # Practices only — certifications live in the Certification table, which is
            # gated by claim_authority.py. "USDA Organic Certified" led this array until
            # 2026-08-07.
            sustainability_practices=[
                "Integrated Pest Management",
                "Cover Cropping",
                "Drip Irrigation",
                "Beneficial Insect Releases",
            ],
            employee_count=18,
            total_acreage=149.0,
            year_established=1998,
            establishment_type="orchard",
            farming_method="sustainable",
            water_sources=["Deep Well Groundwater"],
            climate_zone="Mediterranean (Csb)",
            # `soil_types` is a legacy COLUMN NAME — every surface labels it "Soil health
            # practices" and the farm form collects practices. Seeding texture classes made
            # both the producer profile and the shopper page read "Soil health practices:
            # Sandy Loam, Clay Loam" (fixed 2026-08-07).
            soil_types=["Cover cropping", "Compost application", "Reduced tillage"],
            conservation_practices=[
                "Cover Crops",
                "Windbreaks",
                "Riparian Buffers",
            ],
            irrigation_methods=["Drip", "Micro-sprinkler"],
        )
        # Seeded farm: the records below are invented, so every certifier packet, OSP module,
        # workbook and PUR export built from it is stamped a specimen (common/specimen.py).
        establishment.is_demo = True
        establishment.save(update_fields=["is_demo"])
        self.stdout.write(f"  Establishment: {establishment.name} (#{establishment.id})")

        # 6. Products
        avo_product, _ = Product.objects.get_or_create(
            name="Avocado",
            defaults={"description": "Hass Avocado"},
        )
        ora_product, _ = Product.objects.get_or_create(
            name="Orange",
            defaults={"description": "Valencia Orange"},
        )

        # CropTypes
        avo_crop, _ = CropType.objects.get_or_create(
            slug="avocados",
            defaults={
                "name": "Avocados",
                "category": "tree_fruit",
                "description": "Premium Hass avocado production",
                "typical_farm_size": "10-50 hectares",
                "growing_season": "12 months (evergreen)",
                "harvest_season": "February - September",
                "emissions_per_hectare": 3500.0,
                "industry_average": 4200.0,
                "best_practice": 2800.0,
                "carbon_credit_potential": 1.5,
                "typical_cost_per_hectare": 18000.0,
                "fertilizer_cost_per_hectare": 3200.0,
                "fuel_cost_per_hectare": 1800.0,
                "irrigation_cost_per_hectare": 2500.0,
                "labor_cost_per_hectare": 8000.0,
                "organic_premium": "25-40%",
                "sustainable_premium": "10-20%",
                "local_premium": "5-15%",
                "sustainability_opportunities": [
                    "Drip irrigation optimization",
                    "Cover cropping between rows",
                    "Integrated pest management",
                ],
                "usda_factors_used": True,
                "data_source": "USDA ARS, UC ANR",
            },
        )
        ora_crop, _ = CropType.objects.get_or_create(
            slug="citrus_oranges",
            defaults={
                "name": "Citrus",
                "category": "tree_fruit",
                "description": "Valencia orange production",
                "typical_farm_size": "20-100 hectares",
                "growing_season": "12 months (evergreen)",
                "harvest_season": "March - October",
                "emissions_per_hectare": 2800.0,
                "industry_average": 3500.0,
                "best_practice": 2200.0,
                "carbon_credit_potential": 1.2,
                "typical_cost_per_hectare": 12000.0,
                "fertilizer_cost_per_hectare": 2400.0,
                "fuel_cost_per_hectare": 1500.0,
                "irrigation_cost_per_hectare": 2000.0,
                "labor_cost_per_hectare": 5000.0,
                "organic_premium": "20-35%",
                "sustainable_premium": "10-15%",
                "local_premium": "5-10%",
                "sustainability_opportunities": [
                    "Micro-sprinkler efficiency",
                    "Biological pest control",
                    "Composted citrus pulp recycling",
                ],
                "usda_factors_used": True,
                "data_source": "USDA ARS, UC ANR",
            },
        )

        # 7. Parcels
        avo_parcel = Parcel.objects.create(
            name="Hass Avocado Grove",
            description=(
                "15-hectare mature Hass avocado grove on south-facing hillside. "
                "Trees range from 8-25 years old with drip irrigation."
            ),
            establishment=establishment,
            product=avo_product,
            area=15.0,
            certified=True,
            certification_type="GLOBALG.A.P.",
            soil_type="Sandy Loam",
            contact_person="Miguel Ramirez",
            address="Block A - South Hillside",
            agricultural_details={
                "primary_crop": "Hass Avocado",
                "planting_density": "250 trees/ha",
                "irrigation_type": "Drip",
                "soil_ph": "6.5",
                "soil_organic_matter": "3.2%",
                "sustainability_practices": ("IPM, cover cropping, drip irrigation"),
                "consumer_story": (
                    "Our avocado grove sits on a sun-drenched hillside "
                    "overlooking the Pacific. Every tree is hand-tended "
                    "by our team, and we use beneficial insects instead "
                    "of harsh chemicals whenever possible."
                ),
            },
            carbon_calculation_enabled=True,
        )
        ora_parcel = Parcel.objects.create(
            name="Valencia Orange Orchard",
            description=(
                "20-hectare Valencia orange orchard on the valley floor. "
                "Micro-sprinkler irrigation with wind machines for frost."
            ),
            establishment=establishment,
            product=ora_product,
            area=20.0,
            certified=True,
            certification_type="USDA Organic, GLOBALG.A.P.",
            soil_type="Clay Loam",
            contact_person="Maria Lopez",
            address="Block B - Valley Floor",
            agricultural_details={
                "primary_crop": "Valencia Orange",
                "planting_density": "400 trees/ha",
                "irrigation_type": "Micro-sprinkler",
                "soil_ph": "6.8",
                "soil_organic_matter": "2.8%",
                "production_method": "organic",
                "sustainability_practices": (
                    "USDA Organic certified, biological pest control, "
                    "composted pulp, OMRI-listed inputs only, cover crops"
                ),
                "consumer_story": (
                    "Our USDA Organic certified Valencia orange orchard "
                    "thrives on the valley floor with nutrient-rich clay "
                    "loam soil. Every input is OMRI-listed and approved "
                    "for organic production. We release parasitic wasps "
                    "to control pests naturally and recycle citrus pulp "
                    "as compost."
                ),
            },
            carbon_calculation_enabled=True,
        )
        # Almond parcel (from _almond_demo_data module)
        alm_parcel, alm_product, alm_crop = create_almond_parcel(establishment, demo_images=DEMO_IMAGES)
        self.stdout.write(f"  Parcels: {avo_parcel.name}, {ora_parcel.name}, {alm_parcel.name}")

        # Structured Certification records (for consumer QR badge display)
        Certification.objects.create(
            establishment=establishment,
            certification_type="usda_organic",
            certification_number="DEMO-ORG-0001",
            certifier_name="DEMO — Pacific Slope Organic Certifiers (sample data, not an accredited agent)",
            effective_date=self._dt(2024, 8, 1).date(),
            expiry_date=self._dt(2028, 7, 31).date(),
            certification_scope="Crops - All",
            certified_items=["Hass Avocado", "Valencia Orange", "Nonpareil Almond"],
            verification_status="verified",
        )
        Certification.objects.create(
            establishment=establishment,
            certification_type="global_gap",
            certification_number="DEMO-GGP-0001",
            certifier_name="DEMO — Coast Range Assurance Services (sample data, not an accredited agent)",
            effective_date=self._dt(2024, 6, 1).date(),
            expiry_date=self._dt(2028, 5, 31).date(),
            certification_scope="Crops - All",
            certified_items=["Hass Avocado", "Valencia Orange", "Nonpareil Almond"],
            verification_status="self_reported",
        )
        self.stdout.write("  Certifications: USDA Organic (verified), GLOBALG.A.P. (self-reported)")

        # 8. Productions
        avo_finished = History(
            name="Avocado Season 2024-2025",
            type=History.ORCHARD,
            start_date=self._dt(2024, 9, 1),
            finish_date=self._dt(2025, 7, 15),
            published=True,
            description=(
                "Full production cycle for Hass avocado grove. "
                "19 agricultural events documented including soil management, "
                "irrigation, pest scouting, GLOBALG.A.P. certification, "
                "herbicide application, and three harvest passes "
                "totaling 135,000 kg."
            ),
            production_amount=135000,
            production_unit="kg",
            quality_grade="grade_a",
            harvest_method="manual",
            lot_id="AVO-2024-001",
            product=avo_product,
            parcel=avo_parcel,
            is_outdoor=True,
            age_of_plants="8-25 years",
            number_of_plants="3,750",
            soil_ph="6.5",
            operator=user,
            crop_type=avo_crop,
            earning=0,
            # This production's records were never anchored on-chain (blockchain is a
            # paid add-on). The seeder previously carried an invented Polygon tx hash
            # that resolves to nothing, and propagated blockchain_verified=True onto
            # every event in the PUBLIC consumer payload — an unverifiable proof claim,
            # and "blockchain-verified" is UNSAFE wording per .claude/rules/compliance.md
            # (SAFE: "blockchain-recorded"). Nothing fabricated goes on a public page.
            production_method="organic",
            cover_image_url="https://images.unsplash.com/photo-1726177551991-270f9e79b65e?w=1600&q=80",
            extra_data={
                "blockchain_enabled": False,
                "blockchain_verified": False,
            },
        )
        avo_finished.save()

        avo_current = History(
            name="Avocado Season 2025-2026",
            type=History.ORCHARD,
            start_date=self._dt(2025, 9, 1),
            published=False,
            description=("Current avocado production season - early stage management."),
            production_amount=0,
            product=avo_product,
            parcel=avo_parcel,
            is_outdoor=True,
            age_of_plants="9-26 years",
            number_of_plants="3,750",
            soil_ph="6.5",
            operator=user,
            production_method="organic",
            crop_type=avo_crop,
            earning=0,
        )
        avo_current.save()

        ora_finished = History(
            name="Orange Season 2024-2025",
            type=History.ORCHARD,
            start_date=self._dt(2024, 10, 1),
            finish_date=self._dt(2025, 8, 15),
            published=True,
            description=(
                "Full USDA Organic production cycle for Valencia orange "
                "orchard. 20 agricultural events documented with 100% "
                "OMRI-listed inputs, biological pest control, composting, "
                "PSOC annual certification, and three harvest passes "
                "totaling 420,000 kg."
            ),
            production_amount=420000,
            production_unit="kg",
            quality_grade="grade_a",
            harvest_method="manual",
            lot_id="ORA-2024-001",
            product=ora_product,
            parcel=ora_parcel,
            is_outdoor=True,
            production_method="organic",
            cover_image_url="https://images.unsplash.com/photo-1528582654826-585a71fcf7f4?w=1600&q=80",
            age_of_plants="12-30 years",
            number_of_plants="8,000",
            soil_ph="6.8",
            operator=user,
            crop_type=ora_crop,
            earning=0,
            # See the avocado production above — no fabricated on-chain proof.
            extra_data={
                "blockchain_enabled": False,
                "blockchain_verified": False,
            },
        )
        ora_finished.save()

        ora_current = History(
            name="Orange Season 2025-2026",
            type=History.ORCHARD,
            start_date=self._dt(2025, 10, 1),
            published=False,
            description=(
                "Current USDA Organic orange production season - " "pre-season preparation with OMRI-listed inputs."
            ),
            production_amount=0,
            product=ora_product,
            parcel=ora_parcel,
            is_outdoor=True,
            production_method="organic",
            age_of_plants="13-31 years",
            number_of_plants="8,000",
            soil_ph="6.8",
            operator=user,
            crop_type=ora_crop,
            earning=0,
        )
        ora_current.save()

        # Almond productions
        alm_finished = History(
            name="Almond Season 2024-2025",
            type=History.ORCHARD,
            start_date=self._dt(2024, 11, 1),
            finish_date=self._dt(2025, 10, 15),
            published=True,
            description=(
                "Full production cycle for Nonpareil almond orchard. "
                "22 agricultural events documented including pollination "
                "with 124 bee colonies, 4-split nitrogen fertigation, "
                "NOW mating disruption, hull split harvest via mechanical "
                "shaking, and post-harvest hulling & shelling. "
                "Yield: 170,000 kg kernel weight (2,755 kg/ha)."
            ),
            production_amount=170000,
            production_unit="kg",
            quality_grade="grade_a",
            harvest_method="mechanical",
            lot_id="ALM-2024-001",
            product=alm_product,
            parcel=alm_parcel,
            is_outdoor=True,
            age_of_plants="12-18 years",
            number_of_plants="6,875",
            soil_ph="7.0",
            operator=user,
            crop_type=alm_crop,
            earning=0,
            production_method="organic",
            cover_image_url="https://images.unsplash.com/photo-1773076088491-d6223773da0c?w=1600&q=80",
            # See the avocado production above — no fabricated on-chain proof.
            extra_data={
                "blockchain_enabled": False,
                "blockchain_verified": False,
            },
        )
        alm_finished.save()

        alm_current = History(
            name="Almond Season 2025-2026",
            type=History.ORCHARD,
            start_date=self._dt(2025, 11, 1),
            published=False,
            description=("Current almond production season - dormant management " "and early spring preparation."),
            production_amount=0,
            product=alm_product,
            parcel=alm_parcel,
            is_outdoor=True,
            age_of_plants="13-19 years",
            number_of_plants="6,875",
            soil_ph="7.0",
            operator=user,
            production_method="organic",
            crop_type=alm_crop,
            earning=0,
        )
        alm_current.save()

        self.stdout.write(
            f"  Productions: #{avo_finished.id}, #{avo_current.id}, "
            f"#{ora_finished.id}, #{ora_current.id}, "
            f"#{alm_finished.id}, #{alm_current.id}"
        )

        # 9. Events
        self._create_avocado_finished_events(avo_finished, user)
        self._create_avocado_current_events(avo_current, user)
        self._create_orange_finished_events(ora_finished, user)
        self._create_orange_current_events(ora_current, user)
        create_almond_finished_events(alm_finished, user, demo_images=DEMO_IMAGES)
        create_almond_current_events(alm_current, user, demo_images=DEMO_IMAGES)

        # 10. Set current_history on parcels
        avo_parcel.current_history = avo_current
        avo_parcel.save()
        ora_parcel.current_history = ora_current
        ora_parcel.save()
        alm_parcel.current_history = alm_current
        alm_parcel.save()

        # 11. Update trust metrics on ALL productions (finished + current)
        try:
            avo_finished.update_trust_metrics()
            ora_finished.update_trust_metrics()
            alm_finished.update_trust_metrics()
            avo_current.update_trust_metrics()
            ora_current.update_trust_metrics()
            alm_current.update_trust_metrics()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Trust metrics update failed (non-fatal): {e}"))

        # 12. Summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo data created successfully!"))
        self.stdout.write("")
        self.stdout.write(f"  Company:        {company.name} (#{company.id})")
        self.stdout.write(f"  Establishment:  {establishment.name} (#{establishment.id})")
        self.stdout.write(f"  Avocado Parcel: {avo_parcel.name} (#{avo_parcel.id})")
        self.stdout.write(f"  Orange Parcel:  {ora_parcel.name} (#{ora_parcel.id})")
        self.stdout.write(f"  Almond Parcel:  {alm_parcel.name} (#{alm_parcel.id})")
        self.stdout.write("")
        self.stdout.write(f"  Avocado 2024-25 (FINISHED): #{avo_finished.id} - 19 events")
        self.stdout.write(f"  Avocado 2025-26 (CURRENT):  #{avo_current.id} - 9 events")
        self.stdout.write(f"  Orange 2024-25 (FINISHED):  #{ora_finished.id} - 20 events")
        self.stdout.write(f"  Orange 2025-26 (CURRENT):   #{ora_current.id} - 7 events")
        self.stdout.write(f"  Almond 2024-25 (FINISHED):  #{alm_finished.id} - 22 events")
        self.stdout.write(f"  Almond 2025-26 (CURRENT):   #{alm_current.id} - 8 events")
        self.stdout.write("")
        self.stdout.write("  Consumer URLs:")
        self.stdout.write(f"    /production/{avo_finished.id}  (Avocado - finished)")
        self.stdout.write(f"    /production/{ora_finished.id}  (Orange - finished)")
        self.stdout.write(f"    /production/{alm_finished.id}  (Almond - finished)")

    # -- Helper: UTC datetime shorthand --

    def _dt(self, year, month, day, hour=8):
        return datetime(year, month, day, hour, 0, tzinfo=dt_tz.utc)

    # -- Helper: Create Gallery with demo images --

    def _create_album(self, image_key):
        """Create a Gallery with one GalleryImage, rotating within the pool.

        Every event of a given type used to receive the ENTIRE pool for that key,
        so the same two photographs backed every fungicide application across three
        crops. The audit dossier now flags a repeated image as possible fabricated
        evidence (7 CFR 205.201(a)(3)), and it was flagging the demo farm itself.

        Rotating one image per event keeps consecutive events visually distinct.
        Pools are still small, so reuse is reduced rather than eliminated — the
        honest fix is real photographs from a real operation, which is a content
        problem, not a code one.
        """
        urls = DEMO_IMAGES.get(image_key, [])
        if not urls:
            return None
        if not hasattr(self, "_album_cursor"):
            self._album_cursor = {}
        idx = self._album_cursor.get(image_key, 0)
        self._album_cursor[image_key] = idx + 1
        gallery = Gallery.objects.create()
        GalleryImage.objects.create(gallery=gallery, image_url=urls[idx % len(urls)])
        return gallery

    # -- Avocado 2024-2025 FINISHED (18 events) --

    def _create_avocado_finished_events(self, prod, user):
        # 0: Soil Test (Tier 2 - recommended photo)
        SoilManagementEvent.objects.create(
            history=prod,
            index=0,
            date=self._dt(2024, 9, 5),
            description=(
                "Annual soil test across avocado grove. Lab results: pH 6.5, "
                "organic matter 3.2%, adequate phosphorus, low zinc. "
                "Sandy loam texture confirmed."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=SoilManagementEvent.SOIL_TEST,
            name="Annual Soil Analysis",
            soil_ph=Decimal("6.50"),
            organic_matter_percentage=Decimal("3.20"),
            soil_texture="sandy_loam",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            test_results={
                "ph": 6.5,
                "organic_matter_pct": 3.2,
                "nitrogen_ppm": 45,
                "phosphorus_ppm": 32,
                "potassium_ppm": 280,
                "zinc_ppm": 1.8,
                "lab": "A&L Western Laboratories",
            },
            working_depth=Decimal("30.00"),
            depth_unit="cm",
            extra_data={"samples_collected": 24},
            album=self._create_album("soil_test"),
        )

        # 1: Cover Crop (Tier 1 - essential photo)
        SoilManagementEvent.objects.create(
            history=prod,
            index=1,
            date=self._dt(2024, 9, 20),
            description=(
                "Planted crimson clover and white mustard cover crop mix "
                "between avocado rows. Seed rate 25 kg/ha for nitrogen "
                "fixation and erosion control during fall rains."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=SoilManagementEvent.COVER_CROP,
            name="Fall Cover Crop Planting",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            working_depth=Decimal("30.00"),
            depth_unit="cm",
            soil_ph=Decimal("6.50"),
            organic_matter_percentage=Decimal("3.50"),
            soil_texture="loam",
            soil_moisture="moderate",
            amendment_type="Crimson Clover + White Mustard seed mix",
            amendment_amount="375",
            fuel_consumed=Decimal("8.00"),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=Decimal("6.00"),
            equipment_used="John Deere 5075E with seed drill",
            extra_data={
                "seed_mix": {
                    "crimson_clover_pct": 60,
                    "white_mustard_pct": 40,
                },
                "expected_biomass_tons_ha": 4.5,
            },
            album=self._create_album("cover_crop"),
        )

        # 2: Fertilizer - YaraMila 12-11-18 (Tier 1 - essential, 2 photos)
        ChemicalEvent.objects.create(
            history=prod,
            index=2,
            date=self._dt(2024, 10, 10),
            description=(
                "Applied YaraMila Complex 12-11-18 via banding under tree "
                "canopy. 2,250 kg total across 15 ha (150 kg/ha). "
                "Diesel consumption 13.25 L for application equipment."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="synthetic_fertilizer",
            name="Fall Base Fertilization",
            commercial_name="YaraMila Complex 12-11-18",
            concentration="12-11-18",
            volume="2250",
            area="15",
            # area_unit is EXPLICIT on every chemical event here (2026-08-01). ChemicalEvent
            # defaults it to "acres" while ProductionEvent/SoilManagementEvent default to "ha",
            # so omitting it stamped these hectare values as acres — the live demo card read
            # "Area Treated: 15 acres" directly above the farmer's own note saying "15 ha".
            area_unit="ha",
            way_of_application="banded",
            application_method_structured="banding",
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("13.25"),
            application_fuel_unit="L",
            application_timing="fruit_development",
            weather_conditions="calm_dry",
            target_pest_disease="Nutrient deficiency, Base fertilization",
            organic_approved="not_organic",
            extra_data={"rate_kg_ha": 150, "cost_usd": 3150, "volume_unit": "kg"},
            album=self._create_album("fertilizer"),
        )

        # 3: Irrigation Summary (18 cycles over the season)
        ProductionEvent.objects.create(
            history=prod,
            index=3,
            date=self._dt(2024, 11, 15),
            description=(
                "Deep well pump (~150ft) supplying drip irrigation system "
                "for 15ha Hass avocado grove. 18 irrigation cycles from "
                "November 2024 through June 2025, totaling 3,600,000 "
                "gallons. Soil moisture sensors guide scheduling, averaging "
                "200,000 gal per cycle. Electric pump consuming 3,060 kWh."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=ProductionEvent.IRRIGATION,
            name="Season Irrigation Program",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            fuel_consumed=Decimal("3060.00"),
            fuel_unit="kWh",
            fuel_type="electric",
            water_source="well_groundwater",
            irrigation_method="drip",
            irrigation_depth=Decimal("2.50"),
            irrigation_depth_unit="inches",
            production_efficiency="high",
            observation="Soil moisture sensors confirmed uniform distribution",
            extra_data={
                "is_summary": True,
                "date_start": "2024-11-15",
                "date_end": "2025-06-15",
                "event_count": 18,
                "water_volume_total": 3600000,
                "water_volume_unit": "gallons",
                "irrigation_depth": "2.5",
                "irrigation_depth_unit": "inches",
                "irrigation_method": "drip",
                "water_source": "well_groundwater",
            },
        )

        # 4: Fungicide - Ridomil Gold (Tier 1 - essential, 2 photos)
        ChemicalEvent.objects.create(
            history=prod,
            index=4,
            date=self._dt(2025, 1, 8),
            description=(
                "Ridomil Gold SL (mefenoxam) trunk drench for Phytophthora "
                "cinnamomi root rot prevention. 15 L product in 1500 L water "
                "applied to root zone of 3,750 trees."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FUNGICIDE,
            chemical_subtype="synthetic_fungicide",
            name="Phytophthora Prevention Treatment",
            commercial_name="Ridomil Gold SL (mefenoxam)",
            volume="15",
            concentration="45.3",
            area="15",
            area_unit="ha",
            way_of_application="soil_incorporation",
            target_pest_disease="Phytophthora cinnamomi root rot",
            organic_approved="not_organic",
            rei_hours=Decimal("48.0"),
            phi_days=Decimal("14.0"),
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("4.50"),
            application_fuel_unit="L",
            application_timing="pre_plant",
            weather_conditions="calm_dry",
            extra_data={"dilution_rate": "10 mL/L", "water_volume_L": 1500, "volume_unit": "L"},
            album=self._create_album("fungicide"),
        )

        # 5: Pest Scouting Summary (12 bi-weekly trips)
        PestManagementEvent.objects.create(
            history=prod,
            index=5,
            date=self._dt(2025, 2, 5),
            description=(
                "Bi-weekly scouting program covering 15 hectares of Hass "
                "avocado grove. Primary monitoring for Persea mite "
                "(Oligonychus perseae) and avocado thrips (Scirtothrips "
                "perseae). 12 scouting trips from November through April. "
                "Pest pressure remained low throughout, with natural "
                "predator populations (Galendromus helveolus) maintaining "
                "all pests below economic threshold. Sticky traps and leaf "
                "samples checked on each visit."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=PestManagementEvent.SCOUTING,
            pest_species=("Persea mite (Oligonychus perseae), " "Avocado thrips (Scirtothrips perseae)"),
            pest_pressure_level="Low",
            action_threshold_met=False,
            beneficial_insects_used="yes",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            ipm_strategy=(
                "Monitoring sticky traps and leaf samples. Natural predator "
                "populations (Galendromus helveolus) maintaining pest levels "
                "below economic threshold."
            ),
            extra_data={
                "name": "Pest Scouting Summary",
                "is_summary": True,
                "date_start": "2024-11-01",
                "date_end": "2025-04-30",
                "event_count": 12,
                "pest_species_observed": ("Persea mite, Avocado thrips, Avocado lace bug"),
                "average_pest_pressure": "low",
                "area_covered_total": 15,
                "area_unit": "ha",
                "carbon_notes": ("Pest scouting is observational and does not " "directly produce emissions"),
                "carbon_impact": "zero",
            },
            album=self._create_album("scouting"),
        )

        # 6: Heat Wave
        WeatherEvent.objects.create(
            history=prod,
            index=6,
            date=self._dt(2025, 3, 15),
            description=(
                "3-day heat wave with temperatures reaching 42C (108F). "
                "Activated overhead mist system to reduce canopy temperature "
                "and prevent fruit sunburn. Increased irrigation frequency."
            ),
            created_by=user,
            performed_by="Miguel Ramirez",
            type=WeatherEvent.HIGH_TEMPERATURE,
            observation=(
                "Peak temps 42C/108F. Overhead mist activated 10am-4pm "
                "daily. Estimated 5% fruit drop on exposed south-facing "
                "canopy."
            ),
            extra_data={
                "event_name": "Heat Wave",
                "highest_temperature": "42",
                "start_date": "2025-03-15T10:00",
                "end_date": "2025-03-17T18:00",
                "duration_days": 3,
                "fruit_drop_pct": 5,
                "mist_water_gallons": 8500,
            },
        )

        # 7: Summer Fertigation
        ChemicalEvent.objects.create(
            history=prod,
            index=7,
            date=self._dt(2025, 4, 1),
            description=(
                "Summer fertigation with Fertiactyl GZ 13-0-5 "
                "through drip system. 1,500 L product addressing zinc "
                "deficiency identified in soil test. Humic/fulvic acid "
                "base improves micronutrient uptake."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="synthetic_fertilizer",
            name="Summer Fertigation",
            commercial_name="Fertiactyl GZ 13-0-5",
            concentration="13-0-5",
            volume="1500",
            area="15",
            area_unit="ha",
            way_of_application="fertigation",
            application_method_structured="drip",
            application_timing="fruit_development",
            weather_conditions="calm_dry",
            target_pest_disease="Zinc deficiency correction, Summer nutrition",
            organic_approved="not_organic",
            application_fuel_type="electric",
            application_fuel_consumed=Decimal("2.50"),
            application_fuel_unit="kWh",
            extra_data={"zinc_content_pct": 2.5, "rate_L_ha": 100, "volume_unit": "L"},
            album=self._create_album("fertilizer"),
        )

        # 8: Pruning (Tier 2 - recommended photo)
        ProductionEvent.objects.create(
            history=prod,
            index=8,
            date=self._dt(2025, 4, 20),
            description=(
                "Annual structural pruning of avocado grove. Removed dead "
                "wood, improved light penetration, and managed tree height. "
                "12 gallons diesel, 24 equipment hours."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.PRUNING,
            name="Annual Structural Pruning",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            fuel_consumed=Decimal("12.00"),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_type="tractor",
            equipment_hours=Decimal("24.00"),
            production_efficiency="normal",
            observation="Pruning debris chipped and used as mulch on-site",
            extra_data={"crew_size": 6, "biomass_chipped_tons": 8.5},
            album=self._create_album("pruning"),
        )

        # 9: Harvest Pass 1 (Tier 1 - essential photo)
        ProductionEvent.objects.create(
            history=prod,
            index=9,
            date=self._dt(2025, 5, 1),
            description=(
                "First harvest pass - early-season fruit. 45,000 kg Grade A "
                "Hass avocados. Manual pick with hand tools."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.HARVESTING,
            name="Harvest Pass 1 - Early Season",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            yield_quantity=Decimal("45000.00"),
            yield_unit="kg",
            harvest_quality_grade="grade_a",
            production_efficiency="normal",
            observation="Good size distribution, 70% count 48-60",
            extra_data={
                "crew_size": 12,
                "bins_filled": 90,
                "kg_per_bin": 500,
            },
            album=self._create_album("avocado_harvest"),
        )

        # 10: Harvest Pass 2 (Tier 1 - essential photo)
        ProductionEvent.objects.create(
            history=prod,
            index=10,
            date=self._dt(2025, 5, 25),
            description=(
                "Second harvest pass - peak season. 55,000 kg export quality "
                "Hass avocados. Largest yield of the season."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.HARVESTING,
            name="Harvest Pass 2 - Peak Season",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            yield_quantity=Decimal("55000.00"),
            yield_unit="kg",
            harvest_quality_grade="export_quality",
            production_efficiency="high",
            observation="Excellent oil content 22-24%, premium export grade",
            extra_data={
                "crew_size": 15,
                "bins_filled": 110,
                "oil_content_pct": 23,
            },
            album=self._create_album("avocado_harvest"),
        )

        # 11: Harvest Pass 3 (Tier 1 - essential photo)
        ProductionEvent.objects.create(
            history=prod,
            index=11,
            date=self._dt(2025, 6, 20),
            description=(
                "Third harvest pass - late season cleanup. 35,000 kg Grade A. " "Final pick of remaining mature fruit."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.HARVESTING,
            name="Harvest Pass 3 - Late Season",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            yield_quantity=Decimal("35000.00"),
            yield_unit="kg",
            harvest_quality_grade="grade_a",
            production_efficiency="normal",
            observation="Season wrap-up, smaller fruit but good quality",
            extra_data={"crew_size": 10, "bins_filled": 70},
            album=self._create_album("avocado_harvest"),
        )

        # 12: Equipment Maintenance (migrated from EquipmentEvent → ProductionEvent EM)
        ProductionEvent.objects.create(
            history=prod,
            index=12,
            date=self._dt(2025, 7, 1),
            description=(
                "Scheduled maintenance on John Deere 5075E tractor. "
                "Oil change, filter replacement, hydraulic check. "
                "5 gallons diesel for test run, 8 hours total."
            ),
            created_by=user,
            performed_by="David Chen",
            type=ProductionEvent.EQUIPMENT_MAINTENANCE,
            name="Tractor Annual Service",
            fuel_consumed=Decimal("5.00"),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_type="tractor",
            equipment_operation_type="MN",
            equipment_hours=Decimal("8.00"),
            production_efficiency="normal",
            observation="All systems nominal. Next service at 500 hours.",
            extra_data={
                "equipment_name": "John Deere 5075E",
                "maintenance_cost": 850.00,
                "odometer_hours": 2340,
                "next_service_hours": 2840,
                "previous_use": "conventional",
                "cleaning_protocol": "triple_rinse",
                "inspected_by": "David Chen",
            },
        )

        # 13: GLOBALG.A.P. Certification Audit
        BusinessEvent.objects.create(
            history=prod,
            index=13,
            date=self._dt(2025, 7, 10),
            description=(
                "Annual GLOBALG.A.P. IFA v6 certification audit conducted by "
                "Coast Range Assurance Services (DEMO). All 217 control points reviewed across "
                "food safety, worker welfare, and environmental management. "
                "Certified with zero non-conformances."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=BusinessEvent.CERTIFICATION,
            name="GLOBALG.A.P. Annual Certification",
            business_type="certification",
            certification_type="global_gap",
            verification_status="verified",
            sustainability_practice="integrated_pest",
            verified_certifier_name="DEMO — Coast Range Assurance Services (sample data, not an accredited agent)",
            certificate_number="DEMO-GGP-0002",
            observation=(
                "Full compliance with IFA v6. Highlights: excellent "
                "traceability records, strong IPM program, worker safety "
                "protocols above standard."
            ),
            extra_data={
                "audit_date": "2025-07-10",
                "auditor": "Coast Range Assurance Services (DEMO)",
                "standard": "GLOBALG.A.P. IFA v6",
                "control_points": 217,
                "major_nc": 0,
                "minor_nc": 0,
                "valid_until": "2026-07-09",
            },
        )

        # 14: Glyphosate Herbicide Application (diesel)
        ChemicalEvent.objects.create(
            history=prod,
            index=14,
            date=self._dt(2025, 7, 15),
            description=(
                "Post-harvest glyphosate (Roundup PowerMax 3) weed control "
                "application on row middles. Directed spray to avoid tree "
                "contact. 4.7 L/ha rate with shielded sprayer."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.HERBICIDE,
            chemical_subtype="synthetic_herbicide",
            name="Post-Harvest Weed Control",
            commercial_name="Roundup PowerMax 3 (glyphosate)",
            volume="70.5",
            concentration="48.7",
            area="15",
            area_unit="ha",
            way_of_application="ground_spray",
            application_method_structured="broadcast",
            application_timing="post_harvest",
            weather_conditions="calm_dry",
            target_pest_disease="Broadleaf weeds, Annual grasses",
            organic_approved="not_organic",
            rei_hours=Decimal("12.0"),
            phi_days=Decimal("14.0"),
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("6.00"),
            application_fuel_unit="gal",
            extra_data={
                "rate_L_ha": 4.7,
                "spray_equipment": "Shielded boom sprayer",
                "water_volume_L_ha": 200,
                "nozzle_type": "Flat fan TT11002",
                "volume_unit": "L",
            },
            album=self._create_album("herbicide"),
        )

        # 15: Spring Replanting (Tier 1 - essential photo) (biodiesel)
        ProductionEvent.objects.create(
            history=prod,
            index=15,
            date=self._dt(2024, 9, 25),
            description=(
                "Replanted 120 Hass avocado trees on GEM rootstock to "
                "replace aging, low-producing trees in blocks 3 and 7. "
                "Clonal nursery stock from Saticoy Grove Nursery. Biodiesel-powered "
                "tractor for hole augering and tree placement."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=ProductionEvent.PLANTING,
            name="Spring Replanting - Blocks 3 & 7",
            area_covered=Decimal("2.50"),
            area_unit="ha",
            fuel_consumed=Decimal("18.00"),
            fuel_unit="L",
            fuel_type="biodiesel",
            equipment_type="tractor",
            equipment_hours=Decimal("10.00"),
            production_efficiency="normal",
            observation="120 GEM rootstock trees planted, 6m x 6m spacing",
            seeds_source="commercial",
            seed_certification_status="certified_organic",
            extra_data={
                "trees_planted": 120,
                "rootstock": "GEM (clonal)",
                "nursery": "Saticoy Grove Nursery, Saticoy CA",
                "spacing_m": "6 x 6",
                "blocks": "3, 7",
                "seed_supplier": "Saticoy Grove Nursery, Saticoy CA",
                "seed_variety": "Hass on GEM rootstock",
                "seed_lot_number": "BN-2024-GEM-0892",
                "organic_certificate_number": "DEMO-NUR-0002",
                "treated_or_untreated": "untreated",
            },
            album=self._create_album("planting"),
        )

        # 16: Persea Mite Trap Monitoring (Tier 2 - recommended photo) (manual, no fuel)
        PestManagementEvent.objects.create(
            history=prod,
            index=16,
            date=self._dt(2025, 3, 1),
            description=(
                "Installed and monitored 60 yellow sticky traps across "
                "15 ha for Persea mite (Oligonychus perseae) population "
                "tracking. 4 traps per hectare placed at canopy mid-height. "
                "Results: 2.3 mites/trap average, well below 10/trap threshold."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=PestManagementEvent.TRAP_MONITORING,
            pest_species="Persea mite (Oligonychus perseae)",
            pest_pressure_level="Low",
            trap_count=60,
            action_threshold_met=False,
            beneficial_insects_used="planning",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            ipm_strategy=(
                "Yellow sticky trap grid at 4 traps/ha, canopy mid-height. "
                "Threshold: 10 mites/trap triggers intervention. Natural "
                "predators (Galendromus helveolus) supplementing control."
            ),
            extra_data={
                "name": "Persea Mite Trap Monitoring",
                "traps_per_ha": 4,
                "avg_mites_per_trap": 2.3,
                "treatment_threshold": 10,
                "trap_type": "Yellow sticky card",
                "placement": "Canopy mid-height, south-facing",
            },
            album=self._create_album("trap_monitoring"),
        )

        # 17: Airblast Sprayer Calibration (gasoline)
        ProductionEvent.objects.create(
            history=prod,
            index=17,
            date=self._dt(2025, 4, 10),
            description=(
                "Annual calibration of Turbomist 400 airblast sprayer. "
                "Verified nozzle output, fan speed, and coverage pattern "
                "using water-sensitive cards. Gasoline-powered PTO unit "
                "ran 3 hours during calibration passes."
            ),
            created_by=user,
            performed_by="David Chen",
            type=ProductionEvent.EQUIPMENT_MAINTENANCE,
            name="Airblast Sprayer Calibration",
            fuel_consumed=Decimal("4.50"),
            fuel_unit="gal",
            fuel_type="gasoline",
            equipment_type="sprayer",
            equipment_operation_type="CA",
            equipment_hours=Decimal("3.00"),
            production_efficiency="high",
            observation=(
                "All 24 nozzles within 5% of target output, fan speed "
                "calibrated to 2400 RPM for mature avocado canopy"
            ),
            extra_data={
                "equipment_name": "Turbomist 400 airblast sprayer",
                "nozzles_tested": 24,
                "nozzles_replaced": 2,
                "coverage_pattern": "Full canopy verified",
                "water_sensitive_cards": 48,
            },
        )

        # 18: Water Quality Testing (General - fills general category for 100% score)
        GeneralEvent.objects.create(
            history=prod,
            index=18,
            date=self._dt(2025, 6, 1),
            description=(
                "Quarterly water quality testing of irrigation well and "
                "distribution system. Tested for pH, EC, SAR, boron, "
                "chloride, and microbial contamination. All parameters "
                "within acceptable limits for avocado production."
            ),
            created_by=user,
            performed_by="Ana Torres",
            name="Irrigation Water Quality Test",
            activity_type="quality_control",
            activity_name="Quarterly water quality analysis",
            duration="2",
            people_involved=1,
            observation=(
                "pH 7.1, EC 0.8 dS/m, SAR 2.1 - all within optimal " "range for avocado. No microbial issues detected."
            ),
            extra_data={
                "lab": "A&L Western Laboratories",
                "ph": 7.1,
                "ec_ds_m": 0.8,
                "sar": 2.1,
                "boron_ppm": 0.3,
                "chloride_ppm": 45,
            },
        )

        self.stdout.write("  Avocado Finished: 19 events created")

    # -- Avocado 2025-2026 IN PROGRESS (9 events) --

    def _create_avocado_current_events(self, prod, user):
        # 0: Compost Application (Tier 2 - recommended photo)
        SoilManagementEvent.objects.create(
            history=prod,
            index=0,
            date=self._dt(2025, 9, 10),
            description=(
                "Applied composted green waste at 5 tons/ha across avocado "
                "grove. Improves soil organic matter and water retention."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=SoilManagementEvent.ORGANIC_MATTER,
            name="Fall Compost Application",
            amendment_type="Composted green waste",
            amendment_amount="75000",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            fuel_consumed=Decimal("15.00"),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=Decimal("10.00"),
            equipment_used="John Deere 5075E with spreader",
            extra_data={
                "compost_source": "Agromin, Oxnard CA",
                "c_n_ratio": 18,
            },
            album=self._create_album("organic_matter"),
        )

        # 1: Slow-Release Fertilizer
        ChemicalEvent.objects.create(
            history=prod,
            index=1,
            date=self._dt(2025, 9, 25),
            description=(
                "Applied Osmocote Plus 15-9-12 slow-release fertilizer "
                "via banding. 8-9 month release profile for sustained "
                "nutrition."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="slow_release_fertilizer",
            name="Slow-Release Fall Fertilization",
            commercial_name="Osmocote Plus 15-9-12",
            concentration="15-9-12",
            volume="1875",
            area="15",
            area_unit="ha",
            way_of_application="banded",
            application_method_structured="banding",
            application_timing="pre_plant",
            weather_conditions="calm_dry",
            target_pest_disease="Sustained nutrition, Season-long fertilization",
            organic_approved="not_organic",
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("8.00"),
            application_fuel_unit="L",
            extra_data={"rate_kg_ha": 125, "release_months": "8-9", "volume_unit": "kg"},
            album=self._create_album("fertilizer"),
        )

        # 2: First Irrigation
        ProductionEvent.objects.create(
            history=prod,
            index=2,
            date=self._dt(2025, 10, 5),
            description=(
                "First irrigation run of new season. System check and " "pressure testing before full operation."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=ProductionEvent.IRRIGATION,
            name="Season Opening Irrigation",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            fuel_consumed=Decimal("85.00"),
            fuel_unit="kWh",
            water_source="well_groundwater",
            irrigation_method="drip",
            irrigation_depth=Decimal("1.50"),
            irrigation_depth_unit="inches",
            production_efficiency="normal",
            observation="All emitters functional, no leaks detected",
            extra_data={
                "system_pressure_psi": 25,
                "emitters_checked": 500,
            },
        )

        # 3: Phosphojet Trunk Injection
        ChemicalEvent.objects.create(
            history=prod,
            index=3,
            date=self._dt(2025, 10, 20),
            description=(
                "Phosphojet (potassium phosphite) trunk injection for "
                "Phytophthora cinnamomi prevention. Targeted treatment "
                "of susceptible trees."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FUNGICIDE,
            chemical_subtype="synthetic_fungicide",
            name="Phytophthora Trunk Injection",
            commercial_name="Phosphojet (potassium phosphite)",
            volume="45",
            concentration="45",
            area="15",
            area_unit="ha",
            way_of_application="soil_incorporation",
            target_pest_disease="Phytophthora cinnamomi root rot",
            organic_approved="not_organic",
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("6.00"),
            application_fuel_unit="L",
            application_timing="pre_plant",
            weather_conditions="calm_dry",
            extra_data={
                "trees_injected": 450,
                "ml_per_tree": 100,
                "injection_method": "Chemjet tree injector",
                "volume_unit": "L",
            },
            album=self._create_album("fungicide"),
        )

        # 4: Pest Scouting (Tier 2 - recommended photo)
        PestManagementEvent.objects.create(
            history=prod,
            index=4,
            date=self._dt(2025, 11, 5),
            description=(
                "Early season scouting for avocado lace bug "
                "(Pseudacysta perseae) and Persea mite. Both at low "
                "pressure."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=PestManagementEvent.SCOUTING,
            pest_species=("Avocado lace bug (Pseudacysta perseae), " "Persea mite (Oligonychus perseae)"),
            pest_pressure_level="Low",
            action_threshold_met=False,
            beneficial_insects_used="yes",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            ipm_strategy=("Monitoring leaf undersides and sticky traps. " "Predator mites present."),
            extra_data={
                "name": "Early Season Pest Scouting",
                "lace_bug_per_leaf": 0.5,
                "persea_mite_per_leaf": 1.2,
                "traps_checked": 30,
            },
            album=self._create_album("scouting"),
        )

        # 5: General - Windbreak Maintenance
        GeneralEvent.objects.create(
            history=prod,
            index=5,
            date=self._dt(2025, 11, 15),
            description=(
                "Windbreak tree maintenance along north and west perimeters. "
                "Pruned Monterey cypress and replaced 12 dead trees."
            ),
            created_by=user,
            performed_by="Miguel Ramirez",
            name="Windbreak Maintenance",
            activity_type="maintenance",
            activity_name="Windbreak pruning and replanting",
            duration="4",
            people_involved=3,
            observation=("North windbreak in good condition, west side needs " "gap filling"),
            extra_data={
                "trees_pruned": 45,
                "trees_replaced": 12,
                "species": "Monterey Cypress",
            },
        )

        # 6: Multispectral Drone Survey (electric)
        GeneralEvent.objects.create(
            history=prod,
            index=6,
            date=self._dt(2025, 11, 20),
            description=(
                "Multispectral drone survey of 15 ha avocado grove using "
                "DJI Matrice 350 RTK with MicaSense RedEdge-P sensor. "
                "NDVI, NDRE, and thermal imagery for canopy health assessment "
                "and irrigation uniformity mapping."
            ),
            created_by=user,
            performed_by="David Chen",
            name="Multispectral Drone Survey",
            activity_type="precision_ag",
            activity_name="Aerial multispectral imaging and analysis",
            duration="3",
            people_involved=2,
            observation=(
                "NDVI shows healthy canopy (0.78 avg). Block 7 replants "
                "establishing well. Thermal data identified 3 dry spots "
                "in south section for drip system inspection."
            ),
            extra_data={
                "drone": "DJI Matrice 350 RTK",
                "sensor": "MicaSense RedEdge-P",
                "altitude_m": 30,
                "overlap_pct": 75,
                "ndvi_avg": 0.78,
                "batteries_used": 6,
                "energy_kWh": 1.8,
                "fuel_type": "electric",
            },
        )

        # 7: Copper Hydroxide Fungicide (copper_fungicide subtype)
        ChemicalEvent.objects.create(
            history=prod,
            index=7,
            date=self._dt(2025, 12, 5),
            description=(
                "Copper hydroxide (Kocide 3000) preventive spray for "
                "anthracnose (Colletotrichum gloeosporioides) ahead of "
                "winter rains. 2.24 kg/ha rate via airblast sprayer."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FUNGICIDE,
            chemical_subtype="copper_fungicide",
            name="Preventive Anthracnose Spray",
            commercial_name="Kocide 3000 (copper hydroxide)",
            volume="33.6",
            concentration="46.1",
            area="15",
            area_unit="ha",
            way_of_application="ground_spray",
            application_method_structured="broadcast",
            application_timing="preventive",
            weather_conditions="overcast_humid",
            target_pest_disease="Anthracnose (Colletotrichum gloeosporioides)",
            organic_approved="organic",
            rei_hours=Decimal("48.0"),
            phi_days=Decimal("0.0"),
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("7.00"),
            application_fuel_unit="gal",
            extra_data={
                "rate_kg_ha": 2.24,
                "water_volume_L_ha": 1500,
                "spray_equipment": "Turbomist 400 airblast",
                "copper_metallic_pct": 30,
                "volume_unit": "kg",
            },
            album=self._create_album("fungicide"),
        )

        # 8: Mechanical Weed Cultivation (Tier 2 - recommended photo) (propane)
        ProductionEvent.objects.create(
            history=prod,
            index=8,
            date=self._dt(2026, 1, 5),
            description=(
                "Mechanical weed cultivation in row middles using "
                "propane-powered flame weeder. Chemical-free weed "
                "management between avocado rows. 2 passes across "
                "15 ha."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=ProductionEvent.CULTIVATION,
            name="Mechanical Flame Weeding",
            area_covered=Decimal("15.00"),
            area_unit="ha",
            fuel_consumed=Decimal("45.00"),
            fuel_unit="gal",
            fuel_type="propane",
            equipment_type="tractor",
            equipment_hours=Decimal("12.00"),
            production_efficiency="normal",
            observation=(
                "Flame weeding effective on annual grasses and small " "broadleaf weeds. No herbicide residue concerns."
            ),
            extra_data={
                "passes": 2,
                "weed_control_method": "Thermal (flame)",
                "equipment_name": "Red Dragon propane flame weeder",
                "row_middles_only": True,
            },
            album=self._create_album("cultivation"),
        )

        self.stdout.write("  Avocado Current: 9 events created")

    # -- Orange 2024-2025 FINISHED (20 events) --

    def _create_orange_finished_events(self, prod, user):
        # 0: Soil Test
        SoilManagementEvent.objects.create(
            history=prod,
            index=0,
            date=self._dt(2024, 10, 5),
            description=(
                "Pre-season soil analysis for orange orchard. Lab results: "
                "pH 6.8, organic matter 2.8%, clay loam texture. "
                "Good potassium, nitrogen needs supplementation."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=SoilManagementEvent.SOIL_TEST,
            name="Pre-Season Soil Analysis",
            soil_ph=Decimal("6.80"),
            organic_matter_percentage=Decimal("2.80"),
            soil_texture="clay_loam",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            test_results={
                "ph": 6.8,
                "organic_matter_pct": 2.8,
                "nitrogen_ppm": 38,
                "phosphorus_ppm": 42,
                "potassium_ppm": 310,
                "lab": "A&L Western Laboratories",
            },
            working_depth=Decimal("30.00"),
            depth_unit="cm",
            extra_data={"samples_collected": 32},
            album=self._create_album("soil_test"),
        )

        # 1: Composted Citrus Pulp (Tier 2 - recommended photo)
        SoilManagementEvent.objects.create(
            history=prod,
            index=1,
            date=self._dt(2024, 10, 20),
            description=(
                "Applied composted citrus pulp at 5 t/ha (100 tons total). "
                "Recycled from local juice processing. Builds organic matter "
                "and provides slow-release nutrients."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=SoilManagementEvent.COMPOSTING,
            name="Composted Citrus Pulp Application",
            amendment_type="Composted citrus pulp",
            amendment_amount="100000",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            fuel_consumed=Decimal("25.00"),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=Decimal("16.00"),
            equipment_used="John Deere 5075E with manure spreader",
            extra_data={
                "source": "Sunkist Growers, Oxnard",
                "amendment_source_supplier": "Sunkist Growers, Oxnard",
                "c_n_ratio": 22,
                "c_to_n_ratio": "22:1",
                "compost_temperature_reached_131f": "yes",
                "moisture_pct": 45,
            },
            album=self._create_album("composting"),
        )

        # 2: Organic Nitrogen Fertigation (Tier 1 - essential, 2 photos)
        ChemicalEvent.objects.create(
            history=prod,
            index=2,
            date=self._dt(2024, 11, 5),
            description=(
                "OMRI-listed fish emulsion applied via fertigation. "
                "First of four seasonal nitrogen applications for "
                "organic Valencia orange production. 200 L across 20 ha."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="organic_fertilizer",
            name="Organic Nitrogen Fertigation",
            commercial_name="Neptune's Harvest Organic Fish Fertilizer (2-4-1)",
            concentration="2-4-1",
            volume="200",
            area="20",
            area_unit="ha",
            way_of_application="fertigation",
            application_method_structured="drip",
            application_timing="harvest",
            weather_conditions="calm_dry",
            target_pest_disease="Nitrogen supplementation, Organic fertility program",
            organic_approved="omri_listed",
            application_fuel_type="electric",
            application_fuel_consumed=Decimal("3.50"),
            application_fuel_unit="kWh",
            extra_data={"rate_L_ha": 10, "cost_usd": 3600, "volume_unit": "L", "omri_listed": True},
            album=self._create_album("fertilizer"),
        )

        # 3: Citrus Pest Scouting Summary (Tier 2 - recommended photo) (16 trips over season)
        PestManagementEvent.objects.create(
            history=prod,
            index=3,
            date=self._dt(2024, 11, 20),
            description=(
                "Bi-weekly scouting program covering 20 hectares of Valencia "
                "orange orchard. 16 scouting trips from October 2024 through "
                "June 2025. Primary pests: citrus leafminer (Phyllocnistis "
                "citrella), California red scale (Aonidiella aurantii), "
                "citrus thrips, and Asian citrus psyllid. Pressure started "
                "medium in fall (leafminer on new flush at 15%), triggered "
                "Entrust SC organic treatment and parasitoid release. By spring, "
                "pest pressure dropped to low with biological controls "
                "established."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=PestManagementEvent.SCOUTING,
            pest_species=("Citrus leafminer (Phyllocnistis citrella), " "California red scale (Aonidiella aurantii)"),
            pest_pressure_level="Medium",
            action_threshold_met=True,
            beneficial_insects_used="planning",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            ipm_strategy=(
                "Integrated monitoring with sticky traps and visual "
                "inspection. Threshold exceeded for leafminer at 15% "
                "new leaf damage in November. Parasitoid wasp release "
                "established biological control by spring."
            ),
            extra_data={
                "name": "Citrus Pest Scouting Summary",
                "is_summary": True,
                "date_start": "2024-10-15",
                "date_end": "2025-06-15",
                "event_count": 16,
                "pest_species_observed": (
                    "Citrus leafminer, California red scale, " "Citrus thrips, Asian citrus psyllid"
                ),
                "average_pest_pressure": "moderate",
                "area_covered_total": 20,
                "area_unit": "ha",
                "economic_threshold_met": "true",
                "carbon_notes": ("Pest scouting is observational and does not " "directly produce emissions"),
                "carbon_impact": "zero",
            },
            album=self._create_album("scouting"),
        )

        # 4: Entrust SC Organic Pesticide (Tier 1 - essential, 2 photos)
        ChemicalEvent.objects.create(
            history=prod,
            index=4,
            date=self._dt(2024, 12, 1),
            description=(
                "OMRI-listed spinosad applied at petal fall for citrus "
                "leafminer control. Entrust SC is the organic alternative "
                "to synthetic Delegate WG. 1.5 L across 20 ha."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.PESTICIDE,
            chemical_subtype="organic_pesticide",
            name="Organic Citrus Leafminer Treatment",
            commercial_name="Entrust SC (spinosad 22.5%)",
            volume="1.5",
            concentration="22.5",
            area="20",
            area_unit="ha",
            way_of_application="ground_spray",
            target_pest_disease="Citrus leafminer (Phyllocnistis citrella)",
            organic_approved="omri_listed",
            rei_hours=Decimal("4.0"),
            phi_days=Decimal("1.0"),
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("8.00"),
            application_fuel_unit="gal",
            application_timing="post_emergence",
            weather_conditions="calm_dry",
            extra_data={
                "rate_fl_oz_acre": 6,
                "water_volume_L_ha": 1500,
                "spray_equipment": "Turbomist 400",
                "volume_unit": "L",
                "omri_listed": True,
            },
            album=self._create_album("pesticide"),
        )

        # 5: Irrigation Summary (24 cycles over the season)
        ProductionEvent.objects.create(
            history=prod,
            index=5,
            date=self._dt(2025, 1, 10),
            description=(
                "Micro-sprinkler irrigation system for 20ha Valencia orange "
                "orchard. 24 irrigation cycles from November 2024 through "
                "July 2025, totaling 5,400,000 gallons. Canal water source "
                "tested monthly for salinity. Electric pump consuming "
                "4,590 kWh total. Soil moisture probes at 3 depths guide "
                "scheduling, averaging 225,000 gal per cycle."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=ProductionEvent.IRRIGATION,
            name="Season Irrigation Program",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            fuel_consumed=Decimal("4590.00"),
            fuel_unit="kWh",
            fuel_type="electric",
            water_source="irrigation_canal",
            irrigation_method="micro_sprinkler",
            irrigation_depth=Decimal("3.00"),
            irrigation_depth_unit="inches",
            production_efficiency="normal",
            observation="Canal water tested - low salinity, good quality",
            extra_data={
                "is_summary": True,
                "date_start": "2024-11-01",
                "date_end": "2025-07-15",
                "event_count": 24,
                "water_volume_total": 5400000,
                "water_volume_unit": "gallons",
                "irrigation_depth": "3.0",
                "irrigation_depth_unit": "inches",
                "irrigation_method": "micro_sprinkler",
                "water_source": "irrigation_canal",
            },
        )

        # 6: Santa Ana Winds
        WeatherEvent.objects.create(
            history=prod,
            index=6,
            date=self._dt(2025, 2, 8),
            description=(
                "Santa Ana wind event with sustained gusts to 65 km/h. "
                "Minor branch damage in exposed western rows. "
                "Wind machines activated for orchard protection."
            ),
            created_by=user,
            performed_by="Miguel Ramirez",
            type=WeatherEvent.HIGH_WINDS,
            observation=(
                "Peak gusts 65 km/h from NE. 3 trees with significant "
                "branch damage in Row 12-15. Fruit drop estimated 2%."
            ),
            extra_data={
                "event_name": "Santa Ana Winds",
                "wind_speed": "65",
                "start_date": "2025-02-08T06:00",
                "end_date": "2025-02-09T00:00",
                "direction": "NE",
                "duration_hours": 18,
                "trees_damaged": 3,
                "fruit_drop_pct": 2,
            },
        )

        # 7: Santa Ana Cleanup
        GeneralEvent.objects.create(
            history=prod,
            index=7,
            date=self._dt(2025, 2, 10),
            description=(
                "Santa Ana wind damage cleanup. Removed broken branches, "
                "repositioned micro-sprinkler heads, repaired trellis wire."
            ),
            created_by=user,
            performed_by="Miguel Ramirez",
            name="Santa Ana Cleanup",
            activity_type="emergency",
            activity_name="Wind damage cleanup and repair",
            duration="16",
            people_involved=8,
            observation=("All damaged branches cleared, sprinkler system restored"),
            extra_data={
                "debris_tons": 2.5,
                "sprinklers_repositioned": 18,
                "trellis_repaired_m": 45,
            },
        )

        # 8: Organic Fish/Seaweed Fertigation
        ChemicalEvent.objects.create(
            history=prod,
            index=8,
            date=self._dt(2025, 3, 15),
            description=(
                "OMRI-listed fish/seaweed blend applied via fertigation "
                "for summer nitrogen supplementation. Combined with "
                "Maxicrop kelp foliar for micronutrient support."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="organic_fertilizer",
            name="Organic Summer Nitrogen Fertigation",
            commercial_name="Neptune's Harvest Fish & Seaweed Blend (2-3-1)",
            concentration="2-3-1",
            volume="200",
            area="20",
            area_unit="ha",
            way_of_application="fertigation",
            application_method_structured="drip",
            application_timing="fruit_development",
            weather_conditions="calm_dry",
            target_pest_disease="Nitrogen supplementation, Micronutrient support",
            organic_approved="omri_listed",
            application_fuel_type="electric",
            application_fuel_consumed=Decimal("3.00"),
            application_fuel_unit="kWh",
            extra_data={"rate_L_ha": 10, "cost_usd": 2400, "volume_unit": "L", "omri_listed": True},
            album=self._create_album("fertilizer"),
        )

        # 9: Beneficial Insect Release (Tier 1 - essential photo)
        PestManagementEvent.objects.create(
            history=prod,
            index=9,
            date=self._dt(2025, 4, 1),
            description=(
                "Released Aphytis melinus parasitic wasps at 50,000/ha "
                "for California red scale (Aonidiella aurantii) biological "
                "control. 1 million wasps total across 20 ha."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=PestManagementEvent.BENEFICIAL_RELEASE,
            pest_species="California red scale (Aonidiella aurantii)",
            beneficial_species="Aphytis melinus (parasitic wasp)",
            release_quantity="1,000,000 wasps (50,000/ha)",
            beneficial_insects_used="yes",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            ipm_strategy=(
                "Augmentative biological control. Aphytis melinus "
                "parasitizes red scale crawlers. Release timed to "
                "crawler emergence."
            ),
            extra_data={
                "name": "Beneficial Insect Release (Aphytis melinus)",
                "wasps_per_ha": 50000,
                "total_wasps": 1000000,
                "supplier": "Associates Insectary, Santa Paula CA",
                "release_method": "Cardboard release stations",
                "cost_usd": 3200,
            },
            album=self._create_album("beneficial_insects"),
        )

        # 10: Pruning (Tier 2 - recommended photo)
        ProductionEvent.objects.create(
            history=prod,
            index=10,
            date=self._dt(2025, 4, 20),
            description=(
                "Annual citrus pruning across 20 ha. Managed canopy height, "
                "removed suckers and dead wood. 18 gallons diesel, "
                "36 equipment hours."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.PRUNING,
            name="Annual Citrus Pruning",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            fuel_consumed=Decimal("18.00"),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_type="tractor",
            equipment_hours=Decimal("36.00"),
            production_efficiency="normal",
            observation=("Canopy opened for better light and spray penetration"),
            extra_data={"crew_size": 8, "biomass_chipped_tons": 12},
            album=self._create_album("pruning"),
        )

        # 11: Harvest Pass 1 (Tier 1 - essential photo)
        ProductionEvent.objects.create(
            history=prod,
            index=11,
            date=self._dt(2025, 5, 10),
            description=(
                "First harvest pass - 135,000 kg USDA Organic export "
                "quality Valencia oranges. Brix 12-14, excellent color."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.HARVESTING,
            name="Harvest Pass 1 - Early",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            yield_quantity=Decimal("135000.00"),
            yield_unit="kg",
            harvest_quality_grade="export_quality",
            production_efficiency="high",
            observation="Excellent Brix 12-14, size 72-88 count, USDA Organic certified",
            extra_data={
                "crew_size": 20,
                "bins_filled": 270,
                "brix_avg": 13.2,
            },
            album=self._create_album("orange_harvest"),
        )

        # 12: Harvest Pass 2 (Tier 1 - essential photo)
        ProductionEvent.objects.create(
            history=prod,
            index=12,
            date=self._dt(2025, 6, 5),
            description=(
                "Second harvest pass - 165,000 kg USDA Organic Grade A. " "Peak of season, highest daily picking rates."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.HARVESTING,
            name="Harvest Pass 2 - Peak",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            yield_quantity=Decimal("165000.00"),
            yield_unit="kg",
            harvest_quality_grade="grade_a",
            production_efficiency="high",
            observation="Peak organic harvest, 18 tons/day average",
            extra_data={"crew_size": 25, "bins_filled": 330},
            album=self._create_album("orange_harvest"),
        )

        # 13: Harvest Pass 3 (Tier 1 - essential photo)
        ProductionEvent.objects.create(
            history=prod,
            index=13,
            date=self._dt(2025, 7, 1),
            description=(
                "Third harvest pass - 120,000 kg USDA Organic domestic "
                "market quality. Late season, good juice content."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.HARVESTING,
            name="Harvest Pass 3 - Late Season",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            yield_quantity=Decimal("120000.00"),
            yield_unit="kg",
            harvest_quality_grade="domestic",
            production_efficiency="normal",
            observation="Late season organic cleanup, good juice content for local market",
            extra_data={
                "crew_size": 15,
                "bins_filled": 240,
                "juice_content_pct": 52,
            },
            album=self._create_album("orange_harvest"),
        )

        # 14: Equipment Inspection (migrated from EquipmentEvent → ProductionEvent EM)
        ProductionEvent.objects.create(
            history=prod,
            index=14,
            date=self._dt(2025, 7, 20),
            description=(
                "Annual inspection of Turbomist 400 canopy sprayer. "
                "Nozzle calibration, pump pressure test, tank integrity."
            ),
            created_by=user,
            performed_by="David Chen",
            type=ProductionEvent.EQUIPMENT_MAINTENANCE,
            name="Sprayer Annual Inspection",
            equipment_type="sprayer",
            equipment_operation_type="EI",
            equipment_hours=Decimal("4.00"),
            production_efficiency="high",
            observation="All nozzles calibrated to spec, pump pressure in range",
            extra_data={
                "equipment_name": "Turbomist 400 canopy sprayer",
                "maintenance_cost": 420.00,
                "nozzles_replaced": 4,
                "pump_pressure_psi": 150,
                "tank_capacity_gal": 400,
            },
        )

        # 15: USDA Organic Annual Certification (PSOC)
        BusinessEvent.objects.create(
            history=prod,
            index=15,
            date=self._dt(2025, 8, 1),
            description=(
                "Annual USDA Organic certification inspection by PSOC "
                "(California Certified Organic Farmers). All organic "
                "production practices, input records, and harvest "
                "documentation reviewed. Certification renewed for "
                "12 months."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=BusinessEvent.CERTIFICATION,
            name="USDA Organic Annual Certification",
            business_type="certification",
            certification_type="organic_usda",
            verification_status="verified",
            sustainability_practice="soil_health",
            verified_certifier_name="DEMO — Pacific Slope Organic Certifiers (sample data, not an accredited agent)",
            certificate_number="DEMO-ORG-0001",
            observation=(
                "Full organic system plan review. All inputs verified "
                "OMRI-listed. Buffer zones confirmed. No prohibited "
                "substances detected. Certification renewed through "
                "2026-07-31."
            ),
            extra_data={
                "audit_date": "2025-08-01",
                "auditor": "PSOC",
                "standard": "USDA NOP 7 CFR 205",
                "organic_system_plan": "approved",
                "prohibited_substances": "none_detected",
                "valid_until": "2026-07-31",
            },
        )

        # 16: Organic Herbicide - Suppress EC (electric sprayer)
        ChemicalEvent.objects.create(
            history=prod,
            index=16,
            date=self._dt(2025, 2, 20),
            description=(
                "Suppress EC (caprylic + capric acid) organic herbicide "
                "applied to row middles for broadleaf weed burndown. "
                "OMRI-listed, contact herbicide applied with electric "
                "ATV-mounted sprayer."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.HERBICIDE,
            chemical_subtype="organic_herbicide",
            name="Organic Weed Burndown",
            commercial_name="Suppress EC (caprylic/capric acid)",
            volume="200",
            concentration="47",
            area="20",
            area_unit="ha",
            way_of_application="ground_spray",
            application_method_structured="broadcast",
            application_timing="post_emergence",
            weather_conditions="calm_dry",
            target_pest_disease="Broadleaf weeds, Annual grasses",
            organic_approved="omri_listed",
            rei_hours=Decimal("0.0"),
            phi_days=Decimal("0.0"),
            application_fuel_type="electric",
            application_fuel_consumed=Decimal("4.50"),
            application_fuel_unit="kWh",
            extra_data={
                "rate_L_ha": 10,
                "water_volume_L_ha": 400,
                "spray_equipment": "Polaris Ranger EV with boom",
                "omri_listed": True,
                "volume_unit": "L",
            },
            album=self._create_album("herbicide"),
        )

        # 17: Kaolin Clay Organic Pest Deterrent (Tier 1 - essential, 2 photos)
        ChemicalEvent.objects.create(
            history=prod,
            index=17,
            date=self._dt(2025, 4, 10),
            description=(
                "Surround WP (kaolin clay) particle film applied for "
                "citrus thrips and sunburn protection. Creates white "
                "barrier on fruit surface. OMRI-listed organic treatment. "
                "56 kg/ha rate via airblast sprayer."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.PESTICIDE,
            chemical_subtype="organic_pesticide",
            name="Kaolin Clay Pest & Sunburn Protection",
            commercial_name="Surround WP (kaolin clay)",
            volume="1120",
            concentration="95",
            area="20",
            area_unit="ha",
            way_of_application="ground_spray",
            application_method_structured="broadcast",
            application_timing="fruit_development",
            weather_conditions="calm_dry",
            target_pest_disease="Citrus thrips, Sunburn prevention",
            organic_approved="omri_listed",
            rei_hours=Decimal("4.0"),
            phi_days=Decimal("0.0"),
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("10.00"),
            application_fuel_unit="gal",
            extra_data={
                "rate_kg_ha": 56,
                "water_volume_L_ha": 2000,
                "spray_equipment": "Turbomist 400 airblast",
                "omri_listed": True,
                "mode_of_action": "Physical barrier (particle film)",
                "volume_unit": "kg",
            },
            album=self._create_album("pesticide"),
        )

        # 18: Gypsum pH Adjustment
        SoilManagementEvent.objects.create(
            history=prod,
            index=18,
            date=self._dt(2024, 11, 10),
            description=(
                "Applied agricultural gypsum (calcium sulfate) at 2.5 t/ha "
                "to improve soil calcium levels and reduce sodium buildup "
                "from irrigation water. 50 tons total across 20 ha."
            ),
            created_by=user,
            performed_by="Carlos Mendoza",
            type=SoilManagementEvent.PH_ADJUSTMENT,
            name="Gypsum Calcium & Sodium Correction",
            # Plain words: amendment_type is free text and renders VERBATIM on the consumer
            # page, where "(CaSO4)" is a chemistry lesson nobody asked for.
            amendment_type="Agricultural gypsum",
            amendment_amount="50000",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            soil_ph=Decimal("6.80"),
            working_depth=Decimal("15.00"),
            depth_unit="cm",
            fuel_consumed=Decimal("20.00"),
            fuel_unit="gal",
            fuel_type="diesel",
            equipment_hours=Decimal("14.00"),
            equipment_used="John Deere 5075E with lime spreader",
            extra_data={
                "gypsum_source": "US Gypsum, Santa Barbara County",
                "target": "Reduce exchangeable sodium, boost calcium",
                "pre_sodium_ppm": 180,
                "target_sodium_ppm": 120,
            },
        )

        # 19: IPM Program Implementation - ACP Coordination
        PestManagementEvent.objects.create(
            history=prod,
            index=19,
            date=self._dt(2025, 3, 5),
            description=(
                "Coordinated Asian Citrus Psyllid (ACP) IPM program with "
                "Ventura County Agricultural Commissioner. Installed 40 "
                "ACP traps, released Tamarixia radiata parasitoid wasps, "
                "and implemented quarantine buffer protocols."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=PestManagementEvent.IPM_IMPLEMENTATION,
            pest_species="Asian citrus psyllid (Diaphorina citri)",
            pest_pressure_level="Low",
            beneficial_species="Tamarixia radiata (parasitoid wasp)",
            release_quantity="20,000 wasps (1,000/ha)",
            trap_count=40,
            action_threshold_met=False,
            beneficial_insects_used="yes",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            ipm_strategy=(
                "Integrated ACP management: perimeter trapping, biological "
                "control with Tamarixia radiata, visual inspection of new "
                "flush, coordination with county HLB prevention program."
            ),
            extra_data={
                "name": "IPM - ACP Coordination",
                "program": "Ventura County ACP Area-Wide Management",
                "coordinator": "Ventura County Ag Commissioner",
                "traps_per_ha": 2,
                "trap_type": "Yellow panel trap with ACP lure",
                "wasps_released": 20000,
                "supplier": "CDFA Biological Control Program",
                "hlb_detections": 0,
            },
            album=self._create_album("ipm"),
        )

        self.stdout.write("  Orange Finished: 20 events created")

    # -- Orange 2025-2026 IN PROGRESS (7 events) --

    def _create_orange_current_events(self, prod, user):
        # 0: Pre-season Soil Check
        SoilManagementEvent.objects.create(
            history=prod,
            index=0,
            date=self._dt(2025, 10, 5),
            description=(
                "Pre-season soil check - quick probe for moisture and pH. "
                "Conditions look good for fall planting season."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=SoilManagementEvent.SOIL_TEST,
            name="Pre-Season Soil Check",
            soil_ph=Decimal("6.75"),
            organic_matter_percentage=Decimal("2.90"),
            soil_texture="clay_loam",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            test_results={
                "ph": 6.75,
                "organic_matter_pct": 2.9,
                "moisture_status": "adequate",
            },
            extra_data={"samples_collected": 16, "quick_test": True},
            album=self._create_album("soil_test"),
        )

        # 1: Organic Bloom Support Fertilizer (Tier 1 - essential, 2 photos)
        ChemicalEvent.objects.create(
            history=prod,
            index=1,
            date=self._dt(2025, 10, 25),
            description=(
                "OMRI-listed organic citrus fertilizer blend applied " "at bloom for phosphorus support and fruit set."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FERTILIZER,
            chemical_subtype="organic_fertilizer",
            name="Organic Bloom Support Fertilization",
            commercial_name="Dr. Earth Organic Citrus Fertilizer (5-5-2)",
            concentration="5-5-2",
            volume="2400",
            area="20",
            area_unit="ha",
            way_of_application="broadcast",
            application_method_structured="broadcast",
            application_timing="flowering",
            weather_conditions="calm_dry",
            target_pest_disease="Bloom support, Phosphorus supplementation",
            organic_approved="omri_listed",
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("10.00"),
            application_fuel_unit="L",
            extra_data={"rate_kg_ha": 120, "cost_usd": 3840, "volume_unit": "kg", "omri_listed": True},
            album=self._create_album("fertilizer"),
        )

        # 2: Frost Warning
        WeatherEvent.objects.create(
            history=prod,
            index=2,
            date=self._dt(2025, 12, 15),
            description=(
                "Overnight frost warning - temperatures expected to drop "
                "to -1C (30F). Wind machines activated from 2am to 7am. "
                "No significant damage."
            ),
            created_by=user,
            performed_by="Miguel Ramirez",
            type=WeatherEvent.FROST,
            observation=(
                "Min temp -1C at 5:30am. Wind machines ran 5 hours. " "No visible frost damage to fruit or flowers."
            ),
            extra_data={
                "event_name": "Frost Warning",
                "lower_temperature": "-1",
                "start_date": "2025-12-15T02:00",
                "end_date": "2025-12-15T07:00",
                "wind_machine_hours": 5,
                "wind_machines_count": 4,
                "fuel_consumed_gal": 40,
                "damage": "None",
            },
        )

        # 3: Citrus Thrips Scouting
        PestManagementEvent.objects.create(
            history=prod,
            index=3,
            date=self._dt(2026, 1, 10),
            description=(
                "Early season scouting for citrus thrips (Scirtothrips "
                "citri). Low pressure, well below treatment threshold. "
                "Predatory mites naturally controlling population."
            ),
            created_by=user,
            performed_by="Ana Torres",
            type=PestManagementEvent.SCOUTING,
            pest_species="Citrus thrips (Scirtothrips citri)",
            pest_pressure_level="Low",
            action_threshold_met=False,
            beneficial_insects_used="yes",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            ipm_strategy=(
                "Sticky trap monitoring and visual inspection of new "
                "flush. Predatory mites (Euseius tularensis) maintaining "
                "control."
            ),
            extra_data={
                "name": "Citrus Thrips Scouting",
                "thrips_per_tap": 1.5,
                "treatment_threshold": 8,
                "traps_checked": 40,
            },
            album=self._create_album("scouting"),
        )

        # 4: Sulfur Dust Fungicide (Tier 1 - essential, 2 photos) (sulfur_fungicide)
        ChemicalEvent.objects.create(
            history=prod,
            index=4,
            date=self._dt(2026, 1, 15),
            description=(
                "Micronized sulfur dust (Microthiol Disperss) application "
                "for citrus rust mite (Phyllocoptruta oleivora) and powdery "
                "mildew prevention. 6.7 kg/ha rate via tractor-mounted "
                "duster. OMRI-listed for organic programs."
            ),
            created_by=user,
            performed_by="Roberto Silva",
            type=ChemicalEvent.FUNGICIDE,
            chemical_subtype="sulfur_fungicide",
            name="Sulfur Dust - Mite & Mildew Prevention",
            commercial_name="Microthiol Disperss (micronized sulfur)",
            volume="134",
            concentration="80",
            area="20",
            area_unit="ha",
            way_of_application="ground_spray",
            application_method_structured="broadcast",
            application_timing="fruit_development",
            weather_conditions="calm_dry",
            target_pest_disease=("Citrus rust mite (Phyllocoptruta oleivora), " "Powdery mildew"),
            organic_approved="omri_listed",
            rei_hours=Decimal("24.0"),
            phi_days=Decimal("0.0"),
            application_fuel_type="diesel",
            application_fuel_consumed=Decimal("12.00"),
            application_fuel_unit="L",
            extra_data={
                "rate_kg_ha": 6.7,
                "spray_equipment": "Tractor-mounted duster",
                "omri_listed": True,
                "caution": "Do not apply when temps > 35C",
                "volume_unit": "kg",
            },
            album=self._create_album("fungicide"),
        )

        # 5: Valencia Orange Thinning (manual, no fuel)
        ProductionEvent.objects.create(
            history=prod,
            index=5,
            date=self._dt(2026, 2, 1),
            description=(
                "Hand thinning of excess fruit on heavily loaded Valencia "
                "orange trees. Removed approximately 15% of fruitlets to "
                "improve remaining fruit size and reduce alternate bearing. "
                "Manual work with pruning shears, no equipment."
            ),
            created_by=user,
            performed_by="Jose Garcia",
            type=ProductionEvent.THINNING,
            name="Valencia Orange Hand Thinning",
            area_covered=Decimal("20.00"),
            area_unit="ha",
            production_efficiency="normal",
            observation=(
                "Removed 15% of fruitlets from heavy-bearing trees. "
                "Focus on interior canopy clusters to improve air "
                "circulation and fruit size."
            ),
            extra_data={
                "crew_size": 12,
                "days_to_complete": 4,
                "fruit_removed_pct": 15,
                "method": "Hand thinning with pruning shears",
                "target_fruit_per_tree": 400,
            },
        )

        # 6: Worker Safety Training
        GeneralEvent.objects.create(
            history=prod,
            index=6,
            date=self._dt(2026, 2, 10),
            description=(
                "Annual Worker Protection Standard (WPS) and heat illness "
                "prevention training for all field workers. Covers pesticide "
                "safety, PPE requirements, REI/PHI compliance, heat stress "
                "recognition, and emergency procedures. Bilingual (EN/ES)."
            ),
            created_by=user,
            performed_by="Ana Torres",
            name="Annual Worker Safety Training",
            activity_type="training",
            activity_name="WPS and heat illness prevention certification",
            duration="6",
            people_involved=22,
            observation=(
                "All 22 field workers completed training and received "
                "updated WPS cards. Included hands-on PPE fitting and "
                "emergency response drill."
            ),
            extra_data={
                "training_topics": [
                    "Worker Protection Standard (EPA)",
                    "Heat Illness Prevention (Cal/OSHA)",
                    "PPE Selection and Use",
                    "Emergency First Aid",
                ],
                "certifications_issued": 22,
                "language": "Bilingual EN/ES",
                "trainer": "Ventura County Farm Bureau",
            },
        )

        self.stdout.write("  Orange Current: 7 events created")
