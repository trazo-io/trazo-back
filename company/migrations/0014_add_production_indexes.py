"""
Database Indexes for Company Models
Optimizes queries for company and establishment data
SQLite compatible version using Django's built-in operations
Only includes indexes for fields that actually exist in the models
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0013_increase_field_lengths_international'),
    ]

    operations = [
        # Company Performance Indexes (only using fields that exist)
        migrations.AddIndex(
            model_name='company',
            index=models.Index(fields=['is_active'], name='company_company_is_active_idx'),
        ),
        
        migrations.AddIndex(
            model_name='company',
            index=models.Index(fields=['country', 'state'], name='company_company_country_state_idx'),
        ),
        
        migrations.AddIndex(
            model_name='company',
            index=models.Index(fields=['name'], name='company_company_name_idx'),
        ),
        
        migrations.AddIndex(
            model_name='company',
            index=models.Index(fields=['industry'], name='company_company_industry_idx'),
        ),
        
        # Establishment Performance Indexes (only using fields that exist)
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['company', 'is_active'], name='company_establishment_company_active_idx'),
        ),
        
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['country', 'state', 'city'], name='company_establishment_location_idx'),
        ),
        
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['establishment_type'], name='company_establishment_type_idx'),
        ),
        
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['farming_method'], name='company_establishment_farming_method_idx'),
        ),
        
        # Geographic indexes for location-based queries (Establishment has these fields)
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['latitude', 'longitude'], name='company_establishment_coordinates_idx'),
        ),
        
        # Name indexes for search
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['name'], name='company_establishment_name_idx'),
        ),
        
        # Contact information indexes
        migrations.AddIndex(
            model_name='company',
            index=models.Index(fields=['contact_email'], name='company_company_email_idx'),
        ),
        
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['email'], name='company_establishment_email_idx'),
        ),
        
        # Agricultural operation indexes
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['total_acreage'], name='company_establishment_acreage_idx'),
        ),
        
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['year_established'], name='company_establishment_year_idx'),
        ),
        
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['climate_zone'], name='company_establishment_climate_idx'),
        ),
    ]