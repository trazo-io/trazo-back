from django.urls import include, path, re_path

from rest_framework_nested import routers

from certifications.views import (
    AdjoiningLandAffidavitViewSet,
    BrandOwnerViewSet,
    CertificationViewSet,
    CertifierAccessLinkViewSet,
    LandownerAffidavitViewSet,
    OrganicSystemPlanViewSet,
    OSPAnnualUpdateViewSet,
    PostHarvestFacilityViewSet,
    StateOrganicRegistrationViewSet,
    SupplierViewSet,
)
from documents.views import GeneratedDocumentViewSet
from history.views import EventViewSet, HistoryScanViewSet, HistoryViewSet, RecordsExportViewSet
from product.views import ParcelViewSet, ProductsViewSet
from reviews.views import ReviewsViewSet

from .views import CompanyViewSet, EstablishmentViewSet

router = routers.DefaultRouter()

router.register(r"companies", CompanyViewSet, basename="companies")

# `companies/public/establishments/` DELETED 2026-08-12 — anonymous, no permission classes,
# and it published street address, coordinates, ZIP, contact details and unqualified
# certification claims. Zero callers. See the note in company/views.py.

# Company routes
company_router = routers.NestedDefaultRouter(router, r"companies", lookup="company")
company_router.register(r"establishments", EstablishmentViewSet, basename="company-establishments")


# Establishment routes
establishment_router = routers.NestedDefaultRouter(company_router, r"establishments", lookup="establishment")

establishment_router.register(r"certifications", CertificationViewSet, basename="establishment-certifications")
establishment_router.register(r"osps", OrganicSystemPlanViewSet, basename="establishment-osps")
establishment_router.register(
    r"osp-annual-updates", OSPAnnualUpdateViewSet, basename="establishment-osp-annual-updates"
)
establishment_router.register(r"affidavits", LandownerAffidavitViewSet, basename="establishment-affidavits")
# USDA form #25 — neighbour-signed adjoining-land attestation. Separate route from
# "affidavits" because it is a different document with a different signer.
establishment_router.register(r"adjoining-land", AdjoiningLandAffidavitViewSet, basename="establishment-adjoining-land")
establishment_router.register(
    r"state-organic-registrations",
    StateOrganicRegistrationViewSet,
    basename="establishment-state-organic-registrations",
)
# CCOF G6.1 / 7 CFR 205.272 — the off-farm huller / dryer / cold store / packer a lot is
# sent to, and its organic certificate. Registered 2026-08-16; the model, serializer and
# audit-export block predate this route by months.
establishment_router.register(
    r"post-harvest-facilities",
    PostHarvestFacilityViewSet,
    basename="establishment-post-harvest-facilities",
)
# Seed and planting-stock suppliers and their organic certificates (CCOF G3.0, OTCO C3, WSDA
# 2121-B; 205.201(a)(3) supplier verification).
establishment_router.register(
    r"suppliers",
    SupplierViewSet,
    basename="establishment-suppliers",
)
# Companies whose brands the farm packs into (CCOF G7.0 C, OTCO C8 8.3, WSDA 2121 N 6-7).
establishment_router.register(
    r"brand-owners",
    BrandOwnerViewSet,
    basename="establishment-brand-owners",
)
establishment_router.register(
    r"certifier-links",
    CertifierAccessLinkViewSet,
    basename="establishment-certifier-links",
)
establishment_router.register(r"documents", GeneratedDocumentViewSet, basename="establishment-documents")
establishment_router.register(r"records-export", RecordsExportViewSet, basename="establishment-records-export")
establishment_router.register(r"scans", HistoryScanViewSet, basename="establishment-scans")
establishment_router.register(r"events", EventViewSet, basename="establishment-events")
establishment_router.register(r"parcels", ParcelViewSet, basename="establishment-parcels")
establishment_router.register(r"products", ProductsViewSet, basename="establishment-products")

# Parcels routes
parcel_router = routers.NestedDefaultRouter(establishment_router, r"parcels", lookup="parcel")

parcel_router.register(
    r"histories",
    HistoryViewSet,
    basename="parcel-histories",
)

# History routes
history_router = routers.NestedDefaultRouter(parcel_router, r"histories", lookup="history")
history_router.register(r"reviews", ReviewsViewSet, basename="history-reviews")


urlpatterns = [
    re_path(r"^", include(router.urls)),
    re_path(r"^", include(company_router.urls)),
    re_path(r"^", include(establishment_router.urls)),
    re_path(r"^", include(parcel_router.urls)),
    re_path(r"^", include(history_router.urls)),
    path("", include("history.urls")),
]
