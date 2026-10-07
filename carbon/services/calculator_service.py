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

    #: Emission rows that rest on a published factor applied to a recorded quantity. Only these
    #: reach a consumer figure (recordkeeping review F-02, 2026-10-07). An ALLOWLIST, not a
    #: denylist (review of back #132): `verification_status` is free text, and "estimated"
    #: (a per-hour guess for a repair), "area_estimate" (a per-hectare guess with no fuel
    #: recorded), "insufficient_data" and the error statuses must all fail closed. The farmer's
    #: own dashboard total keeps every row.
    RECORDED_BASIS_STATUSES = frozenset(
        {
            "factors_verified",
            "usda_verified",
            "epa_usda_verified",
            "epa_usda_sourced",
            "epa_usda_verified_aggregate",
            "usda_ipcc_factors_verified",
            "epa_verified",
            "enhanced_factors",
            "verified",
            "verified_zero",
        }
    )

    #: Mass units a season's `production_amount` may carry, in kilograms per unit. Anything else
    #: (boxes, crates, bins, units, bushels) is not a mass and yields no per-kg figure.
    _KG_PER_UNIT = {
        "kg": 1.0,
        "kilogram": 1.0,
        "kilograms": 1.0,
        "lb": 0.45359237,
        "lbs": 0.45359237,
        "pound": 0.45359237,
        "pounds": 0.45359237,
        # "t" is the SI symbol for the metric tonne, never the US short ton (review of back
        # #132; `carbon/utils/unit_converter.py` and `test_harvest_lot_identity` agree).
        "t": 1000.0,
        "ton": 907.18474,
        "tons": 907.18474,
        "tonne": 1000.0,
        "tonnes": 1000.0,
    }

    @classmethod
    def _production_amount_kg(cls, production) -> float:
        amount = float(getattr(production, "production_amount", 0) or 0)
        unit = str(getattr(production, "production_unit", "") or "").strip().lower()
        factor = cls._KG_PER_UNIT.get(unit)
        if amount <= 0 or factor is None:
            return 0.0
        return amount * factor

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

            # Recordkeeping review F-02 (2026-10-07): the figure a SHOPPER reads must count only
            # entries with a recorded basis. An `area_estimate` row is a per-hectare guess for an
            # activity whose fuel was never recorded (R8-04 retired it on every card, and this
            # total still carried it: 82 kg of the specimen's 12,294); a `no_factor_applied` row
            # is a 0 with no basis at all. The farmer's own dashboard keeps `total_emissions`;
            # every consumer field reads `recorded_*`.
            recorded_rows = carbon_entries.filter(type="emission", verification_status__in=self.RECORDED_BASIS_STATUSES)
            excluded_entry_count = carbon_entries.filter(type="emission").count() - recorded_rows.count()
            recorded_emissions = recorded_rows.aggregate(Sum("amount"))["amount__sum"] or 0

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
            #
            # TWO figures, deliberately. `total_co2_kg_per_kg` is NET (emissions minus
            # offsets) and stays that way: the farmer dashboard, reports and benchmarks
            # all read it and net is a legitimate business metric there.
            # `gross_co2_kg_per_kg` divides GROSS emissions by the same yield and is the
            # only one a CONSUMER surface may use. Offsets are bought, self-entered and
            # self-marked verified (`create_secure_carbon_offset`), so a public figure
            # derived from them is a self-created environmental benefit claim:
            # FTC 16 CFR 260.5 (offsets) / 260.4 (general benefit), and EU ECGT 2024/825
            # (live 2026-09-27) bans self-created sustainability labels outright.
            # NEVER point a consumer-facing field at the net figure.
            total_co2_kg_per_kg = 0.0
            gross_co2_kg_per_kg = 0.0
            recorded_co2_kg_per_kg = 0.0
            try:
                first_entry = carbon_entries.select_related("production").first()
                if first_entry and first_entry.production:
                    # Per KILOGRAM of product, so the season's amount is converted from its
                    # recorded unit. Until the recordkeeping review (F-02, 2026-10-07) the figure
                    # divided by the raw amount: a 349,000 lb onion season read as 349,000 kg
                    # and the shopper's "per kg" number was 2.2 times too low. A unit that is not
                    # a mass (boxes, bins, units, bushels) gives no per-kg figure at all.
                    production_amount = self._production_amount_kg(first_entry.production)
                    if production_amount > 0:
                        total_co2_kg_per_kg = net_emissions / production_amount
                        gross_co2_kg_per_kg = float(total_emissions) / production_amount
                        recorded_co2_kg_per_kg = float(recorded_emissions) / production_amount
                    else:
                        # No production amount recorded — cannot compute per-kg
                        total_co2_kg_per_kg = 0.0
                        gross_co2_kg_per_kg = 0.0
                        recorded_co2_kg_per_kg = 0.0
            except Exception:
                total_co2_kg_per_kg = 0.0
                gross_co2_kg_per_kg = 0.0
                recorded_co2_kg_per_kg = 0.0

            return {
                "total_co2_kg_per_kg": total_co2_kg_per_kg,
                "gross_co2_kg_per_kg": gross_co2_kg_per_kg,
                # The consumer figures: gross, and only entries with a recorded basis.
                "recorded_emissions": float(recorded_emissions),
                "recorded_co2_kg_per_kg": recorded_co2_kg_per_kg,
                "excluded_entry_count": excluded_entry_count,
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
