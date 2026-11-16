"""Report operations whose records may be fabricated but are not marked as specimens.

WHY THIS EXISTS
---------------
Everything that keeps invented records from presenting as a real certified farm keys on ONE
column: `Establishment.is_demo`. `common/specimen.py` reads it to stamp exported packets, the
transparency payload reads it for the page banner, and (since 2026-09-08)
`consumer_certification_status` and `ConsumerClaimValidator` read it to refuse a
"Verified via USDA Organic Integrity Database" claim on a fabricated operation.

That flag is opt-IN, deliberately: marking a REAL operation's § 205.103 records "SPECIMEN" would
invite a certifier to reject a legitimate filing, so `is_specimen()` never guesses toward
marking. The cost of that correct default is that a fabricated operation seeded BEFORE the flag
existed (added 2026-08-21), or created by a path that never set it, bypasses every one of those
controls — silently, and on an anonymous consumer page.

MEASURED on a dev database 2026-09-08: two unflagged operations were publishing
"Verified via USDA Organic Integrity Database" from invented records, one of them seeded by a
command that sets `is_demo = True` today. Eighteen more unflagged operations with obviously
seeded names were publishing without a verified badge.

WHAT THIS COMMAND IS, AND IS NOT
--------------------------------
It is a READ-ONLY REPORT. It writes nothing, changes nothing, and returns rows for a human to
judge.

⛔ It deliberately does not offer to fix anything. Deciding an operation is fabricated is a
judgment about a customer relationship, not a string match: flipping `is_demo` on a row that
turns out to belong to a genuine prospect stamps SPECIMEN across their certifier packet, which
is the exact harm the opt-in default exists to prevent. The name hints below are a prompt to
look, never a verdict.

USAGE
    poetry run python manage.py audit_specimen_flags
    poetry run python manage.py audit_specimen_flags --all        # include unpublished
    poetry run python manage.py audit_specimen_flags --fail-on-risk   # non-zero exit for CI

In production:
    doctl apps console <APP_ID> trazo-back
    poetry run python manage.py audit_specimen_flags
"""

from django.core.management.base import BaseCommand

from certifications.models import Certification
from company.models import Establishment
from history.models import Production

#: Substrings in a name, contact address or description that suggest seeded data. A PROMPT TO
#: LOOK, not a verdict — real farms are called "Test Valley" and real people use example.com in
#: a hurry. Anything matching still needs a human to say whether the records are invented.
SEEDED_NAME_HINTS = ("demo", "test", "sample", "example", "showcase", "fixture", "dummy", "lorem")


class Command(BaseCommand):
    help = "Report unmarked operations whose records may be fabricated. Read-only; writes nothing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include operations with no published season (public exposure is the default filter).",
        )
        parser.add_argument(
            "--fail-on-risk",
            action="store_true",
            help="Exit non-zero when an unflagged operation publishes a registry-verified badge.",
        )

    def handle(self, *args, **options):
        include_unpublished = options["all"]
        rows = []

        for establishment in Establishment.objects.filter(is_demo=False).select_related("company"):
            published = Production.objects.filter(parcel__establishment=establishment, published=True).count()
            if not published and not include_unpublished:
                continue

            certs = list(Certification.objects.filter(establishment=establishment))
            # The claim that matters: this is what the consumer page would have shown before
            # 2026-09-08, and still shows for any operation that is not flagged.
            verified = [c for c in certs if c.consumer_display_status == "verified_via_database"]

            haystack = " ".join(
                str(value or "")
                for value in (
                    establishment.name,
                    establishment.contact_email,
                    establishment.description,
                    establishment.company.name if establishment.company else "",
                )
            ).lower()
            hints = sorted({hint for hint in SEEDED_NAME_HINTS if hint in haystack})

            if verified or hints:
                rows.append(
                    {
                        "id": establishment.id,
                        "name": establishment.name or "",
                        "published": published,
                        "verified": len(verified),
                        "hints": hints,
                    }
                )

        # Highest stakes first: an unflagged operation asserting a registry match from records
        # nobody has confirmed are real.
        rows.sort(key=lambda r: (-r["verified"], -r["published"], r["id"]))

        at_risk = [r for r in rows if r["verified"] and r["published"]]

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Operations NOT marked as specimens, worth a look"))
        self.stdout.write("(read-only report — nothing has been changed)")
        self.stdout.write("")

        if not rows:
            self.stdout.write(self.style.SUCCESS("  None. Every unflagged operation looks genuine on both signals."))
        else:
            self.stdout.write(f"  {'est':>5}  {'published':>9}  {'verified':>8}  {'name':34s}  hints")
            for row in rows:
                style = self.style.ERROR if (row["verified"] and row["published"]) else self.style.WARNING
                self.stdout.write(
                    style(
                        f"  {row['id']:5d}  {row['published']:9d}  {row['verified']:8d}  "
                        f"{row['name'][:34]:34s}  {','.join(row['hints']) or '-'}"
                    )
                )

        self.stdout.write("")
        if at_risk:
            self.stdout.write(
                self.style.ERROR(
                    f"  {len(at_risk)} operation(s) publish a page asserting "
                    f'"Verified via USDA Organic Integrity Database" while unmarked.'
                )
            )
            self.stdout.write(
                "  If those records are invented, that claim is on an anonymous consumer page now.\n"
                "  ⛔ Do not flip `is_demo` from this list alone: it stamps SPECIMEN across the\n"
                "     operation's certifier packet, and a wrong call there is worse than the gap."
            )
        else:
            self.stdout.write(self.style.SUCCESS("  No unflagged operation is publishing a registry-verified claim."))
        self.stdout.write("")

        if options["fail_on_risk"] and at_risk:
            raise SystemExit(1)
