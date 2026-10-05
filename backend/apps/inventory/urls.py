"""Tenant inventory routes."""

from django.urls import path

from .views import InventoryDetailView, InventoryListCreateView, StockMovementListCreateView

urlpatterns = [
    path("", InventoryListCreateView.as_view(), name="inventory-list-create"),
    path("<str:inventory_public_id>/", InventoryDetailView.as_view(), name="inventory-detail"),
    path("<str:inventory_public_id>/movements/", StockMovementListCreateView.as_view(), name="stock-movement-list-create"),
]
