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


def generate_inventory_item_public_id() -> str:
    """Return an ``IV`` inventory-item identifier."""
    return generate_public_id("IV")


def generate_stock_movement_public_id() -> str:
    """Return an ``SM`` immutable stock-movement identifier."""
    return generate_public_id("SM")


def generate_supplier_public_id(): return generate_public_id("SP")
def generate_purchase_public_id(): return generate_public_id("PU")
def generate_purchase_line_public_id(): return generate_public_id("PL")

def generate_customer_public_id(): return generate_public_id("CU")
def generate_sale_public_id(): return generate_public_id("SA")
def generate_sale_line_public_id(): return generate_public_id("SL")
