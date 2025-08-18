"""
Django management command for API key rotation
Usage: python manage.py rotate_api_keys [service_name] [--new-key=KEY] [--check-only] [--force]
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from carbon.services.api_key_rotation import api_key_rotation_service


class Command(BaseCommand):
    help = "Rotate API keys for external services"

    def add_arguments(self, parser):
        parser.add_argument(
            "service",
            nargs="?",
            type=str,
            help='Service to rotate keys for (usda_nass, usda_ers, usda_fooddata, stripe, or "all")',
        )

        parser.add_argument("--new-key", type=str, help="New API key to use (required for rotation)")

        parser.add_argument(
            "--check-only", action="store_true", help="Only check rotation status, do not perform rotation"
        )

        parser.add_argument("--force", action="store_true", help="Force rotation even if not needed")

        parser.add_argument(
            "--emergency", action="store_true", help="Emergency rotation mode (security incident response)"
        )

        parser.add_argument("--validate-only", type=str, help="Only validate the provided API key without storing it")

    def handle(self, *args, **options):
        try:
            service = options.get("service")
            new_key = options.get("new_key")
            check_only = options.get("check_only")
            force = options.get("force")
            emergency = options.get("emergency")
            validate_only = options.get("validate_only")

            # Emergency rotation
            if emergency:
                self.handle_emergency_rotation()
                return

            # Check only mode
            if check_only or not service:
                self.handle_check_status()
                return

            # Validate only mode
            if validate_only:
                self.handle_validate_key(service, validate_only)
                return

            # Single service rotation
            if service and service != "all":
                self.handle_single_rotation(service, new_key, force)
                return

            # All services rotation
            if service == "all":
                self.handle_all_rotation(new_key, force)
                return

            # No valid action specified
            self.stdout.write(
                self.style.WARNING(
                    "No action specified. Use --check-only to check status or provide a service name to rotate."
                )
            )

        except Exception as e:
            raise CommandError(f"Command failed: {e}")

    def handle_check_status(self):
        """Check rotation status for all services"""
        self.stdout.write(self.style.HTTP_INFO("🔍 Checking API key rotation status...\n"))

        try:
            results = api_key_rotation_service.check_all_services()

            self.stdout.write(
                f"{'Service':<15} {'Needs Rotation':<15} {'Has Key':<10} {'Last Rotation':<20} {'Critical':<10}"
            )
            self.stdout.write("-" * 80)

            for service_name, status in results.items():
                needs_rotation = "YES" if status.get("needs_rotation", False) else "NO"
                has_key = "YES" if status.get("has_key", False) else "NO"
                last_rotation = status.get("last_rotation", "Never")
                critical = "YES" if status.get("critical", False) else "NO"
                error = status.get("error")

                if isinstance(last_rotation, str) and "T" in last_rotation:
                    try:
                        dt = timezone.datetime.fromisoformat(last_rotation.replace("Z", "+00:00"))
                        last_rotation = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        pass

                # Color coding
                if error:
                    style = self.style.ERROR
                elif needs_rotation and critical:
                    style = self.style.WARNING
                elif needs_rotation:
                    style = self.style.NOTICE
                else:
                    style = self.style.SUCCESS

                line = f"{service_name:<15} {needs_rotation:<15} {has_key:<10} {str(last_rotation):<20} {critical:<10}"

                if error:
                    line += f" ERROR: {error}"

                self.stdout.write(style(line))

            # Summary
            total_services = len(results)
            needing_rotation = sum(1 for s in results.values() if s.get("needs_rotation", False))
            critical_needing = sum(
                1 for s in results.values() if s.get("needs_rotation", False) and s.get("critical", False)
            )

            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(f"Summary: {total_services} services checked")

            if needing_rotation > 0:
                self.stdout.write(self.style.WARNING(f"⚠️  {needing_rotation} services need rotation"))
                if critical_needing > 0:
                    self.stdout.write(self.style.ERROR(f"🚨 {critical_needing} CRITICAL services need rotation"))
            else:
                self.stdout.write(self.style.SUCCESS("✅ All services up to date"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Status check failed: {e}"))

    def handle_single_rotation(self, service_name: str, new_key: str, force: bool):
        """Handle rotation for a single service"""
        try:
            # Validate service name
            valid_services = list(api_key_rotation_service.service_configs.keys())
            if service_name not in valid_services:
                raise CommandError(f"Invalid service '{service_name}'. Valid services: {', '.join(valid_services)}")

            # Check if rotation is needed
            if not force:
                needs_rotation = api_key_rotation_service.check_rotation_needed(service_name)
                if not needs_rotation:
                    self.stdout.write(
                        self.style.WARNING(
                            f"⏸️  Service '{service_name}' does not need rotation. Use --force to rotate anyway."
                        )
                    )
                    return

            # Require new key for rotation
            if not new_key:
                raise CommandError(f"New API key required for {service_name} rotation. Use --new-key=YOUR_KEY")

            self.stdout.write(f"🔄 Rotating API key for {service_name}...")

            # Perform rotation
            success = api_key_rotation_service.rotate_api_key(service_name, new_key)

            if success:
                self.stdout.write(self.style.SUCCESS(f"✅ Successfully rotated API key for {service_name}"))
            else:
                self.stdout.write(self.style.ERROR(f"❌ Failed to rotate API key for {service_name}"))
                raise CommandError("Rotation failed")

        except Exception as e:
            raise CommandError(f"Single rotation failed: {e}")

    def handle_all_rotation(self, new_key: str, force: bool):
        """Handle rotation for all services"""
        self.stdout.write(self.style.WARNING("⚠️  All services rotation requires individual keys"))
        self.stdout.write("Use individual service rotation instead:")

        valid_services = list(api_key_rotation_service.service_configs.keys())
        for service in valid_services:
            self.stdout.write(f"  python manage.py rotate_api_keys {service} --new-key=YOUR_{service.upper()}_KEY")

    def handle_validate_key(self, service_name: str, api_key: str):
        """Validate an API key without storing it"""
        try:
            valid_services = list(api_key_rotation_service.service_configs.keys())
            if service_name not in valid_services:
                raise CommandError(f"Invalid service '{service_name}'. Valid services: {', '.join(valid_services)}")

            self.stdout.write(f"🔍 Validating API key for {service_name}...")

            is_valid = api_key_rotation_service.validate_api_key(service_name, api_key)

            if is_valid:
                self.stdout.write(self.style.SUCCESS(f"✅ API key is valid for {service_name}"))
            else:
                self.stdout.write(self.style.ERROR(f"❌ API key is invalid for {service_name}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Validation failed: {e}"))

    def handle_emergency_rotation(self):
        """Handle emergency rotation mode"""
        self.stdout.write(self.style.ERROR("🚨 EMERGENCY ROTATION MODE"))
        self.stdout.write("This will attempt to rotate ALL API keys immediately.")
        self.stdout.write("New keys must be provided manually as this is a security incident response.")

        confirm = input("Are you sure you want to proceed? (type 'EMERGENCY' to confirm): ")
        if confirm != "EMERGENCY":
            self.stdout.write("Emergency rotation cancelled.")
            return

        try:
            results = api_key_rotation_service.emergency_rotate_all()

            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("EMERGENCY ROTATION RESULTS:")
            self.stdout.write("=" * 60)

            for service, success in results.items():
                if success:
                    self.stdout.write(self.style.SUCCESS(f"✅ {service}: SUCCESS"))
                else:
                    self.stdout.write(self.style.ERROR(f"❌ {service}: FAILED"))

            failed_services = [s for s, success in results.items() if not success]
            if failed_services:
                self.stdout.write(
                    self.style.ERROR(f"\n⚠️  MANUAL INTERVENTION REQUIRED for: {', '.join(failed_services)}")
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Emergency rotation failed: {e}"))
