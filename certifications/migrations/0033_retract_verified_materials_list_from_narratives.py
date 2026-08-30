"""
Remove "the verified materials list" from narratives already compiled into stored plans.

Companion to 0032 and to the 2026-08-27 claim-safety sweep. That sweep changed the compile
TEMPLATES, which only take effect the next time a plan is recompiled — and a submitted or active
plan is never recompiled, because its answers are locked. So seven plans (two active, three
submitted, two superseded) went on carrying the phrase in `sections[*].narrative_generated`, which
is exactly the text the packet's § 205.201(a)(2) narrative prints. The claim was removed from the
code and left standing in the documents.

`compliance.md` reserves "verified" for a USDA Organic Integrity Database match. Trazo resolves an
input's name against OMRI / the WSDA Materials List / the National List; the certifying agent
approves. "The verified materials list" asserts both of the things we do not do.

## Why a string edit rather than a recompile

Recompiling would need the live module registry and compiler inside a migration, which breaks
replay the first time either changes shape. A targeted replacement needs neither, leaves every
other byte of the narrative identical, and cannot reword an answer by accident.

## Why touching submitted and active plans is right here

`narrative_generated` is Trazo's own prose about the operator's stored answers, held separately
from `narrative_manual` (the operator's words, untouched below). No answer changes and no operator
sentence changes; a false statement Trazo made about itself is corrected. Leaving it would mean
every future regeneration of those packets repeats it.
"""

from django.db import migrations

OLD = "verified materials list"
NEW = "materials list on this plan"

# Only the two composed prose fields. `narrative_manual` is the operator's own text and is never
# rewritten — if a farmer wrote "verified materials list" themselves, that is their sentence.
NARRATIVE_FIELDS = ("narrative", "narrative_generated")


def retract(apps, schema_editor):
    OrganicSystemPlan = apps.get_model("certifications", "OrganicSystemPlan")

    for osp in OrganicSystemPlan.objects.iterator():
        sections = osp.sections or {}
        if not isinstance(sections, dict):
            continue

        changed = False
        for section in sections.values():
            if not isinstance(section, dict):
                continue
            for field in NARRATIVE_FIELDS:
                value = section.get(field)
                if isinstance(value, str) and OLD in value:
                    section[field] = value.replace(OLD, NEW)
                    changed = True

        if changed:
            osp.sections = sections
            osp.save(update_fields=["sections"])


class Migration(migrations.Migration):
    dependencies = [("certifications", "0032_retract_trazo_as_seed_treatment_verifier")]
    operations = [migrations.RunPython(retract, migrations.RunPython.noop)]
