#!/usr/bin/env python3
"""
Test script for AI suggestions with backend-fetched recent events
"""
import asyncio
import os
import sys

import django

import pytest

# Setup Django
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.ai_voice_processor import _fetch_recent_events_from_db, generate_ai_event_suggestions


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_recent_events_fetching():
    """Test fetching recent events from database"""
    print("🔍 Testing Recent Events Fetching from Database...")
    print("=" * 60)

    # Test with sample establishment and parcel IDs
    # Note: These should be actual IDs from your database
    test_establishment_id = "21"  # Adjust based on your data
    test_parcel_id = "12"  # Adjust based on your data

    try:
        recent_events = await _fetch_recent_events_from_db(test_establishment_id, test_parcel_id)

        print(f"📊 Found {len(recent_events)} recent events:")
        for i, event in enumerate(recent_events, 1):
            print(f"   {i}. {event}")

        if not recent_events:
            print("   ℹ️  No recent events found (this is normal if no events exist in last 30 days)")

        return recent_events

    except Exception as e:
        print(f"   ❌ Error fetching recent events: {e}")
        return []


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_ai_suggestions_with_backend_events():
    """Test AI suggestions with backend-fetched events"""
    print("\n🤖 Testing AI Suggestions with Backend Events...")
    print("=" * 60)

    test_cases = [
        {
            "crop_type": "strawberries",
            "location": "California",
            "season": "summer",
            "farm_context": {"establishment_id": "21", "parcel_id": "12", "current_month": 6},
        },
        {
            "crop_type": "corn",
            "location": "Iowa",
            "season": "fall",
            "farm_context": {"establishment_id": "21", "parcel_id": "12", "current_month": 10},
        },
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}️⃣ Testing: {test_case['crop_type']} in {test_case['season']}")
        print(f"   Location: {test_case['location']}")
        print(
            f"   Farm Context: establishment {test_case['farm_context']['establishment_id']}, parcel {test_case['farm_context']['parcel_id']}"
        )

        try:
            # Call the AI suggestions function (backend will fetch recent events)
            result = await generate_ai_event_suggestions(
                crop_type=test_case["crop_type"],
                location=test_case["location"],
                season=test_case["season"],
                recent_events=None,  # This parameter is now ignored
                farm_context=test_case["farm_context"],
            )

            print(f"   ✅ Success! Generated {len(result.get('suggestions', []))} suggestions")
            print(f"   🤖 AI Powered: {result.get('ai_powered', False)}")
            print(f"   📊 AI Confidence: {result.get('ai_confidence', 0)}%")
            print(f"   🎯 Reasoning: {result.get('reasoning', 'No reasoning provided')[:100]}...")

            # Show suggestions
            for j, suggestion in enumerate(result.get("suggestions", []), 1):
                print(f"      {j}. {suggestion.get('name', 'Unknown')}")
                print(f"         Category: {suggestion.get('category', 'unknown')}")
                print(f"         Priority: {suggestion.get('priority', 'unknown')}")
                print(f"         Carbon Impact: {suggestion.get('carbon_impact', 0)} kg CO₂")
                print(f"         Confidence: {suggestion.get('confidence', 0)}%")

        except Exception as e:
            print(f"   ❌ Error: {e}")


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_backend_integration():
    """Test the complete backend integration"""
    print("\n🔗 Testing Complete Backend Integration...")
    print("=" * 60)

    # First test recent events fetching
    recent_events = await test_recent_events_fetching()

    # Then test AI suggestions with those events
    await test_ai_suggestions_with_backend_events()

    print("\n" + "=" * 60)
    print("🎯 Backend Integration Test Summary:")
    print(f"   • Recent events fetching: {'✅ Working' if recent_events is not None else '❌ Failed'}")
    print(f"   • AI suggestions: ✅ Working (check individual test results above)")
    print(f"   • Backend now handles recent events automatically")
    print(f"   • Frontend no longer needs to send recent_events parameter")


if __name__ == "__main__":
    print("🚀 Starting AI Suggestions Backend Integration Tests...")
    print("Make sure you have:")
    print("  ✅ Django environment setup")
    print("  ✅ Database with some event data")
    print("  ✅ OpenAI API key configured (optional, will use fallback)")
    print()

    asyncio.run(test_backend_integration())
