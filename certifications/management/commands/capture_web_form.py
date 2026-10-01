"""
Capture one Gravity Form from an agent's web page as a source file for its form inventory.

    poetry run python manage.py capture_web_form https://www.ccof.org/payments/ 5 \
        --out CCOF-Annual-Renewal-Contract.html

A web form has no file to hash and prints no revision. The capture keeps the one form, drops what
changes on every page load, and records the URL and date in its first line, which
`extract_revision` reads as its edition. See certifications/services/form_inventory.py.
"""

import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

import requests

from certifications.services.form_inventory import capture_gravity_form, sha256_of

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


class Command(BaseCommand):
    help = "Capture a Gravity Form from a web page as a form-inventory source."

    def add_arguments(self, parser):
        parser.add_argument("url")
        parser.add_argument("form_id", help="the Gravity Form id, e.g. 5 for gform_5")
        parser.add_argument("--out", required=True)
        parser.add_argument("--captured", default=str(datetime.date.today()))

    def handle(self, *args, url, form_id, out, captured, **options):
        response = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
        if response.status_code != 200:
            raise CommandError(f"{url} answered {response.status_code}")
        try:
            capture = capture_gravity_form(response.text, str(form_id), url, captured)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        path = Path(out).expanduser()
        path.write_text(capture, encoding="utf-8")
        self.stdout.write(f"Wrote {path} (sha256 {sha256_of(path)})")
