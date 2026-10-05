"""Business routes scoped to the authenticated identity."""

from django.urls import path

from .views import BusinessDetailView, BusinessMembersView, BusinessesView

urlpatterns = [
    path("", BusinessesView.as_view()),
    path("<str:public_id>/", BusinessDetailView.as_view()),
    path("<str:public_id>/members/", BusinessMembersView.as_view()),
]
