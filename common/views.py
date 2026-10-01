import datetime
import json
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connections
from django.db.models import Q
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.shortcuts import render

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from redis import Redis
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.storage import is_public_media_key, using_s3_storage
from company.models import Establishment
from product.models import Parcel
from subscriptions.storage_utils import CATEGORY_MEDIA, check_storage_quota

from .aws_utils import SecureAWSClient

logger = logging.getLogger(__name__)

# Create your views here.


def health_check(request):
    # Check database connection
    db_healthy = True
    try:
        connections["default"].cursor()
    except OperationalError as e:
        db_healthy = False
        logger.error("Database connection failed: " + str(e))

    status = 200 if (db_healthy) else 503

    response = {
        "status": "healthy" if status == 200 else "unhealthy",
        "database": "connected" if db_healthy else "disconnected",
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }

    return JsonResponse(response, status=status)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def get_upload_urls(request):
    """
    Generate pre-signed URLs for direct S3 uploads.

    Expected request format:
    {
        "files": [
            {"name": "image1.jpg", "type": "image/jpeg", "size": 12345},
            {"name": "image2.png", "type": "image/png", "size": 67890}
        ],
        "entity_type": "establishment", // or "user", "company", "parcel", etc.
        "entity_id": "123" // optional, for updates to existing entities
    }
    """
    files_info = request.data.get("files", [])
    entity_type = request.data.get("entity_type", "misc")
    entity_id = request.data.get("entity_id", "")

    # Storage quota check — MEDIA (hard-limited). Sizes here are CLIENT-REPORTED, so this
    # check is advisory at the margin: a client that understates them buys itself one
    # over-quota batch. It self-corrects rather than compounds — `GalleryImage.file_size`
    # is written from the real object after upload, so the next check measures the truth.
    #
    # Summed defensively: `files_info` comes off the request body, so a `size` of `"abc"` or
    # `None` used to raise TypeError inside `sum()` and return a 500 from a quota check.
    def _reported_size(entry):
        try:
            return max(0, int(float((entry or {}).get("size", 0) or 0)))
        except (TypeError, ValueError, AttributeError):
            return 0

    total_upload_bytes = sum(_reported_size(f) for f in files_info)
    allowed, error_detail = check_storage_quota(request.user, total_upload_bytes, category=CATEGORY_MEDIA)
    if not allowed:
        return Response(error_detail, status=413)

    # Validate S3 configuration
    is_valid, error_message = SecureAWSClient.validate_s3_configuration()
    if not is_valid:
        logger.error(f"S3 configuration error: {error_message}")
        return Response({"error": "S3 storage is not properly configured", "details": error_message}, status=500)

    try:
        # Get S3 client using secure method
        s3_client = SecureAWSClient.get_s3_client()

        urls_and_keys = []
        for file_info in files_info:
            file_name = file_info.get("name")
            file_type = file_info.get("type")

            # Sanitize filename to avoid issues with spaces and special characters
            sanitized_filename = re.sub(r"[^\w\-_\.]", "_", file_name)

            # Create a unique key for the file based on entity type
            folder = f"{entity_type}s"
            if entity_id:
                key = f"{folder}/{entity_id}/{uuid.uuid4()}-{sanitized_filename}"
            else:
                # For new entities, use user ID or timestamp
                key = f"{folder}/new-{request.user.id}-{uuid.uuid4()}-{sanitized_filename}"

            # Generate a pre-signed URL for this specific file
            presigned_url = s3_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key, "ContentType": file_type},
                ExpiresIn=3600,  # URL expires in 1 hour
            )

            urls_and_keys.append(
                {
                    "uploadUrl": presigned_url,
                    "s3Key": key,
                    "publicUrl": f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{key}",
                }
            )

        return Response(urls_and_keys)

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error(f"AWS S3 ClientError: {error_code} - {str(e)}")
        return Response({"error": "Failed to generate upload URLs", "details": f"S3 error: {error_code}"}, status=500)
    except NoCredentialsError:
        logger.error("No AWS credentials available")
        return Response(
            {"error": "Storage service configuration error", "details": "Authentication failed"}, status=500
        )
    except ValueError as e:
        logger.error(f"Invalid input data: {str(e)}")
        return Response({"error": "Invalid request data", "details": str(e)}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error generating pre-signed URLs: {str(e)}")
        return Response({"error": "Internal server error", "details": "Failed to process upload request"}, status=500)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def get_presigned_url(request):
    """Generate a pre-signed URL for client-side S3 upload"""
    filename = request.data.get("filename")
    file_type = request.data.get("fileType")
    folder = request.data.get("folder", "uploads")

    if not filename or not file_type:
        return Response({"error": "Filename and fileType are required"}, status=400)

    # Storage quota check — MEDIA (hard-limited). Same client-reported caveat as
    # `get_upload_urls`: advisory at the margin, self-correcting once the real size lands
    # on the GalleryImage row.
    file_size = request.data.get("fileSize", 2 * 1024 * 1024)
    allowed, error_detail = check_storage_quota(request.user, file_size, category=CATEGORY_MEDIA)
    if not allowed:
        return Response(error_detail, status=413)

    # Sanitize filename to avoid issues with spaces and special characters
    sanitized_filename = re.sub(r"[^\w\-_\.]", "_", filename)

    # Generate a unique key for the file
    unique_filename = f"{uuid.uuid4()}-{sanitized_filename}"
    key = f"media/{folder}/{unique_filename}"

    # Only generate S3 URLs in production environment
    if using_s3_storage():
        try:
            # Generate the presigned URL using secure client
            s3_client = SecureAWSClient.get_s3_client()

            presigned_url = s3_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key, "ContentType": file_type},
                ExpiresIn=3600,  # URL expires after 1 hour
            )

            # Return the permanent S3 URL (not presigned) for storage in the database.
            # Presigned read URLs are generated on-demand when viewing images.
            permanent_url = (
                f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{key}"
            )

            return Response(
                {
                    "presigned_url": presigned_url,
                    "s3_key": key,
                    "file_url": permanent_url,
                }
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error(f"AWS S3 ClientError: {error_code} - {str(e)}")
            return Response(
                {"error": "Failed to generate presigned URL", "details": f"S3 error: {error_code}"}, status=500
            )
        except NoCredentialsError:
            logger.error("No AWS credentials available")
            return Response(
                {"error": "Storage service configuration error", "details": "Authentication failed"}, status=500
            )
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {str(e)}")
            return Response({"error": "Internal server error", "details": "Failed to process request"}, status=500)
    else:
        # In development, return a placeholder since we'll handle uploads via standard form
        return Response({"development": True, "message": "Running in development mode - use form upload instead"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def local_file_upload(request):
    """Handle file uploads in development environment"""
    # Log request details for debugging
    logger.debug(f"Request method: {request.method}")
    logger.debug(f"Content type: {request.content_type}")
    logger.debug(f"Request FILES: {request.FILES}")
    logger.debug(f"Request headers: {request.headers}")

    # If Content-Type is application/json but we have FILES, Django's parser has already handled it
    if request.content_type and "application/json" in request.content_type and request.FILES:
        logger.info("Request has application/json Content-Type but contains files. Proceeding anyway.")

    try:
        # Check if we have files in the request
        if not request.FILES:
            logger.error("No files found in request.FILES")
            # Try to get raw request body if available
            try:
                if hasattr(request, "_body"):
                    logger.error(f"Raw request body: {request._body[:100]}...")
            except Exception as e:
                logger.error(f"Could not access raw body: {str(e)}")

            return Response({"error": "No files were submitted"}, status=400)

        # Get the file from the request
        upload_file = request.FILES.get("file")
        if not upload_file:
            logger.error(f"No file field found. Available fields: {list(request.FILES.keys())}")
            return Response(
                {"error": 'No file found with key "file"', "available_keys": list(request.FILES.keys())}, status=400
            )

        logger.info(
            f"Processing file upload: {upload_file.name}, size: {upload_file.size}, type: {upload_file.content_type}"
        )

        # Storage quota check — MEDIA, the hard-limited category. The DMS document shelf
        # is metered separately and never refused (`subscriptions.storage_accounting`).
        allowed, error_detail = check_storage_quota(request.user, upload_file.size, category=CATEGORY_MEDIA)
        if not allowed:
            return Response(error_detail, status=413)

        # Read file data
        file_data = upload_file.read()

        # MVP Photo Verification: Validate image content if it's a photo
        content_validation = None
        if upload_file.content_type and upload_file.content_type.startswith("image/"):
            try:
                from carbon.services.photo_evidence_service import photo_evidence_service

                # Extract event type context for event-specific validation
                event_type = request.data.get("event_type") or request.POST.get("event_type")
                subtype = request.data.get("subtype") or request.POST.get("subtype")

                validation_result = photo_evidence_service.validate_and_analyze_photo(
                    file_data=file_data,
                    filename=upload_file.name,
                    event_type=event_type,
                    subtype=subtype,
                )
                content_validation = {
                    "valid": validation_result.get("valid", True),
                    "content_validation": validation_result.get("content_validation"),
                    "content_confidence": validation_result.get("content_confidence", 0),
                    "agricultural_labels": validation_result.get("agricultural_labels", []),
                    "content_bypassed": validation_result.get("content_bypassed", False),
                    "warnings": validation_result.get("warnings", []),
                }
                logger.info(
                    f"Image content validation: {content_validation.get('content_validation')} "
                    f"(bypassed: {content_validation.get('content_bypassed')})"
                )
            except Exception as e:
                logger.warning(f"Photo content validation failed (continuing anyway): {e}")
                content_validation = {"error": str(e), "valid": True}

        # Create unique filename to prevent overwrites
        filename = f"{uuid.uuid4()}-{upload_file.name}"

        # Save the file
        save_path = f"uploads/{filename}"
        path = default_storage.save(save_path, ContentFile(file_data))

        # Get the full URL
        file_url = request.build_absolute_uri(settings.MEDIA_URL + path)
        logger.info(f"File saved to {path}, URL: {file_url}")

        # Return success response with MVP Photo Verification data
        response_data = {"file_url": file_url, "path": path, "success": True}
        if content_validation:
            response_data["content_validation"] = content_validation
        return Response(response_data)

    except UnicodeDecodeError as e:
        logger.error(f"Unicode decode error during file upload: {str(e)}")
        return Response(
            {
                "error": "File upload failed: Invalid character encoding",
                "detail": "Binary data handling error. Ensure your request is using multipart/form-data.",
            },
            status=400,
        )
    except IOError as e:
        logger.error(f"IO error during file upload: {str(e)}")
        return Response(
            {"error": "File upload failed: Storage error", "detail": "Unable to save file to storage"}, status=500
        )
    except Exception as e:
        logger.exception(f"Unexpected error uploading file: {str(e)}")
        return Response(
            {"error": "File upload failed", "detail": "An unexpected error occurred during upload"}, status=500
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def get_presigned_read_url(request):
    """Generate a presigned URL for reading an existing S3 file"""
    s3_url = request.data.get("s3_url")
    s3_key = request.data.get("s3_key")

    if not s3_url and not s3_key:
        return Response({"error": "s3_url or s3_key is required"}, status=400)

    # Extract S3 key from URL if URL was provided
    if s3_url and not s3_key:
        try:
            # Parse S3 URL to extract key
            # Format: https://bucket.s3.region.amazonaws.com/key
            from urllib.parse import urlparse

            parsed = urlparse(s3_url)
            s3_key = parsed.path.lstrip("/")
        except (ValueError, AttributeError) as e:
            logger.error(f"Invalid S3 URL format: {str(e)}")
            return Response({"error": "Invalid S3 URL format", "details": str(e)}, status=400)

    # Only keys anonymous readers could fetch anyway (consumer images). This endpoint signed ANY
    # key it was sent, with no check that the caller may see it, which would make every private
    # record readable by any signed-in account once the bucket stops serving them anonymously.
    # Private records are served by their own authorised routes (2026-10-01).
    if not is_public_media_key(s3_key):
        logger.warning("Presigned read refused for a key outside the public media prefixes: %s", s3_key)
        return Response({"error": "This file is not served through this endpoint."}, status=403)

    # Only generate presigned URLs in production environment
    if using_s3_storage():
        try:
            # Get S3 client using secure method
            s3_client = SecureAWSClient.get_s3_client()

            # Generate presigned URL for reading
            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": s3_key},
                ExpiresIn=3600,  # URL expires after 1 hour
            )

            return Response({"presigned_url": presigned_url, "s3_key": s3_key, "expires_in": 3600})

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error(f"AWS S3 ClientError: {error_code} - {str(e)}")
            return Response({"error": "Failed to generate read URL", "details": f"S3 error: {error_code}"}, status=500)
        except NoCredentialsError:
            logger.error("No AWS credentials available")
            return Response(
                {"error": "Storage service configuration error", "details": "Authentication failed"}, status=500
            )
        except Exception as e:
            logger.error(f"Unexpected error generating presigned read URL: {str(e)}")
            return Response({"error": "Internal server error", "details": "Failed to generate read URL"}, status=500)
    else:
        # In development, return the original URL or a placeholder
        return Response({"development": True, "presigned_url": s3_url or f"/media/{s3_key}", "s3_key": s3_key})


def _generate_single_presigned_url(s3_client, bucket_name, s3_key):
    """Helper function to generate a single presigned URL"""
    try:
        presigned_url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket_name, "Key": s3_key}, ExpiresIn=3600
        )
        return s3_key, presigned_url
    except Exception as e:
        logger.error(f"Error generating presigned URL for {s3_key}: {str(e)}")
        return s3_key, None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def get_presigned_read_urls_batch(request):
    """Generate presigned URLs for multiple S3 files in parallel - 2025 Best Practice"""
    start_time = time.time()
    s3_urls = request.data.get("s3_urls", [])

    if not s3_urls or not isinstance(s3_urls, list):
        return Response({"error": "s3_urls must be a non-empty list"}, status=400)

    if len(s3_urls) > 50:  # Rate limiting for performance
        return Response({"error": "Maximum 50 URLs per batch request"}, status=400)

    # Filter out empty/null URLs
    valid_s3_urls = [url for url in s3_urls if url and url.strip()]

    if not valid_s3_urls:
        return Response({"presigned_urls": {}}, status=200)

    # Only generate presigned URLs in production environment
    if using_s3_storage():
        try:
            # Initialize S3 client using secure method
            s3_client = SecureAWSClient.get_s3_client()

            presigned_urls = {}
            s3_keys = []

            # Extract S3 keys from URLs
            for s3_url in valid_s3_urls:
                try:
                    parsed = urlparse(s3_url)
                    s3_key = parsed.path.lstrip("/")
                    if not is_public_media_key(s3_key):
                        # Same rule as the single endpoint: never sign a private record here.
                        logger.warning("Presigned batch read refused for a non-public key: %s", s3_key)
                        presigned_urls[s3_url] = None
                        continue
                    s3_keys.append((s3_url, s3_key))
                except Exception as e:
                    logger.warning(f"Invalid S3 URL {s3_url}: {str(e)}")
                    presigned_urls[s3_url] = None

            # Generate presigned URLs in parallel for optimal performance
            with ThreadPoolExecutor(max_workers=10) as executor:
                # Submit all tasks
                future_to_url = {
                    executor.submit(
                        _generate_single_presigned_url, s3_client, settings.AWS_STORAGE_BUCKET_NAME, s3_key
                    ): original_url
                    for original_url, s3_key in s3_keys
                }

                # Collect results as they complete
                for future in as_completed(future_to_url):
                    original_url = future_to_url[future]
                    try:
                        s3_key, presigned_url = future.result()
                        presigned_urls[original_url] = presigned_url
                    except Exception as e:
                        logger.error(f"Error processing {original_url}: {str(e)}")
                        presigned_urls[original_url] = None

            # Add performance metrics
            processing_time = time.time() - start_time

            return Response(
                {
                    "presigned_urls": presigned_urls,
                    "expires_in": 3600,
                    "batch_size": len(valid_s3_urls),
                    "processing_time_ms": round(processing_time * 1000, 2),
                    "success_count": sum(1 for url in presigned_urls.values() if url is not None),
                }
            )

        except Exception as e:
            logger.error(f"Error generating batch presigned URLs: {str(e)}")
            return Response({"error": str(e)}, status=500)
    else:
        # In development, return the original URLs
        presigned_urls = {url: url for url in valid_s3_urls}
        return Response({"development": True, "presigned_urls": presigned_urls, "batch_size": len(valid_s3_urls)})


class GlobalSearchPagination(PageNumberPagination):
    """Custom pagination for search results"""

    page_size = 20
    page_size_query_param = "limit"
    max_page_size = 50


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def global_search(request):
    """
    Global search endpoint for establishments and parcels.

    Query Parameters:
    - q: Search query string (required, min 2 characters)
    - types: Comma-separated list of types to search ('establishment', 'parcel')
    - limit: Number of results per page (default: 20, max: 50)
    - offset: Starting offset for pagination

    Returns:
    - results: List of search results with type, name, description, metadata
    - count: Total number of results
    - next/previous: Pagination URLs
    """
    try:
        # Get search parameters
        query = request.GET.get("q", "").strip()
        types = request.GET.get("types", "establishment,parcel").split(",")

        # Validate query
        if not query or len(query) < 2:
            return Response(
                {"error": 'Query parameter "q" is required and must be at least 2 characters long'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get user's companies for permission filtering
        user_companies = []
        if hasattr(request.user, "companies") and request.user.companies.exists():
            user_companies = request.user.companies.all()
        elif hasattr(request.user, "usercompany_set"):
            user_companies = [uc.company for uc in request.user.usercompany_set.all()]

        if not user_companies:
            return Response({"results": [], "count": 0, "message": "No companies associated with user"})

        company_ids = [company.id for company in user_companies]
        results = []

        # Search establishments
        if "establishment" in types:
            establishment_query = Q(
                (
                    Q(name__icontains=query)
                    | Q(description__icontains=query)
                    | Q(address__icontains=query)
                    | Q(city__icontains=query)
                    | Q(zone__icontains=query)
                    | Q(state__icontains=query)
                )
                & Q(company_id__in=company_ids)
                & Q(is_active=True)
            )

            establishments = Establishment.objects.filter(establishment_query).select_related("company", "album")[:25]

            for establishment in establishments:
                # Get location string
                location_parts = [establishment.city, establishment.state]
                location = ", ".join(filter(None, location_parts))

                # Get image URL
                image_url = None
                if (
                    establishment.album
                    and hasattr(establishment.album, "images")
                    and establishment.album.images.exists()
                ):
                    first_image = establishment.album.images.first()
                    if first_image and first_image.image:
                        image_url = first_image.image.url

                # No carbon figure here (removed 2026-09-30). This set `carbon_score` to
                # parcel_count * 25.5, "an example calculation", and the navbar search printed it
                # as "kg CO₂" beside a leaf. A made-up number with a real unit. Search finds a farm;
                # carbon lives in its own reporting views.

                results.append(
                    {
                        "id": establishment.id,
                        "type": "establishment",
                        "name": establishment.name,
                        "description": establishment.description,
                        "location": location,
                        "image_url": image_url,
                        "area": f"{establishment.total_acreage} acres" if establishment.total_acreage else None,
                        "status": "Active" if establishment.is_active else "Inactive",
                        "establishment_id": establishment.id,
                        "company_id": establishment.company_id,
                        "created_at": (
                            establishment.company.created_at.isoformat()
                            if hasattr(establishment.company, "created_at")
                            else None
                        ),
                        "updated_at": (
                            establishment.company.updated_at.isoformat()
                            if hasattr(establishment.company, "updated_at")
                            else None
                        ),
                    }
                )

        # Search parcels
        if "parcel" in types:
            parcel_query = Q(
                (
                    Q(name__icontains=query)
                    | Q(description__icontains=query)
                    | Q(address__icontains=query)
                    | Q(soil_type__icontains=query)
                    | Q(unique_code__icontains=query)
                )
                & Q(establishment__company_id__in=company_ids)
            )

            parcels = Parcel.objects.filter(parcel_query).select_related(
                "establishment", "establishment__company", "album", "product"
            )[:25]

            for parcel in parcels:
                # Get location (parcel address or establishment location)
                if parcel.address:
                    location = parcel.address
                else:
                    location_parts = [parcel.establishment.city, parcel.establishment.state]
                    location = ", ".join(filter(None, location_parts))

                # Get image URL
                image_url = None
                if parcel.album and hasattr(parcel.album, "images") and parcel.album.images.exists():
                    first_image = parcel.album.images.first()
                    if first_image and first_image.image:
                        image_url = first_image.image.url

                # No carbon figure here either: the parcel branch served a real footprint under the
                # same key and label as the invented establishment one, so a reader could not tell
                # which row was which.

                results.append(
                    {
                        "id": parcel.id,
                        "type": "parcel",
                        "name": parcel.name,
                        "description": parcel.description,
                        "location": location,
                        "image_url": image_url,
                        "area": f"{parcel.area} hectares" if parcel.area else None,
                        "status": "Standard",
                        "establishment_id": parcel.establishment_id,
                        "company_id": parcel.establishment.company_id,
                        "created_at": None,  # Parcel model doesn't have created_at
                        "updated_at": None,  # Parcel model doesn't have updated_at
                    }
                )

        # Sort results by relevance (exact matches first, then partial matches)
        query_lower = query.lower()

        def relevance_score(result):
            name_lower = result["name"].lower()
            if name_lower == query_lower:
                return 3  # Exact match
            elif name_lower.startswith(query_lower):
                return 2  # Starts with query
            elif query_lower in name_lower:
                return 1  # Contains query
            else:
                return 0  # Description/other field match

        results.sort(key=relevance_score, reverse=True)

        # Apply pagination
        paginator = GlobalSearchPagination()
        paginated_results = paginator.paginate_queryset(results, request)

        return Response(
            {
                "results": paginated_results,
                "count": len(results),
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            }
        )

    except Exception as e:
        logger.error(f"Error in global search: {str(e)}")
        return Response(
            {
                "error": "Internal server error during search",
                "detail": str(e) if settings.DEBUG else "Search temporarily unavailable",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
