from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from carbon.models import CropType, EventTemplate, ProductionTemplate


class Command(BaseCommand):
    help = "Validate MVP readiness for Iowa and California launch regions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--region",
            type=str,
            choices=["iowa", "california", "all"],
            default="all",
            help="Target region for MVP validation (iowa, california, or all)",
        )
        parser.add_argument("--detailed", action="store_true", help="Show detailed breakdown of each crop's status")

    def handle(self, *args, **options):
        """Validate MVP readiness for launch regions"""

        self.stdout.write(self.style.SUCCESS("🚀 VALIDATING MVP READINESS FOR TRAZO LAUNCH"))
        self.stdout.write("=" * 60)

        region = options.get("region", "all")
        detailed = options.get("detailed", False)

        overall_readiness = 0
        region_count = 0

        if region == "all" or region == "iowa":
            iowa_readiness = self.validate_iowa_readiness(detailed)
            overall_readiness += iowa_readiness
            region_count += 1

        if region == "all" or region == "california":
            california_readiness = self.validate_california_readiness(detailed)
            overall_readiness += california_readiness
            region_count += 1

        # Overall MVP assessment
        avg_readiness = overall_readiness / region_count if region_count > 0 else 0

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("📊 OVERALL MVP READINESS ASSESSMENT")
        self.stdout.write("=" * 60)

        if avg_readiness >= 95:
            status_color = self.style.SUCCESS
            status_message = "✅ READY FOR PRODUCTION LAUNCH"
        elif avg_readiness >= 85:
            status_color = self.style.WARNING
            status_message = "⚠️  MOSTLY READY - MINOR FIXES NEEDED"
        elif avg_readiness >= 70:
            status_color = self.style.WARNING
            status_message = "⚠️  NEEDS WORK BEFORE LAUNCH"
        else:
            status_color = self.style.ERROR
            status_message = "❌ NOT READY FOR PRODUCTION"

        self.stdout.write(status_color(f"{status_message} ({avg_readiness:.1f}% ready)"))

        self.provide_launch_recommendations(avg_readiness, region)

    def validate_iowa_readiness(self, detailed=False):
        """Validate Iowa corn belt readiness"""

        self.stdout.write(self.style.SUCCESS("🌽 IOWA CORN BELT READINESS"))
        self.stdout.write("-" * 40)

        iowa_crops = [
            ("Corn (Field)", {"usda_min": 800, "usda_max": 1200}),
            ("Soybeans", {"usda_min": 600, "usda_max": 900}),
        ]

        iowa_scores = []

        for crop_name, targets in iowa_crops:
            readiness = self.validate_crop_readiness(crop_name, targets, detailed)
            iowa_scores.append(readiness)

        # Iowa-specific features
        conservation_features = self.check_conservation_features()
        consumer_transparency = self.check_consumer_transparency()

        iowa_avg = sum(iowa_scores) / len(iowa_scores) if iowa_scores else 0
        feature_bonus = (conservation_features + consumer_transparency) / 2

        total_iowa = (iowa_avg * 0.8) + (feature_bonus * 0.2)  # 80% crops, 20% features

        self.stdout.write(f"📈 Conservation practices: {conservation_features:.1f}% ready")
        self.stdout.write(f"📱 Consumer transparency: {consumer_transparency:.1f}% ready")
        self.stdout.write(self.style.SUCCESS(f"🏆 IOWA OVERALL: {total_iowa:.1f}% ready"))

        return total_iowa

    def validate_california_readiness(self, detailed=False):
        """Validate California specialty crops readiness"""

        self.stdout.write(self.style.SUCCESS("\n🌿 CALIFORNIA CENTRAL VALLEY READINESS"))
        self.stdout.write("-" * 40)

        california_crops = [
            ("Almonds", {"usda_min": 800, "usda_max": 1200}),
            ("Citrus (Oranges)", {"usda_min": 500, "usda_max": 800}),
            ("Avocados", {"usda_min": 600, "usda_max": 900}),
        ]

        california_scores = []

        for crop_name, targets in california_crops:
            readiness = self.validate_crop_readiness(crop_name, targets, detailed)
            california_scores.append(readiness)

        # California-specific features
        irrigation_features = self.check_irrigation_features()
        water_efficiency = self.check_water_efficiency()

        california_avg = sum(california_scores) / len(california_scores) if california_scores else 0
        feature_bonus = (irrigation_features + water_efficiency) / 2

        total_california = (california_avg * 0.8) + (feature_bonus * 0.2)  # 80% crops, 20% features

        self.stdout.write(f"💧 Irrigation efficiency: {irrigation_features:.1f}% ready")
        self.stdout.write(f"🌱 Water management: {water_efficiency:.1f}% ready")
        self.stdout.write(self.style.SUCCESS(f"🏆 CALIFORNIA OVERALL: {total_california:.1f}% ready"))

        return total_california

    def validate_crop_readiness(self, crop_name, targets, detailed=False):
        """Validate individual crop readiness"""

        try:
            crop_type = CropType.objects.get(name=crop_name, is_active=True)
            template = ProductionTemplate.objects.filter(crop_type=crop_type).first()

            if not template:
                self.stdout.write(f"❌ {crop_name}: No production template")
                return 0

            # Check carbon footprint compliance
            total_carbon = (
                EventTemplate.objects.filter(production_template=template).aggregate(total=Sum("carbon_impact"))[
                    "total"
                ]
                or 0
            )

            usda_min = targets["usda_min"]
            usda_max = targets["usda_max"]

            if usda_min <= total_carbon <= usda_max:
                carbon_score = 100
                carbon_status = "✅ USDA COMPLIANT"
            elif total_carbon < usda_min:
                # Calculate how close we are to minimum
                carbon_score = max(0, 100 * (total_carbon / usda_min))
                carbon_status = f"⚠️  BELOW TARGET ({total_carbon - usda_min:+.0f})"
            else:
                # Above maximum is still compliant but flag for review
                carbon_score = 95
                carbon_status = f"✅ ABOVE RANGE ({total_carbon - usda_max:+.0f})"

            # Check event completeness
            event_count = EventTemplate.objects.filter(production_template=template).count()
            equipment_events = EventTemplate.objects.filter(
                production_template=template, event_type="equipment"
            ).count()

            event_score = min(100, (event_count / 12) * 100)  # Target 12 events per crop
            equipment_score = min(100, (equipment_events / 4) * 100)  # Target 4 equipment events

            # Check regional practices
            regional_practices = EventTemplate.objects.filter(
                production_template=template, typical_amounts__has_key="regional_practice"
            ).count()
            regional_score = min(100, (regional_practices / 3) * 100)  # Target 3 regional practices

            # Check consumer transparency
            transparency_events = EventTemplate.objects.filter(
                production_template=template, typical_amounts__has_key="consumer_transparency"
            ).count()
            transparency_score = min(100, (transparency_events / 3) * 100)  # Target 3 transparency events

            # Overall crop score (weighted)
            crop_readiness = (
                carbon_score * 0.4  # 40% carbon compliance
                + event_score * 0.2  # 20% event completeness
                + equipment_score * 0.15  # 15% equipment events
                + regional_score * 0.15  # 15% regional practices
                + transparency_score * 0.1  # 10% transparency
            )

            if detailed:
                self.stdout.write(f"\n📊 {crop_name} Detailed Breakdown:")
                self.stdout.write(f"  💨 Carbon: {total_carbon:.0f} kg CO2e/ha - {carbon_status}")
                self.stdout.write(f"  📋 Events: {event_count}/12 ({event_score:.0f}%)")
                self.stdout.write(f"  🚜 Equipment: {equipment_events}/4 ({equipment_score:.0f}%)")
                self.stdout.write(f"  🌾 Regional: {regional_practices}/3 ({regional_score:.0f}%)")
                self.stdout.write(f"  📱 Transparency: {transparency_events}/3 ({transparency_score:.0f}%)")
            else:
                self.stdout.write(f"✅ {crop_name}: {crop_readiness:.1f}% ready ({total_carbon:.0f} kg CO2e/ha)")

            return crop_readiness

        except CropType.DoesNotExist:
            self.stdout.write(f"❌ {crop_name}: Crop type not found")
            return 0

    def check_conservation_features(self):
        """Check Iowa conservation practice implementation"""

        conservation_practices = [
            "No-Till Planting (Conservation)",
            "Cover Crop Termination (Pre-Corn)",
            "Variable-Rate Nitrogen Application (GPS)",
        ]

        found_practices = 0
        for practice_name in conservation_practices:
            if EventTemplate.objects.filter(name=practice_name).exists():
                found_practices += 1

        return (found_practices / len(conservation_practices)) * 100

    def check_consumer_transparency(self):
        """Check consumer transparency feature implementation"""

        transparency_events = EventTemplate.objects.filter(typical_amounts__has_key="consumer_transparency").count()

        # Target: at least 6 transparency-enabled events across crops
        return min(100, (transparency_events / 6) * 100)

    def check_irrigation_features(self):
        """Check California irrigation practice implementation"""

        irrigation_practices = [
            "Micro-Sprinkler Irrigation (Water-Efficient)",
            "Deficit Irrigation Strategy (July-August)",
            "Soil Moisture Monitoring Network",
        ]

        found_practices = 0
        for practice_name in irrigation_practices:
            if EventTemplate.objects.filter(name=practice_name).exists():
                found_practices += 1

        return (found_practices / len(irrigation_practices)) * 100

    def check_water_efficiency(self):
        """Check water efficiency features"""

        water_events = EventTemplate.objects.filter(typical_amounts__has_key="water_efficient").count()

        # Target: at least 3 water-efficient events
        return min(100, (water_events / 3) * 100)

    def provide_launch_recommendations(self, readiness_score, region):
        """Provide specific recommendations based on readiness score"""

        self.stdout.write("\n📋 LAUNCH RECOMMENDATIONS")
        self.stdout.write("-" * 30)

        if readiness_score >= 95:
            self.stdout.write(self.style.SUCCESS("🚀 READY FOR IMMEDIATE LAUNCH"))
            self.stdout.write("✅ All systems ready for production")
            self.stdout.write("✅ Begin pilot farmer onboarding")
            self.stdout.write("✅ Start consumer QR scanning campaign")

        elif readiness_score >= 85:
            self.stdout.write(self.style.WARNING("⚠️  LAUNCH IN 1-2 WEEKS"))
            self.stdout.write("🔧 Complete remaining minor fixes")
            self.stdout.write("✅ Systems are mostly production-ready")
            self.stdout.write("📊 Focus on transparency and education features")

        elif readiness_score >= 70:
            self.stdout.write(self.style.WARNING("⚠️  LAUNCH IN 2-4 WEEKS"))
            self.stdout.write("🔧 Address major technical gaps")
            self.stdout.write("📊 Improve carbon calculation compliance")
            self.stdout.write("🌾 Complete regional practice implementation")

        else:
            self.stdout.write(self.style.ERROR("❌ DELAY LAUNCH - MAJOR WORK NEEDED"))
            self.stdout.write("🔧 Significant technical work required")
            self.stdout.write("📊 Carbon calculations need major adjustment")
            self.stdout.write("🌾 Missing critical regional practices")

        # Region-specific recommendations
        if region in ["all", "iowa"]:
            self.stdout.write("\n🌽 Iowa-specific recommendations:")
            self.stdout.write("  • Validate no-till carbon sequestration calculations")
            self.stdout.write("  • Test corn-soy rotation cycle benefits")
            self.stdout.write("  • Prepare farmer education materials")

        if region in ["all", "california"]:
            self.stdout.write("\n🌿 California-specific recommendations:")
            self.stdout.write("  • Validate water efficiency calculations")
            self.stdout.write("  • Test deficit irrigation benefits")
            self.stdout.write("  • Prepare drought-conscious messaging")
