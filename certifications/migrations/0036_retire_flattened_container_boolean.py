"""Clear `containers_clean_or_dedicated` — it cannot be mapped to what replaced it.

G6.1 §B asked ONE boolean, "are these containers new, dedicated to organic use, OR cleaned before
each use?", answered once across every container type the operation had ticked. It compiled as an
affirmative covering all three predicates: on the pilot a single "Yes" spoke for reusable lugs,
single-use cartons and totes while the description substantiated only the lugs. WSDA J5 asks the
same thing as a four-way checkbox; CCOF G6.1 B1 as a per-item table.

`container_safeguards` replaces it. This migration DELETES the stored answers rather than mapping
them, because a stored `True` does not say which safeguard applies — that missing information is
precisely the defect. Inventing one ("they said yes, so call it cleaned_prior") would put a claim
in front of a certifier that the operator never made, which is the failure class this codebase
keeps closing.

`_module_status` recomputes against the current questionnaire, so the affected plans correctly
report `in_progress` again and prompt for the answer. Nothing is lost that was ever stated.
"""

from django.db import migrations

RETIRED_KEY = "containers_clean_or_dedicated"
MODULE_KEY = "g6_1_harvest_transport"


def clear_flattened_answer(apps, schema_editor):
    OrganicSystemPlan = apps.get_model("certifications", "OrganicSystemPlan")
    for osp in OrganicSystemPlan.objects.all().iterator():
        responses = osp.module_responses or {}
        module = (responses.get("modules") or {}).get(MODULE_KEY)
        if not module:
            continue
        answers = module.get("answers") or {}
        if RETIRED_KEY not in answers:
            continue
        answers.pop(RETIRED_KEY, None)
        module["answers"] = answers
        osp.module_responses = responses
        osp.save(update_fields=["module_responses"])


def noop_reverse(apps, schema_editor):
    """Irreversible by design — the value carried no information to restore."""


class Migration(migrations.Migration):
    dependencies = [("certifications", "0035_planmaterialentry_and_more")]
    operations = [migrations.RunPython(clear_flattened_answer, noop_reverse)]
