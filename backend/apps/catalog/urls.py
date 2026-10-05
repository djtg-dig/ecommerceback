"""Routes for public catalog metadata."""

from django.urls import path

from .views import ProductCategoryAttributesView, ProductCategoryListView

urlpatterns = [
    path("", ProductCategoryListView.as_view(), name="product-category-list"),
    path("<str:code>/attributes/", ProductCategoryAttributesView.as_view(), name="product-category-attributes"),
]
