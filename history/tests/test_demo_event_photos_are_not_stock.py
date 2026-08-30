"""A fabricated record may not carry a library photograph as its evidence.

WHY A RULE AND NOT A LONGER LIST
--------------------------------
`prune_misleading_demo_photos.MISLEADING_IMAGE_IDS` is a denylist built by a person opening
photographs one at a time and comparing each to the record beneath it. It has been extended
three times — 2026-08-04, 2026-08-15, 2026-08-28 — and each extension was made of images that
had survived the sweep before it. The 2026-08-28 batch survived twice because the images sat
under `DEMO_IMAGES` keys that sounded harmless (`pruning`, `planting`, `organic_matter`,
`beneficial_insects`) rather than under the machinery keys someone had thought to audit. One
of them was a roped arborist chainsawing a leafy pine, filed as dormant orchard pruning.

A denylist encodes the reviews that happened, so it is always exactly one incident behind. The
invariant does not need the review: a demo farm has no real photographs, so any library
photograph attached to one of its events is standing in for evidence that does not exist.
Whether a given stock frame happens to show the right crop is luck.

WHY EVENT ALBUMS AND NOT EVERY IMAGE
------------------------------------
A stock orchard photo on a demo farm's PROFILE header is decoration and reads as decoration.
The same photo pinned to a dated record — "Preventive anthracnose spray, 14 March, 1 lb/acre"
— asserts that a specific operation happened on a specific day. That is what an inspector
assessing § 205.201(a)(3) fraud prevention reads as fabricated evidence, and it is what every
entry on the denylist turned out to be.

WHY THIS IS NOT REDUNDANT WITH THE SPECIMEN BANNER
--------------------------------------------------
The banner added on 2026-08-30 marks the PAGE. A photograph leaves the page: it is
screenshotted, cropped into a deck, pulled by a link preview. The banner does not travel with
it, so the image has to be honest on its own.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from common.models import Gallery, GalleryImage
from company.models import Company, Establishment
from history.management.commands.prune_misleading_demo_photos import STOCK_IMAGE_HOSTS, _demo_event_gallery_ids
from history.models import History, ProductionEvent
from product.models import Parcel, Product


class DemoEventPhotosAreNotStockTests(TestCase):
    def _farm(self, name, is_demo):
        company = Company.objects.create(name=f"{name} Co")
        est = Establishment.objects.create(name=name, company=company, is_demo=is_demo)
        parcel = Parcel.objects.create(name="Block A", establishment=est, area=2.0)
        history = History.objects.create(parcel=parcel, product=Product.objects.create(name=f"Crop {name}"))
        return est, history

    def _event_with_image(self, history, url):
        gallery = Gallery.objects.create()
        GalleryImage.objects.create(gallery=gallery, image_url=url)
        return ProductionEvent.objects.create(history=history, album=gallery, date=timezone.now())

    def test_no_demo_event_album_holds_a_stock_photograph(self):
        """The invariant itself, run against whatever this database actually contains.

        ⚠️ HONEST LIMIT OF THIS TEST. Django builds an EMPTY test database, so on CI this
        assertion sees only the rows the tests above create and passes without checking any
        real fixture. It has teeth when pointed at a seeded database — a developer's local DB,
        staging, or a restored production snapshot — which is where the 12 unreviewed stock
        photographs found on 2026-08-30 were sitting.

        It is deliberately NOT backed by a static guard over the seeder sources yet. That guard
        would fail CI on 31 existing stock URLs across seven seeders, which forces a product
        decision — whether demo farms keep event photography at all before real orchard
        photographs exist — that belongs to whoever is planning the demo, not to a test.
        """
        gallery_ids = _demo_event_gallery_ids()
        offenders = []
        for host in STOCK_IMAGE_HOSTS:
            offenders.extend(
                GalleryImage.objects.filter(gallery_id__in=gallery_ids, image_url__icontains=host).values_list(
                    "image_url", flat=True
                )
            )
        self.assertEqual(
            sorted(set(offenders)),
            [],
            "library photographs are attached to events on a fabricated farm, so those records "
            "carry evidence of operations that never happened. Remove them with "
            "`manage.py prune_misleading_demo_photos --stock`, or replace them with photographs "
            "of the operation being demonstrated.",
        )

    def test_the_walk_actually_finds_demo_event_albums(self):
        """Anti-vacuity fence.

        A resolver that silently returns an empty set would make the test above pass on every
        database forever — which is precisely how a guard written against a table nobody seeded
        passes without ever checking anything.
        """
        _, demo_history = self._farm("Specimen Photo Farm", is_demo=True)
        event = self._event_with_image(demo_history, "https://images.unsplash.com/photo-0000000000000")

        self.assertIn(event.album_id, _demo_event_gallery_ids())

    def test_a_real_farms_photographs_are_never_in_scope(self):
        """The asymmetry, same as everywhere else in the specimen work.

        Deleting a real grower's photograph destroys their § 205.103 evidence. The resolver
        must key on `is_demo` and nothing else — never on the host, never on "looks like stock".
        """
        _, real_history = self._farm("Real Photo Farm", is_demo=False)
        event = self._event_with_image(real_history, "https://images.unsplash.com/photo-0000000000001")

        self.assertNotIn(event.album_id, _demo_event_gallery_ids())

    def test_establishment_level_imagery_is_out_of_scope(self):
        """A gallery attached to no event is decoration, and stays.

        Stated as a test rather than left implicit, because the obvious "tighten" of this rule
        — sweeping every image on a demo company — would delete farm header photography that
        asserts nothing about any dated operation.
        """
        _, demo_history = self._farm("Header Only Farm", is_demo=True)
        orphan = Gallery.objects.create()
        GalleryImage.objects.create(gallery=orphan, image_url="https://images.unsplash.com/photo-0000000000002")

        self.assertNotIn(orphan.id, _demo_event_gallery_ids())


class PruneStockFlagTests(DemoEventPhotosAreNotStockTests):
    """The `--stock` flag actually deletes, and only what it should.

    The reporting path was exercised by hand on a seeded database; the DELETE path was not,
    and it is the one that cannot be undone. Both directions are pinned here because the
    asymmetry is the same as everywhere else in this work: failing to remove a stock photo
    leaves the old defect, removing a real grower's photograph destroys their § 205.103
    evidence.
    """

    def _run(self, *args):
        out = StringIO()
        call_command("prune_misleading_demo_photos", *args, stdout=out)
        return out.getvalue()

    def test_stock_flag_removes_a_demo_event_photograph(self):
        _, demo = self._farm("Prune Demo Farm", is_demo=True)
        event = self._event_with_image(demo, "https://images.unsplash.com/photo-1111111111111")

        self._run("--stock")

        self.assertFalse(
            GalleryImage.objects.filter(gallery_id=event.album_id).exists(),
            "a library photograph survived --stock on a fabricated farm's event",
        )

    def test_stock_flag_spares_a_real_farms_photograph(self):
        _, real = self._farm("Prune Real Farm", is_demo=False)
        event = self._event_with_image(real, "https://images.unsplash.com/photo-2222222222222")

        self._run("--stock")

        self.assertTrue(
            GalleryImage.objects.filter(gallery_id=event.album_id).exists(),
            "a real operation's photograph was deleted — that is destroyed § 205.103 evidence",
        )

    def test_stock_flag_spares_a_demo_farms_own_uploaded_photograph(self):
        """Only LIBRARY photography is in scope.

        A picture actually taken of the demonstration setup, uploaded to Trazo's own bucket,
        is not standing in for anything. Sweeping every image on a demo farm would delete it.
        """
        _, demo = self._farm("Prune Uploaded Farm", is_demo=True)
        event = self._event_with_image(demo, "https://trazo-media.s3.us-east-2.amazonaws.com/media/x.jpg")

        self._run("--stock")

        self.assertTrue(GalleryImage.objects.filter(gallery_id=event.album_id).exists())

    def test_dry_run_deletes_nothing(self):
        _, demo = self._farm("Prune Dry Farm", is_demo=True)
        event = self._event_with_image(demo, "https://images.unsplash.com/photo-3333333333333")

        output = self._run("--stock", "--dry-run")

        self.assertIn("dry-run", output)
        self.assertTrue(GalleryImage.objects.filter(gallery_id=event.album_id).exists())

    def test_without_the_flag_unreviewed_stock_is_left_alone(self):
        """The flag is opt-in, and the default behaviour is unchanged.

        Whether demo farms keep event photography at all is a product decision tied to the
        demo video, so the broad sweep must never happen by accident on an operator running
        the command the way its docstring has always described.
        """
        _, demo = self._farm("Prune Default Farm", is_demo=True)
        event = self._event_with_image(demo, "https://images.unsplash.com/photo-4444444444444")

        self._run()

        self.assertTrue(GalleryImage.objects.filter(gallery_id=event.album_id).exists())
