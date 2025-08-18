"""
Management command to migrate secrets from environment variables to secure storage
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from backend.security import secure_key_manager


class Command(BaseCommand):
    help = "Migrate secrets from environment variables to secure storage"

    # Define the secrets to migrate
    SECRETS_TO_MIGRATE = [
        ("blockchain_private_key", "BLOCKCHAIN_PRIVATE_KEY", "Blockchain private key for Polygon network"),
        ("usda_api_key", "USDA_API_KEY", "USDA API key for agricultural data"),
        ("usda_fdc_api_key", "USDA_FDC_API_KEY", "USDA FoodData Central API key"),
        ("usda_nass_api_key", "USDA_NASS_API_KEY", "USDA NASS API key"),
        ("stripe_secret_key", "STRIPE_SECRET_KEY", "Stripe secret key for payments"),
        ("stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET", "Stripe webhook secret"),
        ("openai_api_key", "OPENAI_API_KEY", "OpenAI API key for voice processing"),
        ("sendgrid_api_key", "SENDGRID_API_KEY", "SendGrid API key for email"),
        ("aws_access_key_id", "AWS_ACCESS_KEY_ID", "AWS access key ID"),
        ("aws_secret_access_key", "AWS_SECRET_ACCESS_KEY", "AWS secret access key"),
        ("google_client_secret", "GOOGLE_CLIENT_SECRET", "Google OAuth client secret"),
        ("facebook_app_secret", "FACEBOOK_APP_SECRET", "Facebook app secret"),
        ("apple_private_key", "APPLE_PRIVATE_KEY", "Apple Sign In private key"),
        ("icr_api_key", "ICR_API_KEY", "International Carbon Registry API key"),
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without actually migrating",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force migration even if secrets already exist",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        self.stdout.write(self.style.SUCCESS("Starting secrets migration..."))

        # Check secure key manager health
        health = secure_key_manager.health_check()
        if health["status"] == "unhealthy":
            self.stdout.write(self.style.ERROR(f'Secure key manager is unhealthy: {health["issues"]}'))
            return

        migrated_count = 0
        skipped_count = 0

        for secret_name, env_var, description in self.SECRETS_TO_MIGRATE:
            env_value = os.environ.get(env_var)

            if not env_value:
                self.stdout.write(self.style.WARNING(f"Skipping {secret_name}: Environment variable {env_var} not set"))
                skipped_count += 1
                continue

            # Check if secret already exists
            existing_secret = secure_key_manager.get_secret(secret_name)
            if existing_secret and not force:
                self.stdout.write(self.style.WARNING(f"Skipping {secret_name}: Already exists in secure storage"))
                skipped_count += 1
                continue

            if dry_run:
                self.stdout.write(self.style.SUCCESS(f"Would migrate {secret_name} from {env_var}"))
                migrated_count += 1
                continue

            # Migrate the secret
            if secure_key_manager.store_secret(secret_name, env_value, description):
                self.stdout.write(self.style.SUCCESS(f"Migrated {secret_name} from {env_var}"))
                migrated_count += 1
            else:
                self.stdout.write(self.style.ERROR(f"Failed to migrate {secret_name} from {env_var}"))
                skipped_count += 1

        self.stdout.write(self.style.SUCCESS(f"Migration complete: {migrated_count} migrated, {skipped_count} skipped"))

        if not dry_run and migrated_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    "IMPORTANT: Remove the migrated environment variables from your .env file "
                    "and deployment configuration for security."
                )
            )

    def list_current_secrets(self):
        """List current secrets in secure storage"""
        secrets = secure_key_manager.list_secrets()

        if not secrets:
            self.stdout.write("No secrets found in secure storage")
            return

        self.stdout.write(self.style.SUCCESS("Current secrets in secure storage:"))
        for secret_name, metadata in secrets.items():
            self.stdout.write(
                f'  - {secret_name}: {metadata["description"]} ' f'(last changed: {metadata["last_changed"]})'
            )
