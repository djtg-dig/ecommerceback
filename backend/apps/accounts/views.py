import base64
import hmac
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.api_clients.openapi import HMAC_ONLY, described

from .models import CarriIdentity, IDTokenReplay, OAuthHandoff, OAuthLoginAttempt
from .services.oidc import (
    InvalidOIDCToken,
    OIDCError,
    OIDCUnavailable,
    discovery,
    exchange_web_code,
    validate_id_token,
    verified_userinfo,
)

logger = logging.getLogger(__name__)


def _pair(identity):
    refresh = RefreshToken.for_user(identity)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _identity(subject, *, verified_email, auth_time):
    if type(auth_time) is not int:
        raise InvalidOIDCToken("Identity token auth_time is missing.")
    authenticated_at = datetime.fromtimestamp(auth_time, tz=dt_timezone.utc)
    now = timezone.now()
    if authenticated_at > now + timedelta(
        seconds=settings.CARRI_ACCOUNT_ID_TOKEN_CLOCK_SKEW_SECONDS
    ):
        raise InvalidOIDCToken("Identity token auth_time is invalid.")
    identity, _ = CarriIdentity.objects.get_or_create(carri_subject=subject)
    identity.verified_email = verified_email
    identity.email_verified = True
    identity.email_verified_at = now
    identity.last_oidc_auth_at = authenticated_at
    identity.last_login_at = now
    identity.save(
        update_fields=[
            "verified_email",
            "email_verified",
            "email_verified_at",
            "last_oidc_auth_at",
            "last_login_at",
        ]
    )
    return identity


