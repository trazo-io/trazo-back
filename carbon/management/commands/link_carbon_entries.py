"""Link unlinked CarbonEntry rows to their activity, under migration carbon 0047's rule.

Run once after the deploy that ships the link: rows written by the previous containers while the
new ones started have no link yet. Also after restoring entries from a fixture taken before the
link existed. Idempotent; only the link column is written (`.update()`, no save, no signal).
Dry run unless --apply.
"""

from django.core.management.base import BaseCommand

from carbon.event_link import link_all_unlinked


class Command(BaseCommand):
    help = "Link unlinked carbon entries to the activity their writer's text names (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the links (default: dry run).")

    def handle(self, *args, **options):
        counts = link_all_unlinked(apply=options["apply"])
        verb = "linked" if options["apply"] else "would link"
        self.stdout.write(
            f"{verb} {counts['linked']} of {counts['named']} entries whose text names an event; "
            f"left unlinked: {counts['user_created']} created by a user through the API, "
            f"{counts['event_gone']} whose event is gone, {counts['other_production']} in another production."
        )
        if not options["apply"]:
            self.stdout.write("Dry run: nothing written. Re-run with --apply.")
