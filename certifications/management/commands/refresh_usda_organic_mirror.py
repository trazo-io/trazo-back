"""Keep the USDA Organic Integrity mirror within a day of USDA's monthly export (2026-11-13).

WHY. The organic badge is decided against a LOCAL copy of the Integrity database, and nothing
refreshed it: the importer was run by hand, last on the 2026-08-01 export, and `/health/` reported
it 104 days old on 2026-11-13. A stale mirror is wrong in both directions at once: a farm certified
since the snapshot is publicly labelled not independently verified, and a farm that surrendered
keeps its badge. The monthly re-verification job did run, against the same old copy every time.

WHY DAILY AND NOT ON THE 1ST. USDA posts each month's export some days into the month, so the
monthly job (04:00 Pacific on the 1st) would usually find nothing new and leave the mirror a month
behind. This runs every day and does nothing until a newer month exists: one comparison of dates,
no download, on most days.

WHAT IT DOES ON A NEW MONTH. Download, import through `import_usda_organic_data` (which keeps its
refusal to replace good data with an implausible parse), then `reverify_certifications --all`,
because the import alone changes no certificate.

WHEN IT FAILS THE RUN. Only when the mirror is more than one month behind and no newer export can be
downloaded, or when the import or re-verification fails. "This month is not published yet, and we
hold last month's" is the normal state for the first days of a month and is not a failure.
"""

import os
from datetime import date

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max
from django.utils import timezone

from certifications.management.commands.import_usda_organic_data import USDA_MONTHLY_URL, download_export
from certifications.models import USDAOrganicOperation


def _previous_month(first_of_month: date) -> date:
    if first_of_month.month == 1:
        return first_of_month.replace(year=first_of_month.year - 1, month=12)
    return first_of_month.replace(month=first_of_month.month - 1)


class Command(BaseCommand):
    help = "Import the newest USDA Organic Integrity export if it is newer than the mirror, then re-verify."

    def handle(self, *args, **options):
        held = USDAOrganicOperation.objects.aggregate(latest=Max("data_snapshot_date"))["latest"]
        this_month = timezone.now().date().replace(day=1)
        last_month = _previous_month(this_month)

        if held and held >= this_month:
            self.stdout.write(f"USDA mirror is current (snapshot {held}); nothing to do.")
            return

        snapshot, path = this_month, self._download(this_month)
        if path is None:
            if held and held >= last_month:
                self.stdout.write(
                    f"USDA has not published the {this_month:%Y-%m} export yet; the mirror holds {held}, "
                    "one cycle behind at most. Nothing to do."
                )
                return
            snapshot, path = last_month, self._download(last_month)
        if path is None:
            raise CommandError(
                f"The USDA mirror holds {held or 'nothing'} and neither the {this_month:%Y-%m} nor the "
                f"{last_month:%Y-%m} export could be downloaded. Organic badges are being decided on "
                "stale data. Check the URL in import_usda_organic_data and the download errors above."
            )

        try:
            call_command(
                "import_usda_organic_data",
                file=path,
                date=snapshot.strftime("%Y%m%d"),
                stdout=self.stdout._out,
                stderr=self.stderr._out,
            )
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

        call_command("reverify_certifications", all=True, stdout=self.stdout._out, stderr=self.stderr._out)

    def _download(self, first_of_month: date):
        url = USDA_MONTHLY_URL.format(date=first_of_month.strftime("%Y%m%d"))
        self.stdout.write(f"Trying {url}")
        return download_export(url, self.stdout.write, self.stderr.write)
