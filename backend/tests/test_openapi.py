"""Regression tests for the developer-facing OpenAPI documentation."""

import yaml
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_openapi_endpoints_are_publicly_available(client):
    """Documentation remains reachable without weakening business endpoints."""
    assert client.get(reverse("openapi-schema")).status_code == 200
    assert client.get(reverse("swagger-ui")).status_code == 200
    assert client.get(reverse("redoc")).status_code == 200


def test_schema_lists_real_routes_and_ecommerce_bearer_security(client):
    """The published contract includes central routes and custom JWT security."""
    response = client.get(reverse("openapi-schema"))
    schema = yaml.safe_load(response.content)

    assert "EcommerceJWT" in schema["components"]["securitySchemes"]
    assert schema["components"]["securitySchemes"]["EcommerceJWT"] == {
        "type": "http", "scheme": "bearer", "bearerFormat": "JWT"
    }
    for path in (
        "/api/v1/health/",
        "/api/v1/auth/carri/mobile/exchange/",
        "/api/v1/auth/me/",
        "/api/v1/auth/token/refresh/",
        "/api/v1/businesses/",
        "/api/v1/businesses/{public_id}/",
        "/api/v1/business-categories/",
        "/api/v1/product-categories/",
        "/api/v1/product-categories/{code}/attributes/",
        "/api/v1/businesses/{business_public_id}/products/",
        "/api/v1/businesses/{business_public_id}/inventory/",
        "/api/v1/businesses/{business_public_id}/inventory/{inventory_public_id}/movements/",
    ):
        assert path in schema["paths"]
    assert schema["paths"]["/api/v1/auth/me/"]["get"]["security"] == [{"EcommerceJWT": []}]
    assert "parameters" not in schema["paths"]["/api/v1/auth/carri/callback/"]["get"]
    assert schema["paths"]["/api/v1/product-categories/"]["get"].get("security") is None
