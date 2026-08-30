"""
Management command to send one real email and report exactly what the provider said.

Exists because the SendGrid outage (2026-05 to 2026-08) was invisible: the account
had run out of credits, every send 401'd, and nothing surfaced it. A deploy is not
proof that email works -- only a send is.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send one test email through the configured backend and report the result"

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            required=True,
            help="Recipient address. Use an inbox you can actually check.",
        )
        parser.add_argument(
            "--from-email",
            default=None,
            help="Sender address. Defaults to DEFAULT_FROM_EMAIL.",
        )

    def handle(self, *args, **options):
        recipient = options["to"]
        sender = options["from_email"] or settings.DEFAULT_FROM_EMAIL

        self.stdout.write(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"from:          {sender}")
        self.stdout.write(f"to:            {recipient}")

        # A missing key must fail loudly here rather than be swallowed as a
        # "sent 0 messages" success -- that is the shape the outage took.
        connection = get_connection(fail_silently=False)

        message = EmailMultiAlternatives(
            subject="Trazo email delivery test",
            body=(
                "This is a delivery test sent by manage.py send_test_email.\n"
                "If you are reading it, outbound email works."
            ),
            from_email=sender,
            to=[recipient],
            connection=connection,
        )
        message.attach_alternative(
            "<p>This is a delivery test sent by <code>manage.py send_test_email</code>.</p>"
            "<p>If you are reading it, outbound email works.</p>",
            "text/html",
        )

        try:
            sent = message.send()
        except Exception as e:
            # The provider's own response body is in the exception text -- print it
            # rather than a generic failure, which is what hid the credit exhaustion.
            raise CommandError(f"Send FAILED: {e}")

        if sent != 1:
            raise CommandError(f"Send reported {sent} messages sent, expected 1.")

        self.stdout.write(self.style.SUCCESS("Send accepted by the provider."))
        self.stdout.write("Acceptance is not delivery -- confirm the message actually arrived in the inbox.")
