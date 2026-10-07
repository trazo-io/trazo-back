"""
Transparency Response Formatter
Standardized response format for transparency-first API endpoints
Replaces competitive carbon scoring with transparency and factual data
"""

from typing import Any, Dict, List, Optional

from django.utils import timezone

from backend.constants import calculate_miles_equivalent, calculate_trees_equivalent
from common.location import city_state_label


class TransparencyResponseFormatter:
    """
    Formats API responses using transparency-first approach
    Eliminates competitive carbon scoring to solve farmer incentive problems
    """

    def format_qr_response(
        self,
        production,
        carbon_data: Dict[str, Any],
        blockchain_verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Format QR scanning response with transparency-first approach

        Args:
            production: History model instance
            carbon_data: Raw carbon calculation data
            blockchain_verification: Blockchain verification data (always unverified on this surface)

        Returns:
            Standardized transparency-first response
        """

        # `transparency` used to carry the graded section (`completeness_percentage`,
        # `documentation_score`, a blockchain-derived `verification_status`). All three were
        # self-assigned verdicts nobody rendered; the block is kept for wire compatibility with
        # its one remaining fact (2026-09-05).
        transparency_section = {"last_updated": timezone.now().isoformat()}

        # SECONDARY: Raw carbon impact (factual, not comparative)
        #
        # ⛔ THIS IS A PUBLIC, UNAUTHENTICATED SURFACE. Every consumer-facing figure below
        # is computed from GROSS EMISSIONS, never from the net of purchased offsets.
        # Offsets are self-entered and self-marked verified (`create_secure_carbon_offset`),
        # so netting them into a public number manufactures an environmental benefit claim
        # out of the farm's own data: FTC 16 CFR 260.5 (carbon offsets) and 260.4 (general
        # environmental benefit), and EU ECGT 2024/825 (live 2026-09-27), which bans
        # self-created sustainability labels without third-party verification.
        #
        # Fixed 2026-09-23. Until then `net_impact` drove `totalCO2e` on the buyer page and
        # any farm whose recorded offsets exceeded its emissions rendered a green
        # "Carbon Stored" badge over "Very Low Emissions" — a self-created label, on the
        # exact claim class ECGT names, four days before it took effect.
        #
        # `net_impact` and `total_offsets` stay on the wire: they are real facts and the
        # farmer's own dashboard reads them. ⛔ Never point a consumer field at either.
        net_footprint = self._safe_round(carbon_data.get("net_footprint", 0), 2)
        gross_emissions = self._safe_round(carbon_data.get("total_emissions", 0), 2)
        total_offsets = self._safe_round(carbon_data.get("total_offsets", 0), 2)

        # Per-kg, GROSS. The calculator publishes `gross_co2_kg_per_kg` alongside the net
        # `total_co2_kg_per_kg`. Older callers may send only the net one: that is safe to
        # use ONLY when nothing was offset, because then the two are equal by definition.
        # With offsets present and no gross figure, the number is unrecoverable at this
        # layer, so publish none rather than a contaminated one (zero suppresses it in
        # `_get_consumer_context`).
        gross_kg_per_kg = carbon_data.get("gross_co2_kg_per_kg")
        if gross_kg_per_kg is None:
            gross_kg_per_kg = carbon_data.get("total_co2_kg_per_kg", 0) if total_offsets <= 0 else 0
        kg_per_kg = self._safe_round(gross_kg_per_kg, 3)

        carbon_impact = {
            "kg_per_kg": kg_per_kg,
            "total_emissions": gross_emissions,
            "total_offsets": total_offsets,
            "net_impact": net_footprint,
            "unit": "kg CO₂ per kg product",
            # Recordkeeping review F-02 (2026-10-07): `calculation_method: "USDA_EPA_factors"`
            # was a blanket attribution on the wire; factor sources are per input class and
            # stated on each factor (`basis`). The car-and-phone equivalents (`comparisons`,
            # `per_kg_miles`, `per_kg_phone_charges`) R8-14 removed from the page were still
            # served to every anonymous caller; they are gone from the payload.
            "basis": "Recorded fuel and electricity, plus the manufacturing of purchased fertilizer and "
            "crop-protection products; entries with no recorded basis are not counted",
            "consumer_context": self._get_consumer_context(kg_per_kg),
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
            "transparency": {},
            "carbon_impact": {
                "kg_per_kg": 0.0,
                "total_emissions": 0.0,
                "total_offsets": 0.0,
                "net_impact": 0.0,
                "unit": "kg CO₂ per kg product",
            },
            "response_format": "transparency_error_v2",
            "timestamp": timezone.now().isoformat(),
            "error_details": error_details,
        }

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

        # The sign-up wizard's ticked "sustainability goals" are NOT published (recordkeeping
        # review F-11, 2026-10-07). A checkbox ticked at sign-up became a public "Sustainability
        # Commitment" list of environmental-benefit claims with no record behind any of them, the
        # self-created sustainability-label class ECGT 2024/825 bans and an FTC 16 CFR 260.4
        # general-benefit claim. The stored field stays (no migration, nothing deleted); the
        # wizard stopped asking, and this service stopped serving. `crop_focus` and the
        # company's own commitment text remain farmer-authored prose.
        company_sustainability = None
        if company and company.sustainability_metadata and isinstance(company.sustainability_metadata, dict):
            metadata = company.sustainability_metadata
            company_sustainability = {
                "crop_focus": metadata.get("crop_template", {}).get("title") if metadata.get("crop_template") else None,
                "commitment": company.sustainability_commitment,
            }

        return {
            "farm_name": establishment.name if establishment else "Farm",
            "location": city_state_label(establishment) or "Location not specified",
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
        # No car-mile or phone-charge equivalents (R8-14 on the page; recordkeeping review F-02
        # on the wire): a per-kg figure with its scope is the whole of what a shopper gets.
        if kg_per_kg <= 0:
            return {"kg_per_kg": 0.0, "has_per_kg_data": False}
        return {"kg_per_kg": self._safe_round(kg_per_kg, 3), "has_per_kg_data": True}

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
