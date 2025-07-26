"""
Multi-Signature Authentication Service for Trazo
Implements multi-signature requirements for critical blockchain and financial operations.
"""

import logging
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)
User = get_user_model()


class MultiSigRequest(models.Model):
    """Track multi-signature approval requests"""
    OPERATION_TYPES = [
        ('blockchain_transaction', 'Blockchain Transaction'),
        ('key_rotation', 'Key Rotation'),
        ('credit_issuance', 'Carbon Credit Issuance'),
        ('payment_processing', 'Payment Processing'),
        ('contract_deployment', 'Smart Contract Deployment'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
        ('executed', 'Executed'),
    ]
    
    request_id = models.CharField(max_length=64, unique=True, db_index=True)
    operation_type = models.CharField(max_length=50, choices=OPERATION_TYPES)
    operation_data = models.JSONField()
    operation_hash = models.CharField(max_length=64)  # Hash of operation data
    
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='multisig_requests')
    requested_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    required_approvals = models.IntegerField(default=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_result = models.JSONField(null=True, blank=True)
    
    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['operation_type', 'status']),
        ]


class MultiSigApproval(models.Model):
    """Track individual approvals for multi-sig requests"""
    request = models.ForeignKey(MultiSigRequest, on_delete=models.CASCADE, related_name='approvals')
    approver = models.ForeignKey(User, on_delete=models.CASCADE)
    approved_at = models.DateTimeField(auto_now_add=True)
    approval_hash = models.CharField(max_length=64)  # Hash of approval data
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    
    class Meta:
        unique_together = ['request', 'approver']
        ordering = ['approved_at']


