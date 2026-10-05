from django.urls import path
from .views import BusinessesView,BusinessDetailView,BusinessMembersView,BusinessCategoriesView
urlpatterns=[path("",BusinessesView.as_view()),path("<str:p>/",BusinessDetailView.as_view()),path("<str:p>/members/",BusinessMembersView.as_view()),path("../business-categories/",BusinessCategoriesView.as_view())]
