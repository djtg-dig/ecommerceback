"""Opaque public identifiers used by client-facing APIs."""

import secrets

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PUBLIC_ID_SUFFIX_LENGTH = 10


def generate_public_id(prefix: str, length: int = PUBLIC_ID_SUFFIX_LENGTH) -> str:
    """Return a cryptographically random opaque identifier with ``prefix``."""
    return prefix + "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_business_public_id(): return generate_public_id("SH")
def generate_product_public_id(): return generate_public_id("PR")
def generate_product_variant_public_id(): return generate_public_id("PV")
def generate_inventory_item_public_id(): return generate_public_id("IV")
def generate_stock_movement_public_id(): return generate_public_id("SM")
def generate_supplier_public_id(): return generate_public_id("SP")
def generate_purchase_public_id(): return generate_public_id("PU")
def generate_purchase_line_public_id(): return generate_public_id("PL")
def generate_customer_public_id(): return generate_public_id("CU")
def generate_sale_public_id(): return generate_public_id("SA")
def generate_sale_line_public_id(): return generate_public_id("SL")
def generate_receivable_public_id(): return generate_public_id("RC")
def generate_receivable_payment_public_id(): return generate_public_id("RP")
def generate_expense_category_public_id(): return generate_public_id("EC")
def generate_expense_public_id(): return generate_public_id("EX")
def generate_expense_payment_public_id(): return generate_public_id("EP")
def generate_supplier_payment_public_id(): return generate_public_id("PP")
def generate_business_payment_method_public_id(): return generate_public_id("PM")
