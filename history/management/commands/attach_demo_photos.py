"""Attach REAL photographs to a demonstration farm's event records.

WHY THIS EXISTS
---------------
`prune_misleading_demo_photos --stock` removed every library photograph from demo event albums,
because a stock image pinned to a dated record asserts that an operation happened. The demo
farms are now honest and photographless: the consumer page says "No photos for this batch —
the written records below still document the season."

The seeders cannot put them back. They attach photos at creation time from hardcoded Unsplash
pools (`AVOCADO_IMAGES`, `DEMO_IMAGES`), and re-running one would reintroduce exactly the defect
that was removed — plus, through `--reset`, re-mint every `public_id` and 404 every link already
sent. This command is the only supported way back: real photographs, from local files, uploaded
to Trazo's own bucket.

WHAT MAKES THIS SAFE WHERE THE SEEDERS WERE NOT
-----------------------------------------------
A manifest, written by a person, that pairs each file with the record it will illustrate AND a
mandatory `shows` line describing what is actually in the frame.

That field is the whole point. Four photographs survived two separate prunes in August because
they sat under key names that sounded right — `pruning`, `planting`, `organic_matter`,
`beneficial_insects` — while the frames showed a roped arborist in a leafy PINE, a studio
seedling, earthworms, and a ladybird standing in for a parasitic-wasp release. A key name is
not a vetting and a code comment is not evidence. Writing `shows` forces the operator to look
at the image and say what is in it, in a file that can be reviewed and diffed, next to the
event text it has to match.

The command prints both strings side by side during a dry run. Nothing here can check that they
agree — that judgement is the human's, and this exists to make the judgement unavoidable rather
than to replace it.

DELIBERATE LIMITS
-----------------
* DEMO establishments only (`Establishment.is_demo`). Attaching photographs to a real
  operation's records on their behalf is the authorship problem in § 205.201(a): the producer
  is the author of their own records. Real farms upload through the app.
* Local files only. A URL argument would let a stock host back in through the front door.
* Never overwrites. An event that already has photographs is skipped and reported, so a
  second run cannot silently duplicate or replace what a previous one placed.

MANIFEST
--------
    [
      {
        "event": "production:4719",
        "file": "shots/2026-01-12-dormant-pruning.jpg",
        "shows": "Chandler walnut, dormant, fresh pruning cuts on scaffold limbs"
      }
    ]

`event` is "<model>:<id>" where model is one of the eight event types
(production, chemical, soil, pest, weather, business, general, equipment).

USAGE
-----
    poetry run python manage.py attach_demo_photos --manifest shots/manifest.json
    poetry run python manage.py attach_demo_photos --manifest shots/manifest.json --apply
"""

import json
import mimetypes
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from common.models import Gallery, GalleryImage
from common.specimen import is_specimen
from history.management.commands.prune_misleading_demo_photos import STOCK_IMAGE_HOSTS
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)

EVENT_MODELS = {
    "production": ProductionEvent,
    "chemical": ChemicalEvent,
    "soil": SoilManagementEvent,
    "pest": PestManagementEvent,
    "weather": WeatherEvent,
    "business": BusinessEvent,
    "general": GeneralEvent,
    "equipment": EquipmentEvent,
}

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
#: 12 MB. Large enough for a phone photograph, small enough that a stray RAW file is refused.
MAX_BYTES = 12 * 1024 * 1024


