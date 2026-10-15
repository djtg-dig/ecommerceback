import base64
import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.logging import OAuthQueryStringRedactionFilter
from apps.accounts.models import CarriIdentity, OAuthHandoff, OAuthLoginAttempt
from apps.accounts.services import oidc
from apps.accounts.views import _pair


def test_django_logs_redact_carri_oauth_query_strings():
    request_line = '"GET /api/v1/auth/carri/callback/?state=private-state&code=private-code HTTP/1.1"'
    record = logging.LogRecord(
        "django.server",
        logging.INFO,
        __file__,
        1,
        '"%s" %s %s',
        (request_line, 303, 0),
        None,
    )

    assert OAuthQueryStringRedactionFilter().filter(record)
    message = record.getMessage()
    assert "private-state" not in message
    assert "private-code" not in message
    assert "/api/v1/auth/carri/callback/ HTTP/1.1" in message


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_ANDROID_CLIENT_ID="android-client", CARRI_ACCOUNT_ISSUER="https://issuer.example")
def test_mobile_exchange_creates_and_reuses_identity():
    client = APIClient()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "carri-subject",
        "auth_time": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    with patch("apps.accounts.views.validate_id_token", return_value=payload), patch(
        "apps.accounts.views.verified_userinfo",
        return_value="verified@example.com",
    ):
        first = client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "one", "access_token": "access", "nonce": "nonce"}, format="json")
        second = client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "two", "access_token": "access", "nonce": "nonce"}, format="json")
    assert first.status_code == 200
    assert second.status_code == 200
    identity = CarriIdentity.objects.get(carri_subject="carri-subject")
    assert identity.verified_email == "verified@example.com"
    assert identity.email_verified is True
    assert identity.has_fresh_verified_email()


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_ANDROID_CLIENT_ID="android-client")
def test_mobile_exchange_rejects_replay_and_incomplete_payload():
    client = APIClient()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "carri-subject",
        "auth_time": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    with patch("apps.accounts.views.validate_id_token", return_value=payload), patch(
        "apps.accounts.views.verified_userinfo",
        return_value="verified@example.com",
    ):
        assert client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "same", "access_token": "access", "nonce": "nonce"}, format="json").status_code == 200
        assert client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "same", "access_token": "access", "nonce": "nonce"}, format="json").status_code == 400
    assert client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "only"}, format="json").status_code == 400


@pytest.mark.django_db
def test_me_requires_ecommerce_jwt_and_returns_identity():
    identity = CarriIdentity.objects.create(carri_subject="sub-1")
    client = APIClient()
    assert client.get("/api/v1/auth/me/").status_code == 401
    access = _pair(identity)["access"]
    response = client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200
    assert response.json() == {"id": str(identity.id), "carri_subject": "sub-1"}


@pytest.mark.django_db
def test_ecommerce_token_pair_refreshes_and_authenticates_businesses():
    identity = CarriIdentity.objects.create(carri_subject="refreshable-subject")
    client = APIClient()

    issued = _pair(identity)
    refreshed = client.post(
        "/api/v1/auth/token/refresh/", {"refresh": issued["refresh"]}, format="json"
    )

    assert set(issued) == {"access", "refresh"}
    assert refreshed.status_code == 200
    assert set(refreshed.json()) == {"access", "refresh"}
    assert refreshed.json()["refresh"] != issued["refresh"]
    assert client.get(
        "/api/v1/businesses/",
        HTTP_AUTHORIZATION=f"Bearer {refreshed.json()['access']}",
    ).status_code == 200


@pytest.mark.django_db
def test_logout_revokes_existing_access_and_refresh_tokens():
    identity = CarriIdentity.objects.create(carri_subject="logout-subject")
    client = APIClient()
    issued = _pair(identity)

    assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {issued['access']}").status_code == 200
    assert client.post("/api/v1/auth/logout/", HTTP_AUTHORIZATION=f"Bearer {issued['access']}").status_code == 204
    assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {issued['access']}").status_code == 401
    assert client.post("/api/v1/auth/token/refresh/", {"refresh": issued["refresh"]}, format="json").status_code == 401

    identity.refresh_from_db()
    fresh = _pair(identity)
    assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {fresh['access']}").status_code == 200


