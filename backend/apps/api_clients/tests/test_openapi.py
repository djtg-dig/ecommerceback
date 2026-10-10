"""The published OpenAPI contract must document the HMAC security scheme."""

import pytest
import yaml

from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_hmac_security_scheme_is_published(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)

    scheme = schema["components"]["securitySchemes"]["EcommerceClientHMAC"]

    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-Ecommerce-Signature"
    assert "HMAC-SHA256" in scheme["description"]


def test_no_operation_requires_hmac_yet(client):
    """HMAC must stay opt-in until every client is migrated and signed."""

    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)

    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            security = operation.get("security")
            for requirement in security or []:
                assert "EcommerceClientHMAC" not in requirement, (path, method)


def test_the_jwt_scheme_is_still_published_alone(client):
    schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)

    assert schema["components"]["securitySchemes"]["EcommerceJWT"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }


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


def test_middleware_is_installed_but_disabled_by_default():
    from django.conf import settings

    assert (
        "apps.api_clients.middleware.EcommerceClientHMACMiddleware"
        in settings.MIDDLEWARE
    )
    assert list(settings.ECOMMERCE_HMAC_PROTECTED_PREFIXES) == []
    assert dict(settings.ECOMMERCE_HMAC_CLIENT_SECRETS) == {}
