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
]


class Command(BaseCommand):
    help = "Delete demo photographs that depict an operation other than the one they document."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without deleting anything.",
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
