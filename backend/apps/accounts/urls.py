from django.urls import path
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer


class EcommerceTokenRefreshView(TokenRefreshView):
    """Refresh an ecommerce token pair without documenting any provider secret."""

    post = extend_schema(
        tags=["Authentication"], operation_id="ecommerce_token_refresh",
        request=TokenRefreshSerializer, responses={200: inline_serializer("EcommerceTokenRefreshResponse", {"access": serializers.CharField(read_only=True), "refresh": serializers.CharField(read_only=True)}), 401: None},
    )(TokenRefreshView.post)


from .views import CarriCallbackView, CarriHandoffConsumeView, CarriLoginView, CarriMobileExchangeView, CurrentIdentityView

urlpatterns = [
    path("carri/mobile/exchange/", CarriMobileExchangeView.as_view(), name="carri-mobile-exchange"),
    path("carri/login/", CarriLoginView.as_view(), name="carri-login"),
    path("carri/callback/", CarriCallbackView.as_view(), name="carri-callback"),
    path("carri/handoff/consume/", CarriHandoffConsumeView.as_view(), name="carri-handoff-consume"),
    path("me/", CurrentIdentityView.as_view(), name="current-identity"),
    path("token/refresh/", EcommerceTokenRefreshView.as_view(), name="token-refresh"),
]
