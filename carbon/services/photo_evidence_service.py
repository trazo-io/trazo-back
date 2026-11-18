"""
MVP-aligned photo evidence service for enhanced self-reported verification.

This service handles secure photo upload, validation, and storage for carbon offset evidence.
Designed for simplicity and security while maintaining transparency for Trazo's QR-based
agricultural carbon tracking mission.

MVP Photo Verification Enhancement:
- Google Cloud Vision API integration for content validation
- Detects if photos contain agricultural content
- Identifies AI-generated or stock images
- Supports development bypass mode
- Magic byte content-type validation (defense-in-depth)
- HEIC/HEIF support for iPhone users
- EXIF stripping on processed images (privacy protection)
- GPS geofencing against parcel location
"""

import hashlib
import io
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from PIL import ExifTags, Image

logger = logging.getLogger(__name__)

# Try to import pillow-heif for HEIC support (iPhone photos)
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:
    HEIC_SUPPORTED = False
    logger.info("pillow-heif not installed - HEIC/HEIF uploads will be converted on client side")


# Import Vision API service (lazy import to avoid circular dependencies)
def get_vision_service():
    """Get the Vision API service instance."""
    from carbon.services.vision_api_service import vision_api_service

    return vision_api_service


# Script text an image has no reason to carry, lower-case.
_SCRIPT_MARKERS = (b"<?php", b"<script", b"javascript:")


class PhotoProcessingError(Exception):
    """The image could not be re-encoded, so it must not be stored."""


