"""Business routes scoped to the authenticated identity."""

from django.urls import path

from .views import (
    BusinessDetailView,
    BusinessInvitationResendView,
    BusinessInvitationRevokeView,
    BusinessInvitationsView,
    BusinessMemberDetailView,
    BusinessMemberPermissionDetailView,
    BusinessMemberPermissionGrantView,
    BusinessMemberReactivateView,
    BusinessMemberSuspendView,
    BusinessMembersView,
    BusinessPaymentMethodDetailView,
    BusinessPaymentMethodsView,
    BusinessPermissionCatalogView,
    BusinessesView,
)

urlpatterns = [
    path("", BusinessesView.as_view()),
    path("<str:public_id>/", BusinessDetailView.as_view()),
    path("<str:public_id>/members/", BusinessMembersView.as_view()),
    path("<str:public_id>/invitations/", BusinessInvitationsView.as_view()),
    path(
        "<str:public_id>/invitations/<str:invitation_public_id>/resend/",
        BusinessInvitationResendView.as_view(),
    ),
    path(
        "<str:public_id>/invitations/<str:invitation_public_id>/revoke/",
        BusinessInvitationRevokeView.as_view(),
    ),
    path("<str:public_id>/members/<str:member_public_id>/", BusinessMemberDetailView.as_view()),
    path("<str:public_id>/members/<str:member_public_id>/suspend/", BusinessMemberSuspendView.as_view()),
    path("<str:public_id>/members/<str:member_public_id>/reactivate/", BusinessMemberReactivateView.as_view()),
    path("<str:public_id>/members/<str:member_public_id>/permissions/", BusinessMemberPermissionGrantView.as_view()),
    path("<str:public_id>/members/<str:member_public_id>/permissions/<str:permission>/", BusinessMemberPermissionDetailView.as_view()),
    path("<str:public_id>/permissions/", BusinessPermissionCatalogView.as_view()),
    path("<str:public_id>/payment-methods/", BusinessPaymentMethodsView.as_view()),
    path("<str:public_id>/payment-methods/<str:method_public_id>/", BusinessPaymentMethodDetailView.as_view()),
]
