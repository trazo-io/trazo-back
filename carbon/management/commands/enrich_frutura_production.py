"""
Enrich Frutura Production 289 (Premium Valencia Orange) with realistic events.

Adds 14 new events representing ~86 additional farm activities via aggregate
summaries and individual events. Brings total from 12 to 26 visible events
representing ~98 actual farm activities across a full annual citrus cycle.

Usage:
    poetry run python manage.py enrich_frutura_production
    poetry run python manage.py enrich_frutura_production --dry-run
"""

import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from history.models import (
    ChemicalEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)

PRODUCTION_ID = 289


class Command(BaseCommand):
    help = "Enrich Frutura production 289 with realistic Valencia orange events"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without making changes",
        )
        parser.add_argument(
            "--production-id",
            type=int,
            default=PRODUCTION_ID,
            help="Production ID to enrich (default: 289)",
        )

    def handle(self, *args, **options):
        production_id = options["production_id"]
        dry_run = options["dry_run"]

        try:
            production = History.objects.get(id=production_id)
        except History.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Production {production_id} not found"))
            return

        self.stdout.write(self.style.SUCCESS(f"Enriching production {production_id}: {production.name}"))

        # Count existing events
        existing = self._count_events(production)
        self.stdout.write(f"  Existing events: {existing}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))
            self._show_plan()
            return

        created = self._create_events(production)
        new_total = self._count_events(production)
        self.stdout.write(self.style.SUCCESS(f"Created {created} new events. Total: {new_total}"))

    def _count_events(self, production):
        return (
            ProductionEvent.objects.filter(history=production).count()
            + ChemicalEvent.objects.filter(history=production).count()
            + PestManagementEvent.objects.filter(history=production).count()
            + SoilManagementEvent.objects.filter(history=production).count()
            + WeatherEvent.objects.filter(history=production).count()
        )

    def _show_plan(self):
        events = [
            ("ProductionEvent IR", "Aggregate Irrigation Program (38 sessions)"),
            ("PestManagementEvent SC", "Aggregate Pest Monitoring (36 trips)"),
            ("ChemicalEvent FE", "YaraMila 15-15-15 Second App"),
            ("ChemicalEvent FE", "Calcium Nitrate Post-Harvest Recovery"),
            ("ChemicalEvent FE", "Micronutrient Foliar Mix"),
            ("ChemicalEvent PE", "Spirotetramat Aphid Control"),
            ("ProductionEvent PR", "Summer Maintenance Pruning"),
            ("ProductionEvent HA", "Second Harvest Pick"),
            ("ProductionEvent HA", "Third Harvest Pick (Final)"),
            ("ProductionEvent EM", "Irrigation System Inspection"),
            ("SoilManagementEvent CC", "Cover Crop Planting - Ryegrass"),
            ("SoilManagementEvent TI", "Cover Crop Mowing"),
            ("WeatherEvent FR", "Winter Frost Monitoring"),
            ("PestManagementEvent BR", "Beneficial Insect Release"),
        ]
        for i, (model, desc) in enumerate(events, 1):
            self.stdout.write(f"  {i:2d}. [{model}] {desc}")

    @transaction.atomic
    def _create_events(self, production):
        """Create all 14 new events in a single transaction."""
        # Get user from existing events on this production
        existing_event = (
            ProductionEvent.objects.filter(history=production, created_by__isnull=False).first()
            or ChemicalEvent.objects.filter(history=production, created_by__isnull=False).first()
        )
        user = existing_event.created_by if existing_event else None
        created = 0

        # Helper to make timezone-aware dates
        def make_date(year, month, day):
            return timezone.make_aware(datetime.datetime(year, month, day, 8, 0, 0))

        # ──────────────────────────────────────────────
        # 1. Aggregate Irrigation Program (38 sessions)
        # ──────────────────────────────────────────────
        ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="IR",
            description="Annual Drip & Flood Irrigation Program",
            observation=(
                "Comprehensive irrigation management combining drip irrigation "
                "for young trees and micro-sprinkler systems for mature Valencia "
                "orange blocks. Soil moisture sensors guide scheduling every 7-14 "
                "days depending on season and rainfall."
            ),
            date=make_date(2025, 10, 1),
            index=100,
            name="Annual Drip & Flood Irrigation Program",
            irrigation_method="drip",
            area_covered=Decimal("12.5"),
            area_unit="ha",
            water_source="well_groundwater",
            fuel_type="electric",
            extra_data={
                "is_summary": True,
                "event_count": 38,
                "date_start": "2025-05-01",
                "date_end": "2026-02-15",
                "water_volume_total": 2400000,
                "water_volume_unit": "gallons",
                "irrigation_schedule": "Every 7-14 days, adjusted by soil moisture sensors",
                "system_types": ["drip", "micro-sprinkler"],
                "sensor_count": 8,
                "water_efficiency": "92% delivery efficiency",
            },
        )
        created += 1
        self.stdout.write("  + Aggregate Irrigation Program (38 sessions)")

        # ──────────────────────────────────────────────
        # 2. Aggregate Pest Scouting Program (36 trips)
        # ──────────────────────────────────────────────
        PestManagementEvent.objects.create(
            history=production,
            created_by=user,
            type="SC",
            description=(
                "Weekly Pest & Disease Monitoring Program - Systematic weekly "
                "scouting across all citrus blocks monitoring for Asian Citrus "
                "Psyllid (HLB vector), Citrus Leafminer, Green Citrus Aphid, "
                "California Red Scale, and Citrus Thrips. Yellow sticky traps "
                "and pheromone traps deployed at 50m intervals."
            ),
            date=make_date(2025, 10, 15),
            index=101,
            pest_species=(
                "Asian Citrus Psyllid, Citrus Leafminer, " "Green Citrus Aphid, California Red Scale, Citrus Thrips"
            ),
            pest_pressure_level="Low",
            area_covered=Decimal("12.5"),
            area_unit="ha",
            trap_count=24,
            action_threshold_met=False,
            extra_data={
                "is_summary": True,
                "event_count": 36,
                "date_start": "2025-06-01",
                "date_end": "2026-02-10",
                "pest_species_observed": (
                    "Asian Citrus Psyllid, Citrus Leafminer, " "Green Citrus Aphid, California Red Scale, Citrus Thrips"
                ),
                "average_pest_pressure": "low",
                "monitoring_method": "Visual inspection + sticky traps + pheromone traps",
                "trap_density": "24 traps across 12.5 ha",
                "hlb_status": "No HLB detected - all psyllid samples negative",
            },
        )
        created += 1
        self.stdout.write("  + Aggregate Pest Monitoring (36 trips)")

        # ──────────────────────────────────────────────
        # 3. YaraMila 15-15-15 Second Application
        # ──────────────────────────────────────────────
        ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            type="FE",
            description="Second NPK application - fruit swell stage",
            observation=(
                "Balanced NPK application during fruit swell stage to support "
                "Valencia orange size development. Applied via broadcast spreader "
                "with soil incorporation."
            ),
            date=make_date(2025, 10, 1),
            index=102,
            commercial_name="YaraMila Complex 15-15-15",
            chemical_subtype="synthetic_fertilizer",
            volume="200 kg",
            concentration="15-15-15",
            area="12.5 ha",
            way_of_application="Broadcast spreader with incorporation",
            nitrogen_percentage=Decimal("15.0"),
            phosphorus_percentage=Decimal("15.0"),
            potassium_percentage=Decimal("15.0"),
            application_method_structured="broadcast",
            extra_data={
                "growth_stage": "fruit_swell",
                "application_rate": "16 kg/ha",
                "soil_moisture_at_application": "adequate",
            },
        )
        created += 1
        self.stdout.write("  + YaraMila 15-15-15 Second Application")

        # ──────────────────────────────────────────────
        # 4. Calcium Nitrate Post-Harvest Recovery
        # ──────────────────────────────────────────────
        ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            type="FE",
            description="Post-harvest recovery fertilization via drip fertigation",
            observation=(
                "Calcium nitrate applied through drip fertigation system to "
                "replenish tree nutrient reserves after main harvest. Calcium "
                "supports cell wall integrity for next season's fruit set."
            ),
            date=make_date(2025, 6, 15),
            index=103,
            commercial_name="Calcium Nitrate (Ca(NO3)2)",
            chemical_subtype="synthetic_fertilizer",
            volume="150 kg",
            concentration="15.5% N, 26.3% CaO",
            area="12.5 ha",
            way_of_application="Drip fertigation",
            nitrogen_percentage=Decimal("15.5"),
            phosphorus_percentage=Decimal("0"),
            potassium_percentage=Decimal("0"),
            application_method_structured="drip",
            extra_data={
                "growth_stage": "post_harvest_recovery",
                "calcium_content_percent": 26.3,
                "fertigation_duration_hours": 4,
                "application_rate": "12 kg/ha",
            },
        )
        created += 1
        self.stdout.write("  + Calcium Nitrate Post-Harvest Recovery")

        # ──────────────────────────────────────────────
        # 5. Micronutrient Foliar Spray
        # ──────────────────────────────────────────────
        ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            type="FE",
            description="Micronutrient foliar spray - zinc, manganese, iron chelate",
            observation=(
                "Foliar application of chelated micronutrients to correct "
                "deficiencies identified in leaf tissue analysis. Zinc sulfate, "
                "manganese sulfate, and iron chelate (EDDHA) applied at dawn "
                "for optimal leaf absorption."
            ),
            date=make_date(2025, 3, 15),
            index=104,
            commercial_name="Micronutrient Foliar Mix (Zn/Mn/Fe)",
            chemical_subtype="synthetic_fertilizer",
            volume="15 L",
            concentration="Zn 2%, Mn 1.5%, Fe-EDDHA 0.5%",
            area="12.5 ha",
            way_of_application="Foliar spray - airblast sprayer",
            application_method_structured="foliar",
            extra_data={
                "growth_stage": "pre_bloom",
                "micronutrients": {
                    "zinc_sulfate_percent": 2.0,
                    "manganese_sulfate_percent": 1.5,
                    "iron_eddha_percent": 0.5,
                },
                "leaf_tissue_analysis_triggered": True,
                "application_timing": "Early morning (6-8 AM)",
                "spray_volume": "1500 L/ha",
            },
        )
        created += 1
        self.stdout.write("  + Micronutrient Foliar Spray")

        # ──────────────────────────────────────────────
        # 6. Spirotetramat Aphid Control
        # ──────────────────────────────────────────────
        ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            type="PE",
            description="Targeted aphid control - spring population spike",
            observation=(
                "Spirotetramat (Movento 240 SC) applied as foliar spray to "
                "control Green Citrus Aphid population that exceeded action "
                "threshold during spring flush. Systemic activity provides "
                "extended protection during new growth period."
            ),
            date=make_date(2025, 11, 1),
            index=105,
            commercial_name="Spirotetramat (Movento) 240 SC",
            chemical_subtype="synthetic_pesticide",
            volume="0.75 L/ha",
            concentration="240 g/L spirotetramat",
            area="12.5 ha",
            way_of_application="Foliar spray - airblast sprayer",
            target_pest_disease="Green Citrus Aphid (Aphis spiraecola)",
            phi_days=Decimal("7"),
            rei_hours=Decimal("12"),
            extra_data={
                "active_ingredient": "Spirotetramat",
                "mode_of_action": "Lipid biosynthesis inhibitor (IRAC Group 23)",
                "pest_pressure_at_application": "medium",
                "threshold_trigger": "15% of shoots with aphid colonies",
                "spray_volume": "1500 L/ha",
            },
        )
        created += 1
        self.stdout.write("  + Spirotetramat Aphid Control")

        # ──────────────────────────────────────────────
        # 7. Summer Maintenance Pruning
        # ──────────────────────────────────────────────
        ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="PR",
            description="Summer maintenance pruning - water sprout removal",
            observation=(
                "Selective removal of water sprouts and interior canopy "
                "thinning to improve air circulation and light penetration. "
                "Pruning wounds treated with copper paste to prevent "
                "Phytophthora infection."
            ),
            date=make_date(2025, 12, 15),
            index=106,
            name="Summer Maintenance Pruning",
            area_covered=Decimal("2.5"),
            area_unit="ha",
            fuel_consumed=Decimal("4.0"),
            fuel_unit="L",
            fuel_type="diesel",
            equipment_hours=Decimal("8.0"),
            extra_data={
                "pruning_type": "maintenance",
                "tasks": [
                    "Water sprout removal",
                    "Interior canopy thinning",
                    "Dead wood removal",
                    "Wound treatment with copper paste",
                ],
                "biomass_removed_kg": 350,
                "biomass_disposition": "Chipped and composted on-site",
            },
        )
        created += 1
        self.stdout.write("  + Summer Maintenance Pruning")

        # ──────────────────────────────────────────────
        # 8. Second Harvest Pick
        # ──────────────────────────────────────────────
        ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="HA",
            description="Second harvest pick - export quality Valencia oranges",
            observation=(
                "Second selective harvest of export-grade Valencia oranges. "
                "Brix reading 11.8 with acid ratio 12:1. Hand-picked into "
                "field bins, field-graded and transported to packhouse within "
                "4 hours of harvest."
            ),
            date=make_date(2026, 1, 25),
            index=107,
            name="Second Harvest Pick - Export Quality",
            yield_quantity=Decimal("12000"),
            yield_unit="kg",
            area_covered=Decimal("5.0"),
            area_unit="ha",
            fuel_consumed=Decimal("8.0"),
            fuel_unit="L",
            fuel_type="diesel",
            harvest_quality_grade="export_quality",
            extra_data={
                "harvest_method": "hand_picking",
                "brix_level": 11.8,
                "acid_ratio": "12:1",
                "fruit_size_mm": "70-80",
                "color_break_percent": 85,
                "field_to_packhouse_hours": 4,
                "pickers_count": 12,
            },
        )
        created += 1
        self.stdout.write("  + Second Harvest Pick (Export Quality)")

        # ──────────────────────────────────────────────
        # 9. Third Harvest Pick (Final)
        # ──────────────────────────────────────────────
        ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="HA",
            description="Third harvest pick (final) - processing grade",
            observation=(
                "Final harvest strip of remaining fruit for juice processing "
                "market. Lower brix (10.5) but excellent juice yield. "
                "Completes the 2025-2026 Valencia orange season."
            ),
            date=make_date(2026, 2, 8),
            index=108,
            name="Third Harvest Pick - Processing Grade",
            yield_quantity=Decimal("8000"),
            yield_unit="kg",
            area_covered=Decimal("12.5"),
            area_unit="ha",
            fuel_consumed=Decimal("12.0"),
            fuel_unit="L",
            fuel_type="diesel",
            harvest_quality_grade="grade_b",
            extra_data={
                "harvest_method": "hand_picking",
                "brix_level": 10.5,
                "destination": "Juice processing",
                "final_season_harvest": True,
                "total_season_yield_kg": 38000,
            },
        )
        created += 1
        self.stdout.write("  + Third Harvest Pick (Processing Grade)")

        # ──────────────────────────────────────────────
        # 10. Irrigation System Inspection
        # ──────────────────────────────────────────────
        ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="EM",
            description="Pre-season irrigation system inspection and maintenance",
            observation=(
                "Annual pre-season inspection of drip irrigation system. "
                "Replaced 45 clogged emitters, flushed lateral lines, "
                "calibrated pressure regulators, and tested soil moisture "
                "sensor array. System cleared for 2025-2026 season."
            ),
            date=make_date(2025, 8, 1),
            index=109,
            name="Irrigation System Inspection",
            equipment_hours=Decimal("6.0"),
            equipment_type="sprayer",
            equipment_operation_type="MN",
            fuel_type="none",
            extra_data={
                "maintenance_tasks": [
                    "Emitter replacement (45 units)",
                    "Lateral line flushing",
                    "Pressure regulator calibration",
                    "Soil moisture sensor testing",
                    "Filter cleaning",
                ],
                "emitters_replaced": 45,
                "system_pressure_psi": 25,
                "flow_rate_test": "Within 5% of design specification",
            },
        )
        created += 1
        self.stdout.write("  + Irrigation System Inspection")

        # ──────────────────────────────────────────────
        # 11. Cover Crop Planting - Ryegrass
        # ──────────────────────────────────────────────
        SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            type="CC",
            description=(
                "Cover crop planting - Annual Ryegrass between rows. "
                "Lolium multiflorum planted between citrus rows for erosion "
                "control, organic matter building, and beneficial insect "
                "habitat. Seeded at 25 kg/ha using no-till drill."
            ),
            date=make_date(2025, 5, 15),
            index=110,
            name="Cover Crop Planting - Annual Ryegrass",
            amendment_type="Annual Ryegrass (Lolium multiflorum) seed",
            amendment_amount="25 kg/ha",
            area_covered=Decimal("8.0"),
            area_unit="ha",
            fuel_consumed=Decimal("5.0"),
            fuel_unit="L",
            fuel_type="diesel",
            extra_data={
                "species": "Lolium multiflorum (Annual Ryegrass)",
                "seeding_rate_kg_ha": 25,
                "planting_method": "No-till drill",
                "row_position": "Between citrus rows",
                "expected_benefits": [
                    "Erosion control",
                    "Organic matter addition",
                    "Beneficial insect habitat",
                    "Weed suppression",
                ],
            },
        )
        created += 1
        self.stdout.write("  + Cover Crop Planting (Ryegrass)")

        # ──────────────────────────────────────────────
        # 12. Cover Crop Mowing
        # ──────────────────────────────────────────────
        SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            type="TI",
            description=(
                "Cover crop mowing - row middle maintenance. Flail mowing "
                "to maintain 4-inch height. Clippings left as mulch for "
                "moisture retention and organic matter cycling."
            ),
            date=make_date(2025, 4, 1),
            index=111,
            name="Cover Crop Mowing",
            area_covered=Decimal("8.0"),
            area_unit="ha",
            fuel_consumed=Decimal("6.0"),
            fuel_unit="L",
            fuel_type="diesel",
            equipment_hours=Decimal("4.0"),
            extra_data={
                "mowing_height_inches": 4,
                "equipment": "Flail mower",
                "clipping_disposition": "Left as mulch in place",
                "cover_crop_species": "Annual Ryegrass",
            },
        )
        created += 1
        self.stdout.write("  + Cover Crop Mowing")

        # ──────────────────────────────────────────────
        # 13. Winter Frost Monitoring
        # ──────────────────────────────────────────────
        WeatherEvent.objects.create(
            history=production,
            created_by=user,
            type="FR",
            description="Winter frost monitoring - overnight temperature watch",
            observation=(
                "Overnight frost monitoring activated when forecast predicted "
                "temperatures dropping to 1C. Field thermometers confirmed "
                "minimum of 1.2C at canopy level. Wind machines placed on "
                "standby but not activated. No visible frost damage to fruit "
                "or foliage. Irrigation system ready for frost protection "
                "if temperatures had dropped below 0C."
            ),
            date=make_date(2025, 7, 15),
            index=112,
            extra_data={
                "minimum_temperature_celsius": 1.2,
                "forecast_low_celsius": 1.0,
                "duration_hours": 6,
                "monitoring_period": "22:00 - 04:00",
                "wind_machines": "On standby, not activated",
                "frost_damage": "None observed",
                "protection_measures_available": [
                    "Wind machines",
                    "Overhead sprinkler irrigation",
                    "Smudge pots (emergency)",
                ],
            },
        )
        created += 1
        self.stdout.write("  + Winter Frost Monitoring")

        # ──────────────────────────────────────────────
        # 14. Beneficial Insect Release
        # ──────────────────────────────────────────────
        PestManagementEvent.objects.create(
            history=production,
            created_by=user,
            type="BR",
            description=(
                "Beneficial insect release - Tamarixia radiata for HLB "
                "biocontrol. 5,000 parasitoid wasps released targeting "
                "Asian Citrus Psyllid (ACP), primary vector of "
                "Huanglongbing. Released at dawn across orchard perimeter "
                "and interior hotspots identified during scouting."
            ),
            date=make_date(2025, 12, 1),
            index=113,
            pest_species="Asian Citrus Psyllid (Diaphorina citri)",
            beneficial_species="Tamarixia radiata",
            release_quantity="5,000 parasitoid wasps",
            pest_pressure_level="Low",
            beneficial_insects_used="yes",
            area_covered=Decimal("12.5"),
            area_unit="ha",
            extra_data={
                "biocontrol_target": "Asian Citrus Psyllid (HLB vector)",
                "parasitoid_species": "Tamarixia radiata",
                "release_quantity": 5000,
                "release_method": "Dawn release at orchard perimeter + interior hotspots",
                "hlb_prevention_program": True,
                "expected_parasitism_rate": "40-60% within 4 weeks",
            },
        )
        created += 1
        self.stdout.write("  + Beneficial Insect Release (Tamarixia radiata)")

        return created
