from django.shortcuts import render
from django.http import JsonResponse
from django.db import connections
from django.db.utils import OperationalError
from redis import Redis
from redis.exceptions import RedisError
import logging
import datetime
import boto3
import uuid
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import time
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from botocore.exceptions import ClientError, BotoCoreError, NoCredentialsError
from .aws_utils import SecureAWSClient

logger = logging.getLogger(__name__)

# Create your views here.

def health_check(request):
    # Check database connection
    db_healthy = True
    try:
        connections['default'].cursor()
    except OperationalError as e:
        db_healthy = False
        logger.error("Database connection failed: " + str(e))

    status = 200 if (db_healthy) else 503
    
    response = {
        "status": "healthy" if status == 200 else "unhealthy",
        "database": "connected" if db_healthy else "disconnected",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    
    return JsonResponse(response, status=status)


@api_view(['POST'])
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
    files_info = request.data.get('files', [])
    entity_type = request.data.get('entity_type', 'misc')
    entity_id = request.data.get('entity_id', '')
    
    # Validate S3 configuration
    is_valid, error_message = SecureAWSClient.validate_s3_configuration()
    if not is_valid:
        logger.error(f"S3 configuration error: {error_message}")
        return Response(
            {"error": "S3 storage is not properly configured", "details": error_message}, 
            status=500
        )
    
    try:
        # Get S3 client using secure method
        s3_client = SecureAWSClient.get_s3_client()
        
        urls_and_keys = []
        for file_info in files_info:
            file_name = file_info.get('name')
            file_type = file_info.get('type')
            
            # Sanitize filename to avoid issues with spaces and special characters
            sanitized_filename = re.sub(r'[^\w\-_\.]', '_', file_name)
            
            # Create a unique key for the file based on entity type
            folder = f"{entity_type}s"
            if entity_id:
                key = f"{folder}/{entity_id}/{uuid.uuid4()}-{sanitized_filename}"
            else:
                # For new entities, use user ID or timestamp
                key = f"{folder}/new-{request.user.id}-{uuid.uuid4()}-{sanitized_filename}"
            
            # Generate a pre-signed URL for this specific file
            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': key,
                    'ContentType': file_type
                },
                ExpiresIn=3600  # URL expires in 1 hour
            )
            
            urls_and_keys.append({
                'uploadUrl': presigned_url,
                's3Key': key,
                'publicUrl': f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com/{key}"
            })
        
        return Response(urls_and_keys)
    
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"AWS S3 ClientError: {error_code} - {str(e)}")
        return Response({
            "error": "Failed to generate upload URLs",
            "details": f"S3 error: {error_code}"
        }, status=500)
    except NoCredentialsError:
        logger.error("No AWS credentials available")
        return Response({
            "error": "Storage service configuration error",
            "details": "Authentication failed"
        }, status=500)
    except ValueError as e:
        logger.error(f"Invalid input data: {str(e)}")
        return Response({
            "error": "Invalid request data",
            "details": str(e)
        }, status=400)
    except Exception as e:
        logger.error(f"Unexpected error generating pre-signed URLs: {str(e)}")
        return Response({
            "error": "Internal server error",
            "details": "Failed to process upload request"
        }, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_presigned_url(request):
    """Generate a pre-signed URL for client-side S3 upload"""
    filename = request.data.get('filename')
    file_type = request.data.get('fileType')
    folder = request.data.get('folder', 'uploads')
    
    if not filename or not file_type:
        return Response({'error': 'Filename and fileType are required'}, status=400)
    
    # Sanitize filename to avoid issues with spaces and special characters
    sanitized_filename = re.sub(r'[^\w\-_\.]', '_', filename)
    
    # Generate a unique key for the file
    unique_filename = f"{uuid.uuid4()}-{sanitized_filename}"
    key = f"media/{folder}/{unique_filename}"
    
    # Only generate S3 URLs in production environment
    if settings.DEFAULT_FILE_STORAGE == 'storages.backends.s3boto3.S3Boto3Storage':
        try:
            # Generate the presigned URL using secure client
            s3_client = SecureAWSClient.get_s3_client()
            
            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': key,
                    'ContentType': file_type
                },
                ExpiresIn=3600  # URL expires after 1 hour
            )
            
            # Generate a presigned URL for reading the file after upload
            read_url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': key
                },
                ExpiresIn=3600  # URL expires after 1 hour
            )
            
            return Response({
                'presigned_url': presigned_url,
                's3_key': key,
                'file_url': read_url  # Use presigned read URL instead of direct S3 URL
            })
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"AWS S3 ClientError: {error_code} - {str(e)}")
            return Response({
                'error': 'Failed to generate presigned URL',
                'details': f'S3 error: {error_code}'
            }, status=500)
        except NoCredentialsError:
            logger.error("No AWS credentials available")
            return Response({
                'error': 'Storage service configuration error',
                'details': 'Authentication failed'
            }, status=500)
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {str(e)}")
            return Response({
                'error': 'Internal server error',
                'details': 'Failed to process request'
            }, status=500)
    else:
        # In development, return a placeholder since we'll handle uploads via standard form
        return Response({
            'development': True,
            'message': 'Running in development mode - use form upload instead'
        })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def local_file_upload(request):
    """Handle file uploads in development environment"""
    # Log request details for debugging
    logger.debug(f"Request method: {request.method}")
    logger.debug(f"Content type: {request.content_type}")
    logger.debug(f"Request FILES: {request.FILES}")
    logger.debug(f"Request headers: {request.headers}")
    
    # If Content-Type is application/json but we have FILES, Django's parser has already handled it
    if request.content_type and 'application/json' in request.content_type and request.FILES:
        logger.info("Request has application/json Content-Type but contains files. Proceeding anyway.")
    
    try:
        # Check if we have files in the request
        if not request.FILES:
            logger.error("No files found in request.FILES")
            # Try to get raw request body if available
            try:
                if hasattr(request, '_body'):
                    logger.error(f"Raw request body: {request._body[:100]}...")
            except Exception as e:
                logger.error(f"Could not access raw body: {str(e)}")
                
            return Response({'error': 'No files were submitted'}, status=400)
        
        # Get the file from the request
        upload_file = request.FILES.get('file')
        if not upload_file:
            logger.error(f"No file field found. Available fields: {list(request.FILES.keys())}")
            return Response({
                'error': 'No file found with key "file"',
                'available_keys': list(request.FILES.keys())
            }, status=400)
        
        logger.info(f"Processing file upload: {upload_file.name}, size: {upload_file.size}, type: {upload_file.content_type}")
        
        # Create unique filename to prevent overwrites
        filename = f"{uuid.uuid4()}-{upload_file.name}"
        
        # Save the file
        save_path = f'uploads/{filename}'
        path = default_storage.save(save_path, ContentFile(upload_file.read()))
        
        # Get the full URL
        file_url = request.build_absolute_uri(settings.MEDIA_URL + path)
        logger.info(f"File saved to {path}, URL: {file_url}")
        
        # Return success response
        return Response({
            'file_url': file_url,
            'path': path,
            'success': True
        })
        
    except UnicodeDecodeError as e:
        logger.error(f"Unicode decode error during file upload: {str(e)}")
        return Response({
            'error': 'File upload failed: Invalid character encoding',
            'detail': 'Binary data handling error. Ensure your request is using multipart/form-data.'
        }, status=400)
    except IOError as e:
        logger.error(f"IO error during file upload: {str(e)}")
        return Response({
            'error': 'File upload failed: Storage error',
            'detail': 'Unable to save file to storage'
        }, status=500)
    except Exception as e:
        logger.exception(f"Unexpected error uploading file: {str(e)}")
        return Response({
            'error': 'File upload failed',
            'detail': 'An unexpected error occurred during upload'
        }, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_presigned_read_url(request):
    """Generate a presigned URL for reading an existing S3 file"""
    s3_url = request.data.get('s3_url')
    s3_key = request.data.get('s3_key')
    
    if not s3_url and not s3_key:
        return Response({'error': 's3_url or s3_key is required'}, status=400)
    
    # Extract S3 key from URL if URL was provided
    if s3_url and not s3_key:
        try:
            # Parse S3 URL to extract key
            # Format: https://bucket.s3.region.amazonaws.com/key
            from urllib.parse import urlparse
            parsed = urlparse(s3_url)
            s3_key = parsed.path.lstrip('/')
        except (ValueError, AttributeError) as e:
            logger.error(f"Invalid S3 URL format: {str(e)}")
            return Response({'error': 'Invalid S3 URL format', 'details': str(e)}, status=400)
    
    # Only generate presigned URLs in production environment
    if settings.DEFAULT_FILE_STORAGE == 'storages.backends.s3boto3.S3Boto3Storage':
        try:
            # Get S3 client using secure method
            s3_client = SecureAWSClient.get_s3_client()
            
            # Generate presigned URL for reading
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': s3_key
                },
                ExpiresIn=3600  # URL expires after 1 hour
            )
            
            return Response({
                'presigned_url': presigned_url,
                's3_key': s3_key,
                'expires_in': 3600
            })
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"AWS S3 ClientError: {error_code} - {str(e)}")
            return Response({
                'error': 'Failed to generate read URL',
                'details': f'S3 error: {error_code}'
            }, status=500)
        except NoCredentialsError:
            logger.error("No AWS credentials available")
            return Response({
                'error': 'Storage service configuration error',
                'details': 'Authentication failed'
            }, status=500)
        except Exception as e:
            logger.error(f"Unexpected error generating presigned read URL: {str(e)}")
            return Response({
                'error': 'Internal server error',
                'details': 'Failed to generate read URL'
            }, status=500)
    else:
        # In development, return the original URL or a placeholder
        return Response({
            'development': True,
            'presigned_url': s3_url or f'/media/{s3_key}',
            's3_key': s3_key
        })


