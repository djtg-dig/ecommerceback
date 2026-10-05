"""Public identifiers are random, opaque references; they are never authorizations."""
import secrets
ALPHABET="23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
def generate_business_public_id():
    """Return a cryptographically random SH reference with 32^10 possible suffixes."""
    return "SH"+"".join(secrets.choice(ALPHABET) for _ in range(10))
