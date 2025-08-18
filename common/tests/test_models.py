"""
Comprehensive Test Suite for Common App
Tests Gallery and GalleryImage models with S3 integration
"""

import io
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

import boto3
try:
    from moto import mock_s3
except ImportError:
    # Fallback for newer moto versions
    from moto.s3 import mock_s3
from PIL import Image

from common.models import Gallery, GalleryImage


class TestGalleryModel(TestCase):
    """Test Gallery model functionality"""

    def test_gallery_creation(self):
        """Test basic gallery creation"""
        gallery = Gallery.objects.create()

        self.assertIsNotNone(gallery.id)
        self.assertIsNotNone(gallery.created_at)
        self.assertIsNotNone(gallery.updated_at)
        self.assertLessEqual(gallery.created_at, gallery.updated_at)

    def test_gallery_timestamps(self):
        """Test automatic timestamp management"""
        gallery = Gallery.objects.create()

        # Store original timestamps
        original_created = gallery.created_at
        original_updated = gallery.updated_at

        # Update the gallery
        gallery.save()
        gallery.refresh_from_db()

        # Created should remain the same, updated should change
        self.assertEqual(gallery.created_at, original_created)
        self.assertGreaterEqual(gallery.updated_at, original_updated)

    def test_gallery_string_representation(self):
        """Test gallery string representation"""
        gallery = Gallery.objects.create()
        expected = f"Gallery {gallery.id}"

        # Since Gallery doesn't have a custom __str__, it should use default
        self.assertIn(str(gallery.id), str(gallery))

    def test_multiple_galleries(self):
        """Test creating multiple galleries"""
        gallery1 = Gallery.objects.create()
        gallery2 = Gallery.objects.create()

        self.assertNotEqual(gallery1.id, gallery2.id)
        self.assertEqual(Gallery.objects.count(), 2)


class TestGalleryImageModel(TestCase):
    """Test GalleryImage model functionality"""

    def setUp(self):
        """Set up test data"""
        self.gallery = Gallery.objects.create()

    def test_gallery_image_creation_basic(self):
        """Test basic gallery image creation"""
        image = GalleryImage.objects.create(
            gallery=self.gallery, s3_key="test/image.jpg", image_url="https://example.com/image.jpg"
        )

        self.assertEqual(image.gallery, self.gallery)
        self.assertEqual(image.s3_key, "test/image.jpg")
        self.assertEqual(image.image_url, "https://example.com/image.jpg")
        self.assertIsNotNone(image.created_at)
        self.assertIsNotNone(image.updated_at)

    def test_gallery_image_string_representation(self):
        """Test gallery image string representation"""
        image = GalleryImage.objects.create(gallery=self.gallery, s3_key="test/image.jpg")

        expected = f"Image {image.id} for Gallery {self.gallery.id}"
        self.assertEqual(str(image), expected)

    def test_gallery_image_foreign_key_relationship(self):
        """Test foreign key relationship with Gallery"""
        image1 = GalleryImage.objects.create(gallery=self.gallery, s3_key="test/image1.jpg")

        image2 = GalleryImage.objects.create(gallery=self.gallery, s3_key="test/image2.jpg")

        # Check reverse relationship
        gallery_images = self.gallery.images.all()
        self.assertEqual(gallery_images.count(), 2)
        self.assertIn(image1, gallery_images)
        self.assertIn(image2, gallery_images)

    def test_gallery_image_cascade_deletion(self):
        """Test cascade deletion when gallery is deleted"""
        image = GalleryImage.objects.create(gallery=self.gallery, s3_key="test/image.jpg")

        image_id = image.id

        # Delete gallery
        self.gallery.delete()

        # Image should be deleted too
        self.assertFalse(GalleryImage.objects.filter(id=image_id).exists())

    def test_gallery_image_optional_fields(self):
        """Test that all image fields are optional"""
        # Should be able to create with just gallery
        image = GalleryImage.objects.create(gallery=self.gallery)

        self.assertIsNone(image.image.name)
        self.assertIsNone(image.s3_key)
        self.assertIsNone(image.image_url)

    def test_gallery_image_with_uploaded_file(self):
        """Test gallery image with uploaded file"""
        # Create a simple test image
        image_file = self.create_test_image()

        gallery_image = GalleryImage.objects.create(gallery=self.gallery, image=image_file)

        self.assertIsNotNone(gallery_image.image.name)
        self.assertTrue(gallery_image.image.name.startswith("gallery_images/"))

    def create_test_image(self):
        """Helper method to create a test image file"""
        # Create a simple test image
        image = Image.new("RGB", (100, 100), color="red")
        image_io = io.BytesIO()
        image.save(image_io, format="JPEG")
        image_io.seek(0)

        return SimpleUploadedFile(name="test_image.jpg", content=image_io.getvalue(), content_type="image/jpeg")


