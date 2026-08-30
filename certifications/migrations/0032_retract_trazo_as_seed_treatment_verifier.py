"""
Retract the `trazo_verification` basis from stored G3.0 answers.

The option read "Checked against the National List / OMRI / WSDA in Trazo at logging time" and
compiled into the certifier-facing plan as Trazo having verified the seed treatment. No code
performs that check — `drift_detector` explicitly declines to verify a seed TREATMENT — and CCOF's
G3.0 D1 accepts exactly two bases: an OMRI/WSDA listing, or written certifier approval. The option
was removed from the questionnaire on 2026-08-27 (CONTENT_VERSION 2026.08.27); this removes it from
answers already stored, which would otherwise keep printing a retracted claim into packets.

Where it was the ONLY basis given, the answer is deleted rather than replaced. There is no honest
substitute: the operator picked a basis that turned out not to exist, and an unanswered question is
what the record actually supports. The module then reports `in_progress` against the current
questionnaire (see `_module_status`), which is the prompt to answer it properly.

Irreversible by design — restoring a retracted claim into an OSP is not something a `reverse` should
offer.
"""

from django.db import migrations

MODULE = "g3_0_seeds"
QUESTION = "treatment_verification"
RETRACTED = "trazo_verification"


def _answer_list(stored):
    """Answers exist in two shapes: bare, and enveloped {"value", "at"}."""
    if isinstance(stored, dict) and "value" in stored:
        return stored.get("value"), True
    return stored, False


def retract(apps, schema_editor):
    OrganicSystemPlan = apps.get_model("certifications", "OrganicSystemPlan")

    for osp in OrganicSystemPlan.objects.iterator():
        responses = osp.module_responses or {}
        entry = (responses.get("modules") or {}).get(MODULE)
        if not entry:
            continue
        answers = entry.get("answers") or {}
        if QUESTION not in answers:
            continue

        value, enveloped = _answer_list(answers[QUESTION])
        if not isinstance(value, list) or RETRACTED not in value:
            continue

        remaining = [v for v in value if v != RETRACTED]
        if remaining:
            if enveloped:
                answers[QUESTION] = {**answers[QUESTION], "value": remaining}
            else:
                answers[QUESTION] = remaining
        else:
            # The retracted option was the only basis. Unanswered is the honest state.
            answers.pop(QUESTION)

        entry["answers"] = answers
        osp.module_responses = responses
        osp.save(update_fields=["module_responses"])


class Migration(migrations.Migration):
    dependencies = [("certifications", "0031_retire_ccof_certification_type")]
    operations = [migrations.RunPython(retract, migrations.RunPython.noop)]