def _random(size=32):
    return secrets.token_urlsafe(size)


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _error(detail, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": detail}, status=code)


def _authentication_error(code, detail, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({"code": code, "detail": detail}, status=status_code)


def _sha256(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _web_handoff_delivery_url():
    """Return the one configured Next.js delivery URL, or ``None``.

    The callback never accepts a browser-controlled destination. HTTP is only
    accepted while Django DEBUG is on, for a same-machine local BFF.
    """

    raw_url = settings.CARRI_ACCOUNT_WEB_HANDOFF_DELIVERY_URL.strip()
    if not raw_url:
        return None
    parsed = urlsplit(raw_url)
    allowed_schemes = {"https"}
    if settings.DEBUG:
        allowed_schemes.add("http")
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    return raw_url


def _delivery_form_response(*, request, handoff, delivery_url, delivery_binding):
    """POST a handoff without placing it in a URL, referer, or cache."""

    parsed = urlsplit(delivery_url)
    form_action_origin = f"{parsed.scheme}://{parsed.netloc}"
    csp_nonce = secrets.token_urlsafe(18)
    response = render(
        request,
        "accounts/handoff_delivery.html",
        {
            "handoff": handoff,
            "delivery_binding": delivery_binding,
            "delivery_url": delivery_url,
            "csp_nonce": csp_nonce,
        },
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = "no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "DENY"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Content-Security-Policy"] = (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        f"form-action {form_action_origin}; script-src 'nonce-{csp_nonce}'"
    )
    return response


def _clear_browser_binding_cookie(response):
    response.delete_cookie(
        settings.CARRI_ACCOUNT_OAUTH_BROWSER_BINDING_COOKIE_NAME,
        path="/api/v1/auth/carri/callback/",
    )
    return response


class CarriMobileExchangeView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        id_token = request.data.get("id_token", "")
        access_token = request.data.get("access_token", "")
        nonce = request.data.get("nonce", "")
        if not all(isinstance(value, str) and value for value in (id_token, access_token, nonce)):
            return _error("Invalid authentication proof.")
        if not settings.CARRI_ACCOUNT_ANDROID_CLIENT_ID:
            logger.error("carri.mobile_exchange.configuration_missing")
            return _error("Authentication service is unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            payload = validate_id_token(
                id_token=id_token,
                audience=settings.CARRI_ACCOUNT_ANDROID_CLIENT_ID,
                nonce=nonce,
                access_token=access_token,
                require_nonce=True,
                require_at_hash=True,
            )
            email = verified_userinfo(
                access_token=access_token,
                subject=payload["sub"],
            )
            expires_at = datetime.fromtimestamp(payload["exp"], tz=dt_timezone.utc)
            token_hash = hashlib.sha256(id_token.encode()).hexdigest()
            with transaction.atomic():
                IDTokenReplay.objects.create(token_hash=token_hash, expires_at=expires_at)
                identity = _identity(
                    payload["sub"],
                    verified_email=email,
                    auth_time=payload.get("auth_time"),
                )
            logger.info("carri.mobile_exchange.success identity=%s", identity.pk)
            return Response(_pair(identity), status=status.HTTP_200_OK)
        except IntegrityError:
            logger.warning("carri.mobile_exchange.replay")
            return _error("Authentication proof has already been used.")
        except OIDCUnavailable:
            logger.warning("carri.mobile_exchange.provider_unavailable")
            return _error("Authentication service is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        except (OIDCError, InvalidOIDCToken, ValueError, TypeError):
            logger.warning("carri.mobile_exchange.invalid_proof")
            return _error("Invalid authentication proof.")


class CarriLoginView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not all((settings.CARRI_ACCOUNT_CLIENT_ID, settings.CARRI_ACCOUNT_CLIENT_SECRET, settings.CARRI_ACCOUNT_REDIRECT_URI)):
            return _authentication_error(
                "oauth_configuration_unavailable",
                "Le service d'authentification est indisponible.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            delivery = request.query_params.get("delivery", "")
            delivery_url = ""
            delivery_binding = ""
            if delivery:
                if delivery != "nextjs":
                    return _authentication_error(
                        "handoff_delivery_destination_not_allowed",
                        "La destination de livraison du handoff n'est pas autorisée.",
                    )
                delivery_url = _web_handoff_delivery_url()
                delivery_binding = request.query_params.get("delivery_binding", "")
                if not delivery_url:
                    return _authentication_error(
                        "handoff_delivery_destination_not_allowed",
                        "La destination de livraison du handoff n'est pas autorisée.",
                    )
                if not (
                    isinstance(delivery_binding, str)
                    and 32 <= len(delivery_binding) <= 128
                    and all(character.isalnum() or character in "-_" for character in delivery_binding)
                ):
                    return _authentication_error(
                        "handoff_delivery_binding_invalid",
                        "La liaison de livraison du handoff est invalide.",
                    )
            metadata = discovery()
            scopes = settings.CARRI_ACCOUNT_SCOPES.split()
            supported_scopes = set(metadata.get("scopes_supported", ()))
            if not {"openid", "email"}.issubset(scopes) or not set(scopes).issubset(
                supported_scopes
            ):
                raise OIDCError("Carri Account does not support the required scopes.")
            state, nonce, verifier, browser_binding = _random(), _random(), _random(64), _random()
            if delivery_binding:
                # OAuth state is already an opaque browser round-trip value.
                # Carrying the Next.js binding inside it lets Django retain only
                # its hash at rest while returning the exact browser value by POST.
                state = f"{state}.{delivery_binding}"
            OAuthLoginAttempt.create(
                state=state, nonce=nonce, code_verifier=verifier,
                redirect_uri=settings.CARRI_ACCOUNT_REDIRECT_URI,
                browser_binding=browser_binding,
                handoff_delivery_url=delivery_url,
                handoff_delivery_binding=delivery_binding,
                lifetime_seconds=settings.CARRI_ACCOUNT_OAUTH_ATTEMPT_TTL_SECONDS,
            )
            query = urlencode({
                "response_type": "code", "client_id": settings.CARRI_ACCOUNT_CLIENT_ID,
                "redirect_uri": settings.CARRI_ACCOUNT_REDIRECT_URI,
                "scope": " ".join(scopes),
                "state": state, "nonce": nonce, "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
            })
            response = redirect(f"{metadata['authorization_endpoint']}?{query}")
            response.set_cookie(
                settings.CARRI_ACCOUNT_OAUTH_BROWSER_BINDING_COOKIE_NAME,
                browser_binding,
                max_age=settings.CARRI_ACCOUNT_OAUTH_ATTEMPT_TTL_SECONDS,
                httponly=True,
                secure=not settings.DEBUG,
                samesite="Lax",
                path="/api/v1/auth/carri/callback/",
            )
            response["Cache-Control"] = "no-store, max-age=0"
            response["Referrer-Policy"] = "no-referrer"
            return response
        except OIDCUnavailable:
            return _authentication_error(
                "oauth_provider_unavailable",
                "Le service d'authentification est temporairement indisponible.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except OIDCError:
            logger.error("carri.web_login.invalid_provider_configuration")
            return _authentication_error(
                "oauth_configuration_unavailable",
                "Le service d'authentification est indisponible.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class CarriCallbackView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        state = request.query_params.get("state", "")
        state_hash = hashlib.sha256(state.encode()).hexdigest() if state else ""
        try:
            with transaction.atomic():
                attempt = OAuthLoginAttempt.objects.select_for_update().get(state_hash=state_hash)
                if not attempt.is_usable:
                    return _authentication_error(
                        "oauth_state_invalid_or_expired",
                        "L'état OAuth est invalide ou expiré.",
                    )
                if attempt.browser_binding_hash:
                    browser_binding = request.COOKIES.get(
                        settings.CARRI_ACCOUNT_OAUTH_BROWSER_BINDING_COOKIE_NAME,
                        "",
                    )
                    if not browser_binding or not hmac.compare_digest(
                        _sha256(browser_binding), attempt.browser_binding_hash
                    ):
                        return _authentication_error(
                            "oauth_login_csrf_detected",
                            "La liaison de connexion OAuth est invalide.",
                        )
                delivery_binding = ""
                if attempt.handoff_delivery_binding_hash:
                    _, separator, delivery_binding = state.partition(".")
                    if not separator or not hmac.compare_digest(
                        _sha256(delivery_binding), attempt.handoff_delivery_binding_hash
                    ):
                        return _authentication_error(
                            "handoff_delivery_binding_invalid",
                            "La liaison de livraison du handoff est invalide.",
                        )
                if request.query_params.get("error"):
                    attempt.consumed_at = timezone.now()
                    attempt.save(update_fields=["consumed_at"])
                    return _clear_browser_binding_cookie(_authentication_error(
                        "oauth_authorization_denied",
                        "L'autorisation Carri Account a été refusée.",
                    ))
                code = request.query_params.get("code", "")
                if not code:
                    return _authentication_error(
                        "oauth_callback_invalid",
                        "Le retour OAuth est invalide.",
                    )
                tokens = exchange_web_code(code=code, code_verifier=attempt.code_verifier, redirect_uri=attempt.redirect_uri)
                payload = validate_id_token(
                    id_token=tokens.get("id_token", ""), audience=settings.CARRI_ACCOUNT_CLIENT_ID,
                    nonce=attempt.nonce, access_token=tokens.get("access_token"), require_nonce=True,
                    require_at_hash=bool(tokens.get("access_token")),
                )
                email = verified_userinfo(
                    access_token=tokens.get("access_token", ""),
                    subject=payload["sub"],
                )
                identity = _identity(
                    payload["sub"],
                    verified_email=email,
                    auth_time=payload.get("auth_time"),
                )
                attempt.consumed_at = timezone.now()
                attempt.save(update_fields=["consumed_at"])
                handoff_lifetime_seconds = settings.CARRI_ACCOUNT_HANDOFF_TTL_SECONDS
                if attempt.handoff_delivery_url:
                    handoff_lifetime_seconds = min(
                        max(handoff_lifetime_seconds, 1), 300
                    )
                handoff = OAuthHandoff.create_for(
                    identity,
                    handoff_lifetime_seconds,
                    consumer_client_id=(
                        settings.CARRI_ACCOUNT_WEB_HANDOFF_CLIENT_ID
                        if attempt.handoff_delivery_url
                        else ""
                    ),
                )
            logger.info("carri.web_callback.success identity=%s", identity.pk)
            if attempt.handoff_delivery_url:
                response = _delivery_form_response(
                    request=request,
                    handoff=handoff,
                    delivery_url=attempt.handoff_delivery_url,
                    delivery_binding=delivery_binding,
                )
                response = _clear_browser_binding_cookie(response)
                return response
            return _clear_browser_binding_cookie(Response({"handoff": handoff}, status=status.HTTP_200_OK))
        except OAuthLoginAttempt.DoesNotExist:
            return _authentication_error(
                "oauth_state_invalid_or_expired",
                "L'état OAuth est invalide ou expiré.",
            )
        except OIDCUnavailable:
            return _authentication_error(
                "oauth_provider_unavailable",
                "Le service d'authentification est temporairement indisponible.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except (OIDCError, InvalidOIDCToken, ValueError, TypeError):
            logger.warning("carri.web_callback.invalid_proof")
            return _authentication_error(
                "oauth_proof_invalid",
                "La preuve d'authentification est invalide.",
            )


class CarriHandoffConsumeView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        token = request.data.get("handoff", "")
        if not isinstance(token, str) or not token:
            return _authentication_error("handoff_missing", "Le handoff est obligatoire.")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with transaction.atomic():
            handoff = OAuthHandoff.objects.select_for_update().select_related("identity").filter(token_hash=token_hash).first()
            if not handoff:
                return _authentication_error("handoff_invalid", "Le handoff est invalide.")
            if handoff.consumed_at:
                return _authentication_error("handoff_already_consumed", "Le handoff a déjà été consommé.")
            if handoff.expires_at <= timezone.now():
                return _authentication_error("handoff_expired", "Le handoff a expiré.")
            if handoff.consumer_client_id and (
                not request.hmac_verified
                or request.hmac_client_id != handoff.consumer_client_id
            ):
                return _authentication_error(
                    "handoff_client_not_authorized",
                    "Ce client applicatif ne peut pas consommer ce handoff.",
                    status.HTTP_403_FORBIDDEN,
                )
            handoff.consumed_at = timezone.now()
            handoff.save(update_fields=["consumed_at"])
            return Response(_pair(handoff.identity), status=status.HTTP_200_OK)


class CurrentIdentityView(APIView):
    def get(self, request):
        return Response({"id": str(request.user.id), "carri_subject": request.user.carri_subject})

# Explicit APIView annotations keep authentication flows visible without exposing
# provider secrets, authorization codes or PKCE verifier values.
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers

_token_pair_schema = inline_serializer("EcommerceTokenPair", {
    "access": serializers.CharField(read_only=True),
    "refresh": serializers.CharField(read_only=True),
})
_error_schema = inline_serializer("AuthenticationError", {
    "detail": serializers.CharField(read_only=True),
})
_stable_error_schema = inline_serializer("StableAuthenticationError", {
    "code": serializers.CharField(read_only=True),
    "detail": serializers.CharField(read_only=True),
})

CarriMobileExchangeView.post = extend_schema(
    tags=["Authentication"], operation_id="carri_mobile_exchange",
    request=inline_serializer("CarriMobileExchangeRequest", {
        "id_token": serializers.CharField(), "access_token": serializers.CharField(), "nonce": serializers.CharField(),
    }), responses={200: _token_pair_schema, 400: _error_schema, 503: _error_schema},
    description="Valide la preuve OIDC Android puis émet des JWT ecommerce.",
)(CarriMobileExchangeView.post)
CarriLoginView.get = extend_schema(
    tags=["Authentication"], operation_id="carri_web_login", request=None,
    parameters=[
        OpenApiParameter(
            "delivery",
            str,
            OpenApiParameter.QUERY,
            required=False,
            description="Valeur fixe `nextjs` pour demander la livraison POST configurée côté serveur.",
        ),
        OpenApiParameter(
            "delivery_binding",
            str,
            OpenApiParameter.QUERY,
            required=False,
            description="Jeton de corrélation Next.js opaque; jamais une URL de destination.",
        ),
    ],
    responses={302: None, 400: _stable_error_schema, 503: _stable_error_schema},
    description=(
        "Démarre Authorization Code + PKCE chez Carri Account. Le navigateur ne "
        "choisit jamais la destination; `delivery=nextjs` utilise uniquement "
        "l'URL Next.js allowlistée dans la configuration serveur."
    ),
)(CarriLoginView.get)
CarriCallbackView.get = extend_schema(
    tags=["Authentication"], operation_id="carri_web_callback", request=None,
    responses={
        200: inline_serializer(
            "OAuthHandoffResponse",
            {"handoff": serializers.CharField(read_only=True)},
        ),
        (200, "text/html"): OpenApiTypes.STR,
        400: _stable_error_schema,
        503: _stable_error_schema,
    },
    description=(
        "Traite le callback OIDC. Sans livraison demandée, retourne le handoff "
        "JSON historique. Avec `delivery=nextjs`, répond par une page sans cache "
        "qui POSTe le handoff opaque vers la destination Next.js configurée."
    ),
)(CarriCallbackView.get)
CarriHandoffConsumeView.post = extend_schema(
    tags=["Authentication"], operation_id="carri_handoff_consume",
    request=inline_serializer("OAuthHandoffConsumeRequest", {"handoff": serializers.CharField()}),
    responses={
        200: _token_pair_schema,
        400: _stable_error_schema,
        401: _stable_error_schema,
        403: _stable_error_schema,
    },
    auth=HMAC_ONLY,
    description=(
        "Consomme un handoff opaque a usage unique et emet les JWT ecommerce. "
        + described(HMAC_ONLY)
    ),
)(CarriHandoffConsumeView.post)
CurrentIdentityView.get = extend_schema(
    tags=["Authentication"], operation_id="current_ecommerce_identity",
    responses={200: inline_serializer("CurrentIdentity", {"id": serializers.UUIDField(), "carri_subject": serializers.CharField()}), 401: _error_schema},
)(CurrentIdentityView.get)
