"""Remove demo photographs that contradict the record they illustrate.

`create_demo_user` is create-only, so correcting its image pool does not reach an
environment that has already been seeded — the same idempotency trap the education
seeder had. This applies the correction in place, without wiping demo data the
operator may have edited by hand.

Why these images had to go (2026-08-03 dossier review): the demo farm is three
ORCHARDS — avocado, almond, citrus — and the photographs attached to its chemical,
weeding and scouting events showed row-crop and bare-field machinery. A crop-duster
aircraft illustrated a "trunk injection"; a tractor on open ground illustrated flame
weeding "in row middles between avocado rows"; a grass field illustrated scouting for
avocado lace bug. A photograph that documents an operation which did not happen is
worse than no photograph: an inspector assessing SOE fraud prevention
(7 CFR 205.201(a)(3)) reads it as fabricated evidence, and the audit dossier now
flags it.

Deliberately removes rather than replaces. Real photographs of the actual operation
are the only correct fix, and inventing a substitute stock URL would repeat the
mistake in a new costume.

    poetry run python manage.py prune_misleading_demo_photos --dry-run
    poetry run python manage.py prune_misleading_demo_photos
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from common.models import GalleryImage

# Unsplash IDs removed from create_demo_user.DEMO_IMAGES on 2026-08-04.
MISLEADING_IMAGE_IDS = [
    ("photo-1660613757833", "crop-duster aircraft, used for trunk injection / airblast"),
    ("photo-1655130944281", "row-crop field machinery, used for banded fertilizer"),
    ("photo-1719254271334", "aerial row-crop fields, used for banded fertilizer"),
    ("photo-1755931359594", "boom sprayer in crop field, used for orchard pesticide"),
    ("photo-1655130944329", "field machinery, used for orchard weed management"),
    ("photo-1654741275609", "tractor + boom sprayer on bare field, used for weeding"),
    ("photo-1622813071880", "grass field, used for orchard pest scouting"),
    ("photo-1762291317833", "ploughed open field, used for flame weeding between tree rows"),
    ("photo-1587810451787", "open field, used for orchard trap monitoring"),
    # 2026-08-15: survived the 2026-08-04 prune under the caption "ground sprayer applying
    # treatment". It is a liquid-manure slurry tanker + disc injector on bare arable ground,
    # attached to orchard fungicide records — and, being the first production photo, it was
    # rendering as the hero of the consumer QR page.
    ("photo-1758608951483", "liquid-manure slurry tanker, used for orchard fungicide"),
    # 2026-08-28: found on the Blue Oak showcase farm while vetting frames for the demo video.
    # These four survived the 2026-08-04 and 2026-08-15 prunes because they sit under keys that
    # sounded harmless (`pruning`, `planting`, `organic_matter`, `beneficial_insects`) rather
    # than under the machinery keys that were audited. Every one was OPENED before this entry
    # was written; the DEMO_IMAGES comment describing two of them was itself wrong.
    ("photo-1626828476637", "roped arborist chainsawing a leafy PINE, used for dormant orchard pruning"),
    ("photo-1679110663825", "studio shot of a basil-like seedling in cupped hands, used for a 24-tree walnut replant"),
    (
        "photo-1580974563942",
        "EARTHWORMS in compost in cupped hands, used for Feather Meal 13-0-0 broadcast at 400 lb/ac",
    ),
    (
        "photo-1528824620477",
        "seven-spot LADYBIRD on a grass blade, used for a Trichogramma platneri (parasitic wasp) release",
    ),
]


#: Hosts that serve library photography. A picture from one of these was taken somewhere else,
#: of something else, by someone else.
STOCK_IMAGE_HOSTS = (
    "images.unsplash.com",
    "unsplash.com",
    "images.pexels.com",
    "pexels.com",
    "pixabay.com",
    "istockphoto.com",
    "shutterstock.com",
)


def _demo_event_gallery_ids():
    """Gallery ids belonging to EVENTS on establishments flagged `is_demo`.

    Event albums only, deliberately. A stock orchard photo on a demo farm's PROFILE header is
    decoration and reads as such; the same photo pinned to a dated record — "Preventive
    anthracnose spray, 14 March, 1 lb/acre" — is a photograph asserting that a specific
    operation happened. That is the thing 7 CFR 205.201(a)(3) makes an inspector read as
    fabricated evidence, and it is what every entry in MISLEADING_IMAGE_IDS turned out to be.
    """
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

    ids = set()
    for model in (
        WeatherEvent,
        ChemicalEvent,
        ProductionEvent,
        GeneralEvent,
        EquipmentEvent,
        SoilManagementEvent,
        PestManagementEvent,
        BusinessEvent,
    ):
        ids.update(
            model.objects.filter(
                history__parcel__establishment__is_demo=True,
                album__isnull=False,
            ).values_list("album_id", flat=True)
        )
    return ids


class Command(BaseCommand):
    help = "Delete demo photographs that depict an operation other than the one they document."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without deleting anything.",
        )
        parser.add_argument(
            "--stock",
            action="store_true",
            help=(
                "Also remove EVERY stock-library photograph attached to an event on a demo "
                "establishment, not only the individually reviewed ones."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        query = Q()
        for image_id, _reason in MISLEADING_IMAGE_IDS:
            query |= Q(image_url__contains=image_id)

        total = 0
        for image_id, reason in MISLEADING_IMAGE_IDS:
            count = GalleryImage.objects.filter(image_url__contains=image_id).count()
            if count:
                total += count
                self.stdout.write(f"  {count:>5}  {image_id}  — {reason}")

        # --stock: the same defect, addressed as a RULE instead of a list.
        #
        # Every id above was found by a person opening a photograph and comparing it to the
        # record beneath it. That works exactly once per photograph, and this list has now been
        # extended three times — 2026-08-04, 08-15, 08-28 — each time by images that had
        # survived the previous sweep. Four of them survived twice because they sat under keys
        # that sounded innocent (`pruning`, `planting`, `organic_matter`, `beneficial_insects`)
        # rather than under the machinery keys someone had thought to audit.
        #
        # A denylist of reviewed images encodes only the reviews that happened. The rule does
        # not need the review: a fabricated record has no real photographs, so any library
        # photograph attached to one is standing in for evidence that does not exist. Whether
        # it happens to depict the right crop is luck, not correctness.
        if options["stock"]:
            gallery_ids = _demo_event_gallery_ids()
            host_query = Q()
            for host in STOCK_IMAGE_HOSTS:
                host_query |= Q(image_url__icontains=host)
            stock_qs = GalleryImage.objects.filter(host_query, gallery_id__in=gallery_ids).exclude(query)
            stock_count = stock_qs.count()
            if stock_count:
                total += stock_count
                self.stdout.write(
                    f"  {stock_count:>5}  (--stock) library photographs on demo EVENT albums, "
                    "beyond the reviewed list above"
                )
            query |= Q(pk__in=list(stock_qs.values_list("pk", flat=True)))

        if not total:
            self.stdout.write(self.style.SUCCESS("No misleading demo photographs found."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\n--dry-run: {total} image(s) would be removed."))
            return

        deleted, _ = GalleryImage.objects.filter(query).delete()
        self.stdout.write(self.style.SUCCESS(f"\nRemoved {deleted} misleading demo photograph(s)."))
        self.stdout.write(
            "Events that lose their only photo will now show no photo evidence, which is "
            "the honest state. Replace with photographs of the real operation when available."
        )
