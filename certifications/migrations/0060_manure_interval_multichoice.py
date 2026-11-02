"""Wrap `raw_manure_interval_rule` answers in a list: it is a checkbox group now.

CCOF G4.1 B2, OTCO C4 4.3-4 and WSDA AGR 2121 D13a say "all that apply"; a farm with root crops and
tree fruit applies both the 120-day and the 90-day rule and could state only one. The stored single
answer stays exactly what the operator said, now as a one-item list. Nothing is mapped or invented,
so this is lossless and covers every plan in every status, like 0059. Frozen artifacts
(`submission_pdf`, `OSPAnnualUpdate.filed_pdf`) are bytes and are not touched.
"""

from django.db import migrations

MODULE_KEY = "g4_1_compost_manure"
KEYS = ("raw_manure_interval_rule",)


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
            elif isinstance(entry, list) and len(entry) == 1:
                answers[key] = entry[0]
                changed = True
        if changed:
            module["answers"] = answers
            osp.module_responses = responses
            osp.save(update_fields=["module_responses"])


class Migration(migrations.Migration):
    dependencies = [("certifications", "0059_harvest_who_multichoice")]
    operations = [migrations.RunPython(wrap_scalars, unwrap_single)]
