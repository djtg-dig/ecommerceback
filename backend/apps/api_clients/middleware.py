"""Application-level HMAC authentication middleware for ecommerce.

The middleware runs before DRF and identifies the *calling application*, never
the user. It never replaces ``EcommerceJWTAuthentication`` nor the business
permission engine: a valid signature only proves that the request comes from an
application holding the shared secret.

Route policy is a pure function of the method and URL path. Client-declared
hints such as ``User-Agent`` or ``X-Client-Type`` are never consulted, so a
client cannot escape HMAC by claiming to be a mobile application. Mobile
compatibility comes from *separate endpoints*, not from a bypass flag.
"""

import logging

from django.conf import settings
from django.http import JsonResponse

from .models import ApiClient, ClientNonce
from .services.hmac import (
    EMPTY_BODY_SHA256,
    EcommerceHMACHeaders,
    build_canonical_request,
    compute_body_sha256,
    timestamp_is_valid,
    verify_hmac_signature,
)
from .services.secrets import client_secret

logger = logging.getLogger(__name__)


class Mode:
    """The three supported HMAC modes, ordered by strictness."""

    DISABLED = "DISABLED"
    OBSERVATION = "OBSERVATION"
    ENFORCE = "ENFORCE"
    CHOICES = (DISABLED, OBSERVATION, ENFORCE)


class EcommerceClientHMACMiddleware:
    """Validate the application client of every HMAC-protected request."""

    HEADERS = EcommerceHMACHeaders

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._initialize_request_context(request)

        if self.mode == Mode.DISABLED:
            return self.get_response(request)

        if not self.requires_hmac(request):
            return self.get_response(request)

        result = self.verify(request, record_nonce=self.mode == Mode.ENFORCE)
        if result.ok:
            self._accept(request, result)
            return self.get_response(request)

        self._log_rejection(request, result.reason)
        if self.mode == Mode.OBSERVATION:
            # Observation never blocks and must never be read as protection.
            return self.get_response(request)
        return self._reject(request, result.reason)

    # -- configuration ----------------------------------------------------

    @property
    def mode(self):
        return getattr(settings, "ECOMMERCE_HMAC_MODE", Mode.DISABLED)

    @property
    def max_clock_skew_seconds(self):
        return int(
            getattr(settings, "ECOMMERCE_HMAC_MAX_CLOCK_SKEW_SECONDS", 120)
        )

    @property
    def nonce_ttl_seconds(self):
        return int(getattr(settings, "ECOMMERCE_HMAC_NONCE_TTL_SECONDS", 900))

    @property
    def max_body_bytes(self):
        return int(getattr(settings, "ECOMMERCE_HMAC_MAX_BODY_BYTES", 1_000_000))

    @property
    def require_body_hash(self):
        return bool(getattr(settings, "ECOMMERCE_HMAC_REQUIRE_BODY_HASH", True))

    def requires_hmac(self, request):
        """Return whether this route requires an application signature.

        The decision uses only the method and path. Relying on a
        client-declared platform would let any caller opt out of HMAC.
        """

        if self.mode == Mode.DISABLED:
            return False

        method = request.method.upper()
        if method in self.exempt_methods:
            return False

        path = request.path_info or request.path or "/"

        if self._matches(path, self.protected_prefixes):
            return True
        return False

    def _matches(self, path, prefixes):
        return any(path.startswith(prefix) for prefix in prefixes)

    @property
    def exempt_methods(self):
        return tuple(
            method.upper()
            for method in getattr(settings, "ECOMMERCE_HMAC_EXEMPT_METHODS", ("OPTIONS",))
        )

    @property
    def protected_prefixes(self):
        return tuple(
            getattr(settings, "ECOMMERCE_HMAC_PROTECTED_PREFIXES", ())
        )

    # -- verification -----------------------------------------------------

    def verify(self, request, *, record_nonce=True):
        """Verify one request and return a ``VerificationResult``.

        The signature is verified before the activation state, so only a caller
        holding the secret can learn that a key has been revoked. ``record_nonce``
        is disabled while measuring, so an observation run cannot fill the
        replay table with requests that are not actually enforced.
        """

        headers = self.HEADERS.read(request)

        if not self.HEADERS.complete(headers):
            return VerificationResult.failure("client_signature_required")

        if headers.version != self.expected_version:
            return VerificationResult.failure(
                "client_signature_version_unsupported"
            )

        secret = client_secret(headers.client_id)
        api_client = self._load_client(headers.client_id)
        if api_client is None or secret is None:
            # Unknown and unconfigured clients share one indistinguishable answer.
            return VerificationResult.failure("client_signature_invalid")

        if not timestamp_is_valid(
            headers.timestamp, max_clock_skew_seconds=self.max_clock_skew_seconds
        ):
            return VerificationResult.failure("client_signature_expired")

        body_error = self._check_body(request, headers.body_sha256)
        if body_error is not None:
            return VerificationResult.failure(body_error)

        canonical_request = build_canonical_request(
            client_id=headers.client_id,
            timestamp=headers.timestamp,
            nonce=headers.nonce,
            method=request.method,
            path=request.path_info or request.path or "/",
            query_string=request.META.get("QUERY_STRING", ""),
            body_sha256=headers.body_sha256,
            version=headers.version,
        )

        if not verify_hmac_signature(
            provided_signature=headers.signature,
            canonical_request=canonical_request,
            secrets=secret.candidate_secrets(),
        ):
            return VerificationResult.failure("client_signature_invalid")

        if not api_client.is_active:
            return VerificationResult.failure("client_key_revoked")

        if record_nonce and not ClientNonce.record(api_client, headers.nonce):
            return VerificationResult.failure("client_request_replayed")

        return VerificationResult.success(
            api_client=api_client,
            canonical=canonical_request,
            nonce=headers.nonce,
        )

    def _load_client(self, client_id):
        """Return the registry entry of a registered client, or ``None``."""

        if not client_id:
            return None
        try:
            return ApiClient.objects.get(client_id=client_id)
        except ApiClient.DoesNotExist:
            return None

    def _check_body(self, request, declared_body_sha256):
        """Compare the declared body hash with the received bytes."""

        if not self.require_body_hash:
            return None

        if not declared_body_sha256:
            return "client_body_hash_mismatch"

        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            content_length = 0

        if content_length > self.max_body_bytes:
            return "client_body_hash_mismatch"

        actual_body_sha256 = compute_body_sha256(self._read_body(request))
        if actual_body_sha256 != declared_body_sha256:
            return "client_body_hash_mismatch"

        if declared_body_sha256 == EMPTY_BODY_SHA256 and content_length:
            return "client_body_hash_mismatch"
        return None

    def _read_body(self, request):
        """Return the request body bytes, cached by Django for later views."""

        if not hasattr(request, "_cached_hmac_body"):
            try:
                request._cached_hmac_body = request.body
            except Exception:
                request._cached_hmac_body = b""
        return request._cached_hmac_body

    # -- request annotations ---------------------------------------------

    def _initialize_request_context(self, request):
        request.ecommerce_client = None
        request.client_authenticated = False
        request.client_auth_method = ""
        request.hmac_verified = False
        request.hmac_client_id = None

    def _accept(self, request, result):
        api_client = result.api_client
        request.ecommerce_client = api_client
        request.client_authenticated = True
        request.client_auth_method = api_client.auth_method
        request.hmac_verified = api_client.auth_method == ApiClient.AuthMethod.HMAC
        request.hmac_client_id = api_client.client_id
        self._touch_last_seen(api_client)

    def _touch_last_seen(self, api_client):
        """Update ``last_seen_at`` at most once per throttle window."""

        from django.utils import timezone

        now = timezone.now()
        threshold = int(
            getattr(settings, "ECOMMERCE_HMAC_LAST_SEEN_THROTTLE_SECONDS", 300)
        )
        if api_client.last_seen_at and (
            now - api_client.last_seen_at
        ).total_seconds() < threshold:
            return

        ApiClient.objects.filter(pk=api_client.pk).update(last_seen_at=now)
        api_client.last_seen_at = now

    # -- responses --------------------------------------------------------

    @property
    def expected_version(self):
        return getattr(settings, "ECOMMERCE_HMAC_SIGNATURE_VERSION", "v1")

    def _reject(self, request, reason):
        return JsonResponse(
            {"code": reason, "detail": ERROR_DETAILS.get(reason, ERROR_DETAILS["client_signature_invalid"])},
            status=ERROR_STATUS_CODES.get(reason, 401),
        )

    def _log_rejection(self, request, reason):
        logger.warning(
            "ecommerce.hmac_request_rejected",
            extra={
                "hmac_reason": reason,
                "method": request.method,
                "path": request.path,
                "mode": self.mode,
                "client_id": self.HEADERS.read(request).client_id,
            },
        )


