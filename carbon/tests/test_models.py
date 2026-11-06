"""
Comprehensive Test Suite for Carbon App
Tests carbon calculation models, USDA integration, and verification systems
"""

import unittest
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from carbon.models import (
    CarbonBenchmark,
    CarbonCertification,
    CarbonEntry,
    CarbonOffsetProject,
    CarbonOffsetPurchase,
    CarbonSource,
    CropType,
    EventTemplate,
    ProductionTemplate,
    USDAComplianceRecord,
)
from company.models import Company, Establishment

User = get_user_model()


class TestCropTypeModel(TestCase):
    """Test CropType model functionality"""

    def setUp(self):
        """Set up test data"""
        self.crop_data = {
            "name": "Citrus (Oranges)",
            "slug": "citrus_oranges",
            "category": "tree_fruit",
            "description": "Citrus fruit production with focus on oranges",
            "typical_farm_size": "20-100 hectares",
            "growing_season": "12 months (evergreen)",
            "harvest_season": "November - April",
            "emissions_per_hectare": 2500.0,
            "industry_average": 2800.0,
            "best_practice": 1800.0,
            "carbon_credit_potential": 500.0,
            "typical_cost_per_hectare": 15000.0,
            "fertilizer_cost_per_hectare": 3000.0,
            "fuel_cost_per_hectare": 2000.0,
            "irrigation_cost_per_hectare": 1500.0,
            "labor_cost_per_hectare": 8500.0,
            "sustainability_opportunities": ["precision agriculture", "organic transition"],
        }

    def test_crop_type_creation(self):
        """Test basic crop type creation"""
        crop = CropType.objects.create(**self.crop_data)

        self.assertEqual(crop.name, "Citrus (Oranges)")
        self.assertEqual(crop.category, "tree_fruit")
        self.assertTrue(crop.is_active)
        self.assertFalse(crop.usda_factors_used)
        self.assertIsNotNone(crop.created_at)
        self.assertIsNotNone(crop.updated_at)

    def test_crop_type_unique_constraints(self):
        """Test uniqueness constraints"""
        CropType.objects.create(**self.crop_data)

        # Same name should fail
        with self.assertRaises(IntegrityError):
            CropType.objects.create(**self.crop_data)

        # Same slug should fail
        duplicate_data = self.crop_data.copy()
        duplicate_data["name"] = "Different Name"
        with self.assertRaises(IntegrityError):
            CropType.objects.create(**duplicate_data)

    def test_crop_type_string_representation(self):
        """Test string representation"""
        crop = CropType.objects.create(**self.crop_data)
        self.assertEqual(str(crop), "Citrus (Oranges)")

    def test_carbon_benchmark_range_property(self):
        """Test carbon benchmark range property"""
        crop = CropType.objects.create(**self.crop_data)
        expected = "1800.0-2500.0 kg CO2e/ha"
        self.assertEqual(crop.carbon_benchmark_range, expected)

    def test_crop_type_category_choices(self):
        """Test category choices validation"""
        valid_categories = ["tree_fruit", "tree_nut", "grain", "oilseed", "vegetable", "herb", "legume", "other"]

        for category in valid_categories:
            crop_data = self.crop_data.copy()
            crop_data["slug"] = f"test_{category}"
            crop_data["category"] = category
            crop = CropType.objects.create(**crop_data)
            self.assertEqual(crop.category, category)
            crop.delete()


