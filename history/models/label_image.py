"""Container labels of a production."""

from django.db import models


class LabelImage(models.Model):
    """
    A container-label artifact (retail / nonretail / unpackaged) for a production,
    surfaced in the audit export's Container Labeling block (CCOF G7.0 / ORGB34 /
    7 CFR 205.307). Reuses common.GalleryImage for the actual image (S3 +
    thumbnails + external-URL support); this model only adds labeling metadata.
    """

    LABEL_TYPE_CHOICES = [
        ("nonretail", "Nonretail container (shipping/storage)"),
        ("retail", "Retail package"),
        ("unpackaged", "Unpackaged / PLU tag"),
    ]
    CONTAINER_TYPE_CHOICES = [
        ("box", "Box"),
        ("bin", "Bin"),
        ("tote", "Tote"),
        ("bag", "Bag"),
        ("tag", "Tag / PLU"),
    ]

    history = models.ForeignKey("history.Production", on_delete=models.CASCADE, related_name="label_images")
    label_type = models.CharField(max_length=20, choices=LABEL_TYPE_CHOICES, default="nonretail")
    container_type = models.CharField(max_length=20, choices=CONTAINER_TYPE_CHOICES, blank=True, null=True)
    gallery_image = models.ForeignKey(
        "common.GalleryImage",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="label_uses",
        help_text="The actual label image (reuses Gallery S3 + thumbnail infra).",
    )
    lot_link_note = models.TextField(
        blank=True,
        null=True,
        help_text="How this label links the container to the lot / traceback ID (SOE 205.307).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label_type", "created_at"]

    def __str__(self):
        return f"{self.get_label_type_display()} label for production {self.history_id}"
