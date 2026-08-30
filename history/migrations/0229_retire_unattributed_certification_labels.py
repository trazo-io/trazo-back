"""Reorder BusinessEvent.certification_type choices — offered first, retired last.

Choices-only, so nothing changes in Postgres. It exists because the two retired entries
("carbon_neutral", "sustainable_agriculture") moved out of the offered list and into
`DEPRECATED_CERTIFICATION_TYPE_CHOICES`, and `makemigrations --check` is part of CI.

The values are NOT removed from the column. A farmer who logged one of them has a
§ 205.103(b)(2) record that must survive an inspector's trace-back, and stripping the choice
entirely would make `get_certification_type_display()` print the raw slug into a certifier
packet. Writes are refused by `BusinessEventSerializer.validate_certification_type`.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0228_chemicalevent_receipt_document_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="businessevent",
            name="certification_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("organic_usda", "USDA Organic"),
                    ("regenerative", "Regenerative Organic Certified (ROC)"),
                    ("real_organic", "Real Organic Project (ROP)"),
                    ("cng", "Certified Naturally Grown (CNG)"),
                    ("non_gmo", "Non-GMO Project Verified"),
                    ("rainforest_alliance", "Rainforest Alliance"),
                    ("water_stewardship", "Water Stewardship Certification"),
                    ("global_gap", "GlobalG.A.P. Certified"),
                    ("fair_trade", "Fair Trade Certified"),
                    ("food_safety", "SQF / Food Safety Certified"),
                    ("kosher", "Kosher Certified"),
                    ("carbon_neutral", "Carbon Neutral Certification"),
                    ("sustainable_agriculture", "Sustainable Agriculture Standard"),
                ],
                help_text="Type of certification obtained or renewed",
                max_length=50,
                null=True,
            ),
        ),
    ]
