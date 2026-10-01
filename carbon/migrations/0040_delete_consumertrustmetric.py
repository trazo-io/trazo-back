"""Delete ConsumerTrustMetric: five self-graded 0-100 columns that nothing ever wrote.

overall_trust_score, data_completeness_score, verification_score, transparency_score and
consistency_score, each a FloatField validated 0 to 100, plus trust_factors and
improvement_areas JSON blobs, on a OneToOne to History. A consumer trust score is the
self-created sustainability label EU ECGT 2024/825 (live 2026-09-27) bans without
third-party verification.

No row could exist except by hand. The only references in the codebase were an unused
import in carbon/serializers.py and copy_production_to_parcel, which copied a row if it
found one. No view, serializer, service, task or seeder ever created one.

Deleted rather than left dormant because an empty table with five grade columns and a
OneToOne to History is an invitation: the next person wiring a trust widget finds a ready
schema and the claim returns with no discussion. Same reasoning the retired-route register
applies to URLs.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0039_drop_carbon_report_score"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ConsumerTrustMetric",
        ),
    ]
