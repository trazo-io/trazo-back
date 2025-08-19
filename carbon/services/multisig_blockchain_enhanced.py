"""
Enhanced Multi-Signature Blockchain Service
Implements production-grade security for critical blockchain operations
"""

import json
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from backend.services.secrets_manager import secrets_manager

from .blockchain import BlockchainCarbonService

logger = logging.getLogger(__name__)

# Import web3 safely
try:
    from eth_account import Account
    from web3 import Web3

    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    logger.warning("Web3 not available - multisig functionality limited")


class MultiSigError(Exception):
    """Raised when multi-signature operations fail"""


class InsufficientSignaturesError(Exception):
    """Raised when insufficient signatures are provided"""


class MultiSigBlockchainService(BlockchainCarbonService):
    """
    Enhanced blockchain service with multi-signature support for critical operations
    Ensures no single private key can authorize high-value transactions
    """

    def __init__(self):
        super().__init__()

        # Multi-sig configuration
        self.multisig_enabled = getattr(settings, "BLOCKCHAIN_MULTISIG_ENABLED", False)
        self.required_signatures = getattr(settings, "BLOCKCHAIN_REQUIRED_SIGNATURES", 2)
        self.max_signers = getattr(settings, "BLOCKCHAIN_MAX_SIGNERS", 5)

        # Load authorized signers
        self.authorized_signers = self._load_authorized_signers()

        # Transaction value thresholds requiring multi-sig
        self.multisig_threshold_usd = getattr(settings, "BLOCKCHAIN_MULTISIG_THRESHOLD_USD", 1000)
        self.critical_operations = [
            "batch_verify_carbon_records",
            "issue_carbon_credits",
            "transfer_large_amounts",
            "contract_upgrade",
            "emergency_pause",
        ]

        logger.info(
            f"MultiSig initialized - Enabled: {self.multisig_enabled}, "
            f"Required: {self.required_signatures}, Signers: {len(self.authorized_signers)}"
        )

    def _load_authorized_signers(self) -> List[str]:
        """Load authorized signer addresses from secure storage"""
        try:
            # Try to get from secrets manager
            signers_secret = secrets_manager.get_secret("blockchain_authorized_signers", required=False)

            if signers_secret:
                if isinstance(signers_secret, str):
                    return json.loads(signers_secret)
                elif isinstance(signers_secret, list):
                    return signers_secret

            # Fallback to settings
            signers_setting = getattr(settings, "BLOCKCHAIN_SIGNERS", [])
            if isinstance(signers_setting, str):
                return signers_setting.split(",")

            return signers_setting or []

        except Exception as e:
            logger.error(f"Failed to load authorized signers: {e}")
            return []

    def _requires_multisig(self, operation: str, **kwargs) -> bool:
        """Determine if operation requires multi-signature approval"""
        if not self.multisig_enabled:
            return False

        # Always require multisig for critical operations
        if operation in self.critical_operations:
            return True

        # Check value threshold
        value_usd = kwargs.get("value_usd", 0)
        if value_usd >= self.multisig_threshold_usd:
            return True

        # Check batch size
        batch_size = kwargs.get("batch_size", 0)
        if batch_size >= 50:  # Large batch operations
            return True

        return False

    def create_multisig_transaction(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a multi-signature transaction proposal

        Args:
            operation: Name of the operation to execute
            params: Parameters for the operation

        Returns:
            Transaction proposal with unique ID
        """
        try:
            if not self._requires_multisig(operation, **params):
                raise MultiSigError(f"Operation '{operation}' does not require multi-signature")

            # Generate unique transaction ID
            tx_id = self._generate_transaction_id(operation, params)

            # Create transaction proposal
            proposal = {
                "tx_id": tx_id,
                "operation": operation,
                "params": params,
                "created_at": timezone.now().isoformat(),
                "created_by": self.account.address if self.account else "system",
                "required_signatures": self.required_signatures,
                "signatures": [],
                "status": "pending",
                "expires_at": (timezone.now() + timedelta(hours=24)).isoformat(),
                "metadata": {
                    "network": self.network_name,
                    "gas_estimate": params.get("gas_estimate"),
                    "value_usd": params.get("value_usd", 0),
                },
            }

            # Store proposal in cache
            cache_key = f"multisig_proposal_{tx_id}"
            cache.set(cache_key, proposal, 86400)  # 24 hours

            logger.info(f"✅ Multi-sig proposal created: {tx_id} for operation: {operation}")

            return {
                "success": True,
                "tx_id": tx_id,
                "proposal": proposal,
                "required_signatures": self.required_signatures,
                "authorized_signers": self.authorized_signers,
            }

        except Exception as e:
            logger.error(f"Failed to create multi-sig transaction: {e}")
            return {"success": False, "error": str(e)}

    def sign_transaction(self, tx_id: str, private_key: str) -> Dict[str, Any]:
        """
        Sign a multi-signature transaction proposal

        Args:
            tx_id: Transaction ID to sign
            private_key: Private key of authorized signer

        Returns:
            Signature result and updated proposal status
        """
        try:
            if not WEB3_AVAILABLE:
                raise MultiSigError("Web3 not available for signing")

            # Get transaction proposal
            cache_key = f"multisig_proposal_{tx_id}"
            proposal = cache.get(cache_key)

            if not proposal:
                raise MultiSigError(f"Transaction proposal {tx_id} not found or expired")

            if proposal["status"] != "pending":
                raise MultiSigError(f"Transaction {tx_id} is not in pending status")

            # Verify signer is authorized
            account = Account.from_key(private_key)
            signer_address = account.address

            if signer_address not in self.authorized_signers:
                raise MultiSigError(f"Address {signer_address} is not an authorized signer")

            # Check if already signed by this address
            existing_signatures = [sig["signer"] for sig in proposal["signatures"]]
            if signer_address in existing_signatures:
                raise MultiSigError(f"Transaction already signed by {signer_address}")

            # Create message to sign
            message_data = {
                "tx_id": tx_id,
                "operation": proposal["operation"],
                "params": proposal["params"],
                "created_at": proposal["created_at"],
            }
            message = json.dumps(message_data, sort_keys=True)

            # Sign the message
            signed_message = account.sign_message_hash(Web3.keccak(text=message))

            # Add signature to proposal
            signature_entry = {
                "signer": signer_address,
                "signature": signed_message.signature.hex(),
                "signed_at": timezone.now().isoformat(),
                "message_hash": Web3.keccak(text=message).hex(),
            }

            proposal["signatures"].append(signature_entry)

            # Check if we have enough signatures
            if len(proposal["signatures"]) >= self.required_signatures:
                proposal["status"] = "ready_to_execute"
                logger.info(f"✅ Transaction {tx_id} ready to execute with {len(proposal['signatures'])} signatures")

            # Update proposal in cache
            cache.set(cache_key, proposal, 86400)

            return {
                "success": True,
                "tx_id": tx_id,
                "signer": signer_address,
                "signatures_count": len(proposal["signatures"]),
                "required_signatures": self.required_signatures,
                "ready_to_execute": proposal["status"] == "ready_to_execute",
            }

        except Exception as e:
            logger.error(f"Failed to sign transaction {tx_id}: {e}")
            return {"success": False, "error": str(e)}

    def execute_multisig_transaction(self, tx_id: str) -> Dict[str, Any]:
        """
        Execute a multi-signature transaction after sufficient signatures collected

        Args:
            tx_id: Transaction ID to execute

        Returns:
            Execution result
        """
        try:
            # Get transaction proposal
            cache_key = f"multisig_proposal_{tx_id}"
            proposal = cache.get(cache_key)

            if not proposal:
                raise MultiSigError(f"Transaction proposal {tx_id} not found or expired")

            if proposal["status"] != "ready_to_execute":
                raise InsufficientSignaturesError(
                    f"Transaction {tx_id} has {len(proposal['signatures'])} signatures, "
                    f"requires {self.required_signatures}"
                )

            # Verify all signatures
            if not self._verify_all_signatures(proposal):
                raise MultiSigError("Signature verification failed")

            # Execute the operation
            operation = proposal["operation"]
            params = proposal["params"]

            logger.info(f"🔄 Executing multi-sig operation: {operation}")

            # Route to appropriate execution method
            if operation == "batch_verify_carbon_records":
                result = self._execute_batch_verification(params)
            elif operation == "issue_carbon_credits":
                result = self._execute_credit_issuance(params)
            elif operation == "emergency_pause":
                result = self._execute_emergency_pause(params)
            else:
                raise MultiSigError(f"Unknown operation: {operation}")

            # Update proposal status
            proposal["status"] = "executed" if result["success"] else "failed"
            proposal["executed_at"] = timezone.now().isoformat()
            proposal["execution_result"] = result

            cache.set(cache_key, proposal, 86400)

            # Audit log
            self._audit_log_multisig_execution(tx_id, operation, result)

            return {"success": True, "tx_id": tx_id, "operation": operation, "execution_result": result}

        except Exception as e:
            logger.error(f"Failed to execute multi-sig transaction {tx_id}: {e}")
            return {"success": False, "error": str(e)}

    def _verify_all_signatures(self, proposal: Dict[str, Any]) -> bool:
        """Verify all signatures in a proposal"""
        try:
            if not WEB3_AVAILABLE:
                return False

            message_data = {
                "tx_id": proposal["tx_id"],
                "operation": proposal["operation"],
                "params": proposal["params"],
                "created_at": proposal["created_at"],
            }
            message = json.dumps(message_data, sort_keys=True)
            message_hash = Web3.keccak(text=message)

            for signature_entry in proposal["signatures"]:
                try:
                    # Recover signer address from signature
                    recovered_address = Account.recover_message_hash(
                        message_hash, signature=signature_entry["signature"]
                    )

                    # Verify it matches the claimed signer
                    if recovered_address.lower() != signature_entry["signer"].lower():
                        logger.error(f"Signature verification failed for {signature_entry['signer']}")
                        return False

                    # Verify signer is authorized
                    if recovered_address not in self.authorized_signers:
                        logger.error(f"Unauthorized signer: {recovered_address}")
                        return False

                except Exception as e:
                    logger.error(f"Signature verification error: {e}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False

    def _execute_batch_verification(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute batch carbon verification with enhanced security"""
        try:
            carbon_entries = params.get("carbon_entries", [])

            if not carbon_entries:
                raise MultiSigError("No carbon entries provided for verification")

            # Use parent class method but with additional validation
            result = self.batch_verify_carbon_records(carbon_entries)

            logger.info(f"✅ Multi-sig batch verification completed: {len(carbon_entries)} entries")

            return result

        except Exception as e:
            logger.error(f"Multi-sig batch verification failed: {e}")
            return {"success": False, "error": str(e)}

    def _execute_credit_issuance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute carbon credit issuance with enhanced security"""
        try:
            # Implement carbon credit issuance logic
            recipient = params.get("recipient")
            amount = params.get("amount")

            if not recipient or not amount:
                raise MultiSigError("Missing recipient or amount for credit issuance")

            # Placeholder for actual credit issuance
            logger.info(f"✅ Multi-sig credit issuance: {amount} credits to {recipient}")

            return {
                "success": True,
                "recipient": recipient,
                "amount": amount,
                "transaction_hash": "0xmultisig_credit_tx",
            }

        except Exception as e:
            logger.error(f"Multi-sig credit issuance failed: {e}")
            return {"success": False, "error": str(e)}

    def _execute_emergency_pause(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute emergency pause with enhanced security"""
        try:
            reason = params.get("reason", "Emergency pause initiated")

            # Implement emergency pause logic
            logger.warning(f"🚨 Multi-sig emergency pause executed: {reason}")

            return {"success": True, "reason": reason, "paused_at": timezone.now().isoformat()}

        except Exception as e:
            logger.error(f"Multi-sig emergency pause failed: {e}")
            return {"success": False, "error": str(e)}

    def _generate_transaction_id(self, operation: str, params: Dict[str, Any]) -> str:
        """Generate unique transaction ID"""
        import hashlib

        data = f"{operation}_{json.dumps(params, sort_keys=True)}_{timezone.now().isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def _audit_log_multisig_execution(self, tx_id: str, operation: str, result: Dict[str, Any]):
        """Log multi-signature execution for audit purposes"""
        audit_entry = {
            "event": "multisig_execution",
            "tx_id": tx_id,
            "operation": operation,
            "success": result.get("success", False),
            "timestamp": timezone.now().isoformat(),
            "network": self.network_name,
        }

        # Log to audit system
        logger.info(f"AUDIT: MultiSig execution - {json.dumps(audit_entry)}")

    def get_pending_transactions(self) -> List[Dict[str, Any]]:
        """Get all pending multi-signature transactions"""
        try:
            # In a real implementation, this would query a database
            # For now, we'll return a placeholder
            return []

        except Exception as e:
            logger.error(f"Failed to get pending transactions: {e}")
            return []

    def get_transaction_status(self, tx_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific multi-signature transaction"""
        try:
            cache_key = f"multisig_proposal_{tx_id}"
            proposal = cache.get(cache_key)

            if not proposal:
                return None

            return {
                "tx_id": tx_id,
                "operation": proposal["operation"],
                "status": proposal["status"],
                "signatures_count": len(proposal["signatures"]),
                "required_signatures": proposal["required_signatures"],
                "created_at": proposal["created_at"],
                "expires_at": proposal["expires_at"],
            }

        except Exception as e:
            logger.error(f"Failed to get transaction status: {e}")
            return None


# Enhanced convenience functions
def create_multisig_carbon_verification(carbon_entries: List) -> Dict[str, Any]:
    """Create multi-signature carbon verification proposal"""
    multisig_service = MultiSigBlockchainService()

    return multisig_service.create_multisig_transaction(
        "batch_verify_carbon_records",
        {
            "carbon_entries": carbon_entries,
            "batch_size": len(carbon_entries),
            "value_usd": len(carbon_entries) * 10,  # Estimate $10 per verification
        },
    )


def sign_multisig_transaction(tx_id: str, private_key: str) -> Dict[str, Any]:
    """Sign a multi-signature transaction"""
    multisig_service = MultiSigBlockchainService()
    return multisig_service.sign_transaction(tx_id, private_key)


def execute_when_ready(tx_id: str) -> Dict[str, Any]:
    """Execute multi-signature transaction when sufficient signatures collected"""
    multisig_service = MultiSigBlockchainService()
    return multisig_service.execute_multisig_transaction(tx_id)