def _generate_single_presigned_url(s3_client, bucket_name, s3_key):
    """Helper function to generate a single presigned URL"""
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=3600
        )
        return s3_key, presigned_url
    except Exception as e:
        logger.error(f"Error generating presigned URL for {s3_key}: {str(e)}")
        return s3_key, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_presigned_read_urls_batch(request):
    """Generate presigned URLs for multiple S3 files in parallel - 2025 Best Practice"""
    start_time = time.time()
    s3_urls = request.data.get('s3_urls', [])
    
    if not s3_urls or not isinstance(s3_urls, list):
        return Response({'error': 's3_urls must be a non-empty list'}, status=400)
    
    if len(s3_urls) > 50:  # Rate limiting for performance
        return Response({'error': 'Maximum 50 URLs per batch request'}, status=400)
    
    # Filter out empty/null URLs
    valid_s3_urls = [url for url in s3_urls if url and url.strip()]
    
    if not valid_s3_urls:
        return Response({'presigned_urls': {}}, status=200)
    
    # Only generate presigned URLs in production environment
    if settings.DEFAULT_FILE_STORAGE == 'storages.backends.s3boto3.S3Boto3Storage':
        try:
            # Initialize S3 client using secure method
            s3_client = SecureAWSClient.get_s3_client()
            
            presigned_urls = {}
            s3_keys = []
            
            # Extract S3 keys from URLs
            for s3_url in valid_s3_urls:
                try:
                    parsed = urlparse(s3_url)
                    s3_key = parsed.path.lstrip('/')
                    s3_keys.append((s3_url, s3_key))
                except Exception as e:
                    logger.warning(f"Invalid S3 URL {s3_url}: {str(e)}")
                    presigned_urls[s3_url] = None
            
            # Generate presigned URLs in parallel for optimal performance
            with ThreadPoolExecutor(max_workers=10) as executor:
                # Submit all tasks
                future_to_url = {
                    executor.submit(
                        _generate_single_presigned_url, 
                        s3_client, 
                        settings.AWS_STORAGE_BUCKET_NAME, 
                        s3_key
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
            
            return Response({
                'presigned_urls': presigned_urls,
                'expires_in': 3600,
                'batch_size': len(valid_s3_urls),
                'processing_time_ms': round(processing_time * 1000, 2),
                'success_count': sum(1 for url in presigned_urls.values() if url is not None)
            })
            
        except Exception as e:
            logger.error(f"Error generating batch presigned URLs: {str(e)}")
            return Response({'error': str(e)}, status=500)
    else:
        # In development, return the original URLs
        presigned_urls = {url: url for url in valid_s3_urls}
        return Response({
            'development': True,
            'presigned_urls': presigned_urls,
            'batch_size': len(valid_s3_urls)
        })
