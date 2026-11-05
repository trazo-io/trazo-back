"""Store the rule's own annotation on the § 205.601 rows a certifier's form asks the grower about.

The catalogue held paraphrases for fixed coppers, copper sulfate, magnesium sulfate and the two
micronutrient rows ("Minimize soil accumulation."), and the boron row still carried the wording
83 FR 66559 replaced in 2019 ("documented by soil or tissue testing", without the method the
certifying agent approves). WSDA AGR 2121 D4 and H5, OTCO C4 4.5-1 and WSDA AGR 2196's restrictions
column all ask how these conditions are met, so the condition has to be printable as the rule's words.

UPDATE ONLY, as migration 0039: a row that does not exist is not created; `seed_national_list`
carries the same text for a database it seeds. `annotation_kind` is not touched: every one of these
rows is already "condition_of_use". `updated_at` is set by hand because `.update()` skips auto_now,
and it is what the restrictions panel shows as the date Trazo read the text.

Text verified against the eCFR versioner API, Title 7 part 205 up to date as of 2026-11-03, fetched
2026-11-05. Frozen here rather than imported - a migration must replay identically forever.
"""

import datetime
import re

from django.db import migrations
from django.utils import timezone

# (i)(2)'s proviso. The words before it ("copper hydroxide, copper oxide, copper oxychloride,
# includes products exempted from EPA tolerance") list the forms covered, not a condition.
COPPERS_FIXED = (
    "Copper-based materials must be used in a manner that minimizes accumulation in the soil and shall not be used "
    "as herbicides."
)
MICRONUTRIENTS = (
    "Not to be used as a defoliant, herbicide, or desiccant. Those made from nitrates or chlorides are not allowed. "
    "Micronutrient deficiency must be documented by soil or tissue testing or other documented and verifiable method "
    "as approved by the certifying agent."
)
J7_EFFECTIVE = datetime.date(2019, 1, 28)

ROWS = [
    ("Copper hydroxide", COPPERS_FIXED, None),
    ("Copper oxide", COPPERS_FIXED, None),
    ("Copper oxychloride", COPPERS_FIXED, None),
    (
        "Copper sulfate (fungicide)",
        "Substance must be used in a manner that minimizes accumulation of copper in the soil.",
        None,
    ),
    ("Magnesium sulfate", "Allowed with a documented soil deficiency.", None),
    ("Soluble boron products", MICRONUTRIENTS, J7_EFFECTIVE),
    (
        "Zinc/copper/iron/manganese/molybdenum/selenium/cobalt (sulfates, carbonates, oxides, silicates)",
        MICRONUTRIENTS,
        J7_EFFECTIVE,
    ),
]


def _normalize(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def store(apps, schema_editor):
    Substance = apps.get_model("certifications", "NationalListSubstance")
    now = timezone.now()
    for name, notes, effective in ROWS:
        Substance.objects.filter(cfr_section="205.601", substance_name_normalized=_normalize(name)).update(
            restriction_notes=notes, effective_date=effective, updated_at=now
        )


class Migration(migrations.Migration):
    dependencies = [("certifications", "0070_plan_material_category_unset")]

    # Reverse is a no-op: the old wording was a paraphrase, and for boron a superseded one.
    operations = [migrations.RunPython(store, migrations.RunPython.noop)]
