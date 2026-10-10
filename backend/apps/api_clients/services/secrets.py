"""Environment-only HMAC secret configuration.

Secrets never enter the database, the repository, the logs or an API response.
Only this module reads them, and only at verification time.
"""

import json
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError


class ClientSecretError(ValidationError):
    """Raised when the configured HMAC secret material is unusable."""


@dataclass(frozen=True)
class ClientSecret:
    """The current secret of one client plus an optional previous one."""

    current: str = ""
    previous: str = ""
    previous_expires_at: object = None

    @property
    def has_current(self):
        return bool(self.current)

    @property
    def has_active_previous(self):
        """Return whether the previous secret is still inside its grace period.

        A previous secret always needs an explicit expiry. This bounds the
        rotation window if a deployment is delayed or abandoned.
        """

        if not self.previous:
            return False
        if self.previous_expires_at is None:
            return False
        if hasattr(self.previous_expires_at, "tzinfo"):
            from django.utils import timezone

            return timezone.now() < self.previous_expires_at
        return _now() < self.previous_expires_at

    def candidate_secrets(self):
        """Return the secrets accepted for verification, current first."""

        candidates = [self.current]
        if self.has_active_previous:
            candidates.append(self.previous)
        return [secret for secret in candidates if secret]


def _now():
    import time

    return time.time()


def parse_expires_at(raw):
    """Return an aware datetime or a Unix timestamp from a raw value."""

    if not raw:
        return None

    if hasattr(raw, "tzinfo"):
        return raw

    if isinstance(raw, (int, float)):
        return float(raw)

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.lstrip("+-").isdigit():
            return float(text)
        from django.utils import timezone
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(text)
        if parsed is None:
            raise ClientSecretError(
                "ECOMMERCE_HMAC_PREVIOUS_SECRET_EXPIRES_AT doit etre un "
                "horodatage Unix ou une date ISO 8601."
            )
        if parsed.tzinfo is None:
            parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
        return parsed

    raise ClientSecretError(
        "ECOMMERCE_HMAC_PREVIOUS_SECRET_EXPIRES_AT doit etre une chaine."
    )


def parse_client_secrets(raw):
    """Parse and strictly validate the client secret configuration.

    Every entry is normalised while parsing, so a malformed rotation or an
    unusable secret fails when the application starts instead of at the first
    signed request. The returned mapping contains no secret value.
    """

    mapping = _read_client_secrets_mapping(raw)

    for client_id, entry in list(mapping.items()):
        normalized = normalize_entry(client_id, entry)
        if not normalized.has_current:
            raise ClientSecretError(
                f"Aucun secret HMAC courant n'est configure pour {client_id}."
            )
        mapping[client_id] = entry
    return mapping


def _read_client_secrets_mapping(raw):
    """Return the raw client secret mapping from a mapping or JSON text."""

    if not raw:
        return {}

    if isinstance(raw, dict):
        return raw

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClientSecretError(
                "ECOMMERCE_HMAC_CLIENT_SECRETS doit etre un objet JSON valide."
            ) from exc
        if not isinstance(parsed, dict):
            raise ClientSecretError(
                "ECOMMERCE_HMAC_CLIENT_SECRETS doit etre un objet JSON valide."
            )
        return parsed

    raise ClientSecretError(
        "ECOMMERCE_HMAC_CLIENT_SECRETS doit etre un objet JSON valide."
    )


def normalize_entry(client_id, entry):
    """Return one validated ``ClientSecret`` for a configured client."""

    if isinstance(entry, str):
        current, previous, expires = entry, "", None
    elif isinstance(entry, dict):
        current = entry.get("current") or entry.get("secret") or ""
        previous = entry.get("previous") or entry.get("previous_secret") or ""
        expires = entry.get("previous_expires_at")
    else:
        raise ClientSecretError(
            f"Configuration HMAC invalide pour {client_id}."
        )

    if not isinstance(current, str) or not isinstance(previous, str):
        raise ClientSecretError(
            f"Les secrets HMAC de {client_id} doivent etre des chaines."
        )

    if current.strip() != current or previous.strip() != previous:
        raise ClientSecretError(
            f"Les secrets HMAC de {client_id} ne doivent pas contenir "
            "d'espaces superflus."
        )

    if current and previous and current == previous:
        raise ClientSecretError(
            f"Le secret HMAC courant et precedent de {client_id} doivent differer."
        )

    if previous and expires in (None, ""):
        raise ClientSecretError(
            f"Le secret HMAC precedent de {client_id} exige "
            "previous_expires_at."
        )

    return ClientSecret(
        current=current,
        previous=previous,
        previous_expires_at=parse_expires_at(expires),
    )


def client_secret(client_id):
    """Return the configured ``ClientSecret`` of one client, or ``None``.

    ``None`` means the caller is not configured and is reported to the client
    as an unknown client, so a missing key is indistinguishable from an
    unknown one and cannot be used to enumerate configured clients.
    """

    if not client_id or not isinstance(client_id, str):
        return None

    mapping = parse_client_secrets(
        getattr(settings, "ECOMMERCE_HMAC_CLIENT_SECRETS", {})
    )

    if client_id not in mapping:
        return None
    return normalize_entry(client_id, mapping[client_id])


def validate_configuration():
    """Raise ``ClientSecretError`` when any configured material is unusable."""

    parse_client_secrets(
        getattr(settings, "ECOMMERCE_HMAC_CLIENT_SECRETS", {})
    )
