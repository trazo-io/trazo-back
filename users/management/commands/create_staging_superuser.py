from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Creates staging superuser and optionally runs seed data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            action="store_true",
            help="Also run the comprehensive demo seed after creating user",
        )

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

        # Run seed if requested
        if options["seed"]:
            self.stdout.write(self.style.WARNING("\n🌱 Running comprehensive demo seed..."))
            try:
                call_command("seed_comprehensive_demo_ultimate")
                self.stdout.write(self.style.SUCCESS("✅ Seed data loaded successfully!"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error running seed: {str(e)}"))
