"""Opaque public identifiers used by client-facing APIs."""

import secrets

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PUBLIC_ID_SUFFIX_LENGTH = 10


def generate_public_id(prefix: str, length: int = PUBLIC_ID_SUFFIX_LENGTH) -> str:
    """Return a cryptographically random opaque identifier with ``prefix``.

    The database unique constraint remains authoritative; creation services retry a
    bounded number of times if an extremely unlikely collision occurs.
    """
    return prefix + "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_business_public_id() -> str:
    """Return an ``SH`` business identifier."""
    return generate_public_id("SH")


def generate_product_public_id() -> str:
    """Return a ``PR`` product identifier."""
    return generate_public_id("PR")


def generate_product_variant_public_id() -> str:
    """Return a ``PV`` product-variant identifier."""
    return generate_public_id("PV")
