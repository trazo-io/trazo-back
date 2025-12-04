"""
Transparency Response Formatter
Standardized response format for transparency-first API endpoints
Replaces competitive carbon scoring with transparency and factual data
"""

from typing import Any, Dict, List, Optional

from django.utils import timezone


class TransparencyResponseFormatter:
    """
    Formats API responses using transparency-first approach
    Eliminates competitive carbon scoring to solve farmer incentive problems
    """

    def format_qr_response(
        self,
        production,
        carbon_data: Dict[str, Any],
        transparency_data: Dict[str, Any],
        blockchain_verification: Optional[Dict[str, Any]] = None,
        achievements: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Format QR scanning response with transparency-first approach

        Args:
            production: History model instance
            carbon_data: Raw carbon calculation data
            transparency_data: Transparency metrics and scores
            blockchain_verification: Blockchain verification data
            achievements: Transparency-based achievements

        Returns:
            Standardized transparency-first response
        """

        # PRIMARY: Transparency metrics (non-competitive)
        transparency_section = {
            "completeness_percentage": transparency_data.get("transparency_percentage", 0),  # FIX: Use calculated score
            "data_quality_grade": transparency_data.get("carbonGrade", "C"),
            "verification_status": self._get_verification_status(blockchain_verification),
            "documentation_score": transparency_data.get("completeness_score", 0),  # FIX: Remove hardcoded 75
            "last_updated": timezone.now().isoformat(),
        }

        # SECONDARY: Raw carbon impact (factual, not comparative)
        carbon_impact = {
            "kg_per_kg": self._safe_round(carbon_data.get("total_co2_kg_per_kg", 0), 3),
            "total_emissions": self._safe_round(carbon_data.get("total_emissions", 0), 2),
            "total_offsets": self._safe_round(carbon_data.get("total_offsets", 0), 2),
            "net_impact": self._safe_round(carbon_data.get("net_footprint", 0), 2),
            "unit": "kg CO₂ per kg product",
            "calculation_method": carbon_data.get("calculation_method", "USDA_based"),
        }

        # TERTIARY: Contextual information (no competitive ranking)
        farm_context = self._get_farm_context(production)

        return {
            # Core transparency data
            "transparency": transparency_section,
            "carbon_impact": carbon_impact,
            # Supporting information
            "farm_context": farm_context,
            "environmental_impact_description": self._get_impact_description(carbon_impact),
            "data_sources": self._get_data_sources(carbon_data),
            "achievements": achievements or [],
            # Technical metadata
            "response_format": "transparency_v2",
            "timestamp": timezone.now().isoformat(),
            "blockchain_verification": blockchain_verification or {"verified": False},
        }

    def format_quick_response(self, production, minimal_carbon_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Format quick response for progressive loading
        Optimized for <1s response time
        """
        return {
            "transparency": {
                "completeness_percentage": getattr(production, "transparency_percentage", 75),
                "data_quality_grade": getattr(production, "carbon_grade", "C"),
                "verification_status": "verified" if getattr(production, "blockchain_verified", False) else "pending",
            },
            "carbon_impact": {
                "kg_per_kg": (
                    self._safe_round(minimal_carbon_data.get("kg_per_kg", 0), 3) if minimal_carbon_data else 0.0
                ),
                "unit": "kg CO₂ per kg product",
            },
            "response_format": "transparency_quick_v2",
            "timestamp": timezone.now().isoformat(),
        }

    def format_error_response(self, error_message: str, error_details: Optional[str] = None) -> Dict[str, Any]:
        """
        Format error response maintaining transparency structure
        """
        return {
            "error": error_message,
            "transparency": {
                "completeness_percentage": 0,
                "data_quality_grade": "pending",
                "verification_status": "error",
            },
            "carbon_impact": {
                "kg_per_kg": 0.0,
                "total_emissions": 0.0,
                "total_offsets": 0.0,
                "net_impact": 0.0,
                "unit": "kg CO₂ per kg product",
            },
            "achievements": [],
            "response_format": "transparency_error_v2",
            "timestamp": timezone.now().isoformat(),
            "error_details": error_details,
        }

    def _get_verification_status(self, blockchain_verification: Optional[Dict[str, Any]]) -> str:
        """Get verification status from blockchain data"""
        if not blockchain_verification:
            return "pending"
        return "verified" if blockchain_verification.get("verified", False) else "pending"

    def _get_farm_context(self, production) -> Dict[str, Any]:
        """Get farm context without competitive elements"""
        establishment = production.parcel.establishment if production.parcel else None

        # Build harvest details if available
        harvest_details = {}
        if production.production_amount:
            harvest_details["amount"] = production.production_amount
            harvest_details["unit"] = production.production_unit or "kg"
        if production.lot_id:
            harvest_details["lot_number"] = production.lot_id
        if production.quality_grade:
            # Map internal codes to consumer-friendly labels
            grade_labels = {
                "premium": "Premium Grade",
                "grade_a": "Grade A",
                "grade_b": "Grade B",
                "standard": "Standard",
                "processing": "Processing Grade",
            }
            harvest_details["quality_grade"] = grade_labels.get(production.quality_grade, production.quality_grade)
        if production.harvest_method:
            method_labels = {
                "manual": "Hand Harvested",
                "mechanical": "Machine Harvested",
                "mixed": "Mixed Harvest",
            }
            harvest_details["harvest_method"] = method_labels.get(production.harvest_method, production.harvest_method)

        return {
            "farm_name": establishment.name if establishment else "Farm",
            "location": (
                f"{establishment.city}, {establishment.state}"
                if establishment and establishment.city
                else "Location not specified"
            ),
            "crop_type": getattr(production.crop_type, "name", "Unknown") if production.crop_type else "Unknown",
            "production_period": {
                "start": production.start_date.isoformat() if production.start_date else None,
                "end": production.finish_date.isoformat() if production.finish_date else None,
            },
            "harvest_details": harvest_details if harvest_details else None,
        }

    def _get_impact_description(self, carbon_impact: Dict[str, Any]) -> str:
        """Generate consumer-friendly impact description"""
        kg_per_kg = carbon_impact.get("kg_per_kg", 0)

        if kg_per_kg <= 0.5:
            return "Very low carbon impact per kg of product"
        elif kg_per_kg <= 1.0:
            return "Low carbon impact per kg of product"
        elif kg_per_kg <= 2.0:
            return "Moderate carbon impact per kg of product"
        else:
            return "Higher carbon impact per kg of product"

    def _get_data_sources(self, carbon_data: Dict[str, Any]) -> List[str]:
        """Get data sources for transparency"""
        sources = []

        if carbon_data.get("usda_verified"):
            sources.append("USDA Government Database")
        if carbon_data.get("blockchain_verified"):
            sources.append("Blockchain Verification")
        if carbon_data.get("third_party_verified"):
            sources.append("Third-Party Audit")

        if not sources:
            sources.append("Farm Records")

        return sources

    def _safe_round(self, value: float, decimals: int) -> float:
        """Safely round numeric values"""
        try:
            return round(float(value), decimals)
        except (ValueError, TypeError):
            return 0.0
