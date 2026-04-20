from django.apps import AppConfig


class CompanyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "company"

    def ready(self):
        # Register Establishment with django-auditlog so OFPP / split-operation /
        # certifier-relevant changes are captured for NOP audit purposes (Sprint 2.1).
        from auditlog.registry import auditlog

        from company.models import Establishment

        auditlog.register(Establishment)
