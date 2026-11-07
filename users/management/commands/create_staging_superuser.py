from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Creates staging superuser"

    def handle(self, *args, **options):
        User = get_user_model()

        # Create superuser
        email = "oscar@trazo.io"
        password = "om123456"

        # Delete existing user if any
        if User.objects.filter(email=email).exists():
            User.objects.filter(email=email).delete()
            self.stdout.write(self.style.WARNING(f"Deleted existing user: {email}"))

        # Create new superuser
        user = User.objects.create_user(
            username=email, email=email, password=password, is_staff=True, is_superuser=True, is_active=True
        )

        self.stdout.write(self.style.SUCCESS(f"✅ Superuser created successfully: {email}"))
        self.stdout.write(self.style.SUCCESS(f"   Password: {password}"))
