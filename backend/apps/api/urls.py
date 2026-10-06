"""Versioned API routes."""
from django.urls import include

from django.urls import path

from .views import HealthCheckView
from apps.businesses.views import BusinessCategoriesView

urlpatterns = [
    path("businesses/<str:business_public_id>/", include("apps.expenses.urls")),
    path("businesses/<str:business_public_id>/", include("apps.receivables.urls")),
    path("businesses/<str:business_public_id>/", include("apps.sales.urls")),
    path("businesses/<str:business_public_id>/", include("apps.purchases.urls")),
    path("businesses/<str:business_public_id>/inventory/", include("apps.inventory.urls")),
    path("businesses/<str:business_public_id>/products/", include("apps.catalog.product_urls")),
    path("businesses/", include("apps.businesses.urls")),
    path("business-categories/", BusinessCategoriesView.as_view()),
    path("product-categories/", include("apps.catalog.urls")),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("auth/", include("apps.accounts.urls")),
]