class PhotoEvidenceService:
    """
    Service for handling photo evidence uploads with MVP-aligned security and validation.

    Features:
    - Secure file validation and sanitization
    - Image format conversion and compression
    - EXIF data extraction for verification
    - Simple cloud storage integration
    - Evidence integrity checking
    """

    # Configuration - Secure with HEIC support for iPhone users
    ALLOWED_MIME_TYPES = [
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    ]

    ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"]
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB max
    MAX_PHOTOS_PER_ENTRY = 5  # Reasonable limit for MVP

    # Image processing settings
    MAX_DIMENSION = 2048  # Resize large images to save storage
    JPEG_QUALITY = 85  # Good quality vs file size balance

    # Thumbnail sizes for consumer QR page performance
    THUMBNAIL_SIZES = {
        "sm": (150, 150),  # List views, event cards
        "md": (400, 400),  # Gallery views, event detail modals
        "lg": (800, 800),  # Full-screen mobile view
    }

    def __init__(self):
        """Initialize the photo evidence service."""
        self.storage_path = "carbon_evidence/photos/"

    def validate_photo(self, file_data: bytes, filename: str) -> Dict[str, Any]:
        """
        Validate uploaded photo for security and format compliance.

        Uses magic byte validation (not extension-based MIME detection) for
        defense-in-depth against disguised malicious files.

        Args:
            file_data: Raw file bytes
            filename: Original filename

        Returns:
            Dict with validation results
        """
        result = {"valid": False, "errors": [], "warnings": [], "metadata": {}}

        try:
            # File size validation
            if len(file_data) > self.MAX_FILE_SIZE:
                result["errors"].append(f"File too large. Maximum size: {self.MAX_FILE_SIZE / (1024*1024):.1f}MB")
                return result

            if len(file_data) < 1024:  # Minimum 1KB
                result["errors"].append("File too small. Minimum size: 1KB")
                return result

            # File extension validation
            file_ext = os.path.splitext(filename.lower())[1]
            if file_ext not in self.ALLOWED_EXTENSIONS:
                result["errors"].append(f'Invalid file extension. Allowed: {", ".join(self.ALLOWED_EXTENSIONS)}')
                return result

            # Magic byte content-type validation (defense-in-depth)
            detected_mime = self._detect_mime_from_magic_bytes(file_data)
            if detected_mime not in self.ALLOWED_MIME_TYPES:
                result["errors"].append(
                    f"File content does not match an allowed image type. "
                    f"Detected: {detected_mime or 'unknown'}. "
                    f'Allowed: {", ".join(self.ALLOWED_MIME_TYPES)}'
                )
                return result

            # HEIC support check
            if file_ext in [".heic", ".heif"] and not HEIC_SUPPORTED:
                result["warnings"].append(
                    "HEIC/HEIF support requires pillow-heif. "
                    "Image will be processed but consider converting to JPEG before upload."
                )

            # Image validation with PIL
            try:
                image = Image.open(ContentFile(file_data))
                image.verify()  # Verify it's a valid image

                # Re-open for metadata extraction (verify() closes the image)
                image = Image.open(ContentFile(file_data))

                # Extract basic metadata
                result["metadata"] = {
                    "format": image.format,
                    "mode": image.mode,
                    "size": image.size,
                    "filename": filename,
                }

                # Extract EXIF data for verification (if available)
                exif_data = self._extract_exif_data(image)
                if exif_data:
                    result["metadata"]["exif"] = exif_data

                # Check minimum dimensions
                width, height = image.size
                if width < 200 or height < 200:
                    result["warnings"].append(
                        "Image dimensions are quite small. Consider using higher resolution photos for better evidence."
                    )

            except Exception as e:
                result["errors"].append(f"Invalid image file: {str(e)}")
                return result

            # File format security check - look for embedded content
            if self._has_suspicious_content(file_data):
                result["errors"].append("File contains suspicious content and cannot be uploaded")
                return result

            result["valid"] = True
            logger.info(f"Photo validation passed: {filename} ({len(file_data)} bytes, type={detected_mime})")

        except Exception as e:
            logger.error(f"Photo validation error: {e}")
            result["errors"].append(f"Validation error: {str(e)}")

        return result

    def validate_photo_content(
        self,
        file_data: bytes,
        event_type: Optional[str] = None,
        subtype: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate photo content using Google Cloud Vision API.

        MVP Photo Verification Feature:
        - Checks if photo contains agricultural content
        - Detects AI-generated or stock images
        - Provides confidence scores
        - Supports development bypass mode

        Args:
            file_data: Raw image bytes
            event_type: Optional event type for context-specific validation
            subtype: Optional event subtype

        Returns:
            Dict with content validation results
        """
        result = {
            "valid": True,
            "content_validation": None,
            "confidence_score": 0.0,
            "detected_labels": [],
            "agricultural_labels": [],
            "warnings": [],
            "bypassed": False,
        }

        try:
            vision_service = get_vision_service()

            # Perform content validation
            if event_type:
                analysis = vision_service.validate_for_event_type(file_data, event_type, subtype)
            else:
                analysis = vision_service.analyze_photo(file_data)

            # Update result with analysis
            result["valid"] = analysis.is_valid
            result["content_validation"] = analysis.validation_result.value
            result["confidence_score"] = analysis.confidence_score
            result["detected_labels"] = analysis.detected_labels
            result["agricultural_labels"] = analysis.agricultural_labels
            result["warnings"] = analysis.warnings
            result["bypassed"] = analysis.validation_result.value == "bypassed"

            if analysis.error_message:
                result["error"] = analysis.error_message

            logger.info(
                f"Photo content validation: {analysis.validation_result.value}, "
                f"confidence={analysis.confidence_score:.2f}"
            )

        except Exception as e:
            logger.error(f"Photo content validation error: {e}")
            # Don't fail the upload on content validation errors
            result["warnings"].append("Content validation unavailable - proceeding without AI verification")
            result["error"] = str(e)

        return result

    def validate_and_analyze_photo(
        self,
        file_data: bytes,
        filename: str,
        event_type: Optional[str] = None,
        subtype: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Complete photo validation including format and content checks.

        Combines security validation with AI content analysis.

        Args:
            file_data: Raw file bytes
            filename: Original filename
            event_type: Optional event type for context validation
            subtype: Optional event subtype

        Returns:
            Dict with complete validation results
        """
        # First perform format/security validation
        format_result = self.validate_photo(file_data, filename)

        if not format_result["valid"]:
            return format_result

        # Then perform content validation
        content_result = self.validate_photo_content(file_data, event_type, subtype)

        # Merge results
        format_result["content_validation"] = content_result["content_validation"]
        format_result["content_confidence"] = content_result["confidence_score"]
        format_result["detected_labels"] = content_result["detected_labels"]
        format_result["agricultural_labels"] = content_result["agricultural_labels"]
        format_result["content_bypassed"] = content_result["bypassed"]

        # Add content warnings to existing warnings
        format_result["warnings"].extend(content_result["warnings"])

        # Content validation doesn't block upload, but sets flags
        if not content_result["valid"]:
            format_result["content_warning"] = True
            format_result["warnings"].append("Photo may not contain relevant agricultural content")

        return format_result

    def process_and_store_photo(
        self, file_data: bytes, filename: str, carbon_entry_id: int, user_id: int
    ) -> Dict[str, Any]:
        """
        Process, optimize, and store photo evidence securely.

        Args:
            file_data: Raw file bytes
            filename: Original filename
            carbon_entry_id: Associated carbon entry ID
            user_id: User uploading the photo

        Returns:
            Dict with storage results including URL
        """
        result = {"success": False, "photo_url": None, "photo_id": None, "errors": [], "metadata": {}}

        try:
            # First validate the photo
            validation_result = self.validate_photo(file_data, filename)
            if not validation_result["valid"]:
                result["errors"] = validation_result["errors"]
                return result

            # Generate unique filename
            file_ext = os.path.splitext(filename.lower())[1]
            unique_id = str(uuid.uuid4())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_filename = f"carbon_{carbon_entry_id}_{timestamp}_{unique_id}{file_ext}"

            # Process image for optimization. Only re-encoded pixels are stored.
            try:
                processed_data = self._process_image(file_data, file_ext)
            except PhotoProcessingError:
                result["errors"].append("The photo could not be processed, so it was not stored. Try another photo.")
                return result

            # Store file
            file_path = os.path.join(self.storage_path, safe_filename)
            stored_name = default_storage.save(file_path, ContentFile(processed_data))

            # Generate public URL
            if hasattr(default_storage, "url"):
                photo_url = default_storage.url(stored_name)
            else:
                # Fallback for local storage
                photo_url = f"/media/{stored_name}"

            # Create metadata record
            metadata = {
                "original_filename": filename,
                "stored_filename": safe_filename,
                "file_size": len(processed_data),
                "upload_timestamp": datetime.now(timezone.utc).isoformat(),
                "carbon_entry_id": carbon_entry_id,
                "uploaded_by": user_id,
                "file_hash": hashlib.sha256(processed_data).hexdigest(),
                "validation_metadata": validation_result["metadata"],
            }

            result.update({"success": True, "photo_url": photo_url, "photo_id": unique_id, "metadata": metadata})

            logger.info(f"Photo stored successfully: {safe_filename} for carbon entry {carbon_entry_id}")

        except Exception as e:
            logger.error(f"Photo storage error: {e}")
            result["errors"].append(f"Storage error: {str(e)}")

        return result

    def _extract_exif_data(self, image: Image) -> Optional[Dict[str, Any]]:
        """
        Extract useful EXIF data from image for verification purposes.
        Includes full GPS coordinate extraction for geofencing validation.

        Args:
            image: PIL Image object

        Returns:
            Dict with extracted EXIF data or None
        """
        try:
            exif_dict = image._getexif()
            if not exif_dict:
                return None

            # Extract useful metadata for verification
            useful_data = {}

            for tag_id, value in exif_dict.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)

                # Extract specific useful tags
                if tag in ["DateTime", "DateTimeOriginal", "DateTimeDigitized"]:
                    useful_data[tag] = str(value)
                elif tag in ["Make", "Model"]:  # Camera info
                    useful_data[tag] = str(value)
                elif tag == "GPSInfo":
                    useful_data["has_gps"] = True
                    # Extract full GPS coordinates for geofencing
                    gps_coords = self._parse_gps_info(value)
                    if gps_coords:
                        useful_data["gps_latitude"] = gps_coords[0]
                        useful_data["gps_longitude"] = gps_coords[1]
                elif tag in ["Software"]:  # Editing software detection
                    useful_data[tag] = str(value)

            return useful_data if useful_data else None

        except Exception as e:
            logger.warning(f"EXIF extraction failed: {e}")
            return None

    @staticmethod
    def _parse_gps_info(gps_info: Dict) -> Optional[Tuple[float, float]]:
        """
        Parse EXIF GPSInfo tag into decimal latitude/longitude.

        Args:
            gps_info: Raw GPSInfo dict from EXIF

        Returns:
            Tuple of (latitude, longitude) in decimal degrees, or None
        """
        try:
            gps_tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_info.items()}

            lat = gps_tags.get("GPSLatitude")
            lat_ref = gps_tags.get("GPSLatitudeRef")
            lon = gps_tags.get("GPSLongitude")
            lon_ref = gps_tags.get("GPSLongitudeRef")

            if not (lat and lat_ref and lon and lon_ref):
                return None

            def dms_to_decimal(dms, ref):
                """Convert degrees/minutes/seconds to decimal."""
                degrees = float(dms[0])
                minutes = float(dms[1])
                seconds = float(dms[2])
                decimal = degrees + minutes / 60 + seconds / 3600
                if ref in ["S", "W"]:
                    decimal = -decimal
                return decimal

            latitude = dms_to_decimal(lat, lat_ref)
            longitude = dms_to_decimal(lon, lon_ref)
            return (latitude, longitude)

        except Exception as e:
            logger.warning(f"GPS coordinate parsing failed: {e}")
            return None

    @staticmethod
    def validate_photo_location(
        photo_lat: float, photo_lon: float, farm_lat: float, farm_lon: float, max_distance_km: float = 50.0
    ) -> Dict[str, Any]:
        """
        Validate that a photo's GPS coordinates are within range of the farm location.
        Uses Haversine formula for distance calculation.

        Args:
            photo_lat: Photo EXIF latitude
            photo_lon: Photo EXIF longitude
            farm_lat: Farm/establishment latitude
            farm_lon: Farm/establishment longitude
            max_distance_km: Maximum allowed distance in km (default 50km)

        Returns:
            Dict with location_verified bool, distance_km, and message
        """
        try:
            # Haversine formula
            R = 6371  # Earth radius in km
            lat1, lat2 = math.radians(photo_lat), math.radians(farm_lat)
            dlat = math.radians(farm_lat - photo_lat)
            dlon = math.radians(farm_lon - photo_lon)

            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance_km = R * c

            location_verified = distance_km <= max_distance_km

            return {
                "location_verified": location_verified,
                "distance_km": round(distance_km, 2),
                "message": (
                    f"Photo taken within {distance_km:.1f}km of farm"
                    if location_verified
                    else f"Photo taken {distance_km:.1f}km from farm (max {max_distance_km}km)"
                ),
            }

        except Exception as e:
            logger.warning(f"Location validation error: {e}")
            return {
                "location_verified": False,
                "distance_km": None,
                "message": "Could not verify photo location",
            }

    def _detect_mime_from_magic_bytes(self, file_data: bytes) -> Optional[str]:
        """
        Detect MIME type from file content magic bytes (not extension).
        Defense-in-depth: prevents disguised malicious files from passing validation.

        Args:
            file_data: Raw file bytes

        Returns:
            Detected MIME type string or None if unrecognized
        """
        if len(file_data) < 12:
            return None

        # JPEG: FF D8 FF
        if file_data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"

        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if file_data[:8] == b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a":
            return "image/png"

        # WebP: RIFF....WEBP
        if file_data[:4] == b"RIFF" and file_data[8:12] == b"WEBP":
            return "image/webp"

        # HEIC/HEIF: ftyp box with heic/heix/mif1/msf1 brands
        if len(file_data) >= 12:
            # ISO Base Media File Format: size(4) + 'ftyp'(4) + brand(4)
            try:
                if file_data[4:8] == b"ftyp":
                    brand = file_data[8:12].decode("ascii", errors="ignore").lower()
                    heic_brands = {"heic", "heix", "hevc", "hevx", "mif1", "msf1", "avif"}
                    if brand in heic_brands:
                        return "image/heic"
            except Exception:
                pass

        return None

    def _process_image(self, file_data: bytes, file_ext: str) -> bytes:
        """
        Process and optimize image for storage.
        EXIF data is stripped from the output to protect farmer privacy
        (GPS coordinates, device info are NOT included in stored images).
        EXIF is extracted and stored separately in extra_data before this step.

        Supports HEIC/HEIF input (converted to JPEG for storage).

        Args:
            file_data: Raw image bytes
            file_ext: File extension

        Returns:
            Processed image bytes (EXIF-stripped)
        """
        try:
            image = Image.open(ContentFile(file_data))

            # Convert to RGB if necessary (handles RGBA, P, HEIC, etc.)
            if image.mode in ("RGBA", "LA", "P"):
                # Create white background for transparency
                rgb_image = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "P":
                    image = image.convert("RGBA")
                rgb_image.paste(image, mask=image.split()[-1] if len(image.split()) == 4 else None)
                image = rgb_image
            elif image.mode != "RGB":
                image = image.convert("RGB")

            # Resize if too large
            if max(image.size) > self.MAX_DIMENSION:
                image.thumbnail((self.MAX_DIMENSION, self.MAX_DIMENSION), Image.Resampling.LANCZOS)

            # Save optimized version to BytesIO (PIL save without exif= strips EXIF by default)
            output = io.BytesIO()
            # EXIF, XMP and PNG or WebP text are not carried by these saves, but Pillow writes a JPEG's comment
            # segment back from `info` (measured on Pillow 12.3, 2026-11-18): a comment can hold anything, so it
            # goes too and only the pixels are stored.
            image.info.pop("comment", None)

            # HEIC/HEIF always converted to JPEG for broad compatibility
            if file_ext.lower() in [".heic", ".heif"]:
                image.save(output, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)
            elif file_ext.lower() in [".jpg", ".jpeg"]:
                image.save(output, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)
            elif file_ext.lower() == ".png":
                image.save(output, format="PNG", optimize=True)
            elif file_ext.lower() == ".webp":
                image.save(output, format="WEBP", quality=self.JPEG_QUALITY, optimize=True)
            else:
                # Default to JPEG for unknown formats
                image.save(output, format="JPEG", quality=self.JPEG_QUALITY, optimize=True)

            return output.getvalue()

        except Exception as e:
            # Never fall back to the original bytes: they keep the EXIF this step strips (GPS, device) and
            # anything else the file carries beside its pixels. Until 2026-11-18 a failed re-encode stored them.
            logger.error(f"Image processing error: {e}")
            raise PhotoProcessingError(str(e)) from e

    def generate_thumbnails(self, file_data: bytes, base_s3_key: str) -> Dict[str, str]:
        """
        Generate thumbnail images at multiple sizes for consumer QR page performance.
        Thumbnails are stored alongside the original in S3 with size suffix.

        Args:
            file_data: Processed image bytes (already EXIF-stripped)
            base_s3_key: S3 key of the original image

        Returns:
            Dict mapping size name to S3 key (e.g. {"sm": "media/.../thumb_sm.jpg"})
        """
        thumbnails = {}

        try:
            image = Image.open(ContentFile(file_data))
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Generate the S3 key base (without extension)
            key_base, key_ext = os.path.splitext(base_s3_key)
            # Always store thumbnails as JPEG for smallest size
            thumb_ext = ".jpg"

            for size_name, dimensions in self.THUMBNAIL_SIZES.items():
                try:
                    thumb = image.copy()
                    thumb.thumbnail(dimensions, Image.Resampling.LANCZOS)

                    output = io.BytesIO()
                    # Lower quality for thumbnails (smaller files, faster QR page loads)
                    quality = 75 if size_name == "sm" else 80
                    thumb.save(output, format="JPEG", quality=quality, optimize=True)
                    output.seek(0)

                    thumb_key = f"{key_base}_thumb_{size_name}{thumb_ext}"
                    stored_name = default_storage.save(thumb_key, ContentFile(output.getvalue()))
                    thumbnails[size_name] = stored_name

                    logger.debug(f"Thumbnail {size_name} generated: {stored_name}")

                except Exception as e:
                    logger.warning(f"Thumbnail {size_name} generation failed: {e}")

        except Exception as e:
            logger.error(f"Thumbnail generation error: {e}")

        return thumbnails

    def _has_suspicious_content(self, file_data: bytes) -> bool:
        """
        Basic check for suspicious content in uploaded files.

        Args:
            file_data: File bytes to check

        Returns:
            True if suspicious content detected
        """
        try:
            # Executables are not searched for here. validate_photo refuses any file whose first bytes are not an
            # allowed image's (`_detect_mime_from_magic_bytes`), which is where PE, ELF and Mach-O headers have to
            # be to run, and only the re-encoded pixels are stored (`_process_image`), which drops anything else a
            # file carries. Until 2026-11-18 the executable signatures were searched anywhere in the lower-cased
            # first KB, so the two-byte PE header "MZ" matched any "mz", "Mz", "mZ" or "MZ" inside image data: of
            # 600 random-noise images per format it refused 5.8% of JPEGs, 5.0% of PNGs and 1.8% of WebPs.
            check_data = file_data[:1024].lower()
            for marker in _SCRIPT_MARKERS:
                if marker in check_data:
                    logger.warning("Suspicious content in uploaded file: %r in the first KB", marker)
                    return True
            return False

        except Exception:
            # If we can't check, be safe and reject
            return True

    def delete_photo(self, photo_url: str) -> bool:
        """
        Delete photo from storage.

        Args:
            photo_url: URL or path of photo to delete

        Returns:
            True if deleted successfully
        """
        try:
            # Extract filename from URL
            if photo_url.startswith("/media/"):
                file_path = photo_url[7:]  # Remove '/media/' prefix
            elif photo_url.startswith("http"):
                file_path = photo_url.split("/")[-1]
            else:
                file_path = photo_url

            if default_storage.exists(file_path):
                default_storage.delete(file_path)
                logger.info(f"Photo deleted: {file_path}")
                return True
            else:
                logger.warning(f"Photo not found for deletion: {file_path}")
                return False

        except Exception as e:
            logger.error(f"Photo deletion error: {e}")
            return False

    def verify_photo_integrity(self, photo_url: str, expected_hash: str) -> bool:
        """
        Verify photo hasn't been tampered with.

        Args:
            photo_url: Photo URL
            expected_hash: Expected SHA256 hash

        Returns:
            True if integrity check passes
        """
        try:
            # Extract file path from URL
            if photo_url.startswith("/media/"):
                file_path = photo_url[7:]
            else:
                file_path = photo_url.split("/")[-1]

            if not default_storage.exists(file_path):
                return False

            # Read file and compute hash
            with default_storage.open(file_path, "rb") as f:
                file_data = f.read()
                actual_hash = hashlib.sha256(file_data).hexdigest()

            return actual_hash == expected_hash

        except Exception as e:
            logger.error(f"Photo integrity check error: {e}")
            return False

    def upload_evidence_photo(
        self,
        carbon_entry,
        photo_file,
        uploaded_by,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Complete photo upload with Vision API validation and processing.

        Combines validation, processing, and storage in a single method.
        Used by the /carbon/evidence/upload/ enhanced endpoint.

        Args:
            carbon_entry: CarbonEntry model instance
            photo_file: UploadedFile object
            uploaded_by: User who uploaded the photo
            description: Optional photo description
            metadata: Optional additional metadata

        Returns:
            Dict with success status, photo_id, url, metadata, and validation status
        """
        try:
            # Read file data
            file_data = photo_file.read()

            # Step 1: Validate photo format and content with Vision API
            validation_result = self.validate_and_analyze_photo(
                file_data=file_data,
                filename=photo_file.name,
            )

            if not validation_result.get("valid", True):
                return {
                    "success": False,
                    "photo_id": None,
                    "photo_url": None,
                    "metadata": {},
                    "validation_status": validation_result.get("content_validation", "failed"),
                    "errors": validation_result.get("errors", ["Photo validation failed"]),
                }

            # Step 2: Process and store photo
            storage_result = self.process_and_store_photo(
                file_data=file_data,
                filename=photo_file.name,
                carbon_entry_id=carbon_entry.id,
                user_id=uploaded_by.id,
            )

            if not storage_result.get("success", False):
                return {
                    "success": False,
                    "photo_id": None,
                    "photo_url": None,
                    "metadata": {},
                    "validation_status": "storage_failed",
                    "errors": storage_result.get("errors", ["Failed to store photo"]),
                }

            # Step 3: Merge validation and storage results
            result_metadata = storage_result.get("metadata", {})
            result_metadata["description"] = description
            result_metadata["content_validation"] = validation_result.get("content_validation")
            result_metadata["content_confidence"] = validation_result.get("content_confidence", 0)
            result_metadata["agricultural_labels"] = validation_result.get("agricultural_labels", [])
            result_metadata["content_bypassed"] = validation_result.get("content_bypassed", False)

            if metadata:
                result_metadata.update(metadata)

            logger.info(
                f"Photo evidence uploaded for carbon entry {carbon_entry.id} "
                f"(validation: {validation_result.get('content_validation')}, "
                f"bypassed: {validation_result.get('content_bypassed')})"
            )

            return {
                "success": True,
                "photo_id": storage_result.get("photo_id"),
                "photo_url": storage_result.get("photo_url"),
                "metadata": result_metadata,
                "validation_status": validation_result.get("content_validation", "uncertain"),
            }

        except Exception as e:
            logger.error(f"Photo upload error: {e}")
            return {
                "success": False,
                "photo_id": None,
                "photo_url": None,
                "metadata": {},
                "validation_status": "error",
                "errors": [str(e)],
            }


# Singleton instance for easy importing
photo_evidence_service = PhotoEvidenceService()