class TestProductionTemplateModel(TransactionTestCase):
    """Test ProductionTemplate model functionality"""

    def setUp(self):
        """Set up test data"""
        self.crop_type = CropType.objects.create(
            name="Test Crop",
            slug="test_crop",
            category="vegetable",
            description="Test crop for templates",
            emissions_per_hectare=1000.0,
            industry_average=1200.0,
            best_practice=800.0,
            carbon_credit_potential=200.0,
            typical_cost_per_hectare=5000.0,
        )

        self.template_data = {
            "crop_type": self.crop_type,
            "name": "Organic Production",
            "slug": "organic_production",
            "farming_approach": "organic",
            "description": "Comprehensive organic production system",
            "complexity_level": "intermediate",
            "projected_emissions_reduction": 25.0,
            "projected_cost_change": 15.0,
            "projected_yield_impact": -5.0,
            "certification_requirements": ["USDA Organic", "CCOF"],
            "market_demand": "high",
        }

    def test_production_template_creation(self):
        """Test production template creation"""
        template = ProductionTemplate.objects.create(**self.template_data)

        self.assertEqual(template.name, "Organic Production")
        self.assertEqual(template.farming_approach, "organic")
        self.assertTrue(template.is_active)
        self.assertFalse(template.is_recommended)
        self.assertEqual(template.usage_count, 0)
        self.assertTrue(template.usda_compliant)

    def test_production_template_string_representation(self):
        """Test string representation"""
        template = ProductionTemplate.objects.create(**self.template_data)
        expected = f"{self.crop_type.name} - Organic Production"
        self.assertEqual(str(template), expected)

    def test_unique_together_constraint(self):
        """Test unique together constraint for crop_type and slug"""
        ProductionTemplate.objects.create(**self.template_data)

        # Same crop_type and slug should fail
        duplicate_data = self.template_data.copy()
        duplicate_data["name"] = "Different Name"
        with self.assertRaises(IntegrityError):
            ProductionTemplate.objects.create(**duplicate_data)

    def test_increment_usage_method(self):
        """Test increment usage method"""
        template = ProductionTemplate.objects.create(**self.template_data)
        initial_count = template.usage_count

        template.increment_usage()
        template.refresh_from_db()

        self.assertEqual(template.usage_count, initial_count + 1)

    def test_farming_approach_choices(self):
        """Test farming approach choices"""
        valid_approaches = [
            "conventional",
            "organic",
            "precision",
            "regenerative",
            "sustainable",
            "integrated",
            "no_till",
            "cover_crop",
        ]

        for approach in valid_approaches:
            template_data = self.template_data.copy()
            template_data["slug"] = f"test_{approach}"
            template_data["farming_approach"] = approach
            template = ProductionTemplate.objects.create(**template_data)
            self.assertEqual(template.farming_approach, approach)
            template.delete()


class TestEventTemplateModel(TransactionTestCase):
    """Test EventTemplate model functionality"""

    def setUp(self):
        """Set up test data"""
        self.crop_type = CropType.objects.create(
            name="Test Crop",
            slug="test_crop",
            category="vegetable",
            description="Test crop",
            emissions_per_hectare=1000.0,
            industry_average=1200.0,
            best_practice=800.0,
            carbon_credit_potential=200.0,
            typical_cost_per_hectare=5000.0,
        )

        self.production_template = ProductionTemplate.objects.create(
            crop_type=self.crop_type,
            name="Test Template",
            slug="test_template",
            farming_approach="organic",
            description="Test template",
        )

        self.event_data = {
            "production_template": self.production_template,
            "name": "Winter Pruning",
            "event_type": "pruning",
            "description": "Annual winter pruning activity",
            "timing": "December - February",
            "frequency": "annual",
            "typical_duration": "2-3 hours",
            "order_sequence": 1,
            "carbon_impact": 50.0,
            "carbon_category": "medium",
            "cost_estimate": 200.0,
            "labor_hours": 2.5,
            "efficiency_tips": "Use sharp tools to minimize plant damage",
            "sustainability_score": 8,
            "backend_event_type": 2,
            "carbon_sources": ["fuel", "equipment"],
            "typical_amounts": {"fuel": "5L", "hours": "2.5"},
            "alternative_methods": ["hand pruning", "mechanical pruning"],
            "backend_event_fields": {"type": "maintenance", "category": "pruning"},
        }

    def test_event_template_creation(self):
        """Test event template creation"""
        event = EventTemplate.objects.create(**self.event_data)

        self.assertEqual(event.name, "Winter Pruning")
        self.assertEqual(event.event_type, "pruning")
        self.assertEqual(event.carbon_impact, 50.0)
        self.assertEqual(event.carbon_category, "medium")
        self.assertTrue(event.is_active)
        self.assertTrue(event.is_default_enabled)
        self.assertFalse(event.is_required)

    def test_event_template_string_representation(self):
        """Test string representation"""
        event = EventTemplate.objects.create(**self.event_data)
        expected = f"{self.production_template.name} - Winter Pruning"
        self.assertEqual(str(event), expected)

    def test_crop_type_property(self):
        """Test crop_type property"""
        event = EventTemplate.objects.create(**self.event_data)
        self.assertEqual(event.crop_type, self.crop_type)

    def test_formatted_carbon_impact_property(self):
        """Test formatted carbon impact property"""
        # Positive impact
        event = EventTemplate.objects.create(**self.event_data)
        self.assertEqual(event.formatted_carbon_impact, "50.0 kg CO₂")

        # Negative impact (sequestration)
        event_data_negative = self.event_data.copy()
        event_data_negative["name"] = "Carbon Sequestration"
        event_data_negative["carbon_impact"] = -30.0
        event_data_negative["carbon_category"] = "negative"
        event_negative = EventTemplate.objects.create(**event_data_negative)
        self.assertEqual(event_negative.formatted_carbon_impact, "-30.0 kg CO₂ (sequestration)")

    def test_carbon_impact_color_property(self):
        """Test carbon impact color property"""
        # High impact
        high_event = EventTemplate.objects.create(
            **{**self.event_data, "name": "High Impact", "carbon_category": "high"}
        )
        self.assertEqual(high_event.carbon_impact_color, "red")

        # Negative impact
        negative_event = EventTemplate.objects.create(
            **{**self.event_data, "name": "Negative Impact", "carbon_category": "negative"}
        )
        self.assertEqual(negative_event.carbon_impact_color, "green")

    def test_increment_usage_method(self):
        """Test increment usage method"""
        event = EventTemplate.objects.create(**self.event_data)
        initial_count = event.usage_count

        event.increment_usage()
        event.refresh_from_db()

        self.assertEqual(event.usage_count, initial_count + 1)


