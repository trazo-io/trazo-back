"""
Database Indexes for Trazo
Adds optimized indexes for common query patterns and performance improvement
Compatible with both PostgreSQL and SQLite
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('carbon', '0023_update_corrected_emission_factors'),
    ]

    operations = [
        # Core Carbon Entry Performance Indexes using Django's AddIndex operation
        migrations.AddIndex(
            model_name='carbonentry',
            index=models.Index(fields=['establishment', 'created_at'], name='carbon_carbonentry_establishment_date_idx'),
        ),
        
        migrations.AddIndex(
            model_name='carbonentry',
            index=models.Index(fields=['amount'], name='carbon_carbonentry_amount_idx'),
        ),
        
        migrations.AddIndex(
            model_name='carbonentry',
            index=models.Index(fields=['verification_status'], name='carbon_carbonentry_verification_status_idx'),
        ),
        
        migrations.AddIndex(
            model_name='carbonentry',
            index=models.Index(fields=['usda_verified'], name='carbon_carbonentry_usda_verified_idx'),
        ),
        
        # Carbon Source Performance Indexes
        migrations.AddIndex(
            model_name='carbonsource',
            index=models.Index(fields=['category', 'usda_verified'], name='carbon_carbonsource_category_verified_idx'),
        ),
        
        # Composite indexes for complex queries
        migrations.AddIndex(
            model_name='carbonentry',
            index=models.Index(fields=['establishment', 'created_at', 'amount'], name='carbon_carbonentry_est_date_amount_idx'),
        ),
        
        migrations.AddIndex(
            model_name='carbonsource',
            index=models.Index(fields=['category', 'default_emission_factor'], name='carbon_carbonsource_category_emission_idx'),
        ),
        
        # Indexes for data analytics and reporting
        migrations.AddIndex(
            model_name='carbonentry',
            index=models.Index(fields=['created_at'], name='carbon_carbonentry_created_at_idx'),
        ),
        
        # Note: SQLite doesn't support partial indexes with complex WHERE clauses like PostgreSQL
        # The scoring index is simplified for SQLite compatibility
        migrations.AddIndex(
            model_name='carbonentry',
            index=models.Index(fields=['establishment', 'amount', 'effective_amount'], name='carbon_carbonentry_scoring_idx'),
        ),
    ]