"""Versioned API routes."""
from django.urls import include

from django.urls import path

from .views import HealthCheckView
from apps.businesses.views import BusinessCategoriesView

urlpatterns = [
    path("businesses/", include("apps.businesses.urls")),
    path("business-categories/", BusinessCategoriesView.as_view()),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("auth/", include("apps.accounts.urls")),
]
