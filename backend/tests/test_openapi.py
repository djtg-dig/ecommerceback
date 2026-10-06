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
        "/api/v1/businesses/{business_public_id}/suppliers/",
        "/api/v1/businesses/{business_public_id}/purchases/",
        "/api/v1/businesses/{business_public_id}/receivables/",
        "/api/v1/businesses/{business_public_id}/receivables/{receivable_public_id}/payments/",
        "/api/v1/businesses/{business_public_id}/inventory/{inventory_public_id}/movements/",
    ):
        assert path in schema["paths"]
    assert schema["paths"]["/api/v1/auth/me/"]["get"]["security"] == [{"EcommerceJWT": []}]
    assert "parameters" not in schema["paths"]["/api/v1/auth/carri/callback/"]["get"]
    assert schema["paths"]["/api/v1/product-categories/"]["get"].get("security") is None


def test_schema_documents_all_expense_routes_and_filters(client):
    """Expenses routes keep their published methods and query contract."""
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)

    collection = "/api/v1/businesses/{business_public_id}/expenses/"
    detail = "/api/v1/businesses/{business_public_id}/expenses/{expense_public_id}/"
    cancel = detail + "cancel/"
    category_collection = "/api/v1/businesses/{business_public_id}/expense-categories/"
    category_detail = category_collection + "{category_public_id}/"

    assert set(schema["paths"][category_collection]) >= {"get", "post"}
    assert set(schema["paths"][category_detail]) >= {"get", "patch"}
    assert set(schema["paths"][collection]) >= {"get", "post"}
    assert set(schema["paths"][detail]) >= {"get", "patch"}
    assert set(schema["paths"][cancel]) >= {"post"}

    parameters = {
        parameter["name"]
        for parameter in schema["paths"][collection]["get"]["parameters"]
    }
    assert {
        "category",
        "status",
        "payment_method",
        "currency",
        "date_from",
        "date_to",
    } <= parameters

    cancel_schema = schema["paths"][cancel]["post"]["requestBody"]["content"]
    assert "application/json" in cancel_schema


def test_schema_documents_finance_as_get_only_with_its_filters(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    collection = "/api/v1/businesses/{business_public_id}/financial-movements/"
    detail = collection + "{movement_public_id}/"
    summary = "/api/v1/businesses/{business_public_id}/financial-summary/"

    assert set(schema["paths"][collection]) >= {"get"}
    assert "post" not in schema["paths"][collection]
    assert set(schema["paths"][detail]) >= {"get"}
    assert "patch" not in schema["paths"][detail]
    assert set(schema["paths"][summary]) >= {"get"}
    parameters = {parameter["name"] for parameter in schema["paths"][collection]["get"]["parameters"]}
    assert {"direction", "event_type", "payment_method", "date_from", "date_to"} <= parameters


def test_schema_documents_explicit_sale_collection_and_receivable_idempotency(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    complete = "/api/v1/businesses/{business_public_id}/sales/{sale_public_id}/complete/"
    payments = "/api/v1/businesses/{business_public_id}/receivables/{receivable_public_id}/payments/"
    complete_schema = schema["paths"][complete]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert "SaleComplete" in complete_schema.get("$ref", "")
    parameter_names = {entry["name"] for entry in schema["paths"][payments]["post"]["parameters"]}
    assert "Idempotency-Key" in parameter_names


def test_schema_documents_expense_payment_and_reversal_routes(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    payments = "/api/v1/businesses/{business_public_id}/expenses/{expense_public_id}/payments/"
    reversal = payments + "{payment_public_id}/reverse/"
    assert set(schema["paths"][payments]) >= {"get", "post"}
    assert "post" in schema["paths"][reversal]
    names = {parameter["name"] for parameter in schema["paths"][payments]["post"]["parameters"]}
    assert "Idempotency-Key" in names


def test_schema_documents_supplier_payment_routes(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    payments = "/api/v1/businesses/{business_public_id}/purchases/{purchase_public_id}/payments/"
    reversal = payments + "{payment_public_id}/reverse/"
    assert set(schema["paths"][payments]) >= {"get", "post"}
    assert "post" in schema["paths"][reversal]
