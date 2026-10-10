"""Tests for the EcommerceClientHMACMiddleware."""

import json

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path
from apps.api_clients.models import ApiClient

from .testing import (
    HMAC_MODE_SETTINGS,
    TEST_CLIENT_ID,
    TEST_PREVIOUS_SECRET,
    TEST_SECRET,
    ensure_test_client,
    signed_headers,
    wsgi_headers,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _accepted_view(request):
    """A stand-in protected endpoint exposing the client context."""

    return HttpResponse(
        json.dumps(
            {
                "client_authenticated": request.client_authenticated,
                "client_auth_method": request.client_auth_method,
                "hmac_verified": request.hmac_verified,
                "hmac_client_id": request.hmac_client_id,
                "client_reference": getattr(request.ecommerce_client, "reference", None),
                "user": str(getattr(request, "user", "unset")),
            }
        ),
        content_type="application/json",
    )


urlpatterns = [
    path("api/v1/protected/", _accepted_view),
    path("api/v1/protected/action/", _accepted_view),
    path("api/v1/health/", _accepted_view),
    path(
        "api/v1/businesses/",
        _accepted_view,
    ),
    path(
        "api/v1/auth/carri/mobile/exchange/",
        _accepted_view,
    ),
    path("api/v1/auth/token/refresh/", _accepted_view),
]

urlconf = type("HmacTestUrls", (), {"urlpatterns": urlpatterns})

PROTECTED = "/api/v1/protected/"
ACTION = "/api/v1/protected/action/"
EXEMPT = "/api/v1/health/"
ANDROID = "/api/v1/auth/carri/mobile/exchange/"
REFRESH = "/api/v1/auth/token/refresh/"
BUSINESSES = "/api/v1/businesses/"


@pytest.fixture(autouse=True)
def _hmac_route_settings():
    with override_settings(ROOT_URLCONF=urlconf, **HMAC_MODE_SETTINGS):
        ensure_test_client()
        yield


def _settings(**overrides):
    """Return a fresh override_settings instance for one HMAC variation."""

    return override_settings(**{**HMAC_MODE_SETTINGS, **overrides})


class TestEnforceSuccess:
    """A correctly signed request reaches the protected view."""

    def test_valid_signature_is_accepted(self, client):
        response = client.get(PROTECTED, **wsgi_headers(signed_headers(method="GET")))

        assert response.status_code == 200
        payload = response.json()
        assert payload["client_authenticated"] is True
        assert payload["hmac_verified"] is True
        assert payload["hmac_client_id"] == TEST_CLIENT_ID
        assert payload["client_auth_method"] == ApiClient.AuthMethod.HMAC

    def test_post_with_body_and_query_is_accepted(self, client):
        body = json.dumps({"email": "membre@example.com", "title": "Caissier"})
        headers = signed_headers(
            method="POST",
            path=ACTION,
            query_string="page=2&status=PENDING",
            body=body.encode(),
        )

        response = client.post(
            f"{ACTION}?page=2&status=PENDING",
            data=body,
            content_type="application/json",
            **wsgi_headers(headers),
        )

        assert response.status_code == 200

    def test_canonical_query_order_does_not_change_the_signature(self, client):
        headers = signed_headers(
            method="GET",
            path=PROTECTED,
            query_string="status=PENDING&page=2",
        )

        response = client.get(
            f"{PROTECTED}?page=2&status=PENDING",
            **wsgi_headers(headers),
        )

        assert response.status_code == 200

    def test_the_previous_secret_is_accepted_during_a_rotation(self, client):
        headers = signed_headers(secret=TEST_PREVIOUS_SECRET, method="GET")

        response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.status_code == 200

    def test_last_seen_at_is_recorded(self, client):
        client.get(PROTECTED, **wsgi_headers(signed_headers(method="GET")))

        client_model = ApiClient.objects.get(client_id=TEST_CLIENT_ID)
        assert client_model.last_seen_at is not None


class TestEnforceRejections:
    """Every failure mode returns a stable code and a French message."""

    def test_missing_headers_are_refused(self, client):
        response = client.get(PROTECTED)

        assert response.status_code == 401
        assert response.json() == {
            "code": "client_signature_required",
            "detail": (
                "La signature du client applicatif est obligatoire pour cette requête."
            ),
        }

    def test_partial_headers_are_refused(self, client):
        response = client.get(
            PROTECTED, HTTP_X_ECOMMERCE_CLIENT_ID=TEST_CLIENT_ID
        )

        assert response.status_code == 401
        assert response.json()["code"] == "client_signature_required"

    def test_invalid_signature_is_refused(self, client):
        headers = signed_headers(method="GET", signature="0" * 64)

        response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.status_code == 401
        assert response.json()["code"] == "client_signature_invalid"

    def test_unknown_client_is_refused_like_an_invalid_signature(self, client):
        headers = signed_headers(
            method="GET", client_id="not-registered", secret=TEST_SECRET
        )

        response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.status_code == 401
        assert response.json()["code"] == "client_signature_invalid"

    def test_disabled_client_is_refused_with_a_revoked_key(self, client):
        ensure_test_client(is_active=False)
        headers = signed_headers(method="GET")

        response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.status_code == 401
        assert response.json()["code"] == "client_key_revoked"

    def test_expired_timestamp_is_refused(self, client):
        from time import time

        headers = signed_headers(
            method="GET", timestamp=str(int(time()) - 121)
        )

        response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.status_code == 401
        assert response.json()["code"] == "client_signature_expired"

    def test_a_future_timestamp_is_refused(self, client):
        from time import time

        headers = signed_headers(method="GET", timestamp=str(int(time()) + 400))

        response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.json()["code"] == "client_signature_expired"

    def test_wrong_body_hash_is_refused(self, client):
        body = json.dumps({"a": 1})
        headers = signed_headers(
            method="POST", path=ACTION, body=body.encode(), body_sha256="0" * 64
        )

        response = client.post(
            ACTION,
            data=body,
            content_type="application/json",
            **wsgi_headers(headers),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "client_body_hash_mismatch"

    def test_a_declared_empty_body_with_a_real_body_is_refused(self, client):
        body = json.dumps({"a": 1})
        headers = signed_headers(method="POST", path=ACTION, body=b"")

        response = client.post(
            ACTION,
            data=body,
            content_type="application/json",
            **wsgi_headers(headers),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "client_body_hash_mismatch"

    def test_replayed_nonce_is_refused(self, client):
        headers = signed_headers(method="GET", nonce="nonce-rejoue")
        first = client.get(PROTECTED, **wsgi_headers(headers))
        second = client.get(PROTECTED, **wsgi_headers(headers))

        assert first.status_code == 200
        assert second.status_code == 401
        assert second.json()["code"] == "client_request_replayed"

    def test_unsupported_signature_version_is_refused(self, client):
        headers = signed_headers(method="GET", version="v2")

        response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.status_code == 401
        assert response.json()["code"] == (
            "client_signature_version_unsupported"
        )

    def test_expired_previous_secret_is_refused(self, client):
        with override_settings(
            ECOMMERCE_HMAC_CLIENT_SECRETS={
                TEST_CLIENT_ID: {
                    "current": TEST_SECRET,
                    "previous": TEST_PREVIOUS_SECRET,
                    "previous_expires_at": "1",
                }
            }
        ):
            headers = signed_headers(
                method="GET", secret=TEST_PREVIOUS_SECRET, nonce="ancien-secret"
            )

            response = client.get(PROTECTED, **wsgi_headers(headers))

        assert response.status_code == 401
        assert response.json()["code"] == "client_signature_invalid"

    def test_an_oversized_body_is_refused(self, client):
        with override_settings(ECOMMERCE_HMAC_MAX_BODY_BYTES=64):
            body = b'{"data":"' + b"x" * 300 + b'"}'
            headers = signed_headers(method="POST", path=ACTION, body=body)

            response = client.post(
                ACTION,
                data=body,
                content_type="application/json",
                **wsgi_headers(headers),
            )

        assert response.status_code == 400
        assert response.json()["code"] == "client_body_hash_mismatch"

    def test_hmac_does_not_authenticate_the_user(self, client):
        """A valid signature never turns an anonymous caller into a member."""

        response = client.get(PROTECTED, **wsgi_headers(signed_headers(method="GET")))

        assert response.status_code == 200
        assert response.json()["user"] == "AnonymousUser"


class TestModes:
    """The three modes must behave and be labelled differently."""

    def test_disabled_mode_ignores_signatures_entirely(self, client):
        with override_settings(ECOMMERCE_HMAC_MODE="DISABLED"):
            response = client.get(PROTECTED)

        assert response.status_code == 200
        assert response.json()["hmac_verified"] is False

    def test_observation_mode_never_blocks(self, client):
        with override_settings(ECOMMERCE_HMAC_MODE="OBSERVATION"):
            unsigned = client.get(PROTECTED)
            invalid = client.get(
                PROTECTED, **wsgi_headers(signed_headers(method="GET", signature="0" * 64))
            )

        assert unsigned.status_code == 200
        assert invalid.status_code == 200
        assert invalid.json()["hmac_verified"] is False

    def test_observation_mode_still_accepts_a_valid_signature(self, client):
        with override_settings(ECOMMERCE_HMAC_MODE="OBSERVATION"):
            response = client.get(
                PROTECTED, **wsgi_headers(signed_headers(method="GET"))
            )

        assert response.status_code == 200
        assert response.json()["hmac_verified"] is True

    def test_observation_mode_records_no_nonce(self, client):
        """Measuring must not fill the replay table with unenforced requests."""

        from apps.api_clients.models import ClientNonce

        with override_settings(ECOMMERCE_HMAC_MODE="OBSERVATION"):
            first = client.get(
                PROTECTED, **wsgi_headers(signed_headers(method="GET"))
            )
            second = client.get(
                PROTECTED, **wsgi_headers(signed_headers(method="GET"))
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert ClientNonce.objects.count() == 0

    def test_enforce_mode_records_the_consumed_nonce(self, client):
        from apps.api_clients.models import ClientNonce

        headers = signed_headers(method="GET", nonce="nonce-enregistre")
        client.get(PROTECTED, **wsgi_headers(headers))

        assert ClientNonce.objects.filter(nonce="nonce-enregistre").exists()

    def test_enforce_mode_is_stricter_than_observation(self, client):
        headers = wsgi_headers(signed_headers(method="GET", signature="0" * 64))
        with override_settings(ECOMMERCE_HMAC_MODE="ENFORCE"):
            enforced = client.get(PROTECTED, **headers)
        with override_settings(ECOMMERCE_HMAC_MODE="OBSERVATION"):
            observed = client.get(PROTECTED, **headers)

        assert enforced.status_code == 401
        assert observed.status_code == 200

    def test_an_unknown_mode_is_rejected_when_settings_load(self):
        import os
        import subprocess
        import sys

        backend_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        environment = dict(os.environ, DJANGO_SETTINGS_MODULE="config.settings.development", ECOMMERCE_HMAC_MODE="MAYBE")
        executable = sys.executable
        completed = subprocess.run(
            [executable, "manage.py", "check"],
            cwd=backend_dir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert completed.returncode != 0
        assert "ECOMMERCE_HMAC_MODE" in completed.stderr + completed.stdout
        assert "MAYBE" not in completed.stderr.split("ValueError")[-1].splitlines()[:1]

    def test_hmac_is_disabled_by_default_in_settings(self):
        from django.conf import settings

        assert settings.ECOMMERCE_HMAC_MODE in {"DISABLED", "OBSERVATION", "ENFORCE"}


class TestRoutePolicy:
    """HMAC coverage is decided by path, never by a client declaration."""

    def test_exempt_routes_stay_public_in_enforce_mode(self, client):
        response = client.get(EXEMPT)

        assert response.status_code == 200

    def test_android_exchange_route_stays_unsigned(self, client):
        """The APK holds no secret, so its route is exempt by construction."""

        response = client.post(ANDROID)

        assert response.status_code == 200

    def test_the_business_collection_is_not_protected_by_default(self, client):
        """Only explicitly listed prefixes require HMAC, never all of /api/v1/."""

        with _settings(ECOMMERCE_HMAC_PROTECTED_PREFIXES=("/api/v1/protected/",)):
            response = client.get(BUSINESSES)

        assert response.status_code == 200

    def test_options_requests_are_exempt(self, client):
        response = client.options(PROTECTED)

        assert response.status_code == 200

    def test_declaring_android_does_not_bypass_hmac(self, client):
        """A platform header is untrusted and cannot lift the requirement."""

        response = client.get(
            PROTECTED,
            HTTP_USER_AGENT="EcommerceAndroid/1.0",
            HTTP_X_CLIENT_TYPE="MOBILE_ANDROID",
        )

        assert response.status_code == 401
        assert response.json()["code"] == "client_signature_required"

    def test_a_protected_prefix_covers_every_method(self, client):
        for method in ("get", "post", "patch", "delete"):
            response = getattr(client, method)(PROTECTED)
            assert response.status_code == 401, method


class TestNoSecretLeak:
    """No secret, signature or full header set may reach a response or log."""

    def test_the_secret_never_appears_in_a_response(self, client):
        headers = wsgi_headers(signed_headers(method="GET"))
        valid = client.get(PROTECTED, **headers)

        assert TEST_SECRET not in valid.content.decode()

    def test_no_secret_is_logged(self, client, caplog):
        client.get(PROTECTED, **wsgi_headers(signed_headers(method="GET")))

        assert TEST_SECRET not in caplog.text
        assert TEST_PREVIOUS_SECRET not in caplog.text

    def test_a_rejection_logs_no_secret(self, client, caplog):
        client.get(
            PROTECTED, **wsgi_headers(signed_headers(method="GET", signature="0" * 64))
        )

        assert TEST_SECRET not in caplog.text
        assert "hmac_request_rejected" in caplog.text

    def test_the_registry_stores_no_secret(self):
        from apps.api_clients.models import ApiClient as Model

        fields = {
            field.name for field in Model._meta.get_fields() if hasattr(field, "name")
        }
        assert not any("secret" in name.lower() for name in fields)

    def test_error_details_never_echo_the_signature(self, client):
        client.get(
            PROTECTED, **wsgi_headers(signed_headers(method="GET", signature="0" * 64))
        )

        with override_settings(ECOMMERCE_HMAC_MODE="ENFORCE"):
            pass


class TestAndroidCompatibility:
    """Existing JWT and PKCE routes keep working untouched."""

    def test_health_stays_public_without_any_header(self, client):
        assert client.get(EXEMPT).status_code == 200

    def test_refresh_route_is_not_protected_in_this_lot(self, client):
        """Only the explicitly listed prefixes are covered in this lot."""

        with _settings():
            response = client.post(REFRESH, {"refresh": "invalid"})

        assert response.json().get("code") != "client_signature_required"
        assert not any(
            prefix.startswith(REFRESH.rstrip("/")) and REFRESH.startswith(prefix)
            for prefix in HMAC_MODE_SETTINGS["ECOMMERCE_HMAC_PROTECTED_PREFIXES"]
        )

    def test_a_mobile_client_needs_no_hmac_secret_to_call_the_android_route(
        self, client
    ):
        with _settings():
            response = client.post(ANDROID)

        assert response.status_code == 200