class TestGalleryImageURLProperty(TestCase):
    """Test GalleryImage URL property functionality"""

    def setUp(self):
        """Set up test data"""
        self.gallery = Gallery.objects.create()

    @override_settings(AWS_STORAGE_BUCKET_NAME="test-bucket")
    def test_url_property_with_s3_key(self):
        """Test URL property returns S3 URL when s3_key is present"""
        image = GalleryImage.objects.create(gallery=self.gallery, s3_key="test/path/image.jpg")

        expected_url = f"https://test-bucket.s3.amazonaws.com/test/path/image.jpg"
        self.assertEqual(image.url, expected_url)

    def test_url_property_with_image_url(self):
        """Test URL property returns image_url when available"""
        image_url = "https://external.com/image.jpg"
        image = GalleryImage.objects.create(gallery=self.gallery, image_url=image_url)

        self.assertEqual(image.url, image_url)

    def test_url_property_with_local_image(self):
        """Test URL property returns local image URL"""
        image_file = self.create_test_image()

        gallery_image = GalleryImage.objects.create(gallery=self.gallery, image=image_file)

        # Should return the image.url
        self.assertIsNotNone(gallery_image.url)
        self.assertTrue(gallery_image.url.endswith(".jpg"))

    def test_url_property_priority_order(self):
        """Test URL property priority: s3_key > image_url > image"""
        image_file = self.create_test_image()

        # Create image with all three sources
        image = GalleryImage.objects.create(
            gallery=self.gallery,
            s3_key="test/s3_image.jpg",
            image_url="https://external.com/image.jpg",
            image=image_file,
        )

        # Should prioritize S3 key
        with override_settings(AWS_STORAGE_BUCKET_NAME="test-bucket"):
            expected_s3_url = f"https://test-bucket.s3.amazonaws.com/test/s3_image.jpg"
            self.assertEqual(image.url, expected_s3_url)

        # Remove S3 key, should use image_url
        image.s3_key = None
        self.assertEqual(image.url, "https://external.com/image.jpg")

        # Remove image_url, should use local image
        image.image_url = None
        self.assertIsNotNone(image.url)
        self.assertTrue(image.url.endswith(".jpg"))

    def test_url_property_returns_none(self):
        """Test URL property returns None when no image sources"""
        image = GalleryImage.objects.create(gallery=self.gallery)

        self.assertIsNone(image.url)

    def create_test_image(self):
        """Helper method to create a test image file"""
        image = Image.new("RGB", (100, 100), color="blue")
        image_io = io.BytesIO()
        image.save(image_io, format="JPEG")
        image_io.seek(0)

        return SimpleUploadedFile(name="test_image.jpg", content=image_io.getvalue(), content_type="image/jpeg")


