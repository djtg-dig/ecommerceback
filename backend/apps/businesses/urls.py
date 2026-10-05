from django.urls import path
from .views import BusinessesView,BusinessDetailView,BusinessMembersView
urlpatterns=[path("",BusinessesView.as_view()),path("<uuid:pk>/",BusinessDetailView.as_view()),path("<uuid:pk>/members/",BusinessMembersView.as_view())]
