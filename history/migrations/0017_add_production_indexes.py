"""
Production Database Indexes for History Models
Optimizes queries for production history and event data

Note: Uses atomic=False to allow CONCURRENT index creation outside of transactions
"""

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # Disable atomic transaction for concurrent index creation

    dependencies = [
        ('history', '0016_consumer_models'),
    ]

    operations = [
        # History Performance Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_parcel_start_date_idx ON history_history (parcel_id, start_date);",
            reverse_sql="DROP INDEX IF EXISTS history_history_parcel_start_date_idx;"
        ),
        

        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_type_start_date_idx ON history_history (type, start_date);",
            reverse_sql="DROP INDEX IF EXISTS history_history_type_start_date_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_published_idx ON history_history (published);",
            reverse_sql="DROP INDEX IF EXISTS history_history_published_idx;"
        ),
        

        
        # Chemical Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_chemicalevent_history_chemical_idx ON history_chemicalevent (history_id, chemical_name);",
            reverse_sql="DROP INDEX IF EXISTS history_chemicalevent_history_chemical_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_chemicalevent_application_method_idx ON history_chemicalevent (application_method);",
            reverse_sql="DROP INDEX IF EXISTS history_chemicalevent_application_method_idx;"
        ),
        
        # General Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_generalevent_history_activity_idx ON history_generalevent (history_id, activity_type);",
            reverse_sql="DROP INDEX IF EXISTS history_generalevent_history_activity_idx;"
        ),
        
        # Fertilizer Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_fertilizerevent_history_fertilizer_idx ON history_fertilizerevent (history_id, fertilizer_name);",
            reverse_sql="DROP INDEX IF EXISTS history_fertilizerevent_history_fertilizer_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_fertilizerevent_application_method_idx ON history_fertilizerevent (application_method);",
            reverse_sql="DROP INDEX IF EXISTS history_fertilizerevent_application_method_idx;"
        ),
        
        # Weather Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_weatherevent_history_condition_idx ON history_weatherevent (history_id, weather_condition);",
            reverse_sql="DROP INDEX IF EXISTS history_weatherevent_history_condition_idx;"
        ),
        
        # Soil Management Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_soilmanagementevent_history_practice_idx ON history_soilmanagementevent (history_id, practice_type);",
            reverse_sql="DROP INDEX IF EXISTS history_soilmanagementevent_history_practice_idx;"
        ),
        
        # Pest Management Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_pestmanagementevent_history_strategy_idx ON history_pestmanagementevent (history_id, management_strategy);",
            reverse_sql="DROP INDEX IF EXISTS history_pestmanagementevent_history_strategy_idx;"
        ),
        
        # Harvest Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_harvestevent_history_method_idx ON history_harvestevent (history_id, harvest_method);",
            reverse_sql="DROP INDEX IF EXISTS history_harvestevent_history_method_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_harvestevent_yield_idx ON history_harvestevent (yield_amount);",
            reverse_sql="DROP INDEX IF EXISTS history_harvestevent_yield_idx;"
        ),
        
        # Composite indexes for complex queries
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_parcel_start_date_type_idx ON history_history (parcel_id, start_date, type);",
            reverse_sql="DROP INDEX IF EXISTS history_history_parcel_start_date_type_idx;"
        ),
        

        
        # Partial indexes for published records only
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_published_only_parcel_start_date_idx ON history_history (parcel_id, start_date) WHERE published = true;",
            reverse_sql="DROP INDEX IF EXISTS history_history_published_only_parcel_start_date_idx;",
            state_operations=[],
        ),
        
        # Date range indexes for analytics
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_start_date_month_idx ON history_history (date_trunc('month', start_date));",
            reverse_sql="DROP INDEX IF EXISTS history_history_start_date_month_idx;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_start_date_year_idx ON history_history (date_trunc('year', start_date));",
            reverse_sql="DROP INDEX IF EXISTS history_history_start_date_year_idx;",
            state_operations=[],
        ),
        
        # Full-text search indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_notes_gin_idx ON history_history USING gin(to_tsvector('english', coalesce(notes, '')));",
            reverse_sql="DROP INDEX IF EXISTS history_history_notes_gin_idx;",
            state_operations=[],
        ),
        
        # Consumer model indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_consumerreview_production_rating_idx ON history_consumerreview (production_history_id, rating);",
            reverse_sql="DROP INDEX IF EXISTS history_consumerreview_production_rating_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_consumerfavorite_user_production_idx ON history_consumerfavorite (user_id, production_history_id);",
            reverse_sql="DROP INDEX IF EXISTS history_consumerfavorite_user_production_idx;"
        ),
        
        # Sustainability metrics indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_sustainability_score_idx ON history_history (sustainability_score) WHERE sustainability_score IS NOT NULL;",
            reverse_sql="DROP INDEX IF EXISTS history_history_sustainability_score_idx;",
            state_operations=[],
        ),
    ]