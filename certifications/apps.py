from django.apps import AppConfig


class CertificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "certifications"
    verbose_name = "Certifications"

    def ready(self):
        import certifications.signals  # noqa: F401
