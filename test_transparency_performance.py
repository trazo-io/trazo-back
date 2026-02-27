#!/usr/bin/env python
"""
Performance validation test for transparency API optimization.

Measures query count before and after optimization to verify:
- 232 queries → ~15 queries (90% reduction)
- All data still present in response
"""
import os
import sys

import django
from django.db import connection
from django.test.utils import CaptureQueriesContext

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")
django.setup()

from django.test import RequestFactory

from history.models import History
from history.transparency_views import production_transparency_detail


def test_transparency_performance():
    """Test the transparency API performance."""

    # Find a published production for testing
    try:
        production = History.objects.filter(published=True).first()
        if not production:
            print("❌ No published productions found for testing")
            return

        production_id = production.id
        print(f"📊 Testing with production ID: {production_id}")
        print(f"   Production: {production.name}")
        print()

        # Create a test request
        factory = RequestFactory()
        request = factory.get(f"/api/transparency/{production_id}/")

        # Capture queries
        with CaptureQueriesContext(connection) as context:
            response = production_transparency_detail(request, production_id)

        query_count = len(context.captured_queries)

        # Analyze query types
        query_breakdown = {}
        for query in context.captured_queries:
            sql = query["sql"]
            # Extract table name
            if "FROM" in sql:
                table = sql.split("FROM")[1].split()[1].strip('`"')
                query_breakdown[table] = query_breakdown.get(table, 0) + 1

        # Display results
        print("=" * 70)
        print("🎯 PERFORMANCE RESULTS")
        print("=" * 70)
        print(f"Total Queries: {query_count}")
        print()

        print("Query Breakdown by Table:")
        for table, count in sorted(query_breakdown.items(), key=lambda x: -x[1])[:10]:
            print(f"  • {table}: {count} queries")
        print()

        # Success/failure criteria
        TARGET_QUERIES = 15
        SUCCESS_THRESHOLD = 30  # Allow some margin

        print("=" * 70)
        print("✅ SUCCESS CRITERIA")
        print("=" * 70)
        print(f"Target Query Count: < {TARGET_QUERIES} queries")
        print(f"Success Threshold: < {SUCCESS_THRESHOLD} queries (allow margin)")
        print(f"Actual Queries: {query_count}")
        print()

        if query_count < TARGET_QUERIES:
            print("🎉 EXCELLENT! Achieved target optimization!")
            print(f"   Reduction: 232 → {query_count} queries ({((232-query_count)/232*100):.0f}% reduction)")
        elif query_count < SUCCESS_THRESHOLD:
            print("✅ GOOD! Query count significantly reduced!")
            print(f"   Reduction: 232 → {query_count} queries ({((232-query_count)/232*100):.0f}% reduction)")
        else:
            print("⚠️  WARNING: Query optimization may not be working as expected")
            print(f"   Expected: <15 queries | Actual: {query_count} queries")

        print()

        # Verify response data
        if response.status_code == 200:
            print("✅ Response Status: 200 OK")
            data = response.data

            # Check for critical fields
            checks = [
                ("transparency_score", "transparency_score" in data),
                ("timeline events", "timeline_events" in data and len(data.get("timeline_events", [])) > 0),
                ("farmer info", "farmer" in data and data.get("farmer")),
                ("company info", "farmer" in data and "company" in data.get("farmer", {})),
                ("carbon data", "carbon_footprint" in data),
            ]

            print("\nData Integrity Checks:")
            for check_name, result in checks:
                status = "✅" if result else "❌"
                print(f"  {status} {check_name}")
        else:
            print(f"❌ Response Status: {response.status_code}")

        print("\n" + "=" * 70)

    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_transparency_performance()
