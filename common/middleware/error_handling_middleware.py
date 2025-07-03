"""
Enhanced Error Handling Middleware for Trazo
Provides comprehensive error handling, logging, and monitoring for all requests
"""

import json
import time
import uuid
from typing import Dict, Any, Optional
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, OperationalError
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed, NotFound
import logging

from common.services.enhanced_logging import get_logger, track_error

logger = get_logger(__name__)


class EnhancedErrorHandlingMiddleware(MiddlewareMixin):
    """
    Comprehensive error handling middleware
    
    Features:
    - Request/response tracking with unique IDs
    - Structured error logging
    - User-friendly error responses
    - Performance monitoring
    - Rate limiting for error-prone clients
    - Security incident detection
    """
    
    def __init__(self, get_response):
        super().__init__(get_response)
        self.get_response = get_response
        self.debug_mode = getattr(settings, 'DEBUG', False)
        
        # Error response templates
        self.error_templates = {
            'validation_error': {
                'error': 'Validation Error',
                'message': 'The submitted data is invalid.',
                'type': 'validation_error'
            },
            'authentication_error': {
                'error': 'Authentication Error',
                'message': 'Authentication credentials are required or invalid.',
                'type': 'authentication_error'
            },
            'permission_error': {
                'error': 'Permission Denied',
                'message': 'You do not have permission to perform this action.',
                'type': 'permission_error'
            },
            'not_found_error': {
                'error': 'Not Found',
                'message': 'The requested resource was not found.',
                'type': 'not_found_error'
            },
            'database_error': {
                'error': 'Database Error',
                'message': 'A database error occurred. Please try again later.',
                'type': 'database_error'
            },
            'server_error': {
                'error': 'Internal Server Error',
                'message': 'An internal server error occurred. Please try again later.',
                'type': 'server_error'
            },
            'rate_limit_error': {
                'error': 'Rate Limit Exceeded',
                'message': 'Too many requests. Please try again later.',
                'type': 'rate_limit_error'
            }
        }
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Process incoming request and set up tracking"""
        # Generate unique request ID
        request.request_id = str(uuid.uuid4())
        request.start_time = time.time()
        
        # Set logging context
        logger.set_context(
            request_id=request.request_id,
            method=request.method,
            path=request.path,
            user_id=getattr(request.user, 'id', None) if hasattr(request, 'user') else None,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            ip_address=self._get_client_ip(request)
        )
        
        # Log request start
        logger.info(f"Request started: {request.method} {request.path}")
        
        # Check for suspicious activity
        if self._detect_suspicious_activity(request):
            logger.warning("Suspicious activity detected", 
                         security_incident=True,
                         incident_type='suspicious_request')
        
        return None
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Process response and log completion"""
        if hasattr(request, 'start_time'):
            response_time = (time.time() - request.start_time) * 1000
            
            # Add response headers
            response['X-Request-ID'] = getattr(request, 'request_id', 'unknown')
            response['X-Response-Time'] = f"{response_time:.2f}ms"
            
            # Log response
            logger.info(f"Request completed: {response.status_code}",
                       response_time_ms=response_time,
                       status_code=response.status_code,
                       response_size=len(response.content) if hasattr(response, 'content') else 0)
        
        logger.clear_context()
        return response
    
    def process_exception(self, request: HttpRequest, exception: Exception) -> Optional[HttpResponse]:
        """Process unhandled exceptions"""
        request_id = getattr(request, 'request_id', str(uuid.uuid4()))
        
        # Track error
        error_context = {
            'request_id': request_id,
            'method': request.method,
            'path': request.path,
            'user_id': getattr(request.user, 'id', None) if hasattr(request, 'user') else None,
            'ip_address': self._get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'query_params': dict(request.GET),
            'post_data_size': len(request.body) if hasattr(request, 'body') else 0
        }
        
        track_error(exception, error_context)
        
        # Determine error type and response
        error_response = self._create_error_response(exception, request_id)
        
        # Log error with appropriate level
        if isinstance(exception, (ValidationError, PermissionDenied, NotFound)):
            logger.warning(f"Client error: {type(exception).__name__}: {str(exception)}")
        else:
            logger.error(f"Server error: {type(exception).__name__}: {str(exception)}", 
                        error=exception)
        
        # Add security monitoring for certain error types
        if isinstance(exception, (PermissionDenied, AuthenticationFailed)):
            self._track_security_event(request, exception)
        
        return error_response
    
    def _get_client_ip(self, request: HttpRequest) -> str:
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip
    
    def _detect_suspicious_activity(self, request: HttpRequest) -> bool:
        """Detect potentially suspicious request patterns"""
        suspicious_patterns = [
            # SQL injection attempts
            any(pattern in request.path.lower() for pattern in [
                'union', 'select', 'drop', 'insert', 'update', 'delete',
                'script', 'javascript:', 'vbscript:', 'onload', 'onerror'
            ]),
            
            # Path traversal attempts
            '..' in request.path or '/etc/' in request.path,
            
            # Unusual user agents
            request.META.get('HTTP_USER_AGENT', '').lower() in [
                'curl', 'wget', 'python-requests', 'bot', 'scanner'
            ],
            
            # Excessive request size
            len(request.body) > 10 * 1024 * 1024 if hasattr(request, 'body') else False,  # 10MB
            
            # Missing common headers
            not request.META.get('HTTP_USER_AGENT'),
        ]
        
        return any(suspicious_patterns)
    
    def _track_security_event(self, request: HttpRequest, exception: Exception):
        """Track security-related events"""
        security_context = {
            'event_type': 'authentication_failure' if isinstance(exception, AuthenticationFailed) else 'permission_denied',
            'ip_address': self._get_client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'path': request.path,
            'method': request.method,
            'timestamp': timezone.now().isoformat()
        }
        
        logger.warning("Security event detected", 
                      security_incident=True,
                      **security_context)
    
    def _create_error_response(self, exception: Exception, request_id: str) -> JsonResponse:
        """Create standardized error response"""
        # Determine error type and status code
        if isinstance(exception, ValidationError):
            error_data = self.error_templates['validation_error'].copy()
            status_code = status.HTTP_400_BAD_REQUEST
            
            # Add validation details if available
            if hasattr(exception, 'message_dict'):
                error_data['details'] = exception.message_dict
            elif hasattr(exception, 'messages'):
                error_data['details'] = list(exception.messages)
                
        elif isinstance(exception, AuthenticationFailed):
            error_data = self.error_templates['authentication_error'].copy()
            status_code = status.HTTP_401_UNAUTHORIZED
            
        elif isinstance(exception, PermissionDenied):
            error_data = self.error_templates['permission_error'].copy()
            status_code = status.HTTP_403_FORBIDDEN
            
        elif isinstance(exception, NotFound):
            error_data = self.error_templates['not_found_error'].copy()
            status_code = status.HTTP_404_NOT_FOUND
            
        elif isinstance(exception, (IntegrityError, OperationalError)):
            error_data = self.error_templates['database_error'].copy()
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            
        elif isinstance(exception, APIException):
            error_data = {
                'error': exception.__class__.__name__,
                'message': str(exception.detail) if hasattr(exception, 'detail') else str(exception),
                'type': 'api_error'
            }
            status_code = getattr(exception, 'status_code', status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        else:
            error_data = self.error_templates['server_error'].copy()
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        
        # Add common fields
        error_data.update({
            'request_id': request_id,
            'timestamp': timezone.now().isoformat(),
            'status_code': status_code
        })
        
        # Add debug information in development
        if self.debug_mode:
            error_data['debug'] = {
                'exception_type': exception.__class__.__name__,
                'exception_message': str(exception),
                'module': getattr(exception, '__module__', 'unknown')
            }
        
        return JsonResponse(error_data, status=status_code)


class APIRateLimitMiddleware(MiddlewareMixin):
    """
    API rate limiting middleware with enhanced error handling
    """
    
    def __init__(self, get_response):
        super().__init__(get_response)
        self.get_response = get_response
        self.rate_limits = {
            'default': {'requests': 1000, 'window': 3600},  # 1000 requests per hour
            'api': {'requests': 100, 'window': 300},         # 100 requests per 5 minutes
            'auth': {'requests': 10, 'window': 300},         # 10 auth attempts per 5 minutes
        }
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Check rate limits for incoming requests"""
        if not self._should_rate_limit(request):
            return None
        
        client_ip = self._get_client_ip(request)
        rate_limit_key = self._get_rate_limit_key(request, client_ip)
        
        if self._is_rate_limited(rate_limit_key, request):
            logger.warning("Rate limit exceeded", 
                          ip_address=client_ip,
                          path=request.path,
                          rate_limit_exceeded=True)
            
            error_data = {
                'error': 'Rate Limit Exceeded',
                'message': 'Too many requests. Please try again later.',
                'type': 'rate_limit_error',
                'request_id': getattr(request, 'request_id', str(uuid.uuid4())),
                'timestamp': timezone.now().isoformat(),
                'retry_after': self._get_retry_after(request)
            }
            
            response = JsonResponse(error_data, status=status.HTTP_429_TOO_MANY_REQUESTS)
            response['Retry-After'] = str(self._get_retry_after(request))
            return response
        
        return None
    
    def _should_rate_limit(self, request: HttpRequest) -> bool:
        """Determine if request should be rate limited"""
        # Skip rate limiting for certain paths
        skip_paths = ['/health/', '/metrics/', '/admin/']
        return not any(request.path.startswith(path) for path in skip_paths)
    
    def _get_client_ip(self, request: HttpRequest) -> str:
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '')
        return ip
    
    def _get_rate_limit_key(self, request: HttpRequest, client_ip: str) -> str:
        """Generate rate limit key"""
        if request.path.startswith('/api/auth/'):
            limit_type = 'auth'
        elif request.path.startswith('/api/'):
            limit_type = 'api'
        else:
            limit_type = 'default'
        
        return f"rate_limit_{limit_type}_{client_ip}"
    
    def _is_rate_limited(self, rate_limit_key: str, request: HttpRequest) -> bool:
        """Check if client has exceeded rate limit"""
        from django.core.cache import cache
        
        # Get rate limit configuration
        if request.path.startswith('/api/auth/'):
            config = self.rate_limits['auth']
        elif request.path.startswith('/api/'):
            config = self.rate_limits['api']
        else:
            config = self.rate_limits['default']
        
        # Get current request count
        current_requests = cache.get(rate_limit_key, 0)
        
        if current_requests >= config['requests']:
            return True
        
        # Increment request count
        cache.set(rate_limit_key, current_requests + 1, config['window'])
        return False
    
    def _get_retry_after(self, request: HttpRequest) -> int:
        """Get retry after seconds"""
        if request.path.startswith('/api/auth/'):
            return self.rate_limits['auth']['window']
        elif request.path.startswith('/api/'):
            return self.rate_limits['api']['window']
        else:
            return self.rate_limits['default']['window']


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Enhanced request logging middleware
    """
    
    def __init__(self, get_response):
        super().__init__(get_response)
        self.get_response = get_response
        self.logger = get_logger('trazo.requests')
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Log request details"""
        request.log_start_time = time.time()
        
        # Log request with structured data
        self.logger.info("Request received", 
                        method=request.method,
                        path=request.path,
                        query_params=dict(request.GET),
                        content_type=request.content_type,
                        content_length=len(request.body) if hasattr(request, 'body') else 0,
                        user_id=getattr(request.user, 'id', None) if hasattr(request, 'user') else None)
        
        return None
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Log response details"""
        if hasattr(request, 'log_start_time'):
            response_time = (time.time() - request.log_start_time) * 1000
            
            self.logger.info("Response sent",
                           status_code=response.status_code,
                           response_time_ms=round(response_time, 2),
                           content_length=len(response.content) if hasattr(response, 'content') else 0)
        
        return response