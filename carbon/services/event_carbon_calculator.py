import logging
import time
from typing import Any, Dict, List, Optional

from django.utils import timezone

from ..models import CarbonEntry, CarbonSource, USDACalculationAudit, USDAComplianceRecord
from .emission_factors import emission_factors
from .enhanced_emission_factors import EnhancedEmissionFactors
from .enhanced_usda_factors import EnhancedUSDAFactors

logger = logging.getLogger(__name__)


class EventCarbonCalculator:
    """
    Service for calculating carbon impact from agricultural events.
    Implements USDA emission factors and industry best practices.
    Enhanced with regional USDA factors, real-time API integration, and compliance validation.
    """

    # USDA Emission Factors (kg CO2e per unit) - Now sourced from centralized registry
    @property
    def USDA_FERTILIZER_FACTORS(self):
        """Get USDA fertilizer factors from centralized registry (legacy compatibility)"""
        return {
            "nitrogen": emission_factors.get_fertilizer_factor("nitrogen")["value"],
            "phosphorus": emission_factors.get_fertilizer_factor("phosphorus")["value"],
            "potassium": emission_factors.get_fertilizer_factor("potassium")["value"],
        }

    def _get_climate_aware_fertilizer_factors(self, event, application_method: str = "broadcast") -> Dict[str, float]:
        """
        Get climate-aware fertilizer factors based on farm location and application method.
        Uses the new corrected USDA values with climate and application adjustments.
        """
        try:
            # Get farm location
            latitude, longitude, state = self._get_farm_coordinates(event)

            # Get enhanced factors with climate and application method adjustments
            enhanced_factors = emission_factors.get_enhanced_fertilizer_factors(
                nutrients=["nitrogen", "phosphorus", "potassium"],
                latitude=latitude,
                longitude=longitude,
                state=state,
                application_methods={
                    "nitrogen": application_method,
                    "phosphorus": application_method,
                    "potassium": application_method,
                },
            )

            # Extract values for calculation
            return {
                "nitrogen": enhanced_factors["nitrogen"]["value"],
                "phosphorus": enhanced_factors["phosphorus"]["value"],
                "potassium": enhanced_factors["potassium"]["value"],
                "metadata": {
                    "climate_zone": enhanced_factors["nitrogen"]["climate_zone"],
                    "precipitation": enhanced_factors["nitrogen"]["annual_precipitation"],
                    "application_method": application_method,
                    "adjustments_applied": enhanced_factors["nitrogen"]["adjustments_applied"],
                    "version": enhanced_factors["nitrogen"]["version"],
                },
            }

        except Exception as e:
            logger.error(f"Error getting climate-aware fertilizer factors: {e}")
            # Fallback to base factors
            return {
                "nitrogen": emission_factors.get_fertilizer_factor("nitrogen")["value"],
                "phosphorus": emission_factors.get_fertilizer_factor("phosphorus")["value"],
                "potassium": emission_factors.get_fertilizer_factor("potassium")["value"],
                "metadata": {
                    "climate_zone": "unknown",
                    "application_method": application_method,
                    "fallback_used": True,
                    "error": str(e),
                },
            }

    @property
    def FUEL_EMISSION_FACTORS(self):
        """Get fuel emission factors from centralized registry"""
        return {
            "diesel": emission_factors.get_fuel_factor("diesel")["value"],
            "gasoline": emission_factors.get_fuel_factor("gasoline")["value"],
            "natural_gas": emission_factors.get_fuel_factor("natural_gas")["value"],
        }

    @property
    def APPLICATION_EFFICIENCY(self):
        """Get application efficiency factors from centralized registry (legacy compatibility)"""
        return {method: data["value"] for method, data in emission_factors.APPLICATION_EFFICIENCY_FACTORS.items()}

    @property
    def CROP_SPECIFIC_FACTORS(self):
        """Get crop-specific factors from centralized registry (legacy compatibility)"""
        return {crop: data["value"] for crop, data in emission_factors.CROP_SPECIFIC_FACTORS.items()}

    @property
    def CROP_FERTILIZER_EFFICIENCY(self):
        """Get crop fertilizer efficiency factors from centralized registry (legacy compatibility)"""
        return {category: data["value"] for category, data in emission_factors.CROP_FERTILIZER_EFFICIENCY.items()}

    def __init__(self):
        self.current_year = timezone.now().year
        self.enhanced_usda = EnhancedUSDAFactors()

        # Log initialization with centralized factors
        logger.info(f"EventCarbonCalculator initialized with centralized emission factors v{emission_factors.VERSION}")
        logger.info(f"Nitrogen factor: {self.USDA_FERTILIZER_FACTORS['nitrogen']} kg CO2e per kg N (USDA-verified)")
        logger.info(f"Loaded {len(emission_factors.CROP_SPECIFIC_FACTORS)} centralized crop factors")

    def _get_usda_emission_factors(self) -> Dict[str, float]:
        """Get base USDA emission factors for compatibility"""
        # Use centralized factors to ensure consistency
        factors = emission_factors.get_all_factors_simple()
        return {
            "nitrogen": factors["nitrogen"],
            "phosphorus": factors["phosphorus"],
            "potassium": factors["potassium"],
            "diesel": factors["diesel"],
            "gasoline": factors["gasoline"],
            "natural_gas": factors["natural_gas"],
        }

    def _get_establishment_location(self, event) -> tuple:
        """Extract establishment location from event"""
        try:
            # Correct path: event -> history -> parcel -> establishment
            if (
                hasattr(event, "history")
                and event.history
                and hasattr(event.history, "parcel")
                and event.history.parcel
                and hasattr(event.history.parcel, "establishment")
                and event.history.parcel.establishment
            ):
                establishment = event.history.parcel.establishment
                state = getattr(establishment, "state", "Unknown")
                county = getattr(establishment, "county", None)
                return state, county
        except Exception as e:
            logger.error(f"Error getting establishment location: {e}")
        return "Unknown", None

    def _get_farm_coordinates(self, event) -> tuple:
        """
        Extract farm coordinates and location information from event.
        Returns (latitude, longitude, state)
        """
        try:
            # Try to get coordinates from establishment
            if (
                hasattr(event, "history")
                and event.history
                and hasattr(event.history, "parcel")
                and event.history.parcel
                and hasattr(event.history.parcel, "establishment")
                and event.history.parcel.establishment
            ):
                establishment = event.history.parcel.establishment

                # Get coordinates if available
                latitude = getattr(establishment, "latitude", None)
                longitude = getattr(establishment, "longitude", None)
                state = getattr(establishment, "state", "CA")  # Default to California

                # If coordinates are available, use them
                if latitude is not None and longitude is not None:
                    return float(latitude), float(longitude), state

                # If no coordinates, use state for regional estimates
                return None, None, state

        except Exception as e:
            logger.error(f"Error getting farm coordinates: {e}")

        # Default fallback - assume California for unknown locations
        return None, None, "CA"

    def _get_real_time_usda_factors(self, crop_type: str, state: str) -> Dict[str, float]:
        """NEW METHOD: Get real-time USDA emission factors"""
        try:
            # Try to get real-time factors first
            real_time_factors = self.enhanced_usda.get_real_time_emission_factors(crop_type, state)
            if real_time_factors:
                logger.info(f"Using real-time USDA factors for {crop_type} in {state}")
                return real_time_factors

            # Fallback to regional factors
            return self.enhanced_usda.get_regional_factors(crop_type, state)

        except Exception as e:
            logger.error(f"Error getting real-time USDA factors: {e}")
            return self._get_usda_emission_factors()

    def _calculate_confidence_score(self, event, calculation_data: Dict) -> float:
        """NEW METHOD: Calculate confidence score for carbon calculation"""
        try:
            confidence_factors = []

            # Factor 1: Data completeness (0.0 - 0.3)
            required_fields = ["crop_type", "area", "amount"]
            present_fields = sum(1 for field in required_fields if calculation_data.get(field))
            completeness_score = (present_fields / len(required_fields)) * 0.3
            confidence_factors.append(completeness_score)

            # Factor 2: USDA factor usage (0.0 - 0.4)
            usda_factor_score = 0.4 if calculation_data.get("usda_factors_based", False) else 0.1
            confidence_factors.append(usda_factor_score)

            # Factor 3: Regional specificity (0.0 - 0.2)
            state, county = self._get_establishment_location(event)
            regional_score = 0.2 if state != "Unknown" else 0.0
            if county:
                regional_score += 0.05  # Bonus for county-level data
            confidence_factors.append(min(regional_score, 0.2))

            # Factor 4: Method precision (0.0 - 0.1)
            method_score = 0.1 if calculation_data.get("method") == "detailed" else 0.05
            confidence_factors.append(method_score)

            total_confidence = sum(confidence_factors)
            return min(total_confidence, 1.0)

        except Exception as e:
            logger.error(f"Error calculating confidence score: {e}")
            return 0.5  # Default medium confidence

    def _create_usda_compliance_record(
        self, carbon_entry: CarbonEntry, event, calculation_data: Dict, confidence_score: float
    ) -> None:
        """NEW METHOD: Create USDA compliance record"""
        try:
            state, county = self._get_establishment_location(event)

            # Extract crop type properly from event's history relationship
            crop_type = "unknown"
            if hasattr(event, "history") and event.history:
                if hasattr(event.history, "crop_type") and event.history.crop_type:
                    # First try: get from history.crop_type.name (new model structure)
                    crop_type = event.history.crop_type.name
                elif hasattr(event.history, "product") and event.history.product:
                    # Fallback: get from history.product.name (legacy structure)
                    crop_type = event.history.product.name
                elif "crop_name" in calculation_data:
                    # Fallback: get from calculation_data if available
                    crop_type = calculation_data["crop_name"]

            # Log for debugging
            logger.info(f"🌾 USDA Compliance - Crop type extracted: '{crop_type}' for event {event.id}")

            # Ensure state is a valid string and 2-character code (max_length=2 in model)
            if not state or state == "Unknown" or not isinstance(state, str) or len(state) != 2:
                state = "CA"  # Default to California for unknown states

            # Extract proper area from event
            area_hectares = 1  # Default fallback
            if hasattr(event, "area") and event.area and event.area != "None":
                area_hectares = self._convert_area_to_hectares(event.area, event, crop_type)
            elif (
                hasattr(event, "history")
                and event.history
                and hasattr(event.history, "parcel")
                and event.history.parcel
            ):
                area_hectares = self._convert_area_to_hectares(event.history.parcel.area, event, crop_type)

            # Validate against USDA standards
            validation_result = self.enhanced_usda.validate_against_usda_standards(
                {
                    "crop_type": crop_type,
                    "state": state,
                    "co2e": calculation_data.get("co2e", 0),
                    "area_hectares": area_hectares,
                    "usda_factors_based": calculation_data.get("usda_factors_based", False),
                    "method": calculation_data.get("method", "standard"),
                }
            )

            # Create compliance record
            USDAComplianceRecord.objects.create(
                carbon_entry=carbon_entry,
                establishment=getattr(event, "history", None)
                and getattr(event.history, "parcel", None)
                and getattr(event.history.parcel, "establishment", None),
                production=getattr(event, "history", None),
                compliance_status="compliant" if validation_result.is_compliant else "non_compliant",
                confidence_score=validation_result.confidence_score,
                validation_method="enhanced_api" if self.enhanced_usda.usda_api_client.api_key else "local_validation",
                validation_details=validation_result.validation_details,
                recommendations=validation_result.recommendations,
                usda_api_used=bool(self.enhanced_usda.usda_api_client.api_key),
                crop_type=crop_type,
                state=state,
                regional_factors_used=state in self.enhanced_usda.regional_adjustments,
                validated_by=getattr(event, "created_by", None),
            )

            logger.info(f"Created USDA compliance record for carbon entry {carbon_entry.id}")

        except Exception as e:
            logger.error(f"Error creating USDA compliance record: {e}")

    def _create_calculation_audit(
        self, event, carbon_entry: CarbonEntry, calculation_data: Dict, calculation_time_ms: int
    ) -> None:
        """NEW METHOD: Create calculation audit record"""
        try:
            event_type_mapping = {
                "ChemicalEvent": "chemical_event",
                "ProductionEvent": "production_event",
                "EquipmentEvent": "equipment_event",
                "SoilManagementEvent": "soil_management",
                "WeatherEvent": "weather_event",
                "PestManagementEvent": "pest_management",
                "GeneralEvent": "business_event",
            }

            event_type = event_type_mapping.get(event.__class__.__name__, "business_event")
            state, county = self._get_establishment_location(event)

            USDACalculationAudit.objects.create(
                event_type=event_type,
                event_id=event.id,
                carbon_entry=carbon_entry,
                input_data=calculation_data.get("input_data", {}),
                regional_factors_used=calculation_data.get("regional_factors", {}),
                calculation_method=calculation_data.get("method", "standard"),
                usda_factors_applied=calculation_data.get("usda_factors_based", False),
                regional_adjustments_applied=state in self.enhanced_usda.regional_adjustments,
                api_data_used=bool(self.enhanced_usda.usda_api_client.api_key),
                calculated_co2e=calculation_data.get("co2e", 0),
                confidence_score=calculation_data.get("confidence_score", 0.5),
                benchmark_comparison=calculation_data.get("usda_benchmark", {}),
                calculation_time_ms=calculation_time_ms,
                processor_version="2.0_enhanced",
                calculated_by=getattr(event, "created_by", None),
            )

        except Exception as e:
            logger.error(f"Error creating calculation audit: {e}")

    def _add_enhanced_usda_metadata(self, result: Dict[str, Any], event, crop_name: str = "default") -> Dict[str, Any]:
        """Add enhanced USDA metadata to calculation results"""
        start_time = time.time()

        try:
            state, county = self._get_establishment_location(event)

            # Get enhanced metadata
            metadata = self.enhanced_usda.get_enhanced_calculation_metadata(crop_name, state)

            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(event, result)
            result["confidence_score"] = confidence_score

            # Add to result
            result.update(
                {
                    "usda_factors_based": True,
                    "verification_status": "factors_verified",
                    "data_source": metadata["data_source"],
                    "methodology": metadata["methodology"],
                    "regional_specificity": metadata["regional_specificity"],
                    "confidence_level": metadata["confidence_level"],
                    "usda_compliance": metadata["usda_compliance"],
                    "regional_optimization": metadata.get("regional_optimization", False),
                    "real_time_data": metadata.get("real_time_data", False),
                    "api_integration": metadata.get("api_enabled", False),
                }
            )

            # Add benchmark comparison if possible
            if "co2e" in result and result["co2e"] > 0:
                # Calculate carbon intensity (simplified)
                area_hectares = self._convert_area_to_hectares(getattr(event, "area", "1"))
                if area_hectares > 0:
                    carbon_intensity = result["co2e"] / area_hectares
                    benchmark = self.enhanced_usda.get_usda_benchmark_comparison(carbon_intensity, crop_name, state)
                    result["usda_benchmark"] = benchmark

            # Store calculation metadata for audit
            result["input_data"] = {
                "event_type": event.__class__.__name__,
                "event_id": event.id,
                "crop_type": crop_name,
                "state": state,
                "county": county,
            }

            # Get regional factors used
            regional_factors = self._get_real_time_usda_factors(crop_name, state)
            result["regional_factors"] = regional_factors

            calculation_time = int((time.time() - start_time) * 1000)  # Convert to milliseconds
            result["calculation_time_ms"] = calculation_time

            return result

        except Exception as e:
            logger.error(f"Error adding enhanced USDA metadata: {e}")
            # Fallback to basic metadata
            result.update(
                {
                    "usda_factors_based": True,
                    "verification_status": "factors_verified",
                    "data_source": "USDA Agricultural Research Service",
                    "confidence_level": "medium",
                    "confidence_score": 0.5,
                }
            )
            return result

    def _get_crop_category(self, crop_name: str) -> str:
        """Determine crop category from crop name for efficiency calculations"""
        crop_lower = crop_name.lower()

        fruit_keywords = ["orange", "apple", "grape", "lemon", "lime", "strawberry", "blueberry", "avocado"]
        vegetable_keywords = ["tomato", "lettuce", "carrot", "broccoli", "spinach", "cucumber", "pepper", "onion"]
        grain_keywords = ["corn", "wheat", "rice", "barley", "oats"]
        herb_keywords = ["basil", "oregano", "thyme", "rosemary", "mint"]
        legume_keywords = ["soybean", "bean", "chickpea", "lentil", "pea"]
        nut_keywords = ["almond", "walnut", "pecan", "hazelnut"]

        for keyword in fruit_keywords:
            if keyword in crop_lower:
                return "fruits"
        for keyword in vegetable_keywords:
            if keyword in crop_lower:
                return "vegetables"
        for keyword in grain_keywords:
            if keyword in crop_lower:
                return "grains"
        for keyword in herb_keywords:
            if keyword in crop_lower:
                return "herbs"
        for keyword in legume_keywords:
            if keyword in crop_lower:
                return "legumes"
        for keyword in nut_keywords:
            if keyword in crop_lower:
                return "nuts"

        return "default"

    def _get_crop_specific_factor(self, crop_name: str) -> float:
        """Get crop-specific emission factor"""
        crop_key = crop_name.lower().replace(" ", "_")
        return self.CROP_SPECIFIC_FACTORS.get(crop_key, self.CROP_SPECIFIC_FACTORS["default"])

    def calculate_chemical_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of chemical application events using EPA/USDA verified emission factors.
        ENHANCED: Uses only credible, government-sourced data for transparency.
        Includes both manufacturing and application emissions.
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            # Extract chemical data from event
            chemical_data = self._extract_chemical_event_data(event)

            # Get chemical parameters for EPA calculation
            chemical_type = chemical_data.get("chemical_type", "FE")
            volume_liters = chemical_data.get("volume_liters", 0.0)
            area_hectares = chemical_data.get("area_hectares", 0.0)
            npk_content = chemical_data.get("npk_content", {"N": 0, "P": 0, "K": 0})
            application_method = chemical_data.get("application_method", "broadcast")
            product_name = chemical_data.get("product_name", "")
            chemical_subtype = chemical_data.get("chemical_subtype", "")

            # Use EPA/USDA verified emission factors for chemical calculations
            # ENHANCED 2025-01-21: Pass chemical_subtype for explicit emission factor selection.
            # Takes precedence over keyword detection from product_name.
            # Supports: organic_herbicide, copper_fungicide, sulfur_fungicide, biological_fungicide,
            #           organic_pesticide, biological_pesticide, organic_fertilizer, slow_release_fertilizer
            calculation_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
                chemical_type=chemical_type,
                volume_liters=volume_liters,
                area_hectares=area_hectares,
                npk_content=npk_content,
                application_method=application_method,
                product_name=product_name,
                chemical_subtype=chemical_subtype,
            )

            base_emissions = calculation_result["co2e_kg"]
            breakdown = calculation_result["breakdown"]
            data_sources = calculation_result["data_sources"]
            limitations = calculation_result.get("limitations", "")
            calculation_method = calculation_result["calculation_method"]

            # Calculate efficiency score based on EPA data
            confidence_level = breakdown.get("confidence_level", 0.90)
            efficiency_score = confidence_level * 100  # Convert to percentage

            # Generate EPA-based recommendations
            recommendations = self._generate_epa_chemical_recommendations(event, base_emissions, breakdown)

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": round(efficiency_score, 1),
                "calculation_method": calculation_method,
                "verification_status": "epa_usda_verified",
                "data_sources": data_sources,
                "breakdown": breakdown,
                "limitations": limitations,
                "recommendations": recommendations,
                "confidence_level": confidence_level,
            }

            return self._add_enhanced_usda_metadata(result, event, chemical_data.get("crop_name", "unknown"))

        except Exception as e:
            # Return minimal safe calculation on error
            logger.error(f"Chemical event calculation failed: {e}")
            logger.error(
                f"Event data: type={getattr(event, 'type', 'unknown')}, volume={getattr(event, 'volume', 'unknown')}, area={getattr(event, 'area', 'unknown')}"
            )
            return {
                "co2e": 0.0,
                "efficiency_score": 70.0,
                "verification_status": "calculation_error",
                "error": str(e),
                "calculation_method": "epa_fallback",
            }

    def _extract_chemical_event_data(self, event) -> Dict[str, Any]:
        """Extract chemical event data for EPA/USDA calculations"""
        try:
            # Get crop information
            crop_name = "unknown"
            if hasattr(event, "history") and event.history and hasattr(event.history, "product"):
                crop_name = event.history.product.name

            # Extract chemical type - handle None values properly
            chemical_type = getattr(event, "type", None)
            if chemical_type is None or chemical_type == "":
                chemical_type = "FE"  # Default to fertilizer
            elif chemical_type == "":
                chemical_type = "FE"  # Default to fertilizer for empty strings

            # Extract volume (convert to liters)
            # Handle both old format (volume="3320 Kilograms") and new format (volume_applied="3320", volume_unit="kg")
            volume_str = getattr(event, "volume", None)
            if not volume_str:
                # New frontend format: separate volume_applied and volume_unit fields
                volume_applied = getattr(event, "volume_applied", "50")
                volume_unit = getattr(event, "volume_unit", "L")

                # Map common unit variations
                unit_map = {
                    "kg": "Kilograms",
                    "kilograms": "Kilograms",
                    "l": "Liters",
                    "liters": "Liters",
                    "gal": "Gallons",
                    "gallons": "Gallons",
                }

                normalized_unit = unit_map.get(volume_unit.lower(), volume_unit)
                volume_str = f"{volume_applied} {normalized_unit}"

            volume_liters = self._convert_volume_to_liters(volume_str, event, crop_name)

            # Extract area (convert to hectares)
            # Handle both old format (area="16.2 Hectares") and new format (area_treated="16.2", area_unit="ha")
            area_str = getattr(event, "area", None)
            if not area_str:
                # New frontend format: separate area_treated and area_unit fields
                area_treated = getattr(event, "area_treated", "1.0")
                area_unit = getattr(event, "area_unit", "ha")

                # Map common unit variations
                area_unit_map = {"ha": "Hectares", "hectares": "Hectares", "acres": "Acres", "ac": "Acres"}

                normalized_area_unit = area_unit_map.get(area_unit.lower(), area_unit)
                area_str = f"{area_treated} {normalized_area_unit}"

            area_hectares = self._convert_area_to_hectares(area_str, event, crop_name)

            # Extract NPK content
            npk_content = self._get_structured_npk_content(event, crop_name)

            # Extract application method
            application_method = self._get_structured_application_method(event, crop_name)

            # Extract product/commercial name for specific chemical type detection
            # (e.g., organic herbicides, copper fungicides)
            product_name = getattr(event, "commercial_name", "") or ""

            # Extract explicit chemical_subtype for accurate emission factor selection
            # This takes precedence over keyword detection from product_name
            # Values: organic_herbicide, copper_fungicide, sulfur_fungicide, biological_fungicide,
            #         organic_pesticide, biological_pesticide, organic_fertilizer, slow_release_fertilizer
            chemical_subtype = getattr(event, "chemical_subtype", "") or ""

            return {
                "chemical_type": chemical_type,
                "crop_name": crop_name,
                "volume_liters": volume_liters,
                "area_hectares": area_hectares,
                "npk_content": npk_content,
                "application_method": application_method,
                "product_name": product_name,
                "chemical_subtype": chemical_subtype,
            }

        except Exception as e:
            logger.warning(f"Error extracting chemical data, using defaults: {e}")
            return {
                "chemical_type": "FE",
                "crop_name": "unknown",
                "volume_liters": 50.0,
                "area_hectares": 1.0,
                "npk_content": {"N": 16, "P": 16, "K": 16},  # Default NPK
                "application_method": "broadcast",
                "product_name": "",
                "chemical_subtype": "",
            }

    def _generate_epa_chemical_recommendations(self, event, emissions: float, breakdown: dict) -> list:
        """Generate EPA-based recommendations for chemical events"""
        recommendations = []

        try:
            manufacturing_emissions = breakdown.get("manufacturing_emissions_kg_co2e", 0.0)
            application_emissions = breakdown.get("application_emissions_kg_co2e", 0.0)

            # High manufacturing emissions recommendations
            if manufacturing_emissions > application_emissions * 2:
                recommendations.append(
                    {
                        "type": "input_optimization",
                        "message": "Consider slow-release fertilizers to reduce total application frequency",
                        "impact": "High",
                        "source": "EPA Sustainable Agriculture Guidelines",
                    }
                )

            # High total emissions recommendations
            if emissions > 50:
                recommendations.append(
                    {
                        "type": "precision_agriculture",
                        "message": "Use soil testing to apply only needed nutrients",
                        "impact": "High",
                        "source": "USDA Nutrient Management Guidelines",
                    }
                )

            # Application efficiency recommendations
            if breakdown.get("application_method", "").lower() == "broadcast":
                recommendations.append(
                    {
                        "type": "application_efficiency",
                        "message": "Consider precision injection to reduce fertilizer waste",
                        "impact": "Medium",
                        "source": "EPA Agricultural Best Management Practices",
                    }
                )

            # EPA verification transparency
            recommendations.append(
                {
                    "type": "data_transparency",
                    "message": "Chemical carbon footprint calculated using EPA/USDA verified emission factors",
                    "impact": "Transparency",
                    "source": "EPA Greenhouse Gas Emission Factors Hub",
                }
            )

            return recommendations

        except Exception as e:
            logger.warning(f"Error generating EPA chemical recommendations: {e}")
            return []

    def calculate_production_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate production event impact using EPA/USDA verified emission factors.
        ENHANCED: Uses only credible, government-sourced data for transparency.
        """
        try:
            from .verified_emission_factors import VerifiedEmissionFactors

            # Debug logging
            logger.info(
                f"Production calculation: type={getattr(event, 'type', 'unknown')}, fuel_consumed={getattr(event, 'fuel_consumed', 'unknown')}, area_covered={getattr(event, 'area_covered', 'unknown')}"
            )

            # Extract production data from event
            production_data = self._extract_production_event_data(event)
            logger.info(f"Extracted production data: {production_data}")

            # Determine production type for EPA/USDA calculation
            production_type = production_data.get("production_type", "")
            area_covered = production_data.get("area_covered", 0.0)
            fuel_consumed = production_data.get("fuel_consumed")
            equipment_hours = production_data.get("equipment_hours")

            if event.type == "IR":  # Irrigation
                # Use EPA electricity factors for irrigation pumps
                water_volume_gallons = production_data.get("water_volume_gallons")
                if not water_volume_gallons:
                    # ENHANCED: USDA-sourced irrigation water estimates
                    # USDA NASS 2023: Average 1.5 acre-feet/acre/season = ~489,000 gal/acre/season
                    # Single irrigation event: ~30,000-50,000 gallons/acre typical
                    # Sources: ERS.USDA.gov, NASS Irrigation & Water Management Survey 2023
                    water_volume_gallons = self._estimate_irrigation_water_volume(event, area_covered)

                calculation_result = VerifiedEmissionFactors.calculate_drought_irrigation_emissions(
                    water_volume_gallons=water_volume_gallons
                )

                base_emissions = calculation_result["co2e_kg"]
                data_sources = calculation_result["data_sources"]
                calculation_method = calculation_result["calculation_method"]
                breakdown = calculation_result["breakdown"]
                limitations = calculation_result.get("limitations", "")

            elif event.type in ["HA", "PL", "GE", "PR", "IR"]:  # Harvesting, Planting, General, Pruning, Irrigation
                # Use EPA/USDA production emission factors
                calculation_result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type=production_type,
                    area_covered=area_covered,
                    fuel_consumed=fuel_consumed,
                    equipment_hours=equipment_hours,
                )

                base_emissions = calculation_result["co2e_kg"]
                data_sources = calculation_result["data_sources"]
                calculation_method = calculation_result["calculation_method"]
                breakdown = calculation_result["breakdown"]
                limitations = calculation_result.get("limitations", "")

            else:
                # Fallback for unknown production types
                calculation_result = VerifiedEmissionFactors.calculate_production_event_emissions(
                    production_type="general production",
                    area_covered=area_covered,
                    fuel_consumed=fuel_consumed,
                    equipment_hours=equipment_hours,
                )

                base_emissions = calculation_result["co2e_kg"]
                data_sources = calculation_result["data_sources"]
                calculation_method = calculation_result["calculation_method"]
                breakdown = calculation_result["breakdown"]
                limitations = calculation_result.get("limitations", "")

            # Apply crop-specific area if available
            area_modifier = self._get_crop_area_modifier(event)
            if area_modifier != 1.0:
                base_emissions *= area_modifier
                breakdown["crop_area_modifier"] = area_modifier

            # Generate EPA-based recommendations
            recommendations = self._generate_epa_production_recommendations(event, base_emissions, calculation_method)

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": self._calculate_production_efficiency_score(breakdown, calculation_method),
                "calculation_method": calculation_method,
                "verification_status": "usda_verified" if calculation_method == "verified_usda_factors" else "standard",
                "data_sources": data_sources,
                "breakdown": breakdown,
                "limitations": limitations,
                "recommendations": recommendations,
                "confidence_level": breakdown.get("confidence_level", 0.80),
            }

            return self._add_enhanced_usda_metadata(result, event, production_data.get("crop_name", "unknown"))

        except Exception as e:
            logger.error(f"Production event calculation error: {e}")
            return {
                "co2e": 0.0,
                "efficiency_score": 75.0,
                "calculation_method": "calculation_error",
                "verification_status": "error",
                "error": str(e),
                "data_sources": [],
                "breakdown": {},
                "limitations": "Calculation failed, using fallback values",
                "recommendations": [],
            }

    def calculate_weather_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of weather events using VERIFIED EPA and USDA emission factors.

        TRANSPARENCY: Uses only official government emission factors with clear documentation
        of data sources and limitations. No unverified estimates.
        """
        try:
            # Import verified emission factors
            from .verified_emission_factors import VerifiedEmissionFactors

            base_emissions = 0.0
            calculation_result = None
            data_sources = []
            limitations = []

            if event.type == "FR":  # Frost protection
                # Get temperature from direct attribute or extra_data
                lower_temp_value = None
                if hasattr(event, "lower_temperature") and event.lower_temperature:
                    lower_temp_value = event.lower_temperature
                elif event.extra_data and "lower_temperature" in event.extra_data:
                    lower_temp_value = event.extra_data["lower_temperature"]

                if lower_temp_value:
                    temp = self._extract_numeric_value(lower_temp_value, default=32)

                    # Determine protection method from direct attribute or extra_data
                    protection_method = "heaters"  # Default
                    way_of_protection = None
                    if hasattr(event, "way_of_protection") and event.way_of_protection:
                        way_of_protection = event.way_of_protection
                    elif event.extra_data and "way_of_protection" in event.extra_data:
                        way_of_protection = event.extra_data["way_of_protection"]

                    if way_of_protection:
                        way = way_of_protection.lower()
                        if "wind" in way or "fan" in way:
                            protection_method = "wind_machines"
                        elif "heater" in way or "smudge" in way:
                            protection_method = "heaters"

                    # Use verified EPA emission factors for frost protection - handles all edge cases
                    calculation_result = VerifiedEmissionFactors.calculate_frost_protection_emissions(
                        temperature_f=temp,
                        protection_method=protection_method,
                        area_acres=1.0,  # Default to 1 acre, could be enhanced with parcel data
                    )

                    base_emissions = calculation_result["co2e_kg"]
                    breakdown = calculation_result["breakdown"]
                    breakdown["weather_type"] = "FR"
                    data_sources = calculation_result.get("data_sources", [])
                    limitations = [calculation_result.get("limitations", "")]

                else:
                    # No temperature provided - still return standard data sources for transparency
                    base_emissions = 0.0
                    breakdown = {
                        "weather_type": "FR",
                        "error": "Temperature required for verified calculation",
                        "note": "Frost protection emissions depend on temperature - please provide lower_temperature field",
                    }
                    # Add data sources even when no calculation is possible
                    data_sources = [
                        "EPA Greenhouse Gas Emission Factors Hub (40 CFR Part 98)",
                        "Equipment manufacturer specifications (Smudge Pot/Orchard Heater)",
                    ]
                    limitations = ["Temperature data required for accurate calculation"]

            elif event.type == "DR":  # Drought - additional irrigation
                # Get water deficit from direct attribute or extra_data
                water_deficit_value = None
                if hasattr(event, "water_deficit") and event.water_deficit:
                    water_deficit_value = event.water_deficit
                elif event.extra_data and "water_deficit" in event.extra_data:
                    water_deficit_value = event.extra_data["water_deficit"]

                if water_deficit_value:
                    extra_water_m3 = self._extract_numeric_value(water_deficit_value, default=50)
                    # Convert m3 to gallons for EPA calculation (1 m3 = 264.172 gallons)
                    extra_water_gallons = extra_water_m3 * 264.172

                    # Use verified EPA/USDA factors for irrigation pumping
                    calculation_result = VerifiedEmissionFactors.calculate_drought_irrigation_emissions(
                        water_volume_gallons=extra_water_gallons
                    )

                    base_emissions = calculation_result["co2e_kg"]
                    breakdown = calculation_result["breakdown"]
                    breakdown["extra_water_m3"] = extra_water_m3
                    breakdown["weather_type"] = "DR"
                    data_sources = calculation_result["data_sources"]
                    limitations = [calculation_result.get("limitations", "")]

                else:
                    # No water deficit provided - still return standard data sources for transparency
                    base_emissions = 0.0
                    breakdown = {
                        "weather_type": "DR",
                        "error": "Water deficit required for verified calculation",
                        "note": "Drought irrigation emissions depend on water volume - please provide water_deficit field",
                    }
                    # Add data sources even when no calculation is possible
                    data_sources = ["EPA eGRID2022 Summary Tables", "USDA NRCS Irrigation Energy Guidelines"]
                    limitations = ["Water deficit data required for accurate calculation"]

            elif event.type == "HL":  # Hailstorm - Using verified USDA diesel factors
                # Extract hailstorm-specific fields
                weight = self._extract_numeric_value(getattr(event, "weight", "1"), default=1.0)
                diameter = self._extract_numeric_value(getattr(event, "diameter", "1"), default=1.0)
                duration = self._extract_numeric_value(getattr(event, "duration", "1"), default=1.0)

                # Calculate damage severity index (0-10 scale)
                severity = min((weight * diameter) / 10, 10.0)

                # Use USDA verified diesel emission factor for cleanup equipment
                diesel_factor = VerifiedEmissionFactors.get_emission_factor("diesel", "diesel_fuel_mobile")
                equipment_factor = VerifiedEmissionFactors.get_emission_factor("damage", "debris_cleanup")

                if diesel_factor and equipment_factor:
                    # Calculate cleanup emissions using verified factors
                    equipment_hours = severity * duration * 0.5  # Hours of equipment operation
                    fuel_gallons = equipment_hours * equipment_factor.value
                    cleanup_emissions = fuel_gallons * diesel_factor.value

                    # Protection measures (infrastructure/netting damage)
                    protection_emissions = 0.0
                    if hasattr(event, "way_of_protection") and event.way_of_protection:
                        protection_emissions = 2.0 * diesel_factor.value  # 2 gallons for protection setup/repair

                    base_emissions = cleanup_emissions + protection_emissions

                    breakdown = {
                        "weather_type": "HL",
                        "hail_weight_g": weight,
                        "hail_diameter_mm": diameter,
                        "duration_hours": duration,
                        "severity_index": severity,
                        "equipment_hours": equipment_hours,
                        "fuel_gallons": fuel_gallons,
                        "cleanup_emissions_kg": cleanup_emissions,
                        "protection_emissions_kg": protection_emissions,
                        "diesel_emission_factor": diesel_factor.value,
                        "confidence_level": min(diesel_factor.confidence_level, equipment_factor.confidence_level),
                    }

                    data_sources = [diesel_factor.source, equipment_factor.source]
                    limitations = [equipment_factor.notes]

                else:
                    # Fallback if emission factors not available
                    base_emissions = 0.0
                    breakdown = {
                        "weather_type": "HL",
                        "error": "Verified emission factors not available",
                        "note": "Hailstorm cleanup emissions require equipment fuel consumption data",
                    }

            elif event.type == "HT":  # High temperatures - Using verified USDA electricity factors
                # Extract temperature and duration
                if hasattr(event, "highest_temperature") and event.highest_temperature:
                    highest_temp = self._extract_numeric_value(event.highest_temperature, default=90)

                    # Use USDA verified electricity emission factor for cooling systems
                    electricity_factor = VerifiedEmissionFactors.get_emission_factor(
                        "electricity", "electricity_us_avg"
                    )
                    misting_factor = VerifiedEmissionFactors.get_emission_factor("equipment", "misting_system")

                    if electricity_factor and misting_factor and highest_temp > 95:
                        # Extreme heat requiring intervention
                        cooling_hours = 8  # 8 hours of cooling/misting
                        area_acres = 1.0  # Default to 1 acre
                        kwh_consumed = misting_factor.value * cooling_hours * area_acres
                        base_emissions = kwh_consumed * electricity_factor.value

                        breakdown = {
                            "weather_type": "HT",
                            "highest_temperature_f": highest_temp,
                            "cooling_hours": cooling_hours,
                            "cooling_required": True,
                            "area_acres": area_acres,
                            "kwh_consumed": kwh_consumed,
                            "electricity_emission_factor": electricity_factor.value,
                            "misting_consumption_kwh_per_hour_per_acre": misting_factor.value,
                            "confidence_level": min(
                                electricity_factor.confidence_level, misting_factor.confidence_level
                            ),
                        }

                        data_sources = [electricity_factor.source, misting_factor.source]
                        limitations = [misting_factor.notes]

                    else:
                        # No cooling required or factors not available
                        base_emissions = 0.0
                        breakdown = {
                            "weather_type": "HT",
                            "highest_temperature_f": highest_temp,
                            "cooling_required": False,
                            "note": (
                                "No cooling intervention needed below 95°F"
                                if highest_temp <= 95
                                else "Verified emission factors required"
                            ),
                        }
                else:
                    # No temperature provided
                    base_emissions = 0.0
                    breakdown = {
                        "weather_type": "HT",
                        "error": "Temperature required for verified calculation",
                        "note": "High temperature emissions depend on temperature - please provide highest_temperature field",
                    }

            elif event.type in ["TS", "HW", "HH", "LH"]:  # Other weather events - Conservative approach
                # These weather types require specific field data for accurate calculations
                # Using conservative approach with transparent limitations
                base_emissions = 0.0  # No emissions assumed without specific data

                weather_type_names = {
                    "TS": "Tropical Storm",
                    "HW": "High Winds",
                    "HH": "High Humidity",
                    "LH": "Low Humidity",
                }

                breakdown = {
                    "weather_type": event.type,
                    "weather_name": weather_type_names.get(event.type, "Unknown"),
                    "calculation_status": "requires_specific_data",
                    "note": "Emissions calculation requires specific meteorological data and response actions",
                }

                data_sources = ["USDA Agricultural Weather Guidelines"]
                limitations = [
                    "Specific emission calculation requires wind speed, duration, damage assessment, or humidity levels"
                ]

            # Calculate efficiency score based on emissions and method reliability
            if (
                calculation_result
                and "breakdown" in calculation_result
                and "confidence_level" in calculation_result["breakdown"]
            ):
                confidence = calculation_result["breakdown"]["confidence_level"]
                efficiency_score = max(20, min(90, 80 - (base_emissions * 1.5)))
            else:
                confidence = 0.5  # Lower confidence for non-verified calculations
                efficiency_score = max(20, min(70, 60 - (base_emissions * 2)))

            # Get transparency metadata
            metadata = VerifiedEmissionFactors.get_weather_calculation_metadata()

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": round(efficiency_score, 1),
                "calculation_method": metadata["calculation_method"],
                "data_source": "EPA & USDA Verified Emission Factors",
                "verification_status": metadata["verification_status"],
                "breakdown": breakdown,
                "recommendations": self._generate_weather_recommendations(event),
                # TRANSPARENCY FIELDS
                "data_sources": data_sources if data_sources else metadata["data_sources"],
                "limitations": limitations if limitations else metadata["limitations"],
                "confidence_score": confidence,
                "transparency_note": metadata["transparency_note"],
                "last_updated": metadata["last_updated"],
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            return {
                "co2e": 0.0,
                "efficiency_score": 50.0,
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "error": str(e),
            }

    def calculate_equipment_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of equipment events (maintenance, fuel consumption, etc.)
        Enhanced with structured fields for better accuracy.
        """
        try:
            # Get crop information from the production
            crop_name = "default"
            if hasattr(event, "history") and event.history and hasattr(event.history, "product"):
                crop_name = event.history.product.name

            # ENHANCED: Use structured equipment data
            equipment_data = self._get_structured_equipment_data(event, crop_name)

            base_emissions = 0.0
            cost_estimate = 0.0
            efficiency_score = 60.0

            if event.type == "FC":  # Fuel Consumption
                fuel_amount = equipment_data["fuel_amount"]
                fuel_type = equipment_data["fuel_type"].lower()

                emission_factor = self.FUEL_EMISSION_FACTORS.get(fuel_type, self.FUEL_EMISSION_FACTORS["diesel"])
                base_emissions = fuel_amount * emission_factor

                # Apply efficiency modifier based on structured efficiency rating
                efficiency_modifier = {
                    "high": 0.85,  # 15% better efficiency
                    "normal": 1.0,  # Standard emissions
                    "low": 1.25,  # 25% higher emissions
                }.get(equipment_data["efficiency"], 1.0)

                base_emissions *= efficiency_modifier
                cost_estimate = fuel_amount * 1.2  # Approximate fuel cost per liter
                efficiency_score = 90.0 if equipment_data["efficiency"] == "high" else 70.0

                # Equipment type specific adjustments
                equipment_type = equipment_data["equipment_type"]
                if "large" in str(equipment_type).lower():
                    base_emissions *= 1.3  # Large equipment uses more fuel
                elif "small" in str(equipment_type).lower():
                    base_emissions *= 0.8  # Small equipment is more efficient

            elif event.type in ["MN", "RE"]:  # Maintenance, Repair
                # Use equipment type and hours for better estimation
                hours = equipment_data["hours_operated"]
                equipment_type = equipment_data["equipment_type"]

                # Base emissions per hour by equipment type
                base_rate = 2.0  # Default kg CO2e per hour
                if "tractor" in str(equipment_type).lower():
                    if "large" in str(equipment_type).lower():
                        base_rate = 5.0
                    elif "medium" in str(equipment_type).lower():
                        base_rate = 3.5
                    else:
                        base_rate = 2.5
                elif "pump" in str(equipment_type).lower():
                    base_rate = 1.5
                elif "harvester" in str(equipment_type).lower():
                    base_rate = 8.0

                base_emissions = hours * base_rate if hours > 0 else base_rate
                cost_estimate = float(event.maintenance_cost or (hours * 50 if hours > 0 else 100))

            elif event.type == "CA":  # Calibration
                base_emissions = 0.5  # Minimal impact
                cost_estimate = 50.0
                efficiency_score = 95.0  # Well-calibrated equipment is efficient

            elif event.type == "BD":  # Breakdown
                # Higher impact due to inefficiency and potential emergency repairs
                base_emissions = 15.0
                cost_estimate = float(event.maintenance_cost or 500)
                efficiency_score = 30.0  # Broken equipment is very inefficient

            elif event.type == "EI":  # Inspection
                base_emissions = 0.2  # Very minimal impact
                cost_estimate = 25.0
                efficiency_score = 85.0

            recommendations = self._generate_equipment_recommendations(
                event, base_emissions, cost_estimate, equipment_data
            )

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": efficiency_score,
                "calculation_method": (
                    "usda_fuel_factors_enhanced" if event.type == "FC" else "equipment_estimation_enhanced"
                ),
                "data_source": "USDA Agricultural Research Service" if event.type == "FC" else "Industry Standards",
                "verification_status": "factors_verified" if event.type == "FC" else "estimated",
                "breakdown": {
                    "fuel_amount": equipment_data["fuel_amount"],
                    "fuel_type": equipment_data["fuel_type"],
                    "equipment_type": equipment_data["equipment_type"],
                    "area_worked": equipment_data["area_worked"],
                    "hours_operated": equipment_data["hours_operated"],
                    "operation_efficiency": equipment_data["efficiency"],
                    "data_source": equipment_data["data_source"],
                },
                "cost_analysis": {
                    "estimated_cost": cost_estimate,
                    "cost_per_co2e": cost_estimate / max(base_emissions, 0.1),
                    "cost_per_hectare": (
                        cost_estimate / max(equipment_data["area_worked"], 0.1)
                        if equipment_data["area_worked"] > 0
                        else 0
                    ),
                },
                "recommendations": recommendations,
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            return {"co2e": 5.0, "efficiency_score": 60.0, "usda_factors_based": False, "error": str(e)}

    def calculate_soil_management_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of soil management events using USDA area-scaled emission factors
        Enhanced with standardized fuel consumption data for 90% accuracy
        """
        try:
            from .emission_factors import EmissionFactorsRegistry
            from .verified_emission_factors import VerifiedEmissionFactors

            base_emissions = 0.0
            fuel_emissions = 0.0
            area_hectares = 0.0
            confidence_score = 65.0
            data_completeness_factors = []

            # Get area managed - critical for proper scaling
            area_hectares = self._convert_area_to_hectares(
                getattr(event, "area_covered", None) or getattr(event, "area", "1")
            )

            # ENHANCED: Calculate fuel consumption emissions (standardized across event types)
            fuel_consumed_raw = getattr(event, "fuel_consumed", None)
            equipment_hours_raw = getattr(event, "equipment_hours", None)

            # Convert string values to float for calculations
            fuel_consumed = None
            if fuel_consumed_raw:
                try:
                    fuel_consumed = float(fuel_consumed_raw)
                except (ValueError, TypeError):
                    fuel_consumed = None

            equipment_hours = None
            if equipment_hours_raw:
                try:
                    equipment_hours = float(equipment_hours_raw)
                except (ValueError, TypeError):
                    equipment_hours = None

            if fuel_consumed and fuel_consumed > 0:
                # Use verified EPA emission factors for direct fuel combustion
                fuel_unit = getattr(event, "fuel_unit", "L")

                # Convert to gallons for EPA calculation
                if fuel_unit == "L":
                    fuel_gallons = float(fuel_consumed) / 3.78541
                else:  # already in gallons
                    fuel_gallons = float(fuel_consumed)

                # EPA diesel factor: 10.21 kg CO2e per gallon
                fuel_emissions = fuel_gallons * 10.21
                confidence_score = 90.0  # High confidence with fuel data
                data_completeness_factors.extend(["fuel_consumption_documented", "epa_factors_applied"])

                # Log fuel calculation details
                logger.info(
                    f"Soil Management fuel calculation: {fuel_consumed} {fuel_unit} = {fuel_gallons:.2f} gal = {fuel_emissions:.2f} kg CO2e"
                )

            # Map event types to emission factor keys
            event_type_mapping = {
                "OM": "organic_matter",  # Organic Matter Addition
                "CC": "cover_crops",  # Cover Crop
                "CO": "composting",  # Composting
                "TI": "tillage",  # Tillage
                "ST": "soil_test",  # Soil Test
                "PA": "ph_adjustment",  # pH Adjustment
            }

            # Get the appropriate emission factor for area-based calculation
            factor_key = event_type_mapping.get(event.type, "general")
            factor_data = EmissionFactorsRegistry.get_soil_management_factor(factor_key)
            emission_factor = factor_data["value"]  # kg CO2e per hectare

            # Area-based emissions calculation
            area_emissions = 0.0
            if area_hectares > 0:
                area_emissions = area_hectares * emission_factor
                data_completeness_factors.append("area_documented")
            else:
                # Default to 1 hectare if no area specified
                area_hectares = 1.0
                area_emissions = emission_factor
                data_completeness_factors.append("area_assumed")

            # ============================================================================
            # ENHANCED: IPCC 2006 Lime Dissolution CO₂ Emissions (PA events)
            # Agricultural lime releases CO₂ as carbonates dissolve in acidic soil
            # IPCC 2006 Vol 4, Ch 11, Sec 11.3.1: Limestone = 0.44 kg CO₂/kg
            # ============================================================================
            lime_dissolution_emissions = 0.0
            lime_kg_applied = 0.0
            lime_type_used = "limestone"
            lime_factor_data = None

            if event.type == "PA" and hasattr(event, "amendment_amount") and event.amendment_amount:
                # Parse amendment_amount to extract lime quantity
                lime_kg_applied = self._parse_lime_amount(event.amendment_amount)

                if lime_kg_applied > 0:
                    # Detect lime type from amendment_type or description
                    lime_type_used = self._detect_lime_type(event)

                    # Get IPCC-verified lime dissolution factor
                    lime_factor_data = EmissionFactorsRegistry.get_lime_dissolution_factor(lime_type_used)
                    lime_emission_factor = lime_factor_data["value"]  # kg CO₂ per kg lime

                    # Calculate lime dissolution emissions
                    lime_dissolution_emissions = lime_kg_applied * lime_emission_factor
                    data_completeness_factors.append("ipcc_lime_dissolution_calculated")
                    data_completeness_factors.append(f"lime_type_{lime_type_used}")

                    logger.info(
                        f"IPCC Lime Dissolution: {lime_kg_applied:.1f} kg {lime_type_used} × "
                        f"{lime_emission_factor} kg CO₂/kg = {lime_dissolution_emissions:.2f} kg CO₂"
                    )

            # ============================================================================
            # ENHANCED: Tillage Soil CO₂ Flux (TI events)
            # Tillage disturbs soil → increased aeration → accelerated decomposition of SOM
            # Based on Reicosky 1997, West & Post 2002, IPCC 2019 Guidelines
            # ============================================================================
            soil_flux_emissions = 0.0
            tillage_depth_category = "medium"
            soil_flux_factor_data = None

            if event.type == "TI" and area_hectares > 0:
                # Detect tillage depth from event data
                tillage_depth_category = self._detect_tillage_depth(event)

                # Get research-based soil CO₂ flux factor
                soil_flux_factor_data = EmissionFactorsRegistry.get_tillage_soil_flux_factor(
                    tillage_depth_category
                )
                soil_flux_factor = soil_flux_factor_data["value"]  # kg CO₂e per hectare

                # Calculate soil CO₂ flux emissions
                soil_flux_emissions = area_hectares * soil_flux_factor
                data_completeness_factors.append("soil_co2_flux_calculated")
                data_completeness_factors.append(f"tillage_depth_{tillage_depth_category}")

                logger.info(
                    f"Tillage Soil Flux: {area_hectares:.2f} ha × {soil_flux_factor} kg CO₂e/ha "
                    f"({tillage_depth_category} depth) = {soil_flux_emissions:.2f} kg CO₂e"
                )

            # ============================================================================
            # Combine all emission components
            # ============================================================================
            base_emissions = fuel_emissions + area_emissions + lime_dissolution_emissions + soil_flux_emissions

            # Adjust confidence score based on data availability
            if fuel_consumed and fuel_consumed > 0:
                confidence_score = 90.0  # High confidence with fuel data
            elif area_hectares > 0:
                confidence_score = 75.0  # Good confidence with area data only
            else:
                confidence_score = 60.0  # Lower confidence with minimal data

            # Additional confidence factors based on available data
            if hasattr(event, "soil_ph") and event.soil_ph:
                confidence_score += 5.0
                data_completeness_factors.append("soil_ph_available")

            if hasattr(event, "organic_matter_percentage") and event.organic_matter_percentage:
                confidence_score += 5.0
                data_completeness_factors.append("organic_matter_data")

            if hasattr(event, "amendment_amount") and event.amendment_amount:
                if lime_kg_applied > 0:
                    confidence_score += 15.0  # Higher confidence with lime quantity used
                else:
                    confidence_score += 10.0
                data_completeness_factors.append("amendment_quantity")

            if hasattr(event, "test_results") and event.test_results:
                confidence_score += 10.0
                data_completeness_factors.append("detailed_test_results")

            # Boost confidence if IPCC/research factors were applied
            if lime_dissolution_emissions > 0 or soil_flux_emissions > 0:
                confidence_score += 5.0
                data_completeness_factors.append("enhanced_scientific_factors_applied")

            # Cap confidence at 95%
            confidence_score = min(confidence_score, 95.0)

            recommendations = self._generate_soil_recommendations(event, base_emissions)

            # Determine calculation method based on data availability
            calculation_method = "usda_area_scaled_soil_factors"
            if fuel_consumed and fuel_consumed > 0:
                calculation_method = "enhanced_fuel_plus_area_factors"
            if lime_dissolution_emissions > 0:
                calculation_method = "ipcc_lime_dissolution_enhanced"
            if soil_flux_emissions > 0:
                calculation_method = "research_based_tillage_flux_enhanced"
            if lime_dissolution_emissions > 0 and fuel_consumed and fuel_consumed > 0:
                calculation_method = "comprehensive_lime_fuel_enhanced"
            if soil_flux_emissions > 0 and fuel_consumed and fuel_consumed > 0:
                calculation_method = "comprehensive_tillage_fuel_enhanced"

            # Build enhanced calculation string
            calc_parts = []
            if fuel_emissions > 0:
                calc_parts.append(f"Fuel: {round(fuel_emissions, 3)} kg CO₂e")
            if area_emissions > 0:
                calc_parts.append(f"Area: {area_hectares} ha × {emission_factor} = {round(area_emissions, 3)} kg CO₂e")
            if lime_dissolution_emissions > 0:
                calc_parts.append(
                    f"Lime Dissolution (IPCC): {lime_kg_applied:.1f} kg × "
                    f"{lime_factor_data['value']} = {round(lime_dissolution_emissions, 3)} kg CO₂"
                )
            if soil_flux_emissions > 0:
                calc_parts.append(
                    f"Soil Flux ({tillage_depth_category}): {area_hectares} ha × "
                    f"{soil_flux_factor_data['value']} = {round(soil_flux_emissions, 3)} kg CO₂e"
                )
            calculation_string = " + ".join(calc_parts) + f" = {round(base_emissions, 3)} kg CO₂e"

            # Build data sources list
            data_sources = [factor_data["source"]]
            if lime_factor_data:
                data_sources.append(lime_factor_data["source"])
            if soil_flux_factor_data:
                data_sources.append(soil_flux_factor_data["source"])

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": confidence_score,
                "calculation_method": calculation_method,
                "data_source": " | ".join(data_sources),
                "verification_status": "usda_ipcc_factors_verified",
                "emission_factor_used": {
                    "factor_type": factor_key,
                    "factor_value": emission_factor,
                    "unit": factor_data["unit"],
                    "impact_type": factor_data.get("impact_type", "unknown"),
                    "reference": factor_data["reference"],
                },
                "calculation_details": {
                    "area_hectares": area_hectares,
                    "area_emissions": round(area_emissions, 3),
                    "fuel_emissions": round(fuel_emissions, 3),
                    "lime_dissolution_emissions": round(lime_dissolution_emissions, 3),
                    "soil_flux_emissions": round(soil_flux_emissions, 3),
                    "total_emissions": round(base_emissions, 3),
                    "emission_factor": emission_factor,
                    "calculation": calculation_string,
                    "confidence_score": confidence_score,
                    "data_completeness": data_completeness_factors,
                },
                "breakdown": {
                    "soil_activity": event.type,
                    "area_managed": area_hectares,
                    "fuel_consumed": fuel_consumed or 0,
                    "fuel_unit": getattr(event, "fuel_unit", "L"),
                    "equipment_hours": equipment_hours or 0,
                    "area_emissions": round(area_emissions, 3),
                    "fuel_emissions": round(fuel_emissions, 3),
                    "lime_dissolution_emissions": round(lime_dissolution_emissions, 3),
                    "soil_flux_emissions": round(soil_flux_emissions, 3),
                    "emission_factor": emission_factor,
                    "total_impact": base_emissions,
                },
                "recommendations": recommendations,
            }

            # Add lime-specific data if applicable
            if lime_dissolution_emissions > 0 and lime_factor_data:
                result["lime_dissolution_details"] = {
                    "lime_amount_kg": round(lime_kg_applied, 2),
                    "lime_type": lime_type_used,
                    "emission_factor": lime_factor_data["value"],
                    "emission_factor_unit": lime_factor_data["unit"],
                    "emissions_kg_co2": round(lime_dissolution_emissions, 3),
                    "source": lime_factor_data["source"],
                    "reference": lime_factor_data["reference"],
                    "methodology": "IPCC 2006 Tier 1",
                }

            # Add tillage flux-specific data if applicable
            if soil_flux_emissions > 0 and soil_flux_factor_data:
                result["tillage_soil_flux_details"] = {
                    "tillage_depth": tillage_depth_category,
                    "area_hectares": round(area_hectares, 2),
                    "emission_factor": soil_flux_factor_data["value"],
                    "emission_factor_unit": soil_flux_factor_data["unit"],
                    "emissions_kg_co2e": round(soil_flux_emissions, 3),
                    "source": soil_flux_factor_data["source"],
                    "reference": soil_flux_factor_data["reference"],
                    "mechanism": "Soil organic matter decomposition from tillage disturbance",
                }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            return {
                "co2e": 1.0,  # Default to 1.0 kg CO2e for general soil management
                "efficiency_score": 45.0,
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "error": str(e),
                "fallback_used": "general_soil_management_estimate",
            }

    def calculate_business_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of business events (often indirect)
        Enhanced with structured carbon-focused fields.
        """
        try:
            # Get crop information from the production
            crop_name = "default"
            if hasattr(event, "history") and event.history and hasattr(event.history, "product"):
                crop_name = event.history.product.name

            # ENHANCED: Use structured business data
            business_data = self._get_structured_business_data(event, crop_name)

            base_emissions = 0.0
            carbon_credits = business_data["carbon_credits_earned"]
            efficiency_score = 70.0

            # Calculate based on business activity type
            business_type = business_data["business_type"]

            if business_type == "carbon_credits":
                # Carbon credits offset emissions
                if business_data["carbon_credits_unit"] == "kgCO2e":
                    base_emissions = -carbon_credits  # Direct offset in kg
                elif business_data["carbon_credits_unit"] == "tCO2e":
                    base_emissions = -carbon_credits * 1000  # Convert tonnes to kg
                else:  # credits
                    base_emissions = -carbon_credits * 10  # Assume 10 kg per credit unit
                efficiency_score = 95.0  # Very efficient for carbon goals

            elif business_type == "certification":
                # Certification events have minimal direct emissions but positive impact
                cert_type = business_data["certification_type"]
                if cert_type == "carbon_neutral":
                    base_emissions = -50.0  # Significant carbon benefit
                    efficiency_score = 90.0
                elif cert_type == "organic_usda":
                    base_emissions = -20.0  # Moderate carbon benefit
                    efficiency_score = 80.0
                elif cert_type in ["regenerative", "sustainable_agriculture"]:
                    base_emissions = -30.0  # Good carbon benefit
                    efficiency_score = 85.0
                else:
                    base_emissions = -10.0  # Basic certification benefit
                    efficiency_score = 75.0

            elif business_type == "sustainability_audit":
                # Audits improve practices leading to long-term reductions
                base_emissions = 0.5  # Small travel/documentation impact
                efficiency_score = 85.0  # Good for identifying improvements

            elif business_type == "verification":
                # Verification builds consumer trust but has minimal impact
                base_emissions = 1.0  # Small verification process impact
                efficiency_score = 80.0

            elif business_type == "compliance":
                base_emissions = 0.5  # Minimal impact from documentation
                efficiency_score = 70.0

            elif business_type == "transparency":
                # Transparency initiatives have very positive consumer impact
                base_emissions = -5.0  # Small benefit from consumer awareness
                efficiency_score = 88.0

            # Legacy event type handling for backward compatibility
            elif event.type == "CE":  # Certification
                if carbon_credits > 0:
                    base_emissions = -carbon_credits
                    efficiency_score = 90.0
                else:
                    base_emissions = -10.0  # Default certification benefit
                    efficiency_score = 80.0

            elif event.type in ["IN", "CM"]:  # Inspection, Compliance
                base_emissions = 0.5
                efficiency_score = 70.0

            # Apply sustainability practice bonus if applicable
            practice = business_data["sustainability_practice"]
            if practice:
                practice_benefits = {
                    "cover_cropping": -15.0,
                    "no_till": -25.0,
                    "integrated_pest": -10.0,
                    "water_conservation": -8.0,
                    "renewable_energy": -50.0,
                    "composting": -20.0,
                    "biodiversity": -12.0,
                    "soil_health": -18.0,
                }
                practice_benefit = practice_benefits.get(practice, -5.0)
                base_emissions += practice_benefit
                efficiency_score = min(efficiency_score + 10, 100.0)

            recommendations = self._generate_business_recommendations(event, base_emissions, business_data)

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": round(efficiency_score, 1),
                "calculation_method": "carbon_focused_business_analysis",
                "data_source": "Carbon Transparency Standards",
                "verification_status": business_data["verification_status"],
                "breakdown": {
                    "business_type": business_data["business_type"],
                    "certification_type": business_data["certification_type"],
                    "carbon_credits_earned": business_data["carbon_credits_earned"],
                    "carbon_credits_unit": business_data["carbon_credits_unit"],
                    "sustainability_practice": business_data["sustainability_practice"],
                    "verification_status": business_data["verification_status"],
                    "data_source": business_data["data_source"],
                },
                "transparency_metrics": {
                    "consumer_value": "high" if base_emissions < -20 else "medium" if base_emissions < 0 else "low",
                    "verification_level": business_data["verification_status"],
                    "carbon_impact": (
                        "positive" if base_emissions < 0 else "neutral" if base_emissions == 0 else "minimal"
                    ),
                },
                "recommendations": recommendations,
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            return {
                "co2e": 0.0,
                "efficiency_score": 70.0,
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "error": str(e),
            }

    def calculate_pest_management_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of pest management events (IPM practices)
        """
        try:
            base_emissions = 0.0

            if event.type == "BR":  # Beneficial Release
                # Beneficial insect releases reduce need for chemical pesticides
                base_emissions = -0.5  # Small negative impact (avoided chemicals)

            elif event.type == "SC":  # Scouting
                # Travel emissions for scouting
                base_emissions = 0.2  # Minimal transport impact

            elif event.type == "TM":  # Trap Monitoring
                # Minimal impact from trap monitoring
                base_emissions = 0.1

            elif event.type == "IP":  # IPM Implementation
                # IPM typically reduces chemical use
                base_emissions = -1.0  # Avoided chemical applications

            recommendations = self._generate_pest_recommendations(event, base_emissions)

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": 75.0,
                "calculation_method": "integrated_pest_management_estimation",
                "data_source": "Industry Standards",
                "verification_status": "estimated",
                "breakdown": {
                    "pest_management_type": event.type,
                    "estimated_impact": base_emissions,
                },
                "recommendations": recommendations,
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            return {
                "co2e": 0.0,
                "efficiency_score": 75.0,
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "error": str(e),
            }

    def calculate_general_event_impact(self, event) -> Dict[str, Any]:
        """
        Calculate carbon impact of general events using enhanced emission factors.
        Replaces hardcoded 0.5 kg CO2e with context-aware calculations.
        Option A: Empty events return 0.0 kg CO2e instead of 0.25 kg CO2e.
        """
        try:
            # Get event details for calculation
            event_description = (
                getattr(event, "description", "") or getattr(event, "name", "") or getattr(event, "observation", "")
            )
            event_type = getattr(event, "type", "")

            # Option A: Check for empty/minimal event data
            # If no meaningful content is provided, return 0.0 kg CO2e
            if not event_description or event_description.strip() == "":
                return {
                    "co2e": 0.0,
                    "efficiency_score": 100.0,  # Perfect score for no emissions
                    "calculation_method": "empty_general_event",
                    "data_source": "No Activity Specified",
                    "verification_status": "no_activity",
                    "breakdown": {
                        "general_event_type": "empty",
                        "duration_hours": 0.0,
                        "participants": 0,
                        "emission_factor": 0.0,
                        "confidence_level": "high",
                    },
                    "recommendations": ["Add event description to calculate carbon impact"],
                    "transparency_note": "No emissions calculated - no activity specified",
                }

            # Default parameters for general events
            duration_hours = 1.0
            participants = 1

            # Try to extract duration from event data if available
            if hasattr(event, "extra_data") and event.extra_data:
                duration_hours = float(event.extra_data.get("duration_hours", 1.0))
                participants = int(event.extra_data.get("participants", 1))

            # Determine the appropriate general event type based on description
            general_event_type = self._classify_general_event_type(event_description, event_type)

            # Calculate using enhanced emission factors
            calculation_result = EnhancedEmissionFactors.calculate_general_event_emissions(
                event_type=general_event_type, duration_hours=duration_hours, participants=participants
            )

            base_emissions = calculation_result["co2e_kg"]

            # Generate recommendations
            recommendations = self._generate_general_recommendations(event, base_emissions, general_event_type)

            # Calculate efficiency score based on event type and impact
            efficiency_score = self._calculate_general_efficiency_score(general_event_type, base_emissions)

            result = {
                "co2e": round(base_emissions, 3),
                "efficiency_score": efficiency_score,
                "calculation_method": calculation_result["calculation_method"],
                "data_source": calculation_result["source"],
                "verification_status": "enhanced_factors",
                "breakdown": {
                    "general_event_type": general_event_type,
                    "duration_hours": duration_hours,
                    "participants": participants,
                    "emission_factor": calculation_result["emission_factor"],
                    "confidence_level": calculation_result["confidence_level"],
                },
                "recommendations": recommendations,
                "transparency_note": f"Calculated using EPA-verified factors for {general_event_type} activities",
            }

            return self._add_enhanced_usda_metadata(result, event)

        except Exception as e:
            logger.warning(f"Error calculating general event impact: {e}")
            # Fallback to reasonable default instead of hardcoded 0.5
            return {
                "co2e": 0.1,  # Reduced from 0.5 to more appropriate default
                "efficiency_score": 60.0,
                "calculation_method": "general_event_fallback",
                "data_source": "Default Estimation",
                "verification_status": "estimated",
                "breakdown": {"general_event_type": "documentation", "fallback_reason": str(e)},
                "recommendations": [],
                "error": str(e),
            }

    def create_carbon_entry_from_event(self, event, calculation_result: Dict[str, Any]) -> Optional["CarbonEntry"]:
        """
        Create a CarbonEntry from an event and its carbon calculation result.
        Enhanced with USDA compliance tracking and audit logging.
        """
        try:
            from ..models import CarbonEntry

            # Get or create carbon source
            carbon_source = self._get_or_create_carbon_source(event)

            # Get establishment_id through the parcel relationship
            establishment_id = None
            if hasattr(event, "history") and event.history:
                if hasattr(event.history, "parcel") and event.history.parcel:
                    establishment_id = event.history.parcel.establishment.id

            # Create carbon entry
            carbon_entry = CarbonEntry.objects.create(
                establishment_id=establishment_id,
                production_id=getattr(event.history, "id", None) if hasattr(event, "history") else None,
                type="emission" if calculation_result.get("co2e", 0) > 0 else "offset",
                source=carbon_source,
                amount=abs(calculation_result.get("co2e", 0)),
                year=(
                    getattr(event.date, "year", timezone.now().year)
                    if hasattr(event, "date") and event.date
                    else timezone.now().year
                ),
                description=f"Auto-calculated from {event.__class__.__name__} event: {calculation_result.get('calculation_method', 'unknown')}",
                explanation_text=f"This carbon {'emission' if calculation_result.get('co2e', 0) > 0 else 'offset'} was automatically calculated from farm event data using USDA emission factors. Amount: {abs(calculation_result.get('co2e', 0)):.2f} kg CO2e from {event.__class__.__name__.lower().replace('event', '')} activity.",
                usda_factors_based=calculation_result.get("usda_factors_based", False),
                verification_status=calculation_result.get("verification_status", "estimated"),
                data_source=calculation_result.get("data_source", "Unknown"),
                created_by=getattr(event, "created_by", None) if hasattr(event, "created_by") else None,
                registry_verification_id=f"REG-{event.__class__.__name__}-{event.id}",
                methodology_template=f"USDA_{event.__class__.__name__.upper()}",
                permanence_plan="Auto-generated from verified farm event data",
                baseline_data=calculation_result.get("breakdown", {}),
                co2e_amount=calculation_result.get("co2e", 0),
                timestamp=event.date if hasattr(event, "date") else timezone.now(),
                external_verification_id=f"EXT-{event.__class__.__name__}-{event.id}",
            )

            # Create USDA compliance record
            confidence_score = calculation_result.get("confidence_score", 0.5)
            self._create_usda_compliance_record(carbon_entry, event, calculation_result, confidence_score)

            # Update carbon entry USDA verification status based on compliance record
            from ..models import USDAComplianceRecord

            compliance_record = USDAComplianceRecord.objects.filter(carbon_entry=carbon_entry).first()
            if compliance_record and compliance_record.is_usda_verified:
                carbon_entry.usda_verified = True
                carbon_entry.save(update_fields=["usda_verified"])
                logger.info(
                    f"✅ Updated carbon entry {carbon_entry.id} to usda_verified=True based on compliance record"
                )

            # Create calculation audit record
            calculation_time_ms = calculation_result.get("calculation_time_ms", 0)
            self._create_calculation_audit(event, carbon_entry, calculation_result, calculation_time_ms)

            logger.info(f"Created carbon entry {carbon_entry.id} with USDA compliance tracking")
            return carbon_entry

        except Exception as e:
            logger.error(f"Error creating carbon entry from event: {e}")
            return None

    # ENHANCED Helper methods for structured fields
    def _get_structured_npk_content(self, event, crop_name: str = "default") -> Dict[str, float]:
        """
        Get NPK content from structured fields (nitrogen_percentage, phosphorus_percentage, potassium_percentage)
        or fallback to parsing concentration string.
        CRITICAL FIX: Only fertilizers (FE) have NPK content. Pesticides (PE), Fungicides (FU), Herbicides (HE) have ZERO NPK.
        """
        try:
            # CRITICAL: Check chemical type first - only fertilizers have NPK
            chemical_type = getattr(event, "type", "FE")
            if chemical_type in ["PE", "FU", "HE"]:  # Pesticides, Fungicides, Herbicides
                return {"N": 0.0, "P": 0.0, "K": 0.0}  # NO NPK content

            # Only for fertilizers (FE): Check if structured NPK fields are available and populated
            if (
                hasattr(event, "nitrogen_percentage")
                and event.nitrogen_percentage is not None
                and hasattr(event, "phosphorus_percentage")
                and event.phosphorus_percentage is not None
                and hasattr(event, "potassium_percentage")
                and event.potassium_percentage is not None
            ):

                return {
                    "N": float(event.nitrogen_percentage),
                    "P": float(event.phosphorus_percentage),
                    "K": float(event.potassium_percentage),
                }

            # Fallback to parsing concentration string (only for fertilizers)
            concentration = self._get_intelligent_concentration(event.concentration, event, crop_name)
            return self._parse_npk_content(concentration, chemical_type)

        except Exception as e:
            logger.warning(f"Error getting structured NPK content, using fallback: {e}")
            chemical_type = getattr(event, "type", "FE")
            if chemical_type in ["PE", "FU", "HE"]:
                return {"N": 0.0, "P": 0.0, "K": 0.0}  # NO NPK for non-fertilizers
            concentration = self._get_intelligent_concentration(event.concentration, event, crop_name)
            return self._parse_npk_content(concentration, chemical_type)

    def _get_structured_application_method(self, event, crop_name: str = "default") -> str:
        """
        Get application method from structured field (application_method_structured)
        or fallback to way_of_application or application_method
        """
        try:
            # Check if structured application method field is available
            if hasattr(event, "application_method_structured") and event.application_method_structured:
                return event.application_method_structured

            # Check for frontend application_method field
            if hasattr(event, "application_method") and event.application_method:
                return self._get_intelligent_application_method(event.application_method, event, crop_name)

            # Fallback to legacy field
            if hasattr(event, "way_of_application") and event.way_of_application:
                return self._get_intelligent_application_method(event.way_of_application, event, crop_name)

            # Default if no application method found
            return "broadcast"

        except Exception as e:
            logger.warning(f"Error getting structured application method, using fallback: {e}")
            return "broadcast"

    def _get_structured_equipment_data(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get equipment data from structured fields or fallback to legacy fields
        """
        try:
            # Check for structured fields first
            if hasattr(event, "fuel_consumed") and event.fuel_consumed is not None:
                fuel_amount = float(event.fuel_consumed)
                fuel_unit = getattr(event, "fuel_unit", "L")

                # Convert to liters if needed
                if fuel_unit == "gal":
                    fuel_amount *= 3.78541  # gallons to liters
                elif fuel_unit == "kg":
                    fuel_amount *= 1.2  # approximate kg to L for diesel

                return {
                    "fuel_amount": fuel_amount,
                    "fuel_type": event.fuel_type or "diesel",
                    "equipment_type": getattr(event, "equipment_type_structured", None) or event.equipment_name,
                    "area_worked": float(getattr(event, "area_worked", 0) or 0),
                    "area_unit": getattr(event, "area_unit", "ha"),
                    "hours_operated": float(getattr(event, "hours_operated", 0) or 0),
                    "efficiency": getattr(event, "operation_efficiency", "normal"),
                    "data_source": "structured_fields",
                }

            # Fallback to legacy fields
            return {
                "fuel_amount": float(getattr(event, "fuel_amount", 0) or 0),
                "fuel_type": event.fuel_type or "diesel",
                "equipment_type": event.equipment_name or "general",
                "area_worked": self._extract_numeric_value(event.area_covered or "", default=1.0),
                "area_unit": "ha",
                "hours_operated": float(getattr(event, "hours_used", 0) or 0),
                "efficiency": "normal",
                "data_source": "legacy_fields",
            }

        except Exception as e:
            logger.warning(f"Error getting structured equipment data, using defaults: {e}")
            return {
                "fuel_amount": 10.0,  # Default fuel consumption
                "fuel_type": "diesel",
                "equipment_type": "general",
                "area_worked": 1.0,
                "area_unit": "ha",
                "hours_operated": 2.0,
                "efficiency": "normal",
                "data_source": "defaults",
            }

    def _get_structured_production_data(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get production data from structured fields or fallback to legacy fields
        """
        try:
            # Check for structured fields first
            if hasattr(event, "area_covered") and event.area_covered is not None:
                area = float(event.area_covered)
                area_unit = getattr(event, "area_unit", "ha")

                # Convert to hectares if needed
                if area_unit == "acres":
                    area *= 0.404686  # acres to hectares
                elif area_unit == "m2":
                    area /= 10000  # m2 to hectares
                elif area_unit == "km2":
                    area *= 100  # km2 to hectares

                return {
                    "area_hectares": area,
                    "yield_quantity": float(getattr(event, "yield_quantity", 0) or 0),
                    "yield_unit": getattr(event, "yield_unit", "kg"),
                    "fuel_consumed": float(getattr(event, "fuel_consumed", 0) or 0),
                    "fuel_unit": getattr(event, "fuel_unit", "L"),
                    "equipment_hours": float(getattr(event, "equipment_hours", 0) or 0),
                    "transportation_distance": float(getattr(event, "transportation_distance", 0) or 0),
                    "transportation_unit": getattr(event, "transportation_unit", "km"),
                    "efficiency": getattr(event, "production_efficiency", "normal"),
                    "data_source": "structured_fields",
                }

            # Fallback to legacy fields and history data
            area = 1.0  # Default area
            if hasattr(event, "history") and event.history and hasattr(event.history, "parcel"):
                parcel_area = getattr(event.history.parcel, "area", "1")
                area = self._extract_numeric_value(str(parcel_area), default=1.0)

            return {
                "area_hectares": area,
                "yield_quantity": 0.0,
                "yield_unit": "kg",
                "fuel_consumed": 0.0,
                "fuel_unit": "L",
                "equipment_hours": 0.0,
                "transportation_distance": 0.0,
                "transportation_unit": "km",
                "efficiency": "normal",
                "data_source": "legacy_fields",
            }

        except Exception as e:
            logger.warning(f"Error getting structured production data, using defaults: {e}")
            defaults = self._get_intelligent_defaults(event, crop_name)
            return {
                "area_hectares": defaults.get("area", 1.0),
                "yield_quantity": 0.0,
                "yield_unit": "kg",
                "fuel_consumed": 0.0,
                "fuel_unit": "L",
                "equipment_hours": 0.0,
                "transportation_distance": 0.0,
                "transportation_unit": "km",
                "efficiency": "normal",
                "data_source": "defaults",
            }

    def _get_structured_business_data(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get business event data from structured fields
        """
        try:
            return {
                "business_type": getattr(event, "business_type", "certification"),
                "certification_type": getattr(event, "certification_type", None),
                "carbon_credits_earned": float(getattr(event, "carbon_credits_earned", 0) or 0),
                "carbon_credits_unit": getattr(event, "carbon_credits_unit", "tCO2e"),
                "verification_status": getattr(event, "verification_status", "pending"),
                "sustainability_practice": getattr(event, "sustainability_practice", None),
                "data_source": "structured_fields" if hasattr(event, "business_type") else "legacy_fields",
            }
        except Exception as e:
            logger.warning(f"Error getting structured business data, using defaults: {e}")
            return {
                "business_type": "certification",
                "certification_type": None,
                "carbon_credits_earned": 0.0,
                "carbon_credits_unit": "tCO2e",
                "verification_status": "pending",
                "sustainability_practice": None,
                "data_source": "defaults",
            }

    def _extract_production_event_data(self, event) -> Dict[str, Any]:
        """Extract production event data for EPA/USDA calculations"""
        try:
            # Get crop information from the production
            crop_name = "unknown"
            if hasattr(event, "history") and event.history and hasattr(event.history, "product"):
                crop_name = event.history.product.name
            elif hasattr(event, "history") and event.history and hasattr(event.history, "crop_type"):
                crop_name = event.history.crop_type.name if event.history.crop_type else "unknown"

            # Get structured production data
            structured_data = self._get_structured_production_data(event, crop_name)

            # Determine production type based on event type
            production_type = self._get_production_type_name(event.type, crop_name)

            # Extract specific production values
            area_covered = structured_data["area_hectares"] * 2.47105  # Convert to acres for EPA calculations
            fuel_consumed = structured_data["fuel_consumed"]
            equipment_hours = structured_data["equipment_hours"]

            # Convert fuel to gallons if needed
            if fuel_consumed and structured_data["fuel_unit"] == "L":
                fuel_consumed = fuel_consumed / 3.78541  # Convert liters to gallons

            # Estimate water volume for irrigation
            water_volume_gallons = None
            if event.type == "IR":  # Irrigation
                if hasattr(event, "volume") and event.volume:
                    water_volume_gallons = self._convert_volume_to_gallons(event.volume, event, crop_name)
                else:
                    # Estimate based on area (1000 gallons per acre is conservative)
                    water_volume_gallons = area_covered * 1000

            return {
                "production_type": production_type,
                "crop_name": crop_name,
                "area_covered": area_covered,
                "fuel_consumed": fuel_consumed,
                "equipment_hours": equipment_hours,
                "water_volume_gallons": water_volume_gallons,
                "structured_data": structured_data,
            }

        except Exception as e:
            logger.warning(f"Error extracting production data, using defaults: {e}")
            return {
                "production_type": "general production",
                "crop_name": "unknown",
                "area_covered": 1.0,
                "fuel_consumed": None,
                "equipment_hours": None,
                "water_volume_gallons": 1000,
                "structured_data": {},
            }

    def _get_production_type_name(self, event_type: str, crop_name: str) -> str:
        """Get descriptive production type name for EPA calculations - handles ALL frontend types"""
        type_mapping = {
            "HA": f"harvesting {crop_name}",
            "PL": f"planting {crop_name}",
            "IR": f"irrigating {crop_name}",
            "PR": f"pruning {crop_name}",
            "cultivation": f"cultivating {crop_name}",
            "fertilization": f"fertilizing {crop_name}",
            "weeding": f"weeding {crop_name}",
            "mulching": f"mulching {crop_name}",
            "transplanting": f"transplanting {crop_name}",
            "GE": f"general production {crop_name}",
        }
        return type_mapping.get(event_type, f"general production {crop_name}")

    def _convert_volume_to_gallons(self, volume_str: str, event, crop_name: str) -> float:
        """Convert volume string to gallons for EPA calculations"""
        try:
            volume_value = self._extract_numeric_value(volume_str, default=0)
            if volume_value == 0:
                return 1000  # Default fallback

            # Assume liters if no unit specified, convert to gallons
            return volume_value / 3.78541

        except Exception as e:
            logger.warning(f"Error converting volume to gallons: {e}")
            return 1000

    def _get_crop_area_modifier(self, event) -> float:
        """Get crop-specific area modifier for production calculations"""
        try:
            if hasattr(event, "history") and event.history and hasattr(event.history, "product"):
                crop_name = event.history.product.name.lower()

                # High-intensity crops require more resources per acre
                if any(crop in crop_name for crop in ["avocado", "almond", "walnut"]):
                    return 1.3  # 30% higher resource intensity
                elif any(crop in crop_name for crop in ["strawberry", "tomato", "pepper"]):
                    return 1.2  # 20% higher resource intensity
                elif any(crop in crop_name for crop in ["herb", "lettuce", "spinach"]):
                    return 0.8  # 20% lower resource intensity

            return 1.0  # No modifier

        except Exception as e:
            return 1.0

    def _generate_epa_production_recommendations(self, event, emissions: float, calculation_method: str) -> list:
        """Generate EPA-based recommendations for production events"""
        recommendations = []

        try:
            # High emissions threshold (above 50 kg CO2e)
            if emissions > 50:
                recommendations.append(
                    {
                        "type": "efficiency_improvement",
                        "message": "Consider upgrading to more fuel-efficient equipment",
                        "impact": "High",
                        "source": "EPA Mobile Source Emission Standards",
                    }
                )

            if emissions > 25:
                recommendations.append(
                    {
                        "type": "operational_optimization",
                        "message": "Optimize field operations timing to reduce multiple passes",
                        "impact": "Medium",
                        "source": "USDA Agricultural Energy Guidelines",
                    }
                )

            # Always include verification recommendation
            if calculation_method == "verified_usda_factors":
                recommendations.append(
                    {
                        "type": "data_quality",
                        "message": "Carbon calculation uses verified EPA/USDA emission factors",
                        "impact": "Transparency",
                        "source": "EPA Greenhouse Gas Emission Factors Hub",
                    }
                )

            return recommendations

        except Exception as e:
            logger.warning(f"Error generating EPA recommendations: {e}")
            return []

    def _calculate_production_efficiency_score(self, breakdown: Dict, calculation_method: str) -> float:
        """Calculate efficiency score based on EPA calculation method"""
        try:
            base_score = 75.0

            # Higher score for USDA-verified calculations
            if calculation_method == "verified_usda_factors":
                base_score = 85.0

            # Adjust based on calculation basis
            calculation_basis = breakdown.get("calculation_basis", "unknown")
            if calculation_basis == "actual_fuel_consumption":
                base_score += 10  # Actual data is more accurate
            elif calculation_basis == "estimated_from_hours_and_area":
                base_score += 5  # Good estimation method

            # Consider confidence level
            confidence = breakdown.get("confidence_level", 0.8)
            base_score *= confidence

            return min(base_score, 95.0)  # Cap at 95%

        except Exception as e:
            return 75.0

    # Helper methods
    def _parse_npk_content(self, concentration_str: str, chemical_type: str = "FE") -> Dict[str, float]:
        """
        Parse NPK values from concentration string like '10-10-10' or '20-5-10'
        CRITICAL FIX: Only fertilizers (FE) have NPK. Other chemicals return 0-0-0.
        """
        try:
            # CRITICAL: Only fertilizers have NPK content
            if chemical_type in ["PE", "FU", "HE"]:  # Pesticides, Fungicides, Herbicides
                return {"N": 0.0, "P": 0.0, "K": 0.0}

            # For fertilizers (FE): Try to parse NPK format (N-P-K)
            if "-" in concentration_str:
                parts = concentration_str.split("-")
                if len(parts) >= 3:
                    return {"N": float(parts[0]), "P": float(parts[1]), "K": float(parts[2])}

            # Try to extract percentage from text
            import re

            numbers = re.findall(r"\d+(?:\.\d+)?", concentration_str)
            if len(numbers) >= 3:
                return {"N": float(numbers[0]), "P": float(numbers[1]), "K": float(numbers[2])}

            # Default NPK for unknown fertilizers only
            if chemical_type == "FE":
                return {"N": 10.0, "P": 10.0, "K": 10.0}
            else:
                return {"N": 0.0, "P": 0.0, "K": 0.0}  # Non-fertilizers have no NPK

        except:
            # Even in error cases, respect chemical type
            if chemical_type in ["PE", "FU", "HE"]:
                return {"N": 0.0, "P": 0.0, "K": 0.0}
            else:
                return {"N": 10.0, "P": 10.0, "K": 10.0}

    def _extract_numeric_value(self, text: str, default: float = 0.0) -> float:
        """Extract first numeric value from text with intelligent fallbacks for 'Unknown' values"""
        try:
            import re

            # Handle "Unknown" values with intelligent defaults
            if text.lower() in ["unknown", "n/a", "na", "", "none", "null"]:
                return default

            numbers = re.findall(r"\d+(?:\.\d+)?", text)
            return float(numbers[0]) if numbers else default
        except:
            return default

    def _get_intelligent_defaults(self, event, crop_name: str = "default") -> Dict[str, Any]:
        """
        Get intelligent default values for events with missing data based on crop type and event type.
        This prevents zero emissions when users enter "Unknown" values.
        """
        defaults = {
            "volume": 10.0,  # liters
            "area": 1.0,  # hectares
            "concentration": "10-10-10",  # NPK
            "application_method": "broadcast",
        }

        # Crop-specific defaults
        crop_lower = crop_name.lower()

        # Event type specific defaults
        if hasattr(event, "type"):
            if event.type == "FE":  # Fertilizer
                if "citrus" in crop_lower or "orange" in crop_lower:
                    defaults.update(
                        {
                            "volume": 50.0,  # Citrus needs more fertilizer
                            "area": 2.0,  # Typical citrus grove size
                            "concentration": "12-6-6",  # Citrus-specific NPK
                        }
                    )
                elif "corn" in crop_lower:
                    defaults.update(
                        {
                            "volume": 75.0,  # Corn is heavy feeder
                            "area": 1.5,  # Typical corn field
                            "concentration": "46-0-0",  # Urea for corn
                        }
                    )
                elif any(nut in crop_lower for nut in ["almond", "walnut", "pecan"]):
                    defaults.update(
                        {
                            "volume": 60.0,  # Nuts need substantial fertilizer
                            "area": 3.0,  # Larger orchard areas
                            "concentration": "15-15-15",  # Balanced for nuts
                        }
                    )
                elif any(veg in crop_lower for veg in ["tomato", "lettuce", "pepper"]):
                    defaults.update(
                        {
                            "volume": 25.0,  # Vegetables need less volume
                            "area": 0.5,  # Smaller vegetable plots
                            "concentration": "20-20-20",  # High NPK for vegetables
                        }
                    )
                else:
                    # Default fertilizer amounts
                    defaults.update(
                        {
                            "volume": 40.0,
                            "area": 1.5,
                            "concentration": "16-16-16",
                        }
                    )

            elif event.type in ["PE", "HE", "FU"]:  # Pesticides, Herbicides, Fungicides
                if "citrus" in crop_lower:
                    defaults.update({"volume": 25.0, "area": 2.0, "application_method": "spray"})  # Citrus pest control
                elif any(veg in crop_lower for veg in ["tomato", "pepper", "cucumber"]):
                    defaults.update(
                        {"volume": 15.0, "area": 0.5, "application_method": "foliar"}  # Vegetables need less pesticide
                    )
                else:
                    defaults.update({"volume": 20.0, "area": 1.0, "application_method": "spray"})

        # Production event defaults
        elif hasattr(event, "type") and event.type == "IR":  # Irrigation
            if any(nut in crop_lower for nut in ["almond", "walnut"]):
                defaults.update(
                    {
                        "volume": 500.0,  # Nuts need lots of water
                        "area": 3.0,
                    }
                )
            elif "citrus" in crop_lower:
                defaults.update(
                    {
                        "volume": 300.0,  # Citrus moderate water
                        "area": 2.0,
                    }
                )
            else:
                defaults.update(
                    {
                        "volume": 200.0,  # Standard irrigation
                        "area": 1.5,
                    }
                )

        return defaults

    def _convert_volume_to_liters(self, volume_str: str, event=None, crop_name: str = "default") -> float:
        """Convert volume string to liters with intelligent defaults for missing data"""
        try:
            # Check if volume is missing or "Unknown"
            if not volume_str or volume_str.lower() in ["unknown", "n/a", "na", "none", "null"]:
                if event:
                    defaults = self._get_intelligent_defaults(event, crop_name)
                    return defaults["volume"]
                return 10.0  # Fallback default

            volume_str = volume_str.lower()
            number = self._extract_numeric_value(volume_str)

            # If extraction failed, use intelligent defaults
            if number == 0.0 and event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["volume"]

            if "gal" in volume_str:
                return number * 3.78541  # gallons to liters
            elif "kg" in volume_str or "kilogram" in volume_str:
                # Convert kg to liters using density (check before 'l' to avoid false matches)
                return self._convert_kg_to_liters(number, event)
            elif "ml" in volume_str:
                return number / 1000
            elif "l" in volume_str or "liter" in volume_str:
                return number
            else:
                return number  # Assume liters if no unit

        except:
            if event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["volume"]
            return 10.0  # Fallback default

    def _convert_kg_to_liters(self, kg_amount: float, event=None) -> float:
        """
        Convert kilograms to liters using chemical-specific density.

        Common agricultural chemical densities (kg/L):
        - Anhydrous ammonia (82-0-0): ~0.68 kg/L
        - Liquid fertilizers: ~1.2-1.4 kg/L
        - Water-based solutions: ~1.0 kg/L
        - Herbicides/Pesticides: ~0.9-1.2 kg/L
        """
        try:
            # Get NPK content to identify chemical type
            if event and hasattr(event, "concentration"):
                concentration = getattr(event, "concentration", "")
                if "82-0-0" in concentration or "anhydrous" in concentration.lower():
                    # Anhydrous ammonia density
                    density = 0.68  # kg/L
                    return kg_amount / density

            # Check if it's a high-nitrogen fertilizer (likely anhydrous ammonia)
            if event and hasattr(event, "type") and getattr(event, "type") == "FE":
                npk_content = self._get_structured_npk_content(event, "default")
                nitrogen_percent = npk_content.get("N", 0)

                if nitrogen_percent >= 80:  # High nitrogen content (anhydrous ammonia)
                    density = 0.68  # kg/L for anhydrous ammonia
                    return kg_amount / density
                elif nitrogen_percent >= 20:  # Liquid fertilizer
                    density = 1.3  # kg/L for typical liquid fertilizers
                    return kg_amount / density

            # Default density for general agricultural chemicals
            density = 1.0  # kg/L (water-based solutions)
            return kg_amount / density

        except Exception as e:
            logger.warning(f"Error converting kg to liters: {e}")
            # Fallback: assume water density
            return kg_amount / 1.0

    def _convert_area_to_hectares(self, area_str: str, event=None, crop_name: str = "default") -> float:
        """Convert area string to hectares with intelligent defaults for missing data"""
        try:
            # Check if area is missing or "Unknown"
            if not area_str or area_str.lower() in ["unknown", "n/a", "na", "none", "null"]:
                if event:
                    defaults = self._get_intelligent_defaults(event, crop_name)
                    return defaults["area"]
                return 1.0  # Fallback default

            area_str = area_str.lower()
            number = self._extract_numeric_value(area_str)

            # If extraction failed, use intelligent defaults
            if number == 0.0 and event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["area"]

            if "acre" in area_str:
                return number * 0.404686  # acres to hectares
            elif "ha" in area_str or "hectare" in area_str:
                return number
            elif "m²" in area_str or "m2" in area_str:
                return number / 10000
            else:
                return number  # Assume hectares if no unit

        except:
            if event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["area"]
            return 1.0  # Fallback default

    # ============================================================================
    # ENHANCED: Lime and Tillage Helper Methods (IPCC 2006 / Reicosky 1997)
    # ============================================================================

    def _parse_lime_amount(self, amendment_amount: str) -> float:
        """
        Parse amendment_amount string to extract lime quantity in kilograms.

        Supports various formats:
        - "2000 kg" or "2000kg"
        - "2 tons" or "2 tonnes"
        - "4000 lbs" or "4000 pounds"
        - "2 t/ha" (tons per hectare)
        - Just numeric value (assumes kg)

        Returns:
            float: Lime amount in kilograms (0.0 if parsing fails)
        """
        if not amendment_amount:
            return 0.0

        try:
            amount_str = str(amendment_amount).lower().strip()

            # Extract numeric value using regex
            import re

            # Match numbers including decimals and thousands separators
            numeric_match = re.search(r"[\d,]+\.?\d*", amount_str.replace(",", ""))
            if not numeric_match:
                return 0.0

            numeric_value = float(numeric_match.group())

            # Convert to kg based on unit
            if "ton" in amount_str or "tonne" in amount_str or amount_str.endswith("t"):
                # Metric tons to kg
                return numeric_value * 1000.0
            elif "lb" in amount_str or "pound" in amount_str:
                # Pounds to kg
                return numeric_value * 0.453592
            elif "kg" in amount_str or not any(
                unit in amount_str for unit in ["ton", "lb", "pound", "t/ha"]
            ):
                # Already in kg or no unit specified (assume kg)
                return numeric_value
            else:
                # Default: assume kg
                return numeric_value

        except Exception as e:
            logger.warning(f"Failed to parse lime amount '{amendment_amount}': {e}")
            return 0.0

    def _detect_lime_type(self, event) -> str:
        """
        Detect lime type from event data.

        Checks:
        - amendment_type field
        - description field
        - notes field

        Returns:
            str: 'limestone' (CaCO3) or 'dolomite' (CaMg(CO3)2)
        """
        # Default to limestone (most common)
        lime_type = "limestone"

        # Check all possible fields for lime type indicators
        fields_to_check = []

        if hasattr(event, "amendment_type") and event.amendment_type:
            fields_to_check.append(str(event.amendment_type).lower())
        if hasattr(event, "description") and event.description:
            fields_to_check.append(str(event.description).lower())
        if hasattr(event, "notes") and event.notes:
            fields_to_check.append(str(event.notes).lower())
        if hasattr(event, "amendment_amount") and event.amendment_amount:
            fields_to_check.append(str(event.amendment_amount).lower())

        combined_text = " ".join(fields_to_check)

        # Check for dolomite/dolomitic lime indicators
        dolomite_indicators = [
            "dolomite",
            "dolomitic",
            "mag lime",
            "magnesium lime",
            "camg",
            "calcium magnesium",
        ]

        for indicator in dolomite_indicators:
            if indicator in combined_text:
                lime_type = "dolomite"
                logger.info(f"Detected dolomite lime type from event data: '{indicator}'")
                break

        # Check for explicit limestone indicators (to confirm default)
        limestone_indicators = [
            "limestone",
            "calcitic",
            "ag lime",
            "agricultural lime",
            "caco3",
            "calcium carbonate",
        ]

        for indicator in limestone_indicators:
            if indicator in combined_text:
                lime_type = "limestone"
                logger.info(f"Confirmed limestone type from event data: '{indicator}'")
                break

        return lime_type

    def _detect_tillage_depth(self, event) -> str:
        """
        Detect tillage depth category from event data.

        Checks:
        - tillage_depth field
        - description field
        - equipment_type field
        - notes field

        Returns:
            str: 'shallow' (0-10cm), 'medium' (10-20cm), or 'deep' (>20cm)
        """
        # Default to medium if no depth indicators found
        depth_category = "medium"

        # Check for explicit tillage_depth field
        if hasattr(event, "tillage_depth") and event.tillage_depth:
            depth_str = str(event.tillage_depth).lower()

            # Try to extract numeric depth value
            import re

            depth_match = re.search(r"(\d+)", depth_str)
            if depth_match:
                depth_cm = float(depth_match.group(1))

                # Check if it's in inches (common in US)
                if "in" in depth_str or "inch" in depth_str or '"' in depth_str:
                    depth_cm = depth_cm * 2.54  # Convert inches to cm

                # Categorize based on depth
                if depth_cm <= 10:
                    depth_category = "shallow"
                elif depth_cm <= 20:
                    depth_category = "medium"
                else:
                    depth_category = "deep"

                logger.info(f"Detected tillage depth {depth_cm}cm → category: {depth_category}")
                return depth_category

        # Check description and equipment type for depth indicators
        fields_to_check = []
        if hasattr(event, "description") and event.description:
            fields_to_check.append(str(event.description).lower())
        if hasattr(event, "equipment_type") and event.equipment_type:
            fields_to_check.append(str(event.equipment_type).lower())
        if hasattr(event, "notes") and event.notes:
            fields_to_check.append(str(event.notes).lower())

        combined_text = " ".join(fields_to_check)

        # Deep tillage indicators (typically >20cm)
        deep_indicators = [
            "deep tillage",
            "deep plow",
            "moldboard",
            "chisel plow",
            "subsoil",
            "ripper",
            "deep rip",
            "primary tillage",
            "conventional tillage",
            "full inversion",
        ]

        # Shallow tillage indicators (typically 0-10cm)
        shallow_indicators = [
            "shallow",
            "surface",
            "disk harrow",
            "harrow",
            "cultivator",
            "minimum till",
            "reduced till",
            "conservation till",
            "no-till",
            "strip till",
        ]

        # Check for deep tillage first (more emissions)
        for indicator in deep_indicators:
            if indicator in combined_text:
                depth_category = "deep"
                logger.info(f"Detected deep tillage from indicator: '{indicator}'")
                return depth_category

        # Check for shallow tillage
        for indicator in shallow_indicators:
            if indicator in combined_text:
                depth_category = "shallow"
                logger.info(f"Detected shallow tillage from indicator: '{indicator}'")
                return depth_category

        # Default to medium if no clear indicators
        logger.info(f"No tillage depth indicators found, using default: {depth_category}")
        return depth_category

    def _estimate_irrigation_water_volume(self, event, area_acres: float) -> float:
        """
        Estimate irrigation water volume when not explicitly provided.

        Uses USDA NASS 2023 Irrigation and Water Management Survey data:
        - Average seasonal application: 1.5 acre-feet per acre (~489,000 gallons/acre/season)
        - Typical single irrigation: 0.5-1.5 inches per event
        - 1 inch of water per acre = 27,154 gallons

        Sources:
        - USDA ERS Irrigation & Water Use (ers.usda.gov)
        - USDA NASS 2023 Irrigation Survey

        Returns:
            float: Estimated water volume in gallons
        """
        # Default to 1 acre if no area specified
        if not area_acres or area_acres <= 0:
            area_acres = 1.0

        # Base estimation: moderate irrigation event (1 inch of water)
        # 1 inch water per acre = 27,154 gallons
        GALLONS_PER_INCH_PER_ACRE = 27154.0

        # Default single irrigation: 1 inch (moderate)
        irrigation_inches = 1.0

        # Detect irrigation intensity from event data
        fields_to_check = []
        if hasattr(event, "description") and event.description:
            fields_to_check.append(str(event.description).lower())
        if hasattr(event, "notes") and event.notes:
            fields_to_check.append(str(event.notes).lower())
        if hasattr(event, "irrigation_type") and event.irrigation_type:
            fields_to_check.append(str(event.irrigation_type).lower())

        combined_text = " ".join(fields_to_check)

        # Heavy irrigation indicators (1.5-2 inches)
        heavy_indicators = [
            "heavy",
            "deep",
            "flood",
            "furrow flood",
            "border flood",
            "saturate",
            "soak",
            "drought recovery",
        ]

        # Light irrigation indicators (0.5 inches)
        light_indicators = [
            "light",
            "supplement",
            "drip",
            "trickle",
            "micro",
            "deficit",
            "maintenance",
            "germination",
        ]

        # Check for heavy irrigation
        for indicator in heavy_indicators:
            if indicator in combined_text:
                irrigation_inches = 1.75  # Heavy: 1.5-2 inches average
                logger.info(f"Detected heavy irrigation from indicator: '{indicator}'")
                break
        else:
            # Check for light irrigation
            for indicator in light_indicators:
                if indicator in combined_text:
                    irrigation_inches = 0.5  # Light: 0.5 inches
                    logger.info(f"Detected light irrigation from indicator: '{indicator}'")
                    break

        # Calculate total water volume
        water_volume_gallons = area_acres * irrigation_inches * GALLONS_PER_INCH_PER_ACRE

        logger.info(
            f"USDA-based irrigation estimate: {area_acres} acres × {irrigation_inches} inches × "
            f"{GALLONS_PER_INCH_PER_ACRE} gal/in/acre = {water_volume_gallons:.0f} gallons"
        )

        return water_volume_gallons

    def _get_intelligent_concentration(self, concentration_str: str, event=None, crop_name: str = "default") -> str:
        """Get intelligent concentration defaults for missing data"""
        if not concentration_str or concentration_str.lower() in ["unknown", "n/a", "na", "none", "null"]:
            if event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["concentration"]
            return "10-10-10"  # Fallback default
        return concentration_str

    def _get_intelligent_application_method(self, method_str: str, event=None, crop_name: str = "default") -> str:
        """Get intelligent application method defaults for missing data"""
        if not method_str or method_str.lower() in ["unknown", "n/a", "na", "none", "null"]:
            if event:
                defaults = self._get_intelligent_defaults(event, crop_name)
                return defaults["application_method"]
            return "broadcast"  # Fallback default
        return method_str

    def _normalize_application_method(self, method: str) -> str:
        """Normalize application method to standard terms (legacy)"""
        method = method.lower()
        if any(word in method for word in ["drip", "irrigation", "micro"]):
            return "drip_irrigation"
        elif any(word in method for word in ["broadcast", "spread"]):
            return "broadcast"
        elif any(word in method for word in ["foliar", "spray", "leaf"]):
            return "foliar"
        elif any(word in method for word in ["band", "strip"]):
            return "banded"
        elif any(word in method for word in ["inject", "subsurface"]):
            return "injection"
        else:
            return "broadcast"  # Default

    def _normalize_application_method_for_factors(self, method: str) -> str:
        """Normalize application method for emission factor adjustments"""
        method = method.lower()

        # Map to emission factor adjustment categories
        if any(word in method for word in ["inject", "subsurface", "deep"]):
            return "injected"
        elif any(word in method for word in ["incorporate", "till", "mix"]):
            return "incorporated"
        elif any(word in method for word in ["slow", "controlled", "coated", "release"]):
            return "slow_release"
        elif any(word in method for word in ["precision", "variable", "gps", "rate"]):
            return "precision"
        elif any(word in method for word in ["split", "multiple", "sidedress"]):
            return "split_application"
        else:
            return "broadcast"  # Default baseline method

    def _estimate_chemical_cost(self, event, volume_liters: float) -> float:
        """Estimate cost of chemical application"""
        # Rough cost estimates per liter
        cost_per_liter = {
            "FE": 2.50,  # Fertilizer
            "PE": 15.00,  # Pesticide
            "HE": 8.00,  # Herbicide
            "FU": 12.00,  # Fungicide
        }

        base_cost = cost_per_liter.get(event.type, 5.0) * volume_liters
        return round(base_cost, 2)

    def _generate_chemical_recommendations(
        self,
        event,
        efficiency: float,
        emissions: float,
        cost: float,
        crop_name: str = "default",
        crop_category: str = "default",
    ) -> List[Dict[str, Any]]:
        """Generate cost-saving and efficiency recommendations with crop-specific advice"""
        recommendations = []

        if efficiency < 0.8:
            recommendations.append(
                {
                    "type": "efficiency",
                    "title": "Improve Application Efficiency",
                    "description": f"Consider drip irrigation or injection methods for {round((0.9 - efficiency) * 100, 1)}% efficiency gain",
                    "potential_savings": round(cost * (0.9 - efficiency), 2),
                    "carbon_reduction": round(emissions * (0.9 - efficiency), 2),
                }
            )

        if event.type == "FE" and emissions > 50:  # High fertilizer emissions
            recommendations.append(
                {
                    "type": "optimization",
                    "title": "Consider Slow-Release Fertilizer",
                    "description": "Slow-release fertilizers can reduce N2O emissions by 20-30%",
                    "potential_savings": round(cost * 0.15, 2),
                    "carbon_reduction": round(emissions * 0.25, 2),
                }
            )

        # Crop-specific recommendations
        if crop_category == "legumes" and event.type == "FE":
            recommendations.append(
                {
                    "type": "crop_specific",
                    "title": "Reduce Nitrogen for Legumes",
                    "description": f"{crop_name} can fix nitrogen naturally. Consider reducing N fertilizer by 30-50%.",
                    "potential_savings": round(cost * 0.4, 2),
                    "carbon_reduction": round(emissions * 0.4, 2),
                }
            )

        if crop_category == "herbs" and event.type in ["PE", "HE", "FU"]:
            recommendations.append(
                {
                    "type": "crop_specific",
                    "title": "Consider Organic Pest Control",
                    "description": f"{crop_name} responds well to companion planting and beneficial insects.",
                    "potential_savings": round(cost * 0.3, 2),
                    "carbon_reduction": round(emissions * 0.3, 2),
                }
            )

        if crop_category == "nuts" and emissions > 30:
            recommendations.append(
                {
                    "type": "crop_specific",
                    "title": "Tree Crop Efficiency",
                    "description": f"{crop_name} trees benefit from precise nutrient timing. Consider soil testing.",
                    "potential_savings": round(cost * 0.2, 2),
                    "carbon_reduction": round(emissions * 0.2, 2),
                }
            )

        return recommendations

    def _generate_production_recommendations(
        self, event, emissions: float, crop_name: str = "default", crop_category: str = "default"
    ) -> List[Dict[str, Any]]:
        """Generate recommendations for production events with crop-specific advice"""
        recommendations = []

        if event.type == "IR":  # Irrigation
            recommendations.append(
                {
                    "type": "water_efficiency",
                    "title": "Optimize Irrigation Timing",
                    "description": "Early morning irrigation reduces evaporation losses by 20-30%",
                    "potential_savings": 50.0,
                    "carbon_reduction": round(emissions * 0.25, 2),
                }
            )

            # Crop-specific irrigation recommendations
            if crop_category == "nuts":
                recommendations.append(
                    {
                        "type": "crop_specific",
                        "title": "Deficit Irrigation for Nuts",
                        "description": f"{crop_name} can tolerate controlled water stress, reducing water use by 15-25%.",
                        "potential_savings": 100.0,
                        "carbon_reduction": round(emissions * 0.2, 2),
                    }
                )
            elif crop_category == "vegetables":
                recommendations.append(
                    {
                        "type": "crop_specific",
                        "title": "Mulching for Vegetables",
                        "description": f"{crop_name} benefits from mulching to retain soil moisture.",
                        "potential_savings": 75.0,
                        "carbon_reduction": round(emissions * 0.15, 2),
                    }
                )

        if event.type in ["HA", "PL"]:  # Harvesting, Planting
            recommendations.append(
                {
                    "type": "equipment",
                    "title": "Equipment Efficiency",
                    "description": "Regular equipment maintenance can improve fuel efficiency by 10-15%",
                    "potential_savings": 200.0,
                    "carbon_reduction": round(emissions * 0.12, 2),
                }
            )

            # Crop-specific equipment recommendations
            if crop_category == "grains":
                recommendations.append(
                    {
                        "type": "crop_specific",
                        "title": "Combine Harvester Optimization",
                        "description": f"{crop_name} harvesting can be optimized with proper combine settings.",
                        "potential_savings": 150.0,
                        "carbon_reduction": round(emissions * 0.1, 2),
                    }
                )

        return recommendations

    def _generate_weather_recommendations(self, event) -> List[Dict[str, Any]]:
        """Generate recommendations for weather events with enhanced suggestions"""
        recommendations = []

        if event.type == "FR":  # Frost
            recommendations.append(
                {
                    "type": "protection",
                    "title": "Consider Passive Frost Protection",
                    "description": "Row covers or thermal mass can reduce energy needs by 40%",
                    "potential_savings": 300.0,
                    "carbon_reduction": 6.0,
                }
            )
            if hasattr(event, "lower_temperature"):
                temp = self._extract_numeric_value(event.lower_temperature, default=32)
                if temp < 28:  # Severe frost
                    recommendations.append(
                        {
                            "type": "monitoring",
                            "title": "Install Temperature Monitoring System",
                            "description": "Early warning systems can optimize protection timing",
                            "potential_savings": 200.0,
                            "carbon_reduction": 4.0,
                        }
                    )

        elif event.type == "DR":  # Drought
            recommendations.append(
                {
                    "type": "resilience",
                    "title": "Install Drip Irrigation",
                    "description": "Reduce water usage by 50% during drought conditions",
                    "potential_savings": 500.0,
                    "carbon_reduction": 10.0,
                }
            )

        elif event.type == "HL":  # Hailstorm
            recommendations.append(
                {
                    "type": "protection",
                    "title": "Install Hail Netting",
                    "description": "Reduce crop damage by 80-90% in future hail events",
                    "potential_savings": 2000.0,
                    "carbon_reduction": 50.0,
                }
            )
            if hasattr(event, "diameter"):
                diameter = self._extract_numeric_value(event.diameter, default=1.0)
                if diameter > 20:  # Large hail
                    recommendations.append(
                        {
                            "type": "insurance",
                            "title": "Review Crop Insurance Coverage",
                            "description": "Large hail events suggest need for comprehensive coverage",
                            "potential_savings": 5000.0,
                            "carbon_reduction": 0.0,
                        }
                    )

        elif event.type == "HT":  # High temperatures
            recommendations.append(
                {
                    "type": "cooling",
                    "title": "Implement Shade Netting",
                    "description": "Reduce heat stress and water evaporation by 30%",
                    "potential_savings": 400.0,
                    "carbon_reduction": 8.0,
                }
            )

        elif event.type in ["TS", "HW"]:  # Tropical storm, High winds
            recommendations.append(
                {
                    "type": "structural",
                    "title": "Install Windbreaks",
                    "description": "Reduce wind damage and soil erosion",
                    "potential_savings": 800.0,
                    "carbon_reduction": 15.0,
                }
            )

        elif event.type in ["HH", "LH"]:  # Humidity issues
            recommendations.append(
                {
                    "type": "environmental",
                    "title": "Optimize Microclimate Management",
                    "description": "Proper spacing and airflow can reduce humidity-related issues",
                    "potential_savings": 300.0,
                    "carbon_reduction": 5.0,
                }
            )

        return recommendations

    def _generate_equipment_recommendations(
        self, event, emissions: float, cost: float, equipment_data: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Generate recommendations for equipment events"""
        recommendations = []

        if event.type == "FC" and float(event.fuel_amount or 0) > 20:  # High fuel consumption
            recommendations.append(
                {
                    "type": "fuel_efficiency",
                    "title": "Consider Precision Agriculture",
                    "description": "GPS guidance can reduce fuel consumption by 10-15%",
                    "potential_savings": cost * 0.12,
                    "carbon_reduction": emissions * 0.12,
                }
            )

        if event.type in ["MA", "RE"]:
            recommendations.append(
                {
                    "type": "maintenance",
                    "title": "Preventive Maintenance Schedule",
                    "description": "Regular maintenance reduces breakdowns and improves efficiency",
                    "potential_savings": cost * 0.2,
                    "carbon_reduction": 2.0,
                }
            )

        return recommendations

    def _generate_soil_recommendations(self, event, emissions: float) -> List[Dict[str, Any]]:
        """Generate recommendations for soil management events"""
        recommendations = []

        if event.type == "TI":  # Tillage
            recommendations.append(
                {
                    "type": "conservation",
                    "title": "Consider No-Till Practices",
                    "description": "No-till farming can sequester 0.5-1.5 tons CO2e per hectare per year",
                    "potential_savings": 0.0,
                    "carbon_reduction": 10.0,
                }
            )

        if event.type == "ST" and float(event.soil_ph or 0) < 6.0:
            recommendations.append(
                {
                    "type": "soil_health",
                    "title": "pH Adjustment Needed",
                    "description": "Optimal pH improves nutrient efficiency and reduces fertilizer needs",
                    "potential_savings": 200.0,
                    "carbon_reduction": 5.0,
                }
            )

        return recommendations

    def _generate_business_recommendations(
        self, event, emissions: float, business_data: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Generate recommendations for business events"""
        recommendations = []

        if event.type == "HS":
            recommendations.append(
                {
                    "type": "logistics",
                    "title": "Optimize Transportation",
                    "description": "Consolidate shipments to reduce transportation emissions",
                    "potential_savings": 100.0,
                    "carbon_reduction": emissions * 0.3,
                }
            )

        if event.type == "CE":
            recommendations.append(
                {
                    "type": "certification",
                    "title": "Expand Carbon Credit Programs",
                    "description": "Additional sustainable practices can generate more carbon credits",
                    "potential_savings": 1000.0,
                    "carbon_reduction": 20.0,
                }
            )

        return recommendations

    def _generate_pest_recommendations(self, event, emissions: float) -> List[Dict[str, Any]]:
        """Generate recommendations for pest management events"""
        recommendations = []

        if event.type == "SC" and event.pest_pressure_level == "High":
            recommendations.append(
                {
                    "type": "ipm",
                    "title": "Implement Biological Control",
                    "description": "Beneficial insects can reduce pesticide use by 30-50%",
                    "potential_savings": 300.0,
                    "carbon_reduction": 5.0,
                }
            )

        if event.type == "IP":
            recommendations.append(
                {
                    "type": "monitoring",
                    "title": "Expand IPM Monitoring",
                    "description": "Regular monitoring can prevent pest outbreaks and reduce treatments",
                    "potential_savings": 500.0,
                    "carbon_reduction": 8.0,
                }
            )

        return recommendations

    def _get_or_create_carbon_source(self, event) -> "CarbonSource":
        """
        Get or create a CarbonSource for the given event type.
        """
        from ..models import CarbonSource

        # Map event types to carbon source names
        source_mapping = {
            "FE": "Fertilizer Application",
            "PE": "Pesticide Application",
            "HE": "Herbicide Application",
            "FU": "Fungicide Application",
            "IR": "Irrigation",
            "HA": "Harvesting",
            "PL": "Planting",
            "PR": "Pruning",
            "FC": "Fuel Consumption",
            "MA": "Equipment Maintenance",
            "RE": "Equipment Repair",
            "CA": "Equipment Calibration",
            "BR": "Equipment Breakdown",
        }

        source_name = source_mapping.get(event.type, f"{event.type} Activity")

        source, created = CarbonSource.objects.get_or_create(
            name=source_name,
            defaults={
                "category": "agricultural_activity",
                "description": f"Carbon emissions from {source_name.lower()}",
                "usda_factors_based": True,
                "verification_status": "factors_verified",
            },
        )

        return source

    def _classify_general_event_type(self, event_description: str, event_type: str) -> str:
        """
        Classify general event type based on description and type for appropriate emission factor selection.
        """
        description_lower = event_description.lower()
        type_lower = event_type.lower() if event_type else ""

        # Check for specific activity patterns in description
        if any(keyword in description_lower for keyword in ["visit", "inspection", "consultation", "meeting"]):
            return "farm_visit"
        elif any(keyword in description_lower for keyword in ["training", "workshop", "education", "learning"]):
            return "training_session"
        elif any(keyword in description_lower for keyword in ["document", "record", "note", "observation", "report"]):
            return "documentation"
        elif any(keyword in description_lower for keyword in ["scout", "monitor", "check", "survey", "assess"]):
            # Note: These should ideally be pest management events, but if they're general events, treat as documentation
            return "documentation"
        else:
            # Default to documentation for unknown general events
            return "documentation"

    def _generate_general_recommendations(
        self, event, base_emissions: float, general_event_type: str
    ) -> List[Dict[str, Any]]:
        """
        Generate recommendations for general events based on event type and emissions.
        """
        recommendations = []

        if general_event_type == "farm_visit" and base_emissions > 5.0:
            recommendations.append(
                {
                    "type": "efficiency",
                    "title": "Combine Farm Visits",
                    "description": "Schedule multiple activities in single visits to reduce transportation emissions",
                    "potential_savings": 50.0,
                    "carbon_reduction": 2.0,
                }
            )
        elif general_event_type == "training_session":
            recommendations.append(
                {
                    "type": "digitization",
                    "title": "Virtual Training Options",
                    "description": "Consider virtual training sessions to reduce travel-related emissions",
                    "potential_savings": 100.0,
                    "carbon_reduction": 5.0,
                }
            )
        elif general_event_type == "documentation" and base_emissions > 1.0:
            recommendations.append(
                {
                    "type": "efficiency",
                    "title": "Digital Documentation",
                    "description": "Use mobile apps and cloud storage to reduce paper usage and streamline record keeping",
                    "potential_savings": 25.0,
                    "carbon_reduction": 0.5,
                }
            )

        return recommendations

    def _calculate_general_efficiency_score(self, general_event_type: str, base_emissions: float) -> float:
        """
        Calculate efficiency score for general events based on type and emissions.
        """
        # Base efficiency scores by type
        base_scores = {
            "documentation": 80.0,  # Low impact activity
            "training_session": 65.0,  # Medium impact but high value
            "farm_visit": 60.0,  # Higher impact due to transportation
        }

        base_score = base_scores.get(general_event_type, 70.0)

        # Adjust based on emissions level
        if base_emissions <= 0.5:
            return min(95.0, base_score + 15.0)  # Very low emissions
        elif base_emissions <= 2.0:
            return base_score  # Normal range
        else:
            return max(30.0, base_score - (base_emissions * 5))  # Higher emissions reduce score
