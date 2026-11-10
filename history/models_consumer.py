"""
Shopper-side model behind the signed-in consumer dashboard.

UserFavorite, UserProductComparison, UserShoppingGoal, UserShoppingInsight and
UserLocalRecommendation lived here until history 0254 (2026-11-09) retired them: no screen read or
wrote any of them, production held 0 rows in each, and two of their routes leaked unpublished
seasons (compare_products, toggle_favorite). UserLocalRecommendation carried `carbon_score`, a
stored 0-100 grade.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from backend.constants import calculate_miles_equivalent, calculate_trees_equivalent


class UserImpactSummary(models.Model):
    """Aggregate user impact metrics for dashboard"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="impact_summary")

    # Core Impact Metrics
    total_scans = models.IntegerField(default=0)
    total_reviews = models.IntegerField(default=0)
    total_carbon_offset_kg = models.FloatField(default=0.0)  # kg CO2e saved
    total_money_saved_usd = models.FloatField(default=0.0)  # USD saved through better choices

    # US-Friendly Metrics
    miles_driving_offset = models.FloatField(default=0.0)  # Miles of driving offset
    trees_equivalent = models.FloatField(default=0.0)  # Trees planted equivalent

    # Engagement Metrics
    sustainable_farms_found = models.IntegerField(default=0)
    local_farms_found = models.IntegerField(default=0)
    better_choices_made = models.IntegerField(default=0)

    # Achievement Tracking
    achievements_earned = models.JSONField(default=list)
    current_level = models.IntegerField(default=1)
    points_earned = models.IntegerField(default=0)

    # Tracking
    first_scan_date = models.DateTimeField(null=True, blank=True)
    last_scan_date = models.DateTimeField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    def calculate_us_friendly_metrics(self):
        """Convert carbon awareness data to US consumer-friendly units"""
        # For MVP: Show carbon footprint awareness instead of fake "offset"
        # The total_carbon_offset_kg now represents total carbon tracked, not "saved"

        if self.total_carbon_offset_kg > 0:
            # Convert to miles equivalent using EPA standards for context (not as "offset" but as awareness)
            # This shows the equivalent driving impact of the carbon they're tracking
            self.miles_driving_offset = round(calculate_miles_equivalent(self.total_carbon_offset_kg), 1)

            # Trees equivalent for carbon absorption context using EPA standards
            self.trees_equivalent = round(calculate_trees_equivalent(self.total_carbon_offset_kg), 1)
        else:
            self.miles_driving_offset = 0
            self.trees_equivalent = 0

    def add_scan_impact(self, carbon_saved_kg, is_better_choice=True, is_local=False):
        """Add impact from a new scan"""
        self.total_scans += 1
        self.total_carbon_offset_kg += carbon_saved_kg

        if is_better_choice:
            self.better_choices_made += 1

        if is_local:
            self.local_farms_found += 1

        self.last_scan_date = timezone.now()
        if not self.first_scan_date:
            self.first_scan_date = timezone.now()

        self.calculate_us_friendly_metrics()
        self.save()

    def __str__(self):
        return f"{self.user.email} - {self.total_scans} scans, {self.miles_driving_offset} miles offset"
