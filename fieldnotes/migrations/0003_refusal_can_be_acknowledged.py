"""A refused note can be seen and cleared, instead of accumulating forever.

WHAT WAS WRONG. `FieldNoteViewSet.discard` answers 409 for anything that is not PENDING, so a
REFUSED note could not be cleared by anyone, ever. The waiting queue drains as notes are logged or
discarded; the refused list did not. Every unsupported-language message, failed transcription,
photo with no caption and over-budget day stayed on the page for the life of the account, and the
crew roster and channel cards render BELOW it, so the scroll to reach setup grew without bound.

WHY A THIRD STATUS AND NOT `discarded`. Letting `discard` take a refused note needs no migration
and is wrong. DISCARDED records that the OPERATION decided the message was not an event. A refusal
is Trazo failing to read one. Collapsing them would leave anyone reading the trail later unable to
tell "we looked and said no" from "we never got to look", which is the distinction `discard`'s own
docstring exists to protect.

NO REASON FIELD. `refusal_reason` is already on the row, written by the machine that failed. The
operator is recording that they read it, not explaining it, and a free-text box would invite a
second, softer account of the same event into the trail.

The status column is `max_length=16` and "acknowledged" is 12, so this alter is a constraint change
rather than a column rewrite.
"""


import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fieldnotes', '0002_fieldnote_audio_deleted_at_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='fieldnote',
            name='acknowledged_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='fieldnote',
            name='acknowledged_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='fieldnote',
            name='status',
            field=models.CharField(choices=[('transcribing', 'Being read'), ('pending', 'Waiting for review'), ('confirmed', 'Logged'), ('discarded', 'Discarded'), ('refused', 'Could not be accepted'), ('acknowledged', 'Could not be accepted, and seen')], db_index=True, default='pending', max_length=16),
        ),
    ]
