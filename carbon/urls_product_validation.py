"""
PRODUCT VALIDATION URL CONFIGURATION
URL patterns for agricultural product validation endpoints.
"""

from django.urls import path

from . import views_product_validation

app_name = "product_validation"

urlpatterns = [
    # Product autocomplete suggestions
    path("api/product-suggestions/", views_product_validation.product_suggestions, name="product_suggestions"),
    # Product validation
    path("api/validate-product/", views_product_validation.validate_product, name="validate_product"),
    # Validation statistics
    path("api/validation-stats/", views_product_validation.validation_stats, name="validation_stats"),
    # Product database (admin only)
    path("api/product-database/", views_product_validation.product_database, name="product_database"),
]
