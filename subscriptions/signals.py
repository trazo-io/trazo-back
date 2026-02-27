from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


@receiver(post_save, sender="product.Product")
def track_production_creation(sender, instance, created, **kwargs):
    if created:
        try:
            # Check if this product has a parcel relationship
            if hasattr(instance, "parcel") and instance.parcel:
                # Follow the relationship to get to the company
                company = instance.parcel.establishment.company

                if hasattr(company, "subscription"):
                    # Only count productions created this year
                    start_of_year = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                    # Check if the product has a created_at field
                    if hasattr(instance, "created_at") and instance.created_at >= start_of_year:
                        company.subscription.used_productions += 1
                        company.subscription.save(update_fields=["used_productions"])
        except Exception as e:
            # Log error but don't fail the save
            print(f"Error tracking production creation: {str(e)}")


@receiver(post_save, sender="common.GalleryImage")
def track_storage_usage(sender, instance, created, **kwargs):
    """Track storage usage when a GalleryImage is created.

    Handles both local files (reads .size) and S3/URL images (uses 2MB estimate).
    """
    if not created:
        return

    try:
        ESTIMATED_IMAGE_SIZE = 2 * 1024 * 1024  # 2 MB for S3/URL images
        file_size_bytes = 0

        # Determine file size based on storage type
        if hasattr(instance, "image") and instance.image and instance.image.name:
            try:
                file_size_bytes = instance.image.size
            except Exception:
                file_size_bytes = ESTIMATED_IMAGE_SIZE
        elif instance.s3_key or instance.image_url:
            file_size_bytes = ESTIMATED_IMAGE_SIZE
        else:
            return  # No file data at all

        if file_size_bytes <= 0:
            return

        # Find the company through gallery relationships
        company = None
        if hasattr(instance, "gallery") and instance.gallery:
            gallery = instance.gallery

            # Check establishment albums
            establishments = gallery.establishment_set.all()
            if establishments.exists():
                company = establishments.first().company

            # Check parcel albums
            if not company:
                from product.models import Parcel

                parcels = Parcel.objects.filter(album=gallery)
                if parcels.exists():
                    company = parcels.first().establishment.company

            # Check history albums
            if not company:
                from history.models import History

                histories = History.objects.filter(album=gallery)
                if histories.exists():
                    company = histories.first().parcel.establishment.company

        if company and hasattr(company, "subscription"):
            file_size_gb = file_size_bytes / (1024 * 1024 * 1024)
            company.subscription.used_storage_gb += file_size_gb
            company.subscription.save(update_fields=["used_storage_gb"])

    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error("Error tracking storage usage: %s", str(e))
