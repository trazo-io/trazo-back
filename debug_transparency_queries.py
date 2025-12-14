#!/usr/bin/env python
"""
Detailed query debugging for transparency API.
Shows exact SQL queries being executed.
"""
import os
import sys
import django
from django.test.utils import CaptureQueriesContext
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
sys.path.insert(0, '/Users/oscarmunoz/dev/trazo/trazo-back')
django.setup()

from django.test import RequestFactory
from history.transparency_views import production_transparency_detail
from history.models import History

def analyze_queries():
    """Analyze which queries are being executed."""

    production = History.objects.filter(published=True).first()
    if not production:
        print("❌ No published productions found")
        return

    production_id = production.id
    print(f"Analyzing production ID: {production_id}\n")

    factory = RequestFactory()
    request = factory.get(f'/api/transparency/{production_id}/')

    with CaptureQueriesContext(connection) as context:
        response = production_transparency_detail(request, production_id)

    # Group queries by pattern
    query_patterns = {}
    duplicate_queries = {}

    for i, query in enumerate(context.captured_queries):
        sql = query['sql']

        # Detect duplicate queries
        if sql in duplicate_queries:
            duplicate_queries[sql] += 1
        else:
            duplicate_queries[sql] = 1

        # Extract pattern (first 100 chars)
        pattern = sql[:100]
        if pattern in query_patterns:
            query_patterns[pattern] += 1
        else:
            query_patterns[pattern] = 1

    print(f"Total Queries: {len(context.captured_queries)}")
    print()

    # Show top duplicate queries
    print("Top 10 Most Repeated Queries:")
    sorted_queries = sorted(duplicate_queries.items(), key=lambda x: -x[1])
    for sql, count in sorted_queries[:10]:
        if count > 1:
            print(f"  [{count}x] {sql[:120]}...")
    print()

    # Show query patterns
    print("Top Query Patterns:")
    for pattern, count in sorted(query_patterns.items(), key=lambda x: -x[1])[:10]:
        print(f"  [{count}x] {pattern[:100]}...")
    print()

    # Check if prefetch is actually being used
    print("Checking Prefetch Usage:")
    prefetch_queries = [q for q in context.captured_queries if 'history_history' in q['sql'] and 'event' in q['sql'].lower()]
    print(f"  Event-related queries: {len(prefetch_queries)}")

    image_queries = [q for q in context.captured_queries if 'image' in q['sql'].lower()]
    print(f"  Image queries: {len(image_queries)}")

    gallery_queries = [q for q in context.captured_queries if 'gallery' in q['sql'].lower()]
    print(f"  Gallery queries: {len(gallery_queries)}")

if __name__ == "__main__":
    analyze_queries()
