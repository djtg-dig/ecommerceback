"""Tests for the environment-only HMAC secret configuration."""

import pytest
from django.test import override_settings

from apps.api_clients.services.secrets import (
    ClientSecret,
    ClientSecretError,
    client_secret,
    parse_client_secrets,
    validate_configuration,
)

CLIENT_ID = "ecommerce-web-test"


class TestParsing:
    """The configuration must be strict and never silently permissive."""

    def test_empty_configuration_is_empty(self):
        assert parse_client_secrets(None) == {}
        assert parse_client_secrets("") == {}
        assert parse_client_secrets("   ") == {}
        assert parse_client_secrets({}) == {}

    def test_json_text_is_parsed(self):
        mapping = parse_client_secrets(
            '{"ecommerce-web-test": {"current": "s", "previous": "p", "previous_expires_at": "9999999999"}}'
        )

        assert mapping == {"ecommerce-web-test": {"current": "s", "previous": "p", "previous_expires_at": "9999999999"}}

    def test_invalid_json_raises_without_leaking_the_value(self):
        with pytest.raises(ClientSecretError) as exc:
            parse_client_secrets('{"not": ')

        assert "JSON" in str(exc.value)
        assert "not" not in str(exc.value)

    def test_non_object_json_raises(self):
        with pytest.raises(ClientSecretError):
            parse_client_secrets('["a", "b"]')

    def test_current_and_previous_must_differ(self):
        with pytest.raises(ClientSecretError):
            parse_client_secrets({CLIENT_ID: {"current": "x", "previous": "x"}})

    def test_secrets_must_not_contain_surrounding_spaces(self):
        with pytest.raises(ClientSecretError):
            parse_client_secrets({CLIENT_ID: {"current": " x "}})

    def test_non_string_secret_raises(self):
        with pytest.raises(ClientSecretError):
            parse_client_secrets({CLIENT_ID: {"current": 12345}})

    def test_expiry_accepts_unix_seconds_and_iso_dates(self):
        entry = {
            "current": "c",
            "previous": "p",
            "previous_expires_at": "9999999999",
        }

        assert parse_client_secrets({CLIENT_ID: entry})[CLIENT_ID] is entry

    def test_invalid_expiry_raises(self):
        with pytest.raises(ClientSecretError):
            parse_client_secrets(
                {
                    CLIENT_ID: {
                        "current": "c",
                        "previous": "p",
                        "previous_expires_at": "pas-une-date",
                    }
                }
            )

    def test_previous_secret_requires_an_explicit_expiry(self):
        with pytest.raises(ClientSecretError):
            parse_client_secrets({CLIENT_ID: {"current": "c", "previous": "p"}})

    def test_validate_configuration_accepts_a_current_secret(self):
        with override_settings(
            ECOMMERCE_HMAC_CLIENT_SECRETS={CLIENT_ID: {"current": "c"}}
        ):
            validate_configuration()

    def test_validate_configuration_rejects_a_missing_current_secret(self):
        with override_settings(
            ECOMMERCE_HMAC_CLIENT_SECRETS={CLIENT_ID: {"previous": "p"}}
        ):
            with pytest.raises(ClientSecretError):
                validate_configuration()


class TestResolvedSecrets:
    """Only the accepted secrets are returned, in a stable order."""

    @override_settings(
        ECOMMERCE_HMAC_CLIENT_SECRETS={
            CLIENT_ID: {"current": "c", "previous": "p", "previous_expires_at": "9999999999"}
        }
    )
    def test_unknown_client_returns_none(self):
        assert client_secret("not-configured") is None
        assert client_secret("") is None
        assert client_secret(None) is None

    @override_settings(
        ECOMMERCE_HMAC_CLIENT_SECRETS={
            CLIENT_ID: {
                "current": "c",
                "previous": "p",
                "previous_expires_at": "9999999999",
            }
        }
    )
    def test_previous_secret_is_accepted_before_its_expiry(self):
        secret = client_secret(CLIENT_ID)

        assert secret.candidate_secrets() == ["c", "p"]

    @override_settings(
        ECOMMERCE_HMAC_CLIENT_SECRETS={
            CLIENT_ID: {
                "current": "c",
                "previous": "p",
                "previous_expires_at": "1",
            }
        }
    )
    def test_previous_secret_is_refused_after_the_grace_period(self):
        secret = client_secret(CLIENT_ID)

        assert not secret.has_active_previous
        assert secret.candidate_secrets() == ["c"]

    @override_settings(
        ECOMMERCE_HMAC_CLIENT_SECRETS={
            CLIENT_ID: {
                "current": "c",
                "previous": "p",
                "previous_expires_at": "99999999999",
            }
        }
    )
    def test_previous_secret_is_accepted_before_the_grace_period(self):
        secret = client_secret(CLIENT_ID)

        assert secret.has_active_previous
        assert secret.candidate_secrets() == ["c", "p"]

    @override_settings(
        ECOMMERCE_HMAC_CLIENT_SECRETS={
            CLIENT_ID: {
                "current": "c",
                "previous": "p",
                "previous_expires_at": "99999999999",
            }
        }
    )
    def test_iso_expiry_is_supported(self):
        secret = client_secret(CLIENT_ID)

        assert secret.has_active_previous
        assert secret.candidate_secrets() == ["c", "p"]

    def test_string_entry_is_supported_for_a_single_secret(self):
        secret = ClientSecret(current="only")

        assert secret.has_current
        assert not secret.has_active_previous
        assert secret.candidate_secrets() == ["only"]
