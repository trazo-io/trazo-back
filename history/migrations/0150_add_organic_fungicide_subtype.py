# Generated manually 2026-04-09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0149_nop_manure_harvest_interval"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chemicalevent",
            name="chemical_subtype",
            field=models.CharField(
                blank=True,
                choices=[
                    ("synthetic_herbicide", "Synthetic Herbicide"),
                    ("organic_herbicide", "Organic/Natural Herbicide"),
                    ("synthetic_fungicide", "Synthetic Fungicide"),
                    ("organic_fungicide", "Organic/Natural Fungicide"),
                    ("copper_fungicide", "Copper-Based Fungicide"),
                    ("sulfur_fungicide", "Sulfur-Based Fungicide"),
                    ("biological_fungicide", "Biological Fungicide"),
                    ("synthetic_pesticide", "Synthetic Pesticide"),
                    ("organic_pesticide", "Organic/Natural Pesticide"),
                    ("biological_pesticide", "Biological Pesticide"),
                    ("synthetic_fertilizer", "Synthetic/Chemical Fertilizer"),
                    ("organic_fertilizer", "Organic Fertilizer"),
                    ("slow_release_fertilizer", "Slow-Release Fertilizer"),
                ],
                help_text="Specific subtype of chemical for accurate carbon emission calculations. Different subtypes have different manufacturing emission factors.",
                max_length=30,
                null=True,
            ),
        ),
    ]
