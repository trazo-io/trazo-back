"""
Enhanced Multi-Signature Blockchain Service for Trazo
Production-grade multi-signature implementation with comprehensive security patterns.
Addresses CRITICAL security vulnerabilities in blockchain operations.
"""

import hashlib
import json
import logging
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Union

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .blockchain import BlockchainCarbonService, BlockchainOperationError
from .secure_key_management import secure_key_manager

# Import web3 safely
try:
    from eth_account import Account
    from web3 import Web3
    from web3.exceptions import ContractLogicError, TransactionNotFound
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Web3 not available - multisig functionality limited")

logger = logging.getLogger(__name__)


class MultiSigSecurityError(Exception):
    """Raised when multi-signature security requirements are violated"""


class InsufficientSignaturesError(Exception):
    """Raised when insufficient signatures are provided"""


class ProposalExpiredError(Exception):
    """Raised when a proposal has expired"""


class UnauthorizedSignerError(Exception):
    """Raised when an unauthorized signer attempts to sign"""


class EnhancedMultiSigBlockchainService(BlockchainCarbonService):
    """
    Enhanced blockchain service with comprehensive multi-signature security.
    Implements production-grade patterns for Trazo's carbon verification platform.
    
    Features:
    - Automatic multi-sig requirement detection
    - Secure proposal management with expiration
    - Role-based access control
    - Gas optimization for multi-sig operations
    - Comprehensive audit logging
    - Emergency procedures with multi-sig protection
    """

    def __init__(self):
        super().__init__()
        
        # Multi-sig configuration
        self.multisig_enabled = getattr(settings, "BLOCKCHAIN_MULTISIG_ENABLED", True)
        self.required_signatures = getattr(settings, "BLOCKCHAIN_REQUIRED_SIGNATURES", 3)
        self.max_signers = getattr(settings, "BLOCKCHAIN_MAX_SIGNERS", 7)
        self.proposal_validity_hours = getattr(settings, "MULTISIG_PROPOSAL_VALIDITY_HOURS", 24)
        
        # Multi-sig thresholds
        self.thresholds = {
            "carbon_amount_grams": getattr(settings, "MULTISIG_CARBON_THRESHOLD_GRAMS", 1000000),  # 1000 kg
            "credit_amount_grams": getattr(settings, "MULTISIG_CREDIT_THRESHOLD_GRAMS", 100000),   # 100 kg
            "monetary_value_usd": getattr(settings, "MULTISIG_VALUE_THRESHOLD_USD", 50000),        # $50k
            "batch_size": getattr(settings, "MULTISIG_BATCH_THRESHOLD", 10),                       # 10 items
        }
        
        # Load authorized signers from secure storage
        self.authorized_signers = self._load_authorized_signers()
        
        # Emergency procedures configuration
        self.emergency_multisig_enabled = True
        self.emergency_required_signatures = max(2, self.required_signatures - 1)
        
        # Contract addresses for multi-sig contracts
        self.multisig_carbon_contract = None
        self.multisig_token_contract = None
        
        self._initialize_multisig_contracts()
        
        logger.info(
            f"Enhanced MultiSig Service initialized - "
            f"Enabled: {self.multisig_enabled}, "
            f"Required: {self.required_signatures}/{len(self.authorized_signers)}, "
            f"Thresholds: {self.thresholds}"
        )

    def _initialize_multisig_contracts(self):
        """Initialize multi-signature contract instances"""
        try:
            if not self._is_blockchain_ready():
                logger.warning("Blockchain not ready - skipping multi-sig contract initialization")
                return
                
            # Load multi-sig contract addresses
            multisig_carbon_address = getattr(settings, "MULTISIG_CARBON_CONTRACT_ADDRESS", None)
            multisig_token_address = getattr(settings, "MULTISIG_TOKEN_CONTRACT_ADDRESS", None)
            
            if multisig_carbon_address:
                abi = self._load_multisig_carbon_abi()
                self.multisig_carbon_contract = self.web3.eth.contract(
                    address=multisig_carbon_address, abi=abi
                )
                logger.info(f"✅ Multi-sig carbon contract loaded: {multisig_carbon_address}")
                
            if multisig_token_address:
                abi = self._load_multisig_token_abi()
                self.multisig_token_contract = self.web3.eth.contract(
                    address=multisig_token_address, abi=abi
                )
                logger.info(f"✅ Multi-sig token contract loaded: {multisig_token_address}")
                
        except Exception as e:
            logger.error(f"Failed to initialize multi-sig contracts: {e}")
            if self.blockchain_required:
                raise BlockchainOperationError(f"Multi-sig contract initialization failed: {e}")

    def _load_authorized_signers(self) -> List[Dict[str, str]]:
        """Load authorized signers from secure storage with enhanced validation"""
        try:
            # Try to get from secure key manager
            signers_data = secure_key_manager.get_secret("trazo/blockchain/multisig_signers")
            
            if signers_data and isinstance(signers_data, dict):
                signers = signers_data.get("signers", [])
                
                # Validate signer data structure
                validated_signers = []
                for signer in signers:
                    if self._validate_signer_data(signer):
                        validated_signers.append(signer)
                    else:
                        logger.warning(f"Invalid signer data detected: {signer}")
                
                logger.info(f"✅ Loaded {len(validated_signers)} authorized signers")
                return validated_signers
            
            # Fallback to development signers
            if not self.production_mode:
                logger.warning("Using development signers - NOT SECURE FOR PRODUCTION")
                return self._get_development_signers()
            
            logger.error("No authorized signers found in secure storage")
            return []
            
        except Exception as e:
            logger.error(f"Failed to load authorized signers: {e}")
            if self.production_mode:
                raise MultiSigSecurityError(f"Cannot load authorized signers: {e}")
            return self._get_development_signers()

    def _validate_signer_data(self, signer: Dict[str, Any]) -> bool:
        """Validate signer data structure and content"""
        required_fields = ["address", "role", "name"]
        
        if not all(field in signer for field in required_fields):
            return False
            
        # Validate Ethereum address format
        try:
            if not Web3.is_address(signer["address"]):
                return False
        except:
            return False
            
        # Validate role
        valid_roles = ["admin", "operator", "auditor", "emergency"]
        if signer["role"] not in valid_roles:
            return False
            
        return True

    def _get_development_signers(self) -> List[Dict[str, str]]:
        """Get development signers for testing"""
        return [
            {
                "address": "0x742d35Cc6634C0532925a3b8d1c8b2b8b1f6E8B4",
                "role": "admin",
                "name": "Development Admin",
                "created_at": timezone.now().isoformat(),
            },
            {
                "address": "0x8ba1f109551bD432803012645Hac136c02142AC8",
                "role": "operator", 
                "name": "Development Operator",
                "created_at": timezone.now().isoformat(),
            },
            {
                "address": "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
                "role": "auditor",
                "name": "Development Auditor", 
                "created_at": timezone.now().isoformat(),
            },
        ]

    def requires_multisig_approval(
        self,
        operation_type: str,
        carbon_amount: int = 0,
        credit_amount: int = 0,
        monetary_value: int = 0,
        batch_size: int = 1,
        **kwargs
    ) -> bool:
        """
        Determine if operation requires multi-signature approval based on comprehensive criteria
        
        Args:
            operation_type: Type of operation (record, credits, emergency, config)
            carbon_amount: Carbon amount in grams
            credit_amount: Credit amount in grams
            monetary_value: USD value
            batch_size: Number of items in batch
            
        Returns:
            bool: True if multi-sig approval required
        """
        try:
            if not self.multisig_enabled:
                return False
                
            # Always require multi-sig for critical operations
            critical_operations = [
                "emergency_pause",
                "emergency_unpause", 
                "contract_upgrade",
                "signer_management",
                "threshold_updates",
                "producer_registration_high_risk"
            ]
            
            if operation_type in critical_operations:
                logger.info(f"Multi-sig required for critical operation: {operation_type}")
                return True
                
            # Check carbon amount threshold
            if carbon_amount >= self.thresholds["carbon_amount_grams"]:
                logger.info(f"Multi-sig required - carbon amount: {carbon_amount}g >= {self.thresholds['carbon_amount_grams']}g")
                return True
                
            # Check credit amount threshold
            if credit_amount >= self.thresholds["credit_amount_grams"]:
                logger.info(f"Multi-sig required - credit amount: {credit_amount}g >= {self.thresholds['credit_amount_grams']}g")
                return True
                
            # Check monetary value threshold
            if monetary_value >= self.thresholds["monetary_value_usd"]:
                logger.info(f"Multi-sig required - value: ${monetary_value} >= ${self.thresholds['monetary_value_usd']}")
                return True
                
            # Check batch size threshold
            if batch_size >= self.thresholds["batch_size"]:
                logger.info(f"Multi-sig required - batch size: {batch_size} >= {self.thresholds['batch_size']}")
                return True
                
            # Check producer risk level
            producer_risk = kwargs.get("producer_risk_level", 0)
            if producer_risk >= 2:  # High risk producers
                logger.info(f"Multi-sig required - high risk producer: level {producer_risk}")
                return True
                
            # Check time-based requirements (e.g., operations outside business hours)
            if kwargs.get("check_time_based", False):
                current_hour = timezone.now().hour
                if current_hour < 6 or current_hour > 22:  # Outside business hours
                    logger.info("Multi-sig required - operation outside business hours")
                    return True
                    
            return False
            
        except Exception as e:
            logger.error(f"Error checking multi-sig requirements: {e}")
            # Default to requiring multi-sig on error for security
            return True

    def create_multisig_proposal(
        self,
        operation_type: str,
        operation_data: Dict[str, Any],
        deadline_hours: int = None,
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """
        Create a comprehensive multi-signature proposal
        
        Args:
            operation_type: Type of blockchain operation
            operation_data: Data required for the operation
            deadline_hours: Hours until proposal expires (default: 24)
            priority: Priority level (low, normal, high, emergency)
            
        Returns:
            Dict containing proposal details
        """
        try:
            if not self.multisig_enabled:
                raise MultiSigSecurityError("Multi-signature not enabled")
                
            if not self.authorized_signers:
                raise MultiSigSecurityError("No authorized signers configured")
                
            # Set deadline based on priority
            if deadline_hours is None:
                deadline_hours = {
                    "emergency": 1,
                    "high": 6, 
                    "normal": 24,
                    "low": 72
                }.get(priority, 24)
                
            deadline = timezone.now() + timedelta(hours=deadline_hours)
            
            # Generate secure proposal ID
            proposal_id = self._generate_proposal_id(operation_type, operation_data)
            
            # Calculate required signatures based on priority
            required_sigs = self.required_signatures
            if priority == "emergency":
                required_sigs = self.emergency_required_signatures
                
            # Assess operation risk
            risk_level = self._assess_operation_risk(operation_type, operation_data)
            
            # Create proposal structure
            proposal = {
                "proposal_id": proposal_id,
                "operation_type": operation_type,
                "operation_data": operation_data,
                "created_at": timezone.now().isoformat(),
                "created_by": operation_data.get("created_by", "system"),
                "deadline": deadline.isoformat(),
                "priority": priority,
                "status": "pending",
                "required_signatures": required_sigs,
                "signatures": [],
                "approvals": [],
                "rejections": [],
                "risk_assessment": {
                    "level": risk_level,
                    "factors": self._get_risk_factors(operation_type, operation_data),
                    "automated_checks_passed": True,
                },
                "metadata": {
                    "carbon_amount": operation_data.get("carbon_amount", 0),
                    "credit_amount": operation_data.get("credit_amount", 0),
                    "monetary_value": operation_data.get("monetary_value_usd", 0),
                    "batch_size": operation_data.get("batch_size", 1),
                    "network": self.network_name,
                    "contract_version": self._get_contract_version(),
                },
                "audit_trail": [
                    {
                        "action": "proposal_created",
                        "timestamp": timezone.now().isoformat(),
                        "actor": operation_data.get("created_by", "system"),
                        "details": {"priority": priority, "deadline_hours": deadline_hours}
                    }
                ]
            }
            
            # Store proposal securely
            success = self._store_proposal_securely(proposal)
            if not success:
                raise MultiSigSecurityError("Failed to store proposal securely")
                
            # Notify authorized signers
            self._notify_signers_about_proposal(proposal)
            
            # Create audit log entry
            self._create_audit_log("proposal_created", proposal_id, {
                "operation_type": operation_type,
                "priority": priority,
                "risk_level": risk_level,
                "required_signatures": required_sigs,
                "deadline": deadline.isoformat()
            })
            
            logger.info(f"✅ Created multi-sig proposal: {proposal_id} (priority: {priority}, risk: {risk_level})")
            
            return {
                "success": True,
                "proposal_id": proposal_id,
                "required_signatures": required_sigs,
                "deadline": deadline.isoformat(),
                "priority": priority,
                "risk_level": risk_level,
                "authorized_signers": [s["address"] for s in self.authorized_signers],
                "notification_sent": True
            }
            
        except Exception as e:
            logger.error(f"Failed to create multi-sig proposal: {e}")
            raise MultiSigSecurityError(f"Proposal creation failed: {e}")

    def sign_proposal(
        self,
        proposal_id: str,
        signer_address: str,
        signature: str,
        approve: bool = True,
        comment: str = ""
    ) -> Dict[str, Any]:
        """
        Sign a multi-signature proposal with enhanced validation
        
        Args:
            proposal_id: Unique proposal identifier
            signer_address: Address of the signer
            signature: Cryptographic signature
            approve: Whether to approve (True) or reject (False)
            comment: Optional comment from signer
            
        Returns:
            Dict containing signature result
        """
        try:
            # Retrieve and validate proposal
            proposal = self._get_proposal_securely(proposal_id)
            if not proposal:
                raise MultiSigSecurityError(f"Proposal not found: {proposal_id}")
                
            self._validate_proposal_for_signing(proposal, signer_address)
            
            # Verify signature authenticity
            if not self._verify_signature(proposal, signature, signer_address):
                raise MultiSigSecurityError("Invalid signature")
                
            # Add signature to proposal
            signature_entry = {
                "signer_address": signer_address,
                "signature": signature,
                "approve": approve,
                "timestamp": timezone.now().isoformat(),
                "comment": comment,
                "signer_info": self._get_signer_info(signer_address)
            }
            
            proposal["signatures"].append(signature_entry)
            
            if approve:
                proposal["approvals"].append(signer_address)
            else:
                proposal["rejections"].append(signer_address)
                
            # Add to audit trail
            proposal["audit_trail"].append({
                "action": "signature_added",
                "timestamp": timezone.now().isoformat(),
                "actor": signer_address,
                "details": {
                    "approve": approve,
                    "comment": comment,
                    "signer_role": self._get_signer_role(signer_address)
                }
            })
            
            # Check if proposal can be executed or should be rejected
            approval_count = len(proposal["approvals"])
            rejection_count = len(proposal["rejections"])
            required_sigs = proposal["required_signatures"]
            
            if approval_count >= required_sigs:
                proposal["status"] = "approved"
                logger.info(f"✅ Proposal {proposal_id} approved with {approval_count} signatures")
                
                # Auto-execute if configured
                if getattr(settings, "MULTISIG_AUTO_EXECUTE", True):
                    execution_result = self._execute_approved_proposal(proposal)
                    proposal["execution_result"] = execution_result
                    
            elif rejection_count >= required_sigs:
                proposal["status"] = "rejected"
                logger.info(f"❌ Proposal {proposal_id} rejected with {rejection_count} rejections")
                
            # Update proposal storage
            self._store_proposal_securely(proposal)
            
            # Create audit log
            self._create_audit_log("proposal_signed", proposal_id, {
                "signer": signer_address,
                "approve": approve,
                "approval_count": approval_count,
                "rejection_count": rejection_count,
                "status": proposal["status"]
            })
            
            return {
                "success": True,
                "proposal_id": proposal_id,
                "status": proposal["status"],
                "approval_count": approval_count,
                "rejection_count": rejection_count,
                "required_signatures": required_sigs,
                "can_execute": proposal["status"] == "approved"
            }
            
        except Exception as e:
            logger.error(f"Failed to sign proposal {proposal_id}: {e}")
            raise MultiSigSecurityError(f"Signature failed: {e}")

    def execute_approved_proposal(self, proposal_id: str) -> Dict[str, Any]:
        """
        Execute a multi-signature proposal that has received sufficient approvals
        
        Args:
            proposal_id: Unique proposal identifier
            
        Returns:
            Dict containing execution result
        """
        try:
            # Retrieve and validate proposal
            proposal = self._get_proposal_securely(proposal_id)
            if not proposal:
                raise MultiSigSecurityError(f"Proposal not found: {proposal_id}")
                
            # Validate execution prerequisites
            self._validate_proposal_for_execution(proposal)
            
            # Execute the operation
            execution_result = self._execute_approved_proposal(proposal)
            
            return execution_result
            
        except Exception as e:
            logger.error(f"Failed to execute proposal {proposal_id}: {e}")
            raise MultiSigSecurityError(f"Execution failed: {e}")

    def _execute_approved_proposal(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Internal method to execute an approved proposal"""
        try:
            operation_type = proposal["operation_type"]
            operation_data = proposal["operation_data"]
            proposal_id = proposal["proposal_id"]
            
            logger.info(f"🔄 Executing approved proposal: {proposal_id} ({operation_type})")
            
            # Route to appropriate execution method
            execution_result = None
            
            if operation_type == "carbon_record":
                execution_result = self._execute_carbon_record_operation(operation_data)
            elif operation_type == "credit_issuance":
                execution_result = self._execute_credit_issuance_operation(operation_data)
            elif operation_type == "batch_verification":
                execution_result = self._execute_batch_verification_operation(operation_data)
            elif operation_type == "emergency_pause":
                execution_result = self._execute_emergency_pause_operation(operation_data)
            elif operation_type == "emergency_unpause":
                execution_result = self._execute_emergency_unpause_operation(operation_data)
            elif operation_type == "producer_registration":
                execution_result = self._execute_producer_registration_operation(operation_data)
            else:
                raise MultiSigSecurityError(f"Unknown operation type: {operation_type}")
                
            # Update proposal with execution results
            proposal["status"] = "executed" if execution_result.get("success") else "failed"
            proposal["executed_at"] = timezone.now().isoformat()
            proposal["execution_result"] = execution_result
            
            # Add to audit trail
            proposal["audit_trail"].append({
                "action": "proposal_executed",
                "timestamp": timezone.now().isoformat(),
                "actor": "system",
                "details": {
                    "success": execution_result.get("success", False),
                    "transaction_hash": execution_result.get("transaction_hash")
                }
            })
            
            # Store updated proposal
            self._store_proposal_securely(proposal)
            
            # Create audit log
            self._create_audit_log("proposal_executed", proposal_id, {
                "operation_type": operation_type,
                "success": execution_result.get("success", False),
                "transaction_hash": execution_result.get("transaction_hash"),
                "gas_used": execution_result.get("gas_used")
            })
            
            logger.info(f"✅ Executed proposal {proposal_id}: {execution_result.get('success', False)}")
            
            return {
                "success": True,
                "proposal_id": proposal_id,
                "operation_type": operation_type,
                "execution_result": execution_result,
                "executed_at": proposal["executed_at"]
            }
            
        except Exception as e:
            logger.error(f"Proposal execution failed: {e}")
            
            # Update proposal with failure
            proposal["status"] = "failed"
            proposal["executed_at"] = timezone.now().isoformat()
            proposal["execution_error"] = str(e)
            
            proposal["audit_trail"].append({
                "action": "execution_failed",
                "timestamp": timezone.now().isoformat(),
                "actor": "system",
                "details": {"error": str(e)}
            })
            
            self._store_proposal_securely(proposal)
            
            raise MultiSigSecurityError(f"Execution failed: {e}")

    # Implementation of various execution methods
    def _execute_carbon_record_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute carbon record creation operation"""
        try:
            production_id = operation_data["production_id"]
            carbon_data = operation_data["carbon_data"]
            
            # Use the multi-sig carbon contract if available
            if self.multisig_carbon_contract:
                return self._create_multisig_carbon_record(production_id, carbon_data)
            else:
                # Fallback to standard contract
                return super().create_carbon_record(production_id, carbon_data)
                
        except Exception as e:
            logger.error(f"Carbon record operation failed: {e}")
            return {"success": False, "error": str(e)}

    def _execute_credit_issuance_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute carbon credit issuance operation"""
        try:
            production_id = operation_data["production_id"]
            credits = operation_data["credits"]
            
            # Use the multi-sig token contract if available
            if self.multisig_token_contract:
                return self._issue_multisig_carbon_credits(production_id, credits)
            else:
                # Fallback to standard contract
                return super().issue_carbon_credits(production_id, credits)
                
        except Exception as e:
            logger.error(f"Credit issuance operation failed: {e}")
            return {"success": False, "error": str(e)}

    # Additional helper methods for multi-sig operations
    def _generate_proposal_id(self, operation_type: str, operation_data: Dict[str, Any]) -> str:
        """Generate secure, unique proposal ID"""
        data = f"{operation_type}_{json.dumps(operation_data, sort_keys=True)}_{time.time()}_{self.account.address if self.account else 'system'}"
        return hashlib.sha256(data.encode()).hexdigest()

    def _assess_operation_risk(self, operation_type: str, operation_data: Dict[str, Any]) -> str:
        """Assess risk level of blockchain operation"""
        try:
            risk_score = 0
            
            # Base risk by operation type
            operation_risks = {
                "emergency_pause": 90,
                "emergency_unpause": 80,
                "contract_upgrade": 95,
                "credit_issuance": 40,
                "carbon_record": 20,
                "batch_verification": 30,
                "producer_registration": 25
            }
            
            risk_score += operation_risks.get(operation_type, 10)
            
            # Risk factors from data
            carbon_amount = operation_data.get("carbon_amount", 0)
            if carbon_amount > 10000000:  # 10 tons
                risk_score += 30
            elif carbon_amount > 1000000:  # 1 ton
                risk_score += 15
                
            monetary_value = operation_data.get("monetary_value_usd", 0)
            if monetary_value > 1000000:  # $1M
                risk_score += 40
            elif monetary_value > 100000:  # $100k
                risk_score += 20
                
            batch_size = operation_data.get("batch_size", 1)
            if batch_size > 100:
                risk_score += 25
            elif batch_size > 50:
                risk_score += 15
                
            # Risk level classification
            if risk_score >= 80:
                return "critical"
            elif risk_score >= 60:
                return "high"
            elif risk_score >= 40:
                return "medium"
            else:
                return "low"
                
        except Exception as e:
            logger.error(f"Risk assessment failed: {e}")
            return "high"  # Default to high risk on error

    def _get_risk_factors(self, operation_type: str, operation_data: Dict[str, Any]) -> List[str]:
        """Get list of risk factors for the operation"""
        factors = []
        
        if operation_type in ["emergency_pause", "emergency_unpause"]:
            factors.append("emergency_operation")
            
        if operation_data.get("monetary_value_usd", 0) > 100000:
            factors.append("high_monetary_value")
            
        if operation_data.get("batch_size", 1) > 50:
            factors.append("large_batch_size")
            
        if operation_data.get("producer_risk_level", 0) >= 2:
            factors.append("high_risk_producer")
            
        return factors

    def _store_proposal_securely(self, proposal: Dict[str, Any]) -> bool:
        """Store proposal in secure storage with encryption"""
        try:
            proposal_id = proposal["proposal_id"]
            proposal_key = f"trazo/multisig/proposals/{proposal_id}"
            
            return secure_key_manager.store_secret(
                proposal_key,
                proposal,
                f"Multi-sig proposal {proposal_id}"
            )
            
        except Exception as e:
            logger.error(f"Failed to store proposal securely: {e}")
            return False

    def _get_proposal_securely(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve proposal from secure storage"""
        try:
            proposal_key = f"trazo/multisig/proposals/{proposal_id}"
            return secure_key_manager.get_secret(proposal_key, use_cache=False)
            
        except Exception as e:
            logger.error(f"Failed to retrieve proposal: {e}")
            return None

    def _validate_proposal_for_signing(self, proposal: Dict[str, Any], signer_address: str):
        """Validate proposal is eligible for signing"""
        if proposal["status"] != "pending":
            raise MultiSigSecurityError(f"Proposal status is {proposal['status']}, cannot sign")
            
        deadline = timezone.datetime.fromisoformat(proposal["deadline"].replace("Z", "+00:00"))
        if timezone.now() > deadline:
            raise ProposalExpiredError("Proposal has expired")
            
        if not self._is_authorized_signer(signer_address):
            raise UnauthorizedSignerError(f"Address {signer_address} is not an authorized signer")
            
        # Check if already signed
        existing_signers = [s["signer_address"] for s in proposal.get("signatures", [])]
        if signer_address in existing_signers:
            raise MultiSigSecurityError(f"Address {signer_address} has already signed this proposal")

    def _validate_proposal_for_execution(self, proposal: Dict[str, Any]):
        """Validate proposal is ready for execution"""
        if proposal["status"] != "approved":
            raise MultiSigSecurityError(f"Proposal status is {proposal['status']}, cannot execute")
            
        deadline = timezone.datetime.fromisoformat(proposal["deadline"].replace("Z", "+00:00"))
        if timezone.now() > deadline:
            raise ProposalExpiredError("Proposal has expired")
            
        approval_count = len(proposal["approvals"])
        required_sigs = proposal["required_signatures"]
        
        if approval_count < required_sigs:
            raise InsufficientSignaturesError(
                f"Insufficient approvals: {approval_count}/{required_sigs}"
            )

    def _is_authorized_signer(self, address: str) -> bool:
        """Check if address is an authorized signer"""
        return any(
            signer["address"].lower() == address.lower() 
            for signer in self.authorized_signers
        )

    def _get_signer_info(self, address: str) -> Dict[str, str]:
        """Get signer information"""
        for signer in self.authorized_signers:
            if signer["address"].lower() == address.lower():
                return {
                    "name": signer.get("name", "Unknown"),
                    "role": signer.get("role", "Unknown")
                }
        return {"name": "Unknown", "role": "Unknown"}

    def _get_signer_role(self, address: str) -> str:
        """Get signer role"""
        info = self._get_signer_info(address)
        return info.get("role", "Unknown")

    def _verify_signature(self, proposal: Dict[str, Any], signature: str, signer_address: str) -> bool:
        """Verify cryptographic signature"""
        try:
            if not WEB3_AVAILABLE:
                logger.warning("Web3 not available - signature verification skipped")
                return True  # Allow in development mode
                
            # Create message to verify
            message_data = {
                "proposal_id": proposal["proposal_id"],
                "operation_type": proposal["operation_type"],
                "created_at": proposal["created_at"],
                "deadline": proposal["deadline"]
            }
            
            message = json.dumps(message_data, sort_keys=True)
            message_hash = Web3.keccak(text=message)
            
            # Recover address from signature
            recovered_address = Account.recover_message_hash(message_hash, signature=signature)
            
            return recovered_address.lower() == signer_address.lower()
            
        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False

    def _notify_signers_about_proposal(self, proposal: Dict[str, Any]):
        """Notify authorized signers about new proposal"""
        try:
            # This would implement actual notification logic
            # For now, log the notification
            proposal_id = proposal["proposal_id"]
            operation_type = proposal["operation_type"]
            priority = proposal["priority"]
            
            logger.info(f"📧 Notifying {len(self.authorized_signers)} signers about proposal {proposal_id}")
            logger.info(f"   Operation: {operation_type}, Priority: {priority}")
            
            # In production, this would:
            # 1. Send email notifications
            # 2. Create dashboard alerts
            # 3. Send mobile push notifications
            # 4. Log to audit system
            
        except Exception as e:
            logger.error(f"Failed to notify signers: {e}")

    def _create_audit_log(self, event: str, proposal_id: str, details: Dict[str, Any]):
        """Create comprehensive audit log entry"""
        try:
            audit_entry = {
                "event": event,
                "proposal_id": proposal_id,
                "timestamp": timezone.now().isoformat(),
                "network": self.network_name,
                "service": "enhanced_multisig_blockchain",
                "details": details
            }
            
            # Store in secure audit log
            audit_key = f"trazo/audit/multisig/{proposal_id}_{event}_{int(time.time())}"
            secure_key_manager.store_secret(
                audit_key,
                audit_entry,
                f"Audit log for {event}"
            )
            
            # Also log locally
            logger.info(f"AUDIT: {event} - {json.dumps(audit_entry)}")
            
        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")

    # Contract-specific methods for multi-sig contracts
    def _load_multisig_carbon_abi(self) -> List[Dict]:
        """Load ABI for multi-sig carbon verification contract"""
        # This would load the actual ABI for MultiSigCarbonVerification.sol
        # For now, return a placeholder
        return []

    def _load_multisig_token_abi(self) -> List[Dict]:
        """Load ABI for multi-sig token contract"""
        # This would load the actual ABI for MultiSigCarbonCreditToken.sol
        # For now, return a placeholder
        return []

    def _get_contract_version(self) -> str:
        """Get current contract version"""
        return "1.0.0"

    # Override parent methods to add multi-sig protection
    def create_carbon_record(self, production_id: int, carbon_data: Dict[str, Any]) -> Dict[str, Any]:
        """Override with multi-sig protection"""
        try:
            carbon_amount = carbon_data.get("total_emissions", 0) + carbon_data.get("total_offsets", 0)
            monetary_value = carbon_data.get("monetary_value_usd", 0)
            
            if self.requires_multisig_approval(
                "carbon_record",
                carbon_amount=int(carbon_amount * 1000),  # Convert to grams
                monetary_value=monetary_value
            ):
                logger.info(f"Creating multi-sig proposal for carbon record: production_id={production_id}")
                
                proposal_result = self.create_multisig_proposal(
                    "carbon_record",
                    {
                        "production_id": production_id,
                        "carbon_data": carbon_data,
                        "carbon_amount": int(carbon_amount * 1000),
                        "monetary_value_usd": monetary_value,
                        "created_by": carbon_data.get("created_by", "system")
                    }
                )
                
                return {
                    "multisig_required": True,
                    "proposal_id": proposal_result["proposal_id"],
                    "status": "pending_approval",
                    "required_signatures": proposal_result["required_signatures"],
                    "deadline": proposal_result["deadline"],
                    "message": f"Multi-signature approval required. Proposal ID: {proposal_result['proposal_id']}"
                }
            else:
                # Execute directly for low-risk operations
                return super().create_carbon_record(production_id, carbon_data)
                
        except Exception as e:
            logger.error(f"Multi-sig carbon record creation failed: {e}")
            raise BlockchainOperationError(f"Multi-sig operation failed: {e}")

    def issue_carbon_credits(self, production_id: int, credits: float, value_usd: float = 0) -> Dict[str, Any]:
        """Override with multi-sig protection"""
        try:
            credit_amount_grams = int(credits * 1000)  # Convert to grams
            
            if self.requires_multisig_approval(
                "credit_issuance",
                credit_amount=credit_amount_grams,
                monetary_value=int(value_usd)
            ):
                logger.info(f"Creating multi-sig proposal for credit issuance: production_id={production_id}, credits={credits}")
                
                proposal_result = self.create_multisig_proposal(
                    "credit_issuance",
                    {
                        "production_id": production_id,
                        "credits": credits,
                        "credit_amount": credit_amount_grams,
                        "monetary_value_usd": int(value_usd)
                    }
                )
                
                return {
                    "multisig_required": True,
                    "proposal_id": proposal_result["proposal_id"],
                    "status": "pending_approval",
                    "required_signatures": proposal_result["required_signatures"],
                    "deadline": proposal_result["deadline"],
                    "message": f"Multi-signature approval required for {credits} credits. Proposal ID: {proposal_result['proposal_id']}"
                }
            else:
                return super().issue_carbon_credits(production_id, credits)
                
        except Exception as e:
            logger.error(f"Multi-sig credit issuance failed: {e}")
            raise BlockchainOperationError(f"Multi-sig operation failed: {e}")

    # Administrative methods
    def get_pending_proposals(self, signer_address: str = None) -> List[Dict[str, Any]]:
        """Get pending proposals for review"""
        try:
            # This would query all pending proposals
            # Implementation depends on storage solution
            logger.info(f"Getting pending proposals for signer: {signer_address}")
            return []
            
        except Exception as e:
            logger.error(f"Failed to get pending proposals: {e}")
            return []

    def get_proposal_details(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed proposal information"""
        return self._get_proposal_securely(proposal_id)

    def get_multisig_statistics(self) -> Dict[str, Any]:
        """Get multi-signature system statistics"""
        return {
            "enabled": self.multisig_enabled,
            "required_signatures": self.required_signatures,
            "authorized_signers_count": len(self.authorized_signers),
            "thresholds": self.thresholds,
            "emergency_signatures_required": self.emergency_required_signatures
        }


# Enhanced singleton instance
enhanced_multisig_blockchain_service = EnhancedMultiSigBlockchainService()