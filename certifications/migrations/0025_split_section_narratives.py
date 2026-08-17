# WS-2.3 — split legacy section narratives into the generated/manual envelope.
#
# DRAFT plans only. Submitted/active/superseded/withdrawn rows are attested records of
# what a third party received — their consumers read `narrative`, which this envelope
# leaves untouched, and rewriting their JSON would churn the auditlog of a frozen
# document for zero behavioral gain. The compiler normalizes any legacy shape it meets
# at read time (`_split_section`), so an unmigrated row is safe by construction; this
# migration just makes the common case explicit.
#
# Reverse is a no-op: collapsing the envelope back would DELETE the manual/generated
# distinction, and `narrative` already carries the composed text either way.

from django.db import migrations


def split_draft_narratives(apps, schema_editor):
    OrganicSystemPlan = apps.get_model("certifications", "OrganicSystemPlan")
    for osp in OrganicSystemPlan.objects.filter(status="draft").iterator():
        sections = osp.sections or {}
        changed = False
        for key, section in list(sections.items()):
            section = dict(section or {})
            if "narrative_manual" in section:
                continue
            # Everything written before WS-2.3 was written by the operator: manual.
            section["narrative_manual"] = (section.get("narrative") or "").strip()
            section["narrative_generated"] = ""
            sections[key] = section
            changed = True
        if changed:
            osp.sections = sections
            osp.save(update_fields=["sections"])


class Migration(migrations.Migration):

    dependencies = [
        ("certifications", "0024_organicsystemplan_module_responses"),
    ]

    operations = [
        migrations.RunPython(split_draft_narratives, migrations.RunPython.noop),
    ]
