"""The model's permissions say `production`, and the four `*_history` rows go (2026-11-15).

0264 renamed the model `History` to `Production`. Django renames the ContentType with the model,
but not its permissions: `add_history`, `change_history`, `delete_history` and `view_history`
stayed on the renamed ContentType, and post_migrate then created `add_production` and the rest
beside them. Nothing in the code checks either set (no `has_perm`); the Django admin does, for a
staff user who is not a superuser.

Per action:
- both rows exist (a database that ran 0264 and its post_migrate before this one: prod): every
  user and group that held the old permission is given the new one, then the old row is deleted.
  Deleting first would cascade the grants away;
- only the old row exists (0264 and this migration in one run, before post_migrate): it is
  renamed in place, so its grants keep pointing at it;
- neither exists (a fresh database): nothing to do. post_migrate creates the new rows later.

The old rows are looked for on the `history.production` ContentType and also on a leftover
`history.history` one. Django's rename of the ContentType is skipped silently when a
`history.production` row already exists (post_migrate ran with the new model before 0264), which
leaves the old permissions and their grants on the old ContentType. That ContentType is not
deleted: `LogEntry.content_type` cascades, so deleting it would erase audit trail.

Re-running finds nothing to do. The reverse does the same in the other direction, so a rollback
past 0264 leaves grants on the `*_history` permissions the restored model checks.
"""

from django.conf import settings
from django.db import migrations

ACTIONS = ("add", "change", "delete", "view")


def _take_over(apps, old_name, new_name, new_verbose_name):
    """Move each `<action>_<old_name>` permission's grants to `<action>_<new_name>`.

    Both directions work on the ContentType named `history.production`: at this migration the model
    is `Production`, and 0264's reverse renames that ContentType only after this one has reversed.
    """
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    GroupPermission = apps.get_model("auth", "Group").permissions.through
    UserPermission = apps.get_model(settings.AUTH_USER_MODEL).user_permissions.through

    target = ContentType.objects.filter(app_label="history", model="production").first()
    if target is None:
        return
    sources = ContentType.objects.filter(app_label="history", model__in=["production", "history"])
    for action in ACTIONS:
        new = Permission.objects.filter(content_type=target, codename=f"{action}_{new_name}").first()
        for old in Permission.objects.filter(content_type__in=sources, codename=f"{action}_{old_name}"):
            if new is None:
                old.content_type = target
                old.codename = f"{action}_{new_name}"
                old.name = f"Can {action} {new_verbose_name}"
                old.save(update_fields=["content_type", "codename", "name"])
                new = old
                continue
            group_ids = GroupPermission.objects.filter(permission=old).values_list("group_id", flat=True)
            GroupPermission.objects.bulk_create(
                [GroupPermission(group_id=g, permission=new) for g in group_ids], ignore_conflicts=True
            )
            user_ids = UserPermission.objects.filter(permission=old).values_list("user_id", flat=True)
            UserPermission.objects.bulk_create(
                [UserPermission(user_id=u, permission=new) for u in user_ids], ignore_conflicts=True
            )
            old.delete()


def forward(apps, schema_editor):
    _take_over(apps, "history", "production", apps.get_model("history", "Production")._meta.verbose_name)


def backward(apps, schema_editor):
    _take_over(apps, "production", "history", "history")


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0264_history_model_is_production"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(forward, backward)]
