"""Versioned API routes."""
from django.urls import include

from django.urls import path

from .views import HealthCheckView

urlpatterns = [
    path("businesses/", include("apps.businesses.urls")),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("auth/", include("apps.accounts.urls")),
]
