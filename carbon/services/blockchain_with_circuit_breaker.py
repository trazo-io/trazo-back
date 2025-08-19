"""
Blockchain Service with Enhanced Circuit Breaker Protection
Provides resilient blockchain interactions with comprehensive failure handling
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .circuit_breaker_enhanced import CircuitBreakerError, blockchain_circuit_breaker, blockchain_fallback_response

logger = logging.getLogger(__name__)

# Import Web3 safely
try:
    from web3 import Web3
    from web3.exceptions import TransactionNotFound

    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    logger.warning("Web3 not available - blockchain functionality limited")


class BlockchainCircuitBreakerService:
    """
    Blockchain service with comprehensive circuit breaker protection

    Features:
    - Circuit breaker protection for all RPC calls
    - Automatic fallback mechanisms
    - Transaction queue management for failures
    - Gas optimization and retry logic
    - Comprehensive error handling and logging
    """

    def __init__(self):
        self.network_name = getattr(settings, "BLOCKCHAIN_NETWORK", "polygon-mainnet")
        self.rpc_url = getattr(settings, "POLYGON_RPC_URL", "https://polygon-rpc.com")
        self.chain_id = getattr(settings, "BLOCKCHAIN_CHAIN_ID", 137)  # Polygon mainnet

        # Contract addresses
        self.carbon_verification_address = getattr(settings, "CARBON_VERIFICATION_CONTRACT", None)
        self.carbon_credit_address = getattr(settings, "CARBON_CREDIT_CONTRACT", None)

        # Initialize Web3 if available
        if WEB3_AVAILABLE:
            try:
                self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
                self.is_connected = self.w3.is_connected()
                logger.info(f"Blockchain service initialized - Connected: {self.is_connected}")
            except Exception as e:
                logger.error(f"Failed to initialize Web3: {e}")
                self.w3 = None
                self.is_connected = False
        else:
            self.w3 = None
            self.is_connected = False

        # Transaction queue for failed operations
        self.failed_tx_queue_key = "blockchain_failed_tx_queue"

    @blockchain_circuit_breaker("get_block_number")
    def get_current_block_number(self) -> int:
        """Get current block number with circuit breaker protection"""
        if not self.is_connected:
            raise Exception("Blockchain not connected")

        return self.w3.eth.block_number

    @blockchain_circuit_breaker("get_gas_price")
    def get_gas_price(self) -> int:
        """Get current gas price with circuit breaker protection"""
        if not self.is_connected:
            raise Exception("Blockchain not connected")

        return self.w3.eth.gas_price

    @blockchain_circuit_breaker("get_transaction_receipt")
    def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get transaction receipt with circuit breaker protection"""
        if not self.is_connected:
            raise Exception("Blockchain not connected")

        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            return dict(receipt) if receipt else None
        except TransactionNotFound:
            return None

    @blockchain_circuit_breaker("get_transaction")
    def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get transaction details with circuit breaker protection"""
        if not self.is_connected:
            raise Exception("Blockchain not connected")

        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            return dict(tx) if tx else None
        except TransactionNotFound:
            return None

    @blockchain_circuit_breaker("estimate_gas")
    def estimate_gas(self, transaction: Dict[str, Any]) -> int:
        """Estimate gas for transaction with circuit breaker protection"""
        if not self.is_connected:
            raise Exception("Blockchain not connected")

        return self.w3.eth.estimate_gas(transaction)

    @blockchain_circuit_breaker("send_transaction")
    def send_transaction(self, transaction: Dict[str, Any]) -> str:
        """Send transaction with circuit breaker protection"""
        if not self.is_connected:
            raise Exception("Blockchain not connected")

        try:
            # Validate transaction
            self._validate_transaction(transaction)

            # Estimate gas if not provided
            if "gas" not in transaction:
                estimated_gas = self.estimate_gas(transaction)
                transaction["gas"] = int(estimated_gas * 1.2)  # Add 20% buffer

            # Send transaction
            tx_hash = self.w3.eth.send_transaction(transaction)

            logger.info(f"Transaction sent successfully: {tx_hash.hex()}")
            return tx_hash.hex()

        except Exception as e:
            logger.error(f"Transaction failed: {e}")
            # Queue transaction for retry
            self._queue_failed_transaction(transaction, str(e))
            raise

    def _validate_transaction(self, transaction: Dict[str, Any]):
        """Validate transaction parameters"""
        required_fields = ["from", "to"]
        for field in required_fields:
            if field not in transaction:
                raise ValueError(f"Missing required transaction field: {field}")

        # Validate addresses
        if not self.w3.is_address(transaction["from"]):
            raise ValueError(f"Invalid from address: {transaction['from']}")

        if not self.w3.is_address(transaction["to"]):
            raise ValueError(f"Invalid to address: {transaction['to']}")

    def _queue_failed_transaction(self, transaction: Dict[str, Any], error: str):
        """Queue failed transaction for retry"""
        try:
            queue = cache.get(self.failed_tx_queue_key, [])

            failed_tx = {
                "transaction": transaction,
                "error": error,
                "timestamp": timezone.now().isoformat(),
                "retry_count": 0,
                "max_retries": 3,
            }

            queue.append(failed_tx)
            cache.set(self.failed_tx_queue_key, queue, 86400)  # 24 hours

            logger.info(f"Queued failed transaction for retry: {len(queue)} in queue")

        except Exception as e:
            logger.error(f"Failed to queue transaction: {e}")

    @blockchain_circuit_breaker("verify_carbon_record")
    def verify_carbon_record(self, carbon_entry_id: int, carbon_data: Dict[str, Any]) -> Dict[str, Any]:
        """Verify carbon record on blockchain with circuit breaker protection"""
        try:
            if not self.carbon_verification_address:
                raise Exception("Carbon verification contract address not configured")

            # Prepare verification data
            verification_data = {
                "entry_id": carbon_entry_id,
                "carbon_footprint": carbon_data.get("total_emissions", 0),
                "timestamp": int(time.time()),
                "data_hash": self._calculate_data_hash(carbon_data),
            }

            # Create transaction (simplified - would use actual contract ABI)
            transaction = {
                "to": self.carbon_verification_address,
                "data": self._encode_verification_data(verification_data),
                "gas": 100000,  # Estimated gas limit
                "gasPrice": self.get_gas_price(),
            }

            # Send verification transaction
            tx_hash = self.send_transaction(transaction)

            return {
                "success": True,
                "transaction_hash": tx_hash,
                "verification_data": verification_data,
                "network": self.network_name,
                "timestamp": timezone.now().isoformat(),
            }

        except CircuitBreakerError as e:
            logger.warning(f"Circuit breaker open for carbon verification: {e}")
            return blockchain_fallback_response(
                "verify_carbon_record", carbon_entry_id=carbon_entry_id, carbon_data=carbon_data
            )

        except Exception as e:
            logger.error(f"Carbon verification failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "carbon_entry_id": carbon_entry_id,
                "timestamp": timezone.now().isoformat(),
                "retry_required": True,
            }

    @blockchain_circuit_breaker("batch_verify_carbon_records")
    def batch_verify_carbon_records(self, carbon_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Batch verify multiple carbon records with circuit breaker protection"""
        try:
            if not carbon_entries:
                return {"success": False, "error": "No carbon entries provided"}

            if len(carbon_entries) > 50:  # Limit batch size
                raise ValueError("Batch size too large (max 50 entries)")

            # Prepare batch verification data
            batch_data = []
            for entry in carbon_entries:
                verification_data = {
                    "entry_id": entry.get("id"),
                    "carbon_footprint": entry.get("total_emissions", 0),
                    "timestamp": int(time.time()),
                    "data_hash": self._calculate_data_hash(entry),
                }
                batch_data.append(verification_data)

            # Create batch transaction
            transaction = {
                "to": self.carbon_verification_address,
                "data": self._encode_batch_verification_data(batch_data),
                "gas": len(batch_data) * 80000,  # Estimated gas per entry
                "gasPrice": self.get_gas_price(),
            }

            # Send batch verification transaction
            tx_hash = self.send_transaction(transaction)

            return {
                "success": True,
                "transaction_hash": tx_hash,
                "verified_count": len(batch_data),
                "verification_data": batch_data,
                "network": self.network_name,
                "timestamp": timezone.now().isoformat(),
            }

        except CircuitBreakerError as e:
            logger.warning(f"Circuit breaker open for batch verification: {e}")
            return blockchain_fallback_response("batch_verify_carbon_records", carbon_entries=carbon_entries)

        except Exception as e:
            logger.error(f"Batch verification failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "entry_count": len(carbon_entries),
                "timestamp": timezone.now().isoformat(),
                "retry_required": True,
            }

    @blockchain_circuit_breaker("issue_carbon_credits")
    def issue_carbon_credits(self, recipient: str, amount: int, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Issue carbon credits with circuit breaker protection"""
        try:
            if not self.carbon_credit_address:
                raise Exception("Carbon credit contract address not configured")

            # Validate parameters
            if not self.w3.is_address(recipient):
                raise ValueError(f"Invalid recipient address: {recipient}")

            if amount <= 0:
                raise ValueError(f"Invalid credit amount: {amount}")

            # Create credit issuance transaction
            transaction = {
                "to": self.carbon_credit_address,
                "data": self._encode_credit_issuance(recipient, amount, metadata),
                "gas": 150000,  # Estimated gas for credit issuance
                "gasPrice": self.get_gas_price(),
            }

            # Send issuance transaction
            tx_hash = self.send_transaction(transaction)

            return {
                "success": True,
                "transaction_hash": tx_hash,
                "recipient": recipient,
                "amount": amount,
                "metadata": metadata,
                "network": self.network_name,
                "timestamp": timezone.now().isoformat(),
            }

        except CircuitBreakerError as e:
            logger.warning(f"Circuit breaker open for credit issuance: {e}")
            return blockchain_fallback_response(
                "issue_carbon_credits", recipient=recipient, amount=amount, metadata=metadata
            )

        except Exception as e:
            logger.error(f"Credit issuance failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "recipient": recipient,
                "amount": amount,
                "timestamp": timezone.now().isoformat(),
                "retry_required": True,
            }

    def _calculate_data_hash(self, data: Dict[str, Any]) -> str:
        """Calculate hash of carbon data for verification"""
        import hashlib

        # Create consistent data string
        data_string = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_string.encode()).hexdigest()

    def _encode_verification_data(self, verification_data: Dict[str, Any]) -> str:
        """Encode verification data for smart contract call"""
        # This would use actual contract ABI encoding
        # Simplified implementation for testing
        return (
            "0x" + "".join(f"{v:064x}" if isinstance(v, int) else f"{v:>64}" for v in verification_data.values())[:200]
        )

    def _encode_batch_verification_data(self, batch_data: List[Dict[str, Any]]) -> str:
        """Encode batch verification data for smart contract call"""
        # Simplified batch encoding
        encoded_entries = [self._encode_verification_data(entry) for entry in batch_data]
        return "0x" + "".join(encoded_entries)[:500]  # Truncate for example

    def _encode_credit_issuance(self, recipient: str, amount: int, metadata: Dict[str, Any]) -> str:
        """Encode credit issuance data for smart contract call"""
        # Simplified encoding for credit issuance
        recipient_hex = recipient[2:] if recipient.startswith("0x") else recipient
        amount_hex = f"{amount:064x}"
        metadata_hash = self._calculate_data_hash(metadata)

        return f"0x{recipient_hex}{amount_hex}{metadata_hash}"[:200]

    def get_failed_transactions(self) -> List[Dict[str, Any]]:
        """Get list of failed transactions waiting for retry"""
        return cache.get(self.failed_tx_queue_key, [])

    def retry_failed_transactions(self) -> Dict[str, Any]:
        """Retry failed transactions in queue"""
        failed_queue = self.get_failed_transactions()
        if not failed_queue:
            return {"success": True, "message": "No failed transactions to retry"}

        retry_results = {
            "total_attempted": 0,
            "successful_retries": 0,
            "failed_retries": 0,
            "permanently_failed": 0,
            "results": [],
        }

        updated_queue = []

        for failed_tx in failed_queue:
            retry_results["total_attempted"] += 1

            try:
                # Check if max retries exceeded
                if failed_tx["retry_count"] >= failed_tx["max_retries"]:
                    retry_results["permanently_failed"] += 1
                    retry_results["results"].append(
                        {
                            "transaction": failed_tx["transaction"],
                            "status": "permanently_failed",
                            "reason": "Max retries exceeded",
                        }
                    )
                    continue

                # Retry the transaction
                tx_hash = self.send_transaction(failed_tx["transaction"])

                retry_results["successful_retries"] += 1
                retry_results["results"].append(
                    {"transaction": failed_tx["transaction"], "status": "success", "tx_hash": tx_hash}
                )

            except Exception as e:
                # Increment retry count and requeue
                failed_tx["retry_count"] += 1
                failed_tx["last_retry"] = timezone.now().isoformat()
                failed_tx["last_error"] = str(e)

                updated_queue.append(failed_tx)
                retry_results["failed_retries"] += 1
                retry_results["results"].append(
                    {"transaction": failed_tx["transaction"], "status": "retry_failed", "error": str(e)}
                )

        # Update queue with remaining failed transactions
        cache.set(self.failed_tx_queue_key, updated_queue, 86400)

        logger.info(
            f"Transaction retry completed: {retry_results['successful_retries']} succeeded, "
            f"{retry_results['failed_retries']} failed, "
            f"{retry_results['permanently_failed']} permanently failed"
        )

        return retry_results

    def get_service_health(self) -> Dict[str, Any]:
        """Get blockchain service health status"""
        try:
            # Test basic connectivity
            current_block = self.get_current_block_number()
            gas_price = self.get_gas_price()

            # Check failed transaction queue
            failed_queue = self.get_failed_transactions()

            return {
                "status": "healthy",
                "connected": self.is_connected,
                "network": self.network_name,
                "current_block": current_block,
                "gas_price_gwei": gas_price / 10**9 if gas_price else 0,
                "failed_tx_queue_size": len(failed_queue),
                "contracts_configured": {
                    "carbon_verification": self.carbon_verification_address is not None,
                    "carbon_credit": self.carbon_credit_address is not None,
                },
                "timestamp": timezone.now().isoformat(),
            }

        except CircuitBreakerError:
            return {
                "status": "circuit_open",
                "connected": False,
                "network": self.network_name,
                "message": "Circuit breaker is open - blockchain calls are being blocked",
                "timestamp": timezone.now().isoformat(),
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "network": self.network_name,
                "error": str(e),
                "timestamp": timezone.now().isoformat(),
            }


# Global blockchain service instance
blockchain_service = BlockchainCircuitBreakerService()


# Convenience functions
def verify_carbon_on_blockchain(carbon_entry_id: int, carbon_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function for carbon verification"""
    return blockchain_service.verify_carbon_record(carbon_entry_id, carbon_data)


def batch_verify_carbon_on_blockchain(carbon_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convenience function for batch carbon verification"""
    return blockchain_service.batch_verify_carbon_records(carbon_entries)


def issue_carbon_credits_on_blockchain(recipient: str, amount: int, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function for carbon credit issuance"""
    return blockchain_service.issue_carbon_credits(recipient, amount, metadata)


def get_blockchain_health() -> Dict[str, Any]:
    """Get blockchain service health status"""
    return blockchain_service.get_service_health()
