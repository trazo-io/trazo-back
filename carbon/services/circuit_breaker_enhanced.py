"""
Enhanced Circuit Breaker Implementation for Trazo
Provides comprehensive circuit breaker pattern for all external API calls
Addresses production readiness requirement for API resilience
"""

import logging
import time
import threading
from typing import Dict, Any, Callable, Optional, List, Union
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
import json
import hashlib
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"           # Normal operation
    OPEN = "open"              # Failing, blocking calls
    HALF_OPEN = "half_open"    # Testing if service is back


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5           # Number of failures before opening
    timeout_seconds: int = 60           # Time to wait before testing service
    success_threshold: int = 3          # Successes needed to close circuit
    request_timeout: int = 30           # Individual request timeout
    max_retry_attempts: int = 3         # Max retries before considering failure
    exponential_backoff: bool = True    # Use exponential backoff for retries
    fallback_enabled: bool = True       # Enable fallback responses
    metrics_enabled: bool = True        # Track detailed metrics
    health_check_enabled: bool = True   # Periodic health checks


@dataclass
class CircuitMetrics:
    """Metrics tracking for circuit breaker"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeouts: int = 0
    circuit_opens: int = 0
    circuit_closes: int = 0
    fallback_uses: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    average_response_time: float = 0.0
    error_types: Dict[str, int] = field(default_factory=dict)


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open"""
    def __init__(self, service_name: str, last_failure: str = None):
        self.service_name = service_name
        self.last_failure = last_failure
        message = f"Circuit breaker OPEN for {service_name}"
        if last_failure:
            message += f" - Last failure: {last_failure}"
        super().__init__(message)


class FallbackNotAvailableError(Exception):
    """Raised when fallback mechanism is not available"""
    pass


