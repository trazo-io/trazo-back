from urllib.parse import urlparse

from django.conf import settings
from django.db import models


class Gallery(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class GalleryImage(models.Model):
    gallery = models.ForeignKey(Gallery, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="gallery_images/", blank=True, null=True)
    s3_key = models.CharField(max_length=255, blank=True, null=True)
    image_url = models.URLField(max_length=1000, blank=True, null=True)
    file_size = models.PositiveIntegerField(
        null=True, blank=True, help_text="File size in bytes, populated on upload for accurate storage tracking"
    )
    extra_data = models.JSONField(
        blank=True, null=True, help_text="Stores Vision API validation results, GPS data, and other image metadata"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Auto-populate file_size from local image if not already set
        if not self.file_size and self.image:
            try:
                self.file_size = self.image.size
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Image {self.id} for Gallery {self.gallery.id}"

    @property
    def url(self):
        """Return a permanent public URL for the image."""
        region = getattr(settings, "AWS_S3_REGION_NAME", "us-east-2")
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "trazo-media")
        base = f"https://{bucket}.s3.{region}.amazonaws.com"

        if self.s3_key:
            return f"{base}/{self.s3_key}"
        elif self.image_url:
            # Clean expired presigned params from legacy stored URLs
            if "X-Amz-Signature" in self.image_url:
                clean_url = self.image_url.split("?")[0]
                # Fix legacy URLs missing region in hostname
                if ".s3.amazonaws.com" in clean_url and f".s3.{region}." not in clean_url:
                    try:
                        parsed = urlparse(clean_url)
                        key = parsed.path.lstrip("/")
                        return f"{base}/{key}"
                    except Exception:
                        pass
                return clean_url
            return self.image_url
        elif self.image:
            return self.image.url
        return None
