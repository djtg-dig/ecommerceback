import uuid

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import CarriIdentity


class EcommerceJWTAuthentication(JWTAuthentication):
    """Authenticates ecommerce tokens against the local Carri identity projection."""

    def get_user(self, validated_token):
        identity_id = validated_token.get(settings.ECOMMERCE_IDENTITY_CLAIM)
        if not identity_id:
            raise AuthenticationFailed("Ecommerce identity claim is missing.", code="identity_missing")
        try:
            identity_uuid = uuid.UUID(str(identity_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise AuthenticationFailed("Ecommerce identity claim is invalid.", code="identity_invalid") from exc
        try:
            return CarriIdentity.objects.get(pk=identity_uuid)
        except CarriIdentity.DoesNotExist as exc:
            raise AuthenticationFailed("Ecommerce identity not found.", code="identity_not_found") from exc
