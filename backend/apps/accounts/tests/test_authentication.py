import base64
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CarriIdentity, OAuthLoginAttempt
from apps.accounts.services import oidc


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_ANDROID_CLIENT_ID="android-client", CARRI_ACCOUNT_ISSUER="https://issuer.example")
def test_mobile_exchange_creates_and_reuses_identity():
    client = APIClient()
    payload = {"sub": "carri-subject", "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())}
    with patch("apps.accounts.views.validate_id_token", return_value=payload):
        first = client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "one", "access_token": "access", "nonce": "nonce"}, format="json")
        second = client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "two", "access_token": "access", "nonce": "nonce"}, format="json")
    assert first.status_code == 200
    assert second.status_code == 200
    assert CarriIdentity.objects.filter(carri_subject="carri-subject").count() == 1


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_ANDROID_CLIENT_ID="android-client")
def test_mobile_exchange_rejects_replay_and_incomplete_payload():
    client = APIClient()
    payload = {"sub": "carri-subject", "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())}
    with patch("apps.accounts.views.validate_id_token", return_value=payload):
        assert client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "same", "access_token": "access", "nonce": "nonce"}, format="json").status_code == 200
        assert client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "same", "access_token": "access", "nonce": "nonce"}, format="json").status_code == 400
    assert client.post("/api/v1/auth/carri/mobile/exchange/", {"id_token": "only"}, format="json").status_code == 400


@pytest.mark.django_db
def test_me_requires_ecommerce_jwt_and_returns_identity():
    identity = CarriIdentity.objects.create(carri_subject="sub-1")
    client = APIClient()
    assert client.get("/api/v1/auth/me/").status_code == 401
    access = str(RefreshToken.for_user(identity).access_token)
    response = client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200
    assert response.json() == {"id": str(identity.id), "carri_subject": "sub-1"}


@pytest.mark.django_db
@override_settings(CARRI_ACCOUNT_CLIENT_ID="web-client", CARRI_ACCOUNT_ISSUER="https://issuer.example")
def test_web_callback_consumes_state_once_and_returns_handoff():
    state = "state-value"
    OAuthLoginAttempt.create(state=state, nonce="nonce", code_verifier="verifier", redirect_uri="https://app.example/callback")
    client = APIClient()
    token_payload = {"id_token": "id", "access_token": "access"}
    with patch("apps.accounts.views.exchange_web_code", return_value=token_payload), patch("apps.accounts.views.validate_id_token", return_value={"sub": "web-sub"}):
        response = client.get("/api/v1/auth/carri/callback/", {"state": state, "code": "code"})
        reused = client.get("/api/v1/auth/carri/callback/", {"state": state, "code": "code"})
    assert response.status_code == 200
    assert "handoff" in response.json()
    assert reused.status_code == 400


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
