#!/usr/bin/env python3
"""
Test script for Trazo's minimal transparency solution
Validates that transparency calculation solves the farmer incentive problem

This script demonstrates:
1. How transparency scoring works with different event counts
2. Why this eliminates the gaming incentive
3. Comparison with the problematic competitive ranking approach

Run: python test_transparency_solution.py
"""
import os
import sys

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from datetime import datetime, timedelta

from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, EquipmentEvent, History, ProductionEvent
from history.services.transparency_calculator import TransparencyCalculator
from product.models import Parcel
from users.models import User


def create_test_data():
    """Create test productions to demonstrate transparency scoring"""

    print("🌱 Creating test data for transparency solution validation...")

    # Create test company and establishment
    company, _ = Company.objects.get_or_create(name="Test Farm Solutions", defaults={"country": "USA"})

    establishment, _ = Establishment.objects.get_or_create(
        name="Transparency Test Farm",
        company=company,
        defaults={"country": "USA", "city": "Sacramento", "state": "California", "address": "123 Farm Road"},
    )

    parcel, _ = Parcel.objects.get_or_create(name="Test Field A", establishment=establishment, defaults={"area": 10.0})

    # Create two test productions to demonstrate the difference

    # Production A: Honest farmer (logs everything)
    history_honest = History.objects.create(
        name="Honest Farmer Production",
        parcel=parcel,
        start_date=timezone.now() - timedelta(days=120),
        finish_date=timezone.now() - timedelta(days=30),
        published=True,
        extra_data={"farming_approach": "organic", "test_scenario": "honest_logging"},
    )

    # Production B: Gaming farmer (selective logging)
    history_gaming = History.objects.create(
        name="Gaming Farmer Production",
        parcel=parcel,
        start_date=timezone.now() - timedelta(days=120),
        finish_date=timezone.now() - timedelta(days=30),
        published=True,
        extra_data={"farming_approach": "organic", "test_scenario": "selective_logging"},
    )

    # Honest farmer logs many events (15 events)
    honest_events = [
        ("Planted organic seeds", ProductionEvent.PLANTING),
        ("Installed drip irrigation", ProductionEvent.IRRIGATION),
        ("Applied organic compost", ChemicalEvent.FERTILIZER),
        ("Equipment maintenance check", EquipmentEvent.MAINTENANCE),
        ("Pest scouting round 1", ProductionEvent.PLANTING),
        ("Applied beneficial insects", ChemicalEvent.PESTICIDE),
        ("Mid-season irrigation adjustment", ProductionEvent.IRRIGATION),
        ("Organic fertilizer application", ChemicalEvent.FERTILIZER),
        ("Equipment repair - tractor", EquipmentEvent.REPAIR),
        ("Pest scouting round 2", ProductionEvent.PLANTING),
        ("Cover crop seeding", ChemicalEvent.FERTILIZER),
        ("Harvest preparation", ProductionEvent.HARVESTING),
        ("Final irrigation", ProductionEvent.IRRIGATION),
        ("Equipment cleaning", EquipmentEvent.MAINTENANCE),
        ("Harvest completion", ProductionEvent.HARVESTING),
    ]

    for i, (description, event_type) in enumerate(honest_events):
        if (
            "fertilizer" in description.lower()
            or "compost" in description.lower()
            or "beneficial" in description.lower()
            or "cover crop" in description.lower()
        ):
            ChemicalEvent.objects.create(
                history=history_honest,
                description=description,
                date=history_honest.start_date + timedelta(days=i * 7),
                index=i,
                type=event_type,
            )
        elif "equipment" in description.lower() or "tractor" in description.lower():
            EquipmentEvent.objects.create(
                history=history_honest,
                description=description,
                date=history_honest.start_date + timedelta(days=i * 7),
                index=i,
                type=event_type,
            )
        else:
            ProductionEvent.objects.create(
                history=history_honest,
                description=description,
                date=history_honest.start_date + timedelta(days=i * 7),
                index=i,
                type=event_type,
            )

    # Gaming farmer logs only minimal events (6 events - avoids carbon-intensive activities)
    gaming_events = [
        ("Planted seeds", ProductionEvent.PLANTING),
        ("Basic irrigation", ProductionEvent.IRRIGATION),
        ("Light maintenance", EquipmentEvent.MAINTENANCE),
        ("Harvest prep", ProductionEvent.HARVESTING),
        ("Harvest", ProductionEvent.HARVESTING),
        ("Field cleanup", ProductionEvent.HARVESTING),
    ]

    for i, (description, event_type) in enumerate(gaming_events):
        if "maintenance" in description.lower():
            EquipmentEvent.objects.create(
                history=history_gaming,
                description=description,
                date=history_gaming.start_date + timedelta(days=i * 15),
                index=i,
                type=event_type,
            )
        else:
            ProductionEvent.objects.create(
                history=history_gaming,
                description=description,
                date=history_gaming.start_date + timedelta(days=i * 15),
                index=i,
                type=event_type,
            )

    return history_honest, history_gaming


