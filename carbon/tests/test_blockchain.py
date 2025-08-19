"""
Test Suite for Blockchain Verification
Ensures blockchain integration is production-ready and secure
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from carbon.models import CarbonEntry, CarbonReport, CarbonSource
from carbon.services.blockchain import BlockchainCarbonService, BlockchainOperationError, BlockchainUnavailableError
from company.models import Company, Establishment

User = get_user_model()


class TestBlockchainServiceInitialization(TestCase):
    """Test blockchain service initialization and configuration"""

    @override_settings(
        BLOCKCHAIN_ENABLED=True,
        POLYGON_RPC_URL="https://rpc-amoy.polygon.technology/",
        CARBON_CONTRACT_ADDRESS="0x1234567890123456789012345678901234567890",
        ENVIRONMENT="production",
        DEBUG=False,
    )
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", True)
    @patch("carbon.services.blockchain.Web3")
    @patch("carbon.services.blockchain.get_secure_blockchain_key")
    def test_production_initialization_success(self, mock_get_key, mock_web3_class):
        """Test successful blockchain initialization in production"""
        # Mock Web3 connection
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_web3_class.return_value = mock_web3

        # Mock private key
        mock_get_key.return_value = "0x" + "1" * 64

        # Mock account
        mock_account = MagicMock()
        mock_account.address = "0xabcdef1234567890abcdef1234567890abcdef12"
        mock_web3.eth.account.from_key.return_value = mock_account

        # Mock contract
        mock_contract = MagicMock()
        mock_web3.eth.contract.return_value = mock_contract

        # Initialize service
        service = BlockchainCarbonService()

        self.assertTrue(service.production_mode)
        self.assertTrue(service.blockchain_required)
        self.assertIsNotNone(service.web3)
        self.assertIsNotNone(service.contract)
        self.assertIsNotNone(service.account)

    @override_settings(BLOCKCHAIN_ENABLED=False, ENVIRONMENT="production", DEBUG=False)
    def test_production_initialization_failure_disabled(self):
        """Test blockchain initialization failure when disabled in production"""
        with self.assertRaises(BlockchainUnavailableError):
            BlockchainCarbonService()

    @override_settings(BLOCKCHAIN_ENABLED=True, POLYGON_RPC_URL=None, ENVIRONMENT="production", DEBUG=False)
    def test_production_initialization_failure_no_rpc(self):
        """Test blockchain initialization failure when no RPC URL in production"""
        with self.assertRaises(BlockchainUnavailableError):
            BlockchainCarbonService()

    @override_settings(
        BLOCKCHAIN_ENABLED=True,
        POLYGON_RPC_URL="https://rpc-amoy.polygon.technology/",
        ENVIRONMENT="development",
        DEBUG=True,
    )
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", False)
    def test_development_initialization_graceful_degradation(self):
        """Test graceful degradation in development when Web3 unavailable"""
        # Should not raise error in development
        service = BlockchainCarbonService()

        self.assertFalse(service.production_mode)
        self.assertFalse(service.blockchain_required)
        self.assertIsNone(service.web3)


class TestBlockchainCarbonVerification(TransactionTestCase):
    """Test blockchain carbon verification functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA")

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Establishment", address="123 Test St", country="USA"
        )

        self.carbon_source = CarbonSource.objects.create(
            name="Test Emissions", unit="kg CO2e", category="Test", default_emission_factor=1.0
        )

        self.carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=1000.0,
            year=2024,
        )

    @override_settings(
        BLOCKCHAIN_ENABLED=True,
        POLYGON_RPC_URL="https://rpc-amoy.polygon.technology/",
        CARBON_CONTRACT_ADDRESS="0x1234567890123456789012345678901234567890",
        ENVIRONMENT="development",
    )
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", True)
    @patch("carbon.services.blockchain.Web3")
    @patch("carbon.services.blockchain.get_secure_blockchain_key")
    def test_carbon_record_verification_success(self, mock_get_key, mock_web3_class):
        """Test successful carbon record verification on blockchain"""
        # Mock Web3 connection
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_web3_class.return_value = mock_web3

        # Mock private key and account
        mock_get_key.return_value = "0x" + "1" * 64
        mock_account = MagicMock()
        mock_account.address = "0xabcdef1234567890abcdef1234567890abcdef12"
        mock_web3.eth.account.from_key.return_value = mock_account

        # Mock contract and transaction
        mock_contract = MagicMock()
        mock_web3.eth.contract.return_value = mock_contract

        # Mock transaction receipt
        mock_receipt = {"transactionHash": "0xabcdef123456789", "status": 1, "gasUsed": 150000, "blockNumber": 12345}
        mock_web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        # Mock gas estimation and transaction building
        mock_contract.functions.verifyCarbonRecord.return_value.estimateGas.return_value = 150000
        mock_transaction = {
            "to": "0x1234567890123456789012345678901234567890",
            "data": "0xabcdef",
            "gas": 150000,
            "gasPrice": 30000000000,
            "nonce": 1,
        }
        mock_contract.functions.verifyCarbonRecord.return_value.buildTransaction.return_value = mock_transaction

        # Mock signed transaction
        mock_signed = MagicMock()
        mock_signed.rawTransaction = b"signed_tx_data"
        mock_web3.eth.account.sign_transaction.return_value = mock_signed

        # Mock transaction hash
        mock_web3.eth.send_raw_transaction.return_value = b"tx_hash"

        # Initialize service and verify record
        service = BlockchainCarbonService()
        result = service.create_carbon_verification(self.carbon_entry)

        self.assertTrue(result["success"])
        self.assertIn("transaction_hash", result)
        self.assertIn("block_number", result)
        self.assertEqual(result["status"], "verified")

    @override_settings(BLOCKCHAIN_ENABLED=False)
    def test_verification_when_blockchain_disabled(self):
        """Test verification behavior when blockchain is disabled"""
        service = BlockchainCarbonService()

        result = service.create_carbon_verification(self.carbon_entry)

        # Should return mock success in development
        self.assertIn("success", result)
        if not result["success"]:
            self.assertIn("error", result)
            self.assertIn("blockchain not available", result["error"])

    @override_settings(
        BLOCKCHAIN_ENABLED=True,
        POLYGON_RPC_URL="https://rpc-amoy.polygon.technology/",
        CARBON_CONTRACT_ADDRESS="0x1234567890123456789012345678901234567890",
        ENVIRONMENT="development",
    )
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", True)
    @patch("carbon.services.blockchain.Web3")
    @patch("carbon.services.blockchain.get_secure_blockchain_key")
    def test_verification_transaction_failure(self, mock_get_key, mock_web3_class):
        """Test handling of transaction failures"""
        # Mock Web3 connection
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_web3_class.return_value = mock_web3

        # Mock private key and account
        mock_get_key.return_value = "0x" + "1" * 64
        mock_account = MagicMock()
        mock_web3.eth.account.from_key.return_value = mock_account

        # Mock contract
        mock_contract = MagicMock()
        mock_web3.eth.contract.return_value = mock_contract

        # Mock transaction failure
        mock_web3.eth.send_raw_transaction.side_effect = Exception("Transaction failed")

        # Initialize service
        service = BlockchainCarbonService()

        result = service.create_carbon_verification(self.carbon_entry)

        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_data_integrity_validation(self):
        """Test carbon data integrity validation"""
        service = BlockchainCarbonService()

        # Test with valid carbon entry
        is_valid = service._validate_carbon_data(self.carbon_entry)
        self.assertTrue(is_valid)

        # Test with invalid carbon entry (negative amount)
        invalid_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=-100.0,  # Invalid negative amount
            year=2024,
        )

        is_valid = service._validate_carbon_data(invalid_entry)
        self.assertFalse(is_valid)


