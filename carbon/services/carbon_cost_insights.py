"""
Carbon Cost Intelligence Service - Simplified

Provides lightweight cost intelligence focused ONLY on carbon-related insights.
Avoids complex farm management features to stay focused on carbon transparency mission.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List

from django.db.models import Avg, Sum
from django.utils import timezone

from carbon.models import CarbonEntry
from history.models import History  # Production is actually History model


class CarbonCostInsights:
    """Lightweight cost intelligence focused ONLY on carbon-related savings"""

    def __init__(self):
        self.carbon_credit_rate = Decimal("25.00")  # $25/ton average market rate

    def get_carbon_economics(self, production_id: int) -> Dict[str, Any]:
        """
        OPTIMIZED: Get simple carbon economics for a production without triggering USDA API calls.
        Uses cached carbon data from extra_data field instead of real-time calculations.

        NOTE: carbon_credit_potential HIDDEN from UI per transparency-first decision.
        Data retained in database for potential future B2B reports.
        """
        try:
            production = History.objects.get(id=production_id)

            # Basic efficiency insights without triggering calculations
            efficiency_tips = self.get_carbon_efficiency_tips_cached(production)

            # NEVER: NO PREMIUM PRICING ELIGIBILITY. Removed 2026-09-30 together with the two
            # methods that produced it. `.claude/rules/compliance.md` bans price and premium claims
            # by name: product outcomes are safe, a percentage premium is not. Trazo has no pricing
            # data, no buyer commitments and no users, so any number here was invented.
            #
            # What was here, for the record, because both are worth recognising if they reappear:
            #   * a 0-100 `score` from event counts mapped to a FOUR-RUNG ladder
            #     none / basic / sustainable / premium, which is the self-assigned tier ladder
            #     retired on 2026-09-02, rebuilt under a pricing name; and
            #   * `potential_premium` and `premium_percentage` strings, up to "25%", one of them
            #     keyed partly off `blockchain_verified`, a phrase compliance.md bans outright
            #     ("recorded", never "verified") on a feature whose flag is False.
            return {
                # carbon_credit_potential HIDDEN: B2B data, not exposed in UI
                "efficiency_tips": efficiency_tips,
                "next_actions": self.get_next_carbon_actions_cached(production),
                "generated_at": timezone.now().isoformat(),
                "data_source": "cached",  # Indicate this uses cached data
            }

        except History.DoesNotExist:
            return {"error": "Production not found"}
        except Exception as e:
            return {"error": str(e)}

    def calculate_carbon_credit_potential_cached(self, production: History, cached_data: Dict) -> Dict[str, Any]:
        """Calculate carbon credit potential using cached data to avoid USDA API calls"""
        try:
            # Use cached carbon score or calculate simple estimate
            carbon_score = cached_data.get("carbon_score", 75)  # Default to 75 if no cached data
            total_emissions = cached_data.get("total_emissions", 0)
            total_offsets = cached_data.get("total_offsets", 0)

            # Simple credit calculation
            net_emissions = total_emissions - total_offsets
            credit_potential = max(0, total_offsets - total_emissions) / 1000  # Convert to tons
            credit_value = credit_potential * float(self.carbon_credit_rate)

            return {
                "potential_credits_tons": round(credit_potential, 2),
                "estimated_value_usd": round(credit_value, 2),
                "carbon_score": carbon_score,
                "eligibility": "eligible" if credit_potential > 0 else "not_eligible",
                "data_source": "cached_summary",
            }
        except Exception:
            return {
                "potential_credits_tons": 0,
                "estimated_value_usd": 0,
                "carbon_score": 75,
                "eligibility": "unknown",
                "data_source": "fallback",
            }

    def get_carbon_efficiency_tips_cached(self, production: History) -> List[str]:
        """Get efficiency tips without triggering carbon calculations"""
        tips = [
            "Consider switching to precision fertilizer application to reduce nitrogen waste",
            "Implement cover crops to improve soil carbon sequestration",
            "Explore renewable energy options for irrigation and equipment",
        ]

        # Add production-specific tips based on basic attributes
        if production.is_outdoor:
            tips.append("Outdoor production allows for natural pest control - consider reducing pesticide use")

        return tips[:3]  # Return top 3 tips

    def get_next_carbon_actions_cached(self, production: History) -> List[str]:
        """Get next actions without triggering calculations"""
        actions = []

        if not production.published:
            actions.append("Publish production to enable carbon credit eligibility")

        # NEVER: the action here read "Enable blockchain verification for premium pricing", which
        # packs two banned phrases into one sentence shown to a farmer. compliance.md: say
        # "blockchain-recorded", never "verified", and make no premium-pricing claim at all. It also
        # told them to turn on a feature whose flag is False and whose add-on is withdrawn, keyed off
        # `extra_data["blockchain_transaction"]`, which under `mock_mode` is a fabricated hash.
        # Removed 2026-09-30 with the rest of the premium claim.

        actions.append("Schedule carbon footprint assessment for next production cycle")

        return actions[:3]

    def calculate_carbon_credit_potential(self, production: History) -> Dict[str, Any]:
        """Simple carbon credit revenue estimation"""
        try:
            # Get total carbon sequestered from production
            carbon_entries = CarbonEntry.objects.filter(production=production, type="offset")

            total_sequestered = carbon_entries.aggregate(total=Sum("co2_equivalent"))["total"] or Decimal("0")

            # Convert to tons (assuming co2_equivalent is in kg)
            tons_sequestered = total_sequestered / Decimal("1000")

            potential_revenue = tons_sequestered * self.carbon_credit_rate

            return {
                "tons_sequestered": float(tons_sequestered),
                "market_rate_per_ton": float(self.carbon_credit_rate),
                "potential_revenue": float(potential_revenue),
                "confidence": "medium",
                "verification_needed": tons_sequestered > 0,
                "next_steps": (
                    [
                        "Complete carbon verification process",
                        "Register with carbon credit marketplace",
                        "Maintain detailed carbon tracking records",
                    ]
                    if tons_sequestered > 0
                    else [
                        "Continue carbon tracking to build credit potential",
                        "Focus on carbon sequestration activities",
                    ]
                ),
            }

        except Exception as e:
            return {"error": str(e), "tons_sequestered": 0, "potential_revenue": 0}

    def get_carbon_efficiency_tips(self, production: History) -> List[Dict[str, Any]]:
        """Get efficiency tips focused only on carbon-heavy activities"""
        tips = []

        try:
            # Analyze fuel consumption events from carbon entries
            fuel_entries = CarbonEntry.objects.filter(production=production, source__category__icontains="fuel")

            if fuel_entries.exists():
                avg_fuel_per_event = fuel_entries.aggregate(avg=Avg("amount"))["avg"] or 0

                if avg_fuel_per_event > 50:  # Threshold for high fuel use (kg CO2e)
                    tips.append(
                        {
                            "category": "fuel_efficiency",
                            "title": "Optimize Fuel Usage",
                            "description": f"Average fuel emissions are {avg_fuel_per_event:.1f} kg CO2e per operation. Consider precision agriculture techniques.",
                            "potential_savings": "Reduce fuel costs by 15-25%",
                            "carbon_impact": "Lower CO2 emissions from machinery",
                            "priority": "high",
                        }
                    )

            # Analyze fertilizer usage
            fertilizer_entries = CarbonEntry.objects.filter(
                production=production, source__category__icontains="fertilizer"
            )

            if fertilizer_entries.exists():
                tips.append(
                    {
                        "category": "fertilizer_efficiency",
                        "title": "Optimize Fertilizer Application",
                        "description": "Consider soil testing and precision application to reduce fertilizer use.",
                        "potential_savings": "Reduce fertilizer costs by 10-20%",
                        "carbon_impact": "Lower N2O emissions from fertilizer",
                        "priority": "medium",
                    }
                )

            # Limit to max 2 tips to avoid overwhelming
            return tips[:2]

        except Exception as e:
            return [{"category": "error", "title": "Unable to analyze efficiency", "description": str(e)}]

    def get_next_carbon_actions(self, production: History) -> List[Dict[str, str]]:
        """Get max 2 simple next actions focused on carbon improvement"""
        actions = []

        try:
            # Check recent activity
            recent_entries = CarbonEntry.objects.filter(
                production=production, created_at__gte=timezone.now() - timedelta(days=30)
            ).count()

            if recent_entries == 0:
                actions.append(
                    {
                        "action": "Log Recent Activities",
                        "description": "Record any farm activities from the past month",
                        "impact": "Improves carbon tracking accuracy",
                    }
                )

            # Check for incomplete carbon tracking
            total_carbon_entries = CarbonEntry.objects.filter(production=production).count()

            if total_carbon_entries < 3:  # Minimum threshold for good tracking
                actions.append(
                    {
                        "action": "Calculate Carbon Impact",
                        "description": "Add more carbon tracking entries for better insights",
                        "impact": "Complete carbon footprint tracking",
                    }
                )

            # If no specific actions, suggest general improvement
            if not actions:
                actions.append(
                    {
                        "action": "Continue Carbon Tracking",
                        "description": "Keep logging activities to build carbon credit potential",
                        "impact": "Builds toward carbon credit eligibility",
                    }
                )

            return actions[:2]  # Max 2 actions

        except Exception as e:
            return [
                {
                    "action": "Review Carbon Data",
                    "description": "Check carbon tracking setup",
                    "impact": "Ensure accurate carbon calculations",
                }
            ]

    def get_establishment_carbon_summary(self, establishment_id: int) -> Dict[str, Any]:
        """Get carbon cost summary for entire establishment

        NOTE: carbon_credit_potential HIDDEN from UI per transparency-first decision.
        Data retained in database for potential future B2B reports.
        """
        try:
            from company.models import Establishment

            establishment = Establishment.objects.get(id=establishment_id)

            # Get all productions for this establishment
            productions = History.objects.filter(parcel__establishment=establishment)

            # Calculate basic carbon metrics (no credit data)
            total_sequestered = Decimal("0")
            for production in productions:
                carbon_data = self.calculate_carbon_credit_potential(production)
                if "tons_sequestered" in carbon_data:
                    total_sequestered += Decimal(str(carbon_data["tons_sequestered"]))

            return {
                "establishment_name": establishment.name,
                "total_productions": productions.count(),
                "total_carbon_sequestered_tons": float(total_sequestered),
                # carbon_credit_potential HIDDEN: B2B data, not exposed in UI
                "summary_date": timezone.now().isoformat(),
            }

        except Exception as e:
            return {"error": str(e)}