class MultiSigAuthService:
    """
    Multi-signature authentication service for critical operations.
    Ensures multiple authorized users approve sensitive actions.
    """
    
    def __init__(self):
        self.approval_policies = {
            'blockchain_transaction': {
                'required_approvals': 2,
                'expiry_hours': 24,
                'allowed_roles': ['company_admin', 'finance_manager'],
                'value_thresholds': {
                    'low': {'amount': 1000, 'approvals': 1},
                    'medium': {'amount': 10000, 'approvals': 2},
                    'high': {'amount': float('inf'), 'approvals': 3}
                }
            },
            'key_rotation': {
                'required_approvals': 2,
                'expiry_hours': 4,
                'allowed_roles': ['company_admin', 'security_admin'],
            },
            'credit_issuance': {
                'required_approvals': 2,
                'expiry_hours': 48,
                'allowed_roles': ['company_admin', 'compliance_officer'],
            },
            'payment_processing': {
                'required_approvals': 1,
                'expiry_hours': 12,
                'allowed_roles': ['company_admin', 'finance_manager'],
            },
            'contract_deployment': {
                'required_approvals': 3,
                'expiry_hours': 72,
                'allowed_roles': ['company_admin', 'tech_lead', 'security_admin'],
            }
        }
    
    def create_approval_request(
        self,
        operation_type: str,
        operation_data: Dict[str, Any],
        requested_by: User,
        custom_approvals: Optional[int] = None
    ) -> MultiSigRequest:
        """
        Create a new multi-signature approval request.
        
        Args:
            operation_type: Type of operation requiring approval
            operation_data: Details of the operation
            requested_by: User initiating the request
            custom_approvals: Override default approval requirement
            
        Returns:
            MultiSigRequest instance
        """
        try:
            policy = self.approval_policies.get(operation_type)
            if not policy:
                raise ValueError(f"Unknown operation type: {operation_type}")
            
            # Check if user has permission to initiate this operation
            if not self._user_can_initiate(requested_by, operation_type):
                raise PermissionDenied("User not authorized to initiate this operation")
            
            # Generate unique request ID
            request_data = {
                'operation_type': operation_type,
                'operation_data': operation_data,
                'requested_by': requested_by.id,
                'timestamp': datetime.now().isoformat()
            }
            request_id = hashlib.sha256(
                json.dumps(request_data, sort_keys=True).encode()
            ).hexdigest()[:16]
            
            # Calculate operation hash for integrity
            operation_hash = hashlib.sha256(
                json.dumps(operation_data, sort_keys=True).encode()
            ).hexdigest()
            
            # Determine required approvals based on policy and thresholds
            required_approvals = custom_approvals or self._calculate_required_approvals(
                operation_type, operation_data
            )
            
            # Create the request
            multisig_request = MultiSigRequest.objects.create(
                request_id=request_id,
                operation_type=operation_type,
                operation_data=operation_data,
                operation_hash=operation_hash,
                requested_by=requested_by,
                expires_at=datetime.now() + timedelta(hours=policy['expiry_hours']),
                required_approvals=required_approvals
            )
            
            logger.info(f"Created multi-sig request {request_id} for {operation_type}")
            
            # Send notifications to eligible approvers
            self._notify_approvers(multisig_request)
            
            return multisig_request
            
        except Exception as e:
            logger.error(f"Error creating multi-sig request: {e}")
            raise
    
    def approve_request(
        self,
        request_id: str,
        approver: User,
        ip_address: str,
        user_agent: str
    ) -> bool:
        """
        Approve a multi-signature request.
        
        Args:
            request_id: ID of the request to approve
            approver: User approving the request
            ip_address: IP address of approver
            user_agent: User agent string
            
        Returns:
            bool: True if approval successful and request ready for execution
        """
        try:
            # Get the request
            multisig_request = MultiSigRequest.objects.get(
                request_id=request_id,
                status='pending'
            )
            
            # Check if request has expired
            if datetime.now() > multisig_request.expires_at:
                multisig_request.status = 'expired'
                multisig_request.save()
                raise ValueError("Request has expired")
            
            # Check if user can approve this type of operation
            if not self._user_can_approve(approver, multisig_request.operation_type):
                raise PermissionDenied("User not authorized to approve this operation")
            
            # Check if user is trying to approve their own request
            if approver == multisig_request.requested_by:
                raise PermissionDenied("Cannot approve your own request")
            
            # Check if user has already approved
            if MultiSigApproval.objects.filter(
                request=multisig_request,
                approver=approver
            ).exists():
                raise ValueError("User has already approved this request")
            
            # Create approval hash
            approval_data = {
                'request_id': request_id,
                'approver_id': approver.id,
                'timestamp': datetime.now().isoformat(),
                'operation_hash': multisig_request.operation_hash
            }
            approval_hash = hashlib.sha256(
                json.dumps(approval_data, sort_keys=True).encode()
            ).hexdigest()
            
            # Record the approval
            MultiSigApproval.objects.create(
                request=multisig_request,
                approver=approver,
                approval_hash=approval_hash,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            # Check if we have enough approvals
            approval_count = multisig_request.approvals.count()
            if approval_count >= multisig_request.required_approvals:
                multisig_request.status = 'approved'
                multisig_request.save()
                
                logger.info(f"Multi-sig request {request_id} fully approved")
                
                # Clear any cached data
                cache_key = f"multisig_request_{request_id}"
                cache.delete(cache_key)
                
                return True
            
            logger.info(f"Multi-sig request {request_id} partially approved ({approval_count}/{multisig_request.required_approvals})")
            return False
            
        except MultiSigRequest.DoesNotExist:
            logger.error(f"Multi-sig request {request_id} not found")
            raise ValueError("Request not found or already processed")
        except Exception as e:
            logger.error(f"Error approving multi-sig request: {e}")
            raise
    
    def execute_approved_request(self, request_id: str) -> Dict[str, Any]:
        """
        Execute an approved multi-signature request.
        
        Args:
            request_id: ID of the approved request
            
        Returns:
            Dict with execution results
        """
        try:
            multisig_request = MultiSigRequest.objects.get(
                request_id=request_id,
                status='approved'
            )
            
            # Verify all approvals are valid
            if not self._verify_approvals(multisig_request):
                raise ValueError("Invalid approvals detected")
            
            # Execute the operation based on type
            result = self._execute_operation(
                multisig_request.operation_type,
                multisig_request.operation_data
            )
            
            # Update request status
            multisig_request.status = 'executed'
            multisig_request.executed_at = datetime.now()
            multisig_request.execution_result = result
            multisig_request.save()
            
            logger.info(f"Executed multi-sig request {request_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing multi-sig request: {e}")
            raise
    
    def _calculate_required_approvals(
        self,
        operation_type: str,
        operation_data: Dict[str, Any]
    ) -> int:
        """Calculate required approvals based on thresholds"""
        policy = self.approval_policies[operation_type]
        
        # Check for value-based thresholds
        if 'value_thresholds' in policy and 'amount' in operation_data:
            amount = float(operation_data.get('amount', 0))
            for level in ['high', 'medium', 'low']:
                threshold = policy['value_thresholds'][level]
                if amount <= threshold['amount']:
                    return threshold['approvals']
        
        return policy['required_approvals']
    
    def _user_can_initiate(self, user: User, operation_type: str) -> bool:
        """Check if user can initiate operation"""
        # Implementation depends on your role system
        # For now, check if user is authenticated and active
        return user.is_authenticated and user.is_active
    
    def _user_can_approve(self, user: User, operation_type: str) -> bool:
        """Check if user can approve operation"""
        policy = self.approval_policies.get(operation_type, {})
        allowed_roles = policy.get('allowed_roles', [])
        
        # Check user roles (implementation depends on your role system)
        # For now, check if user is staff
        return user.is_staff or user.is_superuser
    
    def _verify_approvals(self, request: MultiSigRequest) -> bool:
        """Verify all approvals are valid"""
        for approval in request.approvals.all():
            # Recalculate approval hash
            approval_data = {
                'request_id': request.request_id,
                'approver_id': approval.approver.id,
                'timestamp': approval.approved_at.isoformat(),
                'operation_hash': request.operation_hash
            }
            expected_hash = hashlib.sha256(
                json.dumps(approval_data, sort_keys=True).encode()
            ).hexdigest()
            
            if approval.approval_hash != expected_hash:
                logger.error(f"Invalid approval hash for request {request.request_id}")
                return False
        
        return True
    
    def _execute_operation(
        self,
        operation_type: str,
        operation_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the approved operation"""
        # This would integrate with actual operation handlers
        # For now, return success
        return {
            'status': 'success',
            'operation_type': operation_type,
            'executed_at': datetime.now().isoformat()
        }
    
    def _notify_approvers(self, request: MultiSigRequest):
        """Send notifications to eligible approvers"""
        # In production, integrate with notification system
        logger.info(f"Notifying approvers for request {request.request_id}")


# Singleton instance
multisig_auth_service = MultiSigAuthService()