class TestGalleryImageS3Integration(TestCase):
    """Test S3 integration functionality"""

    def setUp(self):
        """Set up test data"""
        self.gallery = Gallery.objects.create()

    @override_settings(
        AWS_STORAGE_BUCKET_NAME="test-bucket",
        AWS_ACCESS_KEY_ID="test-key",
        AWS_SECRET_ACCESS_KEY="test-secret",
        AWS_S3_REGION_NAME="us-east-1",
    )
    @mock_s3
    def test_s3_key_handling(self):
        """Test S3 key handling with mocked S3"""
        # Create S3 bucket
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")

        # Create gallery image with S3 key
        image = GalleryImage.objects.create(gallery=self.gallery, s3_key="test/folder/image.jpg")

        self.assertEqual(image.s3_key, "test/folder/image.jpg")
        expected_url = "https://test-bucket.s3.amazonaws.com/test/folder/image.jpg"
        self.assertEqual(image.url, expected_url)

    def test_s3_key_validation(self):
        """Test S3 key format validation"""
        # Test valid S3 keys
        valid_keys = ["folder/image.jpg", "deep/nested/folder/image.png", "image.gif", "folder-name/image_name.jpeg"]

        for key in valid_keys:
            image = GalleryImage.objects.create(gallery=self.gallery, s3_key=key)
            self.assertEqual(image.s3_key, key)
            image.delete()  # Clean up

    def test_s3_key_max_length(self):
        """Test S3 key maximum length constraint"""
        # S3 key field has max_length=255
        long_key = "a" * 256  # Too long

        with self.assertRaises(Exception):  # Should raise validation error
            image = GalleryImage.objects.create(gallery=self.gallery, s3_key=long_key)

    def test_image_url_validation(self):
        """Test image URL validation"""
        # Test valid URLs
        valid_urls = [
            "https://example.com/image.jpg",
            "http://test.com/path/to/image.png",
            "https://cdn.example.com/images/photo.gif",
        ]

        for url in valid_urls:
            image = GalleryImage.objects.create(gallery=self.gallery, image_url=url)
            self.assertEqual(image.image_url, url)
            image.delete()  # Clean up

    def test_image_url_max_length(self):
        """Test image URL maximum length constraint"""
        # image_url field has max_length=1000
        long_url = "https://example.com/" + "a" * 1000  # Too long

        with self.assertRaises(Exception):  # Should raise validation error
            image = GalleryImage.objects.create(gallery=self.gallery, image_url=long_url)


class TestGalleryImageFileUpload(TestCase):
    """Test file upload functionality"""

    def setUp(self):
        """Set up test data"""
        self.gallery = Gallery.objects.create()

    def test_image_upload_path(self):
        """Test image upload path configuration"""
        image_file = self.create_test_image()

        gallery_image = GalleryImage.objects.create(gallery=self.gallery, image=image_file)

        # Should upload to gallery_images/ directory
        self.assertTrue(gallery_image.image.name.startswith("gallery_images/"))

    def test_image_file_formats(self):
        """Test different image file formats"""
        formats = [("JPEG", "image/jpeg", ".jpg"), ("PNG", "image/png", ".png"), ("GIF", "image/gif", ".gif")]

        for format_name, content_type, extension in formats:
            image_file = self.create_test_image_format(format_name, extension)

            gallery_image = GalleryImage.objects.create(gallery=self.gallery, image=image_file)

            self.assertIsNotNone(gallery_image.image.name)
            self.assertTrue(gallery_image.image.name.endswith(extension))
            gallery_image.delete()  # Clean up

    def test_large_image_handling(self):
        """Test handling of large images"""
        # Create a larger test image
        large_image = self.create_large_test_image()

        gallery_image = GalleryImage.objects.create(gallery=self.gallery, image=large_image)

        self.assertIsNotNone(gallery_image.image.name)

    def create_test_image(self):
        """Helper method to create a test image file"""
        image = Image.new("RGB", (100, 100), color="green")
        image_io = io.BytesIO()
        image.save(image_io, format="JPEG")
        image_io.seek(0)

        return SimpleUploadedFile(name="test_image.jpg", content=image_io.getvalue(), content_type="image/jpeg")

    def create_test_image_format(self, format_name, extension):
        """Helper method to create test image in specific format"""
        image = Image.new("RGB", (50, 50), color="purple")
        image_io = io.BytesIO()
        image.save(image_io, format=format_name)
        image_io.seek(0)

        return SimpleUploadedFile(
            name=f"test_image{extension}", content=image_io.getvalue(), content_type=f"image/{format_name.lower()}"
        )

    def create_large_test_image(self):
        """Helper method to create a larger test image"""
        image = Image.new("RGB", (1000, 1000), color="orange")
        image_io = io.BytesIO()
        image.save(image_io, format="JPEG", quality=95)
        image_io.seek(0)

        return SimpleUploadedFile(name="large_test_image.jpg", content=image_io.getvalue(), content_type="image/jpeg")


