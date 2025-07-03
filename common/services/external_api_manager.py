"""
External API Manager with Comprehensive Circuit Breaker Integration
Centralizes all external API calls with circuit breaker protection, retry logic, and fallback mechanisms
"""

import logging
import requests
from typing import Dict, Any, Optional, Callable, List, Union
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
import json
import time
from datetime import datetime, timedelta

from carbon.services.circuit_breaker_enhanced import (
    circuit_manager,
    usda_circuit_breaker,
    stripe_circuit_breaker,
    blockchain_circuit_breaker,
    usda_fallback_response,
    stripe_fallback_response,
    blockchain_fallback_response,
    CircuitBreakerError
)

logger = logging.getLogger(__name__)


class ExternalAPIManager:
    """
    Centralized manager for all external API calls with circuit breaker protection
    
    Provides:
    - Circuit breaker protection for all external services
    - Standardized error handling and logging
    - Fallback mechanisms and caching
    - Rate limiting and request optimization
    - Comprehensive monitoring and metrics
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Trazo-Backend/1.0 (Agricultural Carbon Platform)',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        # Service-specific configurations
        self.service_configs = {
            'usda_nass': {
                'base_url': 'https://quickstats.nass.usda.gov/api',
                'circuit_breaker_type': 'usda_api',
                'timeout': 30,
                'rate_limit_per_minute': 10,
                'cache_ttl': 3600,  # 1 hour
                'fallback_enabled': True
            },
            'usda_fooddata': {
                'base_url': 'https://api.nal.usda.gov/fdc/v1',
                'circuit_breaker_type': 'usda_api',
                'timeout': 25,
                'rate_limit_per_minute': 15,
                'cache_ttl': 7200,  # 2 hours
                'fallback_enabled': True
            },
            'usda_ers': {
                'base_url': 'https://api.ers.usda.gov/data',
                'circuit_breaker_type': 'usda_api',
                'timeout': 30,
                'rate_limit_per_minute': 8,
                'cache_ttl': 3600,
                'fallback_enabled': True
            },
            'stripe': {
                'base_url': 'https://api.stripe.com/v1',
                'circuit_breaker_type': 'stripe_api',
                'timeout': 30,
                'rate_limit_per_minute': 100,
                'cache_ttl': 300,  # 5 minutes for billing data
                'fallback_enabled': True
            },
            'polygon_rpc': {
                'base_url': getattr(settings, 'POLYGON_RPC_URL', 'https://polygon-rpc.com'),
                'circuit_breaker_type': 'blockchain_api',
                'timeout': 45,
                'rate_limit_per_minute': 30,
                'cache_ttl': 60,  # 1 minute for blockchain data
                'fallback_enabled': True
            },
            'ipfs': {
                'base_url': getattr(settings, 'IPFS_GATEWAY_URL', 'https://ipfs.io'),
                'circuit_breaker_type': 'default',
                'timeout': 60,
                'rate_limit_per_minute': 20,
                'cache_ttl': 1800,  # 30 minutes
                'fallback_enabled': False
            }
        }
        
        logger.info("ExternalAPIManager initialized with circuit breaker protection")
    
    def _get_rate_limit_key(self, service_name: str) -> str:
        """Get cache key for rate limiting"""
        return f"api_rate_limit_{service_name}_{timezone.now().strftime('%Y%m%d%H%M')}"
    
    def _check_rate_limit(self, service_name: str) -> bool:
        """Check if request is within rate limits"""
        config = self.service_configs.get(service_name, {})
        rate_limit = config.get('rate_limit_per_minute', 60)
        
        rate_key = self._get_rate_limit_key(service_name)
        current_count = cache.get(rate_key, 0)
        
        if current_count >= rate_limit:
            logger.warning(f"Rate limit exceeded for {service_name}: {current_count}/{rate_limit}")
            return False
        
        # Increment counter
        cache.set(rate_key, current_count + 1, 60)  # 1 minute TTL
        return True
    
    def _get_cache_key(self, service_name: str, endpoint: str, params: Dict[str, Any]) -> str:
        """Generate cache key for API response"""
        import hashlib
        
        # Create consistent hash from params
        param_str = json.dumps(params, sort_keys=True)
        param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]
        
        return f"api_cache_{service_name}_{endpoint.replace('/', '_')}_{param_hash}"
    
    def _get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached API response"""
        try:
            cached = cache.get(cache_key)
            if cached:
                # Add cache metadata
                cached['_cached'] = True
                cached['_cache_timestamp'] = cached.get('_cache_timestamp', timezone.now().isoformat())
                return cached
        except Exception as e:
            logger.error(f"Cache retrieval failed: {e}")
        
        return None
    
    def _cache_response(self, cache_key: str, response: Dict[str, Any], ttl: int):
        """Cache API response"""
        try:
            # Add cache metadata
            response['_cache_timestamp'] = timezone.now().isoformat()
            cache.set(cache_key, response, ttl)
        except Exception as e:
            logger.error(f"Cache storage failed: {e}")
    
    @usda_circuit_breaker('usda_nass_api')
    def call_usda_nass(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make USDA NASS API call with circuit breaker protection"""
        return self._make_api_call('usda_nass', endpoint, params)
    
    @usda_circuit_breaker('usda_fooddata_api')
    def call_usda_fooddata(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make USDA FoodData Central API call with circuit breaker protection"""
        return self._make_api_call('usda_fooddata', endpoint, params)
    
    @usda_circuit_breaker('usda_ers_api')
    def call_usda_ers(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make USDA ERS API call with circuit breaker protection"""
        return self._make_api_call('usda_ers', endpoint, params)
    
    @stripe_circuit_breaker('stripe_api')
    def call_stripe(self, endpoint: str, params: Dict[str, Any], method: str = 'GET') -> Dict[str, Any]:
        """Make Stripe API call with circuit breaker protection"""
        return self._make_api_call('stripe', endpoint, params, method=method)
    
    @blockchain_circuit_breaker('polygon_rpc')
    def call_polygon_rpc(self, method: str, params: List[Any]) -> Dict[str, Any]:
        """Make Polygon RPC call with circuit breaker protection"""
        rpc_data = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': int(time.time())
        }
        return self._make_api_call('polygon_rpc', '', rpc_data, method='POST')
    
    def _make_api_call(self, service_name: str, endpoint: str, params: Dict[str, Any], 
                      method: str = 'GET', headers: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Make API call with comprehensive error handling and circuit breaker protection
        
        Args:
            service_name: Name of the service (usda_nass, stripe, etc.)
            endpoint: API endpoint path
            params: Request parameters
            method: HTTP method (GET, POST, etc.)
            headers: Additional headers
            
        Returns:
            API response data
        """
        config = self.service_configs.get(service_name)
        if not config:
            raise ValueError(f"Unknown service: {service_name}")
        
        # Check rate limiting
        if not self._check_rate_limit(service_name):
            raise Exception(f"Rate limit exceeded for {service_name}")
        
        # Check cache first
        cache_key = self._get_cache_key(service_name, endpoint, params)
        cached_response = self._get_cached_response(cache_key)
        if cached_response:
            logger.debug(f"Cache hit for {service_name} {endpoint}")
            return cached_response
        
        # Prepare request
        base_url = config['base_url']
        url = f"{base_url}/{endpoint.lstrip('/')}" if endpoint else base_url
        timeout = config.get('timeout', 30)
        
        # Merge headers
        request_headers = self.session.headers.copy()
        if headers:
            request_headers.update(headers)
        
        # Add service-specific headers
        if service_name == 'stripe':
            stripe_key = self._get_stripe_key()
            request_headers['Authorization'] = f'Bearer {stripe_key}'
        
        start_time = time.time()
        
        try:
            logger.debug(f"Making {method} request to {service_name}: {url}")
            
            if method.upper() == 'GET':
                response = self.session.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=timeout
                )
            elif method.upper() == 'POST':
                response = self.session.post(
                    url,
                    json=params,
                    headers=request_headers,
                    timeout=timeout
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response_time = time.time() - start_time
            logger.debug(f"{service_name} API call completed in {response_time:.2f}s")
            
            # Check response status
            response.raise_for_status()
            
            # Parse response
            try:
                response_data = response.json()
            except ValueError:
                response_data = {'raw_response': response.text}
            
            # Add metadata
            response_data.update({
                '_service': service_name,
                '_endpoint': endpoint,
                '_response_time_ms': round(response_time * 1000, 2),
                '_timestamp': timezone.now().isoformat(),
                '_cached': False
            })
            
            # Cache successful responses
            cache_ttl = config.get('cache_ttl', 3600)
            self._cache_response(cache_key, response_data, cache_ttl)
            
            return response_data
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout calling {service_name} API: {url}")
            raise Exception(f"API timeout for {service_name}")
            
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error calling {service_name} API: {url}")
            raise Exception(f"Connection error for {service_name}")
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 'unknown'
            logger.error(f"HTTP error {status_code} calling {service_name} API: {url}")
            raise Exception(f"HTTP {status_code} error for {service_name}")
            
        except Exception as e:
            logger.error(f"Unexpected error calling {service_name} API: {e}")
            raise
    
    def _get_stripe_key(self) -> str:
        """Get Stripe API key from secure storage"""
        from backend.services.secrets_manager import secrets_manager
        return secrets_manager.get_secret('stripe_api_key', required=True)
    
    def get_service_health(self) -> Dict[str, Any]:
        """Get health status of all external services"""
        health_data = {}
        
        for service_name in self.service_configs.keys():
            circuit_breaker = circuit_manager.get_circuit_breaker(
                f"{service_name}_api", 
                self.service_configs[service_name]['circuit_breaker_type']
            )
            
            metrics = circuit_breaker.get_metrics()
            
            # Determine health status
            if metrics['state'] == 'open':
                status = 'unhealthy'
            elif metrics['state'] == 'half_open':
                status = 'recovering'
            else:
                # Check success rate
                success_rate = metrics['success_rate_percent']
                if success_rate >= 95:
                    status = 'healthy'
                elif success_rate >= 80:
                    status = 'degraded'
                else:
                    status = 'unhealthy'
            
            health_data[service_name] = {
                'status': status,
                'circuit_state': metrics['state'],
                'success_rate': metrics['success_rate_percent'],
                'total_requests': metrics['total_requests'],
                'average_response_time_ms': metrics['average_response_time_ms'],
                'last_success': metrics['last_success_time'],
                'last_failure': metrics['last_failure_time']
            }
        
        # Overall health
        unhealthy_services = [s for s, h in health_data.items() if h['status'] == 'unhealthy']
        degraded_services = [s for s, h in health_data.items() if h['status'] == 'degraded']
        
        if unhealthy_services:
            overall_status = 'critical' if len(unhealthy_services) > 1 else 'degraded'
        elif degraded_services:
            overall_status = 'degraded'
        else:
            overall_status = 'healthy'
        
        return {
            'overall_status': overall_status,
            'services': health_data,
            'unhealthy_services': unhealthy_services,
            'degraded_services': degraded_services,
            'timestamp': timezone.now().isoformat()
        }
    
    def reset_circuit_breakers(self, service_name: str = None):
        """Reset circuit breakers for specific service or all services"""
        if service_name:
            circuit_breaker = circuit_manager.get_circuit_breaker(
                f"{service_name}_api",
                self.service_configs[service_name]['circuit_breaker_type']
            )
            circuit_breaker.reset()
            logger.info(f"Reset circuit breaker for {service_name}")
        else:
            circuit_manager.reset_all()
            logger.info("Reset all circuit breakers")
    
    def clear_cache(self, service_name: str = None):
        """Clear cached responses for specific service or all services"""
        if service_name:
            # Clear specific service cache
            pattern = f"api_cache_{service_name}_*"
            # Note: Django cache doesn't support pattern deletion by default
            # This would need custom implementation or Redis backend
            logger.info(f"Cache clear requested for {service_name}")
        else:
            # Clear all API cache
            logger.info("Cache clear requested for all services")


# Global API manager instance
api_manager = ExternalAPIManager()


# Convenience functions for common API calls
def call_usda_nass_api(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function for USDA NASS API calls"""
    return api_manager.call_usda_nass(endpoint, params)


def call_usda_fooddata_api(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function for USDA FoodData Central API calls"""
    return api_manager.call_usda_fooddata(endpoint, params)


def call_stripe_api(endpoint: str, params: Dict[str, Any], method: str = 'GET') -> Dict[str, Any]:
    """Convenience function for Stripe API calls"""
    return api_manager.call_stripe(endpoint, params, method)


def call_polygon_rpc(method: str, params: List[Any]) -> Dict[str, Any]:
    """Convenience function for Polygon RPC calls"""
    return api_manager.call_polygon_rpc(method, params)


def get_external_api_health() -> Dict[str, Any]:
    """Get health status of all external APIs"""
    return api_manager.get_service_health()