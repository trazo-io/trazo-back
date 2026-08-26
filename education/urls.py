from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .views import FarmerQuestionAnswerViewSet

router = DefaultRouter()
router.register(r"faqs", FarmerQuestionAnswerViewSet, basename="education-faqs")

urlpatterns = [
    path("", include(router.urls)),
]
