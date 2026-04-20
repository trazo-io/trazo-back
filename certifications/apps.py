from django.apps import AppConfig


class CertificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "certifications"
    verbose_name = "Certifications"

    def ready(self):
        import certifications.auditlog_registry  # noqa: F401  Register OSP/affidavit audit trail (Sprint 5A)
        import certifications.signals  # noqa: F401
