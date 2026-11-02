"""Bring the OCCSP line of the renewal-deadlines FAQ to FSA's 2025/2026 terms on deployed databases.

Why a migration and not the seeder: deploys run only `migrate` (start.sh), and
`seed_education_content` is create-only unless run with `--refresh`, so a corrected line in the
seeder never reaches a database seeded once. Only the OCCSP line is rewritten, and only on the
row that carries it; the rest of the answer is left exactly as it is. A fresh database has no row
here and gets the same text from the seeder.

Source: FSA, "USDA Helps Organic Producers with Certification Costs", July 2, 2026,
https://www.fsa.usda.gov/news-events/news/07-02-2026/usda-helps-organic-producers-certification-costs

Frozen here rather than imported from the seeder: a migration must replay identically.
"""

from django.db import migrations

QUESTION = "What deadlines matter for renewal season?"
LINE_PREFIX = "- **OCCSP cost-share**"
NEW_LINE = (
    "- **OCCSP cost-share** (USDA Farm Service Agency): applications for the **2025 and 2026 program "
    "years** are due **December 31, 2026**, at your county FSA office or a participating state agency. "
    "It reimburses up to 75% of eligible certification costs, up to $750 per certification scope "
    "(crops, wild crops, livestock, processing/handling, state organic program fees). Eligible costs "
    "are the fees of USDA organic certification itself (application, inspection, state program and "
    "assessment fees) and related postage; recordkeeping software, Trazo included, is not on FSA's "
    "list. FSA pays first come, first served until funds run out (FSA announcement, July 2, 2026)"
)


def rewrite_occsp_line(apps, schema_editor):
    FarmerQuestionAnswer = apps.get_model("education", "FarmerQuestionAnswer")
    for faq in FarmerQuestionAnswer.objects.filter(question=QUESTION):
        lines = faq.answer.split("\n")
        rewritten = [NEW_LINE if line.startswith(LINE_PREFIX) else line for line in lines]
        if rewritten != lines:
            faq.answer = "\n".join(rewritten)
            faq.save(update_fields=["answer", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("education", "0002_alter_farmerquestionanswer_category"),
    ]

    operations = [
        migrations.RunPython(rewrite_occsp_line, migrations.RunPython.noop),
    ]
