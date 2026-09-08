"""The only supported way to put photographs back on a demonstration farm.

`prune_misleading_demo_photos --stock` cleared every library image off demo event albums, and
the seeders cannot put them back without reintroducing the defect (they attach from hardcoded
Unsplash pools) or re-minting `public_id`s. `attach_demo_photos` is the replacement, and these
tests pin the properties that make it safe rather than just functional:

  * demo establishments only — a real operation's records are authored by the producer
  * local files only — a URL is how a stock host walks back in
  * `shows` is mandatory — the operator must state what is in the frame, because a key name is
    not a vetting; that is exactly how a roped arborist in a pine came to illustrate "dormant
    orchard pruning" and survive two prunes
  * never overwrites — a second run cannot silently duplicate or replace
"""

import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from carbon.models import CropType
from common.models import Gallery, GalleryImage
from company.models import Company, Establishment
from history.models import History, ProductionEvent
from product.models import Parcel, Product

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


class AttachDemoPhotosTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.photo = Path(self.tmp.name) / "dormant-pruning.png"
        self.photo.write_bytes(PNG)

    def _event(self, *, is_demo=True):
        company = Company.objects.create(name=f"Co {is_demo}")
        est = Establishment.objects.create(name=f"Farm {is_demo}", company=company, is_demo=is_demo)
        parcel = Parcel.objects.create(name="Block A", establishment=est, area=4.0)
        crop = CropType.objects.create(
            name=f"Walnuts {is_demo}",
            slug=f"walnuts-{is_demo}",
            category="nut",
            description="Nut",
            typical_farm_size="10-40 ha",
            growing_season="Mar-Aug",
            harvest_season="Sep-Oct",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        history = History.objects.create(
            parcel=parcel,
            product=Product.objects.create(name=f"Walnuts {is_demo}"),
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=120),
        )
        return ProductionEvent.objects.create(
            history=history, date=timezone.now(), description="Dormant pruning of the walnut block"
        )

    def _manifest(self, entries):
        path = Path(self.tmp.name) / "manifest.json"
        path.write_text(json.dumps(entries))
        return str(path)

    def _entry(self, event, **overrides):
        entry = {
            "event": f"production:{event.id}",
            "file": str(self.photo),
            "shows": "Chandler walnut, dormant, fresh pruning cuts on scaffold limbs",
        }
        entry.update(overrides)
        return entry

    # ---- the property that replaces the failed key-name vetting -----------

    def test_shows_is_mandatory(self):
        event = self._event()
        entry = self._entry(event)
        del entry["shows"]
        with self.assertRaises(CommandError) as ctx:
            call_command("attach_demo_photos", "--manifest", self._manifest([entry]), verbosity=0)
        self.assertIn("shows", str(ctx.exception))

    def test_blank_shows_is_refused(self):
        """An empty string is the obvious way around a required field."""
        event = self._event()
        with self.assertRaises(CommandError):
            call_command(
                "attach_demo_photos", "--manifest", self._manifest([self._entry(event, shows="   ")]), verbosity=0
            )

    # ---- the boundaries ---------------------------------------------------

    def test_a_real_farm_is_refused(self):
        """§ 205.201(a) makes the producer the author of their own records."""
        event = self._event(is_demo=False)
        with self.assertRaises(CommandError) as ctx:
            call_command("attach_demo_photos", "--manifest", self._manifest([self._entry(event)]), verbosity=0)
        self.assertIn("not a demonstration farm", str(ctx.exception))

    def test_a_url_is_refused(self):
        """The one input that would let a library photograph back in."""
        event = self._event()
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "attach_demo_photos",
                "--manifest",
                self._manifest([self._entry(event, file="https://images.unsplash.com/photo-123")]),
                verbosity=0,
            )
        self.assertIn("local path", str(ctx.exception))

    def test_a_missing_file_is_refused(self):
        event = self._event()
        with self.assertRaises(CommandError):
            call_command(
                "attach_demo_photos",
                "--manifest",
                self._manifest([self._entry(event, file=str(Path(self.tmp.name) / "nope.jpg"))]),
                verbosity=0,
            )

    # ---- dry run is the default ------------------------------------------

    def test_dry_run_attaches_nothing(self):
        event = self._event()
        call_command("attach_demo_photos", "--manifest", self._manifest([self._entry(event)]), verbosity=0)
        event.refresh_from_db()
        self.assertIsNone(event.album)

    # ---- applying ---------------------------------------------------------

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_apply_attaches_the_photograph_and_keeps_the_description(self):
        event = self._event()
        entry = self._entry(event)
        call_command("attach_demo_photos", "--manifest", self._manifest([entry]), "--apply", verbosity=0)

        event.refresh_from_db()
        self.assertIsNotNone(event.album)
        image = event.album.images.get()
        self.assertTrue(image.s3_key, "the file was not stored")
        self.assertEqual(image.extra_data["shows"], entry["shows"])
        self.assertEqual(image.extra_data["source"], "attach_demo_photos")

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_what_it_attaches_survives_the_stock_prune(self):
        """The whole point: these are real files on Trazo's own bucket, not library images.

        If `--stock` swept them the demo would be photographless again after every prune, and
        the operator would have no way to tell which loss was intended.
        """
        event = self._event()
        call_command("attach_demo_photos", "--manifest", self._manifest([self._entry(event)]), "--apply", verbosity=0)
        call_command("prune_misleading_demo_photos", "--stock", verbosity=0)

        event.refresh_from_db()
        self.assertEqual(event.album.images.count(), 1, "the prune removed a real photograph")

    # ---- s3_key mode: the one that works in the production console ---------

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_an_existing_bucket_object_can_be_attached_by_key(self):
        """Why this mode exists: the command is normally run in the DO console, which cannot
        see files on the operator's machine. `--manifest shots/manifest.json` there fails with
        "manifest not found" and there is no way to hand it a local photograph."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        key = default_storage.save("gallery_images/demo/already-there.png", ContentFile(PNG))
        event = self._event()
        entry = self._entry(event)
        del entry["file"]
        entry["s3_key"] = key

        call_command("attach_demo_photos", "--manifest", self._manifest([entry]), "--apply", verbosity=0)

        event.refresh_from_db()
        image = event.album.images.get()
        self.assertEqual(image.s3_key, key, "the existing object was not attached where it lies")
        self.assertEqual(image.extra_data["shows"], entry["shows"])

    def test_a_missing_key_is_refused(self):
        """A typo would otherwise attach a row that renders as a broken thumbnail — the exact
        state the consumer page was in before the gallery fix."""
        event = self._event()
        entry = self._entry(event)
        del entry["file"]
        entry["s3_key"] = "gallery_images/demo/does-not-exist.png"
        with self.assertRaises(CommandError) as ctx:
            call_command("attach_demo_photos", "--manifest", self._manifest([entry]), verbosity=0)
        self.assertIn("no object at key", str(ctx.exception))

    def test_a_url_as_s3_key_is_refused(self):
        event = self._event()
        entry = self._entry(event)
        del entry["file"]
        entry["s3_key"] = "https://images.unsplash.com/photo-123"
        with self.assertRaises(CommandError) as ctx:
            call_command("attach_demo_photos", "--manifest", self._manifest([entry]), verbosity=0)
        self.assertIn("not a URL", str(ctx.exception))

    def test_exactly_one_source_is_required(self):
        """Both, or neither, is a manifest the operator has not thought through."""
        event = self._event()
        both = self._entry(event, s3_key="gallery_images/demo/x.png")
        with self.assertRaises(CommandError) as ctx:
            call_command("attach_demo_photos", "--manifest", self._manifest([both]), verbosity=0)
        self.assertIn("exactly one", str(ctx.exception))

        neither = self._entry(event)
        del neither["file"]
        with self.assertRaises(CommandError):
            call_command("attach_demo_photos", "--manifest", self._manifest([neither]), verbosity=0)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
    )
    def test_an_event_that_already_has_photographs_is_skipped(self):
        event = self._event()
        event.album = Gallery.objects.create()
        event.save(update_fields=["album"])
        GalleryImage.objects.create(gallery=event.album, image_url="https://example.com/existing.jpg")

        call_command("attach_demo_photos", "--manifest", self._manifest([self._entry(event)]), "--apply", verbosity=0)

        event.refresh_from_db()
        self.assertEqual(event.album.images.count(), 1, "a second run duplicated or replaced")
