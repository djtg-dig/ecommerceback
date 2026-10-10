"""Opaque public identifiers for registered client applications."""

import secrets

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PUBLIC_ID_SUFFIX_LENGTH = 10


def generate_public_id(prefix: str, length: int = PUBLIC_ID_SUFFIX_LENGTH) -> str:
    """Return a cryptographically random opaque identifier with ``prefix``."""
    return prefix + "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_api_client_public_id():
    """Return the opaque public reference ``ACXXXXXXXXXX`` of a client application."""
    return generate_public_id("AC")