class TestCarbonSourceModel(TestCase):
    """Test CarbonSource model functionality"""

    def test_carbon_source_creation(self):
        """Test carbon source creation"""
        source = CarbonSource.objects.create(
            name="Nitrogen Fertilizer",
            description="Synthetic nitrogen fertilizer",
            unit="kg N",
            category="Fertilizer",
            default_emission_factor=5.9,
            usda_factors_based=True,
            verification_status="factors_verified",
            data_source="USDA Agricultural Research Service",
        )

        self.assertEqual(source.name, "Nitrogen Fertilizer")
        self.assertEqual(source.unit, "kg N")
        self.assertTrue(source.usda_factors_based)
        self.assertEqual(source.verification_status, "factors_verified")

    def test_carbon_source_string_representation(self):
        """Test string representation"""
        source = CarbonSource.objects.create(
            name="Test Source", unit="kg", category="Test", default_emission_factor=2.5
        )
        self.assertEqual(str(source), "Test Source")

    def test_carbon_source_unique_name(self):
        """Test unique name constraint"""
        CarbonSource.objects.create(name="Unique Source", unit="kg", category="Test", default_emission_factor=1.0)

        with self.assertRaises(IntegrityError):
            CarbonSource.objects.create(name="Unique Source", unit="L", category="Test2", default_emission_factor=2.0)


