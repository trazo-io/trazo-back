"""
Re-derive every committed form inventory whose source file is in --sources, and fail on any change.

    poetry run python manage.py verify_form_inventory --sources ~/sources

Run whenever an agent's form is re-fetched. A source whose sha256 differs from the inventory's is a
new edition: re-run `extract_form_inventory` for it and review the diff against the register.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from certifications.services.certifier_register import certifiers
from certifications.services.form_inventory import derive_items, inventory_dir, load_inventory, sha256_of


class Command(BaseCommand):
    help = "Check committed form inventories against their source files."

    def add_arguments(self, parser):
        parser.add_argument("--sources", required=True, help="folder holding the agents' PDF/DOCX files")

    def handle(self, *args, sources, **options):
        folder = Path(sources).expanduser()
        problems, checked, missing = [], 0, []
        for agent in certifiers():
            for path in sorted(inventory_dir(agent).glob("*.yaml")):
                inventory = load_inventory(path)
                source = folder / inventory.source_file
                if not source.is_file():
                    missing.append(f"{agent}/{path.name}: {inventory.source_file}")
                    continue
                checked += 1
                if sha256_of(source) != inventory.sha256:
                    problems.append(f"{agent}/{path.name}: {source.name} is a different file (sha256 changed)")
                    continue
                derived = derive_items(
                    agent, source, inventory.overrides, "" if inventory.extracted else "none", path.name
                )
                if tuple(derived) != inventory.items:
                    have = {i.ref for i in inventory.items}
                    got = {i.ref for i in derived}
                    problems.append(
                        f"{agent}/{path.name}: re-derived items differ "
                        f"(only committed: {sorted(have - got)}; only derived: {sorted(got - have)})"
                    )
        for line in missing:
            self.stdout.write(f"not checked, source not in folder: {line}")
        if problems:
            raise CommandError("\n".join(problems))
        self.stdout.write(self.style.SUCCESS(f"{checked} inventories match their sources."))
