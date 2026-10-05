import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import jwt
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from jwt.algorithms import RSAAlgorithm

logger = logging.getLogger(__name__)


class OIDCError(Exception):
    pass


class OIDCUnavailable(OIDCError):
    pass


class InvalidOIDCToken(OIDCError):
    pass


def _issuer():
    issuer = settings.CARRI_ACCOUNT_ISSUER.rstrip("/")
    if not issuer:
        raise OIDCError("Carri Account issuer is not configured.")
    return issuer


def discovery():
    key = "carri_oidc_discovery"
    cached = cache.get(key)
    if cached:
        return cached
    try:
        response = requests.get(
            urljoin(_issuer() + "/", ".well-known/openid-configuration"),
            timeout=settings.CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OIDCUnavailable("Carri Account discovery is unavailable.") from exc
    if data.get("issuer", "").rstrip("/") != _issuer():
        raise OIDCError("Carri Account discovery issuer does not match configuration.")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not data.get(field):
            raise OIDCError("Carri Account discovery is incomplete.")
    cache.set(key, data, settings.CARRI_ACCOUNT_DISCOVERY_CACHE_SECONDS)
    return data


def _jwks(*, refresh=False):
    key = "carri_oidc_jwks"
    if refresh:
        cache.delete(key)
    cached = cache.get(key)
    if cached:
        return cached
    uri = discovery()["jwks_uri"]
    try:
        response = requests.get(uri, timeout=settings.CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OIDCUnavailable("Carri Account JWKS is unavailable.") from exc
    if not isinstance(data.get("keys"), list):
        raise OIDCError("Carri Account JWKS is invalid.")
    cache.set(key, data, settings.CARRI_ACCOUNT_JWKS_CACHE_SECONDS)
    return data


def _key_for(kid):
    for refresh in (False, True):
        for jwk in _jwks(refresh=refresh)["keys"]:
            if jwk.get("kid") == kid and jwk.get("kty") == "RSA" and jwk.get("alg") == "RS256":
                return RSAAlgorithm.from_jwk(jwk)
    raise InvalidOIDCToken("Unknown signing key.")


def _at_hash(access_token):
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode("ascii")


def validate_id_token(*, id_token, audience, nonce=None, access_token=None, require_nonce=False, require_at_hash=False):
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise InvalidOIDCToken("Malformed identity token.") from exc
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise InvalidOIDCToken("Unsupported identity token algorithm.")
    try:
        payload = jwt.decode(
            id_token,
            _key_for(header["kid"]),
            algorithms=["RS256"],
            audience=audience,
            issuer=_issuer(),
            leeway=settings.CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "sub"], "verify_iat": True},
        )
    except jwt.PyJWTError as exc:
        raise InvalidOIDCToken("Invalid identity token.") from exc
    if not payload.get("sub"):
        raise InvalidOIDCToken("Identity token subject is missing.")
    if require_nonce and not nonce:
        raise InvalidOIDCToken("Identity token nonce is missing.")
    if nonce and payload.get("nonce") != nonce:
        raise InvalidOIDCToken("Identity token nonce is invalid.")
    aud = payload.get("aud")
    audiences = {aud} if isinstance(aud, str) else set(aud or [])
    if len(audiences) > 1 and payload.get("azp") != audience:
        raise InvalidOIDCToken("Identity token authorized party is invalid.")
    if payload.get("azp") and payload["azp"] != audience:
        raise InvalidOIDCToken("Identity token authorized party is invalid.")
    if require_at_hash and not access_token:
        raise InvalidOIDCToken("Carri access token is missing.")
    if access_token:
        claim = payload.get("at_hash")
        if not claim or not hmac.compare_digest(str(claim), _at_hash(access_token)):
            raise InvalidOIDCToken("Identity token access-token binding is invalid.")
    return payload


def exchange_web_code(*, code, code_verifier, redirect_uri):
    metadata = discovery()
    try:
        response = requests.post(
            metadata["token_endpoint"],
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": code_verifier},
            auth=(settings.CARRI_ACCOUNT_CLIENT_ID, settings.CARRI_ACCOUNT_CLIENT_SECRET),
            timeout=settings.CARRI_ACCOUNT_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OIDCUnavailable("Carri Account token exchange failed.") from exc
