"""Operator records are never anonymously readable; only consumer images are (2026-10-01).

WHY THIS EXISTS
---------------
The `trazo-media` bucket policy granted anonymous `s3:GetObject` on every object, and every stored
file's URL was a permanent unauthenticated link (`AWS_QUERYSTRING_AUTH = False`). An anonymous GET
of an uploaded document returned 200, at a guessable key. Packets carrying the signed annual-update
filing, affidavits, certificates and OSP PDFs were all in that bucket.

The fix has two halves and these tests hold both:
  * every private FileField uses `private_records_storage` (signed, expiring URLs), and every public
    one stores under a prefix in `PUBLIC_MEDIA_PREFIXES`; a new field that is neither fails here;
  * the bucket policy in `infra/s3/` grants anonymous reads under exactly those prefixes.
Plus two holes that would have defeated it: the presigned-read endpoint signed any key it was sent,
and carbon certifications were readable across tenants.
"""

import json
from pathlib import Path

from django.apps import apps
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings

from rest_framework.test import APIClient

from backend.storage import PUBLIC_MEDIA_PREFIXES, is_public_media_key, private_records_storage

REPO = Path(__file__).resolve().parents[2]
POLICY = REPO / "infra" / "s3" / "trazo-media-bucket-policy.json"

#: Fields that are public on purpose, with their prefix. Anything else must be private.
PUBLIC_FIELDS = {
    "common.GalleryImage.image",
    "company.Company.logo",
    "history.Production.qr_code",
    "product.Product.image",
    "users.User.image",
}