@pytest.mark.django_db
def test_ecommerce_token_refresh_rejects_invalid_expired_and_unknown_identities():
    client = APIClient()
    expired = RefreshToken()
    expired["identity_id"] = str(uuid.uuid4())
    expired.set_exp(lifetime=timedelta(seconds=-1))
    invalid_identity = RefreshToken()
    invalid_identity["identity_id"] = "not-a-uuid"
    unknown_identity = RefreshToken()
    unknown_identity["identity_id"] = str(uuid.uuid4())

    for refresh in ("not-a-token", str(expired), str(invalid_identity), str(unknown_identity)):
        response = client.post("/api/v1/auth/token/refresh/", {"refresh": refresh}, format="json")
        assert response.status_code == 401


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_CLIENT_ID="web-client", CARRI_ACCOUNT_ISSUER="https://issuer.example")
def test_web_callback_consumes_state_once_and_returns_handoff():
    state = "state-value"
    OAuthLoginAttempt.create(state=state, nonce="nonce", code_verifier="verifier", redirect_uri="https://app.example/callback")
    client = APIClient()
    token_payload = {"id_token": "id", "access_token": "access"}
    id_payload = {
        "sub": "web-sub",
        "auth_time": int(datetime.now(timezone.utc).timestamp()),
    }
    with patch("apps.accounts.views.exchange_web_code", return_value=token_payload), patch(
        "apps.accounts.views.validate_id_token",
        return_value=id_payload,
    ), patch(
        "apps.accounts.views.verified_userinfo",
        return_value="web@example.com",
    ):
        response = client.get("/api/v1/auth/carri/callback/", {"state": state, "code": "code"})
        reused = client.get("/api/v1/auth/carri/callback/", {"state": state, "code": "code"})
    assert response.status_code == 200
    assert "handoff" in response.json()
    assert reused.status_code == 400
    assert CarriIdentity.objects.get(carri_subject="web-sub").verified_email == "web@example.com"


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff",
)
def test_nextjs_access_denied_posts_only_safe_error_and_binding_then_rejects_replay(caplog):
    delivery_binding = "N" * 43
    client = APIClient()
    metadata = {
        "authorization_endpoint": "https://identity.example/oauth/authorize/",
        "scopes_supported": ["openid", "email"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        login = client.get(
            "/api/v1/auth/carri/login/",
            {"delivery": "nextjs", "delivery_binding": delivery_binding},
        )

    authorization_query = parse_qs(urlsplit(login["Location"]).query)
    assert authorization_query["prompt"] == ["login"]
    state = authorization_query["state"][0]
    attempt = OAuthLoginAttempt.objects.get(
        state_hash=hashlib.sha256(state.encode()).hexdigest()
    )
    callback = client.get(
        "/api/v1/auth/carri/callback/",
        {"state": state, "error": "access_denied"},
    )
    body = callback.content.decode()
    names = re.findall(r'<input type="hidden" name="([^"]+)"', body)

    assert callback.status_code == 200
    assert callback["Content-Type"].startswith("text/html")
    assert callback["Cache-Control"] == "no-store, max-age=0"
    assert callback["Referrer-Policy"] == "no-referrer"
    assert callback["X-Frame-Options"] == "DENY"
    assert names == ["error", "delivery_binding"]
    assert 'action="https://web.example/api/auth/carri/handoff" method="post"' in body
    assert 'name="error" value="access_denied"' in body
    assert f'name="delivery_binding" value="{delivery_binding}"' in body
    assert 'name="handoff"' not in body
    assert not CarriIdentity.objects.exists()
    assert not OAuthHandoff.objects.exists()
    assert "sessionid" not in callback.cookies
    assert callback.cookies["ecommerce_oauth_attempt"]["max-age"] == 0
    attempt.refresh_from_db()
    assert attempt.consumed_at is not None
    assert state not in caplog.text
    assert delivery_binding not in caplog.text

    replay = client.get(
        "/api/v1/auth/carri/callback/",
        {"state": state, "error": "access_denied"},
    )
    assert replay.status_code == 302
    assert replay["Location"] == "https://web.example/connexion?erreur=oauth_state_invalid_or_expired"
    assert b"handoff-delivery" not in replay.content
    assert not OAuthHandoff.objects.exists()


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff",
)
def test_nextjs_access_denied_rejects_invalid_state_without_delivery():
    delivery_binding = "S" * 43
    client = APIClient()
    metadata = {
        "authorization_endpoint": "https://identity.example/oauth/authorize/",
        "scopes_supported": ["openid", "email"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        login = client.get(
            "/api/v1/auth/carri/login/",
            {"delivery": "nextjs", "delivery_binding": delivery_binding},
        )

    state = parse_qs(urlsplit(login["Location"]).query)["state"][0]
    invalid_state = f"{state}x"
    callback = client.get(
        "/api/v1/auth/carri/callback/",
        {"state": invalid_state, "error": "access_denied"},
    )

    assert callback.status_code == 302
    assert callback["Location"] == "https://web.example/connexion?erreur=oauth_state_invalid_or_expired"
    assert b"handoff-delivery" not in callback.content
    assert not CarriIdentity.objects.exists()
    assert not OAuthHandoff.objects.exists()


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff",
)
def test_nextjs_access_denied_invalidates_expired_attempt_without_delivery():
    delivery_binding = "E" * 43
    client = APIClient()
    metadata = {
        "authorization_endpoint": "https://identity.example/oauth/authorize/",
        "scopes_supported": ["openid", "email"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        login = client.get(
            "/api/v1/auth/carri/login/",
            {"delivery": "nextjs", "delivery_binding": delivery_binding},
        )

    state = parse_qs(urlsplit(login["Location"]).query)["state"][0]
    attempt = OAuthLoginAttempt.objects.get(
        state_hash=hashlib.sha256(state.encode()).hexdigest()
    )
    attempt.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    attempt.save(update_fields=["expires_at"])

    callback = client.get(
        "/api/v1/auth/carri/callback/",
        {"state": state, "error": "access_denied"},
    )

    assert callback.status_code == 302
    assert callback["Location"] == "https://web.example/connexion?erreur=oauth_state_invalid_or_expired"
    assert b"handoff-delivery" not in callback.content
    attempt.refresh_from_db()
    assert attempt.consumed_at is not None
    assert not CarriIdentity.objects.exists()
    assert not OAuthHandoff.objects.exists()


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_CLIENT_ID="web-client", CARRI_ACCOUNT_ISSUER="https://issuer.example")
def test_web_callback_rejects_unverified_userinfo_email_without_creating_identity_or_handoff():
    state = "unverified-email-state"
    attempt = OAuthLoginAttempt.create(
        state=state,
        nonce="nonce",
        code_verifier="verifier",
        redirect_uri="https://app.example/callback",
    )
    client = APIClient()
    token_payload = {"id_token": "id", "access_token": "access"}
    id_payload = {
        "sub": "unverified-email-sub",
        "auth_time": int(datetime.now(timezone.utc).timestamp()),
    }
    with patch("apps.accounts.views.exchange_web_code", return_value=token_payload), patch(
        "apps.accounts.views.validate_id_token", return_value=id_payload
    ), patch(
        "apps.accounts.views.verified_userinfo",
        side_effect=oidc.InvalidOIDCUserInfo("Carri userinfo response is invalid."),
    ):
        response = client.get(
            "/api/v1/auth/carri/callback/", {"state": state, "code": "code"}
        )

    assert response.status_code == 400
    assert response.json() == {
        "code": "oauth_proof_invalid",
        "detail": "La preuve d'authentification est invalide.",
    }
    assert not CarriIdentity.objects.exists()
    assert not OAuthHandoff.objects.exists()
    attempt.refresh_from_db()
    assert attempt.consumed_at is None


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff",
)
def test_nextjs_callback_delivers_specific_unverified_email_error_without_identity():
    delivery_binding = "U" * 43
    client = APIClient()
    metadata = {
        "authorization_endpoint": "https://identity.example/oauth/authorize/",
        "scopes_supported": ["openid", "email"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        login = client.get(
            "/api/v1/auth/carri/login/",
            {"delivery": "nextjs", "delivery_binding": delivery_binding},
        )

    state = parse_qs(urlsplit(login["Location"]).query)["state"][0]
    attempt = OAuthLoginAttempt.objects.get(
        state_hash=hashlib.sha256(state.encode()).hexdigest()
    )
    token_payload = {"id_token": "id", "access_token": "access"}
    id_payload = {
        "sub": "unverified-nextjs-sub",
        "auth_time": int(datetime.now(timezone.utc).timestamp()),
    }
    with patch("apps.accounts.views.exchange_web_code", return_value=token_payload), patch(
        "apps.accounts.views.validate_id_token", return_value=id_payload
    ), patch(
        "apps.accounts.views.verified_userinfo",
        side_effect=oidc.UnverifiedOIDCEmail("not verified"),
    ):
        callback = client.get(
            "/api/v1/auth/carri/callback/",
            {"state": state, "code": "code"},
        )

    body = callback.content.decode()
    names = re.findall(r'<input type="hidden" name="([^"]+)"', body)
    assert callback.status_code == 200
    assert names == ["error", "delivery_binding"]
    assert 'name="error" value="oauth_email_not_verified"' in body
    assert f'name="delivery_binding" value="{delivery_binding}"' in body
    assert not CarriIdentity.objects.exists()
    assert not OAuthHandoff.objects.exists()
    assert "sessionid" not in callback.cookies
    attempt.refresh_from_db()
    assert attempt.consumed_at is not None


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff/",
    CARRI_ACCOUNT_HANDOFF_TTL_SECONDS=900,
    DEBUG=False,
)
def test_web_callback_delivers_handoff_by_post_without_tokens_or_query_leak(caplog):
    delivery_binding = "A" * 43
    client = APIClient()
    metadata = {
        "authorization_endpoint": "https://identity.example/oauth/authorize/",
        "scopes_supported": ["openid", "email"],
    }
    token_payload = {"id_token": "id", "access_token": "access"}
    id_payload = {
        "sub": "post-web-sub",
        "auth_time": int(datetime.now(timezone.utc).timestamp()),
    }

    with patch("apps.accounts.views.discovery", return_value=metadata):
        login = client.get(
            "/api/v1/auth/carri/login/",
            {
                "delivery": "nextjs",
                "delivery_binding": delivery_binding,
                "delivery_url": "https://attacker.example/collect/",
                "redirect_uri": "https://attacker.example/callback/",
            },
        )

    assert login.status_code == 302
    assert parse_qs(urlsplit(login["Location"]).query)["redirect_uri"] == [
        "https://api.example/api/v1/auth/carri/callback/"
    ]
    assert login.cookies["ecommerce_oauth_attempt"]["httponly"] is True
    assert login.cookies["ecommerce_oauth_attempt"]["secure"] is True
    assert login.cookies["ecommerce_oauth_attempt"]["samesite"] == "Lax"
    state = parse_qs(urlsplit(login["Location"]).query)["state"][0]

    with patch("apps.accounts.views.exchange_web_code", return_value=token_payload), patch(
        "apps.accounts.views.validate_id_token", return_value=id_payload
    ), patch("apps.accounts.views.verified_userinfo", return_value="post@example.com"):
        callback = client.get("/api/v1/auth/carri/callback/", {"state": state, "code": "code"})

    body = callback.content.decode()
    handoff = OAuthHandoff.objects.get(identity__carri_subject="post-web-sub")
    delivered_handoff = re.search(
        r'<input type="hidden" name="handoff" value="([^"]+)">', body
    ).group(1)
    assert callback.status_code == 200
    assert handoff.expires_at <= datetime.now(timezone.utc) + timedelta(minutes=5, seconds=1)
    assert callback["Cache-Control"] == "no-store, max-age=0"
    assert callback["Referrer-Policy"] == "no-referrer"
    assert callback["X-Robots-Tag"] == "noindex, nofollow"
    assert 'action="https://web.example/api/auth/carri/handoff/" method="post"' in body
    assert f'name="handoff" value="{handoff.token_hash}"' not in body
    assert 'name="delivery_binding" value="' + delivery_binding + '"' in body
    assert "access" not in body
    assert "refresh" not in body
    assert "?handoff=" not in body
    assert handoff.consumer_client_id == "ecommerce-web"
    assert handoff.consumed_at is None
    assert delivered_handoff not in caplog.text


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff/",
)
def test_callback_rejects_login_csrf_without_the_browser_binding_cookie():
    client = APIClient()
    metadata = {
        "authorization_endpoint": "https://identity.example/oauth/authorize/",
        "scopes_supported": ["openid", "email"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        login = client.get(
            "/api/v1/auth/carri/login/",
            {"delivery": "nextjs", "delivery_binding": "B" * 43},
        )

    state = parse_qs(urlsplit(login["Location"]).query)["state"][0]
    attacker = APIClient()
    callback = attacker.get(
        "/api/v1/auth/carri/callback/",
        {"state": state, "error": "access_denied"},
    )

    assert callback.status_code == 302
    assert callback["Location"] == "https://web.example/connexion?erreur=oauth_login_csrf_detected"


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff/",
)
def test_callback_rejects_substituted_delivery_binding_in_oauth_state():
    delivery_binding = "D" * 43
    client = APIClient()
    metadata = {
        "authorization_endpoint": "https://identity.example/oauth/authorize/",
        "scopes_supported": ["openid", "email"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        login = client.get(
            "/api/v1/auth/carri/login/",
            {"delivery": "nextjs", "delivery_binding": delivery_binding},
        )

    state = parse_qs(urlsplit(login["Location"]).query)["state"][0]
    state_prefix, _separator, _binding = state.rpartition(".")
    substituted_state = f"{state_prefix}.{'E' * len(delivery_binding)}"
    callback = client.get(
        "/api/v1/auth/carri/callback/",
        {"state": substituted_state, "error": "access_denied"},
    )

    assert callback.status_code == 302
    assert callback["Location"] == "https://web.example/connexion?erreur=oauth_state_invalid_or_expired"
    assert not CarriIdentity.objects.exists()


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
    CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL="https://web.example/api/auth/carri/handoff/",
)
def test_login_rejects_browser_selected_delivery_destination():
    response = APIClient().get(
        "/api/v1/auth/carri/login/",
        {
            "delivery": "https://attacker.example/collect/",
            "delivery_binding": "F" * 43,
            "delivery_url": "https://attacker.example/collect/",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "handoff_delivery_destination_not_allowed"


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_ISSUER="https://issuer.example",
)
def test_next_delivery_requires_a_configured_fixed_destination():
    response = APIClient().get(
        "/api/v1/auth/carri/login/",
        {"delivery": "nextjs", "delivery_binding": "C" * 43},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "handoff_delivery_destination_not_allowed"


@pytest.mark.django_db
@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_REDIRECT_URI="https://api.example/api/v1/auth/carri/callback/",
)
def test_web_login_reports_provider_failure_with_a_stable_code():
    with patch(
        "apps.accounts.views.discovery", side_effect=oidc.OIDCUnavailable()
    ):
        response = APIClient().get("/api/v1/auth/carri/login/")

    assert response.status_code == 503
    assert response.json() == {
        "code": "oauth_provider_unavailable",
        "detail": "Le service d'authentification est temporairement indisponible.",
    }


@pytest.mark.django_db
@override_settings(ECOMMERCE_HMAC_MODE="DISABLED")
def test_handoff_reports_missing_expired_replayed_and_invalid_states():
    client = APIClient()
    missing = client.post("/api/v1/auth/carri/handoff/consume/", {}, format="json")
    invalid = client.post(
        "/api/v1/auth/carri/handoff/consume/", {"handoff": "unknown"}, format="json"
    )
    identity = CarriIdentity.objects.create(carri_subject="expired-handoff")
    expired = OAuthHandoff.create_for(identity, lifetime_seconds=-1)
    expired_response = client.post(
        "/api/v1/auth/carri/handoff/consume/", {"handoff": expired}, format="json"
    )
    usable = OAuthHandoff.create_for(identity)
    assert client.post(
        "/api/v1/auth/carri/handoff/consume/", {"handoff": usable}, format="json"
    ).status_code == 200
    replayed = client.post(
        "/api/v1/auth/carri/handoff/consume/", {"handoff": usable}, format="json"
    )

    assert missing.json()["code"] == "handoff_missing"
    assert invalid.json()["code"] == "handoff_invalid"
    assert expired_response.json()["code"] == "handoff_expired"
    assert replayed.json()["code"] == "handoff_already_consumed"


def _signed_token(private_key, claims, *, alg="RS256", kid="key-1"):
    return jwt.encode(claims, private_key, algorithm=alg, headers={"kid": kid})


@override_settings(CARRI_ACCOUNT_ISSUER="https://issuer.example", CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS=0)
def test_id_token_validator_checks_signature_claims_nonce_and_at_hash():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    access = "carri-access"
    digest = hashlib.sha256(access.encode()).digest()
    at_hash = base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode()
    claims = {"iss": "https://issuer.example", "aud": "android-client", "sub": "sub", "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=5)).timestamp()), "nonce": "nonce", "at_hash": at_hash}
    token = _signed_token(private, claims)
    with patch("apps.accounts.services.oidc._key_for", return_value=private.public_key()):
        assert oidc.validate_id_token(id_token=token, audience="android-client", nonce="nonce", access_token=access, require_nonce=True, require_at_hash=True)["sub"] == "sub"
        with pytest.raises(oidc.InvalidOIDCToken):
            oidc.validate_id_token(id_token=token, audience="wrong", nonce="nonce")
        with pytest.raises(oidc.InvalidOIDCToken):
            oidc.validate_id_token(id_token=token, audience="android-client", nonce="wrong")
        with pytest.raises(oidc.InvalidOIDCToken):
            oidc.validate_id_token(id_token=token, audience="android-client", nonce="nonce", access_token="wrong", require_at_hash=True)


@override_settings(CARRI_ACCOUNT_ISSUER="https://issuer.example")
def test_id_token_validator_rejects_invalid_algorithm_and_unknown_kid_refreshes_once():
    with pytest.raises(oidc.InvalidOIDCToken):
        oidc.validate_id_token(id_token=jwt.encode({"sub": "s"}, "this-is-a-test-secret-with-at-least-thirty-two-bytes", algorithm="HS256", headers={"kid": "x"}), audience="a")
    with patch("apps.accounts.services.oidc._jwks", side_effect=[{"keys": []}, {"keys": []}]) as jwks:
        with pytest.raises(oidc.InvalidOIDCToken):
            oidc._key_for("missing")
    assert jwks.call_count == 2

@pytest.mark.django_db
def test_me_rejects_missing_invalid_and_unknown_ecommerce_identity_claims():
    client = APIClient()
    identity = CarriIdentity.objects.create(carri_subject="sub-invalid-claims")
    valid_refresh = RefreshToken.for_user(identity)
    valid_refresh["session_version"] = identity.session_version

    missing = RefreshToken()
    missing_access = str(missing.access_token)
    invalid = RefreshToken()
    invalid["identity_id"] = "not-a-uuid"
    unknown = RefreshToken()
    unknown["identity_id"] = "00000000-0000-0000-0000-000000000000"

    assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {missing_access}").status_code == 401
    assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {invalid.access_token}").status_code == 401
    assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {unknown.access_token}").status_code == 401
    assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {valid_refresh.access_token}").status_code == 200
