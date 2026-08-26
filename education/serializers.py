from rest_framework import serializers

from .models import FarmerQuestionAnswer


class FarmerQuestionAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmerQuestionAnswer
        fields = ["id", "question", "answer", "category", "is_featured", "view_count", "helpful_votes"]