class TestBlockchainBatchOperations(TransactionTestCase):
    """Test blockchain batch operations for efficiency"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA")

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Establishment", address="123 Test St", country="USA"
        )

        self.carbon_source = CarbonSource.objects.create(
            name="Test Emissions", unit="kg CO2e", category="Test", default_emission_factor=1.0
        )

        # Create multiple carbon entries for batch testing
        self.carbon_entries = []
        for i in range(5):
            entry = CarbonEntry.objects.create(
                establishment=self.establishment,
                created_by=self.user,
                type="emission",
                source=self.carbon_source,
                amount=100.0 * (i + 1),
                year=2024,
                description=f"Test emission {i + 1}",
            )
            self.carbon_entries.append(entry)

    @override_settings(BLOCKCHAIN_ENABLED=True, BLOCKCHAIN_BATCH_SIZE_LIMIT=3, ENVIRONMENT="development")
    @patch("carbon.services.blockchain.WEB3_AVAILABLE", True)
    @patch("carbon.services.blockchain.Web3")
    @patch("carbon.services.blockchain.get_secure_blockchain_key")
    def test_batch_verification_success(self, mock_get_key, mock_web3_class):
        """Test successful batch verification of multiple records"""
        # Mock Web3 connection
        mock_web3 = MagicMock()
        mock_web3.is_connected.return_value = True
        mock_web3_class.return_value = mock_web3

        # Mock private key and account
        mock_get_key.return_value = "0x" + "1" * 64
        mock_account = MagicMock()
        mock_web3.eth.account.from_key.return_value = mock_account

        # Mock contract
        mock_contract = MagicMock()
        mock_web3.eth.contract.return_value = mock_contract

        # Mock successful batch transaction
        mock_receipt = {"transactionHash": "0xbatch123456789", "status": 1, "gasUsed": 300000, "blockNumber": 12346}
        mock_web3.eth.wait_for_transaction_receipt.return_value = mock_receipt

        # Initialize service
        service = BlockchainCarbonService()

        # Test batch verification
        result = service.batch_verify_carbon_records(self.carbon_entries)

        # Should split into batches due to batch size limit
        self.assertTrue(result["success"])
        self.assertIn("batches_processed", result)
        self.assertGreater(result["batches_processed"], 1)  # Should be split into multiple batches

    def test_batch_size_limits(self):
        """Test batch size limit enforcement"""
        service = BlockchainCarbonService()

        # Test batch splitting
        batches = service._split_into_batches(self.carbon_entries, batch_size=2)

        self.assertEqual(len(batches), 3)  # 5 items split into batches of 2
        self.assertEqual(len(batches[0]), 2)
        self.assertEqual(len(batches[1]), 2)
        self.assertEqual(len(batches[2]), 1)

    def test_gas_optimization(self):
        """Test gas price optimization"""
        service = BlockchainCarbonService()

        # Test gas price calculation
        mock_web3 = MagicMock()
        mock_web3.eth.gas_price = 50000000000  # 50 gwei
        service.web3 = mock_web3

        optimized_price = service._calculate_optimal_gas_price()

        # Should not exceed maximum gas price
        max_gas_price = getattr(service, "max_gas_price", 100000000000)  # 100 gwei
        self.assertLessEqual(optimized_price, max_gas_price)


class TestBlockchainSecurity(TestCase):
    """Test blockchain security features"""

    @override_settings(
        BLOCKCHAIN_MULTISIG_ENABLED=True,
        BLOCKCHAIN_REQUIRED_SIGNATURES=2,
        BLOCKCHAIN_SIGNERS=["0xsigner1", "0xsigner2", "0xsigner3"],
    )
    def test_multisig_configuration(self):
        """Test multi-signature wallet configuration"""
        service = BlockchainCarbonService()

        # Check multisig settings
        self.assertTrue(service.multisig_enabled)
        self.assertEqual(service.required_signatures, 2)
        self.assertEqual(len(service.authorized_signers), 3)

    def test_key_security_validation(self):
        """Test private key security validation"""
        service = BlockchainCarbonService()

        # Test valid key format
        valid_key = "0x" + "1" * 64
        self.assertTrue(service._validate_private_key(valid_key))

        # Test invalid key formats
        invalid_keys = [
            "1" * 64,  # Missing 0x prefix
            "0x" + "1" * 63,  # Too short
            "0x" + "1" * 65,  # Too long
            "0xgg" + "1" * 62,  # Invalid hex characters
        ]

        for invalid_key in invalid_keys:
            self.assertFalse(service._validate_private_key(invalid_key))

    def test_transaction_replay_protection(self):
        """Test transaction replay attack protection"""
        service = BlockchainCarbonService()

        # Mock transaction data
        tx_data = {
            "establishment_id": self.establishment.id if hasattr(self, "establishment") else 1,
            "carbon_amount": 1000.0,
            "timestamp": timezone.now().isoformat(),
            "hash": "test_hash_123",
        }

        # Test nonce inclusion
        prepared_data = service._prepare_transaction_data(tx_data)

        self.assertIn("nonce", prepared_data)
        self.assertIn("timestamp", prepared_data)
        self.assertIn("chain_id", prepared_data)

    def test_data_integrity_protection(self):
        """Test data integrity protection mechanisms"""
        service = BlockchainCarbonService()

        # Test data hashing
        test_data = {"amount": 1000.0, "type": "emission", "timestamp": "2024-01-01T00:00:00Z"}

        hash1 = service._calculate_data_hash(test_data)
        hash2 = service._calculate_data_hash(test_data)

        # Same data should produce same hash
        self.assertEqual(hash1, hash2)

        # Modified data should produce different hash
        modified_data = {**test_data, "amount": 1001.0}
        hash3 = service._calculate_data_hash(modified_data)

        self.assertNotEqual(hash1, hash3)


class TestBlockchainErrorHandling(TestCase):
    """Test blockchain error handling and recovery"""

    def test_network_connectivity_handling(self):
        """Test handling of network connectivity issues"""
        service = BlockchainCarbonService()

        # Test connection retry logic
        with patch.object(service, "_check_network_connection") as mock_check:
            mock_check.side_effect = [False, False, True]  # Fail twice, then succeed

            # Should eventually succeed after retries
            result = service._ensure_network_connection(max_retries=3)
            self.assertTrue(result)
            self.assertEqual(mock_check.call_count, 3)

    def test_transaction_timeout_handling(self):
        """Test handling of transaction timeouts"""
        service = BlockchainCarbonService()

        # Mock timeout scenario
        with patch.object(service, "_wait_for_confirmation") as mock_wait:
            mock_wait.side_effect = TimeoutError("Transaction confirmation timeout")

            # Should handle timeout gracefully
            result = service._handle_transaction_timeout("0xtest123")

            self.assertIn("status", result)
            self.assertEqual(result["status"], "pending")
            self.assertIn("retry_recommended", result)

    def test_gas_price_spike_handling(self):
        """Test handling of gas price spikes"""
        service = BlockchainCarbonService()

        # Mock high gas prices
        mock_web3 = MagicMock()
        mock_web3.eth.gas_price = 200000000000  # 200 gwei (very high)
        service.web3 = mock_web3

        # Should implement gas price protection
        result = service._check_gas_price_limits()

        self.assertIn("gas_price_warning", result)
        self.assertTrue(result["gas_price_warning"])


if __name__ == "__main__":
    unittest.main()
