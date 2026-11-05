"""Write history/taxonomy.json, the snapshot of history/taxonomy.py the frontend parity tests read.

The frontend CI checks this repo out as a sibling and compares its own event registry against the
snapshot. `history/tests/test_taxonomy.py` fails when the snapshot is stale.

    manage.py export_event_taxonomy
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from history.taxonomy import snapshot

SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "taxonomy.json"


def render() -> str:
    return json.dumps(snapshot(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write history/taxonomy.json from history/taxonomy.py."

    def handle(self, *args, **options):
        SNAPSHOT_PATH.write_text(render(), encoding="utf-8")
        self.stdout.write(f"wrote {SNAPSHOT_PATH}")
