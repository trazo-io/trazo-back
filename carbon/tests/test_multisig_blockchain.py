"""
Comprehensive tests for multi-signature blockchain functionality.
Tests security patterns, gas optimization, and multi-sig workflows.
"""

import json
import time
from datetime import timedelta
from unittest.mock import MagicMock, Mock, patch

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

import pytest

# Import the services to test
from ..services.enhanced_multisig_blockchain_service import (
    EnhancedMultiSigBlockchainService,
    InsufficientSignaturesError,
    MultiSigSecurityError,
    ProposalExpiredError,
    UnauthorizedSignerError,
)
from ..services.polygon_security_manager import (
    GasOptimizationError,
    PolygonSecurityError,
    PolygonSecurityManager,
    TransactionSecurityError,
)


class TestEnhancedMultiSigBlockchainService(TestCase):
    """Test enhanced multi-signature blockchain service"""

    def setUp(self):
        """Set up test environment"""
        self.service = EnhancedMultiSigBlockchainService()

        # Mock authorized signers
        self.test_signers = [
            {
                "address": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",
                "role": "admin",
                "name": "Test Admin",
                "created_at": timezone.now().isoformat(),
            },
            {
                "address": "0x8ba1f109551bD432803012645Hac136c02142AC8",
                "role": "operator",
                "name": "Test Operator",
                "created_at": timezone.now().isoformat(),
            },
            {
                "address": "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
                "role": "auditor",
                "name": "Test Auditor",
                "created_at": timezone.now().isoformat(),
            },
        ]

        self.service.authorized_signers = self.test_signers
        self.service.required_signatures = 2

    def test_requires_multisig_approval_carbon_threshold(self):
        """Test multi-sig requirement for carbon amount threshold"""
        # Should require multi-sig for large carbon amounts
        requires_multisig = self.service.requires_multisig_approval(
            operation_type="carbon_record", carbon_amount=2000000, monetary_value=0  # 2000 kg in grams
        )
        self.assertTrue(requires_multisig)

        # Should not require multi-sig for small carbon amounts
        requires_multisig = self.service.requires_multisig_approval(
            operation_type="carbon_record", carbon_amount=500000, monetary_value=0  # 500 kg in grams
        )
        self.assertFalse(requires_multisig)

    def test_requires_multisig_approval_value_threshold(self):
        """Test multi-sig requirement for monetary value threshold"""
        # Should require multi-sig for high-value operations
        requires_multisig = self.service.requires_multisig_approval(
            operation_type="credit_issuance", carbon_amount=0, monetary_value=75000  # $75k
        )
        self.assertTrue(requires_multisig)

    def test_requires_multisig_approval_critical_operations(self):
        """Test multi-sig requirement for critical operations"""
        critical_operations = ["emergency_pause", "emergency_unpause", "contract_upgrade", "signer_management"]

        for operation in critical_operations:
            requires_multisig = self.service.requires_multisig_approval(
                operation_type=operation, carbon_amount=0, monetary_value=0
            )
            self.assertTrue(requires_multisig, f"Operation {operation} should require multi-sig")

    @patch("carbon.services.enhanced_multisig_blockchain_service.secure_key_manager")
    def test_create_multisig_proposal_success(self, mock_secure_key_manager):
        """Test successful multi-sig proposal creation"""
        mock_secure_key_manager.store_secret.return_value = True

        operation_data = {
            "production_id": 123,
            "carbon_data": {"total_emissions": 1000, "total_offsets": 500},
            "carbon_amount": 1500000,  # Above threshold
            "created_by": "test_user",
        }

        result = self.service.create_multisig_proposal(
            operation_type="carbon_record", operation_data=operation_data, priority="normal"
        )

        self.assertTrue(result["success"])
        self.assertIn("proposal_id", result)
        self.assertEqual(result["required_signatures"], 2)
        self.assertEqual(result["priority"], "normal")
        self.assertTrue(mock_secure_key_manager.store_secret.called)

    def test_create_multisig_proposal_emergency_priority(self):
        """Test emergency priority proposal with reduced signature requirements"""
        with patch(
            "carbon.services.enhanced_multisig_blockchain_service.secure_key_manager"
        ) as mock_secure_key_manager:
            mock_secure_key_manager.store_secret.return_value = True

            operation_data = {"emergency_type": "pause", "reason": "Critical vulnerability detected"}

            result = self.service.create_multisig_proposal(
                operation_type="emergency_pause", operation_data=operation_data, priority="emergency"
            )

            # Emergency should require fewer signatures
            self.assertEqual(result["required_signatures"], self.service.emergency_required_signatures)

    @patch("carbon.services.enhanced_multisig_blockchain_service.secure_key_manager")
    def test_sign_proposal_success(self, mock_secure_key_manager):
        """Test successful proposal signing"""
        # Create a mock proposal
        proposal = {
            "proposal_id": "test_proposal_123",
            "operation_type": "carbon_record",
            "operation_data": {"test": "data"},
            "created_at": timezone.now().isoformat(),
            "deadline": (timezone.now() + timedelta(hours=24)).isoformat(),
            "status": "pending",
            "required_signatures": 2,
            "signatures": [],
            "approvals": [],
            "rejections": [],
            "audit_trail": [],
        }

        mock_secure_key_manager.get_secret.return_value = proposal
        mock_secure_key_manager.store_secret.return_value = True

        # Mock signature verification
        with patch.object(self.service, "_verify_signature", return_value=True):
            result = self.service.sign_proposal(
                proposal_id="test_proposal_123",
                signer_address=self.test_signers[0]["address"],
                signature="mock_signature",
                approve=True,
                comment="Approved for testing",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["approval_count"], 1)
        self.assertEqual(result["status"], "pending")  # Still needs one more signature

    @patch("carbon.services.enhanced_multisig_blockchain_service.secure_key_manager")
    def test_sign_proposal_auto_approve(self, mock_secure_key_manager):
        """Test proposal auto-approval when sufficient signatures reached"""
        # Create proposal with one existing signature
        proposal = {
            "proposal_id": "test_proposal_456",
            "operation_type": "carbon_record",
            "operation_data": {"test": "data"},
            "created_at": timezone.now().isoformat(),
            "deadline": (timezone.now() + timedelta(hours=24)).isoformat(),
            "status": "pending",
            "required_signatures": 2,
            "signatures": [
                {
                    "signer_address": self.test_signers[0]["address"],
                    "approve": True,
                    "timestamp": timezone.now().isoformat(),
                }
            ],
            "approvals": [self.test_signers[0]["address"]],
            "rejections": [],
            "audit_trail": [],
        }

        mock_secure_key_manager.get_secret.return_value = proposal
        mock_secure_key_manager.store_secret.return_value = True

        # Mock execution
        with patch.object(self.service, "_verify_signature", return_value=True):
            with patch.object(self.service, "_execute_approved_proposal") as mock_execute:
                mock_execute.return_value = {"success": True, "transaction_hash": "0xtest"}

                result = self.service.sign_proposal(
                    proposal_id="test_proposal_456",
                    signer_address=self.test_signers[1]["address"],
                    signature="mock_signature_2",
                    approve=True,
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["approval_count"], 2)
        self.assertEqual(result["status"], "approved")
        self.assertTrue(result["can_execute"])

    def test_sign_proposal_unauthorized_signer(self):
        """Test signing with unauthorized signer address"""
        proposal = {
            "proposal_id": "test_proposal_789",
            "operation_type": "carbon_record",
            "status": "pending",
            "deadline": (timezone.now() + timedelta(hours=24)).isoformat(),
            "signatures": [],
            "audit_trail": [],
        }

        with patch(
            "carbon.services.enhanced_multisig_blockchain_service.secure_key_manager"
        ) as mock_secure_key_manager:
            mock_secure_key_manager.get_secret.return_value = proposal

            with self.assertRaises(UnauthorizedSignerError):
                self.service.sign_proposal(
                    proposal_id="test_proposal_789",
                    signer_address="0xUnauthorizedAddress",
                    signature="mock_signature",
                    approve=True,
                )

    def test_sign_proposal_expired(self):
        """Test signing expired proposal"""
        expired_proposal = {
            "proposal_id": "test_proposal_expired",
            "operation_type": "carbon_record",
            "status": "pending",
            "deadline": (timezone.now() - timedelta(hours=1)).isoformat(),  # Expired
            "signatures": [],
            "audit_trail": [],
        }

        with patch(
            "carbon.services.enhanced_multisig_blockchain_service.secure_key_manager"
        ) as mock_secure_key_manager:
            mock_secure_key_manager.get_secret.return_value = expired_proposal

            with self.assertRaises(ProposalExpiredError):
                self.service.sign_proposal(
                    proposal_id="test_proposal_expired",
                    signer_address=self.test_signers[0]["address"],
                    signature="mock_signature",
                    approve=True,
                )

    def test_assess_operation_risk(self):
        """Test operation risk assessment"""
        # Test high-risk operation
        high_risk_data = {
            "carbon_amount": 15000000,  # 15 tons
            "monetary_value_usd": 200000,  # $200k
            "batch_size": 150,
        }

        risk_level = self.service._assess_operation_risk("emergency_pause", high_risk_data)
        self.assertEqual(risk_level, "critical")

        # Test low-risk operation
        low_risk_data = {"carbon_amount": 100000, "monetary_value_usd": 1000, "batch_size": 5}  # 100 kg  # $1k

        risk_level = self.service._assess_operation_risk("carbon_record", low_risk_data)
        self.assertEqual(risk_level, "low")

    def test_validate_signer_data(self):
        """Test signer data validation"""
        # Valid signer
        valid_signer = {"address": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4", "role": "admin", "name": "Test Admin"}
        self.assertTrue(self.service._validate_signer_data(valid_signer))

        # Invalid signer - missing required field
        invalid_signer = {
            "address": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",
            "role": "admin",
            # Missing 'name'
        }
        self.assertFalse(self.service._validate_signer_data(invalid_signer))

        # Invalid signer - invalid role
        invalid_role_signer = {
            "address": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",
            "role": "invalid_role",
            "name": "Test Admin",
        }
        self.assertFalse(self.service._validate_signer_data(invalid_role_signer))

    def test_generate_proposal_id(self):
        """Test proposal ID generation"""
        operation_data = {"test": "data", "timestamp": 123456}

        proposal_id_1 = self.service._generate_proposal_id("carbon_record", operation_data)
        proposal_id_2 = self.service._generate_proposal_id("carbon_record", operation_data)

        # IDs should be different due to timestamp
        self.assertNotEqual(proposal_id_1, proposal_id_2)
        self.assertEqual(len(proposal_id_1), 64)  # SHA-256 hash length


class TestPolygonSecurityManager(TestCase):
    """Test Polygon network security manager"""

    def setUp(self):
        """Set up test environment"""
        self.security_manager = PolygonSecurityManager()

    def test_get_optimal_gas_params_standard(self):
        """Test optimal gas parameter calculation for standard transactions"""
        gas_params = self.security_manager.get_optimal_gas_params(transaction_type="standard", priority="normal")

        self.assertIn("gasLimit", gas_params)
        self.assertIn("maxFeePerGas", gas_params)
        self.assertIn("maxPriorityFeePerGas", gas_params)
        self.assertIn("estimatedCost", gas_params)
        self.assertGreater(gas_params["gasLimit"], 0)
        self.assertGreater(gas_params["maxFeePerGas"], 0)

    def test_get_optimal_gas_params_high_priority(self):
        """Test gas parameters for high priority transactions"""
        normal_params = self.security_manager.get_optimal_gas_params(transaction_type="standard", priority="normal")

        high_priority_params = self.security_manager.get_optimal_gas_params(
            transaction_type="standard", priority="high"
        )

        # High priority should have higher gas prices
        self.assertGreater(high_priority_params["maxFeePerGas"], normal_params["maxFeePerGas"])

    def test_get_optimal_gas_params_complex_transaction(self):
        """Test gas parameters for complex transactions"""
        complex_params = self.security_manager.get_optimal_gas_params(transaction_type="complex", priority="normal")

        standard_params = self.security_manager.get_optimal_gas_params(transaction_type="standard", priority="normal")

        # Complex transactions should have higher gas limits
        self.assertGreater(complex_params["gasLimit"], standard_params["gasLimit"])

    @patch("carbon.services.polygon_security_manager.cache")
    def test_analyze_network_conditions(self, mock_cache):
        """Test network conditions analysis"""
        mock_cache.get.return_value = None
        mock_cache.set.return_value = True

        conditions = self.security_manager._analyze_network_conditions()

        self.assertIn("congestion_level", conditions)
        self.assertIn("average_gas_price_gwei", conditions)
        self.assertIn("network_utilization", conditions)
        self.assertIn("timestamp", conditions)

    def test_validate_gas_prices_valid(self):
        """Test gas price validation with valid prices"""
        valid_gas_prices = {
            "max_fee_per_gas": int(30e9),  # 30 GWEI in wei
            "max_priority_fee_per_gas": int(2e9),  # 2 GWEI in wei
        }

        # Should not raise exception
        try:
            self.security_manager._validate_gas_prices(valid_gas_prices)
        except GasOptimizationError:
            self.fail("validate_gas_prices raised GasOptimizationError with valid prices")

    def test_validate_gas_prices_too_high(self):
        """Test gas price validation with excessively high prices"""
        high_gas_prices = {
            "max_fee_per_gas": int(200e9),  # 200 GWEI in wei (too high)
            "max_priority_fee_per_gas": int(2e9),  # 2 GWEI in wei
        }

        with self.assertRaises(GasOptimizationError):
            self.security_manager._validate_gas_prices(high_gas_prices)

    def test_estimate_transaction_cost(self):
        """Test transaction cost estimation"""
        gas_limit = 100000
        max_fee_per_gas = int(30e9)  # 30 GWEI in wei

        cost_estimate = self.security_manager._estimate_transaction_cost(gas_limit, max_fee_per_gas)

        self.assertIn("matic", cost_estimate)
        self.assertIn("usd", cost_estimate)
        self.assertIn("wei", cost_estimate)
        self.assertGreater(cost_estimate["matic"], 0)
        self.assertGreater(cost_estimate["usd"], 0)

    @patch("carbon.services.polygon_security_manager.secure_key_manager")
    def test_secure_transaction_preparation(self, mock_secure_key_manager):
        """Test secure transaction preparation"""
        # Mock private key
        mock_private_key = "0x" + "a" * 64  # Mock private key
        mock_secure_key_manager.get_blockchain_private_key.return_value = mock_private_key

        transaction_data = {
            "to": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",
            "value": 0,
            "data": "0x",
            "type": "standard",
            "priority": "normal",
        }

        with patch("carbon.services.polygon_security_manager.Account") as mock_account:
            mock_account_instance = Mock()
            mock_account_instance.address = "0x123456789"
            mock_account.from_key.return_value = mock_account_instance

            with patch.object(self.security_manager, "_get_secure_nonce", return_value=1):
                result = self.security_manager.secure_transaction_preparation(transaction_data)

        self.assertIn("transaction", result)
        self.assertIn("account", result)
        self.assertIn("estimated_cost", result)
        self.assertTrue(result["security_measures_applied"])

    def test_validate_transaction_security_valid(self):
        """Test transaction security validation with valid data"""
        valid_transaction = {"to": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4", "value": 100, "data": "0x"}

        sender_address = "0x8ba1f109551bD432803012645Hac136c02142AC8"

        # Should not raise exception
        try:
            self.security_manager._validate_transaction_security(valid_transaction, sender_address)
        except TransactionSecurityError:
            self.fail("Transaction security validation failed for valid transaction")

    def test_validate_transaction_security_invalid_recipient(self):
        """Test transaction security validation with invalid recipient"""
        invalid_transaction = {"to": "invalid_address", "value": 100, "data": "0x"}

        sender_address = "0x8ba1f109551bD432803012645Hac136c02142AC8"

        with self.assertRaises(TransactionSecurityError):
            self.security_manager._validate_transaction_security(invalid_transaction, sender_address)

    def test_validate_transaction_security_negative_value(self):
        """Test transaction security validation with negative value"""
        invalid_transaction = {
            "to": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",
            "value": -100,  # Negative value
            "data": "0x",
        }

        sender_address = "0x8ba1f109551bD432803012645Hac136c02142AC8"

        with self.assertRaises(TransactionSecurityError):
            self.security_manager._validate_transaction_security(invalid_transaction, sender_address)

    def test_circuit_breaker_activation(self):
        """Test circuit breaker activation after multiple failures"""
        # Simulate multiple transaction failures
        for i in range(self.security_manager.max_failed_transactions):
            self.security_manager._handle_transaction_failure(Exception(f"Test failure {i+1}"))

        # Circuit breaker should be active
        self.assertTrue(self.security_manager._is_circuit_breaker_active())

    def test_circuit_breaker_reset(self):
        """Test circuit breaker reset functionality"""
        # Activate circuit breaker
        self.security_manager._activate_circuit_breaker()
        self.assertTrue(self.security_manager._is_circuit_breaker_active())

        # Reset circuit breaker
        result = self.security_manager.force_reset_circuit_breaker()
        self.assertTrue(result)
        self.assertFalse(self.security_manager._is_circuit_breaker_active())

    def test_get_security_status(self):
        """Test security status reporting"""
        status = self.security_manager.get_security_status()

        self.assertIn("circuit_breaker_active", status)
        self.assertIn("failed_transaction_count", status)
        self.assertIn("security_features", status)
        self.assertIn("network", status)
        self.assertIn("thresholds", status)

    def test_calculate_gas_efficiency(self):
        """Test gas efficiency calculation"""
        # Test excellent efficiency
        efficiency = self.security_manager._calculate_gas_efficiency(50000)
        self.assertEqual(efficiency, "excellent")

        # Test good efficiency
        efficiency = self.security_manager._calculate_gas_efficiency(200000)
        self.assertEqual(efficiency, "good")

        # Test high consumption
        efficiency = self.security_manager._calculate_gas_efficiency(800000)
        self.assertEqual(efficiency, "high_consumption")

    def test_get_safe_gas_defaults(self):
        """Test safe gas defaults for different transaction types"""
        defaults = self.security_manager._get_safe_gas_defaults("standard")

        self.assertIn("gasLimit", defaults)
        self.assertIn("maxFeePerGas", defaults)
        self.assertIn("maxPriorityFeePerGas", defaults)
        self.assertTrue(defaults["safeDefaults"])

    def test_chain_id_mapping(self):
        """Test chain ID mapping for different networks"""
        # Test different network configurations
        test_cases = [
            ("polygon_mainnet", 137),
            ("polygon_amoy", 80002),
            ("polygon_mumbai", 80001),
            ("unknown_network", 80002),  # Should default to Amoy
        ]

        for network, expected_chain_id in test_cases:
            self.security_manager.network_name = network
            chain_id = self.security_manager._get_chain_id()
            self.assertEqual(chain_id, expected_chain_id)


class TestMultiSigIntegration(TestCase):
    """Integration tests for multi-sig with carbon operations"""

    def setUp(self):
        """Set up integration test environment"""
        self.multisig_service = EnhancedMultiSigBlockchainService()
        self.security_manager = PolygonSecurityManager()

    @patch("carbon.services.enhanced_multisig_blockchain_service.secure_key_manager")
    def test_carbon_record_multisig_flow(self, mock_secure_key_manager):
        """Test complete multi-sig flow for carbon record creation"""
        mock_secure_key_manager.store_secret.return_value = True
        mock_secure_key_manager.get_secret.return_value = None

        # Test data that should trigger multi-sig
        carbon_data = {
            "total_emissions": 2000,  # 2000 kg = 2,000,000 grams (above threshold)
            "total_offsets": 500,
            "crop_type": "avocado",
            "created_by": "test_farmer",
        }

        # Create carbon record should trigger multi-sig proposal
        result = self.multisig_service.create_carbon_record(123, carbon_data)

        self.assertTrue(result["multisig_required"])
        self.assertIn("proposal_id", result)
        self.assertEqual(result["status"], "pending_approval")

    @patch("carbon.services.enhanced_multisig_blockchain_service.secure_key_manager")
    def test_credit_issuance_multisig_flow(self, mock_secure_key_manager):
        """Test complete multi-sig flow for credit issuance"""
        mock_secure_key_manager.store_secret.return_value = True

        # Test credit issuance that should trigger multi-sig
        result = self.multisig_service.issue_carbon_credits(
            production_id=123,
            credits=150.0,  # 150 kg = 150,000 grams (above threshold)
            value_usd=75000,  # Above value threshold
        )

        self.assertTrue(result["multisig_required"])
        self.assertIn("proposal_id", result)
        self.assertEqual(result["status"], "pending_approval")

    def test_gas_optimization_with_multisig(self):
        """Test gas optimization for multi-sig transactions"""
        # Get gas parameters for multi-sig transaction
        gas_params = self.security_manager.get_optimal_gas_params(transaction_type="multisig", priority="high")

        self.assertGreater(gas_params["gasLimit"], 200000)  # Multi-sig should have higher gas limit
        self.assertIn("estimatedCost", gas_params)

    def test_security_validation_integration(self):
        """Test security validation integration between services"""
        # Test that security manager validates multi-sig transaction data
        multisig_transaction = {
            "to": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",
            "value": 0,
            "data": "0xa9059cbb...",  # Multi-sig function call
            "type": "multisig",
            "priority": "high",
        }

        # Should not raise security errors for valid multi-sig transaction
        try:
            self.security_manager._validate_transaction_security(
                multisig_transaction, "0x8ba1f109551bD432803012645Hac136c02142AC8"
            )
        except TransactionSecurityError:
            self.fail("Security validation failed for valid multi-sig transaction")


if __name__ == "__main__":
    pytest.main([__file__])
