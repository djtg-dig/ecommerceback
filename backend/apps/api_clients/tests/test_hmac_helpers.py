"""Tests for the Ecommerce-HMAC v1 canonicalisation and signing helpers."""

from apps.api_clients.services.hmac import (
    EMPTY_BODY_SHA256,
    EcommerceHMACHeaders,
    build_canonical_request,
    canonicalize_path_and_query,
    compute_body_sha256,
    compute_hmac_signature,
    sign_request,
    timestamp_is_valid,
)


DEMO_SECRET = "demo-shared-secret-not-a-real-key"


class TestCanonicalisation:
    """The canonical string must be deterministic for every client."""

    def test_empty_body_hash_is_stable(self):
        assert EMPTY_BODY_SHA256 == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        assert compute_body_sha256(None) == EMPTY_BODY_SHA256
        assert compute_body_sha256(b"") == EMPTY_BODY_SHA256

    def test_canonical_request_joins_seven_ordered_lines(self):
        canonical = build_canonical_request(
            client_id="ecommerce-web",
            timestamp="1760000000",
            nonce="5f2b7c1e-9a3d-4c8e-b1a6-0d4e2f8c9a01",
            method="get",
            path="/api/v1/businesses/",
            query_string="page=2&page_size=20",
            body_sha256=EMPTY_BODY_SHA256,
        )

        assert canonical.split("\n") == [
            "v1",
            "ecommerce-web",
            "1760000000",
            "5f2b7c1e-9a3d-4c8e-b1a6-0d4e2f8c9a01",
            "GET",
            "/api/v1/businesses/?page=2&page_size=20",
            EMPTY_BODY_SHA256,
        ]

    def test_query_is_sorted_by_key_then_value_with_blank_and_repeated_values(
        self,
    ):
        assert (
            canonicalize_path_and_query(
                "/api/v1/businesses/", "status=PAID&page=2&tag=b&tag=a&empty="
            )
            == "/api/v1/businesses/?empty=&page=2&status=PAID&tag=a&tag=b"
        )

    def test_path_without_query_is_not_appended_with_a_question_mark(self):
        assert canonicalize_path_and_query("/api/v1/health/", "") == "/api/v1/health/"

    def test_signature_uses_hmac_sha256_hex(self):
        signature = compute_hmac_signature(
            "demo-shared-secret-not-a-real-key", "canonical"
        )

        assert len(signature) == 64
        assert signature == signature.lower()
        int(signature, 16)


class TestDocumentedVectors:
    """The three vectors of the P1-A5.2 report must stay reproducible."""

    SIGNATURE_VERSION = "v1"
    DEMO_SECRET = DEMO_SECRET

    def test_vector_one_get_with_query(self):
        body_sha256 = compute_body_sha256(b"")
        canonical = build_canonical_request(
            client_id="ecommerce-web",
            timestamp="1760000000",
            nonce="5f2b7c1e-9a3d-4c8e-b1a6-0d4e2f8c9a01",
            method="GET",
            path="/api/v1/businesses/",
            query_string="page=2&page_size=20",
            body_sha256=body_sha256,
        )

        assert compute_hmac_signature(DEMO_SECRET, canonical) == (
            "f9ed028a8aea2533d551fba8f86197906edfa2cafefdb191ba37b0bacb86e6bb"
        )

    def test_vector_two_post_with_body(self):
        body = b'{"email":"membre@example.com","title":"Caissier"}'
        body_sha256 = compute_body_sha256(body)
        canonical = build_canonical_request(
            client_id="ecommerce-web",
            timestamp="1760000100",
            nonce="8c1d4e2a-7b93-4f05-9d6a-3e5c7a1b2d40",
            method="POST",
            path="/api/v1/businesses/SH23456789AB/invitations/",
            query_string="",
            body_sha256=body_sha256,
        )

        assert body_sha256 == (
            "26588659a66e2d544f2dc0252081ee2c3225bb9a5eb4b0edbbda96eeeb60e930"
        )
        assert compute_hmac_signature(DEMO_SECRET, canonical) == (
            "ffe9356b7e5814534731aa8644e0cca7156b19ee6c3819c5f58eeb61a454d52c"
        )

    def test_vector_three_get_without_query(self):
        canonical = build_canonical_request(
            client_id="ecommerce-web",
            timestamp="1760000200",
            nonce="a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
            method="GET",
            path="/api/v1/me/business-invitations/MI23456789AB/accept/",
            query_string="",
            body_sha256=EMPTY_BODY_SHA256,
        )

        assert compute_hmac_signature(DEMO_SECRET, canonical) == (
            "db4a311f9bf026d663dd1ca806c405e55f32c383fb8292345656ee8ba616fa84"
        )

    def test_same_request_signed_twice_is_identical(self):
        first = sign_request(
            secret=DEMO_SECRET,
            client_id="ecommerce-web",
            timestamp="1760000000",
            nonce="nonce-fixe",
            method="POST",
            path="/api/v1/businesses/",
            query_string="",
            body=b'{"a":1}',
        )
        second = sign_request(
            secret=DEMO_SECRET,
            client_id="ecommerce-web",
            timestamp="1760000000",
            nonce="nonce-fixe",
            method="POST",
            path="/api/v1/businesses/",
            query_string="",
            body=b'{"a":1}',
        )

        assert first == second

    def test_signature_changes_with_any_canonical_component(self):
        base = dict(
            secret=DEMO_SECRET,
            client_id="ecommerce-web",
            timestamp="1760000000",
            nonce="nonce-fixe",
            method="POST",
            path="/api/v1/businesses/",
            query_string="",
            body=b'{"a":1}',
        )
        reference = sign_request(**base)[0]

        for field, value in (
            ("client_id", "ecommerce-other"),
            ("timestamp", "1760000001"),
            ("nonce", "autre-nonce"),
            ("method", "PUT"),
            ("path", "/api/v1/businesses/other/"),
            ("query_string", "page=2"),
            ("body", b'{"a":2}'),
        ):
            assert sign_request(**{**base, field: value})[0] != reference


