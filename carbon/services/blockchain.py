import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

from django.conf import settings
from django.utils import timezone

from history.custom_fields import get_custom_fields_for_blockchain_hash

try:
    from web3 import Web3

    WEB3_AVAILABLE = True
except ImportError:
    Web3 = None
    WEB3_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.critical("web3 library not installed. Blockchain functionality unavailable.")

from .secure_key_management import get_secure_blockchain_key


class BlockchainUnavailableError(Exception):
    """Raised when blockchain is required but unavailable"""


class BlockchainOperationError(Exception):
    """Raised when blockchain operation fails"""


class BlockchainCarbonService:
    """
    Service for recording production data hashes on the Polygon blockchain.

    The contract (TransparencyVerification.sol) stores only:
      - productionId → dataHash + timestamp

    All other production data (carbon, events, etc.) lives in Trazo's database.
    The on-chain hash proves data hasn't been tampered with after submission.
    """

    def __init__(self):
        self.web3 = None
        self.contract = None
        self.account = None

        environment = getattr(settings, "ENVIRONMENT", "development").lower()
        debug_mode = getattr(settings, "DEBUG", True)
        force_blockchain = getattr(settings, "FORCE_BLOCKCHAIN_VERIFICATION", False)

        self.production_mode = environment == "production" and debug_mode is False
        blockchain_enabled = getattr(settings, "BLOCKCHAIN_ENABLED", False)
        self.blockchain_required = (self.production_mode and blockchain_enabled) or force_blockchain

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            "Blockchain init: env=%s, debug=%s, prod_mode=%s, required=%s",
            environment,
            debug_mode,
            self.production_mode,
            self.blockchain_required,
        )

        self.network_name = getattr(settings, "BLOCKCHAIN_NETWORK_NAME", "polygon_amoy")
        self.explorer_url = getattr(settings, "POLYGON_EXPLORER_URL", "https://amoy.polygonscan.com")

        self._initialize_blockchain_connection()

    # ------------------------------------------------------------------
    # Connection setup
    # ------------------------------------------------------------------

    def _initialize_blockchain_connection(self):
        """Initialize blockchain connection with proper error handling."""
        try:
            if not WEB3_AVAILABLE:
                self._handle_unavailable("Web3 library not available")
                return

            if not getattr(settings, "BLOCKCHAIN_ENABLED", False):
                self._handle_unavailable("Blockchain disabled in settings")
                return

            if not getattr(settings, "POLYGON_RPC_URL", ""):
                self._handle_unavailable("No blockchain RPC URL configured")
                return

            self.web3 = Web3(Web3.HTTPProvider(settings.POLYGON_RPC_URL))

            if not self.web3.is_connected():
                self._handle_unavailable(f"Failed to connect to {self.network_name}")
                return

            self.logger.info("Connected to %s: %s", self.network_name, settings.POLYGON_RPC_URL)

            contract_address = getattr(settings, "CARBON_CONTRACT_ADDRESS", "")
            if not contract_address:
                self._handle_unavailable("No contract address configured")
                return

            contract_abi = self._load_contract_abi()
            if not contract_abi:
                contract_abi = self._get_fallback_abi()

            self.contract = self.web3.eth.contract(address=contract_address, abi=contract_abi)
            self.logger.info("Contract loaded at: %s", contract_address)

            try:
                blockchain_private_key = get_secure_blockchain_key()
                if blockchain_private_key:
                    self.account = self.web3.eth.account.from_key(blockchain_private_key)
                    self.logger.info("Wallet connected: %s", self.account.address)
                else:
                    raise ValueError("No blockchain private key available")
            except Exception as e:
                self._handle_unavailable(f"Failed to load private key: {e}")

        except BlockchainUnavailableError:
            raise
        except Exception as e:
            self._handle_unavailable(f"Blockchain initialization failed: {e}")

    def _handle_unavailable(self, msg: str):
        """Log warning or raise error depending on whether blockchain is required."""
        if self.blockchain_required:
            raise BlockchainUnavailableError(msg)
        self.logger.warning(msg)

    def _is_blockchain_ready(self) -> bool:
        """Check if blockchain service is ready for operations."""
        return (
            self.web3 is not None
            and self.web3.is_connected()
            and self.contract is not None
            and self.account is not None
        )

    def _load_contract_abi(self) -> Optional[list]:
        """Load ABI from the contract JSON file."""
        try:
            from pathlib import Path

            # Try new contract first, fall back to legacy
            for filename in ("TransparencyVerification.json", "CarbonVerification.json"):
                contract_file = Path(__file__).parent.parent / "contracts" / filename
                if contract_file.exists():
                    with open(contract_file, "r") as f:
                        contract_data = json.load(f)
                        if "abi" in contract_data:
                            abi = contract_data["abi"]
                            if isinstance(abi, str):
                                return json.loads(abi)
                            return abi
            return None
        except Exception as e:
            self.logger.error("Error loading contract ABI: %s", e)
            return None

    def _get_fallback_abi(self) -> list:
        """Fallback ABI matching TransparencyVerification.sol."""
        return [
            {
                "inputs": [
                    {"name": "productionId", "type": "uint256"},
                    {"name": "dataHash", "type": "bytes32"},
                ],
                "name": "recordProduction",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            },
            {
                "inputs": [{"name": "productionId", "type": "uint256"}],
                "name": "getRecord",
                "outputs": [
                    {"name": "dataHash", "type": "bytes32"},
                    {"name": "timestamp", "type": "uint256"},
                ],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [
                    {"name": "productionId", "type": "uint256"},
                    {"name": "hash", "type": "bytes32"},
                ],
                "name": "verifyHash",
                "outputs": [{"name": "matches", "type": "bool"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [{"name": "productionId", "type": "uint256"}],
                "name": "hasRecord",
                "outputs": [{"name": "exists", "type": "bool"}],
                "stateMutability": "view",
                "type": "function",
            },
            {
                "inputs": [],
                "name": "totalRecords",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            },
        ]

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def hash_production_data(self, data: Dict[str, Any]) -> str:
        """
        Create a keccak256 hash of production data for blockchain storage.
        Falls back to SHA-256 in development when web3 is unavailable.
        """
        hash_input = {
            "production_id": data.get("production_id"),
            "company_id": data.get("company_id"),
            "start_date": data.get("start_date"),
            "finish_date": data.get("finish_date"),
            "finalization_hash": data.get("finalization_hash"),
            "finalization_event_count": data.get("finalization_event_count", 0),
            "total_co2e": str(data.get("total_co2e", 0)),
            "carbon_entry_count": data.get("carbon_entry_count", 0),
        }

        # Include custom fields in hash if present
        custom_fields = data.get("custom_fields", [])
        if custom_fields:
            hash_input["custom_fields"] = get_custom_fields_for_blockchain_hash(custom_fields)

        sorted_data = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))

        if WEB3_AVAILABLE:
            raw_hex = Web3.keccak(text=sorted_data).hex()
            return raw_hex.removeprefix("0x")
        return hashlib.sha256(sorted_data.encode()).hexdigest()

    # Keep old name as alias for backward compatibility
    def hash_carbon_data(self, carbon_data: Dict[str, Any]) -> str:
        """Backward-compatible alias for hash_production_data."""
        return self.hash_production_data(carbon_data)

    # ------------------------------------------------------------------
    # Submit production hash to blockchain
    # ------------------------------------------------------------------

    def submit_production(self, production_id: int, data_hash: str) -> Dict[str, Any]:
        """
        Submit a production's data hash to the blockchain.

        This is the primary submission method. It calls recordProduction(productionId, dataHash)
        on the TransparencyVerification contract.

        Returns dict with transaction_hash, block_number, gas_used, etc.
        """
        try:
            if not self._is_blockchain_ready():
                if self.blockchain_required:
                    raise BlockchainUnavailableError("Blockchain submission requires active connection")
                self.logger.info("Blockchain not ready, using mock for production %s", production_id)
                return self._create_mock_record(production_id, data_hash)

            hash_bytes = bytes.fromhex(data_hash)
            gas_price = int(self.web3.eth.gas_price * 1.2)
            nonce = self.web3.eth.get_transaction_count(self.account.address)

            self.logger.info("Submitting production %s to blockchain (hash=%s...)", production_id, data_hash[:16])

            transaction = self.contract.functions.recordProduction(
                production_id, hash_bytes
            ).build_transaction(
                {
                    "from": self.account.address,
                    "gas": 150000,  # AccessControl + storage ~117K, with buffer
                    "gasPrice": gas_price,
                    "nonce": nonce,
                    "chainId": self.web3.eth.chain_id,
                }
            )

            blockchain_private_key = get_secure_blockchain_key()
            signed_txn = self.web3.eth.account.sign_transaction(transaction, blockchain_private_key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_txn.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            tx_hex = tx_hash.hex() if tx_hash.hex().startswith("0x") else f"0x{tx_hash.hex()}"

            self.logger.info("Production %s submitted: tx=%s, block=%s", production_id, tx_hex, receipt["blockNumber"])

            return {
                "success": True,
                "transaction_hash": tx_hex,
                "data_hash": data_hash,
                "block_number": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
                "production_id": production_id,
                "network": self.network_name,
                "explorer_url": f"{self.explorer_url}/tx/{tx_hex}",
                "blockchain_verified": True,
            }

        except Exception as e:
            self.logger.error("Blockchain submission failed for production %s: %s", production_id, e)
            if self.blockchain_required:
                raise BlockchainOperationError(f"Blockchain submission failed: {e}")
            return None

    # Backward-compatible alias used by tasks.py
    def submit_monthly_summary(self, producer_id, production_id, total_co2e, data_hash, raw_data):
        """Backward-compatible wrapper around submit_production."""
        return self.submit_production(production_id, data_hash)

    # Backward-compatible alias used by management command
    def create_carbon_record(self, production_id: int, carbon_data: Dict[str, Any]) -> Dict[str, Any]:
        """Backward-compatible wrapper: hash data then submit."""
        record_hash = self.hash_production_data(carbon_data)

        if self.blockchain_required and not self._is_blockchain_ready():
            raise BlockchainUnavailableError("Blockchain required but unavailable")

        if self._is_blockchain_ready():
            return self.submit_production(production_id, record_hash)
        else:
            self.logger.warning("Creating mock record for development - production_id: %s", production_id)
            return self._create_mock_record(production_id, record_hash)

    # ------------------------------------------------------------------
    # Read / verify on-chain records
    # ------------------------------------------------------------------

    def read_on_chain_record(self, production_id: int) -> Optional[Dict[str, Any]]:
        """
        Read the on-chain record for a production (free view call, no gas).
        Returns dict with data_hash and timestamp, or None if not found.
        """
        try:
            if not self._is_blockchain_ready():
                self.logger.info("Blockchain not available for on-chain read")
                return None

            result = self.contract.functions.getRecord(production_id).call()
            data_hash_bytes = result[0]
            timestamp = result[1]

            if timestamp == 0:
                return None

            return {
                "data_hash": data_hash_bytes.hex(),
                "timestamp": timestamp,
                "production_id": production_id,
            }

        except Exception as e:
            self.logger.error("Error reading on-chain record for production %s: %s", production_id, e)
            return None

    def verify_on_chain_hash(self, production_id: int, data_hash: str) -> Dict[str, Any]:
        """
        Verify that a data hash matches what's stored on-chain.
        Returns verification result with match status.
        """
        try:
            if not self._is_blockchain_ready():
                if self.blockchain_required:
                    raise BlockchainUnavailableError("Blockchain verification required but unavailable")
                return {"verified": False, "error": "Blockchain not available"}

            hash_bytes = bytes.fromhex(data_hash)
            matches = self.contract.functions.verifyHash(production_id, hash_bytes).call()

            return {
                "verified": matches,
                "production_id": production_id,
                "data_hash": data_hash,
                "blockchain_verified": True,
                "network": self.network_name,
            }

        except Exception as e:
            self.logger.error("Error verifying hash for production %s: %s", production_id, e)
            return {"verified": False, "error": str(e), "blockchain_verified": False}

    # Backward-compatible alias
    def verify_carbon_record(self, production_id: int) -> Dict[str, Any]:
        """Backward-compatible: read record and return verification status."""
        try:
            record = self.read_on_chain_record(production_id)
            if record:
                return {
                    "verified": True,
                    "record_hash": record["data_hash"],
                    "timestamp": record["timestamp"],
                    "blockchain_verified": True,
                    "network": self.network_name,
                }
            return {"verified": False, "blockchain_verified": False}
        except Exception as e:
            self.logger.error("Error verifying record: %s", e)
            return {"verified": False, "error": str(e), "blockchain_verified": False}

    # ------------------------------------------------------------------
    # Development mock
    # ------------------------------------------------------------------

    def _create_mock_record(self, production_id: int, data_hash: str) -> Dict[str, Any]:
        """Create mock blockchain record for development ONLY."""
        if self.production_mode:
            raise BlockchainUnavailableError("Mock records not allowed in production")

        self.logger.warning("DEVELOPMENT: Mock blockchain record for production %s", production_id)
        mock_tx_hash = hashlib.sha256(f"{production_id}_{data_hash}_{int(time.time())}".encode()).hexdigest()

        return {
            "success": True,
            "transaction_hash": f"0x{mock_tx_hash}",
            "data_hash": data_hash,
            "block_number": 12345 + production_id,
            "gas_used": 60000,
            "production_id": production_id,
            "network": f"{self.network_name}_development_mock",
            "explorer_url": f"{self.explorer_url}/tx/0x{mock_tx_hash}",
            "blockchain_verified": False,
            "mock": True,
        }


# Singleton instance
blockchain_service = BlockchainCarbonService()