class TestCarbonEntryModel(TransactionTestCase):
    """Test CarbonEntry model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA")

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Farm", address="123 Farm Road", country="USA", created_by=self.user
        )

        self.carbon_source = CarbonSource.objects.create(
            name="Test Source", unit="kg", category="Fuel", default_emission_factor=2.5
        )

    def test_carbon_entry_creation_emission(self):
        """Test carbon entry creation for emission"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=100.0,
            co2e_amount=250.0,
            year=2024,
            description="Test emission entry",
        )

        self.assertEqual(entry.type, "emission")
        self.assertEqual(entry.amount, 100.0)
        self.assertEqual(entry.effective_amount, 100.0)  # Should equal amount for emissions
        self.assertFalse(entry.usda_factors_based)
        self.assertEqual(entry.verification_status, "estimated")

    def test_carbon_entry_creation_offset(self):
        """Test carbon entry creation for offset"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.carbon_source,
            amount=50.0,
            year=2024,
            verification_level="self_reported",
            description="Test offset entry",
        )

        self.assertEqual(entry.type, "offset")
        self.assertEqual(entry.verification_level, "self_reported")
        self.assertEqual(entry.trust_score, 0.5)
        self.assertEqual(entry.effective_amount, 25.0)  # 50.0 * 0.5

    def test_carbon_entry_string_representation(self):
        """Test string representation"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=100.0,
            year=2024,
        )

        self.assertIn("Emission", str(entry))
        self.assertIn("100.0", str(entry))

    def test_verification_badge_property(self):
        """Test verification badge property"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.carbon_source,
            amount=50.0,
            year=2024,
            verification_level="certified_project",
        )

        badge = entry.verification_badge
        self.assertEqual(badge["color"], "green")
        self.assertEqual(badge["text"], "Certified Project")
        self.assertEqual(badge["icon"], "certificate")

    def test_calculate_carbon_score_method(self):
        """Test carbon score calculation"""
        # Carbon negative scenario
        score = CarbonEntry.calculate_carbon_score(total_emissions=100.0, total_offsets=150.0)
        self.assertGreater(score, 50)  # Should be > 50 for carbon negative

        # Carbon neutral scenario
        score = CarbonEntry.calculate_carbon_score(total_emissions=100.0, total_offsets=100.0)
        self.assertEqual(score, 50)  # Should be exactly 50 for neutral

        # Carbon positive scenario
        score = CarbonEntry.calculate_carbon_score(total_emissions=100.0, total_offsets=50.0)
        self.assertLess(score, 50)  # Should be < 50 for carbon positive

    def test_constraint_either_establishment_or_production(self):
        """Test constraint requiring either establishment or production"""
        # Should fail with neither establishment nor production
        with self.assertRaises(IntegrityError):
            CarbonEntry.objects.create(
                created_by=self.user, type="emission", source=self.carbon_source, amount=100.0, year=2024
            )


class TestCarbonCertificationModel(TransactionTestCase):
    """Test CarbonCertification model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA")

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Farm", address="123 Farm Road", country="USA", created_by=self.user
        )

    def test_carbon_certification_creation(self):
        """Test carbon certification creation"""
        cert = CarbonCertification.objects.create(
            establishment=self.establishment,
            certifier="USDA Organic",
            certificate_id="CERT-2024-001",
            issue_date=date.today(),
            expiry_date=date.today() + timedelta(days=365),
            is_usda_soe_verified=True,
            verification_date=date.today(),
            verification_details="Verified by USDA inspector",
        )

        self.assertEqual(cert.certifier, "USDA Organic")
        self.assertEqual(cert.certificate_id, "CERT-2024-001")
        self.assertTrue(cert.is_usda_soe_verified)

    def test_carbon_certification_string_representation(self):
        """Test string representation"""
        cert = CarbonCertification.objects.create(establishment=self.establishment, certificate_id="CERT-TEST-001")

        expected = f"CERT-TEST-001 ({self.establishment.name})"
        self.assertEqual(str(cert), expected)


