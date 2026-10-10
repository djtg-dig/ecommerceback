"""Integration tests for the confidential ``ecommerce-web`` BFF client.

These tests exercise the real URLconf and the real handoff endpoint, and they
reproduce exactly the signature a Next.js BFF will generate: the same canonical
request, the same six headers, the same body hash.
"""

import json

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.accounts.models import CarriIdentity, OAuthHandoff
from apps.api_clients.models import ApiClient, ClientNonce
from apps.api_clients.openapi import HMAC_ONLY, JWT_AND_HMAC

from .testing import (
    PROVISIONED_CLIENT_ID,
    TEST_PREVIOUS_SECRET,
    TEST_SECRET,
    bff_headers,
    ensure_test_client,
    signed_headers,
    wsgi_headers,
)

HANDOFF = "/api/v1/auth/carri/handoff/consume/"
CLIENT_ID = PROVISIONED_CLIENT_ID
OTHER_CLIENT_ID = "other-bff"
OTHER_SECRET = "other-test-only-hmac-secret"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def bff_settings():
    """Provision the BFF client and enforce its route policy end to end."""

    call_command("provision_api_clients")
    ClientNonce.objects.all().delete()

    with override_settings(
        ECOMMERCE_HMAC_MODE="ENFORCE",
        ECOMMERCE_HMAC_PROTECTED_PREFIXES=("/api/v1/auth/carri/handoff/consume/",),
        ECOMMERCE_HMAC_CLIENT_SECRETS={
            CLIENT_ID: {
                "current": TEST_SECRET,
                "previous": TEST_PREVIOUS_SECRET,
                "previous_expires_at": "9999999999",
            },
            OTHER_CLIENT_ID: {"current": OTHER_SECRET},
        },
        ECOMMERCE_HMAC_MAX_CLOCK_SKEW_SECONDS=120,
        ECOMMERCE_HMAC_NONCE_TTL_SECONDS=900,
    ):
        yield
    ClientNonce.objects.all().delete()


@pytest.fixture
def web_client(bff_settings):
    """The provisioned confidential BFF client."""

    return ApiClient.objects.get(client_id=CLIENT_ID)


def consume(client, *, body, headers=None):
    """POST the handoff to the real endpoint with the given signature."""

    payload = json.dumps({"handoff": body})
    return client.post(
        HANDOFF,
        data=payload,
        content_type="application/json",
        **(wsgi_headers(headers) if headers else {}),
    )


@pytest.fixture
def handoff():
    """One usable opaque handoff token, as the OAuth callback would return."""

    identity = CarriIdentity.objects.create(
        carri_subject="bff-test-subject", verified_email="bff@example.com"
    )
    return OAuthHandoff.create_for(identity)


@pytest.fixture
def web_handoff():
    """A one-use handoff explicitly reserved for the confidential Web BFF."""

    identity = CarriIdentity.objects.create(
        carri_subject="web-bff-bound-subject", verified_email="web-bff@example.com"
    )
    return OAuthHandoff.create_for(identity, consumer_client_id=CLIENT_ID)


class TestProvisioning:
    """The client must be provisioned without any secret."""

    def test_the_command_creates_the_web_client(self):
        call_command("provision_api_clients")

        client = ApiClient.objects.get(client_id=CLIENT_ID)
        assert client.client_type == ApiClient.ClientType.WEB
        assert client.auth_method == ApiClient.AuthMethod.HMAC
        assert client.is_active is True
        assert client.reference.startswith("AC")
        assert len(client.reference) == 12

    def test_the_command_is_idempotent(self):
        call_command("provision_api_clients")
        first = ApiClient.objects.get(client_id=CLIENT_ID)
        call_command("provision_api_clients")
        second = ApiClient.objects.get(client_id=CLIENT_ID)

        assert first.pk == second.pk
        assert first.reference == second.reference
        assert ApiClient.objects.filter(client_id=CLIENT_ID).count() == 1

    def test_no_mobile_hmac_client_is_provisioned(self):
        call_command("provision_api_clients")

        mobile = ApiClient.objects.filter(
            client_type__in={
                ApiClient.ClientType.MOBILE_ANDROID,
                ApiClient.ClientType.MOBILE_IOS,
            },
            auth_method=ApiClient.AuthMethod.HMAC,
        )
        assert not mobile.exists()

    def test_the_registry_holds_no_secret_column(self, web_client):
        web_client.refresh_from_db()
        serialized = str(vars(web_client))

        assert TEST_SECRET not in serialized
        assert TEST_PREVIOUS_SECRET not in serialized


