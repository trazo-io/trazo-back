"""
Transparency Response Formatter
Standardized response format for transparency-first API endpoints
Replaces competitive carbon scoring with transparency and factual data
"""

from typing import Any, Dict, List, Optional

from django.utils import timezone

from backend.constants import calculate_miles_equivalent, calculate_trees_equivalent


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
        net_footprint = self._safe_round(carbon_data.get("net_footprint", 0), 2)
        kg_per_kg = self._safe_round(carbon_data.get("total_co2_kg_per_kg", 0), 3)
        carbon_impact = {
            "kg_per_kg": kg_per_kg,
            "total_emissions": self._safe_round(carbon_data.get("total_emissions", 0), 2),
            "total_offsets": self._safe_round(carbon_data.get("total_offsets", 0), 2),
            "net_impact": net_footprint,
            "unit": "kg CO₂ per kg product",
            "calculation_method": carbon_data.get("calculation_method", "USDA_based"),
            # Consumer-friendly: per-unit comparison + impact level
            "consumer_context": self._get_consumer_context(kg_per_kg),
            # Detailed comparisons for total production (expandable section)
            "comparisons": self._calculate_comparisons(abs(net_footprint)),
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
        company = establishment.company if establishment else None

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

        # Build company sustainability data from onboarding metadata
        # BUGFIX: Check that sustainability_metadata is a dict before calling .get()
        company_sustainability = None
        if company and company.sustainability_metadata and isinstance(company.sustainability_metadata, dict):
            metadata = company.sustainability_metadata
            # Extract sustainability goals - these are collected during company creation
            sustainability_goals = metadata.get("sustainability_goals", [])
            # Map goal IDs to consumer-friendly labels
            goal_labels = {
                "full_transparency": "Full Farming Transparency",
                "carbon_reduction": "Environmental Impact Tracking",
                "water_conservation": "Water Conservation",
                "soil_health": "Soil Health Focus",
                "biodiversity": "Biodiversity Protection",
                "local_sourcing": "Local Community Support",
            }
            company_sustainability = {
                "goals": [goal_labels.get(g, g) for g in sustainability_goals] if sustainability_goals else [],
                "crop_focus": metadata.get("crop_template", {}).get("title") if metadata.get("crop_template") else None,
                "commitment": company.sustainability_commitment,
            }

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
            # NEW: Company sustainability data from onboarding
            "company_sustainability": company_sustainability,
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

        if carbon_data.get("usda_factors_used"):
            sources.append("USDA Government Database")
        if carbon_data.get("blockchain_verified"):
            sources.append("Blockchain Verification")
        if carbon_data.get("third_party_verified"):
            sources.append("Third-Party Audit")

        if not sources:
            sources.append("Farm Records")

        return sources

    def _get_consumer_context(self, kg_per_kg: float) -> Dict[str, Any]:
        """
        Generate consumer-friendly carbon context using per-unit data.
        INFORMATIONAL ONLY — no color-coded judgment or competitive ranking.

        Trazo's transparency-first philosophy: the transparency score is the
        only evaluative metric. Carbon data is factual context for consumers
        who want to learn more, not a judgment of the farm.

        Uses kg_per_kg (CO2e per kg of product) for meaningful comparisons.
        EPA factor: 0.35548 kg CO2/mile → miles_per_kg = kg_per_kg / 0.35548
        """
        if kg_per_kg <= 0:
            return {
                "kg_per_kg": 0.0,
                "per_kg_miles": 0.0,
                "per_kg_phone_charges": 0,
                "has_per_kg_data": False,
            }

        miles_per_kg = self._safe_round(kg_per_kg / 0.35548, 1)
        # Average phone charge = ~0.008 kWh × 0.39 kg CO2/kWh = 0.003 kg CO2
        phone_charges = int(kg_per_kg / 0.003) if kg_per_kg > 0 else 0

        return {
            "kg_per_kg": self._safe_round(kg_per_kg, 3),
            "per_kg_miles": miles_per_kg,
            "per_kg_phone_charges": phone_charges,
            "has_per_kg_data": True,
        }

    def _calculate_comparisons(self, co2e_kg: float) -> Dict[str, Any]:
        """
        Calculate real-life comparisons using EPA/USDA conversion factors.
        Single source of truth — frontend should display these, not recalculate.

        Factors:
        - Miles: EPA 0.35548 kg CO2/mile (8.887 kg CO2/gal ÷ 25 mpg)
        - Trees: EPA ~21.8 kg CO2/tree/year
        - Electricity: EPA eGRID 2023 0.39 kg CO2/kWh
        """
        if co2e_kg <= 0:
            return {"driving_miles": 0, "trees_per_year": 0, "kwh_electricity": 0}

        miles = self._safe_round(calculate_miles_equivalent(co2e_kg), 1)
        trees = int(calculate_trees_equivalent(co2e_kg)) + 1  # ceil
        kwh = self._safe_round(co2e_kg / 0.39, 0)  # EPA eGRID 2023: 0.39 kg CO2/kWh

        return {
            "driving_miles": miles,
            "trees_per_year": trees,
            "kwh_electricity": int(kwh),
        }

    def _safe_round(self, value: float, decimals: int) -> float:
        """Safely round numeric values"""
        try:
            return round(float(value), decimals)
        except (ValueError, TypeError):
            return 0.0
