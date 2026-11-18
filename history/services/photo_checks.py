"""Photo checks on one record: the Vision content verdict and GPS presence.

Moved out of `PublicHistorySerializer` (2026-11-17) so the record detail can carry the verdict
to the FARMER (`EventViewSet._with_photo_content_flag`). Until then only the public serializer
computed `photo_content_flag`, and it withholds the field from shoppers, so the "this photo
looks like a stock image" warning in the activity sheet never rendered for anyone.

The logic is unchanged from the serializer method it came from.
"""


def analyze_event_photos(event):
    """
    Single-pass analysis of all photos on an event.
    Returns a dict with GPS, content flags, and image count.
    Avoids N+1 queries by iterating images only once (uses prefetch_related from view).
    """
    result = {
        "has_gps_data": False,
        "all_flagged": True,  # Assume flagged until we find a clean photo
        "content_flag": None,  # Worst flag found (for farmer warning)
        "image_count": 0,
    }
    flagged_values = ("not_agricultural", "ai_generated", "stock_photo")

    if not hasattr(event, "album") or not event.album:
        return result

    try:
        for image in event.album.images.all():
            result["image_count"] += 1
            ed = getattr(image, "extra_data", None)
            is_dict = isinstance(ed, dict) if ed else False

            # GPS check
            if is_dict and (ed.get("gps_latitude") or ed.get("latitude")):
                result["has_gps_data"] = True

            # Content validation check
            if is_dict:
                flag = ed.get("content_validation", "")
                if flag in flagged_values:
                    # Track worst flag for farmer warning
                    if result["content_flag"] is None:
                        result["content_flag"] = flag
                else:
                    # At least one photo is NOT flagged
                    result["all_flagged"] = False
            else:
                # No extra_data = assume legitimate (demo data, legacy uploads)
                result["all_flagged"] = False
    except Exception:
        result["all_flagged"] = False

    # If no images were found, nothing is flagged
    if result["image_count"] == 0:
        result["all_flagged"] = False

    return result