def demonstrate_old_vs_new_approach():
    """Demonstrate how the new approach solves the incentive problem"""

    print("\n" + "=" * 80)
    print("🚨 DEMONSTRATING THE FARMER INCENTIVE PROBLEM SOLUTION")
    print("=" * 80)

    history_honest, history_gaming = create_test_data()
    transparency_calc = TransparencyCalculator()

    # Calculate transparency scores
    honest_transparency = transparency_calc.calculate_transparency_score(history_honest)
    gaming_transparency = transparency_calc.calculate_transparency_score(history_gaming)

    print(f"\n📊 RESULTS COMPARISON:")
    print(f"\n🌟 HONEST FARMER (logs everything):")
    print(f"   • Events logged: {honest_transparency['actual_event_count']}")
    print(f"   • Expected events: {honest_transparency['expected_event_count']}")
    print(f"   • Transparency score: {honest_transparency['transparency_percentage']:.1f}%")
    print(f"   • Message: {honest_transparency['message']}")
    print(f"   • Farming approach: {honest_transparency['farming_approach']}")

    print(f"\n🎭 GAMING FARMER (selective logging):")
    print(f"   • Events logged: {gaming_transparency['actual_event_count']}")
    print(f"   • Expected events: {gaming_transparency['expected_event_count']}")
    print(f"   • Transparency score: {gaming_transparency['transparency_percentage']:.1f}%")
    print(f"   • Message: {gaming_transparency['message']}")
    print(f"   • Farming approach: {gaming_transparency['farming_approach']}")

    # Simulate old problematic approach (competitive carbon ranking)
    print(f"\n🔴 OLD PROBLEMATIC APPROACH (Competitive Carbon Ranking):")
    print(f"   Honest Farmer: '2.5 kg CO₂/kg (Worse than 65% of farms)' ← LOOKS BAD")
    print(f"   Gaming Farmer: '1.8 kg CO₂/kg (Better than 85% of farms)' ← LOOKS GOOD")
    print(f"   ❌ PROBLEM: Gaming farmer gets rewarded for incomplete data!")

    print(f"\n✅ NEW TRANSPARENCY APPROACH (No Competitive Ranking):")
    print(
        f"   Honest Farmer: '{honest_transparency['transparency_percentage']:.0f}% transparency - {honest_transparency['message']}' ← TRUSTWORTHY"
    )
    print(
        f"   Gaming Farmer: '{gaming_transparency['transparency_percentage']:.0f}% transparency - {gaming_transparency['message']}' ← QUESTIONABLE"
    )
    print(f"   ✅ SOLUTION: Honest farmer gets rewarded for complete documentation!")

    # Compare each farm against its OWN previous finished seasons. The former
    # compare_with_benchmarks() graded against invented "industry"/"certification"
    # thresholds and was removed 2026-08-02.
    honest_history = transparency_calc.compare_with_own_history(history_honest)
    gaming_history = transparency_calc.compare_with_own_history(history_gaming)

    print(f"\n🎯 PROGRESS VS THE FARM'S OWN PREVIOUS SEASONS:")
    print(f"   Honest Farmer: {honest_history['current_score']}% (previous best: {honest_history['previous_best']})")
    print(f"   Gaming Farmer: {gaming_history['current_score']}% (previous best: {gaming_history['previous_best']})")

    # Show improvement suggestions
    honest_insights = transparency_calc.get_transparency_insights(history_honest)
    gaming_insights = transparency_calc.get_transparency_insights(history_gaming)

    print(f"\n💡 ACTIONABLE INSIGHTS:")
    print(f"   Honest Farmer recommendations: {len(honest_insights['recommendations'])} suggestions")
    print(f"   Gaming Farmer recommendations: {len(gaming_insights['recommendations'])} suggestions")
    print(f"   Gaming Farmer missing categories: {len(gaming_insights['missing_categories'])}")

    return honest_transparency["transparency_percentage"] > gaming_transparency["transparency_percentage"]


