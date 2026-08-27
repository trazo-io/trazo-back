from django.apps import AppConfig


class SecurityConfig(AppConfig):
    name = "backend.security"
    verbose_name = "Trazo Security"

    def ready(self):
        # Registers the deployment-time checks. Importing here rather than at module scope
        # is what makes them run: Django only imports `checks` if something asks it to.
        from . import checks  # noqa: F401