S3_SETTINGS = dict(
    STORAGES={
        "default": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    AWS_STORAGE_BUCKET_NAME="trazo-media",
    AWS_S3_REGION_NAME="us-east-2",
    AWS_ACCESS_KEY_ID="AKIATESTTESTTESTTEST",
    AWS_SECRET_ACCESS_KEY="test-secret-test-secret-test-secret-1234",
    AWS_QUERYSTRING_AUTH=False,
)


def _file_fields():
    for model in apps.get_models():
        for f in model._meta.get_fields():
            if isinstance(f, models.FileField):
                yield f"{model._meta.app_label}.{model.__name__}.{f.name}", f


def _prefix(field) -> str:
    up = field.upload_to
    return up if isinstance(up, str) else ""


class EveryFileFieldIsClassifiedTests(SimpleTestCase):
    def test_the_inventory_is_read(self):
        self.assertGreater(len(list(_file_fields())), 15)

    def test_a_public_field_stores_under_a_public_prefix(self):
        problems = []
        seen = set()
        for name, field in _file_fields():
            if name not in PUBLIC_FIELDS:
                continue
            seen.add(name)
            prefix = _prefix(field).rstrip("/") + "/"
            if not prefix.startswith(PUBLIC_MEDIA_PREFIXES):
                problems.append(f"{name} stores under {prefix!r}, which the bucket does not serve publicly")
        self.assertEqual(seen, PUBLIC_FIELDS, "a listed public field no longer exists")
        self.assertEqual(problems, [])

    def test_every_other_field_uses_private_storage(self):
        problems = [
            name
            for name, field in _file_fields()
            if name not in PUBLIC_FIELDS and getattr(field, "_storage_callable", None) is not private_records_storage
        ]
        self.assertEqual(
            problems,
            [],
            "these FileFields would store operator records with permanent public URLs: use "
            "storage=private_records_storage, or add them to PUBLIC_FIELDS on purpose",
        )

    def test_no_private_field_stores_under_a_public_prefix(self):
        problems = []
        for name, field in _file_fields():
            if name in PUBLIC_FIELDS:
                continue
            prefix = _prefix(field).rstrip("/") + "/"
            if prefix.startswith(PUBLIC_MEDIA_PREFIXES):
                problems.append(f"{name}: {prefix}")
        self.assertEqual(problems, [], "a private record under a public prefix is anonymously readable")


class BucketPolicyTests(SimpleTestCase):
    def test_the_policy_grants_exactly_the_public_prefixes(self):
        policy = json.loads(POLICY.read_text())
        resources = []
        for statement in policy["Statement"]:
            self.assertEqual(statement["Effect"], "Allow")
            granted = statement["Resource"]
            resources += granted if isinstance(granted, list) else [granted]
        self.assertNotIn("arn:aws:s3:::trazo-media/*", resources, "the whole bucket must never be public")
        self.assertEqual(sorted(resources), sorted(f"arn:aws:s3:::trazo-media/{p}*" for p in PUBLIC_MEDIA_PREFIXES))

    def test_key_classification(self):
        self.assertTrue(is_public_media_key("gallery_images/a.jpg"))
        self.assertTrue(is_public_media_key("/media/establishments/x.png"))
        for private in ("documents/2026/09/x.zip", "affidavits/a.pdf", "ofpp/p.pdf", "media/../documents/x", ""):
            self.assertFalse(is_public_media_key(private), private)


class PrivateUrlsAreSignedTests(SimpleTestCase):
    @override_settings(**S3_SETTINGS)
    def test_a_private_record_url_is_signed_and_expires_and_a_public_one_is_not(self):
        from django.core.files.storage import storages

        private_url = private_records_storage().url("documents/2026/09/packet.zip")
        self.assertIn("X-Amz-Signature=", private_url)
        self.assertIn("X-Amz-Expires=900", private_url)
        storages._storages = {}
        try:
            public_url = storages["default"].url("gallery_images/photo.jpg")
        finally:
            storages._storages = {}
        self.assertNotIn("X-Amz-Signature", public_url)

    @override_settings(
        **S3_SETTINGS, AWS_S3_CUSTOM_DOMAIN="trazo-media.s3.us-east-2.amazonaws.com", AWS_LOCATION="media"
    )
    def test_a_custom_domain_or_location_does_not_unsign_or_relocate_a_private_record(self):
        """Staging's settings (review of back #87): a custom domain must not drop the signature, and
        AWS_LOCATION must not put a private record under a public prefix."""
        storage = private_records_storage()
        url = storage.url("documents/2026/09/packet.zip")
        self.assertIn("X-Amz-Signature=", url)
        self.assertIn("/documents/2026/09/packet.zip", url)
        self.assertNotIn("/media/documents/", url)

    def test_without_s3_the_default_storage_is_used(self):
        from django.core.files.storage import default_storage

        self.assertIs(private_records_storage(), default_storage)


class PresignedReadIsPublicMediaOnlyTests(TestCase):
    def setUp(self):
        from users.models import User

        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user(email="reader@test.com", password="x"))

    def test_a_private_key_is_refused(self):
        res = self.client.post("/api/get-presigned-read-url/", {"s3_key": "documents/2026/09/x.zip"}, format="json")
        self.assertEqual(res.status_code, 403, res.content[:200])

    def test_a_public_key_is_served(self):
        res = self.client.post("/api/get-presigned-read-url/", {"s3_key": "gallery_images/x.jpg"}, format="json")
        self.assertEqual(res.status_code, 200, res.content[:200])

    @override_settings(**S3_SETTINGS)
    def test_the_batch_never_signs_a_private_key(self):
        from unittest import mock

        with mock.patch("common.views.SecureAWSClient.get_s3_client") as client:
            client.return_value.generate_presigned_url.side_effect = lambda *a, **k: "signed"
            res = self.client.post(
                "/api/get-presigned-read-urls-batch/",
                {
                    "s3_urls": [
                        "https://trazo-media.s3.us-east-2.amazonaws.com/documents/2026/09/x.zip",
                        "https://trazo-media.s3.us-east-2.amazonaws.com/gallery_images/y.jpg",
                    ]
                },
                format="json",
            )
        self.assertEqual(res.status_code, 200, res.content[:300])
        urls = res.json()["presigned_urls"]
        self.assertIsNone(urls["https://trazo-media.s3.us-east-2.amazonaws.com/documents/2026/09/x.zip"])
        self.assertEqual(urls["https://trazo-media.s3.us-east-2.amazonaws.com/gallery_images/y.jpg"], "signed")


class CarbonCertificationsAreTenantScopedTests(TestCase):
    def setUp(self):
        from carbon.models import CarbonCertification
        from company.models import Company, Establishment
        from users.models import User, WorksIn

        self.a = Company.objects.create(name="Company A")
        self.b = Company.objects.create(name="Company B")
        est_a = Establishment.objects.create(name="Farm A", company=self.a)
        self.est_b = Establishment.objects.create(name="Farm B", company=self.b)
        self.cert_a = CarbonCertification.objects.create(
            establishment=est_a, certifier="Certifier", certificate_id="A-1", issue_date="2026-01-01"
        )
        self.user_b = User.objects.create_user(email="b@test.com", password="x")
        WorksIn.objects.create(user=self.user_b, company=self.b, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user_b)

    def test_another_companys_certification_is_not_listed_or_readable(self):
        res = self.client.get("/api/carbon/certifications/")
        self.assertEqual(res.status_code, 200, res.content[:200])
        rows = res.json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertNotIn(self.cert_a.pk, [r["id"] for r in rows])
        self.assertEqual(self.client.get(f"/api/carbon/certifications/{self.cert_a.pk}/").status_code, 404)

    def test_a_certification_cannot_be_filed_against_another_company(self):
        res = self.client.post(
            "/api/carbon/certifications/",
            {
                "establishment": self.cert_a.establishment_id,
                "certifier": "X",
                "certificate_id": "B-1",
                "issue_date": "2026-02-01",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 403, res.content[:200])