class TestUSDAComplianceRecordModel(TransactionTestCase):
    """Test USDAComplianceRecord model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA")

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Farm", address="123 Farm Road", country="USA", created_by=self.user
        )

        self.carbon_source = CarbonSource.objects.create(
            name="Test Source", unit="kg", category="Fuel", default_emission_factor=2.5
        )

        self.carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=100.0,
            year=2024,
        )

    def test_usda_compliance_record_creation(self):
        """Test USDA compliance record creation"""
        record = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            establishment=self.establishment,
            compliance_status="compliant",
            confidence_score=0.95,
            validation_method="api_validation",
            validation_details={"api_version": "2.0", "factors_matched": True},
            recommendations=["Use certified organic fertilizer"],
            usda_api_used=True,
            api_response_code=200,
            crop_type="Citrus",
            state="CA",
            regional_factors_used=True,
            validated_by=self.user,
        )

        self.assertEqual(record.compliance_status, "compliant")
        self.assertEqual(record.confidence_score, 0.95)
        self.assertEqual(record.confidence_level, "high")
        self.assertTrue(record.usda_api_used)
        self.assertEqual(record.crop_type, "Citrus")

    def test_confidence_level_auto_setting(self):
        """Test automatic confidence level setting based on score"""
        # High confidence
        high_record = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            establishment=self.establishment,
            confidence_score=0.95,
            crop_type="Test",
            state="CA",
        )
        self.assertEqual(high_record.confidence_level, "high")

        # Medium confidence
        medium_record = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            establishment=self.establishment,
            confidence_score=0.8,
            crop_type="Test2",
            state="CA",
        )
        self.assertEqual(medium_record.confidence_level, "medium")

        # Low confidence
        low_record = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            establishment=self.establishment,
            confidence_score=0.6,
            crop_type="Test3",
            state="CA",
        )
        self.assertEqual(low_record.confidence_level, "low")

    def test_is_epa_factors_based_property(self):
        """Test is_epa_factors_based property"""
        # Record with successful validation (factors were applied)
        verified_record = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            compliance_status="compliant",
            confidence_score=0.95,
            crop_type="Test",
            state="CA",
        )
        self.assertTrue(verified_record.is_epa_factors_based)

        # Record without successful validation (factors were not applied)
        unverified_record = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            compliance_status="compliant",
            confidence_score=0.7,
            crop_type="Test2",
            state="CA",
        )
        self.assertFalse(unverified_record.is_epa_factors_based)

    def test_needs_review_property(self):
        """Test needs_review property"""
        # Non-compliant should need review
        non_compliant = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            compliance_status="non_compliant",
            confidence_score=0.8,
            crop_type="Test",
            state="CA",
        )
        self.assertTrue(non_compliant.needs_review)

        # Low confidence should need review
        low_confidence = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            compliance_status="compliant",
            confidence_score=0.6,
            crop_type="Test2",
            state="CA",
        )
        self.assertTrue(low_confidence.needs_review)

        # Good record should not need review
        good_record = USDAComplianceRecord.objects.create(
            carbon_entry=self.carbon_entry,
            compliance_status="compliant",
            confidence_score=0.9,
            crop_type="Test3",
            state="CA",
        )
        self.assertFalse(good_record.needs_review)


class TestCarbonOffsetProjectModel(TestCase):
    """Test CarbonOffsetProject model functionality"""

    def test_carbon_offset_project_creation(self):
        """Test carbon offset project creation"""
        project = CarbonOffsetProject.objects.create(
            name="Reforestation Project Brazil",
            description="Large-scale reforestation in Amazon basin",
            project_type="Forestry",
            certification_standard="VCS",
            location="Brazil, Amazon",
            price_per_ton=Decimal("15.50"),
            available_capacity=Decimal("10000.00"),
        )

        self.assertEqual(project.name, "Reforestation Project Brazil")
        self.assertEqual(project.project_type, "Forestry")
        self.assertEqual(project.price_per_ton, Decimal("15.50"))
        self.assertEqual(project.available_capacity, Decimal("10000.00"))

    def test_carbon_offset_project_string_representation(self):
        """Test string representation"""
        project = CarbonOffsetProject.objects.create(
            name="Test Project",
            description="Test description",
            project_type="Test",
            certification_standard="Test",
            location="Test Location",
            price_per_ton=Decimal("10.00"),
            available_capacity=Decimal("1000.00"),
        )

        self.assertEqual(str(project), "Test Project")


class TestCarbonOffsetPurchaseModel(TransactionTestCase):
    """Test CarbonOffsetPurchase model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.project = CarbonOffsetProject.objects.create(
            name="Test Project",
            description="Test project",
            project_type="Forestry",
            certification_standard="VCS",
            location="Test Location",
            price_per_ton=Decimal("12.00"),
            available_capacity=Decimal("5000.00"),
        )

    def test_carbon_offset_purchase_creation(self):
        """Test carbon offset purchase creation"""
        purchase = CarbonOffsetPurchase.objects.create(
            project=self.project,
            user=self.user,
            amount=Decimal("10.0"),
            price_per_ton=Decimal("12.00"),
            status="completed",
            is_verified=True,
        )

        self.assertEqual(purchase.amount, Decimal("10.0"))
        self.assertEqual(purchase.total_price, Decimal("120.00"))  # 10 * 12
        self.assertTrue(purchase.is_verified)
        self.assertIsNotNone(purchase.certificate_id)

    def test_total_price_auto_calculation(self):
        """Test automatic total price calculation"""
        purchase = CarbonOffsetPurchase.objects.create(
            project=self.project, user=self.user, amount=Decimal("5.0"), price_per_ton=Decimal("15.00")
        )

        # Should automatically calculate total_price
        expected_total = Decimal("5.0") * Decimal("15.00")
        self.assertEqual(purchase.total_price, expected_total)

    def test_carbon_offset_purchase_string_representation(self):
        """Test string representation"""
        purchase = CarbonOffsetPurchase.objects.create(
            project=self.project, user=self.user, amount=Decimal("2.5"), price_per_ton=Decimal("10.00")
        )

        expected = f"{self.user.username} - {self.project.name} - 2.5 tons"
        self.assertEqual(str(purchase), expected)


