from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import pytest
import requests
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.accounts.services import oidc


def userinfo_response(**overrides):
    data = {
        "public_id": "US1234567890",
        "email": " User@Example.COM ",
        "email_verified": True,
    }
    data.update(overrides)
    return data


def test_verified_userinfo_normalizes_email_and_matches_validated_subject():
    with patch(
        "apps.accounts.services.oidc.fetch_userinfo",
        return_value=userinfo_response(),
    ):
        email = oidc.verified_userinfo(
            access_token="opaque-access-token",
            subject="US1234567890",
        )

    assert email == "user@example.com"


def test_verified_userinfo_rejects_subject_mismatch():
    with patch(
        "apps.accounts.services.oidc.fetch_userinfo",
        return_value=userinfo_response(public_id="USOTHER00000"),
    ), pytest.raises(oidc.InvalidOIDCUserInfo, match="subject"):
        oidc.verified_userinfo(
            access_token="opaque-access-token",
            subject="US1234567890",
        )


@pytest.mark.parametrize("claim", [False, None, "true", 1])
def test_verified_userinfo_requires_strict_true_boolean(claim):
    payload = userinfo_response()
    if claim is None:
        payload.pop("email_verified")
    else:
        payload["email_verified"] = claim
    with patch(
        "apps.accounts.services.oidc.fetch_userinfo",
        return_value=payload,
    ), pytest.raises(oidc.InvalidOIDCUserInfo, match="not verified"):
        oidc.verified_userinfo(
            access_token="opaque-access-token",
            subject="US1234567890",
        )


@pytest.mark.parametrize("email", [None, "", "not-an-email", "user@"])
def test_verified_userinfo_rejects_missing_or_invalid_email(email):
    with patch(
        "apps.accounts.services.oidc.fetch_userinfo",
        return_value=userinfo_response(email=email),
    ), pytest.raises(oidc.InvalidOIDCUserInfo, match="email"):
        oidc.verified_userinfo(
            access_token="opaque-access-token",
            subject="US1234567890",
        )


@override_settings(CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS=3)
def test_userinfo_rejects_invalid_access_token_without_logging_it(caplog):
    response = Mock(status_code=401)
    with patch(
        "apps.accounts.services.oidc.discovery",
        return_value={"userinfo_endpoint": "https://account.example/userinfo"},
    ), patch("apps.accounts.services.oidc.requests.get", return_value=response), pytest.raises(
        oidc.InvalidOIDCUserInfo,
        match="rejected",
    ):
        oidc.fetch_userinfo("secret-access-token")

    assert "secret-access-token" not in caplog.text


def test_userinfo_network_failure_is_controlled_and_does_not_leak_token(caplog):
    with patch(
        "apps.accounts.services.oidc.discovery",
        return_value={"userinfo_endpoint": "https://account.example/userinfo"},
    ), patch(
        "apps.accounts.services.oidc.requests.get",
        side_effect=requests.Timeout("network timeout"),
    ), pytest.raises(oidc.OIDCUnavailable, match="unavailable"):
        oidc.fetch_userinfo("another-secret-token")

    assert "another-secret-token" not in caplog.text


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_EMAIL_PROOF_MAX_AGE_SECONDS=600)
def test_verified_email_freshness_checks_observation_and_auth_time_separately():
    now = timezone.now()
    identity = CarriIdentity.objects.create(
        carri_subject="freshness-subject",
        verified_email="fresh@example.com",
        email_verified=True,
        email_verified_at=now,
        last_oidc_auth_at=now,
    )
    assert identity.has_fresh_verified_email(now=now)

    identity.email_verified_at = now - timedelta(minutes=11)
    assert not identity.has_fresh_verified_email(now=now)

    identity.email_verified_at = now
    identity.last_oidc_auth_at = now - timedelta(minutes=11)
    assert not identity.has_fresh_verified_email(now=now)


@pytest.mark.django_db
def test_existing_session_without_verified_email_requires_reauthentication():
    identity = CarriIdentity.objects.create(carri_subject="legacy-session")

    assert identity.verified_email == ""
    assert identity.email_verified is False
    assert not identity.has_fresh_verified_email()


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_ANDROID_CLIENT_ID="android-client")
def test_unverified_userinfo_never_overwrites_an_existing_valid_proof():
    observed_at = timezone.now() - timedelta(minutes=2)
    identity = CarriIdentity.objects.create(
        carri_subject="preserved-subject",
        verified_email="preserved@example.com",
        email_verified=True,
        email_verified_at=observed_at,
        last_oidc_auth_at=observed_at,
    )
    payload = {
        "sub": identity.carri_subject,
        "auth_time": int(timezone.now().timestamp()),
        "exp": int((timezone.now() + timedelta(minutes=5)).timestamp()),
    }
    client = APIClient()
    with patch(
        "apps.accounts.views.validate_id_token",
        return_value=payload,
    ), patch(
        "apps.accounts.views.verified_userinfo",
        side_effect=oidc.InvalidOIDCUserInfo("Email is not verified."),
    ):
        response = client.post(
            "/api/v1/auth/carri/mobile/exchange/",
            {
                "id_token": "new-proof",
                "access_token": "opaque-access-token",
                "nonce": "nonce",
            },
            format="json",
        )

    identity.refresh_from_db()
    assert response.status_code == 400
    assert identity.verified_email == "preserved@example.com"
    assert identity.email_verified_at == observed_at


@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_REDIRECT_URI="https://shop.example/callback",
    CARRI_ACCOUNT_SCOPES="openid email",
)
@pytest.mark.django_db
def test_web_login_requests_openid_email_and_preserves_pkce(client):
    metadata = {
        "authorization_endpoint": "https://account.example/authorize",
        "scopes_supported": ["openid", "email", "profile"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        response = client.get("/api/v1/auth/carri/login/")

    query = parse_qs(urlparse(response.url).query)
    assert response.status_code == 302
    assert query["scope"] == ["openid email"]
    assert query["nonce"][0]
    assert query["state"][0]
    assert query["code_challenge"][0]
    assert query["code_challenge_method"] == ["S256"]


@override_settings(
    CARRI_ACCOUNT_CLIENT_ID="web-client",
    CARRI_ACCOUNT_CLIENT_SECRET="web-secret",
    CARRI_ACCOUNT_REDIRECT_URI="https://shop.example/callback",
    CARRI_ACCOUNT_SCOPES="openid email",
)
@pytest.mark.django_db
def test_web_login_fails_closed_when_provider_does_not_support_email(client):
    metadata = {
        "authorization_endpoint": "https://account.example/authorize",
        "scopes_supported": ["openid"],
    }
    with patch("apps.accounts.views.discovery", return_value=metadata):
        response = client.get("/api/v1/auth/carri/login/")

    assert response.status_code == 503