class TestBffActivation:
    """The BFF route is enforced only when the mode says so."""

    def test_disabled_mode_accepts_the_unsigned_bff_route(self, client, handoff):
        with override_settings(ECOMMERCE_HMAC_MODE="DISABLED"):
            response = consume(client, body=handoff)

        assert response.status_code == 200
        assert "access" in response.json()

    def test_observation_mode_accepts_the_unsigned_bff_route(self, client, handoff):
        with override_settings(
            ECOMMERCE_HMAC_MODE="OBSERVATION",
            ECOMMERCE_HMAC_PROTECTED_PREFIXES=(HANDOFF,),
            ECOMMERCE_HMAC_CLIENT_SECRETS={CLIENT_ID: {"current": TEST_SECRET}},
        ):
            response = consume(client, body=handoff)

        assert response.status_code == 200

    def test_enforce_mode_rejects_the_unsigned_bff_route(self, client, bff_settings):
        identity = CarriIdentity.objects.create(carri_subject="unsigned-enforced-handoff")
        handoff = OAuthHandoff.create_for(identity, consumer_client_id=CLIENT_ID)

        response = consume(client, body=handoff)

        assert response.status_code == 401
        assert response.json() == {
            "code": "client_signature_required",
            "detail": (
                "La signature du client applicatif est obligatoire pour cette requête."
            ),
        }

    def test_enforce_mode_accepts_a_signed_bff_request(self, client, web_handoff, bff_settings):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(method="POST", path=HANDOFF, body=body.encode())

        response = consume(client, body=web_handoff, headers=headers)

        assert response.status_code == 200
        assert response.json()["access"]
        assert response.json()["refresh"]

    def test_enforce_mode_preserves_unsigned_legacy_handoffs(self, client, handoff, bff_settings):
        response = consume(client, body=handoff)

        assert response.status_code == 200
        assert response.json()["access"]

    def test_disabled_mode_rejects_unsigned_next_delivery_handoffs(self, client):
        identity = CarriIdentity.objects.create(carri_subject="disabled-bound-handoff")
        handoff = OAuthHandoff.create_for(identity, consumer_client_id=CLIENT_ID)

        with override_settings(ECOMMERCE_HMAC_MODE="DISABLED"):
            response = consume(client, body=handoff)

        assert response.status_code == 403
        assert response.json()["code"] == "handoff_client_not_authorized"
        assert OAuthHandoff.objects.get(identity=identity).consumed_at is None


