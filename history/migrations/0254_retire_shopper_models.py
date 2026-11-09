"""Retire five shopper models from the state, step 1 of 2.

UserFavorite, UserProductComparison, UserShoppingGoal, UserShoppingInsight and
UserLocalRecommendation (with its `carbon_score`, a stored 0-100 grade). No screen read or wrote
any of them; their routes (`consumer/favorites/`, `consumer/goals/`,
`consumer/dashboard/compare_products/`) leave with this change, closing the two tenancy findings
on compare_products and toggle_favorite. On 2026-11-09 production held 0 rows in all seven tables
(the five plus the two many-to-many tables). UserImpactSummary stays: the signed-in consumer
dashboard reads it.

The tables cannot go yet. `migrate` runs on the new container while the previous ones still serve,
and their delete collector reads these tables when it deletes a user, a production or an
establishment. So:

1. refuse to run if any of the seven tables holds a row;
2. drop the foreign keys from these tables to live ones (users, productions, establishments).
   With the models gone, Django no longer knows the tables reference them, and a constraint it
   cannot see makes `TRUNCATE` of the live table fail (every TransactionTestCase flush). The two
   foreign keys between the retiring tables themselves stay; step 2 drops them with the tables;
3. remove the five models from the state only. The tables and the content types stay.

Step 2 drops the seven tables. Reversing this one restores the foreign keys and puts the models
back in the state over the tables still there.
"""

from django.db import migrations

#: Frozen: the seven tables this step retires.
TABLES = (
    "history_userfavorite",
    "history_userlocalrecommendation",
    "history_userlocalrecommendation_recommended_products",
    "history_userproductcomparison",
    "history_userproductcomparison_products",
    "history_usershoppinggoal",
    "history_usershoppinginsight",
)


def rows_held(cursor):
    held = {}
    for table in TABLES:
        cursor.execute(f'SELECT count(*) FROM "{table}"')
        count = cursor.fetchone()[0]
        if count:
            held[table] = count
    return held


#: (table, column, referenced table, Django's constraint name) for every foreign key from a retired
#: table to a live one, as history 0016 created them. The forward step finds the constraints by
#: table instead of by name; the reverse puts these back.
OUTWARD_FOREIGN_KEYS = (
    (
        "history_userfavorite",
        "production_id",
        "history_history",
        "history_userfavorite_production_id_0e1f46df_fk_history_h",
    ),
    (
        "history_userfavorite",
        "user_id",
        "users_user",
        "history_userfavorite_user_id_93c84096_fk_users_user_id",
    ),
    (
        "history_userlocalrecommendation",
        "establishment_id",
        "company_establishment",
        "history_userlocalrec_establishment_id_41076c51_fk_company_e",
    ),
    (
        "history_userlocalrecommendation",
        "user_id",
        "users_user",
        "history_userlocalrec_user_id_25dc05c9_fk_users_use",
    ),
    (
        "history_userlocalrecommendation_recommended_products",
        "history_id",
        "history_history",
        "history_userlocalrec_history_id_e897e1fe_fk_history_h",
    ),
    (
        "history_userproductcomparison",
        "user_id",
        "users_user",
        "history_userproductcomparison_user_id_a72a88ad_fk_users_user_id",
    ),
    (
        "history_userproductcomparison_products",
        "history_id",
        "history_history",
        "history_userproductc_history_id_c229ffa0_fk_history_h",
    ),
    (
        "history_usershoppinggoal",
        "user_id",
        "users_user",
        "history_usershoppinggoal_user_id_55b0e73c_fk_users_user_id",
    ),
    (
        "history_usershoppinginsight",
        "user_id",
        "users_user",
        "history_usershoppinginsight_user_id_49a765e5_fk_users_user_id",
    ),
)


def outward_foreign_keys(cursor):
    """(table, constraint) for each foreign key from a retired table to a table outside the set."""
    cursor.execute(
        "SELECT c.conrelid::regclass::text, c.conname FROM pg_constraint c "
        "WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY(%s) "
        "AND NOT (c.confrelid::regclass::text = ANY(%s)) ORDER BY 1, 2",
        [list(TABLES), list(TABLES)],
    )
    return cursor.fetchall()


#: Adding or dropping a foreign key locks the referenced table too (users_user, history_history,
#: company_establishment: logins and every page). Fail after 5 s instead of queueing every read
#: behind a long transaction; the deploy can be retried. Set inside both directions, because a
#: reverse runs the operations backwards.
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def drop_outward_foreign_keys(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(LOCK_TIMEOUT)
        for table, constraint in outward_foreign_keys(cursor):
            cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}"')


def restore_outward_foreign_keys(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(LOCK_TIMEOUT)
        for table, column, target, constraint in OUTWARD_FOREIGN_KEYS:
            cursor.execute(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" FOREIGN KEY ("{column}") '
                f'REFERENCES "{target}" ("id") DEFERRABLE INITIALLY DEFERRED'
            )


def refuse_if_a_row_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = rows_held(cursor)
    if held:
        raise RuntimeError(
            f"history 0254: retired tables hold rows {held}; nothing was changed. No screen writes "
            "them: find out what did before retiring them."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0253_backfill_activity_link"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunPython(drop_outward_foreign_keys, restore_outward_foreign_keys),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(
                    name="userlocalrecommendation",
                    unique_together=None,
                ),
                migrations.RemoveField(
                    model_name="userlocalrecommendation",
                    name="establishment",
                ),
                migrations.RemoveField(
                    model_name="userlocalrecommendation",
                    name="recommended_products",
                ),
                migrations.RemoveField(
                    model_name="userlocalrecommendation",
                    name="user",
                ),
                migrations.RemoveField(
                    model_name="userproductcomparison",
                    name="products",
                ),
                migrations.RemoveField(
                    model_name="userproductcomparison",
                    name="user",
                ),
                migrations.RemoveField(
                    model_name="usershoppinggoal",
                    name="user",
                ),
                migrations.RemoveField(
                    model_name="usershoppinginsight",
                    name="user",
                ),
                migrations.DeleteModel(
                    name="UserFavorite",
                ),
                migrations.DeleteModel(
                    name="UserLocalRecommendation",
                ),
                migrations.DeleteModel(
                    name="UserProductComparison",
                ),
                migrations.DeleteModel(
                    name="UserShoppingGoal",
                ),
                migrations.DeleteModel(
                    name="UserShoppingInsight",
                ),
            ],
            database_operations=[],
        ),
    ]