class TestCarbonIntegrations(TransactionTestCase):
    """Test carbon model integrations and complex scenarios"""

    def setUp(self):
        """Set up test data for integration tests"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA")

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Farm", address="123 Farm Road", country="USA", created_by=self.user
        )

    def test_complete_carbon_tracking_flow(self):
        """Test complete carbon tracking workflow"""
        # Create crop type and template
        crop_type = CropType.objects.create(
            name="Integration Test Crop",
            slug="integration_test",
            category="vegetable",
            description="Test crop for integration",
            emissions_per_hectare=1500.0,
            industry_average=1800.0,
            best_practice=1200.0,
            carbon_credit_potential=300.0,
            typical_cost_per_hectare=8000.0,
        )

        template = ProductionTemplate.objects.create(
            crop_type=crop_type,
            name="Sustainable Production",
            slug="sustainable_production",
            farming_approach="sustainable",
            description="Sustainable production system",
        )

        event_template = EventTemplate.objects.create(
            production_template=template,
            name="Fertilizer Application",
            event_type="fertilization",
            description="Nitrogen fertilizer application",
            timing="Spring",
            frequency="annual",
            carbon_impact=75.0,
            carbon_category="medium",
            cost_estimate=300.0,
            backend_event_type=1,
        )

        # Create carbon source
        carbon_source = CarbonSource.objects.create(
            name="Nitrogen Fertilizer",
            unit="kg N",
            category="Fertilizer",
            default_emission_factor=5.9,
            usda_factors_based=True,
        )

        # Create carbon entry
        carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=carbon_source,
            amount=100.0,
            co2e_amount=590.0,
            year=2024,
            usda_factors_based=True,
        )

        # Create USDA compliance record
        compliance = USDAComplianceRecord.objects.create(
            carbon_entry=carbon_entry,
            establishment=self.establishment,
            compliance_status="compliant",
            confidence_score=0.9,
            crop_type=crop_type.name,
            state="CA",
            usda_api_used=True,
            regional_factors_used=True,
        )

        # Verify the complete flow
        self.assertEqual(carbon_entry.source.name, "Nitrogen Fertilizer")
        self.assertTrue(carbon_entry.usda_factors_based)
        self.assertTrue(compliance.is_epa_factors_based)
        self.assertEqual(compliance.confidence_level, "high")

    def test_benchmark_comparison_integration(self):
        """Test benchmark comparison functionality"""
        # Create benchmark
        benchmark = CarbonBenchmark.objects.create(
            industry="Citrus Production",
            year=2024,
            average_emissions=2500.0,
            min_emissions=1800.0,
            max_emissions=3200.0,
            company_count=150,
            unit="kg CO2e per hectare",
            source="USDA Agricultural Census",
            crop_type="Citrus",
            region="California",
        )

        # Test carbon score calculation with benchmark
        score = CarbonEntry.calculate_carbon_score(
            total_emissions=2000.0, total_offsets=500.0, industry_benchmark=benchmark.average_emissions
        )

        # Should get a good score for being below industry average
        self.assertGreater(score, 25)  # Better than worst case
        self.assertLess(score, 50)  # Still carbon positive


if __name__ == "__main__":
    unittest.main()
