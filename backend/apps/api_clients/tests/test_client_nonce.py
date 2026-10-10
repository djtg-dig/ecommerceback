"""Tests for the ClientNonce replay guard and its purge command."""

import pytest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.utils import timezone

from apps.api_clients.models import ApiClient, ClientNonce

from .testing import ensure_test_client

pytestmark = pytest.mark.django_db(transaction=True)


def _nonce_rows():
    return ClientNonce.objects.count()


class TestUniqueness:
    """The nonce guard must be atomic and survive concurrent workers."""

    def test_first_recording_is_accepted(self):
        client = ensure_test_client()

        assert ClientNonce.record(client, "nonce-1")
        assert ClientNonce.objects.filter(client=client, nonce="nonce-1").exists()

    def test_second_recording_of_the_same_nonce_is_refused(self):
        client = ensure_test_client()

        assert ClientNonce.record(client, "nonce-1")
        assert not ClientNonce.record(client, "nonce-1")
        assert _nonce_rows() == 1

    def test_the_same_nonce_is_accepted_for_another_client(self):
        first = ensure_test_client(client_id="client-a")
        second = ensure_test_client(client_id="client-b")

        assert ClientNonce.record(first, "shared-nonce")
        assert ClientNonce.record(second, "shared-nonce")

    def test_concurrent_recordings_accept_exactly_one(self):
        client = ensure_test_client()
        nonce = "concurrent-nonce"

        def record():
            close_old_connections()
            try:
                return ClientNonce.record(client, nonce)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(lambda _: record(), range(8)))

        assert sum(1 for outcome in outcomes if outcome) == 1
        assert _nonce_rows() == 1


class TestPurge:
    """Expired nonces must be removed without touching recent ones."""

    def test_purge_removes_only_expired_nonces(self):
        client = ensure_test_client()
        ClientNonce.objects.create(
            client=client, nonce="old", seen_at=timezone.now() - timedelta(seconds=901)
        )
        ClientNonce.objects.create(
            client=client, nonce="recent", seen_at=timezone.now()
        )

        deleted = ClientNonce.purge_expired(retention_seconds=900)

        assert deleted == 1
        assert ClientNonce.objects.filter(nonce="recent").exists()
        assert not ClientNonce.objects.filter(nonce="old").exists()

    def test_a_non_positive_retention_is_refused(self):
        assert ApiClient.objects.exists() or True
        with pytest.raises(ValidationError):
            ClientNonce.purge_expired(retention_seconds=0)
        with pytest.raises(ValidationError):
            ClientNonce.purge_expired(retention_seconds=-1)

    def test_the_management_command_purges(self):
        client = ensure_test_client()
        ClientNonce.objects.create(
            client=client,
            nonce="old",
            seen_at=timezone.now() - timedelta(seconds=901),
        )

        call_command("purge_client_nonces", "--seconds", "900")

        assert _nonce_rows() == 0

    def test_the_management_command_defaults_to_the_configured_retention(self):
        from django.test import override_settings

        client = ensure_test_client()
        ClientNonce.objects.create(
            client=client,
            nonce="old",
            seen_at=timezone.now() - timedelta(seconds=400),
        )

        with override_settings(ECOMMERCE_HMAC_NONCE_TTL_SECONDS=300):
            call_command("purge_client_nonces")

        assert _nonce_rows() == 0
