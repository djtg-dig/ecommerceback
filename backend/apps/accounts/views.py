import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlencode

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

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
            return _error("Authentication service is unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            metadata = discovery()
            scopes = settings.CARRI_ACCOUNT_SCOPES.split()
            supported_scopes = set(metadata.get("scopes_supported", ()))
            if not {"openid", "email"}.issubset(scopes) or not set(scopes).issubset(
                supported_scopes
            ):
                raise OIDCError("Carri Account does not support the required scopes.")
            state, nonce, verifier = _random(), _random(), _random(64)
            OAuthLoginAttempt.create(
                state=state, nonce=nonce, code_verifier=verifier,
                redirect_uri=settings.CARRI_ACCOUNT_REDIRECT_URI,
                lifetime_seconds=settings.CARRI_ACCOUNT_OAUTH_ATTEMPT_TTL_SECONDS,
            )
            query = urlencode({
                "response_type": "code", "client_id": settings.CARRI_ACCOUNT_CLIENT_ID,
                "redirect_uri": settings.CARRI_ACCOUNT_REDIRECT_URI,
                "scope": " ".join(scopes),
                "state": state, "nonce": nonce, "code_challenge": _challenge(verifier),
                "code_challenge_method": "S256",
            })
            return redirect(f"{metadata['authorization_endpoint']}?{query}")
        except OIDCUnavailable:
            return _error("Authentication service is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        except OIDCError:
            logger.error("carri.web_login.invalid_provider_configuration")
            return _error("Authentication service is unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)


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
                    return _error("OAuth state is invalid or expired.")
                if request.query_params.get("error"):
                    attempt.consumed_at = timezone.now()
                    attempt.save(update_fields=["consumed_at"])
                    return _error("Carri Account authorization was denied.")
                code = request.query_params.get("code", "")
                if not code:
                    return _error("OAuth callback is invalid.")
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
                handoff = OAuthHandoff.create_for(identity, settings.CARRI_ACCOUNT_HANDOFF_TTL_SECONDS)
            logger.info("carri.web_callback.success identity=%s", identity.pk)
            return Response({"handoff": handoff}, status=status.HTTP_200_OK)
        except OAuthLoginAttempt.DoesNotExist:
            return _error("OAuth state is invalid or expired.")
        except OIDCUnavailable:
            return _error("Authentication service is temporarily unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE)
        except (OIDCError, InvalidOIDCToken, ValueError, TypeError):
            logger.warning("carri.web_callback.invalid_proof")
            return _error("Invalid authentication proof.")


class CarriHandoffConsumeView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        token = request.data.get("handoff", "")
        if not isinstance(token, str) or not token:
            return _error("Invalid handoff.")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with transaction.atomic():
            handoff = OAuthHandoff.objects.select_for_update().select_related("identity").filter(token_hash=token_hash).first()
            if not handoff or not handoff.is_usable:
                return _error("Invalid handoff.")
            handoff.consumed_at = timezone.now()
            handoff.save(update_fields=["consumed_at"])
            return Response(_pair(handoff.identity), status=status.HTTP_200_OK)


class CurrentIdentityView(APIView):
    def get(self, request):
        return Response({"id": str(request.user.id), "carri_subject": request.user.carri_subject})

# Explicit APIView annotations keep authentication flows visible without exposing
# provider secrets, authorization codes or PKCE verifier values.
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers

_token_pair_schema = inline_serializer("EcommerceTokenPair", {
    "access": serializers.CharField(read_only=True),
    "refresh": serializers.CharField(read_only=True),
})
_error_schema = inline_serializer("AuthenticationError", {"detail": serializers.CharField(read_only=True)})

CarriMobileExchangeView.post = extend_schema(
    tags=["Authentication"], operation_id="carri_mobile_exchange",
    request=inline_serializer("CarriMobileExchangeRequest", {
        "id_token": serializers.CharField(), "access_token": serializers.CharField(), "nonce": serializers.CharField(),
    }), responses={200: _token_pair_schema, 400: _error_schema, 503: _error_schema},
    description="Valide la preuve OIDC Android puis émet des JWT ecommerce.",
)(CarriMobileExchangeView.post)
CarriLoginView.get = extend_schema(
    tags=["Authentication"], operation_id="carri_web_login", request=None,
    responses={302: None, 503: _error_schema},
    description="Démarre Authorization Code + PKCE chez Carri Account.",
)(CarriLoginView.get)
CarriCallbackView.get = extend_schema(
    tags=["Authentication"], operation_id="carri_web_callback", request=None,
    responses={200: inline_serializer("OAuthHandoffResponse", {"handoff": serializers.CharField(read_only=True)}), 400: _error_schema, 503: _error_schema},
    description="Traite le callback OIDC et retourne un handoff opaque à usage unique.",
)(CarriCallbackView.get)
CarriHandoffConsumeView.post = extend_schema(
    tags=["Authentication"], operation_id="carri_handoff_consume",
    request=inline_serializer("OAuthHandoffConsumeRequest", {"handoff": serializers.CharField()}),
    responses={200: _token_pair_schema, 400: _error_schema},
)(CarriHandoffConsumeView.post)
CurrentIdentityView.get = extend_schema(
    tags=["Authentication"], operation_id="current_ecommerce_identity",
    responses={200: inline_serializer("CurrentIdentity", {"id": serializers.UUIDField(), "carri_subject": serializers.CharField()}), 401: _error_schema},
)(CurrentIdentityView.get)
