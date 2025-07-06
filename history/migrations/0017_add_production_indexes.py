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
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_chemicalevent_history_chemical_idx ON history_chemicalevent (history_id, commercial_name);",
            reverse_sql="DROP INDEX IF EXISTS history_chemicalevent_history_chemical_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_chemicalevent_application_method_idx ON history_chemicalevent (way_of_application);",
            reverse_sql="DROP INDEX IF EXISTS history_chemicalevent_application_method_idx;"
        ),
        
        # General Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_generalevent_history_activity_idx ON history_generalevent (history_id, name);",
            reverse_sql="DROP INDEX IF EXISTS history_generalevent_history_activity_idx;"
        ),
        
        # Note: FertilizerEvent model doesn't exist - removed indexes
        
        # Weather Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_weatherevent_history_condition_idx ON history_weatherevent (history_id, type);",
            reverse_sql="DROP INDEX IF EXISTS history_weatherevent_history_condition_idx;"
        ),
        
        # Soil Management Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_soilmanagementevent_history_practice_idx ON history_soilmanagementevent (history_id, type);",
            reverse_sql="DROP INDEX IF EXISTS history_soilmanagementevent_history_practice_idx;"
        ),
        
        # Pest Management Event Indexes
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_pestmanagementevent_history_strategy_idx ON history_pestmanagementevent (history_id, ipm_strategy);",
            reverse_sql="DROP INDEX IF EXISTS history_pestmanagementevent_history_strategy_idx;"
        ),
        
        # Note: HarvestEvent model doesn't exist - removed indexes
        
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
        
        # Date range indexes for analytics - simplified to avoid IMMUTABLE function issues
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_start_date_btree_idx ON history_history (start_date);",
            reverse_sql="DROP INDEX IF EXISTS history_history_start_date_btree_idx;",
            state_operations=[],
        ),
        
        # Full-text search indexes - removed as notes field doesn't exist
        # Future: Add when notes field is added to History model
        
        # Consumer model indexes - using correct table names from 0016_consumer_models
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_userfavorite_user_production_idx ON history_userfavorite (user_id, production_id);",
            reverse_sql="DROP INDEX IF EXISTS history_userfavorite_user_production_idx;"
        ),
        
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_userlocalrecommendation_user_establishment_idx ON history_userlocalrecommendation (user_id, establishment_id);",
            reverse_sql="DROP INDEX IF EXISTS history_userlocalrecommendation_user_establishment_idx;"
        ),
        
        # Note: sustainability_score field doesn't exist - removed index
    ]