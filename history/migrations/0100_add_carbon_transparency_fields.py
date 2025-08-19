# Generated migration for Trazo 2025 Carbon Transparency Enhancement
# Phase 1: Foundation & Data Architecture - History Model Enhancement

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('history', '0020_add_unique_visitors'),
    ]

    operations = [
        # Add carbon grade and transparency fields to History model (Production)
        migrations.AddField(
            model_name='history',
            name='carbon_grade',
            field=models.CharField(
                max_length=2,
                choices=[
                    ('A+', 'A+ Grade (Exceptional)'),
                    ('A', 'A Grade (Excellent)'),
                    ('A-', 'A- Grade (Very Good)'),
                    ('B+', 'B+ Grade (Good)'),
                    ('B', 'B Grade (Above Average)'),
                    ('B-', 'B- Grade (Average)'),
                    ('C+', 'C+ Grade (Below Average)'),
                    ('C', 'C Grade (Poor)'),
                    ('C-', 'C- Grade (Very Poor)'),
                    ('D+', 'D+ Grade (Failing)'),
                    ('D', 'D Grade (Critical)'),
                    ('F', 'F Grade (Unacceptable)'),
                ],
                blank=True,
                null=True,
                help_text='A-F carbon performance grade for consumer understanding'
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='industry_comparison',
            field=models.JSONField(
                default=dict,
                help_text='Comparison with industry benchmarks and percentiles'
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='equivalency_metrics',
            field=models.JSONField(
                default=dict,
                help_text='Consumer-friendly equivalency metrics (miles driven, trees planted, etc.)'
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='trust_indicators',
            field=models.JSONField(
                default=dict,
                help_text='Trust building indicators (verification status, data quality, etc.)'
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='carbon_journey_data',
            field=models.JSONField(
                default=dict,
                help_text='Timeline and journey data for carbon story visualization'
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='improvement_recommendations',
            field=models.JSONField(
                default=list,
                help_text='AI-generated recommendations for carbon footprint reduction'
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='certification_status',
            field=models.JSONField(
                default=dict,
                help_text='Certification and compliance status information'
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='consumer_insights',
            field=models.JSONField(
                default=dict,
                help_text='Consumer-focused insights and explanations'
            ),
        ),
        
        # Add database indexes for performance optimization
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_history_carbon_grade ON history_history(carbon_grade);",
            reverse_sql="DROP INDEX IF EXISTS idx_history_carbon_grade;"
        ),
    ]