from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import CarriCallbackView, CarriHandoffConsumeView, CarriLoginView, CarriMobileExchangeView, CurrentIdentityView

urlpatterns = [
    path("carri/mobile/exchange/", CarriMobileExchangeView.as_view(), name="carri-mobile-exchange"),
    path("carri/login/", CarriLoginView.as_view(), name="carri-login"),
    path("carri/callback/", CarriCallbackView.as_view(), name="carri-callback"),
    path("carri/handoff/consume/", CarriHandoffConsumeView.as_view(), name="carri-handoff-consume"),
    path("me/", CurrentIdentityView.as_view(), name="current-identity"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
]
