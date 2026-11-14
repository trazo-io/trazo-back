"""The `History` model is `Production` (schema remodel Phase 3, 2026-11-14).

A rename in Django state that changes nothing in the database except the `django_content_type`
row. Written by hand: `makemigrations` without a prompt reads a rename as "delete History, create
Production", which would drop the table.

1. `AlterModelTable` pins the table to the name it already has, so the rename cannot move it (a
   model with no explicit `db_table` takes its table name from its class).
2. The automatic link table behind `post_harvest_facilities` becomes an explicit model, in state
   only, with the table, columns and uniqueness it already has. An automatic link table names its
   columns after the model, so the rename would have run
   `RENAME COLUMN history_id TO production_id` while the previous release, still serving during
   the deploy, read `history_id`.
3. `RenameModel` at the top level of the migration, so contenttypes injects its own operation that
   renames the content type row in place: same id, so every auditlog `LogEntry` keeps pointing at
   the same rows. Foreign keys to the model follow in state; their columns and constraints do not
   change, because the table does not.
4. `album`'s reverse names were derived from the class name; they are pinned to what they were.

It depends on the current leaf of every other app whose models point at this one (carbon,
documents, product, reviews). Without that, the graph may build those apps' state AFTER the rename,
their foreign keys still name "history.history", and `makemigrations` reports a change that is not
there (reviews did, 2026-11-14).

`sqlmigrate history 0264` prints no statement but the two no-ops.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("carbon", "0055_tree_crops_have_no_soil_contact"),
        ("common", "0001_initial"),
        ("documents", "0011_wa_spray_records_source"),
        ("history", "0263_production_method_has_no_default"),
        ("product", "0031_parcel_planned_crop_orchard_columns"),
        ("reviews", "0004_allow_anonymous_reviews"),
    ]

    operations = [
        migrations.AlterModelTable(name="history", table="history_history"),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ProductionPostHarvestFacility",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        (
                            "history",
                            models.ForeignKey(
                                db_column="history_id",
                                on_delete=django.db.models.deletion.CASCADE,
                                to="history.history",
                            ),
                        ),
                        (
                            "postharvestfacility",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="certifications.postharvestfacility",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "history_history_post_harvest_facilities",
                        "unique_together": {("history", "postharvestfacility")},
                    },
                ),
                migrations.AlterField(
                    model_name="history",
                    name="post_harvest_facilities",
                    field=models.ManyToManyField(
                        blank=True,
                        related_name="productions",
                        through="history.ProductionPostHarvestFacility",
                        to="certifications.postharvestfacility",
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.RenameModel(old_name="History", new_name="Production"),
        migrations.AlterField(
            model_name="production",
            name="album",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="history_set",
                related_query_name="history",
                to="common.gallery",
            ),
        ),
    ]
