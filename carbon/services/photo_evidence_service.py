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
"""

import hashlib
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from PIL import ExifTags, Image

logger = logging.getLogger(__name__)


# Import Vision API service (lazy import to avoid circular dependencies)
def get_vision_service():
    """Get the Vision API service instance."""
    from carbon.services.vision_api_service import vision_api_service

    return vision_api_service


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

    # MVP Configuration - Simple but secure
    ALLOWED_MIME_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]

    ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"]
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB max
    MAX_PHOTOS_PER_ENTRY = 5  # Reasonable limit for MVP

    # Image processing settings
    MAX_DIMENSION = 2048  # Resize large images to save storage
    JPEG_QUALITY = 85  # Good quality vs file size balance

    def __init__(self):
        """Initialize the photo evidence service."""
        self.storage_path = "carbon_evidence/photos/"

    def validate_photo(self, file_data: bytes, filename: str) -> Dict[str, Any]:
        """
        Validate uploaded photo for security and format compliance.

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

            # MIME type validation
            detected_mime = mimetypes.guess_type(filename)[0]
            if detected_mime not in self.ALLOWED_MIME_TYPES:
                result["errors"].append(f'Invalid file type. Allowed: {", ".join(self.ALLOWED_MIME_TYPES)}')
                return result

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
            logger.info(f"Photo validation passed: {filename} ({len(file_data)} bytes)")

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

            # Process image for optimization
            processed_data = self._process_image(file_data, file_ext)

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
                elif tag in ["GPSInfo"]:  # Location data (if available)
                    useful_data["has_gps"] = True
                elif tag in ["Software"]:  # Editing software detection
                    useful_data[tag] = str(value)

            return useful_data if useful_data else None

        except Exception as e:
            logger.warning(f"EXIF extraction failed: {e}")
            return None

    def _process_image(self, file_data: bytes, file_ext: str) -> bytes:
        """
        Process and optimize image for storage.

        Args:
            file_data: Raw image bytes
            file_ext: File extension

        Returns:
            Processed image bytes
        """
        try:
            image = Image.open(ContentFile(file_data))

            # Convert to RGB if necessary (handles RGBA, P, etc.)
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

            # Save optimized version
            output = ContentFile(b"")

            if file_ext.lower() in [".jpg", ".jpeg"]:
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
            logger.error(f"Image processing error: {e}")
            # Return original data if processing fails
            return file_data

    def _has_suspicious_content(self, file_data: bytes) -> bool:
        """
        Basic check for suspicious content in uploaded files.

        Args:
            file_data: File bytes to check

        Returns:
            True if suspicious content detected
        """
        try:
            # Check for executable signatures
            suspicious_signatures = [
                b"\x4d\x5a",  # PE executable
                b"\x7f\x45\x4c\x46",  # ELF executable
                b"\xfe\xed\xfa",  # Mach-O executable
                b"<?php",  # PHP code
                b"<script",  # JavaScript
                b"javascript:",  # JavaScript URL
            ]

            # Check first 1KB of file
            check_data = file_data[:1024].lower()

            for sig in suspicious_signatures:
                if sig.lower() in check_data:
                    logger.warning("Suspicious content detected in uploaded file")
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
