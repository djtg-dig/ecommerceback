"""Canonicalisation and HMAC-SHA256 signing helpers.

The contract is ``Ecommerce-HMAC v1`` and is shared by every client that must
sign a request, in particular the Next.js BFF. The canonical request is a
deterministic newline-separated string, so a signature computed over the same
logical request is always identical, whatever the client implementation.
"""

import hashlib
import hmac
import time
from urllib.parse import parse_qsl, urlencode


ECOMMERCE_HMAC_SIGNATURE_VERSION = "v1"

EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()


def compute_body_sha256(body):
    """Return the SHA-256 hex digest of the exact request body bytes."""

    return hashlib.sha256(body or b"").hexdigest()


def canonicalize_path_and_query(path, query_string=""):
    """Canonicalize path and query parameters for the signed payload.

    Parameters are sorted by name then value, blank values are preserved and
    repeated parameters are kept, so a query string and its canonical form
    always produce the same signature.
    """

    pairs = parse_qsl(query_string or "", keep_blank_values=True)
    canonical_query = urlencode(
        sorted(pairs, key=lambda item: (item[0], item[1]))
    )
    canonical_path = path or "/"
    if not canonical_query:
        return canonical_path
    return f"{canonical_path}?{canonical_query}"


def build_canonical_request(
    *,
    client_id,
    timestamp,
    nonce,
    method,
    path,
    query_string="",
    body_sha256=EMPTY_BODY_SHA256,
    version=ECOMMERCE_HMAC_SIGNATURE_VERSION,
):
    """Build the exact ``Ecommerce-HMAC v1`` canonical request string."""

    canonical_path_and_query = canonicalize_path_and_query(path, query_string)
    return "\n".join(
        [
            version,
            client_id,
            str(timestamp),
            nonce,
            method.upper(),
            canonical_path_and_query,
            body_sha256,
        ]
    )


def compute_hmac_signature(secret, canonical_request):
    """Compute an HMAC-SHA256 hex signature for a canonical request."""

    return hmac.new(
        secret.encode("utf-8"),
        canonical_request.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sign_request(
    *,
    secret,
    client_id,
    timestamp,
    nonce,
    method,
    path,
    query_string="",
    body=b"",
    version=ECOMMERCE_HMAC_SIGNATURE_VERSION,
):
    """Return the headers-ready signature and body hash for one request."""

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
    return compute_hmac_signature(secret, canonical_request), body_sha256


def verify_hmac_signature(*, provided_signature, canonical_request, secrets):
    """Verify a signature in constant time against each accepted secret."""

    if not isinstance(provided_signature, str) or not provided_signature:
        return False

    for secret in secrets:
        candidate = compute_hmac_signature(secret, canonical_request)
        if hmac.compare_digest(candidate, provided_signature):
            return True
    return False


def timestamp_is_valid(timestamp, *, max_clock_skew_seconds):
    """Return whether an integer Unix timestamp is inside the tolerance window."""

    try:
        request_time = int(timestamp)
    except (TypeError, ValueError):
        return False

    now = int(time.time())
    return (
        now - max_clock_skew_seconds
        <= request_time
        <= now + max_clock_skew_seconds
    )


class EcommerceHMACHeaders:
    """The six header names of the ``Ecommerce-HMAC v1`` contract."""

    CLIENT_ID = "X-Ecommerce-Client-Id"
    TIMESTAMP = "X-Ecommerce-Timestamp"
    NONCE = "X-Ecommerce-Nonce"
    BODY_SHA256 = "X-Ecommerce-Content-SHA256"
    VERSION = "X-Ecommerce-Signature-Version"
    SIGNATURE = "X-Ecommerce-Signature"

    _ORDER = (CLIENT_ID, TIMESTAMP, NONCE, BODY_SHA256, VERSION, SIGNATURE)

    _FIELD_OF_HEADER = {
        CLIENT_ID: "client_id",
        TIMESTAMP: "timestamp",
        NONCE: "nonce",
        BODY_SHA256: "body_sha256",
        VERSION: "version",
        SIGNATURE: "signature",
    }

    @classmethod
    def all(cls):
        """Return the six header names in canonical order."""

        return cls._ORDER

    @classmethod
    def read(cls, request):
        """Return the normalised header values of one request."""

        values = {}
        for name in cls._ORDER:
            raw = request.headers.get(name) or request.META.get(name) or ""
            raw = raw.strip() if isinstance(raw, str) else str(raw).strip()
            values[cls._FIELD_OF_HEADER[name]] = raw
        return cls(**values)

    @classmethod
    def complete(cls, values):
        """Return whether every header is present and non-empty."""

        return bool(getattr(values, "client_id", "")) and all(
            (
                values.client_id,
                values.timestamp,
                values.nonce,
                values.body_sha256,
                values.version,
                values.signature,
            )
        )

    @classmethod
    def signable_headers(cls, *, client_id, timestamp, nonce, body_sha256, version=None):
        """Return the header dict a client must send for one request."""

        return {
            cls.CLIENT_ID: client_id,
            cls.TIMESTAMP: str(timestamp),
            cls.NONCE: nonce,
            cls.BODY_SHA256: body_sha256,
            cls.VERSION: version or ECOMMERCE_HMAC_SIGNATURE_VERSION,
            cls.SIGNATURE: None,
        }

    def __init__(
        self,
        client_id="",
        timestamp="",
        nonce="",
        body_sha256="",
        version="",
        signature="",
    ):
        self.client_id = client_id
        self.timestamp = timestamp
        self.nonce = nonce
        self.body_sha256 = body_sha256
        self.version = version
        self.signature = signature

    def __eq__(self, other):
        if not isinstance(other, EcommerceHMACHeaders):
            return NotImplemented
        return all(
            getattr(self, field) == getattr(other, field)
            for field in (
                "client_id",
                "timestamp",
                "nonce",
                "body_sha256",
                "version",
                "signature",
            )
        )
