from django.urls import include, path

from rest_framework import routers

from .views import ParcelCropHistoryViewSet, ParcelViewSet, ProductsViewSet

router = routers.DefaultRouter()

router.register(r"parcels", ParcelViewSet, basename="parcels")
router.register(r"products", ProductsViewSet, basename="products")
router.register(r"parcel-crop-history", ParcelCropHistoryViewSet, basename="parcel-crop-history")

urlpatterns = [
    path("", include(router.urls)),
]
