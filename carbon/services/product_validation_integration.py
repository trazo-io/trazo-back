"""
PRODUCT VALIDATION INTEGRATION
Integrates product validation with existing ChemicalEvent serializer.
Provides backward-compatible validation and warnings for immediate deployment.
"""

import logging
from typing import Dict, List, Optional
from rest_framework import serializers

from .product_validation import product_validator, ProductMatch

logger = logging.getLogger(__name__)


class ChemicalEventValidationMixin:
    """
    Mixin for ChemicalEvent serializer to add product validation.
    Provides commercial name validation without breaking existing functionality.
    """
    
    def validate_commercial_name_against_type(self, validated_data: Dict) -> Dict:
        """
        Validate commercial_name against the selected chemical type.
        Adds validation warnings but doesn't block save operation.
        """
        commercial_name = validated_data.get('commercial_name', '')
        chemical_type = validated_data.get('type', '')
        
        if not commercial_name or not chemical_type:
            return validated_data
        
        try:
            # Validate product name
            product_match = product_validator.validate_commercial_name(
                commercial_name=commercial_name,
                user_selected_type=chemical_type,
                confidence_threshold=0.7
            )
            
            # Store validation results in extra_data for frontend display
            extra_data = validated_data.get('extra_data', {}) or {}
            extra_data['product_validation'] = {
                'validated': True,
                'confidence': product_match.confidence,
                'correct_type': product_match.correct_type,
                'warnings': product_match.warnings,
                'npk_ratio': product_match.npk_ratio,
                'manufacturer': product_match.manufacturer,
                'active_ingredient': product_match.active_ingredient,
                'validation_timestamp': self._get_current_timestamp(),
                'validator_version': '1.0.0'
            }
            
            # Auto-fill NPK data for fertilizers if available
            if (product_match.correct_type == 'FE' and 
                product_match.npk_ratio and 
                product_match.confidence > 0.8):
                
                npk_parts = product_match.npk_ratio.split('-')
                if len(npk_parts) == 3:
                    try:
                        # Only auto-fill if user hasn't provided values
                        if not validated_data.get('nitrogen_percentage'):
                            validated_data['nitrogen_percentage'] = float(npk_parts[0])
                        if not validated_data.get('phosphorus_percentage'):
                            validated_data['phosphorus_percentage'] = float(npk_parts[1])
                        if not validated_data.get('potassium_percentage'):
                            validated_data['potassium_percentage'] = float(npk_parts[2])
                        
                        extra_data['product_validation']['auto_filled_npk'] = True
                        
                    except (ValueError, IndexError):
                        logger.warning(f"Could not parse NPK ratio: {product_match.npk_ratio}")
            
            validated_data['extra_data'] = extra_data
            
            # Log validation results for monitoring
            self._log_validation_result(product_match, chemical_type)
            
        except Exception as e:
            logger.error(f"Product validation error: {e}")
            # Don't block save operation on validation errors
            
        return validated_data
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp for validation tracking"""
        from django.utils import timezone
        return timezone.now().isoformat()
    
    def _log_validation_result(self, product_match: ProductMatch, user_type: str):
        """Log validation results for monitoring and improvement"""
        log_data = {
            'commercial_name': product_match.commercial_name,
            'user_type': user_type,
            'correct_type': product_match.correct_type,
            'confidence': product_match.confidence,
            'type_match': user_type == product_match.correct_type,
            'warnings_count': len(product_match.warnings)
        }
        
        if user_type != product_match.correct_type:
            logger.warning(f"Product type mismatch detected: {log_data}")
        else:
            logger.info(f"Product validation successful: {log_data}")


def get_product_suggestions_api(partial_name: str) -> List[Dict]:
    """
    API endpoint function for product autocomplete.
    Can be called from Django views or DRF endpoints.
    """
    if not partial_name or len(partial_name.strip()) < 2:
        return []
    
    try:
        return product_validator.get_product_suggestions(
            partial_name=partial_name.strip(),
            max_suggestions=5
        )
    except Exception as e:
        logger.error(f"Product suggestions API error: {e}")
        return []


def get_validation_stats_api() -> Dict:
    """
    API endpoint function for validation statistics.
    Useful for admin dashboards and monitoring.
    """
    try:
        return product_validator.get_validation_stats()
    except Exception as e:
        logger.error(f"Validation stats API error: {e}")
        return {
            "error": str(e),
            "total_products": 0,
            "status": "error"
        }


class ProductValidatedChemicalEventSerializer(serializers.ModelSerializer):
    """
    Drop-in replacement for ChemicalEvent serializer with product validation.
    Can be used instead of UpdateChemicalEventSerializer for enhanced validation.
    """
    
    # Add read-only fields for validation results
    product_validation = serializers.SerializerMethodField(read_only=True)
    suggested_products = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = None  # Will be set when imported with proper ChemicalEvent model
        fields = "__all__"
    
    def get_product_validation(self, obj) -> Optional[Dict]:
        """Get product validation results from extra_data"""
        if hasattr(obj, 'extra_data') and obj.extra_data:
            return obj.extra_data.get('product_validation')
        return None
    
    def get_suggested_products(self, obj) -> List[Dict]:
        """Get product suggestions based on partial commercial_name"""
        if not hasattr(obj, 'commercial_name') or not obj.commercial_name:
            return []
        
        return get_product_suggestions_api(obj.commercial_name)
    
    def validate(self, data):
        """Enhanced validation with product validation"""
        # First, run any existing validation
        if hasattr(super(), 'validate'):
            data = super().validate(data)
        
        # Apply product validation
        mixin = ChemicalEventValidationMixin()
        data = mixin.validate_commercial_name_against_type(data)
        
        return data


# Integration helpers for existing serializers
def enhance_chemical_event_serializer(serializer_class):
    """
    Decorator to enhance existing ChemicalEvent serializers with product validation.
    Maintains backward compatibility while adding validation features.
    
    Usage:
        @enhance_chemical_event_serializer
        class UpdateChemicalEventSerializer(serializers.ModelSerializer):
            # existing code...
    """
    
    class EnhancedSerializer(serializer_class, ChemicalEventValidationMixin):
        
        def validate(self, data):
            # Run original validation
            if hasattr(super(serializer_class, self), 'validate'):
                data = super().validate(data)
            
            # Add product validation
            data = self.validate_commercial_name_against_type(data)
            
            return data
        
        class Meta(serializer_class.Meta):
            pass
    
    return EnhancedSerializer


# Usage monitoring for optimization
validation_metrics = {
    'total_validations': 0,
    'successful_matches': 0,
    'type_mismatches': 0,
    'unknown_products': 0,
    'auto_filled_npk': 0
}


def track_validation_metric(metric_name: str):
    """Track validation metrics for optimization"""
    global validation_metrics
    validation_metrics[metric_name] = validation_metrics.get(metric_name, 0) + 1
    
    # Log metrics every 100 validations
    if validation_metrics['total_validations'] % 100 == 0:
        logger.info(f"Product validation metrics: {validation_metrics}")