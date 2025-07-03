"""
Migration to increase field lengths for international business support
Addresses production readiness issue with company/establishment names and addresses
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0012_streamline_establishment_operations'),
    ]

    operations = [
        # Increase company name field length
        migrations.AlterField(
            model_name='company',
            name='name',
            field=models.CharField(
                max_length=150,  # Increased from 30 to 150
                help_text='Company name (increased length for international businesses)'
            ),
        ),
        
        # Increase establishment name field length
        migrations.AlterField(
            model_name='establishment',
            name='name',
            field=models.CharField(
                max_length=150,  # Increased from 30 to 150
                help_text='Establishment name (increased length for international operations)'
            ),
        ),
        
        # Increase address field lengths
        migrations.AlterField(
            model_name='company',
            name='address',
            field=models.CharField(
                max_length=300,  # Increased for international addresses
                blank=True,
                help_text='Company address (extended for international formats)'
            ),
        ),
        
        migrations.AlterField(
            model_name='establishment',
            name='address',
            field=models.CharField(
                max_length=300,  # Increased for international addresses
                help_text='Establishment address (extended for international formats)'
            ),
        ),
        
        # Increase city field lengths
        migrations.AlterField(
            model_name='company',
            name='city',
            field=models.CharField(
                max_length=100,  # Increased for international city names
                blank=True,
                help_text='City name (extended for international cities)'
            ),
        ),
        
        migrations.AlterField(
            model_name='establishment',
            name='city',
            field=models.CharField(
                max_length=100,  # Increased for international city names
                blank=True,
                help_text='City name (extended for international cities)'
            ),
        ),
        
        # Increase state/province field lengths
        migrations.AlterField(
            model_name='company',
            name='state',
            field=models.CharField(
                max_length=100,  # Increased for international states/provinces
                blank=True,
                help_text='State or province (extended for international regions)'
            ),
        ),
        
        migrations.AlterField(
            model_name='establishment',
            name='state',
            field=models.CharField(
                max_length=100,  # Increased for international states/provinces
                blank=True,
                help_text='State or province (extended for international regions)'
            ),
        ),
        
        # Add simple indexes for better performance on searches (SQLite compatible)
        migrations.AddIndex(
            model_name='company',
            index=models.Index(fields=['name'], name='company_name_search_idx'),
        ),
        
        migrations.AddIndex(
            model_name='establishment',
            index=models.Index(fields=['name'], name='establishment_name_search_idx'),
        ),
    ]