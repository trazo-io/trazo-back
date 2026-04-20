# Sprint 1.1 — NOP Seed Traceability (7 CFR 205.204 / NOP 5029)
#
# Adds supplier/purchase/lot/cert status/treatment fields to ProductionEvent (planting subtype)
# mirroring the ChemicalEvent supplier pattern from 0146_nop_compliance_fields.
#
# Includes a data migration that reshapes the SEEDS_SOURCE enum: historical records with
# seeds_source="certified_organic" are moved to seed_certification_status="certified_organic"
# and seeds_source is reset to "commercial" (safe default). SEEDS_SOURCE now represents
# WHERE the seed came from; seed_certification_status represents WHAT it is, per NOP.

from django.db import migrations, models

SEED_CERTIFICATION_STATUS_CHOICES = [
    ("certified_organic", "Certified Organic"),
    ("transitional", "Transitional"),
    ("non_organic_untreated", "Non-organic (Untreated)"),
    ("non_organic_treated", "Non-organic (Treated)"),
]

SEEDS_SOURCE_CHOICES = [
    ("farm_saved", "Farm-Saved Seeds"),
    ("local", "Local Nursery/Supplier"),
    ("cooperative", "Farmer Cooperative"),
    ("commercial", "Commercial Supplier"),
    ("other", "Other"),
]


def migrate_certified_organic_source(apps, schema_editor):
    """Move seeds_source='certified_organic' into seed_certification_status."""
    ProductionEvent = apps.get_model("history", "ProductionEvent")
    qs = ProductionEvent.objects.filter(seeds_source="certified_organic")
    qs.update(seed_certification_status="certified_organic", seeds_source="commercial")


def reverse_migrate_certified_organic_source(apps, schema_editor):
    """Reverse: restore seeds_source='certified_organic' for records that match."""
    ProductionEvent = apps.get_model("history", "ProductionEvent")
    qs = ProductionEvent.objects.filter(seed_certification_status="certified_organic", seeds_source="commercial")
    qs.update(seeds_source="certified_organic")


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0151_nop_equipment_cleaning_operation_type"),
    ]

    operations = [
        # 1. Add the new traceability fields (planting subtype).
        migrations.AddField(
            model_name="productionevent",
            name="seed_supplier_name",
            field=models.CharField(
                blank=True,
                help_text="Name of the seed/planting stock supplier (NOP 7 CFR 205.204 traceability)",
                max_length=200,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productionevent",
            name="seed_purchase_date",
            field=models.DateField(
                blank=True,
                help_text="Date seed/planting stock was purchased (traceability to supplier invoice)",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productionevent",
            name="seed_purchase_invoice",
            field=models.CharField(
                blank=True,
                help_text="Supplier invoice number for the seed/planting stock purchase",
                max_length=100,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productionevent",
            name="seed_lot_number",
            field=models.CharField(
                blank=True,
                help_text="Supplier lot/batch identifier for the seed/planting stock",
                max_length=100,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productionevent",
            name="seed_certification_status",
            field=models.CharField(
                blank=True,
                choices=SEED_CERTIFICATION_STATUS_CHOICES,
                help_text=(
                    "Regulatory classification per NOP 7 CFR 205.204. "
                    "Non-organic treated seed with prohibited substances disqualifies the crop."
                ),
                max_length=30,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="productionevent",
            name="seed_treatment",
            field=models.CharField(
                blank=True,
                help_text="Seed coatings, inoculants, or pelleting materials applied (NOP 7 CFR 205.204(a)(5))",
                max_length=200,
                null=True,
            ),
        ),
        # 2. Move existing 'certified_organic' values from seeds_source into the new field.
        migrations.RunPython(
            migrate_certified_organic_source,
            reverse_code=reverse_migrate_certified_organic_source,
        ),
        # 3. Reshape the SEEDS_SOURCE choices (drop 'certified_organic' — it's not a source).
        migrations.AlterField(
            model_name="productionevent",
            name="seeds_source",
            field=models.CharField(
                blank=True,
                choices=SEEDS_SOURCE_CHOICES,
                help_text=(
                    "Where the seed/planting stock came from (transparency field; does not affect carbon). "
                    "For regulatory classification (organic/transitional/non-organic), use seed_certification_status."
                ),
                max_length=50,
                null=True,
            ),
        ),
    ]