class TestHeaders:
    """The six headers must be read and validated from the request."""

    def test_all_six_headers_are_named(self):
        assert EcommerceHMACHeaders.all() == (
            "X-Ecommerce-Client-Id",
            "X-Ecommerce-Timestamp",
            "X-Ecommerce-Nonce",
            "X-Ecommerce-Content-SHA256",
            "X-Ecommerce-Signature-Version",
            "X-Ecommerce-Signature",
        )

    def test_read_normalises_values(self, rf):
        request = rf.get(
            "/api/v1/protected/",
            HTTP_X_ECOMMERCE_CLIENT_ID=" ecommerce-web ",
            HTTP_X_ECOMMERCE_TIMESTAMP="1760000000",
            HTTP_X_ECOMMERCE_NONCE="nonce",
            HTTP_X_ECOMMERCE_CONTENT_SHA256=EMPTY_BODY_SHA256,
            HTTP_X_ECOMMERCE_SIGNATURE_VERSION="v1",
            HTTP_X_ECOMMERCE_SIGNATURE="abc",
        )

        headers = EcommerceHMACHeaders.read(request)

        assert headers.client_id == "ecommerce-web"
        assert headers.timestamp == "1760000000"
        assert headers.signature == "abc"
        assert EcommerceHMACHeaders.complete(headers)

    def test_complete_is_false_when_a_header_is_missing(self, rf):
        request = rf.get("/api/v1/protected/", HTTP_X_ECOMMERCE_CLIENT_ID="web")

        headers = EcommerceHMACHeaders.read(request)

        assert not EcommerceHMACHeaders.complete(headers)

    def test_empty_values_are_not_complete(self, rf):
        request = rf.get(
            "/api/v1/protected/",
            HTTP_X_ECOMMERCE_CLIENT_ID="",
            HTTP_X_ECOMMERCE_TIMESTAMP="",
            HTTP_X_ECOMMERCE_NONCE="",
            HTTP_X_ECOMMERCE_CONTENT_SHA256="",
            HTTP_X_ECOMMERCE_SIGNATURE_VERSION="",
            HTTP_X_ECOMMERCE_SIGNATURE="",
        )

        headers = EcommerceHMACHeaders.read(request)

        assert not EcommerceHMACHeaders.complete(headers)


class TestTimestampWindow:
    """The clock tolerance must be symmetric and bounded."""

    def test_current_time_is_valid(self):
        import time

        assert timestamp_is_valid(int(time.time()), max_clock_skew_seconds=120)

    def test_boundary_inside_is_valid(self):
        import time

        now = int(time.time())
        assert timestamp_is_valid(now - 120, max_clock_skew_seconds=120)
        assert timestamp_is_valid(now + 120, max_clock_skew_seconds=120)

    def test_boundary_outside_is_invalid(self):
        import time

        now = int(time.time())
        assert not timestamp_is_valid(now - 121, max_clock_skew_seconds=120)
        assert not timestamp_is_valid(now + 121, max_clock_skew_seconds=120)

    def test_non_integer_timestamp_is_invalid(self):
        assert not timestamp_is_valid("", max_clock_skew_seconds=120)
        assert not timestamp_is_valid("abc", max_clock_skew_seconds=120)
        assert not timestamp_is_valid(None, max_clock_skew_seconds=120)
