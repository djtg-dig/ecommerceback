from apps.businesses.identifiers import generate_public_id


def generate_financial_movement_public_id():
    """Return an opaque FM identifier using the project-wide secure generator."""
    return generate_public_id("FM")


def generate_payment_transaction_public_id():
    """Return an opaque informational payment transaction identifier."""
    return generate_public_id("PT")