class VerificationResult:
    """The outcome of one HMAC verification, carrying no secret material."""

    __slots__ = ("ok", "reason", "api_client", "canonical", "nonce")

    def __init__(self, ok, reason="", api_client=None, canonical="", nonce=""):
        self.ok = ok
        self.reason = reason
        self.api_client = api_client
        self.canonical = canonical
        self.nonce = nonce

    @classmethod
    def success(cls, *, api_client, canonical, nonce=""):
        return cls(True, api_client=api_client, canonical=canonical, nonce=nonce)

    @classmethod
    def failure(cls, reason):
        return cls(False, reason=reason)


ERROR_STATUS_CODES = {
    "client_signature_required": 401,
    "client_signature_invalid": 401,
    "client_signature_expired": 401,
    "client_signature_version_unsupported": 401,
    "client_request_replayed": 401,
    "client_key_revoked": 401,
    "client_body_hash_mismatch": 400,
}

ERROR_DETAILS = {
    "client_signature_required": (
        "La signature du client applicatif est obligatoire pour cette requête."
    ),
    "client_signature_invalid": (
        "La signature du client applicatif est invalide."
    ),
    "client_signature_expired": (
        "La signature du client applicatif a expiré, vérifiez l'horloge de l'appareil."
    ),
    "client_signature_version_unsupported": (
        "La version de la signature du client applicatif n'est pas prise en charge."
    ),
    "client_request_replayed": (
        "Cette requête signée a déjà été traitée."
    ),
    "client_key_revoked": (
        "La clé du client applicatif a été révoquée."
    ),
    "client_body_hash_mismatch": (
        "L'empreinte du corps de la requête ne correspond pas aux données reçues."
    ),
}
