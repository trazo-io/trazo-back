# Generated manually for trial email notification tracking

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0002_add_pending_plan_to_subscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="email_notifications_sent",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Tracks sent trial lifecycle emails. Keys: day_11, day_14, day_17.",
            ),
        ),
    ]
