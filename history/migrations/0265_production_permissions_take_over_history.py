"""The model's permissions say `production`, and the four `*_history` rows go (2026-11-15).

0264 renamed the model `History` to `Production`. Django renames the ContentType with the model,
but not its permissions: `add_history`, `change_history`, `delete_history` and `view_history`
stayed on the renamed ContentType, and post_migrate then created `add_production` and the rest
beside them. Nothing in the code checks either set (no `has_perm`); the Django admin does, for a
staff user who is not a superuser.

Per action, on the `history.production` ContentType:
- both rows exist (any database migrated before 0264, prod included): every user and group that
  held the old permission is given the new one, then the old row is deleted. Deleting first would
  cascade the grants away;
- only the old row exists (0264 and this migration in the same run, before post_migrate): it is
  renamed in place, so its grants keep pointing at it;
- neither exists (a fresh database): nothing to do. post_migrate creates the new rows later.

Re-running finds nothing to do. The reverse is a no-op: a database rolled back past this point
still has the `*_production` permissions, and 0264's reverse renames the model, not permissions.
"""

from django.conf import settings
from django.db import migrations

ACTIONS = ("add", "change", "delete", "view")


def forward(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    GroupPermission = apps.get_model("auth", "Group").permissions.through
    UserPermission = apps.get_model(settings.AUTH_USER_MODEL).user_permissions.through
    verbose_name = apps.get_model("history", "Production")._meta.verbose_name

    content_type = ContentType.objects.filter(app_label="history", model="production").first()
    if content_type is None:
        return
    for action in ACTIONS:
        old = Permission.objects.filter(content_type=content_type, codename=f"{action}_history").first()
        if old is None:
            continue
        new = Permission.objects.filter(content_type=content_type, codename=f"{action}_production").first()
        if new is None:
            old.codename = f"{action}_production"
            old.name = f"Can {action} {verbose_name}"
            old.save(update_fields=["codename", "name"])
            continue
        for group_id in GroupPermission.objects.filter(permission=old).values_list("group_id", flat=True):
            GroupPermission.objects.get_or_create(group_id=group_id, permission=new)
        for user_id in UserPermission.objects.filter(permission=old).values_list("user_id", flat=True):
            UserPermission.objects.get_or_create(user_id=user_id, permission=new)
        old.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("history", "0264_history_model_is_production"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
