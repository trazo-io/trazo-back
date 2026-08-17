"""The DMS counts toward storage, and documents never hit the wall that photos hit.

Two defects are guarded here, both shipped by the October pivot's document shelf:

1. **The shelf was invisible to the meter.** `_compute_used_storage_gb` summed
   `GalleryImage` and nothing else, so every OSP packet, audit dossier, PUR export and
   farmer upload was storage the farm paid for and the usage bar never showed.

2. **The shelf had no gate.** `check_storage_quota` was wired into the three gallery
   upload paths in `common/views.py` and nowhere else — a farm at 100% of quota could
   still upload unlimited PDFs.

Closing (2) naively would have created a third defect, which the last two tests here
exist to prevent: if documents were hard-limited, or if the media wall were measured
against the TOTAL, a farm whose generated documents filled the plan would be permanently
unable to upload anything — generated rows are immutable (`is_deletable` is False) and
`extra-storage` was retired in 0006, so there is nothing to delete and nothing to buy.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from common.models import Gallery, GalleryImage
from company.models import Company, Establishment
from documents.services.filing import file_document
from subscriptions.models import Plan, Subscription
from subscriptions.serializers import SubscriptionSerializer
from subscriptions.storage_accounting import document_storage_bytes, media_storage_bytes, storage_breakdown
from subscriptions.storage_utils import CATEGORY_DOCUMENTS, CATEGORY_MEDIA, check_storage_quota
from users.models import User, WorksIn

GB = 1024 * 1024 * 1024


class StorageAccountingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Accounting Farm")
        self.establishment = Establishment.objects.create(name="Shelf Ranch", company=self.company, state="CA")
        self.plan, _ = Plan.objects.get_or_create(
            slug="storage-accounting-test",
            defaults={
                "name": "Accounting Test",
                "description": "fixture",
                "price": 0,
                "interval": "monthly",
                "is_active": False,
                "features": {"max_establishments": 1, "storage_limit_gb": 10},
            },
        )
        self.subscription = Subscription.objects.create(
            company=self.company,
            plan=self.plan,
            status="active",
            current_period_start=timezone.now() - timedelta(days=1),
        )

    def _file_doc(self, size_bytes, source="dossier"):
        doc = file_document(
            establishment=self.establishment,
            source=source,
            folder="exports",
            title="Doc",
            filename="doc.pdf",
            content=b"x",
            content_type="application/pdf",
        )
        # The real size is written by `file_document` from the payload; overriding it keeps
        # the test from having to materialise gigabytes on disk to exercise the arithmetic.
        doc.size_bytes = size_bytes
        doc.save(update_fields=["size_bytes"])
        return doc

    def _add_photo(self, size_bytes):
        gallery = self.establishment.album
        if gallery is None:
            gallery = Gallery.objects.create()
            self.establishment.album = gallery
            self.establishment.save(update_fields=["album"])
        return GalleryImage.objects.create(
            gallery=gallery, image_url="https://example.test/x.jpg", file_size=size_bytes
        )

    def test_documents_count_toward_storage(self):
        """The regression that motivated all of this: the shelf must be visible."""
        before = document_storage_bytes(self.company)
        self.assertEqual(before, 0)

        # Sized in GB, not MB. The breakdown is reported to 2dp of a GIGABYTE, so a couple
        # of megabytes rounds to 0.00 and an assertion on it would fail for a formatting
        # reason while the accounting was correct.
        self._file_doc(2 * GB)  # dossier archive
        self._file_doc(3 * GB)  # packet archive

        after = document_storage_bytes(self.company)
        # Prove the query READ something before asserting anything about the total — a
        # zero here would otherwise pass a "documents are counted" test for the wrong reason.
        self.assertEqual(after, 5 * GB)

        breakdown = storage_breakdown(self.company)
        self.assertGreater(breakdown["documents_gb"], Decimal("0.00"))
        self.assertEqual(breakdown["total_gb"], breakdown["media_gb"] + breakdown["documents_gb"])

    def test_media_and_documents_are_separate_totals(self):
        self._add_photo(4 * 1024 * 1024)
        self._file_doc(6 * 1024 * 1024)

        self.assertEqual(media_storage_bytes(self.company), 4 * 1024 * 1024)
        self.assertEqual(document_storage_bytes(self.company), 6 * 1024 * 1024)

        breakdown = storage_breakdown(self.company)
        self.assertEqual(breakdown["total_gb"], breakdown["media_gb"] + breakdown["documents_gb"])

    def test_the_displayed_parts_always_sum_to_the_displayed_total(self):
        """The property the usage meter renders, at the sizes that actually break it.

        MEASURED on the demo farm: 0.1155 GB of photos and 0.0051 GB of documents round to
        0.12 and 0.01, which display as summing to 0.13 — while the true total rounds to
        0.12. Deriving the total from the rounded parts is what keeps the card's own
        arithmetic honest; the ≤0.01 GB it costs is invisible against a 10 GB floor.
        """
        awkward_pairs = [
            (int(0.1155 * GB), int(0.0051 * GB)),  # the real observed case
            (int(0.005 * GB), int(0.005 * GB)),  # both round up from below a cent
            (int(0.014 * GB), int(0.014 * GB)),  # both round down
            (0, int(0.006 * GB)),  # empty media
        ]
        for media_bytes, doc_bytes in awkward_pairs:
            with self.subTest(media=media_bytes, documents=doc_bytes):
                GalleryImage.objects.all().delete()
                from documents.models import GeneratedDocument

                GeneratedDocument.objects.all().delete()
                if media_bytes:
                    self._add_photo(media_bytes)
                if doc_bytes:
                    self._file_doc(doc_bytes)

                breakdown = storage_breakdown(self.company)
                self.assertEqual(
                    breakdown["total_gb"],
                    breakdown["media_gb"] + breakdown["documents_gb"],
                    "the meter would print parts that do not add up to its own total",
                )
                # And the drift from the true total stays within one displayed unit.
                true_total = Decimal(media_bytes + doc_bytes) / Decimal(GB)
                self.assertLessEqual(abs(breakdown["total_gb"] - true_total), Decimal("0.01"))

    def test_a_sub_gigabyte_shelf_is_still_reportable(self):
        """The Blue Oak Orchards case: 21 real documents that weigh under a megabyte.

        Photo evidence runs to gigabytes; a certifier document shelf runs to kilobytes and
        megabytes. Rounded to GB, a genuine shelf of an audit dossier, a PUR export, two OSP
        packets, module PDFs, a workbook, a snapshot and lot tags prints as "0.00 GB" beside
        a list of 21 files — arithmetically right, and it reads as a broken meter. The raw
        byte counts travel so the client can pick the unit per line.
        """
        # Real sizes, read off the demo farm's shelf.
        for size in (41_000, 714, 73_000, 2_000, 6_000, 7_000, 7_000, 46_000):
            self._file_doc(size)

        breakdown = storage_breakdown(self.company)
        self.assertEqual(breakdown["documents_gb"], Decimal("0.00"), "GB is the wrong unit at this scale")
        self.assertEqual(breakdown["documents_bytes"], 182_714)
        self.assertGreater(breakdown["documents_bytes"], 0, "the byte figure is what makes the shelf reportable")

        data = SubscriptionSerializer(self.subscription).data
        self.assertEqual(data["storage_breakdown"]["documents_bytes"], 182_714)
        self.assertEqual(
            data["storage_breakdown"]["total_bytes"],
            data["storage_breakdown"]["media_bytes"] + data["storage_breakdown"]["documents_bytes"],
        )

    def test_serializer_total_includes_documents(self):
        self._add_photo(1 * 1024 * 1024)
        self._file_doc(9 * 1024 * 1024)

        data = SubscriptionSerializer(self.subscription).data
        self.assertGreater(float(data["used_storage_gb"]), 0.0)
        self.assertEqual(data["storage_breakdown"]["enforced_category"], "media")
        self.assertAlmostEqual(
            data["storage_breakdown"]["media_gb"] + data["storage_breakdown"]["documents_gb"],
            data["storage_breakdown"]["total_gb"],
            places=2,
        )


class StorageQuotaCategoryTests(TestCase):
    """Which category is refused at the ceiling, and which is not."""

    def setUp(self):
        self.company = Company.objects.create(name="Quota Farm")
        self.establishment = Establishment.objects.create(name="Quota Ranch", company=self.company, state="CA")
        self.user = User.objects.create_user(email="quota@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.plan, _ = Plan.objects.get_or_create(
            slug="storage-quota-test",
            defaults={
                "name": "Quota Test",
                "description": "fixture",
                "price": 0,
                "interval": "monthly",
                "is_active": False,
                "features": {"max_establishments": 1, "storage_limit_gb": 1},
            },
        )
        Subscription.objects.create(
            company=self.company,
            plan=self.plan,
            status="active",
            current_period_start=timezone.now() - timedelta(days=1),
        )
        self.company.refresh_from_db()

    def _fill_media(self, gb):
        gallery = Gallery.objects.create()
        self.establishment.album = gallery
        self.establishment.save(update_fields=["album"])
        GalleryImage.objects.create(gallery=gallery, image_url="https://example.test/big.jpg", file_size=int(gb * GB))

    def _fill_documents(self, gb):
        doc = file_document(
            establishment=self.establishment,
            source="packet",
            folder="exports",
            title="Big packet",
            filename="packet.zip",
            content=b"x",
        )
        doc.size_bytes = int(gb * GB)
        doc.save(update_fields=["size_bytes"])

    def test_media_still_blocked_at_the_ceiling(self):
        self._fill_media(0.95)
        allowed, detail = check_storage_quota(self.user, int(0.2 * GB), category=CATEGORY_MEDIA)
        self.assertFalse(allowed)
        self.assertEqual(detail["code"], "STORAGE_QUOTA_EXCEEDED")
        self.assertEqual(detail["category"], CATEGORY_MEDIA)

    def test_documents_are_never_blocked_by_quota(self):
        """Even far past the ceiling. A refused certificate is the failure the tier prevents."""
        self._fill_documents(5.0)  # 5x the 1 GB plan
        allowed, detail = check_storage_quota(self.user, int(1.0 * GB), category=CATEGORY_DOCUMENTS)
        self.assertTrue(allowed)
        self.assertIsNone(detail)

    def test_documents_do_not_consume_the_photo_headroom(self):
        """The dead end this design exists to avoid.

        If the media wall were measured against the TOTAL, a shelf full of undeletable
        generated documents would permanently block photo upload with no action available
        to the farmer. The wall is measured against media alone for exactly this reason.
        """
        self._fill_documents(5.0)
        allowed, detail = check_storage_quota(self.user, int(0.1 * GB), category=CATEGORY_MEDIA)
        self.assertTrue(allowed, detail)

    def test_a_full_document_shelf_raises_no_storage_warning(self):
        """A warning says "act now or something stops working". Documents cannot stop working.

        Scoring the warning on the TOTAL would fire "95% used — upgrade to avoid service
        interruption" at a farm with a large document shelf, about an interruption that
        cannot happen, in response to files it is not allowed to delete.
        """
        from subscriptions.serializers import SubscriptionSerializer

        self._fill_documents(5.0)  # 5x the 1 GB plan, documents only
        warnings = SubscriptionSerializer(self.company.subscription).data["usage_warnings"]
        storage_warnings = [w for w in warnings if w["metric"] == "storage"]
        self.assertEqual(storage_warnings, [], "documents raised an alarm about a wall that does not exist")

        # ...and the photo half still does raise one, so the assertion above is not passing
        # because warnings are broken generally.
        self._fill_media(0.95)
        warnings = SubscriptionSerializer(self.company.subscription).data["usage_warnings"]
        storage_warnings = [w for w in warnings if w["metric"] == "storage"]
        self.assertEqual(len(storage_warnings), 1, warnings)
        self.assertEqual(storage_warnings[0]["level"], "critical")

    def test_no_subscription_blocks_both_categories(self):
        """Soft does not mean ungated: no plan is still no storage."""
        orphan = User.objects.create_user(email="orphan@test.com", password="x")
        for category in (CATEGORY_MEDIA, CATEGORY_DOCUMENTS):
            allowed, detail = check_storage_quota(orphan, 1024, category=category)
            self.assertFalse(allowed, category)
            self.assertEqual(detail["code"], "NO_SUBSCRIPTION", category)

    def test_explicit_company_beats_get_active_company(self):
        """A multi-company user must be metered against the company being uploaded to."""
        other = Company.objects.create(name="Other Quota Farm")
        Establishment.objects.create(name="Other Ranch", company=other, state="CA")
        WorksIn.objects.create(user=self.user, company=other, role=WorksIn.COMPANY_ADMIN)
        big_plan, _ = Plan.objects.get_or_create(
            slug="storage-quota-test-big",
            defaults={
                "name": "Quota Test Big",
                "description": "fixture",
                "price": 0,
                "interval": "monthly",
                "is_active": False,
                "features": {"max_establishments": 1, "storage_limit_gb": 500},
            },
        )
        Subscription.objects.create(
            company=other,
            plan=big_plan,
            status="active",
            current_period_start=timezone.now() - timedelta(days=1),
        )
        self._fill_media(0.95)

        # Without the explicit company the helper may measure either farm; with it, the
        # 500 GB farm is unambiguously the one being checked.
        allowed, detail = check_storage_quota(self.user, int(2 * GB), category=CATEGORY_MEDIA, company=other)
        self.assertTrue(allowed, detail)
