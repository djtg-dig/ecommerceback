"""OpenAPI security requirements for the HMAC-protected routes.

DRF derives an operation security requirement from its authentication classes,
which cannot express a middleware-enforced application signature. These
constants keep the published contract aligned with the enforcement policy.

A requirement is a list of objects where each object lists the schemes that
must *all* be satisfied. Listing both schemes in one object means JWT **and**
HMAC; listing them in two separate objects would express an alternative, i.e.
either one alone would be enough.
"""

# Only the application signature, used by an anonymous BFF route that returns
# the JWT pair.
HMAC_ONLY = ({"EcommerceClientHMAC": []},)

# The user JWT and the application signature together.
JWT_AND_HMAC = ({"EcommerceJWT": [], "EcommerceClientHMAC": []},)

# The user JWT alone, for the routes still reachable by every platform.
JWT_ONLY = ({"EcommerceJWT": []},)


def described(requirements):
    """Return one schema description line for a set of requirements."""

    if requirements == HMAC_ONLY:
        return "Exige la signature HMAC du client applicatif (client_id ecommerce-web)."
    if requirements == JWT_AND_HMAC:
        return (
            "Exige un JWT ecommerce valide et la signature HMAC du client "
            "applicatif. Les deux sont obligatoires simultanement."
        )
    return "Exige un JWT ecommerce valide."
