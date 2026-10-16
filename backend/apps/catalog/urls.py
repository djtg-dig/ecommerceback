"""Routes for public catalog metadata."""

from django.urls import path

from .views import (
    ProductCategoryAttributesView,
    ProductCategoryListView,
    ProductCategoryRegistryDetailView,
    ProductCategoryRegistryListView,
)

urlpatterns = [
    path("", ProductCategoryListView.as_view(), name="product-category-list"),
    path("registry/", ProductCategoryRegistryListView.as_view(), name="product-category-registry-list"),
    path(
        "registry/<str:code>/",
        ProductCategoryRegistryDetailView.as_view(),
        name="product-category-registry-detail",
    ),
    path("<str:code>/attributes/", ProductCategoryAttributesView.as_view(), name="product-category-attributes"),
]
