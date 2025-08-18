# Generated migration for Trazo 2025 Carbon Transparency Enhancement
# Phase 1: Foundation & Data Architecture

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('carbon', '0027_database_performance_optimizations'),
    ]

    operations = [
        # Add enhanced carbon entry fields for better transparency tracking
        migrations.AddField(
            model_name='carbonentry',
            name='explanation_text',
            field=models.TextField(
                blank=True,
                help_text='Consumer-friendly explanation of this carbon entry'
            ),
        ),
        migrations.AddField(
            model_name='carbonentry',
            name='confidence_level',
            field=models.CharField(
                max_length=10,
                choices=[
                    ('high', 'High Confidence (>90%)'),
                    ('medium', 'Medium Confidence (70-90%)'),
                    ('low', 'Low Confidence (<70%)'),
                ],
                default='medium',
                help_text='Confidence level in this carbon calculation'
            ),
        ),
        migrations.AddField(
            model_name='carbonentry',
            name='calculation_details',
            field=models.JSONField(
                default=dict,
                help_text='Detailed calculation methodology and factors used'
            ),
        ),
        migrations.AddField(
            model_name='carbonentry',
            name='improvement_potential',
            field=models.FloatField(
                default=0.0,
                help_text='Potential CO2e reduction through improvements'
            ),
        ),
        migrations.AddField(
            model_name='carbonentry',
            name='benchmark_comparison',
            field=models.JSONField(
                default=dict,
                help_text='Comparison with industry and regional benchmarks'
            ),
        ),

        # Add enhanced carbon report fields for comprehensive reporting
        migrations.AddField(
            model_name='carbonreport',
            name='detailed_breakdown',
            field=models.JSONField(
                default=dict,
                help_text='Detailed breakdown of carbon sources and sinks'
            ),
        ),
        migrations.AddField(
            model_name='carbonreport',
            name='trend_analysis',
            field=models.JSONField(
                default=dict,
                help_text='Historical trend analysis and projections'
            ),
        ),
        migrations.AddField(
            model_name='carbonreport',
            name='improvement_tracking',
            field=models.JSONField(
                default=dict,
                help_text='Tracking of improvement initiatives and their impact'
            ),
        ),
        migrations.AddField(
            model_name='carbonreport',
            name='stakeholder_insights',
            field=models.JSONField(
                default=dict,
                help_text='Insights for different stakeholders (farmers, consumers, regulators)'
            ),
        ),

        # Add new model for Consumer Trust Metrics
        migrations.CreateModel(
            name='ConsumerTrustMetric',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('production', models.OneToOneField(
                    on_delete=models.CASCADE,
                    related_name='consumer_trust_metric',
                    to='history.History',
                    help_text='Production this metric applies to'
                )),
                ('overall_trust_score', models.FloatField(
                    default=0.0,
                    validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(100.0)],
                    help_text='Overall consumer trust score (0-100)'
                )),
                ('data_completeness_score', models.FloatField(
                    default=0.0,
                    validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(100.0)],
                    help_text='Data completeness score (0-100)'
                )),
                ('verification_score', models.FloatField(
                    default=0.0,
                    validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(100.0)],
                    help_text='Third-party verification score (0-100)'
                )),
                ('transparency_score', models.FloatField(
                    default=0.0,
                    validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(100.0)],
                    help_text='Information transparency score (0-100)'
                )),
                ('consistency_score', models.FloatField(
                    default=0.0,
                    validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(100.0)],
                    help_text='Data consistency over time score (0-100)'
                )),
                ('engagement_metrics', models.JSONField(
                    default=dict,
                    help_text='Consumer engagement metrics and patterns'
                )),
                ('trust_factors', models.JSONField(
                    default=dict,
                    help_text='Factors contributing to trust score'
                )),
                ('improvement_areas', models.JSONField(
                    default=list,
                    help_text='Areas where trust can be improved'
                )),
                ('last_calculated', models.DateTimeField(
                    auto_now=True,
                    help_text='Last time trust metrics were calculated'
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'carbon_consumer_trust_metric',
                'verbose_name': 'Consumer Trust Metric',
                'verbose_name_plural': 'Consumer Trust Metrics',
            },
        ),

        # Add Carbon Intelligence model for AI-powered insights
        migrations.CreateModel(
            name='CarbonIntelligence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('production', models.OneToOneField(
                    on_delete=models.CASCADE,
                    related_name='carbon_intelligence',
                    to='history.History',
                    help_text='Production this intelligence applies to'
                )),
                ('ai_insights', models.JSONField(
                    default=dict,
                    help_text='AI-generated insights about carbon performance'
                )),
                ('pattern_analysis', models.JSONField(
                    default=dict,
                    help_text='Analysis of carbon patterns and trends'
                )),
                ('predictive_metrics', models.JSONField(
                    default=dict,
                    help_text='Predictive analytics for future carbon performance'
                )),
                ('optimization_suggestions', models.JSONField(
                    default=list,
                    help_text='AI-generated optimization suggestions'
                )),
                ('risk_assessment', models.JSONField(
                    default=dict,
                    help_text='Carbon risk assessment and mitigation strategies'
                )),
                ('benchmarking_analysis', models.JSONField(
                    default=dict,
                    help_text='Intelligent benchmarking against similar operations'
                )),
                ('confidence_score', models.FloatField(
                    default=0.0,
                    validators=[django.core.validators.MinValueValidator(0.0), django.core.validators.MaxValueValidator(100.0)],
                    help_text='Confidence in AI analysis (0-100)'
                )),
                ('analysis_date', models.DateTimeField(
                    auto_now=True,
                    help_text='Date of latest AI analysis'
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'carbon_intelligence',
                'verbose_name': 'Carbon Intelligence',
                'verbose_name_plural': 'Carbon Intelligence Records',
            },
        ),

        # Add index optimizations for performance
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_carbonentry_confidence ON carbon_carbonentry(confidence_level);",
            reverse_sql="DROP INDEX IF EXISTS idx_carbonentry_confidence;"
        ),
    ]