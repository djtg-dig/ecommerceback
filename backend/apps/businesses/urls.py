"""Business routes scoped to the authenticated identity."""

from django.urls import path

from .views import (BusinessDetailView, BusinessMemberDetailView, BusinessMembersView, BusinessesView, BusinessPaymentMethodsView, BusinessPaymentMethodDetailView)

urlpatterns = [
    path("", BusinessesView.as_view()),
    path("<str:public_id>/", BusinessDetailView.as_view()),
    path("<str:public_id>/members/", BusinessMembersView.as_view()),
    path("<str:public_id>/members/<str:member_public_id>/", BusinessMemberDetailView.as_view()),
    path("<str:public_id>/payment-methods/", BusinessPaymentMethodsView.as_view()),
    path("<str:public_id>/payment-methods/<str:method_public_id>/", BusinessPaymentMethodDetailView.as_view()),
]
