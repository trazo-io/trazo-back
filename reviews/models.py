from django.db import models

# Create your models here.


class Review(models.Model):
    headline = models.CharField(max_length=100)
    written_review = models.TextField()
    date = models.DateTimeField(auto_now_add=True)
    rating = models.IntegerField()
    user = models.ForeignKey("users.User", related_name="reviews", on_delete=models.CASCADE, null=True, blank=True)
    production = models.ForeignKey("history.Production", related_name="reviews", on_delete=models.CASCADE)
    scan = models.ForeignKey(
        "history.HistoryScan",
        related_name="reviews",
        on_delete=models.CASCADE,
        null=True,
    )
    images = models.JSONField(
        default=list,
        blank=True,
        help_text="List of image URLs uploaded by the reviewer",
    )
