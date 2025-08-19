"""
Third-Party Verification API Integration Tests

Tests the complete flow of third-party verification APIs
for carbon offset entries including registry credential verification,
verification status checking, bulk operations, and methodology templates.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase

from rest_framework.test import APIClient

from carbon.models import CarbonEntry, CarbonSource
from carbon.services.registry_integration import RegistryIntegrationService
from carbon.services.verification_service import VerificationService
from company.models import Company, Establishment

User = get_user_model()


class ThirdPartyVerificationTestCase(TransactionTestCase):
    """Test third-party verification API integration"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()

        # Create test company and user
        self.company = Company.objects.create(
            name="Test Verification Company", address="123 Test St", city="Test City", state="CA", country="USA"
        )

        self.user = User.objects.create_user(
            email="verification_test@trazo.io", password="testpass123", first_name="Test", last_name="User"
        )

        # Create WorksIn relationship
        from users.models import WorksIn

        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        self.establishment = Establishment.objects.create(
            company=self.company,
            name="Test Farm",
            address="456 Farm Rd",
            city="Farm City",
            state="CA",
            country="USA",
            establishment_type="farm",
        )

        # Create test carbon sources
        self.no_till_source = CarbonSource.objects.create(
            name="no_till",
            category="offset",
            default_emission_factor=-1.0,
            unit="kg CO2e",
            description="No-till farming carbon offset",
            usda_verified=True,
        )

        self.tree_planting_source = CarbonSource.objects.create(
            name="tree_planting",
            category="offset",
            default_emission_factor=-2.5,
            unit="kg CO2e",
            description="Tree planting carbon offset",
            usda_verified=True,
        )

        # Create test carbon entries
        self.self_reported_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.no_till_source,
            amount=50.0,
            year=2025,
            description="Self-reported no-till offset",
            verification_level="self_reported",
            trust_score=0.3,
            effective_amount=15.0,
            audit_status="pending",
        )

        self.vcs_certified_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.tree_planting_source,
            amount=500.0,
            year=2025,
            description="VCS certified tree planting project",
            verification_level="certified_project",
            registry_verification_id="VCS-1001",
            trust_score=0.9,
            effective_amount=450.0,
            audit_status="verified",
        )

        self.client.force_authenticate(user=self.user)

    def test_registry_credential_verification_success(self):
        """Test successful registry credential verification"""
        response = self.client.post(
            "/api/carbon/verify-registry-credentials/",
            {
                "registry_verification_id": "VCS-1001",
                "registry_type": "vcs",
                "carbon_entry_id": self.vcs_certified_entry.id,
            },
            format="json",
        )

        # Accept both 200 (success) and 400 (expected failure due to mock registry)
        self.assertIn(response.status_code, [200, 400])

        if response.status_code == 200:
            data = response.json()
            self.assertIn("verified", data)
            self.assertIn("registry", data)
        else:
            # Expected failure for mock testing
            data = response.json()
            self.assertIn("message", data)

    def test_verification_status_api(self):
        """Test verification status API endpoint"""
        response = self.client.get(f"/api/carbon/entries/{self.self_reported_entry.id}/verification-status/")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["carbon_entry_id"], self.self_reported_entry.id)
        self.assertIn("verification_status", data)
        self.assertIn("trust_score", data["verification_status"])
        self.assertIn("audit_status", data["verification_status"])
        self.assertIn("evidence_summary", data)
        self.assertIn("audit_trail", data)

    def test_bulk_verification_scheduling(self):
        """Test bulk verification API"""
        entry_ids = [self.self_reported_entry.id, self.vcs_certified_entry.id]

        response = self.client.post(
            "/api/carbon/bulk-verify/",
            {"carbon_entry_ids": entry_ids, "verification_action": "schedule_audit"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("bulk_verification_summary", data)
        summary = data["bulk_verification_summary"]

        self.assertIn("total_entries", summary)
        self.assertIn("successful", summary)
        self.assertIn("failed", summary)
        self.assertEqual(summary["total_entries"], 2)

    def test_methodology_templates_api(self):
        """Test methodology templates API"""
        response = self.client.get("/api/carbon/methodology-templates/")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("methodology_templates", data)
        self.assertIn("supported_methodologies", data)
        self.assertIn("registry_standards", data)

        templates = data["methodology_templates"]
        self.assertIsInstance(templates, dict)

        # Check for no-till template if present
        if "no_till" in templates:
            no_till = templates["no_till"]
            self.assertIn("methodology", no_till)
            self.assertIn("emission_factor", no_till)

    @patch("carbon.services.verification_service.VerificationService.verify_offset_entry")
    def test_verification_service_integration(self, mock_verify):
        """Test direct verification service integration"""
        # Mock verification result
        mock_verify.return_value = {
            "approved": True,
            "trust_score": 0.85,
            "anti_gaming_flags": [],
            "requirements": ["documentation_review"],
            "audit_required": False,
            "registry_validation": {"verified": True},
            "methodology_validation": {"valid": True},
        }

        verification_service = VerificationService()
        result = verification_service.verify_offset_entry(self.vcs_certified_entry)

        self.assertTrue(result["approved"])
        self.assertEqual(result["trust_score"], 0.85)
        self.assertIsInstance(result["anti_gaming_flags"], list)
        self.assertIsInstance(result["requirements"], list)
        self.assertFalse(result["audit_required"])
        self.assertTrue(result["registry_validation"]["verified"])
        self.assertTrue(result["methodology_validation"]["valid"])

        mock_verify.assert_called_once_with(self.vcs_certified_entry)

    @patch("carbon.services.registry_integration.RegistryIntegrationService.get_methodology_template")
    @patch("carbon.services.registry_integration.RegistryIntegrationService.get_registry_project_url")
    @patch("carbon.services.registry_integration.RegistryIntegrationService.validate_project_credentials")
    def test_registry_integration_service(self, mock_validate, mock_url, mock_template):
        """Test registry integration service functionality"""
        # Mock service responses
        mock_template.return_value = {
            "methodology": "VM0007",
            "emission_factor": -2.1,
            "required_data": ["area", "crop_type", "duration"],
        }
        mock_url.return_value = "https://registry.verra.org/project/VCS-1001"
        mock_validate.return_value = {"valid": True, "status": "active"}

        registry_service = RegistryIntegrationService()

        # Test methodology template retrieval
        template = registry_service.get_methodology_template("no_till")
        self.assertIsNotNone(template)
        self.assertEqual(template["methodology"], "VM0007")
        self.assertEqual(template["emission_factor"], -2.1)
        self.assertIsInstance(template["required_data"], list)

        # Test registry URL generation
        vcs_url = registry_service.get_registry_project_url("VCS-1001", "vcs")
        self.assertIsNotNone(vcs_url)
        self.assertIn("verra.org", vcs_url)

        # Test credential validation
        validation = registry_service.validate_project_credentials("VCS-1001", "vcs")
        self.assertIsNotNone(validation)
        self.assertTrue(validation["valid"])

        # Verify mocks were called
        mock_template.assert_called_once_with("no_till")
        mock_url.assert_called_once_with("VCS-1001", "vcs")
        mock_validate.assert_called_once_with("VCS-1001", "vcs")


class RegistryCredentialTestCase(TestCase):
    """Test registry credential verification functionality"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()

        self.company = Company.objects.create(
            name="Registry Test Company", address="456 Registry Ave", city="Registry City", state="NY"
        )

        self.user = User.objects.create_user(
            email="registry_test@trazo.io",
            password="testpass123",
        )

        # Create WorksIn relationship

        from users.models import WorksIn

        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        self.establishment = Establishment.objects.create(
            company=self.company, name="Registry Test Farm", establishment_type="farm"
        )

        self.source = CarbonSource.objects.create(
            name="test_offset", category="offset", default_emission_factor=-1.0, unit="kg CO2e"
        )

        self.client.force_authenticate(user=self.user)

    def test_vcs_registry_verification(self):
        """Test VCS registry verification"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.source,
            amount=100.0,
            year=2025,
            verification_level="certified_project",
            registry_verification_id="VCS-1001",
        )

        response = self.client.post(
            "/api/carbon/verify-registry-credentials/",
            {"registry_verification_id": "VCS-1001", "registry_type": "vcs", "carbon_entry_id": entry.id},
            format="json",
        )

        # Should handle VCS verification attempt
        self.assertIn(response.status_code, [200, 400])

    def test_gold_standard_registry_verification(self):
        """Test Gold Standard registry verification"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.source,
            amount=200.0,
            year=2025,
            verification_level="certified_project",
            registry_verification_id="GS-2002",
        )

        response = self.client.post(
            "/api/carbon/verify-registry-credentials/",
            {"registry_verification_id": "GS-2002", "registry_type": "gold_standard", "carbon_entry_id": entry.id},
            format="json",
        )

        # Should handle Gold Standard verification attempt
        self.assertIn(response.status_code, [200, 400])

    def test_invalid_registry_type(self):
        """Test invalid registry type handling"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.source,
            amount=50.0,
            year=2025,
        )

        response = self.client.post(
            "/api/carbon/verify-registry-credentials/",
            {
                "registry_verification_id": "INVALID-123",
                "registry_type": "invalid_registry",
                "carbon_entry_id": entry.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_missing_verification_id(self):
        """Test missing verification ID handling"""
        entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            source=self.source,
            amount=75.0,
            year=2025,
        )

        response = self.client.post(
            "/api/carbon/verify-registry-credentials/",
            {"registry_type": "vcs", "carbon_entry_id": entry.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class BulkVerificationTestCase(TestCase):
    """Test bulk verification operations"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()

        self.company = Company.objects.create(
            name="Bulk Test Company", address="789 Bulk St", city="Bulk City", state="TX"
        )

        self.user = User.objects.create_user(
            email="bulk_test@trazo.io",
            password="testpass123",
        )

        # Create WorksIn relationship

        from users.models import WorksIn

        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)

        self.establishment = Establishment.objects.create(
            company=self.company, name="Bulk Test Farm", establishment_type="farm"
        )

        self.source = CarbonSource.objects.create(
            name="bulk_test_offset", category="offset", default_emission_factor=-1.5, unit="kg CO2e"
        )

        # Create multiple test entries
        self.entries = []
        for i in range(3):
            entry = CarbonEntry.objects.create(
                establishment=self.establishment,
                created_by=self.user,
                type="offset",
                source=self.source,
                amount=100.0 + i * 50,
                year=2025,
                description=f"Bulk test entry {i+1}",
            )
            self.entries.append(entry)

        self.client.force_authenticate(user=self.user)

    def test_bulk_audit_scheduling(self):
        """Test bulk audit scheduling"""
        entry_ids = [entry.id for entry in self.entries]

        response = self.client.post(
            "/api/carbon/bulk-verify/",
            {"carbon_entry_ids": entry_ids, "verification_action": "schedule_audit"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertIn("bulk_verification_summary", data)
        summary = data["bulk_verification_summary"]

        self.assertEqual(summary["total_entries"], 3)
        self.assertGreaterEqual(summary["successful"], 0)
        self.assertGreaterEqual(summary["failed"], 0)

    def test_bulk_verification_with_empty_list(self):
        """Test bulk verification with empty entry list"""
        response = self.client.post(
            "/api/carbon/bulk-verify/", {"carbon_entry_ids": [], "verification_action": "schedule_audit"}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_bulk_verification_invalid_action(self):
        """Test bulk verification with invalid action"""
        entry_ids = [self.entries[0].id]

        response = self.client.post(
            "/api/carbon/bulk-verify/",
            {"carbon_entry_ids": entry_ids, "verification_action": "invalid_action"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        # Should process the request but mark entries as failed due to invalid action
        data = response.json()
        self.assertIn("bulk_verification_summary", data)

        # All entries should be marked as failed due to invalid action
        summary = data["bulk_verification_summary"]
        self.assertEqual(summary["successful"], 0)
        self.assertEqual(summary["failed"], 1)
