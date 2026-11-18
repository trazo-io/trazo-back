"""A signed upload is an image, in a folder the app uses, of the size the signature states.

Overall review 2026-11, OV-SEC-C12. Any signed-in account, consumer accounts included, could get a
PUT signed for any content type under any folder of the public-read `media/` prefix, with no size
bound, and `get_upload_urls` put a prefix taken from the request into the key. An object served as
text/html or image/svg+xml from the bucket runs script.
"""

from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings

import boto3
from botocore.config import Config
from rest_framework.test import APIClient

from users.models import User

_URL = "/api/get-presigned-url/"


def _offline_s3_client():
    """A real client with dummy keys: it signs URLs without touching the network."""
    return boto3.client(
        "s3",
        region_name="us-east-2",
        aws_access_key_id="AKIAEXAMPLEEXAMPLE00",
        aws_secret_access_key="x" * 40,
        config=Config(s3={"addressing_style": "virtual"}, signature_version="s3v4"),
    )


@override_settings(AWS_STORAGE_BUCKET_NAME="trazo-test-bucket", AWS_S3_REGION_NAME="us-east-2")
class _Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="shopper@example.com", password="pw-for-test-only")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        # The quota is its own module's subject (`subscriptions.tests.test_storage_accounting`);
        # here it only has to be handed the size the signature binds.
        self.quota = mock.patch("common.views.check_storage_quota", return_value=(True, None))
        patches = (
            mock.patch("common.views.using_s3_storage", return_value=True),
            mock.patch("common.views.SecureAWSClient.get_s3_client", side_effect=_offline_s3_client),
        )
        self.quota_check = self.quota.start()
        self.addCleanup(self.quota.stop)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _ask(self, **body):
        data = {"filename": "block-4.jpg", "fileType": "image/jpeg", "folder": "establishments", "fileSize": 524288}
        data.update(body)
        return self.client.post(_URL, {k: v for k, v in data.items() if v is not None}, format="json")


class ASignedUploadIsBoundedTests(_Base):
    def test_an_image_is_signed_with_its_type_and_length(self):
        response = self._ask()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["s3_key"].startswith("media/establishments/"))
        query = parse_qs(urlparse(response.data["presigned_url"]).query)
        self.assertEqual(query["X-Amz-SignedHeaders"], ["content-length;content-type;host"])
        self.assertEqual(self.quota_check.call_args.args[1], 524288)

    def test_script_bearing_types_are_refused(self):
        for file_type in ("text/html", "image/svg+xml", "application/javascript", "application/octet-stream"):
            with self.subTest(file_type=file_type):
                self.assertEqual(self._ask(fileType=file_type).status_code, 400)

    def test_a_heic_photo_reported_as_octet_stream_is_accepted_by_its_name(self):
        self.assertEqual(self._ask(filename="IMG_0042.HEIC", fileType="application/octet-stream").status_code, 200)
        self.assertEqual(self._ask(filename="page.html", fileType="application/octet-stream").status_code, 400)

    def test_only_the_apps_folder(self):
        for folder in ("gallery_images", "../qr_codes", "uploads"):
            with self.subTest(folder=folder):
                self.assertEqual(self._ask(folder=folder).status_code, 400)
        response = self._ask(folder=None)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["s3_key"].startswith("media/establishments/"))

    def test_the_size_is_required_and_at_most_ten_megabytes(self):
        for size in (None, "abc", 0, -5, 10 * 1024 * 1024 + 1, 5 * 1024 * 1024 * 1024):
            with self.subTest(size=size):
                self.assertEqual(self._ask(fileSize=size).status_code, 400)
        self.assertEqual(self._ask(fileSize=10 * 1024 * 1024).status_code, 200)


class TheOtherUploadPathsAreClosedTests(_Base):
    def test_get_upload_urls_is_gone(self):
        response = self.client.post(
            "/api/upload-urls/",
            {"files": [{"name": "x.html", "type": "text/html", "size": 1}], "entity_type": "gallery_image"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_the_development_upload_answers_404_when_storage_is_s3(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("page.html", b"<html><script>alert(1)</script></html>", content_type="text/html")
        response = self.client.post("/api/local-upload/", {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 404)
