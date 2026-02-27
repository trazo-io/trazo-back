"""
Data migration: Convert old role codes to new simplified role system.

DS (Domain Supervisor) -> FM (Farm Manager)
DW (Domain Worker) -> VW (Viewer)
DE (Dealer) -> VW (Viewer)
"""

from django.db import migrations


def convert_roles_forward(apps, schema_editor):
    WorksIn = apps.get_model("users", "WorksIn")
    CompanyInvitation = apps.get_model("users", "CompanyInvitation")

    # Convert WorksIn roles
    WorksIn.objects.filter(role="DS").update(role="FM")
    WorksIn.objects.filter(role="DW").update(role="VW")
    WorksIn.objects.filter(role="DE").update(role="VW")

    # Convert CompanyInvitation roles
    CompanyInvitation.objects.filter(role="DS").update(role="FM")
    CompanyInvitation.objects.filter(role="DW").update(role="VW")
    CompanyInvitation.objects.filter(role="DE").update(role="VW")


def convert_roles_reverse(apps, schema_editor):
    WorksIn = apps.get_model("users", "WorksIn")
    CompanyInvitation = apps.get_model("users", "CompanyInvitation")

    # Reverse: FM -> DS, VW -> DW (DE data is lost in reverse)
    WorksIn.objects.filter(role="FM").update(role="DS")
    WorksIn.objects.filter(role="VW").update(role="DW")

    CompanyInvitation.objects.filter(role="FM").update(role="DS")
    CompanyInvitation.objects.filter(role="VW").update(role="DW")


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0011_user_company_verified_passwordresettoken_and_more"),
    ]

    operations = [
        migrations.RunPython(convert_roles_forward, convert_roles_reverse),
    ]
