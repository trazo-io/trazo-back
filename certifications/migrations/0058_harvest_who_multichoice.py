"""Wrap `who_harvests` and `who_transports` answers in a list: both are checkbox groups now.

WSDA AGR 2121 §J1/§J10 and CCOF G6.1 A1/A2 ask "all that apply"; an orchard with its own crew AND a
custom harvester could only give one. The stored single answer stays exactly what the operator
said, now as a one-item list. Nothing is mapped or invented, so this is lossless and covers every
plan in every status: an unmigrated submitted or superseded plan would otherwise lose its
custom-harvester answers on packet regeneration (`includes` reads a list). Frozen artifacts
(`submission_pdf`, `OSPAnnualUpdate.filed_pdf`) are bytes and are not touched.
"""

from django.db import migrations

MODULE_KEY = "g6_1_harvest_transport"
KEYS = ("who_harvests", "who_transports")


def wrap_scalars(apps, schema_editor):
    OrganicSystemPlan = apps.get_model("certifications", "OrganicSystemPlan")
    for osp in OrganicSystemPlan.objects.all().iterator():
        responses = osp.module_responses or {}
        module = (responses.get("modules") or {}).get(MODULE_KEY)
        if not module:
            continue
        answers = module.get("answers") or {}
        changed = False
        for key in KEYS:
            entry = answers.get(key)
            if isinstance(entry, dict) and "value" in entry:
                value = entry["value"]
                if isinstance(value, str) and value:
                    entry["value"] = [value]
                    changed = True
            elif isinstance(entry, str) and entry:
                answers[key] = [entry]
                changed = True
        if changed:
            module["answers"] = answers
            osp.module_responses = responses
            osp.save(update_fields=["module_responses"])


def unwrap_single(apps, schema_editor):
    """Reverse only one-item lists; a plan that has since chosen several keeps them."""
    OrganicSystemPlan = apps.get_model("certifications", "OrganicSystemPlan")
    for osp in OrganicSystemPlan.objects.all().iterator():
        responses = osp.module_responses or {}
        module = (responses.get("modules") or {}).get(MODULE_KEY)
        if not module:
            continue
        answers = module.get("answers") or {}
        changed = False
        for key in KEYS:
            entry = answers.get(key)
            if isinstance(entry, dict) and isinstance(entry.get("value"), list) and len(entry["value"]) == 1:
                entry["value"] = entry["value"][0]
                changed = True
        if changed:
            osp.module_responses = responses
            osp.save(update_fields=["module_responses"])


class Migration(migrations.Migration):
    dependencies = [("certifications", "0057_change_notification_removal_reason")]
    operations = [migrations.RunPython(wrap_scalars, unwrap_single)]
