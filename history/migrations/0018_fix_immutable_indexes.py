"""
Fix function-based indexes that require IMMUTABLE functions
"""

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # Disable atomic transaction for concurrent index creation

    dependencies = [
        ('history', '0017_add_production_indexes'),
    ]

    operations = [
        # Drop the problematic indexes that use non-immutable functions
        migrations.RunSQL(
            "DROP INDEX IF EXISTS history_history_start_date_month_idx;",
            reverse_sql=""
        ),
        
        migrations.RunSQL(
            "DROP INDEX IF EXISTS history_history_start_date_year_idx;",
            reverse_sql=""
        ),
        
        # Notes index was never created due to missing field
        # migrations.RunSQL(
        #     "DROP INDEX IF EXISTS history_history_notes_gin_idx;",
        #     reverse_sql=""
        # ),
        
        # Create replacement indexes without using date_trunc
        # Instead, we'll create indexes on the start_date directly
        # which can be used for date range queries
        migrations.RunSQL(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS history_history_start_date_btree_idx ON history_history (start_date);",
            reverse_sql="DROP INDEX IF EXISTS history_history_start_date_btree_idx;"
        ),
        
        # For text search, we'll skip notes index since field doesn't exist
        # Future: Add when notes field is added to History model
    ]