class EnhancedCircuitBreaker:
    """
    Enhanced circuit breaker with comprehensive failure handling
    
    Features:
    - Configurable thresholds and timeouts
    - Exponential backoff for retries
    - Fallback mechanisms
    - Detailed metrics tracking
    - Health check integration
    - Cache-based state persistence
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.lock = threading.RLock()
        
        # State management
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._next_attempt_time = None
        
        # Metrics
        self.metrics = CircuitMetrics()
        
        # Cache keys
        self.state_cache_key = f"circuit_breaker_state_{self.name}"
        self.metrics_cache_key = f"circuit_breaker_metrics_{self.name}"
        
        # Load persisted state
        self._load_state()
        
        logger.info(f"CircuitBreaker '{self.name}' initialized - State: {self.state}")
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state"""
        return self._state
    
    def _load_state(self):
        """Load circuit state from cache"""
        try:
            cached_state = cache.get(self.state_cache_key)
            if cached_state:
                self._state = CircuitState(cached_state.get('state', 'closed'))
                self._failure_count = cached_state.get('failure_count', 0)
                self._success_count = cached_state.get('success_count', 0)
                
                last_failure = cached_state.get('last_failure_time')
                if last_failure:
                    self._last_failure_time = datetime.fromisoformat(last_failure)
                
                next_attempt = cached_state.get('next_attempt_time')
                if next_attempt:
                    self._next_attempt_time = datetime.fromisoformat(next_attempt)
            
            # Load metrics
            cached_metrics = cache.get(self.metrics_cache_key)
            if cached_metrics:
                self.metrics = CircuitMetrics(**cached_metrics)
                
        except Exception as e:
            logger.warning(f"Failed to load circuit breaker state for {self.name}: {e}")
    
    def _save_state(self):
        """Save circuit state to cache"""
        try:
            state_data = {
                'state': self._state.value,
                'failure_count': self._failure_count,
                'success_count': self._success_count,
                'last_failure_time': self._last_failure_time.isoformat() if self._last_failure_time else None,
                'next_attempt_time': self._next_attempt_time.isoformat() if self._next_attempt_time else None,
                'updated_at': timezone.now().isoformat()
            }
            cache.set(self.state_cache_key, state_data, 86400)  # 24 hours
            
            # Save metrics
            if self.config.metrics_enabled:
                metrics_data = {
                    'total_requests': self.metrics.total_requests,
                    'successful_requests': self.metrics.successful_requests,
                    'failed_requests': self.metrics.failed_requests,
                    'timeouts': self.metrics.timeouts,
                    'circuit_opens': self.metrics.circuit_opens,
                    'circuit_closes': self.metrics.circuit_closes,
                    'fallback_uses': self.metrics.fallback_uses,
                    'last_failure_time': self.metrics.last_failure_time.isoformat() if self.metrics.last_failure_time else None,
                    'last_success_time': self.metrics.last_success_time.isoformat() if self.metrics.last_success_time else None,
                    'average_response_time': self.metrics.average_response_time,
                    'error_types': self.metrics.error_types
                }
                cache.set(self.metrics_cache_key, metrics_data, 86400)
                
        except Exception as e:
            logger.error(f"Failed to save circuit breaker state for {self.name}: {e}")
    
    def _can_attempt(self) -> bool:
        """Check if a request attempt is allowed"""
        with self.lock:
            if self._state == CircuitState.CLOSED:
                return True
            elif self._state == CircuitState.OPEN:
                # Check if timeout period has passed
                if self._next_attempt_time and datetime.now() >= self._next_attempt_time:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info(f"CircuitBreaker '{self.name}' moved to HALF_OPEN")
                    self._save_state()
                    return True
                return False
            elif self._state == CircuitState.HALF_OPEN:
                return True
            
        return False
    
    def _record_success(self, response_time: float = None):
        """Record a successful request"""
        with self.lock:
            self.metrics.total_requests += 1
            self.metrics.successful_requests += 1
            self.metrics.last_success_time = datetime.now()
            
            # Update average response time
            if response_time:
                if self.metrics.average_response_time == 0:
                    self.metrics.average_response_time = response_time
                else:
                    # Exponential moving average
                    self.metrics.average_response_time = (
                        0.9 * self.metrics.average_response_time + 0.1 * response_time
                    )
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self.metrics.circuit_closes += 1
                    logger.info(f"CircuitBreaker '{self.name}' CLOSED - Service recovered")
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
            
            self._save_state()
    
    def _record_failure(self, error: Exception):
        """Record a failed request"""
        with self.lock:
            self.metrics.total_requests += 1
            self.metrics.failed_requests += 1
            self.metrics.last_failure_time = datetime.now()
            
            # Track error types
            error_type = type(error).__name__
            self.metrics.error_types[error_type] = self.metrics.error_types.get(error_type, 0) + 1
            
            # Special handling for timeouts
            if 'timeout' in error_type.lower():
                self.metrics.timeouts += 1
            
            self._failure_count += 1
            self._last_failure_time = datetime.now()
            
            # Check if we should open the circuit
            if (self._state == CircuitState.CLOSED and 
                self._failure_count >= self.config.failure_threshold):
                
                self._state = CircuitState.OPEN
                self._next_attempt_time = datetime.now() + timedelta(seconds=self.config.timeout_seconds)
                self.metrics.circuit_opens += 1
                
                logger.error(f"CircuitBreaker '{self.name}' OPENED - Too many failures ({self._failure_count})")
                
            elif self._state == CircuitState.HALF_OPEN:
                # Return to open state on failure during half-open
                self._state = CircuitState.OPEN
                self._next_attempt_time = datetime.now() + timedelta(seconds=self.config.timeout_seconds)
                logger.warning(f"CircuitBreaker '{self.name}' returned to OPEN from HALF_OPEN")
            
            self._save_state()
    
    def call(self, func: Callable, *args, fallback: Callable = None, **kwargs) -> Any:
        """
        Execute a function call with circuit breaker protection
        
        Args:
            func: Function to call
            *args: Function arguments
            fallback: Fallback function to call if circuit is open
            **kwargs: Function keyword arguments
            
        Returns:
            Function result or fallback result
            
        Raises:
            CircuitBreakerError: If circuit is open and no fallback
        """
        if not self._can_attempt():
            logger.warning(f"CircuitBreaker '{self.name}' is OPEN - request blocked")
            
            if fallback and self.config.fallback_enabled:
                logger.info(f"Using fallback for {self.name}")
                self.metrics.fallback_uses += 1
                return fallback(*args, **kwargs)
            else:
                raise CircuitBreakerError(
                    self.name, 
                    str(self._last_failure_time) if self._last_failure_time else None
                )
        
        # Attempt the call with retries
        last_exception = None
        start_time = time.time()
        
        for attempt in range(self.config.max_retry_attempts):
            try:
                if attempt > 0:
                    # Exponential backoff
                    if self.config.exponential_backoff:
                        delay = min(2 ** attempt, 10)  # Max 10 seconds
                        time.sleep(delay)
                        logger.debug(f"Retry {attempt + 1} for {self.name} after {delay}s delay")
                
                # Execute the function
                result = func(*args, **kwargs)
                
                # Record success
                response_time = time.time() - start_time
                self._record_success(response_time)
                
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"Attempt {attempt + 1} failed for {self.name}: {e}")
                
                # Don't retry for certain error types
                if self._is_non_retryable_error(e):
                    break
        
        # All retries failed
        self._record_failure(last_exception)
        
        # Try fallback if available
        if fallback and self.config.fallback_enabled:
            logger.info(f"All retries failed for {self.name}, using fallback")
            self.metrics.fallback_uses += 1
            return fallback(*args, **kwargs)
        
        # No fallback, raise the last exception
        raise last_exception
    
    def _is_non_retryable_error(self, error: Exception) -> bool:
        """Check if error should not be retried"""
        non_retryable = [
            'AuthenticationError',
            'PermissionError',
            'ValueError',
            'TypeError',
            'KeyError'
        ]
        
        error_type = type(error).__name__
        return error_type in non_retryable
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics"""
        with self.lock:
            success_rate = 0
            if self.metrics.total_requests > 0:
                success_rate = (self.metrics.successful_requests / self.metrics.total_requests) * 100
            
            return {
                'name': self.name,
                'state': self._state.value,
                'failure_count': self._failure_count,
                'success_count': self._success_count,
                'total_requests': self.metrics.total_requests,
                'successful_requests': self.metrics.successful_requests,
                'failed_requests': self.metrics.failed_requests,
                'success_rate_percent': round(success_rate, 2),
                'timeouts': self.metrics.timeouts,
                'circuit_opens': self.metrics.circuit_opens,
                'circuit_closes': self.metrics.circuit_closes,
                'fallback_uses': self.metrics.fallback_uses,
                'average_response_time_ms': round(self.metrics.average_response_time * 1000, 2),
                'last_failure_time': self.metrics.last_failure_time.isoformat() if self.metrics.last_failure_time else None,
                'last_success_time': self.metrics.last_success_time.isoformat() if self.metrics.last_success_time else None,
                'error_types': self.metrics.error_types,
                'next_attempt_time': self._next_attempt_time.isoformat() if self._next_attempt_time else None
            }
    
    def reset(self):
        """Manually reset circuit breaker to closed state"""
        with self.lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._next_attempt_time = None
            self._save_state()
            
            logger.info(f"CircuitBreaker '{self.name}' manually reset to CLOSED")
    
    def force_open(self):
        """Manually force circuit breaker to open state"""
        with self.lock:
            self._state = CircuitState.OPEN
            self._next_attempt_time = datetime.now() + timedelta(seconds=self.config.timeout_seconds)
            self.metrics.circuit_opens += 1
            self._save_state()
            
            logger.warning(f"CircuitBreaker '{self.name}' manually forced to OPEN")


class CircuitBreakerManager:
    """
    Manager for multiple circuit breakers
    Provides centralized management and monitoring
    """
    
    def __init__(self):
        self.circuit_breakers: Dict[str, EnhancedCircuitBreaker] = {}
        self.lock = threading.RLock()
        
        # Default configurations for different service types
        self.default_configs = {
            'usda_api': CircuitBreakerConfig(
                failure_threshold=3,
                timeout_seconds=30,
                success_threshold=2,
                request_timeout=15,
                max_retry_attempts=2
            ),
            'stripe_api': CircuitBreakerConfig(
                failure_threshold=5,
                timeout_seconds=60,
                success_threshold=3,
                request_timeout=30,
                max_retry_attempts=3
            ),
            'blockchain_api': CircuitBreakerConfig(
                failure_threshold=2,
                timeout_seconds=120,
                success_threshold=3,
                request_timeout=45,
                max_retry_attempts=2
            ),
            'default': CircuitBreakerConfig()
        }
        
        logger.info("CircuitBreakerManager initialized")
    
    def get_circuit_breaker(self, name: str, service_type: str = 'default') -> EnhancedCircuitBreaker:
        """Get or create a circuit breaker for a service"""
        with self.lock:
            if name not in self.circuit_breakers:
                config = self.default_configs.get(service_type, self.default_configs['default'])
                self.circuit_breakers[name] = EnhancedCircuitBreaker(name, config)
                
            return self.circuit_breakers[name]
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers"""
        with self.lock:
            return {
                name: breaker.get_metrics() 
                for name, breaker in self.circuit_breakers.items()
            }
    
    def reset_all(self):
        """Reset all circuit breakers"""
        with self.lock:
            for breaker in self.circuit_breakers.values():
                breaker.reset()
            logger.info("All circuit breakers reset")
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary"""
        with self.lock:
            total_circuits = len(self.circuit_breakers)
            open_circuits = sum(1 for cb in self.circuit_breakers.values() if cb.state == CircuitState.OPEN)
            half_open_circuits = sum(1 for cb in self.circuit_breakers.values() if cb.state == CircuitState.HALF_OPEN)
            
            overall_health = "healthy"
            if open_circuits > 0:
                overall_health = "degraded" if open_circuits < total_circuits else "critical"
            elif half_open_circuits > 0:
                overall_health = "recovering"
            
            return {
                'overall_health': overall_health,
                'total_circuits': total_circuits,
                'open_circuits': open_circuits,
                'half_open_circuits': half_open_circuits,
                'closed_circuits': total_circuits - open_circuits - half_open_circuits,
                'timestamp': timezone.now().isoformat()
            }


# Global circuit breaker manager
circuit_manager = CircuitBreakerManager()


# Decorator for easy circuit breaker application
def circuit_breaker(service_name: str, service_type: str = 'default', fallback: Callable = None):
    """
    Decorator to apply circuit breaker to a function
    
    Args:
        service_name: Name of the service for circuit breaker
        service_type: Type of service (usda_api, stripe_api, blockchain_api, default)
        fallback: Fallback function to call if circuit is open
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cb = circuit_manager.get_circuit_breaker(service_name, service_type)
            return cb.call(func, *args, fallback=fallback, **kwargs)
        return wrapper
    return decorator


