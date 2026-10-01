from django.db import migrations


def preflight_and_backfill(apps, schema_editor):
    """Give every existing filing its establishment and revision 1, and say which were filed
    before Trazo kept a frozen copy.

    Every existing row becomes revision 1 of its year. The old constraint was per plan version,
    so one establishment can hold two rows for the same year against different versions; they
    would collide on the new (establishment, year, revision) key. Which of them is the real
    filing is a fact this migration does not have, so it does not pick one: it stops and names
    them.

    A row already filed gets `legacy_none`. No frozen copy and no signer are written for it:
    rendering one now would present today's records as what was filed then.
    """
    from collections import defaultdict

    OSPAnnualUpdate = apps.get_model("certifications", "OSPAnnualUpdate")
    rows = list(OSPAnnualUpdate.objects.select_related("prior_osp").order_by("id"))
    by_year = defaultdict(list)
    for row in rows:
        by_year[(row.prior_osp.establishment_id, row.reporting_year)].append(row.id)
    clashes = {key: ids for key, ids in by_year.items() if len(ids) > 1}
    if clashes:
        listed = "; ".join(
            "establishment {} year {}: annual updates {}".format(est, year, ", ".join(str(i) for i in ids))
            for (est, year), ids in sorted(clashes.items())
        )
        raise RuntimeError(
            "More than one annual update exists for the same establishment and year, so they cannot all "
            "become revision 1. Decide which one was filed and resolve the others by hand before "
            "migrating: " + listed
        )
    for row in rows:
        row.establishment_id = row.prior_osp.establishment_id
        row.revision_number = 1
        row.snapshot_state = "legacy_none" if row.submitted_at is not None else ""
        row.save(update_fields=["establishment", "revision_number", "snapshot_state"])


class Migration(migrations.Migration):
    """Data only. Kept apart from the schema change and from the constraints that depend on it,
    so no table is altered in the transaction that updates its rows."""

    dependencies = [("certifications", "0043_annual_update_revisions")]

    operations = [
        migrations.RunPython(preflight_and_backfill, migrations.RunPython.noop),
    ]
