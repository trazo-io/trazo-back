"""
Carbon Calculator Service for Production Carbon Calculations
Provides a simple interface for calculating carbon emissions for production records
"""

import logging
from typing import Any, Dict, Optional

from django.db.models import Sum

from ..models import CarbonEntry

logger = logging.getLogger(__name__)


class CarbonCalculatorService:
    """Service for calculating carbon emissions from production data"""

    def calculate_production_carbon(self, history_id: int) -> Dict[str, Any]:
        """
        Calculate carbon emissions for a given production history

        Args:
            history_id: The ID of the production history record

        Returns:
            Dictionary with carbon calculation results
        """
        try:
            # Get carbon entries for this production. `source` is read per entry in the breakdown
            # loop below — without the join that was one CarbonSource query per entry (45 on a
            # 69-event season, 2026-09-05).
            carbon_entries = CarbonEntry.objects.filter(production_id=history_id).select_related("source")

            if not carbon_entries.exists():
                return {
                    "total_co2_kg_per_kg": 0.0,
                    "breakdown": {},
                    "status": "no_data",
                    "message": "No carbon data available for this production",
                }

            # Calculate total emissions
            total_emissions = carbon_entries.filter(type="emission").aggregate(Sum("amount"))["amount__sum"] or 0

            # Calculate total offsets
            total_offsets = (
                carbon_entries.filter(type="offset").aggregate(Sum("effective_amount"))["effective_amount__sum"] or 0
            )

            # Calculate net emissions
            net_emissions = float(total_emissions) - float(total_offsets)

            # Create breakdown by category
            breakdown = {}
            for entry in carbon_entries:
                # Fix: Access category through the source relationship
                category = entry.source.category if entry.source and entry.source.category else "other"
                if category not in breakdown:
                    breakdown[category] = 0

                if entry.type == "emission":
                    breakdown[category] += float(entry.amount or 0)
                elif entry.type == "offset":
                    breakdown[category] -= float(entry.effective_amount or 0)

            # Calculate per-kg value by dividing by production yield
            # CarbonEntry.production is FK to History which has production_amount
            total_co2_kg_per_kg = 0.0
            try:
                first_entry = carbon_entries.select_related("production").first()
                if first_entry and first_entry.production:
                    production_amount = first_entry.production.production_amount or 0
                    if production_amount > 0:
                        total_co2_kg_per_kg = net_emissions / production_amount
                    else:
                        # No production amount recorded — cannot compute per-kg
                        total_co2_kg_per_kg = 0.0
            except Exception:
                total_co2_kg_per_kg = 0.0

            return {
                "total_co2_kg_per_kg": total_co2_kg_per_kg,
                "breakdown": breakdown,
                "total_emissions": float(total_emissions),
                "total_offsets": float(total_offsets),
                "net_emissions": net_emissions,
                "entry_count": carbon_entries.count(),
                "status": "calculated",
                "message": "Carbon calculation completed successfully",
            }

        except Exception as e:
            logger.error(f"Error calculating carbon for production {history_id}: {str(e)}")
            return {
                "total_co2_kg_per_kg": 0.0,
                "breakdown": {},
                "status": "error",
                "message": f"Carbon calculation failed: {str(e)}",
            }
