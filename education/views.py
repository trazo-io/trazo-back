"""Education API — the FAQ endpoint only.

The category/course/lesson viewsets were removed 2026-08-24: no frontend
surface ever consumed them (the topic pages are i18n strings bundled with the
app; the only education hook in use is ``useGetFarmerQuestionsQuery``), while
the seeded lesson content still taught the pre-pivot transparency score and
the withdrawn blockchain add-on. The models remain for their migrations, and
``seed_education_content`` purges any previously seeded rows.
"""

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import FarmerQuestionAnswer
from .serializers import FarmerQuestionAnswerSerializer


class FarmerQuestionAnswerViewSet(viewsets.ReadOnlyModelViewSet):
    """View FAQ for farmers"""

    queryset = FarmerQuestionAnswer.objects.all()
    serializer_class = FarmerQuestionAnswerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Return FAQs ordered by helpfulness"""
        return FarmerQuestionAnswer.objects.all().order_by("-is_featured", "-helpful_votes", "-view_count")

    @action(detail=False, methods=["get"])
    def featured(self, request):
        """Get featured FAQs"""
        featured_faqs = self.get_queryset().filter(is_featured=True)[:10]
        serializer = self.get_serializer(featured_faqs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_category(self, request):
        """Get FAQs by category"""
        category = request.query_params.get("category")
        if category:
            faqs = self.get_queryset().filter(category=category)
        else:
            faqs = self.get_queryset()

        serializer = self.get_serializer(faqs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def mark_helpful(self, request, pk=None):
        """Mark FAQ as helpful"""
        faq = self.get_object()
        faq.helpful_votes += 1
        faq.save()

        return Response({"helpful_votes": faq.helpful_votes})

    def retrieve(self, request, *args, **kwargs):
        """Increment view count when FAQ is viewed"""
        faq = self.get_object()
        faq.view_count += 1
        faq.save()

        return super().retrieve(request, *args, **kwargs)