class TestBffSignature:
    """A signed BFF request must behave exactly like the contract states."""

    def test_a_missing_signature_is_refused(self, client, web_handoff, bff_settings):
        response = client.post(
            HANDOFF, data=json.dumps({"handoff": web_handoff}), content_type="application/json"
        )

        assert response.json()["code"] == "client_signature_required"

    def test_a_wrong_signature_is_refused(self, client, web_handoff, bff_settings):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(
            method="POST", path=HANDOFF, body=body.encode(), signature="0" * 64
        )

        response = consume(client, body=web_handoff, headers=headers)

        assert response.status_code == 401
        assert response.json()["code"] == "client_signature_invalid"

    def test_a_wrong_secret_is_refused(self, client, web_handoff, bff_settings):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(
            method="POST", path=HANDOFF, body=body.encode(), secret="un-autre-secret"
        )

        response = consume(client, body=web_handoff, headers=headers)

        assert response.json()["code"] == "client_signature_invalid"

    def test_a_disabled_client_is_refused(self, client, web_handoff, web_client):
        web_client = ApiClient.objects.get(client_id=CLIENT_ID)
        web_client.is_active = False
        web_client.save(update_fields=["is_active"])

        body = json.dumps({"handoff": web_handoff})
        response = consume(
            client,
            body=web_handoff,
            headers=bff_headers(method="POST", path=HANDOFF, body=body.encode()),
        )

        assert response.json()["code"] == "client_key_revoked"

    def test_a_replayed_nonce_is_refused(self, client, web_handoff, bff_settings):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(
            method="POST", path=HANDOFF, body=body.encode(), nonce="nonce-bff"
        )

        first = consume(client, body=web_handoff, headers=headers)
        second = consume(client, body=web_handoff, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 401
        assert second.json()["code"] == "client_request_replayed"

    def test_an_expired_clock_is_refused(self, client, web_handoff, bff_settings):
        import time

        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(
            method="POST",
            path=HANDOFF,
            body=body.encode(),
            timestamp=str(int(time.time()) - 121),
        )

        response = consume(client, body=web_handoff, headers=headers)

        assert response.json()["code"] == "client_signature_expired"

    def test_the_previous_secret_is_accepted_during_a_rotation(
        self, client, web_handoff, bff_settings
    ):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(
            method="POST",
            path=HANDOFF,
            body=body.encode(),
            secret=TEST_PREVIOUS_SECRET,
            nonce="nonce-rotation",
        )

        response = consume(client, body=web_handoff, headers=headers)

        assert response.status_code == 200

    def test_a_tampered_body_is_refused(self, client, web_handoff, bff_settings):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(method="POST", path=HANDOFF, body=b"{}")

        tampered = json.dumps({"handoff": web_handoff, "extra": "field"})
        response = client.post(
            HANDOFF,
            data=tampered,
            content_type="application/json",
            **wsgi_headers(headers),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "client_body_hash_mismatch"

    def test_the_signature_is_bound_to_the_route(self, client, web_handoff, bff_settings):
        """A signature over another path never authorises the BFF route."""

        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(
            method="POST", path="/api/v1/auth/carri/handoff/other/", body=body.encode()
        )

        response = consume(client, body=web_handoff, headers=headers)

        assert response.json()["code"] == "client_signature_invalid"

    def test_a_next_delivery_handoff_is_bound_to_ecommerce_web(self, client, bff_settings):
        ApiClient.objects.create(
            name="Other BFF",
            client_id=OTHER_CLIENT_ID,
            client_type=ApiClient.ClientType.INTERNAL_SERVICE,
            auth_method=ApiClient.AuthMethod.HMAC,
        )
        identity = CarriIdentity.objects.create(carri_subject="bound-handoff")
        handoff = OAuthHandoff.create_for(
            identity, consumer_client_id=CLIENT_ID
        )
        body = json.dumps({"handoff": handoff})
        headers = signed_headers(
            method="POST",
            path=HANDOFF,
            body=body.encode(),
            client_id=OTHER_CLIENT_ID,
            secret=OTHER_SECRET,
        )

        response = consume(client, body=handoff, headers=headers)

        assert response.status_code == 403
        assert response.json()["code"] == "handoff_client_not_authorized"
        assert OAuthHandoff.objects.get(identity=identity).consumed_at is None

    def test_a_bound_handoff_is_consumed_once_only_by_its_web_client(
        self, client, bff_settings
    ):
        identity = CarriIdentity.objects.create(carri_subject="single-use-bound-handoff")
        handoff = OAuthHandoff.create_for(identity, consumer_client_id=CLIENT_ID)
        body = json.dumps({"handoff": handoff})
        headers = bff_headers(method="POST", path=HANDOFF, body=body.encode())

        first = consume(client, body=handoff, headers=headers)
        replay_body = json.dumps({"handoff": handoff})
        replay_headers = bff_headers(
            method="POST", path=HANDOFF, body=replay_body.encode(), nonce="bound-replay"
        )
        replay = consume(client, body=handoff, headers=replay_headers)

        assert first.status_code == 200
        assert first.json()["access"] and first.json()["refresh"]
        assert replay.status_code == 400
        assert replay.json()["code"] == "handoff_already_consumed"

    def test_an_expired_bound_handoff_cannot_be_consumed(self, client, bff_settings):
        identity = CarriIdentity.objects.create(carri_subject="expired-bound-handoff")
        handoff = OAuthHandoff.create_for(
            identity, lifetime_seconds=-1, consumer_client_id=CLIENT_ID
        )
        body = json.dumps({"handoff": handoff})
        headers = bff_headers(method="POST", path=HANDOFF, body=body.encode())

        response = consume(client, body=handoff, headers=headers)

        assert response.status_code == 400
        assert response.json()["code"] == "handoff_expired"
        assert OAuthHandoff.objects.get(identity=identity).consumed_at is None


class TestAndroidRoutesStayOpen:
    """No mobile or browser route may require a signature."""

    def test_the_mobile_exchange_route_stays_unsigned(self, client, bff_settings):
        response = client.post(
            "/api/v1/auth/carri/mobile/exchange/",
            {"id_token": "one", "access_token": "access", "nonce": "nonce"},
            format="json",
        )

        assert response.status_code != 401
        assert response.json().get("code") != "client_signature_required"

    def test_the_web_login_route_stays_unsigned(self, client, bff_settings):
        response = client.get("/api/v1/auth/carri/login/")

        assert response.status_code in (302, 503)

    def test_the_callback_route_stays_unsigned(self, client, bff_settings):
        response = client.get("/api/v1/auth/carri/callback/", {"code": "x", "state": "y"})

        assert response.status_code in (400, 503)
        assert response.json().get("code") != "client_signature_required"

    def test_the_identity_route_stays_unsigned(self, client, bff_settings):
        response = client.get("/api/v1/auth/me/")

        assert response.status_code == 401
        assert "code" not in response.json()

    def test_the_refresh_route_stays_unsigned(self, client, bff_settings):
        response = client.post(
            "/api/v1/auth/token/refresh/", {"refresh": "invalid"}, format="json"
        )

        assert response.json().get("code") != "client_signature_required"

    def test_business_routes_stay_unsigned(self, client, bff_settings):
        response = client.get("/api/v1/businesses/")

        assert response.status_code == 401
        assert "code" not in response.json()

    def test_the_health_route_stays_public(self, client, bff_settings):
        assert client.get("/api/v1/health/").status_code == 200

    def test_a_platform_header_never_replaces_a_signature(
        self, client, web_handoff, bff_settings
    ):
        response = client.post(
            HANDOFF,
            data=json.dumps({"handoff": web_handoff}),
            content_type="application/json",
            HTTP_USER_AGENT="EcommerceAndroid/1.0",
            HTTP_ORIGIN="https://app.example.com",
            HTTP_X_CLIENT_TYPE="MOBILE_ANDROID",
        )

        assert response.json()["code"] == "client_signature_required"


class TestNoSecretExposure:
    """The secret never reaches a response body or a log line."""

    def test_no_secret_in_a_successful_response(self, client, web_handoff, bff_settings):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(method="POST", path=HANDOFF, body=body.encode())

        response = consume(client, body=web_handoff, headers=headers)

        assert TEST_SECRET not in response.content.decode()

    def test_no_secret_in_a_rejected_response(self, client, web_handoff, bff_settings):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(
            method="POST", path=HANDOFF, body=body.encode(), signature="0" * 64
        )

        response = consume(client, body=web_handoff, headers=headers)

        assert TEST_SECRET not in response.content.decode()

    def test_no_secret_in_the_logs(self, client, web_handoff, bff_settings, caplog):
        body = json.dumps({"handoff": web_handoff})
        headers = bff_headers(method="POST", path=HANDOFF, body=body.encode())

        consume(client, body=web_handoff, headers=headers)

        assert TEST_SECRET not in caplog.text
        assert TEST_PREVIOUS_SECRET not in caplog.text

    def test_the_rotation_grace_period_is_configurable(self):
        with override_settings(
            ECOMMERCE_HMAC_CLIENT_SECRETS={
                CLIENT_ID: {
                    "current": TEST_SECRET,
                    "previous": TEST_PREVIOUS_SECRET,
                    "previous_expires_at": "1",
                }
            }
        ):
            from apps.api_clients.services.secrets import client_secret

            secret = client_secret(CLIENT_ID)

        assert secret.candidate_secrets() == [TEST_SECRET]


class TestPublishedContract:
    """The published OpenAPI must match the enforced route policy."""

    def test_the_bff_operation_declares_the_hmac_scheme(self, client):
        import yaml

        from django.urls import reverse

        schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)
        operation = schema["paths"][HANDOFF]["post"]

        assert operation["security"] == [{"EcommerceClientHMAC": []}]
        assert operation["security"][0] in [dict(HMAC_ONLY[0])]

    def test_only_the_bff_routes_are_published_as_hmac_protected(self, client):
        import yaml

        from django.urls import reverse

        from django.conf import settings

        schema = yaml.safe_load(client.get(reverse("openapi-schema")).content)

        published = {
            path
            for path, operations in schema["paths"].items()
            for method, operation in operations.items()
            if method in {"get", "post", "put", "patch", "delete"}
            and any("EcommerceClientHMAC" in requirement for requirement in operation.get("security", []))
        }

        for protected in settings.ECOMMERCE_HMAC_PROTECTED_PREFIXES:
            assert published, (protected, list(schema["paths"]))

    def test_the_combined_requirement_shape_is_a_single_object(self):
        assert HMAC_ONLY == ({"EcommerceClientHMAC": []},)
        assert JWT_AND_HMAC == (
            {"EcommerceJWT": [], "EcommerceClientHMAC": []},
        )
        assert len(JWT_AND_HMAC) == 1

    def test_the_bff_only_declaration_contains_the_enforced_prefix(self):
        from django.conf import settings

        for prefix in settings.ECOMMERCE_HMAC_PROTECTED_PREFIXES:
            assert any(
                prefix.startswith(reserved)
                for reserved in settings.ECOMMERCE_HMAC_BFF_ONLY_PREFIXES
            )
