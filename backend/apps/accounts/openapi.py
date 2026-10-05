"""OpenAPI extensions for the ecommerce authentication boundary."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class EcommerceJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    """Describe local ecommerce JWTs without changing runtime authentication.

    ``EcommerceJWTAuthentication`` resolves a Carri identity from an ecommerce
    access token. drf-spectacular needs this extension to render the Swagger
    Bearer-token Authorize control for that custom DRF authentication class.
    """

    target_class = "apps.accounts.authentication.EcommerceJWTAuthentication"
    name = "EcommerceJWT"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