class Command(BaseCommand):
    help = "Attach real local photographs to a demonstration farm's events, from a manifest."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, help="Path to the JSON manifest.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Upload and attach. Without it, the manifest is validated and printed only.",
        )

    # ---- validation ------------------------------------------------------

    def _resolve_event(self, ref):
        try:
            kind, raw_id = ref.split(":", 1)
        except ValueError:
            raise CommandError(f"`event` must look like 'production:4719', got {ref!r}")
        model = EVENT_MODELS.get(kind)
        if model is None:
            raise CommandError(f"unknown event kind {kind!r}; expected one of {', '.join(sorted(EVENT_MODELS))}")
        try:
            # Events carry no `parcel` FK of their own — they reach the establishment through
            # `history.parcel.establishment`. Asking for `parcel__establishment` here raised
            # FieldError on every entry.
            event = model.objects.select_related("history__parcel__establishment").get(id=int(raw_id))
        except (model.DoesNotExist, ValueError):
            raise CommandError(f"no {kind} event with id {raw_id}")
        return event

    def _establishment_of(self, event):
        parcel = getattr(getattr(event, "history", None), "parcel", None)
        return getattr(parcel, "establishment", None)

    def _validate_file(self, raw_path):
        # Tested on the RAW string, BEFORE Path() touches it. `Path("https://x/y")` collapses the
        # double slash to `https:/x/y`, so a check against the constructed path silently misses
        # every URL — it then failed as "file not found", which is luck rather than a rule. This
        # is the one input the command must never accept: a URL is how a library photograph gets
        # back in, and every host check downstream reads the stored value, not the intent.
        if str(raw_path).strip().lower().startswith(("http://", "https://", "//")):
            raise CommandError(f"`file` must be a local path, not a URL: {raw_path}")
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise CommandError(f"file not found: {path}")
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise CommandError(f"{path.name}: expected one of {', '.join(sorted(ALLOWED_SUFFIXES))}")
        size = path.stat().st_size
        if size > MAX_BYTES:
            raise CommandError(f"{path.name}: {size / 1e6:.1f} MB exceeds the {MAX_BYTES / 1e6:.0f} MB limit")
        if any(host in str(path).lower() for host in STOCK_IMAGE_HOSTS):
            raise CommandError(f"{path.name}: path names a stock library host")
        return path, size

    def _validate_s3_key(self, raw_key):
        """An object already in Trazo's own bucket, named by key.

        The key is checked for existence rather than trusted, because a typo would otherwise
        attach a working-looking image row that renders as a broken thumbnail — which is exactly
        the state the consumer page was in before the gallery fix.
        """
        key = str(raw_key).strip().lstrip("/")
        if key.lower().startswith(("http://", "https://", "//")):
            raise CommandError(
                f"`s3_key` is an object key, not a URL: {raw_key}. A URL would let a library "
                "host back in; keys resolve inside Trazo's own bucket."
            )
        if any(host in key.lower() for host in STOCK_IMAGE_HOSTS):
            raise CommandError(f"{key}: names a stock library host")
        if not default_storage.exists(key):
            raise CommandError(f"no object at key {key!r} in the configured bucket")
        try:
            size = default_storage.size(key)
        except Exception:
            size = 0
        return key, size

    # ---- main ------------------------------------------------------------

    def handle(self, *args, **options):
        manifest_path = Path(options["manifest"]).expanduser()
        if not manifest_path.is_file():
            raise CommandError(f"manifest not found: {manifest_path}")
        try:
            entries = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as exc:
            raise CommandError(f"manifest is not valid JSON: {exc}")
        if not isinstance(entries, list) or not entries:
            raise CommandError("manifest must be a non-empty JSON list")

        planned, skipped = [], []
        for index, entry in enumerate(entries, start=1):
            for field in ("event", "shows"):
                if not str(entry.get(field) or "").strip():
                    raise CommandError(
                        f"entry {index}: `{field}` is required. `shows` must describe what is "
                        "actually in the frame — that description is the only thing standing "
                        "between this command and the mislabelled photographs it replaces."
                    )
            has_file = bool(str(entry.get("file") or "").strip())
            has_key = bool(str(entry.get("s3_key") or "").strip())
            if has_file == has_key:
                raise CommandError(
                    f"entry {index}: give exactly one of `file` (a local path, uploaded by this "
                    "command) or `s3_key` (an object already in the bucket). `s3_key` exists "
                    "because this command is normally run in the production console, which "
                    "cannot see files on your machine."
                )
            event = self._resolve_event(entry["event"])
            establishment = self._establishment_of(event)
            if not is_specimen(establishment):
                raise CommandError(
                    f"entry {index}: {entry['event']} belongs to "
                    f"{getattr(establishment, 'name', 'an unknown establishment')!r}, which is not a "
                    "demonstration farm. A real operation's records are authored by the producer "
                    "(7 CFR 205.201(a)); photographs for those go through the app."
                )
            if event.album and event.album.images.exists():
                skipped.append((entry["event"], "already has photographs"))
                continue
            if has_file:
                path, size = self._validate_file(entry["file"])
                planned.append((entry, event, path, None, size))
            else:
                key, size = self._validate_s3_key(entry["s3_key"])
                planned.append((entry, event, None, key, size))

        # ---- report ------------------------------------------------------
        self.stdout.write(f"manifest: {manifest_path}  ({len(entries)} entries)\n")
        for entry, event, path, key, size in planned:
            description = (getattr(event, "description", "") or getattr(event, "name", "") or "").strip()
            label = path.name if path else f"s3:{key}"
            self.stdout.write(f"  {entry['event']}  <-  {label}  ({size / 1e6:.1f} MB)")
            self.stdout.write(f"      record : {description[:96] or '(no description)'}")
            self.stdout.write(f"      shows  : {entry['shows']}")
            self.stdout.write("")
        for ref, why in skipped:
            self.stdout.write(self.style.WARNING(f"  SKIP {ref} — {why}"))

        if not planned:
            self.stdout.write(self.style.WARNING("\nNothing to attach."))
            return

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN — {len(planned)} photograph(s) would be attached. Read each "
                    "`record` against its `shows` line above; if a pair does not match, fix the "
                    "manifest rather than the caption. Re-run with --apply."
                )
            )
            return

        attached = 0
        with transaction.atomic():
            for entry, event, path, existing_key, _size in planned:
                if path is not None:
                    target = f"gallery_images/demo/{event.__class__.__name__.lower()}-{event.id}-{path.name}"
                    with path.open("rb") as handle:
                        stored_key = default_storage.save(target, handle)
                else:
                    # Already in the bucket; attach it where it lies rather than copying.
                    stored_key = existing_key
                if event.album is None:
                    event.album = Gallery.objects.create()
                    event.save(update_fields=["album"])
                GalleryImage.objects.create(
                    gallery=event.album,
                    s3_key=stored_key,
                    file_size=(path.stat().st_size if path is not None else _size or None),
                    # The operator's own description of the frame, kept beside the image so a
                    # later reviewer can check the pairing without opening the file.
                    extra_data={
                        "shows": entry["shows"],
                        "source": "attach_demo_photos",
                        "content_type": mimetypes.guess_type(path.name if path else stored_key)[0],
                    },
                )
                attached += 1

        self.stdout.write(self.style.SUCCESS(f"\nAttached {attached} photograph(s)."))
        self.stdout.write(
            "These are real files on Trazo's own bucket, so `prune_misleading_demo_photos "
            "--stock` will not remove them and `test_demo_event_photos_are_not_stock` stays green."
        )
