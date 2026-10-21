import uuid

from django.conf import settings
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from .models import CarriIdentity


class UserPreferencesSerializer(serializers.ModelSerializer):
    """Expose exclusivement les préférences propres à l'identité connectée."""

    preferred_language = serializers.ChoiceField(
        choices=CarriIdentity.PreferredLanguage.choices,
        allow_blank=True,
        required=False,
    )

    class Meta:
        model = CarriIdentity
        fields = ("preferred_language",)


class EcommerceTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh tokens issued for the local Carri identity projection.

    SimpleJWT's default serializer resolves its subject through Django's
    configured auth user model. Ecommerce tokens intentionally use the UUID
    primary key of ``CarriIdentity`` instead, so resolve that claim explicitly.
    The ``RefreshToken`` constructor remains responsible for signature, token
    type and expiration validation.
    """

    default_error_messages = {
        "identity_missing": "Ecommerce identity claim is missing.",
        "identity_invalid": "Ecommerce identity claim is invalid.",
        "identity_not_found": "Ecommerce identity not found.",
        "no_active_account": "No active account found for the given token.",
    }

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        identity_id = refresh.payload.get(settings.ECOMMERCE_IDENTITY_CLAIM)
        if not identity_id:
            raise AuthenticationFailed(self.error_messages["identity_missing"], "identity_missing")

        try:
            identity_uuid = uuid.UUID(str(identity_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise AuthenticationFailed(self.error_messages["identity_invalid"], "identity_invalid") from exc

        try:
            identity = CarriIdentity.objects.get(pk=identity_uuid)
        except CarriIdentity.DoesNotExist as exc:
            raise AuthenticationFailed(self.error_messages["identity_not_found"], "identity_not_found") from exc

        if not api_settings.USER_AUTHENTICATION_RULE(identity):
            raise AuthenticationFailed(self.error_messages["no_active_account"], "no_active_account")
        if refresh.payload.get("session_version") != identity.session_version:
            raise AuthenticationFailed("Ecommerce session has expired.", "session_expired")

        data = {"access": str(refresh.access_token)}
        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    refresh.blacklist()
                except AttributeError:
                    pass
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            refresh.outstand()
            data["refresh"] = str(refresh)

        return data
