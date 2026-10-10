"""Shared helpers for the ecommerce HMAC test suite.

No secret is ever a real one: these constants exist only in the test process and
are supplied through ``override_settings``.
"""

import uuid

from django.test import override_settings

from apps.api_clients.models import ApiClient
from apps.api_clients.services.hmac import (
    EcommerceHMACHeaders,
    build_canonical_request,
    compute_body_sha256,
    compute_hmac_signature,
    sign_request,
)

TEST_CLIENT_ID = "ecommerce-web-test"
PROVISIONED_CLIENT_ID = "ecommerce-web"
TEST_SECRET = "test-only-hmac-secret"
TEST_PREVIOUS_SECRET = "previous-test-only-hmac-secret"
UNKNOWN_CLIENT_ID = "unknown-client-test"

TEST_SECRETS = {
    TEST_CLIENT_ID: {
        "current": TEST_SECRET,
        "previous": TEST_PREVIOUS_SECRET,
        "previous_expires_at": "9999999999",
    }
}

HMAC_MODE_SETTINGS = {
    "ECOMMERCE_HMAC_MODE": "ENFORCE",
    "ECOMMERCE_HMAC_PROTECTED_PREFIXES": ("/api/v1/protected/",),
    "ECOMMERCE_HMAC_EXEMPT_METHODS": ("OPTIONS",),
    "ECOMMERCE_HMAC_MAX_CLOCK_SKEW_SECONDS": 120,
    "ECOMMERCE_HMAC_NONCE_TTL_SECONDS": 900,
    "ECOMMERCE_HMAC_MAX_BODY_BYTES": 1_000_000,
    "ECOMMERCE_HMAC_CLIENT_SECRETS": TEST_SECRETS,
}

hmac_settings = override_settings(**HMAC_MODE_SETTINGS)


def ensure_test_client(**defaults):
    """Create the registry entry used by the HMAC tests."""

    attributes = {
        "name": "Ecommerce Web Test",
        "client_type": ApiClient.ClientType.WEB,
        "auth_method": ApiClient.AuthMethod.HMAC,
        "is_active": True,
    }
    attributes.update(defaults)
    client, _created = ApiClient.objects.update_or_create(
        client_id=TEST_CLIENT_ID,
        defaults=attributes,
    )
    return client


def new_timestamp(import_time=None):
    """Return a fresh valid Unix timestamp."""

    import time

    return str(int(import_time if import_time is not None else time.time()))


def new_nonce():
    """Return a fresh random nonce, unique per signed request."""

    return str(uuid.uuid4())


def signed_headers(
    *,
    method="GET",
    path="/api/v1/protected/",
    query_string="",
    body=b"",
    client_id=TEST_CLIENT_ID,
    secret=TEST_SECRET,
    timestamp=None,
    nonce=None,
    version="v1",
    signature=None,
    body_sha256=None,
):
    """Build the six signed headers for one logical request."""

    timestamp = timestamp if timestamp is not None else new_timestamp()
    nonce = nonce if nonce is not None else new_nonce()
    if body_sha256 is None:
        body_sha256 = compute_body_sha256(body)

    canonical_request = build_canonical_request(
        client_id=client_id,
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        query_string=query_string,
        body_sha256=body_sha256,
        version=version,
    )
    if signature is None:
        signature = compute_hmac_signature(secret, canonical_request)

    return {
        EcommerceHMACHeaders.CLIENT_ID: client_id,
        EcommerceHMACHeaders.TIMESTAMP: timestamp,
        EcommerceHMACHeaders.NONCE: nonce,
        EcommerceHMACHeaders.BODY_SHA256: body_sha256,
        EcommerceHMACHeaders.VERSION: version,
        EcommerceHMACHeaders.SIGNATURE: signature,
    }


def bff_headers(
    *,
    method,
    path,
    body=b"",
    query_string="",
    secret=TEST_SECRET,
    timestamp=None,
    nonce=None,
    signature=None,
):
    """Build an Ecommerce-HMAC v1 request as the future Next.js BFF does."""

    return signed_headers(
        method=method,
        path=path,
        body=body,
        query_string=query_string,
        client_id=PROVISIONED_CLIENT_ID,
        secret=secret,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
    )


def sign_body(
    *, client_id=TEST_CLIENT_ID, secret=TEST_SECRET, method, path, query_string="", body=b""
):
    """Return ``(signature, body_sha256)`` for one request body."""

    signature, body_sha256 = sign_request(
        secret=secret,
        client_id=client_id,
        timestamp=new_timestamp(),
        nonce=new_nonce(),
        method=method,
        path=path,
        query_string=query_string,
        body=body,
    )
    return signature, body_sha256


def wsgi_headers(headers):
    """Convert header names to the WSGI keys expected by the test client."""

    return {
        "HTTP_" + name.upper().replace("-", "_"): value
        for name, value in headers.items()
    }
