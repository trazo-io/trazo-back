from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Changes password for a specific user by email"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            required=True,
            help="Email of the user to change password for",
        )
        parser.add_argument(
            "--password",
            type=str,
            required=True,
            help="New password to set",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        email = options["email"]
        password = options["password"]

        try:
            # Find the user by email
            user = User.objects.get(email=email)
            
            # Change the password using Django's built-in method (this handles hashing)
            user.set_password(password)
            user.save()
            
            self.stdout.write(
                self.style.SUCCESS(f"✅ Password changed successfully for user: {email}")
            )
            
        except User.DoesNotExist:
            raise CommandError(f"❌ User with email '{email}' does not exist")
        except Exception as e:
            raise CommandError(f"❌ Error changing password: {str(e)}")