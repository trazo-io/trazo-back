"""
Data migration: migrate existing Establishment.certifications TextField
to structured Certification records.
"""

from django.db import migrations


KNOWN_TYPES = {
    "usda organic": "usda_organic",
    "organic": "usda_organic",
    "ccof": "ccof",
    "certified naturally grown": "cng",
    "cng": "cng",
    "real organic project": "real_organic_project",
    "regenerative organic": "roc",
    "regenerative organic certified": "roc",
    "non-gmo": "non_gmo_project",
    "non gmo": "non_gmo_project",
    "non-gmo project": "non_gmo_project",
    "global gap": "global_gap",
    "globalgap": "global_gap",
    "fair trade": "fair_trade",
    "fair trade certified": "fair_trade",
    "rainforest alliance": "rainforest_alliance",
}


def migrate_existing_certifications(apps, schema_editor):
    Establishment = apps.get_model("company", "Establishment")
    Certification = apps.get_model("certifications", "Certification")

    migrated = 0
    for est in Establishment.objects.exclude(certifications__isnull=True).exclude(certifications=""):
        cert_text = est.certifications or ""
        for raw in cert_text.split(","):
            raw = raw.strip()
            if not raw:
                continue
            cert_type = KNOWN_TYPES.get(raw.lower(), "other")
            _, created = Certification.objects.get_or_create(
                establishment=est,
                certification_type=cert_type,
                certification_number=None,
                defaults={
                    "verification_status": "self_reported",
                    "verification_notes": f"Migrated from legacy text field: {raw}",
                },
            )
            if created:
                migrated += 1

    if migrated:
        print(f"  Migrated {migrated} certification(s) from legacy text fields")


def reverse_migration(apps, schema_editor):
    Certification = apps.get_model("certifications", "Certification")
    Certification.objects.filter(
        verification_notes__startswith="Migrated from legacy text field:"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("certifications", "0001_initial"),
        ("company", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            migrate_existing_certifications,
            reverse_code=reverse_migration,
        ),
    ]
