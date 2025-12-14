"""
Management command to test Google Cloud Vision API integration.

Usage:
    # Test with development bypass (no API calls)
    python manage.py test_vision_api

    # Test with a real image file
    python manage.py test_vision_api --image /path/to/photo.jpg

    # Force real API calls (requires API key configured)
    python manage.py test_vision_api --image /path/to/photo.jpg --force-api

    # Test with event type context
    python manage.py test_vision_api --image /path/to/photo.jpg --event-type chemical --subtype FE
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test Google Cloud Vision API integration for photo verification"

    def add_arguments(self, parser):
        parser.add_argument(
            "--image",
            type=str,
            help="Path to an image file to analyze",
        )
        parser.add_argument(
            "--force-api",
            action="store_true",
            help="Force real API calls even in development mode",
        )
        parser.add_argument(
            "--event-type",
            type=str,
            choices=["weather", "production", "chemical", "general", "equipment", "soil", "pest", "business"],
            help="Event type for context-specific validation",
        )
        parser.add_argument(
            "--subtype",
            type=str,
            help="Event subtype (e.g., FE for fertilizer, HA for harvest)",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Google Cloud Vision API Test ===\n"))

        # Display current configuration
        self._display_configuration()

        # Import the Vision API service
        from carbon.services.vision_api_service import vision_api_service

        # Override settings if force-api is specified
        if options["force_api"]:
            self.stdout.write(self.style.WARNING("\nForcing real API calls...\n"))
            vision_api_service._bypass_in_dev = False
            vision_api_service._enabled = True

        # Display service state
        self._display_service_state(vision_api_service)

        # Get or create test image data
        if options["image"]:
            image_data = self._load_image(options["image"])
            if image_data is None:
                return
        else:
            image_data = self._get_test_image()

        # Perform analysis
        self._analyze_image(vision_api_service, image_data, options)

    def _display_configuration(self):
        """Display current Vision API configuration."""
        self.stdout.write("Configuration:")
        self.stdout.write(f"  DEBUG mode: {settings.DEBUG}")
        self.stdout.write(f"  VISION_API_ENABLED: {getattr(settings, 'VISION_API_ENABLED', False)}")
        self.stdout.write(f"  VISION_API_BYPASS_IN_DEV: {getattr(settings, 'VISION_API_BYPASS_IN_DEV', True)}")

        api_key = getattr(settings, "GOOGLE_CLOUD_VISION_API_KEY", "")
        if api_key:
            masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            self.stdout.write(f"  API Key: {masked_key}")
        else:
            self.stdout.write(self.style.WARNING("  API Key: NOT CONFIGURED"))

    def _display_service_state(self, service):
        """Display Vision API service state."""
        self.stdout.write("\nService State:")
        self.stdout.write(f"  is_enabled: {service.is_enabled}")
        self.stdout.write(f"  should_bypass: {service.should_bypass}")

        if service.should_bypass:
            self.stdout.write(self.style.SUCCESS("\n  >>> Running in DEVELOPMENT BYPASS mode"))
            self.stdout.write("  >>> No real API calls will be made\n")
        elif service.is_enabled:
            self.stdout.write(self.style.SUCCESS("\n  >>> Running in PRODUCTION mode"))
            self.stdout.write("  >>> Real API calls will be made\n")
        else:
            self.stdout.write(self.style.WARNING("\n  >>> API is DISABLED"))
            self.stdout.write("  >>> Will return uncertain result\n")

    def _load_image(self, path):
        """Load image from file path."""
        if not os.path.exists(path):
            self.stdout.write(self.style.ERROR(f"Image file not found: {path}"))
            return None

        try:
            with open(path, "rb") as f:
                image_data = f.read()
            self.stdout.write(f"\nLoaded image: {path}")
            self.stdout.write(f"  Size: {len(image_data) / 1024:.1f} KB")
            return image_data
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error loading image: {e}"))
            return None

    def _get_test_image(self):
        """Generate a minimal test image for bypass testing."""
        # Create a minimal valid JPEG (1x1 pixel green)
        # This is just for testing the bypass mode
        minimal_jpeg = bytes(
            [
                0xFF,
                0xD8,
                0xFF,
                0xE0,
                0x00,
                0x10,
                0x4A,
                0x46,
                0x49,
                0x46,
                0x00,
                0x01,
                0x01,
                0x00,
                0x00,
                0x01,
                0x00,
                0x01,
                0x00,
                0x00,
                0xFF,
                0xDB,
                0x00,
                0x43,
                0x00,
                0x08,
                0x06,
                0x06,
                0x07,
                0x06,
                0x05,
                0x08,
                0x07,
                0x07,
                0x07,
                0x09,
                0x09,
                0x08,
                0x0A,
                0x0C,
                0x14,
                0x0D,
                0x0C,
                0x0B,
                0x0B,
                0x0C,
                0x19,
                0x12,
                0x13,
                0x0F,
                0x14,
                0x1D,
                0x1A,
                0x1F,
                0x1E,
                0x1D,
                0x1A,
                0x1C,
                0x1C,
                0x20,
                0x24,
                0x2E,
                0x27,
                0x20,
                0x22,
                0x2C,
                0x23,
                0x1C,
                0x1C,
                0x28,
                0x37,
                0x29,
                0x2C,
                0x30,
                0x31,
                0x34,
                0x34,
                0x34,
                0x1F,
                0x27,
                0x39,
                0x3D,
                0x38,
                0x32,
                0x3C,
                0x2E,
                0x33,
                0x34,
                0x32,
                0xFF,
                0xC0,
                0x00,
                0x0B,
                0x08,
                0x00,
                0x01,
                0x00,
                0x01,
                0x01,
                0x01,
                0x11,
                0x00,
                0xFF,
                0xC4,
                0x00,
                0x1F,
                0x00,
                0x00,
                0x01,
                0x05,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x01,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x01,
                0x02,
                0x03,
                0x04,
                0x05,
                0x06,
                0x07,
                0x08,
                0x09,
                0x0A,
                0x0B,
                0xFF,
                0xC4,
                0x00,
                0xB5,
                0x10,
                0x00,
                0x02,
                0x01,
                0x03,
                0x03,
                0x02,
                0x04,
                0x03,
                0x05,
                0x05,
                0x04,
                0x04,
                0x00,
                0x00,
                0x01,
                0x7D,
                0x01,
                0x02,
                0x03,
                0x00,
                0x04,
                0x11,
                0x05,
                0x12,
                0x21,
                0x31,
                0x41,
                0x06,
                0x13,
                0x51,
                0x61,
                0x07,
                0x22,
                0x71,
                0x14,
                0x32,
                0x81,
                0x91,
                0xA1,
                0x08,
                0x23,
                0x42,
                0xB1,
                0xC1,
                0x15,
                0x52,
                0xD1,
                0xF0,
                0x24,
                0x33,
                0x62,
                0x72,
                0x82,
                0x09,
                0x0A,
                0x16,
                0x17,
                0x18,
                0x19,
                0x1A,
                0x25,
                0x26,
                0x27,
                0x28,
                0x29,
                0x2A,
                0x34,
                0x35,
                0x36,
                0x37,
                0x38,
                0x39,
                0x3A,
                0x43,
                0x44,
                0x45,
                0x46,
                0x47,
                0x48,
                0x49,
                0x4A,
                0x53,
                0x54,
                0x55,
                0x56,
                0x57,
                0x58,
                0x59,
                0x5A,
                0x63,
                0x64,
                0x65,
                0x66,
                0x67,
                0x68,
                0x69,
                0x6A,
                0x73,
                0x74,
                0x75,
                0x76,
                0x77,
                0x78,
                0x79,
                0x7A,
                0x83,
                0x84,
                0x85,
                0x86,
                0x87,
                0x88,
                0x89,
                0x8A,
                0x92,
                0x93,
                0x94,
                0x95,
                0x96,
                0x97,
                0x98,
                0x99,
                0x9A,
                0xA2,
                0xA3,
                0xA4,
                0xA5,
                0xA6,
                0xA7,
                0xA8,
                0xA9,
                0xAA,
                0xB2,
                0xB3,
                0xB4,
                0xB5,
                0xB6,
                0xB7,
                0xB8,
                0xB9,
                0xBA,
                0xC2,
                0xC3,
                0xC4,
                0xC5,
                0xC6,
                0xC7,
                0xC8,
                0xC9,
                0xCA,
                0xD2,
                0xD3,
                0xD4,
                0xD5,
                0xD6,
                0xD7,
                0xD8,
                0xD9,
                0xDA,
                0xE1,
                0xE2,
                0xE3,
                0xE4,
                0xE5,
                0xE6,
                0xE7,
                0xE8,
                0xE9,
                0xEA,
                0xF1,
                0xF2,
                0xF3,
                0xF4,
                0xF5,
                0xF6,
                0xF7,
                0xF8,
                0xF9,
                0xFA,
                0xFF,
                0xDA,
                0x00,
                0x08,
                0x01,
                0x01,
                0x00,
                0x00,
                0x3F,
                0x00,
                0xFB,
                0xD5,
                0xDB,
                0x94,
                0xFF,
                0xD9,
            ]
        )
        self.stdout.write("\nUsing minimal test image (for bypass mode testing)")
        self.stdout.write("  Note: For real API testing, use --image /path/to/photo.jpg")
        return minimal_jpeg

    def _analyze_image(self, service, image_data, options):
        """Perform image analysis and display results."""
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- Analysis Results ---\n"))

        try:
            if options["event_type"]:
                self.stdout.write(f"Event context: {options['event_type']}")
                if options["subtype"]:
                    self.stdout.write(f"Event subtype: {options['subtype']}")
                result = service.validate_for_event_type(
                    image_data,
                    options["event_type"],
                    options.get("subtype"),
                )
            else:
                result = service.analyze_photo(image_data)

            # Display results
            self._display_result(result)

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nError during analysis: {e}"))
            import traceback

            self.stdout.write(traceback.format_exc())

    def _display_result(self, result):
        """Display analysis result in a formatted way."""
        # Validation result
        validation_status = result.validation_result.value
        if result.is_valid:
            self.stdout.write(self.style.SUCCESS(f"Validation Result: {validation_status}"))
        else:
            self.stdout.write(self.style.ERROR(f"Validation Result: {validation_status}"))

        # Confidence score
        confidence_pct = result.confidence_score * 100
        if confidence_pct >= 80:
            style = self.style.SUCCESS
        elif confidence_pct >= 50:
            style = self.style.WARNING
        else:
            style = self.style.ERROR
        self.stdout.write(style(f"Confidence Score: {confidence_pct:.1f}%"))

        # Detected labels
        if result.detected_labels:
            self.stdout.write(f"\nDetected Labels ({len(result.detected_labels)}):")
            for label in result.detected_labels[:10]:
                self.stdout.write(f"  - {label}")
            if len(result.detected_labels) > 10:
                self.stdout.write(f"  ... and {len(result.detected_labels) - 10} more")

        # Agricultural labels
        if result.agricultural_labels:
            self.stdout.write(self.style.SUCCESS(f"\nAgricultural Labels ({len(result.agricultural_labels)}):"))
            for label in result.agricultural_labels:
                self.stdout.write(self.style.SUCCESS(f"  - {label}"))

        # Warnings
        if result.warnings:
            self.stdout.write(self.style.WARNING(f"\nWarnings ({len(result.warnings)}):"))
            for warning in result.warnings:
                self.stdout.write(self.style.WARNING(f"  - {warning}"))

        # Error message
        if result.error_message:
            self.stdout.write(self.style.ERROR(f"\nError: {result.error_message}"))

        # Raw response info
        if result.raw_response:
            self.stdout.write(f"\nRaw Response Available: Yes")
            if "bypassed" in result.raw_response:
                self.stdout.write(self.style.WARNING("  Mode: Development Bypass (simulated)"))

        self.stdout.write("")
