"""The published OpenAPI contract must document the HMAC security scheme."""

import yaml

from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import reverse

from apps.api_clients.middleware import EcommerceClientHMACMiddleware
from apps.api_clients.openapi import HMAC_ONLY

def test_hmac_security_scheme_is_published(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)

    scheme = schema["components"]["securitySchemes"]["EcommerceClientHMAC"]

    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-Ecommerce-Signature"
    assert "HMAC-SHA256" in scheme["description"]


def test_only_the_reserved_bff_operation_requires_hmac(client):
    """HMAC is published only for the explicit server-to-server operation."""

    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    handoff = "/api/v1/auth/carri/handoff/consume/"
    hmac_operations = set()

    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if any(
                "EcommerceClientHMAC" in requirement
                for requirement in operation.get("security") or []
            ):
                hmac_operations.add((path, method))

    assert hmac_operations == {(handoff, "post")}
    assert schema["paths"][handoff]["post"]["security"] == [dict(HMAC_ONLY[0])]


def test_the_jwt_scheme_is_still_published_alone(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)

    assert schema["components"]["securitySchemes"]["EcommerceJWT"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }


def test_oauth_callback_documents_json_and_html_delivery_responses(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    callback = schema["paths"]["/api/v1/auth/carri/callback/"]["get"]
    content = callback["responses"]["200"]["content"]
    response_schema = content["application/json"]["schema"]
    if "$ref" in response_schema:
        name = response_schema["$ref"].rsplit("/", 1)[-1]
        response_schema = schema["components"]["schemas"][name]

    assert "application/json" in content
    assert "text/html" in content
    assert response_schema["properties"]["handoff"]["type"] == "string"


def test_handoff_errors_document_stable_codes_and_client_binding(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    consume = schema["paths"]["/api/v1/auth/carri/handoff/consume/"]["post"]
    errors = consume["responses"]["403"]["content"]["application/json"]["schema"]
    if "$ref" in errors:
        name = errors["$ref"].rsplit("/", 1)[-1]
        errors = schema["components"]["schemas"][name]

    assert {"code", "detail"} <= set(errors["properties"])


def test_the_combined_requirement_shape_is_valid_openapi(client):
    """JWT and HMAC together must be one requirement object, never two.

    Two separate objects would express an alternative, meaning either one is
    enough, which is not the intended contract.
    """

    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
    schemes = schema["components"]["securitySchemes"]

    combined = {"EcommerceJWT": [], "EcommerceClientHMAC": []}

    assert len(combined) == 2
    assert all(name in schemes for name in combined)

    jwt_operations = []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            requirements = operation.get("security") or []
            has_jwt = any("EcommerceJWT" in requirement for requirement in requirements)
            has_hmac = any(
                "EcommerceClientHMAC" in requirement for requirement in requirements
            )
            if has_jwt:
                jwt_operations.append((path, method))
            if has_jwt and has_hmac:
                assert combined in requirements, (path, method, requirements)

    assert jwt_operations


def test_middleware_policy_defaults_are_independent_from_local_env():
    """The code default remains DISABLED even when the developer uses ENFORCE."""

    import config.settings.base as base_settings

    assert (
        "apps.api_clients.middleware.EcommerceClientHMACMiddleware"
        in settings.MIDDLEWARE
    )
    assert base_settings.DEFAULT_ECOMMERCE_HMAC_MODE == "DISABLED"
    assert base_settings.ECOMMERCE_HMAC_BFF_ONLY_PREFIXES == (
        "/api/v1/auth/carri/handoff/consume/",
    )


def test_enforce_can_be_activated_without_protecting_android_routes():
    factory = RequestFactory()
    middleware = EcommerceClientHMACMiddleware(lambda request: None)

    with override_settings(
        ECOMMERCE_HMAC_MODE="ENFORCE",
        ECOMMERCE_HMAC_PROTECTED_PREFIXES=(
            "/api/v1/auth/carri/handoff/consume/",
        ),
    ):
        assert middleware.requires_hmac(
            factory.post("/api/v1/auth/carri/handoff/consume/")
        )
        assert not middleware.requires_hmac(
            factory.post("/api/v1/auth/carri/mobile/exchange/")
        )
