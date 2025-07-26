from django.db import models
from datetime import datetime
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
    album = models.ForeignKey(
        "common.Gallery", on_delete=models.CASCADE, blank=True, null=True
    )
    establishment = models.ForeignKey(
        Establishment, on_delete=models.CASCADE, related_name="parcels"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, blank=True, null=True
    )
    area = models.FloatField(help_text="Parcel area in hectares")
    certified = models.BooleanField(
        default=False, help_text="Certified by a professional"
    )
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
    address = models.CharField(max_length=200, blank=True, null=True, help_text="Parcel specific address or location details")
    
    # ✅ COMPREHENSIVE AGRICULTURAL DATA for Carbon Calculations
    agricultural_details = models.JSONField(
        default=dict, 
        blank=True,
        help_text="Detailed agricultural data for carbon footprint calculations and USDA compliance"
    )
    
    # ✅ CARBON CALCULATION FLAGS
    carbon_calculation_enabled = models.BooleanField(
        default=False,
        help_text="Enable advanced carbon footprint calculations"
    )
    
    usda_compliance_eligible = models.BooleanField(
        default=False,
        help_text="Meets USDA requirements for carbon credit verification"
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
        required_soil_fields = [
            'soil_ph', 'soil_organic_matter', 'soil_nitrogen',
            'soil_phosphorus', 'soil_potassium'
        ]
        return all(field in self.agricultural_details for field in required_soil_fields)
    
    def has_complete_conservation_data(self):
        """Check if conservation practice data is complete for carbon credits"""
        required_conservation_fields = [
            'cover_crop_management', 'crop_rotation_pattern',
            'carbon_sequestration_practices', 'integrated_pest_management'
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
            'soil_organic_matter', 'nrcs_practices', 'organic_certification_status',
            'cover_crop_management', 'irrigation_efficiency'
        ]
        self.usda_compliance_eligible = all(
            field in self.agricultural_details and self.agricultural_details[field]
            for field in required_usda_fields
        )

    def finish_current_history(self, history_data, images):
        if self.current_history is not None:
            self.current_history.finish(history_data, images)
            history = self.current_history
            self.current_history = None
            self.save()
            return history
        return None
