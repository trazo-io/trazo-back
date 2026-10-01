"""
Derive (or re-derive) one register form's official question inventory from its source file.

    poetry run python manage.py extract_form_inventory ccof Certification-Contract \
        --source ~/sources/CCOF-Certification-Contract-NOPB06.pdf --retrieved 2026-09-30

Overrides already recorded in the inventory are kept and re-applied, so re-running after a form is
re-fetched shows exactly what the new edition changed. See certifications/services/form_inventory.py.
"""

import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

import yaml

from certifications.services.certifier_register import forms_dir
from certifications.services.form_inventory import (
    derive_items,
    extract_revision,
    inventory_path,
    sha256_of,
    write_inventory,
)


class Command(BaseCommand):
    help = "Derive a register form's official question inventory from its source PDF or DOCX."

    def add_arguments(self, parser):
        parser.add_argument("agent")
        parser.add_argument("form", help="register form file stem, e.g. Certification-Contract")
        parser.add_argument("--source", required=True, help="the agent's PDF or DOCX")
        parser.add_argument("--url", default="", help="where the source file was downloaded from")
        parser.add_argument("--retrieved", default=str(datetime.date.today()))

    def handle(self, *args, agent, form, source, url, retrieved, **options):
        form_path = forms_dir(agent) / f"{form}.yaml"
        if not form_path.is_file():
            raise CommandError(f"No register form {form_path}")
        source_path = Path(source).expanduser()
        target = inventory_path(form_path)
        overrides, extraction = [], ""
        if target.is_file():
            existing = yaml.safe_load(target.read_text()) or {}
            overrides = existing.get("overrides") or []
            extraction = existing.get("extraction") or ""
            url = url or (existing.get("source") or {}).get("url", "")
        items = derive_items(agent, source_path, overrides, extraction, target.name)
        write_inventory(
            target,
            source={
                "file": source_path.name,
                "url": url,
                "sha256": sha256_of(source_path),
                "revision": extract_revision(source_path),
                "retrieved": retrieved,
            },
            items=items,
            overrides=overrides,
            extraction=extraction,
        )
        self.stdout.write(self.style.SUCCESS(f"Wrote {target} ({len(items)} items, {len(overrides)} overrides)"))
