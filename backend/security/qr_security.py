"""
QR Code Security Module for Trazo
Adds HMAC signatures and tamper detection to QR codes
"""

import hmac
import hashlib
import time
import base64
import json
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode, parse_qs, urlparse
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta
from backend.security import get_secure_key
import logging

logger = logging.getLogger(__name__)


class QRSecurityManager:
    """
    Manages QR code security with HMAC signatures and tamper detection
    """
    
    def __init__(self):
        self.secret_key = self._get_signing_key()
        self.default_expiry_hours = 24 * 30  # 30 days default expiry
        
    def _get_signing_key(self) -> str:
        """Get the signing key for QR code HMAC"""
        # Try to get from secure storage first
        key = get_secure_key('qr_signing_key', 'QR_SIGNING_KEY')
        if not key:
            # Fallback to SECRET_KEY if no dedicated QR key
            key = settings.SECRET_KEY
            logger.warning("Using Django SECRET_KEY for QR signing - consider setting dedicated QR_SIGNING_KEY")
        return key
    
    def generate_secure_qr_url(self, 
                              base_url: str, 
                              production_id: int,
                              expiry_hours: Optional[int] = None) -> str:
        """
        Generate a secure QR code URL with HMAC signature and expiration
        
        Args:
            base_url: Base URL for the QR code
            production_id: Production ID
            expiry_hours: Hours until expiration (default: 30 days)
            
        Returns:
            Secure URL with HMAC signature
        """
        expiry_hours = expiry_hours or self.default_expiry_hours
        
        # Calculate expiration timestamp
        expiry_timestamp = int(time.time()) + (expiry_hours * 3600)
        
        # Create payload
        payload = {
            'id': production_id,
            'exp': expiry_timestamp,
            'iat': int(time.time()),  # Issued at time
            'v': '1.0'  # Version for future compatibility
        }
        
        # Encode payload
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True).encode()
        ).decode().rstrip('=')
        
        # Generate HMAC signature
        signature = self._generate_hmac_signature(payload_b64)
        
        # Construct secure URL
        secure_url = f"{base_url}?p={payload_b64}&s={signature}"
        
        logger.info(f"Generated secure QR URL for production {production_id}, expires in {expiry_hours} hours")
        return secure_url
    
    def verify_qr_url(self, url: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Verify a secure QR code URL
        
        Args:
            url: URL to verify
            
        Returns:
            Tuple of (is_valid, payload_data, error_message)
        """
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            
            # Extract payload and signature
            payload_b64_list = query_params.get('p')
            signature_list = query_params.get('s')
            
            if not payload_b64_list or not signature_list:
                return False, None, "Missing payload or signature"
            
            payload_b64 = payload_b64_list[0]
            signature = signature_list[0]
            
            # Verify HMAC signature
            expected_signature = self._generate_hmac_signature(payload_b64)
            if not hmac.compare_digest(signature, expected_signature):
                logger.warning(f"QR URL HMAC signature verification failed for URL: {url}")
                return False, None, "Invalid signature"
            
            # Decode payload
            try:
                # Add padding if needed
                payload_b64_padded = payload_b64 + '=' * (4 - len(payload_b64) % 4)
                payload_json = base64.urlsafe_b64decode(payload_b64_padded).decode()
                payload = json.loads(payload_json)
            except (ValueError, json.JSONDecodeError) as e:
                return False, None, f"Invalid payload format: {e}"
            
            # Check expiration
            current_time = int(time.time())
            if payload.get('exp', 0) < current_time:
                return False, None, "QR code has expired"
            
            # Check issued at time (prevent future-dated tokens)
            if payload.get('iat', 0) > current_time + 300:  # 5 minute clock skew allowance
                return False, None, "QR code issued in the future"
            
            return True, payload, None
            
        except Exception as e:
            logger.error(f"Error verifying QR URL: {e}")
            return False, None, f"Verification error: {e}"
    
    def _generate_hmac_signature(self, payload_b64: str) -> str:
        """Generate HMAC signature for payload"""
        return hmac.new(
            self.secret_key.encode(),
            payload_b64.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def get_production_id_from_url(self, url: str) -> Optional[int]:
        """
        Extract production ID from a QR URL (secure or legacy)
        
        Args:
            url: QR code URL
            
        Returns:
            Production ID if found, None otherwise
        """
        try:
            # Try secure format first
            is_valid, payload, error = self.verify_qr_url(url)
            if is_valid and payload:
                return payload.get('id')
            
            # Fallback to legacy format
            parsed = urlparse(url)
            path_parts = parsed.path.strip('/').split('/')
            
            if len(path_parts) >= 2 and path_parts[0] == 'production':
                try:
                    return int(path_parts[1])
                except ValueError:
                    pass
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting production ID from URL: {e}")
            return None
    
    def is_secure_qr_url(self, url: str) -> bool:
        """
        Check if a URL is a secure QR code URL
        
        Args:
            url: URL to check
            
        Returns:
            True if URL has secure QR format, False otherwise
        """
        try:
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            return 'p' in query_params and 's' in query_params
        except:
            return False
    
    def get_qr_metadata(self, url: str) -> Dict:
        """
        Get metadata about a QR code URL
        
        Args:
            url: QR code URL
            
        Returns:
            Dictionary with metadata
        """
        metadata = {
            'url': url,
            'is_secure': self.is_secure_qr_url(url),
            'production_id': self.get_production_id_from_url(url),
            'verified': False,
            'expired': False,
            'error': None
        }
        
        if metadata['is_secure']:
            is_valid, payload, error = self.verify_qr_url(url)
            metadata['verified'] = is_valid
            metadata['error'] = error
            
            if payload:
                metadata['issued_at'] = datetime.fromtimestamp(payload.get('iat', 0))
                metadata['expires_at'] = datetime.fromtimestamp(payload.get('exp', 0))
                metadata['expired'] = payload.get('exp', 0) < int(time.time())
                metadata['version'] = payload.get('v', 'unknown')
        
        return metadata


# Global instance - lazy initialization
_qr_security_manager = None

def get_qr_security_manager():
    global _qr_security_manager
    if _qr_security_manager is None:
        _qr_security_manager = QRSecurityManager()
    return _qr_security_manager


def generate_secure_qr_url(base_url: str, production_id: int, expiry_hours: Optional[int] = None) -> str:
    """
    Convenience function to generate a secure QR URL
    
    Args:
        base_url: Base URL for the QR code
        production_id: Production ID
        expiry_hours: Hours until expiration
        
    Returns:
        Secure URL with HMAC signature
    """
    return get_qr_security_manager().generate_secure_qr_url(base_url, production_id, expiry_hours)


def verify_qr_url(url: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
    """
    Convenience function to verify a QR URL
    
    Args:
        url: URL to verify
        
    Returns:
        Tuple of (is_valid, payload_data, error_message)
    """
    return get_qr_security_manager().verify_qr_url(url)


def get_production_id_from_qr_url(url: str) -> Optional[int]:
    """
    Convenience function to extract production ID from QR URL
    
    Args:
        url: QR code URL
        
    Returns:
        Production ID if found, None otherwise
    """
    return get_qr_security_manager().get_production_id_from_url(url)