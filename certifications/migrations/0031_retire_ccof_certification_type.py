"""Retire "CCOF" as a certification TYPE; keep it as the certifying AGENT.

CCOF is an ACA accredited under 7 CFR Part 205 — it ISSUES USDA Organic certificates. It was
never a certification in its own right, and while it sat in the type vocabulary:

  * `VERIFIER_REGISTRY` only wires Organic Integrity Database verification to `usda_organic`,
    so a farm filing its certificate as "CCOF" silently lost the database check that would
    have confirmed it;
  * `ORGANIC_CONFERRING_CERT_TYPES` / `NOP_CERTIFICATION_TYPES` and their three
    copy-pasted twins each had to name `ccof` alongside `usda_organic` forever.

Forward: every `ccof` row becomes `usda_organic`, and "CCOF" is written into `certifier_name`
when that field is empty so the issuing agent survives the move. A row that already names a
certifier keeps it — the operator's own words win over this migration's assumption.

Reverse restores the type for rows this migration touched, identified by the certifier name
it wrote. Rows that already carried a different certifier are left alone in both directions.
"""

from django.db import migrations, models


def ccof_type_to_usda_organic(apps, schema_editor):
    Certification = apps.get_model("certifications", "Certification")
    for cert in Certification.objects.filter(certification_type="ccof"):
        cert.certification_type = "usda_organic"
        if not (cert.certifier_name or "").strip():
            cert.certifier_name = "CCOF"
        cert.save(update_fields=["certification_type", "certifier_name"])


def usda_organic_back_to_ccof(apps, schema_editor):
    Certification = apps.get_model("certifications", "Certification")
    Certification.objects.filter(certification_type="usda_organic", certifier_name="CCOF").update(
        certification_type="ccof"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("certifications", "0030_certifieraccesslink_audience_and_more"),
    ]

    operations = [
        # Data first: the AlterField below is choices-only (no DB constraint in Postgres),
        # but running the move first keeps the two steps in a defensible order if the field
        # ever gains a check constraint.
        migrations.RunPython(ccof_type_to_usda_organic, usda_organic_back_to_ccof),
        migrations.AlterField(
            model_name="certification",
            name="certification_type",
            field=models.CharField(
                choices=[
                    ("usda_organic", "USDA Organic"),
                    ("cng", "Certified Naturally Grown"),
                    ("real_organic_project", "Real Organic Project"),
                    ("roc", "Regenerative Organic Certified"),
                    ("korean_organic", "Korean Organic Certification"),
                    ("non_gmo_project", "Non-GMO Project Verified"),
                    ("global_gap", "GlobalG.A.P."),
                    ("primus_gfs", "PrimusGFS"),
                    ("salmon_safe", "Salmon-Safe"),
                    ("fair_trade", "Fair Trade Certified"),
                    ("rainforest_alliance", "Rainforest Alliance"),
                    ("sqf", "SQF Certified"),
                    ("kosher", "Kosher Certified"),
                    ("other", "Other"),
                ],
                help_text="Type of agricultural certification",
                max_length=30,
            ),
        ),
    ]
