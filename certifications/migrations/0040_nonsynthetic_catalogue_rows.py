"""Re-file three catalogue rows that are not on § 205.601 as nonsynthetic, in place.

"Spinosad", "Microbial products (Bacillus thuringiensis, etc.)" and "d-Limonene" were seeded at
§ 205.601(e). Checked against the eCFR (Title 7 part 205, issue of 2026-09-04) on 2026-09-10:
none of the three is in § 205.601, which lists SYNTHETIC substances. Each is nonsynthetic, and a
nonsynthetic substance is allowed in organic crop production unless § 205.602 names it
(§ 205.105(b)). Every surface that printed the section therefore told a certifier, and the buyer
page told a shopper, that the product was a listed synthetic.

UPDATE IN PLACE — never create, never delete. A deleted row would drop out of every plan that
attached it (the M2M) and null the link on every ChemicalEvent and PlanMaterialEntry; a moved row
keeps its primary key, so plans and records stay attached. Where a nonsynthetic row of the same
name already exists the § 205.601 row is left alone and logged, because the unique constraint on
(name, section) would refuse the move and merging two rows is a decision, not a migration.
Frozen here rather than imported from the seeder — a migration must replay identically forever.
"""

import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)

NOTE = (
    "Nonsynthetic; allowed in organic crop production without a National List entry. "
    "§ 205.105(b) prohibits only the nonsynthetic substances § 205.602 lists."
)
ROWS = ["spinosad", "microbial products (bacillus thuringiensis, etc.)", "d-limonene"]


def refile(apps, schema_editor):
    Substance = apps.get_model("certifications", "NationalListSubstance")
    for normalized in ROWS:
        if Substance.objects.filter(substance_name_normalized=normalized, cfr_section="nonsyn").exists():
            logger.warning(
                "0040: a nonsynthetic %r row already exists; its § 205.601 row, if any, is left for review",
                normalized,
            )
            continue
        Substance.objects.filter(substance_name_normalized=normalized, cfr_section="205.601").update(
            cfr_section="nonsyn",
            subsection=None,
            restriction_notes=NOTE,
            annotation_kind="rationale",
        )


class Migration(migrations.Migration):
    dependencies = [("certifications", "0039_national_list_205_602_text")]

    operations = [
        migrations.AlterField(
            model_name="nationallistsubstance",
            name="cfr_section",
            field=models.CharField(
                choices=[
                    ("205.105", "§205.105 — Excluded substances & methods (prohibited)"),
                    ("205.601", "§205.601 — Synthetic allowed (crops)"),
                    ("205.602", "§205.602 — Nonsynthetic prohibited (crops)"),
                    ("205.603", "§205.603 — Synthetic allowed (livestock)"),
                    ("205.605", "§205.605 — Nonagricultural allowed (handling)"),
                    ("205.606", "§205.606 — Nonorganic agricultural allowed (handling)"),
                    ("nonsyn", "Nonsynthetic — allowed without a National List entry"),
                ],
                db_index=True,
                max_length=10,
            ),
        ),
        # Reverse is a no-op: putting the rows back at § 205.601 would restore a false citation.
        migrations.RunPython(refile, migrations.RunPython.noop),
    ]
