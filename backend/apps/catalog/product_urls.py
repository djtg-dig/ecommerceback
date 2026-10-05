"""Tenant-scoped product and variant routes."""

from django.urls import path

from .views import ProductArchiveView, ProductDetailView, ProductListCreateView, ProductVariantDetailView, ProductVariantListCreateView

urlpatterns = [
    path("", ProductListCreateView.as_view(), name="product-list-create"),
    path("<str:product_public_id>/", ProductDetailView.as_view(), name="product-detail"),
    path("<str:product_public_id>/archive/", ProductArchiveView.as_view(), name="product-archive"),
    path("<str:product_public_id>/variants/", ProductVariantListCreateView.as_view(), name="product-variant-list-create"),
    path("<str:product_public_id>/variants/<str:variant_public_id>/", ProductVariantDetailView.as_view(), name="product-variant-detail"),
]