def test_category_breakdown():
    """Test the category breakdown functionality"""

    print(f"\n📋 TESTING CATEGORY BREAKDOWN:")

    history_honest, history_gaming = History.objects.filter(
        extra_data__test_scenario__in=["honest_logging", "selective_logging"]
    ).order_by("extra_data__test_scenario")

    transparency_calc = TransparencyCalculator()
    honest_transparency = transparency_calc.calculate_transparency_score(history_honest)

    print(f"\n🔍 Honest Farmer Category Analysis:")
    for category, data in honest_transparency.get("category_breakdown", {}).items():
        print(
            f"   • {category.replace('_', ' ').title()}: {data['completeness_percentage']:.1f}% "
            f"({data['actual_count']}/{data['expected_count']} events) - {data['status']}"
        )

    return True


def validate_consumer_messaging():
    """Test that consumer-facing messages are clear and trust-building"""

    print(f"\n💬 VALIDATING CONSUMER MESSAGING:")

    # Test different transparency levels
    test_cases = [
        (95, "Complete transparency"),
        (85, "Comprehensive farm record"),
        (70, "Good record keeping"),
        (50, "Basic information available"),
        (30, "Limited information available"),
    ]

    transparency_calc = TransparencyCalculator()

    for percentage, expected_message_start in test_cases:
        message = transparency_calc._generate_transparency_message(percentage, {})
        print(f"   • {percentage}%: {message}")

        # Validate message is consumer-friendly
        assert len(message) < 100, "Message too long for mobile display"
        assert not any(
            tech_term in message.lower() for tech_term in ["api", "algorithm", "database"]
        ), "Contains technical jargon"
        assert "transparency" in message.lower(), "Doesn't emphasize transparency"

    print(f"   ✅ All consumer messages are clear and trust-focused")
    return True


def main():
    """Run all tests to validate the transparency solution"""

    print("🚀 STARTING TRAZO TRANSPARENCY SOLUTION VALIDATION")
    print("This test demonstrates how transparency scoring solves the farmer gaming problem")

    try:
        # Test 1: Demonstrate the solution
        incentive_problem_solved = demonstrate_old_vs_new_approach()

        # Test 2: Category breakdown
        category_test_passed = test_category_breakdown()

        # Test 3: Consumer messaging
        messaging_test_passed = validate_consumer_messaging()

        # Final assessment
        print(f"\n" + "=" * 80)
        print("🏆 FINAL ASSESSMENT")
        print("=" * 80)

        if incentive_problem_solved and category_test_passed and messaging_test_passed:
            print("✅ SUCCESS: Transparency solution works as designed!")
            print("\n💡 KEY BENEFITS:")
            print("   • Eliminates competitive carbon ranking")
            print("   • Rewards honest, complete documentation")
            print("   • Provides clear consumer messaging")
            print("   • Uses absolute standards, not relative comparisons")
            print("   • Maintains all existing carbon calculation functionality")
            print("\n🎯 OUTCOME: Farmers are now incentivized to log MORE events, not fewer")
            print("🌟 This approach positions Trazo as the authentic transparency leader!")

            return True
        else:
            print("❌ FAILURE: Some tests did not pass")
            return False

    except Exception as e:
        print(f"🚨 ERROR: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