class TestGalleryPerformance(TestCase):
    """Test performance-related functionality"""

    def setUp(self):
        """Set up test data"""
        self.gallery = Gallery.objects.create()

    def test_bulk_image_creation(self):
        """Test creating multiple images efficiently"""
        images_data = []

        for i in range(10):
            images_data.append(
                GalleryImage(
                    gallery=self.gallery,
                    s3_key=f"test/bulk_image_{i}.jpg",
                    image_url=f"https://example.com/image_{i}.jpg",
                )
            )

        # Bulk create
        created_images = GalleryImage.objects.bulk_create(images_data)

        self.assertEqual(len(created_images), 10)
        self.assertEqual(self.gallery.images.count(), 10)

    def test_gallery_images_query_optimization(self):
        """Test query optimization for gallery images"""
        # Create multiple images
        for i in range(5):
            GalleryImage.objects.create(gallery=self.gallery, s3_key=f"test/image_{i}.jpg")

        # Test efficient queries
        with self.assertNumQueries(1):
            images = list(self.gallery.images.all())
            self.assertEqual(len(images), 5)

    def test_gallery_with_many_images(self):
        """Test gallery with many images"""
        # Create many images
        for i in range(50):
            GalleryImage.objects.create(gallery=self.gallery, s3_key=f"test/many_images_{i}.jpg")

        self.assertEqual(self.gallery.images.count(), 50)

        # Test pagination-like access
        first_10 = self.gallery.images.all()[:10]
        self.assertEqual(len(list(first_10)), 10)


class TestGalleryEdgeCases(TestCase):
    """Test edge cases and error conditions"""

    def setUp(self):
        """Set up test data"""
        self.gallery = Gallery.objects.create()

    def test_gallery_image_without_gallery(self):
        """Test that gallery is required for GalleryImage"""
        with self.assertRaises(IntegrityError):
            GalleryImage.objects.create(s3_key="test/orphan_image.jpg")

    def test_empty_values_handling(self):
        """Test handling of empty values"""
        image = GalleryImage.objects.create(
            gallery=self.gallery, s3_key="", image_url=""  # Empty string  # Empty string
        )

        # Empty strings should be converted to None or handled gracefully
        self.assertIsNone(image.url)

    def test_special_characters_in_s3_key(self):
        """Test special characters in S3 key"""
        special_keys = [
            "test/image with spaces.jpg",
            "test/image-with-dashes.jpg",
            "test/image_with_underscores.jpg",
            "test/folder/subfolder/image.jpg",
        ]

        for key in special_keys:
            image = GalleryImage.objects.create(gallery=self.gallery, s3_key=key)
            self.assertEqual(image.s3_key, key)
            image.delete()  # Clean up

    def test_unicode_handling(self):
        """Test Unicode character handling"""
        unicode_key = "test/图片.jpg"  # Chinese characters

        image = GalleryImage.objects.create(gallery=self.gallery, s3_key=unicode_key)

        self.assertEqual(image.s3_key, unicode_key)

    def test_gallery_deletion_performance(self):
        """Test performance of gallery deletion with many images"""
        # Create many images
        for i in range(20):
            GalleryImage.objects.create(gallery=self.gallery, s3_key=f"test/performance_image_{i}.jpg")

        # Should efficiently delete all related images
        gallery_id = self.gallery.id
        self.gallery.delete()

        # Verify all images were deleted
        self.assertEqual(GalleryImage.objects.filter(gallery_id=gallery_id).count(), 0)


if __name__ == "__main__":
    unittest.main()
