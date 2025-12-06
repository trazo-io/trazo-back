from datetime import datetime

from django.db import models

from company.models import Establishment


class Product(models.Model):
    name = models.CharField(max_length=30)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to="product_images", blank=True)

    def __str__(self):
        return self.name


class Parcel(models.Model):
    name = models.CharField(max_length=30)
    description = models.TextField(blank=True, null=True)
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    establishment = models.ForeignKey(Establishment, on_delete=models.CASCADE, related_name="parcels")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, blank=True, null=True)
    area = models.FloatField(help_text="Parcel area in hectares")
    certified = models.BooleanField(default=False, help_text="Certified by a professional")
    current_history = models.OneToOneField(
        "history.History",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="current_parcel",
    )
    polygon = models.JSONField(blank=True, null=True)
    map_metadata = models.JSONField(blank=True, null=True)
    # crop_type removed - now stored in History model for per-production tracking
    soil_type = models.CharField(max_length=50, blank=True, null=True)
    unique_code = models.CharField(max_length=50, blank=True, null=True)
    certification_type = models.CharField(max_length=50, blank=True, null=True)
    contact_person = models.CharField(max_length=60, blank=True, null=True)
    contact_phone = models.CharField(max_length=30, blank=True, null=True)
    contact_email = models.EmailField(max_length=254, blank=True, null=True)
    address = models.CharField(
        max_length=200, blank=True, null=True, help_text="Parcel specific address or location details"
    )

    # ✅ COMPREHENSIVE AGRICULTURAL DATA for Carbon Calculations
    agricultural_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Detailed agricultural data for carbon footprint calculations and USDA compliance",
    )

    # ✅ CARBON CALCULATION FLAGS
    carbon_calculation_enabled = models.BooleanField(
        default=False, help_text="Enable advanced carbon footprint calculations"
    )

    usda_compliance_eligible = models.BooleanField(
        default=False, help_text="Meets USDA requirements for carbon credit verification"
    )

    def __str__(self):
        return str(self.id) + " - " + self.name + " - " + self.establishment.name

    @property
    def productions_completed(self):
        return self.histories.filter(finish_date__year=datetime.now().year).count()

    # ✅ AGRICULTURAL DATA ACCESS METHODS
    def get_agricultural_detail(self, field_name, default=None):
        """Get specific agricultural detail field"""
        return self.agricultural_details.get(field_name, default)

    def set_agricultural_detail(self, field_name, value):
        """Set specific agricultural detail field"""
        if not isinstance(self.agricultural_details, dict):
            self.agricultural_details = {}
        self.agricultural_details[field_name] = value

    def has_complete_soil_data(self):
        """Check if soil health data is complete for carbon calculations"""
        required_soil_fields = ["soil_ph", "soil_organic_matter", "soil_nitrogen", "soil_phosphorus", "soil_potassium"]
        return all(field in self.agricultural_details for field in required_soil_fields)

    def has_complete_conservation_data(self):
        """Check if conservation practice data is complete for carbon credits"""
        required_conservation_fields = [
            "cover_crop_management",
            "crop_rotation_pattern",
            "carbon_sequestration_practices",
            "integrated_pest_management",
        ]
        return all(field in self.agricultural_details for field in required_conservation_fields)

    def calculate_carbon_readiness_score(self):
        """Calculate completeness score for carbon calculations (0-100)"""
        total_fields = 37  # Total advanced agricultural fields
        completed_fields = len([k for k, v in self.agricultural_details.items() if v])
        return min(100, (completed_fields / total_fields) * 100)

    def update_usda_compliance_status(self):
        """Update USDA compliance eligibility based on available data"""
        required_usda_fields = [
            "soil_organic_matter",
            "nrcs_practices",
            "organic_certification_status",
            "cover_crop_management",
            "irrigation_efficiency",
        ]
        self.usda_compliance_eligible = all(
            field in self.agricultural_details and self.agricultural_details[field] for field in required_usda_fields
        )

    # 🎯 TRANSPARENCY-FOCUSED METHODS
    def get_transparency_description(self):
        """Get consumer-facing parcel description"""
        return self.description or ""

    def get_sustainability_practices(self):
        """Get sustainability practices narrative for consumers"""
        # Check multiple possible keys due to form field mapping
        return (
            self.agricultural_details.get("sustainability_practices")
            or self.agricultural_details.get("cover_crop_management")
            or self.agricultural_details.get("carbon_sequestration_practices")
            or ""
        )

    def get_consumer_story(self):
        """Get consumer story explaining why this parcel matters"""
        # Check multiple possible keys due to form field mapping
        return (
            self.agricultural_details.get("consumer_story")
            or self.agricultural_details.get("consumer_narrative")
            or ""
        )

    def get_primary_crop(self):
        """Get primary crop focus for this parcel"""
        # Check multiple possible keys due to form field mapping
        return (
            self.agricultural_details.get("primary_crop")
            or self.agricultural_details.get("crop_focus")
            or ""
        )

    def is_transparency_ready(self):
        """Check if parcel has sufficient transparency data for consumer display"""
        has_description = bool(self.description and len(self.description.strip()) >= 10)
        has_practices = bool(
            self.agricultural_details.get("sustainability_practices")
            or self.agricultural_details.get("cover_crop_management")
            or self.agricultural_details.get("carbon_sequestration_practices")
        )
        has_images = bool(self.album and self.album.images.exists())

        return has_description and (has_practices or has_images)

    def get_transparency_score(self):
        """Calculate transparency readiness score (0-100) for consumer confidence"""
        score = 0

        # Description quality (40 points)
        if self.description and len(self.description.strip()) >= 10:
            description_length = len(self.description.strip())
            if description_length >= 100:
                score += 40
            elif description_length >= 50:
                score += 30
            else:
                score += 20

        # Sustainability practices (30 points)
        if (
            self.agricultural_details.get("sustainability_practices")
            or self.agricultural_details.get("cover_crop_management")
            or self.agricultural_details.get("carbon_sequestration_practices")
        ):
            score += 30

        # Visual documentation (20 points)
        if self.album and self.album.images.exists():
            image_count = self.album.images.count()
            if image_count >= 3:
                score += 20
            elif image_count >= 1:
                score += 15

        # Certification (10 points)
        if self.certified and self.certification_type:
            score += 10

        return min(100, score)

    def finish_current_history(self, history_data, images):
        if self.current_history is not None:
            self.current_history.finish(history_data, images)
            history = self.current_history
            self.current_history = None
            self.save()
            return history
        return None