# Convenience functions for specific service types
def usda_circuit_breaker(service_name: str, fallback: Callable = None):
    """Circuit breaker specifically configured for USDA APIs"""
    return circuit_breaker(service_name, 'usda_api', fallback)


def stripe_circuit_breaker(service_name: str, fallback: Callable = None):
    """Circuit breaker specifically configured for Stripe API"""
    return circuit_breaker(service_name, 'stripe_api', fallback)


def blockchain_circuit_breaker(service_name: str, fallback: Callable = None):
    """Circuit breaker specifically configured for Blockchain APIs"""
    return circuit_breaker(service_name, 'blockchain_api', fallback)


# Fallback functions for common services
def usda_fallback_response(endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """Standard fallback response for USDA API failures"""
    return {
        'success': False,
        'data': None,
        'fallback': True,
        'message': f'USDA API temporarily unavailable - using fallback',
        'endpoint': endpoint,
        'timestamp': timezone.now().isoformat(),
        'cache_source': 'fallback_mechanism'
    }


def stripe_fallback_response(operation: str, **kwargs) -> Dict[str, Any]:
    """Standard fallback response for Stripe API failures"""
    return {
        'success': False,
        'fallback': True,
        'message': f'Stripe API temporarily unavailable - {operation} deferred',
        'operation': operation,
        'timestamp': timezone.now().isoformat(),
        'retry_required': True
    }


def blockchain_fallback_response(operation: str, **kwargs) -> Dict[str, Any]:
    """Standard fallback response for Blockchain API failures"""
    return {
        'success': False,
        'fallback': True,
        'message': f'Blockchain network temporarily unavailable - {operation} queued',
        'operation': operation,
        'timestamp': timezone.now().isoformat(),
        'queue_for_retry': True
    }